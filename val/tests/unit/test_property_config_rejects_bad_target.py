"""
Property test — Task 9.3 of spec ``single-config-streamlining``.

**Property 2: Rifiuto di valori non-target e immutabilità del Config_File**

    *For any* chiave ``k ∈ TARGET_CONFIGURATION.keys()`` e *any* valore ``v``
    tale che ``v ≠ TARGET_CONFIGURATION[k]`` (stringa vuota, unicode
    arbitrario, tipi non-stringa, strutture annidate), scrivere ``v`` in
    ``config.yaml`` in posizione ``k`` e chiamare ``load_config()`` SHALL:

    1. sollevare :class:`ConfigException` il cui messaggio contiene come
       sottostringa sia il nome esatto della chiave ``k`` sia la
       rappresentazione stringa di ``v``;
    2. lasciare i byte di ``config.yaml`` identici a prima della chiamata.

**Validates: Requirements 2.6, 2.8, 3.11, 4.14, 7.8**

Implementation notes
--------------------
When Hypothesis is available, the main property test uses strategies to
generate ``(target_key, non_target_value)`` pairs across a broad input
space (strings, unicode, numbers, booleans, None, lists, dicts). When
Hypothesis is not available, a ``pytest.mark.parametrize`` fallback with
representative cases provides equivalent coverage. Both variants share
the same core property check via the ``_check_property`` helper.

Scope note on the "missing key" branch
--------------------------------------
Property 2's theoretical statement also mentions *"chiave assente"*, but
the Config_Loader policy (Req 3.12 / 7.6) is to **apply the target
default** for a missing key and proceed without raising. Missing-key
cases therefore belong to Property 1 (positive load) — validated by
``test_property_config_positive.py`` — and are intentionally out of
scope here, where the test asserts a ``ConfigException`` is raised.
"""

import hashlib
import math
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

import config
from exceptions import ConfigException

try:
    from hypothesis import HealthCheck, assume, given, settings
    from hypothesis import strategies as st
    _HYPOTHESIS_AVAILABLE = True
