"""
Property test — positive loading of target configurations
(single-config-streamlining spec).

**Property 1: Caricamento positivo di configurazioni target**

*For any* configuration ``config.yaml`` valid with respect to the
Target_Configuration (``general.architecture=dual_pc``,
``capture.backend=capture_card``, ``general.primary_engine=ai``,
``input.driver=kmbox_net``), including cases where any subset of those 4 keys
is absent from the file (defaults apply), :func:`config.load_config` SHALL
return — without raising — a dictionary in which each key of
``TARGET_CONFIGURATION`` is present and equal to its target value.

In addition, any arbitrary additional keys present in the source ``config.yaml``
SHALL be preserved in the returned dictionary.

**Validates: Requirements 2.7, 3.10, 3.12, 4.11, 7.1, 7.2, 7.3, 7.4, 7.6**

Implementation notes
--------------------
* Hypothesis strategies generate:
  - a subset of the 4 Target_Configuration keys to *omit* from the file (so
    the loader's default-application path is exercised);
  - an arbitrary collection of extra keys (primitives, lists, nested dicts)
    to verify preservation.
* The base file always contains a minimum ``input.kmbox_net`` section as
  required by the design (Req 7.5).
* Each test writes a YAML file to ``tmp_path`` and monkeypatches
  ``config._CONFIG_FILE`` so tests are fully isolated.
* When Hypothesis is not installed a ``pytest.mark.parametrize`` fallback
  covers ~20 representative cases that span the same input space.
"""

from __future__ import annotations

import copy
import os
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import pytest
import yaml

import config

try:  # pragma: no cover — availability depends on the runner environment
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st

    _HYPOTHESIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _HYPOTHESIS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Target_Configuration — mirrors config.TARGET_CONFIGURATION. Kept as a
# local tuple so the test does not depend on dict ordering semantics.
# ---------------------------------------------------------------------------

_TARGET_PAIRS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("general", "architecture"), "dual_pc"),
    (("capture", "backend"), "capture_card"),
    (("general", "primary_engine"), "ai"),
    (("input", "driver"), "kmbox_net"),
)

# Dotted paths exactly as used by ``config.TARGET_CONFIGURATION``.
_TARGET_DOTTED: Tuple[str, ...] = (
    "general.architecture",
    "capture.backend",
    "general.primary_engine",
    "input.driver",
)

# Top-level sections that belong to the base configuration. Extras generated
# by Hypothesis must not land on these names to avoid accidentally rewriting
# the target values (we test preservation of *additional* keys, not override
# semantics which are covered elsewhere).
_RESERVED_TOP_LEVEL: frozenset = frozenset(
    {"general", "capture", "input", "ai_engine"}
)


# ---------------------------------------------------------------------------
# Base valid configuration builder.
# ---------------------------------------------------------------------------


