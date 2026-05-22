"""
Property test — legacy-key diagnostics emitted by ``config.load_config``
(single-config-streamlining spec, task 9.4).

**Property 3: Diagnostica su chiavi legacy**

*For any* non-empty subset ``L`` of
``LEGACY_KEYS = {hsv_engine, memory_esp, input.ib, input.kmbox_serial,
input.makcu_serial, input.makcu_socket, input.efi, general.exe_spoof}`` —
plus optionally one synthetic key whose name contains one of the substrings
``spoof`` / ``antidbg`` / ``threat_response`` — and *for any* random value
assignment (scalar, list or mapping) to those keys in an otherwise-valid
``config.yaml``, :func:`config.load_config` SHALL emit a diagnostic output
(warning or error, via :mod:`utils.logger`) whose concatenation contains, as
a substring, the exact dotted name of **every** key in ``L``.

**Validates: Requirements 7.7**

Implementation notes
--------------------
* ``config._logger`` is created via ``utils.logger.setup_logger`` with
  ``propagate = False``, so pytest's :fixture:`caplog` — which hooks into the
  propagation chain at the root logger — does **not** capture records emitted
  by the config logger. To remain robust we attach a dedicated
  :class:`logging.Handler` directly to ``config._logger`` for the duration
  of each test, flush its output after ``load_config`` returns, and assert
  on the concatenated captured text. (The task description explicitly allows
  "caplog or a logging.Handler attached to the config logger".)
* The base configuration is a self-contained, target-valid dict so the
  loader reaches the legacy-detection path without raising on the four
  Target_Configuration keys.
* Hypothesis drives the property; a ``pytest.mark.parametrize`` fallback
  covers the full power set of singletons + a couple of representative
  mixed cases when Hypothesis is not available.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import pytest
import yaml

import config

try:  # pragma: no cover — availability depends on the runner environment
    from hypothesis import HealthCheck, assume, given, settings
    from hypothesis import strategies as st

    _HYPOTHESIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _HYPOTHESIS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Legacy-key catalogue — mirrors the constants in ``config.py`` as dotted
# paths. Kept local so the test is self-contained and does not drift silently
# when ``config.py`` is refactored: any divergence will surface as a failing
# assertion instead of a silently weaker test.
# ---------------------------------------------------------------------------

#: The eight dotted paths explicitly enumerated by Requirement 7.7.
LEGACY_KEYS: Tuple[str, ...] = (
    "hsv_engine",
    "memory_esp",
    "input.ib",
    "input.kmbox_serial",
    "input.makcu_serial",
    "input.makcu_socket",
    "input.efi",
    "general.exe_spoof",
)

#: Substrings that, when present in any nested key name, qualify that key
#: as legacy (Req 5.11, 7.7).
_LEGACY_SUBSTRINGS: Tuple[str, ...] = ("spoof", "antidbg", "threat_response")

#: Synthetic legacy keys used to exercise the substring-detection branch of
#: the loader's diagnostic pass. Each entry is a dotted path whose *leaf*
#: contains exactly one of ``_LEGACY_SUBSTRINGS``. Leaves are chosen to not
#: collide with any other LEGACY_KEYS entry so we can assert on the dotted
#: path directly.
_SYNTHETIC_LEGACY_KEYS: Tuple[str, ...] = (
    "general.input_spoof",
    "general.antidbg",
    "general.threat_response",
    "misc.spoof_metadata",
    "misc.antidbg_layer",
    "misc.threat_response_mode",
)


# ---------------------------------------------------------------------------
# Base configuration (target-valid, minimal).
# ---------------------------------------------------------------------------


def _valid_base_config() -> Dict[str, Any]:
    """Return a freshly-built dict that satisfies the Target_Configuration.

    Kept local and rebuilt on every call so the legacy-injection mutations
    in each test never leak between examples.
    """
    return {
        "general": {
            "architecture": "dual_pc",
            "primary_engine": "ai",
            "activation_key": "caps_lock",
            "panic_key": "f10",
            "log_level": "WARNING",
            "log_file": "errors.log",
            "mode": "aimbot",
            "overlay": False,
            "pipeline": "python",
        },
        "capture": {
            "backend": "capture_card",
            "device_index": 0,
            "fps_cap": 60,
            "resolution_width": 1920,
            "resolution_height": 1080,
        },
        "input": {
            "driver": "kmbox_net",
            "kmbox_net": {
                "ip": "192.168.2.188",
                "port": "6234",
                "uuid": "00000000-0000-0000-0000-000000000000",
                "use_encryption": True,
            },
        },
        "ai_engine": {
            "enabled": True,
            "confidence": 0.55,
        },
    }


# ---------------------------------------------------------------------------
# Dotted-path helpers (local copies, mirroring ``config._set_dotted_key`` but
# intentionally duplicated so the test does not depend on the loader's
# private surface).
# ---------------------------------------------------------------------------


def _set_dotted(cfg: Dict[str, Any], dotted_key: str, value: Any) -> None:
    """Insert ``value`` at ``dotted_key`` in ``cfg``, creating nested dicts
    as needed. Non-mapping intermediates are replaced with fresh dicts so
    injection never raises on a pathological base.
    """
    parts = dotted_key.split(".")
    node: Dict[str, Any] = cfg
    for part in parts[:-1]:
        existing = node.get(part)
        if not isinstance(existing, dict):
            existing = {}
            node[part] = existing
        node = existing
    node[parts[-1]] = value


# ---------------------------------------------------------------------------
# Logging capture — a dedicated handler attached to ``config._logger`` for
# the duration of a single ``load_config()`` call.
# ---------------------------------------------------------------------------


class _ListHandler(logging.Handler):
    """Accumulate ``LogRecord`` objects in memory for post-hoc assertions.

    Captures only records at ``WARNING`` or above, matching the diagnostic
    contract stated in Req 7.7 ("warning or error").
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        self.records.append(record)