except ImportError:  # pragma: no cover — exercised only on envs without Hypothesis
    _HYPOTHESIS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _valid_target_config() -> Dict[str, Any]:
    """Build a minimal but fully-valid Target_Configuration dict.

    Kept local (instead of loading the workspace's ``config.yaml``) so the
    test is hermetic and cannot be perturbed by changes to the live config.
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
    }


#: The four dotted keys whose values are pinned by ``TARGET_CONFIGURATION``.
TARGET_KEYS: List[str] = list(config.TARGET_CONFIGURATION.keys())

#: Set of all target values across every target key. Used to filter out
#: values that would coincidentally match one of the targets.
_TARGET_VALUES = set(config.TARGET_CONFIGURATION.values())


def _set_dotted(cfg: Dict[str, Any], dotted_key: str, value: Any) -> None:
    """Set ``cfg[...][last] = value`` walking the dotted path."""
    parts = dotted_key.split(".")
    node: Dict[str, Any] = cfg
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def _get_dotted(cfg: Dict[str, Any], dotted_key: str) -> Any:
    """Return the value at ``dotted_key`` or ``None`` if absent."""
    node: Any = cfg
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_yaml_dumpable(value: Any) -> bool:
    """Return True if ``yaml.safe_dump`` can serialize ``value`` safely.

    Filters out floats that are NaN/inf (YAML representation works, but
    ``NaN != NaN`` breaks the "not equal to target" check downstream)
    and exotic nested structures that might contain them.
    """
    try:
        yaml.safe_dump({"x": value}, allow_unicode=True)
    except (yaml.YAMLError, TypeError, ValueError):
        return False
    # Reject NaN at the top level; it's a valid YAML value but compares
    # unequal to itself which destabilises the property formulation.
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return False
    return True


def _check_property(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_key: str,
    bad_value: Any,
) -> None:
    """Core invariant, shared by Hypothesis and parametrize tests.

    Procedure:
      1. Build a valid Target_Configuration dict, inject ``bad_value`` at
         ``target_key``.
      2. Serialize to a temp ``config.yaml``; snapshot bytes + sha256.
      3. Via YAML roundtrip, compute the *effective* value the loader will
         actually see; skip the case if that effective value collapses to
         the target (e.g. a YAML-serializable wrapper that evaluates equal).
      4. Monkeypatch :data:`config._CONFIG_FILE` at the temp file.
      5. Assert :func:`config.load_config` raises :class:`ConfigException`
         whose message contains both the exact dotted key and
         ``repr(effective_bad_value)``.
      6. Assert the temp file's bytes and sha256 are unchanged.
    """
    target_value = config.TARGET_CONFIGURATION[target_key]

    # Step 1: build + inject.
    cfg = _valid_target_config()
    _set_dotted(cfg, target_key, bad_value)

    # Step 2: serialize + snapshot. YAML dump is a safe operation and
    # ``_is_yaml_dumpable`` has already been asserted by callers.
    temp_config = tmp_path / "config.yaml"
    yaml_text = yaml.safe_dump(cfg, sort_keys=True, allow_unicode=True)
    temp_config.write_text(yaml_text, encoding="utf-8")
    original_bytes = temp_config.read_bytes()
    original_hash = _sha256_of(temp_config)

    # Step 3: compute the post-roundtrip value the loader will see.
    roundtripped = yaml.safe_load(temp_config.read_text(encoding="utf-8"))
    effective_bad_value = _get_dotted(roundtripped, target_key)

    # Skip if the YAML roundtrip happened to land on the target value.
    # Compare by type+equality to avoid ``True == 1`` collapse.
    if (
        type(effective_bad_value) is type(target_value)
        and effective_bad_value == target_value
    ):
        pytest.skip(
            f"YAML roundtrip of {bad_value!r} produced the target value "
            f"{target_value!r} for {target_key!r}."
        )

    # Step 4: redirect loader.
    monkeypatch.setattr(config, "_CONFIG_FILE", str(temp_config))

    # Step 5: expect ConfigException citing key + repr of offending value.
    with pytest.raises(ConfigException) as exc_info:
        config.load_config()
    message = str(exc_info.value)

    assert target_key in message, (
        f"ConfigException message does not cite the key {target_key!r}.\n"
        f"  bad_value           = {bad_value!r}\n"
        f"  effective_bad_value = {effective_bad_value!r}\n"
        f"  message             = {message!r}"
    )
    expected_repr = repr(effective_bad_value)
    assert expected_repr in message, (
        f"ConfigException message does not cite repr(effective_bad_value).\n"
        f"  bad_value           = {bad_value!r}\n"
        f"  effective_bad_value = {effective_bad_value!r}\n"
        f"  expected_repr       = {expected_repr!r}\n"
        f"  message             = {message!r}"
    )

    # Step 6: config.yaml must be byte-for-byte identical.
    post_bytes = temp_config.read_bytes()
    assert post_bytes == original_bytes, (
        f"config.yaml bytes changed during load_config() for "
        f"({target_key!r}, {bad_value!r}).\n"
        f"  before = {original_bytes!r}\n"
        f"  after  = {post_bytes!r}"
    )
    assert _sha256_of(temp_config) == original_hash, (
        f"config.yaml sha256 changed during load_config() for "
        f"({target_key!r}, {bad_value!r}) — loader is writing to disk."
    )


# ---------------------------------------------------------------------------
# Primary property test — Hypothesis strategies
# ---------------------------------------------------------------------------

if _HYPOTHESIS_AVAILABLE:

    # Smart strategies tailored to the non-target input space:
    #   - arbitrary unicode text (includes empty string)
    #   - integers (incl. negatives / zero)
    #   - finite floats (NaN/inf filtered downstream)
    #   - booleans
    #   - None
    #   - small lists of primitives
    #   - small dicts of str -> primitive
    _primitive = st.one_of(
        st.text(max_size=40),
        st.integers(min_value=-10_000, max_value=10_000),
        st.floats(allow_nan=False, allow_infinity=False, width=32),
        st.booleans(),
        st.none(),
    )

    _non_target_value_strategy = st.one_of(
        _primitive,
        st.lists(_primitive, min_size=0, max_size=4),
        st.dictionaries(
            st.text(min_size=1, max_size=6),
            _primitive,
            min_size=0,
            max_size=3,
        ),
    )

    @pytest.mark.unit
    @settings(
        max_examples=120,
        deadline=None,
        suppress_health_check=[
            HealthCheck.function_scoped_fixture,
            HealthCheck.too_slow,
        ],
    )
    @given(
        target_key=st.sampled_from(TARGET_KEYS),
        bad_value=_non_target_value_strategy,
    )
    def test_property_non_target_value_is_rejected(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        target_key: str,
        bad_value: Any,
    ) -> None:
        """Hypothesis-driven property test for Property 2.

        Constrains the generated ``bad_value`` away from the target value
        for the selected key, skips YAML-unrepresentable values, and
        delegates to :func:`_check_property`.
        """
        target_value = config.TARGET_CONFIGURATION[target_key]

        # Reject examples that are already the target value (would violate
        # the property's premise ``v ≠ TARGET_CONFIGURATION[k]``).
        if (
            type(bad_value) is type(target_value)
            and bad_value == target_value
        ):
            assume(False)

        # Reject examples that can't be represented in YAML.
        if not _is_yaml_dumpable(bad_value):
            assume(False)

        _check_property(tmp_path, monkeypatch, target_key, bad_value)


# ---------------------------------------------------------------------------
# Fallback / regression parametrize cases
# ---------------------------------------------------------------------------
# These explicit cases run in addition to the Hypothesis property above so
# that the highest-signal inputs (unicode edge cases, well-known removed
# backends/drivers, zero-width characters) are always exercised on every
# run, and so the test file still has meaningful coverage if Hypothesis is
# ever uninstalled from the environment.

_REPRESENTATIVE_NON_TARGET_VALUES = [
    pytest.param("single_pc", id="str-wrong-arch"),
    pytest.param("dxgi", id="str-removed-backend"),
    pytest.param("mss", id="str-removed-backend-mss"),
    pytest.param("hsv", id="str-removed-engine"),
    pytest.param("makcu", id="str-removed-driver"),
    pytest.param("CAPTURE_CARD", id="str-case-mismatch"),
    pytest.param(" capture_card ", id="str-whitespace-padded"),
    pytest.param("", id="str-empty"),
    pytest.param("αβγ", id="unicode-greek"),
    pytest.param("日本語", id="unicode-japanese"),
    pytest.param("\u200b", id="unicode-zero-width-space"),
    pytest.param(0, id="int-zero"),
    pytest.param(42, id="int-positive"),
    pytest.param(-1, id="int-negative"),
    pytest.param(3.14, id="float"),
    pytest.param(True, id="bool-true"),
    pytest.param(False, id="bool-false"),
    pytest.param(None, id="none"),
    pytest.param([], id="list-empty"),
    pytest.param([1, 2, 3], id="list-ints"),
    pytest.param(["capture_card"], id="list-target-wrapped"),
    pytest.param({}, id="dict-empty"),
    pytest.param({"nested": "value"}, id="dict-nested"),
]


@pytest.mark.unit
@pytest.mark.parametrize("target_key", TARGET_KEYS)
@pytest.mark.parametrize("bad_value", _REPRESENTATIVE_NON_TARGET_VALUES)
def test_representative_non_target_values_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_key: str,
    bad_value: Any,
) -> None:
    """Deterministic regression cases covering Property 2's edge space.

    Complements the Hypothesis property test above with a fixed,
    reproducible set of inputs spanning removed-backend names, empty and
    unicode strings, numeric primitives, booleans, None, and container
    types. Also acts as the fallback when Hypothesis is not installed.
    """
    _check_property(tmp_path, monkeypatch, target_key, bad_value)