def _base_valid_config() -> Dict[str, Any]:
    """Return a deep copy of the minimum-valid Target_Configuration file.

    Includes all four target keys and the ``input.kmbox_net`` section with
    non-empty values, matching the shape required by Req 7.1–7.5.
    """
    return {
        "general": {
            "architecture": "dual_pc",
            "primary_engine": "ai",
        },
        "capture": {
            "backend": "capture_card",
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
# Dotted-path helpers (local — config.py keeps its helpers private).
# ---------------------------------------------------------------------------


def _set_path(d: Dict[str, Any], path: Sequence[str], value: Any) -> None:
    """Set a nested value at ``path`` inside ``d``, creating intermediates."""
    node: Dict[str, Any] = d
    for segment in path[:-1]:
        existing = node.get(segment)
        if not isinstance(existing, dict):
            existing = {}
            node[segment] = existing
        node = existing
    node[path[-1]] = value


def _get_path(d: Dict[str, Any], path: Sequence[str]) -> Any:
    """Fetch the value at ``path`` inside ``d``; return :data:`_MISSING` if
    absent.
    """
    node: Any = d
    for segment in path:
        if not isinstance(node, dict) or segment not in node:
            return _MISSING
        node = node[segment]
    return node


def _delete_path(d: Dict[str, Any], path: Sequence[str]) -> None:
    """Remove the value at ``path`` inside ``d``. Silently no-ops if absent."""
    node: Any = d
    for segment in path[:-1]:
        if not isinstance(node, dict) or segment not in node:
            return
        node = node[segment]
    if isinstance(node, dict):
        node.pop(path[-1], None)


_MISSING = object()


# ---------------------------------------------------------------------------
# Valid-config builder with optional omissions and extras overlay.
# ---------------------------------------------------------------------------


def _make_config_under_test(
    omit_indices: Sequence[int],
    extras: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    """Build a Target-valid config and apply omissions + extras.

    Args:
        omit_indices: Indexes into :data:`_TARGET_PAIRS` identifying which
            target keys should be removed from the file (so the loader must
            default them).
        extras: Arbitrary additional keys to overlay on top of the base
            config. Extras whose top-level key is reserved are dropped to
            keep the test focused on preservation of *additional* keys.

    Returns:
        ``(config_dict, omitted_dotted_paths)`` — the dict ready to write
        to YAML and the list of dotted paths actually removed.
    """
    cfg = _base_valid_config()

    omitted: List[str] = []
    for i in omit_indices:
        path, _expected = _TARGET_PAIRS[i]
        _delete_path(cfg, path)
        omitted.append(_TARGET_DOTTED[i])

    # Overlay extras, skipping reserved top-level keys.
    for top_key, top_value in extras.items():
        if top_key in _RESERVED_TOP_LEVEL:
            continue
        cfg[top_key] = copy.deepcopy(top_value)

    return cfg, omitted


# ---------------------------------------------------------------------------
# YAML I/O + monkeypatched loader invocation.
# ---------------------------------------------------------------------------


def _write_yaml(path: os.PathLike, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=True)


def _load_with_monkeypatched_path(
    monkeypatch: pytest.MonkeyPatch, tmp_file: os.PathLike
) -> Dict[str, Any]:
    """Call :func:`config.load_config` with ``_CONFIG_FILE`` pointing at
    ``tmp_file`` for per-test isolation.
    """
    monkeypatch.setattr(config, "_CONFIG_FILE", str(tmp_file))
    return config.load_config()


# ---------------------------------------------------------------------------
# Leaf iteration — used to verify that extras are preserved.
# ---------------------------------------------------------------------------


def _iter_leaves(
    node: Any, prefix: Tuple[str, ...] = ()
) -> Iterable[Tuple[Tuple[str, ...], Any]]:
    """Yield ``(path_tuple, value)`` for every leaf of a nested mapping."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _iter_leaves(value, prefix + (str(key),))
    else:
        yield prefix, node


# ---------------------------------------------------------------------------
# Core property assertion — shared by Hypothesis and fallback tests.
# ---------------------------------------------------------------------------


def _check_property(
    tmp_path, monkeypatch: pytest.MonkeyPatch, config_dict: Dict[str, Any]
) -> None:
    """Assert Property 1 on ``config_dict``.

    Procedure:
      1. Write ``config_dict`` to ``tmp_path/config.yaml``.
      2. Monkeypatch ``config._CONFIG_FILE`` and call ``load_config``.
      3. Assert the call does not raise.
      4. Assert every target key is present in the returned dict with its
         target value.
      5. Assert every extra leaf present in the source survives unchanged.
    """
    tmp_file = tmp_path / "config.yaml"
    _write_yaml(tmp_file, config_dict)

    # (1) — no exception expected.
    try:
        loaded = _load_with_monkeypatched_path(monkeypatch, tmp_file)
    except Exception as exc:  # pragma: no cover — failure path
        pytest.fail(
            f"load_config() raised {type(exc).__name__} on a valid "
            f"Target_Configuration: {exc!r}\nconfig={config_dict!r}"
        )

    # (2) — must be a dict.
    assert isinstance(loaded, dict), (
        f"load_config() returned {type(loaded).__name__}, expected dict"
    )

    # (3) — every target key is present with its target value, even if it
    # was omitted from the source file.
    for path, expected in _TARGET_PAIRS:
        got = _get_path(loaded, path)
        assert got is not _MISSING, (
            f"target key '{'.'.join(path)}' missing from loaded config "
            f"(source omitted={path not in {p for p, _ in _TARGET_PAIRS if _get_path(config_dict, p) is not _MISSING}})"
        )
        assert got == expected, (
            f"target key '{'.'.join(path)}' has value {got!r}, "
            f"expected {expected!r}"
        )

    # (4) — every leaf present in the source file (excluding the four
    # target keys, which are validated above) must survive unchanged.
    target_path_set = {path for path, _ in _TARGET_PAIRS}
    for leaf_path, leaf_value in _iter_leaves(config_dict):
        if leaf_path in target_path_set:
            continue
        got = _get_path(loaded, leaf_path)
        assert got == leaf_value, (
            f"extra key '{'.'.join(leaf_path)}' not preserved: "
            f"expected {leaf_value!r}, got {got!r}"
        )


# ---------------------------------------------------------------------------
# Hypothesis strategies.
# ---------------------------------------------------------------------------


if _HYPOTHESIS_AVAILABLE:

    # Primitive leaf values that survive a YAML round-trip cleanly.
    _primitive_st = st.one_of(
        st.booleans(),
        st.integers(min_value=-10_000, max_value=10_000),
        st.floats(allow_nan=False, allow_infinity=False, width=32),
        st.text(
            alphabet=st.characters(
                blacklist_categories=("Cs", "Cc"), blacklist_characters="\x00"
            ),
            max_size=12,
        ),
    )

    # A leaf may also be a list of primitives.
    _leaf_st = st.one_of(
        _primitive_st,
        st.lists(_primitive_st, max_size=4),
    )

    # Identifier-like keys for extras (safe inside YAML and in dotted paths).
    _key_st = st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Lu"), whitelist_characters="_"
        ),
        min_size=1,
        max_size=8,
    )

    # Top-level keys must not collide with the reserved base sections.
    _top_key_st = _key_st.filter(lambda s: s not in _RESERVED_TOP_LEVEL)

    # Extras are a mapping of top-level keys to leaves or nested dicts.
    _extras_st = st.dictionaries(
        keys=_top_key_st,
        values=st.one_of(
            _leaf_st,
            st.dictionaries(keys=_key_st, values=_leaf_st, max_size=4),
        ),
        max_size=4,
    )

    # Which of the 4 target keys to *omit* from the file — a subset of
    # {0, 1, 2, 3}. Using ``sets`` gives us the empty subset (none omitted)
    # up to the full subset (all four omitted).
    _omit_st = st.sets(
        st.integers(min_value=0, max_value=len(_TARGET_PAIRS) - 1),
        max_size=len(_TARGET_PAIRS),
    )

    @pytest.mark.unit
    @given(omit=_omit_st, extras=_extras_st)
    @settings(
        max_examples=60,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_load_config_positive_property(
        omit, extras, monkeypatch, tmp_path
    ) -> None:
        """Property 1 (Hypothesis): valid target configurations load cleanly.

        For any subset of omitted target keys and any extras, ``load_config``
        returns a dict that (a) contains every target key with its target
        value, and (b) preserves every extra key present in the source file.
        """
        cfg, _omitted = _make_config_under_test(sorted(omit), extras)
        _check_property(tmp_path, monkeypatch, cfg)


# ---------------------------------------------------------------------------
# Parametrized fallback — ~20 representative cases. Always runs so the
# property has deterministic regression coverage even when Hypothesis is
# unavailable or is parameterised with a different random seed.
# ---------------------------------------------------------------------------


def _build_fallback_cases() -> List[Tuple[str, Tuple[int, ...], Dict[str, Any]]]:
    """Return ``(case_id, omit_indices, extras)`` for the fallback suite."""
    cases: List[Tuple[str, Tuple[int, ...], Dict[str, Any]]] = []

    # 1. Base case — all target keys present, no extras.
    cases.append(("all_target_keys_no_extras", (), {}))

    # 2-5. Single-key omissions — one target key removed at a time.
    for idx, dotted in enumerate(_TARGET_DOTTED):
        cases.append((f"omit_{dotted.replace('.', '_')}", (idx,), {}))

    # 6. Two-key omission (architecture + backend).
    cases.append(("omit_architecture_and_backend", (0, 1), {}))

    # 7. Three-key omission.
    cases.append(("omit_first_three", (0, 1, 2), {}))

    # 8. All four target keys omitted — full default application.
    cases.append(("omit_all_target_keys", (0, 1, 2, 3), {}))

    # 9. Primitive extras at top level.
    cases.append(
        (
            "extras_primitive_scalars",
            (),
            {"alpha": 1, "beta": "hello", "gamma": True, "delta": 3.14},
        )
    )

    # 10. Nested-dict extras.
    cases.append(
        (
            "extras_nested_dict",
            (),
            {
                "aim": {
                    "speed": 0.7,
                    "smoothing_factor": 0.8,
                    "output_hz": 240,
                },
            },
        )
    )

    # 11. List-valued extras.
    cases.append(
        (
            "extras_lists",
            (),
            {
                "vision": {
                    "lower_color": [130, 80, 120],
                    "upper_color": [170, 255, 255],
                    "group_close_target_blobs_threshold": [5, 5],
                },
            },
        )
    )

    # 12. Deeply nested extras.
    cases.append(
        (
            "extras_deep_nesting",
            (),
            {
                "recoil": {"mode": "off", "recoil_y": 35.0, "recover": 0.0},
                "trigger": {
                    "delay": 0,
                    "randomization": 30,
                    "threshold": 8,
                    "enabled": False,
                },
            },
        )
    )

    # 13. Unicode extras (ensures YAML encoding survives).
    cases.append(
        (
            "extras_unicode_strings",
            (),
            {
                "labels": {
                    "greeting_it": "ciao mondo",
                    "cafe": "café",
                    "punctuation": "a-b_c.d",
                },
            },
        )
    )

    # 14. Many top-level extras (stress the walk).
    cases.append(
        (
            "extras_many_top_level",
            (),
            {f"extra_{i}": {"value": i, "flag": bool(i % 2)} for i in range(6)},
        )
    )

    # 15. Omit target key + add extras (combined case).
    cases.append(
        (
            "omit_backend_with_extras",
            (1,),
            {"aim": {"output_hz": 240}, "rapid_fire": {"enabled": False}},
        )
    )

    # 16. Omit all target keys + rich extras.
    cases.append(
        (
            "omit_all_with_rich_extras",
            (0, 1, 2, 3),
            {
                "vision": {"debug": False, "capture_fov_x": 420},
                "aim": {"speed": 0.7},
                "trigger": {"enabled": False},
            },
        )
    )

    # 17. Extras with edge-case primitives (zero, empty string, negative).
    cases.append(
        (
            "extras_edge_primitives",
            (),
            {
                "edges": {
                    "zero_int": 0,
                    "empty_str": "",
                    "neg_float": -1.5,
                    "false_bool": False,
                },
            },
        )
    )

    # 18. Extras with empty nested dict.
    cases.append(("extras_empty_nested_dict", (), {"placeholder": {}}))

    # 19. Extras with mixed list (primitives only).
    cases.append(
        (
            "extras_mixed_list",
            (),
            {"data": {"samples": [1, 2, 3, 4, 5], "tags": ["a", "b", "c"]}},
        )
    )

    # 20. Omit two non-adjacent target keys (capture.backend + input.driver).
    cases.append(("omit_backend_and_driver", (1, 3), {}))

    return cases


_FALLBACK_CASES = _build_fallback_cases()


@pytest.mark.unit
@pytest.mark.parametrize(
    "case_id,omit_indices,extras",
    _FALLBACK_CASES,
    ids=[case_id for case_id, _, _ in _FALLBACK_CASES],
)
def test_load_config_positive_fallback(
    case_id, omit_indices, extras, monkeypatch, tmp_path
):
    """Property 1 (parametrized fallback): curated valid configurations."""
    cfg, _omitted = _make_config_under_test(omit_indices, extras)
    _check_property(tmp_path, monkeypatch, cfg)


# ---------------------------------------------------------------------------
# Scaffolding sanity checks — isolate scaffolding bugs from property failures.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_helper_base_config_is_valid_target() -> None:
    """The base valid config must match every Target_Configuration value."""
    base = _base_valid_config()
    for path, expected in _TARGET_PAIRS:
        assert _get_path(base, path) == expected


@pytest.mark.unit
def test_helper_delete_path_removes_leaf() -> None:
    """`_delete_path` removes the leaf without damaging siblings."""
    d: Dict[str, Any] = {"a": {"b": 1, "c": 2}, "d": 3}
    _delete_path(d, ("a", "b"))
    assert "b" not in d["a"]
    assert d["a"]["c"] == 2
    assert d["d"] == 3


@pytest.mark.unit
def test_helper_extras_skip_reserved_top_levels() -> None:
    """Extras overlay must drop reserved top-level keys to avoid clobbering
    the target values mid-test.
    """
    cfg, _ = _make_config_under_test(
        omit_indices=(),
        extras={"general": {"architecture": "single_pc"}, "safe_extra": 1},
    )
    # ``general`` from extras was dropped → target value preserved.
    assert cfg["general"]["architecture"] == "dual_pc"
    # The non-reserved extra survived.
    assert cfg["safe_extra"] == 1