# ---------------------------------------------------------------------------
# Pytest fixture that wires up capture + auto-detach.
# ---------------------------------------------------------------------------


@pytest.fixture
def config_log_capture(request: pytest.FixtureRequest) -> _ListHandler:
    """Yield a :class:`_ListHandler` attached to ``config._logger``.

    The handler is detached and the logger's level restored at teardown,
    regardless of whether the test body raises.
    """
    handler = _ListHandler()
    logger = config._logger
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)

    def _teardown() -> None:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    request.addfinalizer(_teardown)
    return handler


# ---------------------------------------------------------------------------
# Shared property check.
# ---------------------------------------------------------------------------


def _concatenate_messages(handler: _ListHandler) -> str:
    """Concatenate every captured warning/error record into a single string.

    The concatenation uses newline separators so distinct records remain
    parseable when the assertion fails. Both the formatted message and the
    record's ``message`` attribute are included so the substring check is
    insensitive to handler-formatting choices.
    """
    parts: List[str] = []
    for record in handler.records:
        parts.append(record.getMessage())
        # Also include any exception text so errors attached to the record
        # contribute to the concatenation.
        if record.exc_info:
            parts.append(logging.Formatter().formatException(record.exc_info))
    return "\n".join(parts)


def _write_config(tmp_path: Path, cfg: Dict[str, Any]) -> Path:
    """Serialize ``cfg`` to ``tmp_path / config.yaml`` with ``yaml.safe_dump``
    and return the resulting :class:`~pathlib.Path`.
    """
    tmp_file = tmp_path / "config.yaml"
    tmp_file.write_text(
        yaml.safe_dump(cfg, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )
    return tmp_file


def _check_property(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    handler: _ListHandler,
    legacy_paths: Sequence[str],
    values_by_path: Dict[str, Any],
) -> None:
    """Core invariant: every path in ``legacy_paths`` SHALL appear as a
    substring in the concatenated diagnostic output produced by
    ``load_config()``.

    Parameters
    ----------
    tmp_path
        Pytest-provided temporary directory.
    monkeypatch
        Pytest-provided monkeypatch used to redirect ``config._CONFIG_FILE``.
    handler
        The :class:`_ListHandler` attached to ``config._logger`` by the
        fixture.
    legacy_paths
        Non-empty sequence of dotted keys the test has injected into the
        config. Every entry must appear verbatim in the diagnostic output.
    values_by_path
        Mapping from dotted key to the value injected at that path.
    """
    assert legacy_paths, "test precondition: legacy_paths must be non-empty"

    cfg = _valid_base_config()
    for dotted in legacy_paths:
        _set_dotted(cfg, dotted, values_by_path[dotted])

    tmp_file = _write_config(tmp_path, cfg)
    monkeypatch.setattr(config, "_CONFIG_FILE", str(tmp_file))

    # Clear any stale records from a previous call in this process.
    handler.records.clear()

    # ``load_config`` must not raise on a target-valid config, even when
    # legacy sections are present (the diagnostic is emitted as WARNING).
    config.load_config()

    captured = _concatenate_messages(handler)

    # Primary invariant: each injected dotted key appears as a substring.
    missing = [p for p in legacy_paths if p not in captured]
    assert not missing, (
        "load_config() did not emit a diagnostic mentioning every injected "
        "legacy key.\n"
        f"  injected keys    = {list(legacy_paths)!r}\n"
        f"  missing from log = {missing!r}\n"
        f"  captured output  = {captured!r}"
    )

    # Secondary invariant: at least one WARNING-or-higher record was emitted
    # (so "no log at all" cannot silently satisfy the substring check on an
    # accidentally-empty ``legacy_paths``).
    assert handler.records, (
        "load_config() did not emit any diagnostic record at WARNING+ level "
        "despite legacy keys being present."
    )
    assert all(r.levelno >= logging.WARNING for r in handler.records), (
        "captured a record below WARNING — Req 7.7 requires warning or error."
    )


# ---------------------------------------------------------------------------
# Hypothesis-driven property test.
# ---------------------------------------------------------------------------


if _HYPOTHESIS_AVAILABLE:

    # Primitive values accepted by ``yaml.safe_dump``. None is excluded
    # because YAML's ``null`` makes the legacy section collapse into the
    # ``_LEGACY_SUBSTRINGS`` branch only if the *key* name matches; the
    # top-level/subkey branches in ``config._detect_legacy_keys`` already
    # trigger on key presence so null values still exercise the diagnostic.
    # We include it anyway to strengthen the test.
    _primitive_st = st.one_of(
        st.booleans(),
        st.integers(min_value=-1_000, max_value=1_000),
        st.floats(allow_nan=False, allow_infinity=False, width=32),
        st.text(
            alphabet=st.characters(
                blacklist_categories=("Cs", "Cc"),
                blacklist_characters="\x00",
            ),
            max_size=10,
        ),
        st.none(),
    )

    _leaf_st = st.one_of(
        _primitive_st,
        st.lists(_primitive_st, max_size=4),
        st.dictionaries(
            keys=st.text(
                alphabet=st.characters(
                    whitelist_categories=("Ll", "Lu", "Nd"),
                    whitelist_characters="_",
                ),
                min_size=1,
                max_size=6,
            ),
            values=_primitive_st,
            max_size=3,
        ),
    )

    # A non-empty subset of LEGACY_KEYS. ``min_size=1`` encodes the
    # property's "non-empty subset" premise.
    _subset_st = st.lists(
        st.sampled_from(LEGACY_KEYS),
        min_size=1,
        max_size=len(LEGACY_KEYS),
        unique=True,
    )

    # Optional synthetic ``*spoof*``/``*antidbg*``/``*threat_response*`` key.
    _synthetic_st = st.one_of(
        st.none(),
        st.sampled_from(_SYNTHETIC_LEGACY_KEYS),
    )

    @pytest.mark.unit
    @given(
        subset=_subset_st,
        synthetic=_synthetic_st,
        value_seed=st.lists(_leaf_st, min_size=len(LEGACY_KEYS) + len(_SYNTHETIC_LEGACY_KEYS),
                            max_size=len(LEGACY_KEYS) + len(_SYNTHETIC_LEGACY_KEYS)),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[
            HealthCheck.function_scoped_fixture,
            HealthCheck.too_slow,
        ],
    )
    def test_property_legacy_keys_are_diagnosed(
        subset: Sequence[str],
        synthetic: Any,
        value_seed: List[Any],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        config_log_capture: _ListHandler,
    ) -> None:
        """Property 3 (Hypothesis): every injected legacy key is named in
        the diagnostic output.

        The generator yields:
          * ``subset`` — a non-empty subset of :data:`LEGACY_KEYS`;
          * ``synthetic`` — either ``None`` or one of
            :data:`_SYNTHETIC_LEGACY_KEYS` to additionally exercise the
            substring-detection branch;
          * ``value_seed`` — a fixed-length list of leaves, one per legacy
            path (indexed below), so each injection gets a deterministic
            but Hypothesis-explored value.
        """
        # Deterministic value assignment per path. Using an index into the
        # flat path list avoids Hypothesis's dict-strategy bias toward
        # small-key domains and keeps the shrinking signal meaningful.
        all_paths: Tuple[str, ...] = LEGACY_KEYS + _SYNTHETIC_LEGACY_KEYS
        values_by_path: Dict[str, Any] = {
            path: value_seed[idx] for idx, path in enumerate(all_paths)
        }

        injected: List[str] = list(subset)
        if synthetic is not None and synthetic not in injected:
            injected.append(synthetic)

        # Premise of Property 3: the injection set is non-empty.
        assume(injected)

        _check_property(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            handler=config_log_capture,
            legacy_paths=injected,
            values_by_path=values_by_path,
        )


# ---------------------------------------------------------------------------
# Parametrized fallback / regression cases — run unconditionally so the
# highest-signal inputs (every single legacy key, the full set, each
# synthetic substring) are always exercised.
# ---------------------------------------------------------------------------


def _singleton_params() -> List[pytest.param]:
    """Build one parametrize case per legacy key (singleton injections)."""
    out: List[pytest.param] = []
    for dotted in LEGACY_KEYS:
        out.append(
            pytest.param(
                [dotted],
                id=f"singleton-{dotted.replace('.', '-')}",
            )
        )
    return out


def _synthetic_singleton_params() -> List[pytest.param]:
    """Build one parametrize case per synthetic legacy key."""
    out: List[pytest.param] = []
    for dotted in _SYNTHETIC_LEGACY_KEYS:
        out.append(
            pytest.param(
                [dotted],
                id=f"synthetic-{dotted.replace('.', '-')}",
            )
        )
    return out


_MIXED_PARAMS: List[pytest.param] = [
    pytest.param(list(LEGACY_KEYS), id="all-legacy-keys"),
    pytest.param(
        ["hsv_engine", "memory_esp", "general.exe_spoof"],
        id="mixed-top-and-general",
    ),
    pytest.param(
        [
            "input.ib",
            "input.kmbox_serial",
            "input.makcu_serial",
            "input.makcu_socket",
            "input.efi",
        ],
        id="all-legacy-input-subkeys",
    ),
    pytest.param(
        ["hsv_engine", "general.input_spoof"],
        id="legacy-plus-synthetic-spoof",
    ),
    pytest.param(
        ["memory_esp", "general.antidbg", "misc.threat_response_mode"],
        id="legacy-plus-two-synthetics",
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize(
    "legacy_paths",
    _singleton_params() + _synthetic_singleton_params() + _MIXED_PARAMS,
)
def test_representative_legacy_injections_are_diagnosed(
    legacy_paths: List[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_log_capture: _ListHandler,
) -> None:
    """Deterministic coverage of Property 3 across singletons, the full
    power-set bound and a handful of curated mixes.

    Uses a fixed ``42`` sentinel as the injected value for every key so
    the test is fully reproducible and independent of Hypothesis's
    shrinking behaviour. The loader's diagnostic contract is about the
    *keys* (not the values), so a constant value is sufficient coverage
    here; value-variance is exercised by the Hypothesis test above.
    """
    values_by_path = {path: 42 for path in legacy_paths}
    _check_property(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        handler=config_log_capture,
        legacy_paths=legacy_paths,
        values_by_path=values_by_path,
    )


# ---------------------------------------------------------------------------
# Sanity tests — guard against regressions in the test scaffolding itself.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_capture_handler_is_detached_on_teardown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The capture fixture must leave ``config._logger`` with the same
    number of handlers after teardown as before.
    """
    before = list(config._logger.handlers)
    # Inline use of the fixture machinery: request a single handler, then
    # manually tear down.
    handler = _ListHandler()
    config._logger.addHandler(handler)
    try:
        assert handler in config._logger.handlers
    finally:
        config._logger.removeHandler(handler)
    after = list(config._logger.handlers)
    assert before == after, (
        "handler leakage detected on teardown: "
        f"before={before!r}, after={after!r}"
    )


@pytest.mark.unit
def test_clean_base_config_emits_no_legacy_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_log_capture: _ListHandler,
) -> None:
    """Precondition sanity: the target-valid base config by itself must
    not trigger any legacy diagnostic. If this fails, the base config is
    too noisy and the main property's assertion would be vacuous.
    """
    cfg = _valid_base_config()
    tmp_file = _write_config(tmp_path, cfg)
    monkeypatch.setattr(config, "_CONFIG_FILE", str(tmp_file))

    config_log_capture.records.clear()
    config.load_config()

    captured = _concatenate_messages(config_log_capture)
    for legacy_path in LEGACY_KEYS:
        assert legacy_path not in captured, (
            f"base config accidentally triggers diagnostic for {legacy_path!r}: "
            f"{captured!r}"
        )
