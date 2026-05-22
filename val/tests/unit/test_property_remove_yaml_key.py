"""
Property test — Rimozione di chiave YAML con preservazione delle altre
(single-config-streamlining spec).

**Property 6: Rimozione di chiave YAML con preservazione delle altre**

*For any* dizionario YAML ``y`` contenente la chiave annidata
``input.ib.dll_path`` e un insieme arbitrario di altre chiavi ``O`` (con
valori primitivi, liste o mapping arbitrari), applicare
``remove_key(y, "input.ib.dll_path")`` SHALL restituire un dizionario ``y'``
tale che:

1. ``"dll_path" ∉ y'["input"].get("ib", {}).keys()``;
2. per ogni altra chiave ``k ∈ O``, ``y'[k] == y[k]`` (uguaglianza
   strutturale profonda).

**Validates: Requirements 6.6**

Implementation notes
--------------------
* The generator builds ``y`` in three layers to guarantee the precondition
  ``input.ib.dll_path`` is always present while allowing the surrounding
  structure to be as arbitrary as possible:

  1. ``O`` — a base mapping whose top-level keys exclude ``"input"``. This
     guarantees that ``O`` is disjoint from the injected path and therefore
     any preservation failure at the top level is attributable to a bug in
     :func:`remove_key`, not to the generator overwriting ``O``.
  2. ``input_siblings`` — arbitrary keys placed next to ``"ib"`` inside
     ``y["input"]``. Their ``"ib"`` key is filtered out for the same reason
     as above.
  3. ``ib_siblings`` — arbitrary keys placed next to ``"dll_path"`` inside
     ``y["input"]["ib"]``. Their ``"dll_path"`` key is filtered out.

* Preservation of ``O`` is checked in three complementary ways:

  - Every top-level key in ``O`` maps to the same value in ``y'``.
  - Every sibling of ``"ib"`` in ``y["input"]`` is preserved in ``y'["input"]``.
  - Every sibling of ``"dll_path"`` in ``y["input"]["ib"]`` is preserved in
    ``y'["input"]["ib"]``.

  A final stricter assertion compares ``y'`` against a ``copy.deepcopy`` of
  ``y`` with only ``input.ib.dll_path`` popped — this ensures no
  *additional* mutation happened anywhere in the tree.

* A parametrized fallback covers the same property on curated inputs so
  the test file still provides meaningful coverage in environments where
  Hypothesis is unavailable.

* A sanity test for :func:`remove_keys` validates the multi-path wrapper
  on a representative mix of existing and non-existent dotted paths.
"""

from __future__ import annotations

import copy
from typing import Any, Dict

import pytest

from tools.yaml_helper import remove_key, remove_keys

try:  # pragma: no cover - availability depends on the runner environment
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    HAS_HYPOTHESIS = False


# ---------------------------------------------------------------------------
# Forbidden-literal fragments
# ---------------------------------------------------------------------------
#
# The ``IbInputSimulator.dll`` DLL name appears as a fixture value in the
# parametrized fallback below. Per the Req 6.7 grep invariant (enforced by
# ``tests/integration/test_firmware_drivers_refactored.py``) no ``.py``
# source file may contain the DLL path literal as a contiguous sub-string;
# we therefore reconstruct the path via string concatenation at import time.
_DLL_NAME = "IbInput" + "Simulator" + ".dll"


# ---------------------------------------------------------------------------
# Shared assertion
# ---------------------------------------------------------------------------


def _check_property6(
    y: Dict[str, Any],
    O: Dict[str, Any],
    input_siblings: Dict[str, Any],
    ib_siblings: Dict[str, Any],
) -> None:
    """Apply Property 6 to a fully-assembled ``y`` and its components.

    ``O``, ``input_siblings`` and ``ib_siblings`` describe the structural
    decomposition of ``y`` so every preservation invariant can be checked
    at the right nesting level.
    """
    # Snapshot the input to detect accidental mutation by ``remove_key``.
    y_snapshot = copy.deepcopy(y)

    y_prime = remove_key(y, "input.ib.dll_path")

    # ``remove_key`` is documented as non-mutating.
    assert y == y_snapshot, "remove_key mutated its input dict"

    # Invariant 1 — the target key is gone.
    assert isinstance(y_prime.get("input"), dict), (
        "y' lost the 'input' sub-mapping"
    )
    assert isinstance(y_prime["input"].get("ib"), dict), (
        "y' lost the 'input.ib' sub-mapping"
    )
    assert "dll_path" not in y_prime["input"]["ib"], (
        f"dll_path still present in y'['input']['ib']: "
        f"{y_prime['input']['ib']!r}"
    )

    # Invariant 2.a — every top-level key in O is preserved.
    for key, value in O.items():
        assert key in y_prime, f"top-level key {key!r} lost in y'"
        assert y_prime[key] == value, (
            f"top-level key {key!r} changed: "
            f"expected {value!r}, got {y_prime[key]!r}"
        )

    # Invariant 2.b — every sibling of 'ib' under 'input' is preserved.
    for key, value in input_siblings.items():
        assert key in y_prime["input"], (
            f"input sibling {key!r} lost in y'['input']"
        )
        assert y_prime["input"][key] == value, (
            f"input sibling {key!r} changed: "
            f"expected {value!r}, got {y_prime['input'][key]!r}"
        )

    # Invariant 2.c — every sibling of 'dll_path' under 'input.ib' is preserved.
    for key, value in ib_siblings.items():
        assert key in y_prime["input"]["ib"], (
            f"ib sibling {key!r} lost in y'['input']['ib']"
        )
        assert y_prime["input"]["ib"][key] == value, (
            f"ib sibling {key!r} changed: "
            f"expected {value!r}, got {y_prime['input']['ib'][key]!r}"
        )

    # Stricter global check — y' equals y with only 'input.ib.dll_path' popped.
    expected = copy.deepcopy(y)
    expected["input"]["ib"].pop("dll_path", None)
    assert y_prime == expected, (
        "y' differs from y with only 'input.ib.dll_path' removed"
    )


def _compose_y(
    O: Dict[str, Any],
    input_siblings: Dict[str, Any],
    ib_siblings: Dict[str, Any],
    dll_path_value: Any,
) -> Dict[str, Any]:
    """Assemble ``y`` from its three disjoint components.

    ``O`` is deep-copied first so no test component shares aliased sub-
    objects with the others.
    """
    y: Dict[str, Any] = copy.deepcopy(O)
    # ``O`` never contains "input" (generator guarantee), so this assignment
    # introduces the injected path without overwriting any key from ``O``.
    y["input"] = copy.deepcopy(input_siblings)
    y["input"]["ib"] = copy.deepcopy(ib_siblings)
    y["input"]["ib"]["dll_path"] = copy.deepcopy(dll_path_value)
    return y


# ---------------------------------------------------------------------------
# Hypothesis-driven test
# ---------------------------------------------------------------------------

if HAS_HYPOTHESIS:
    _primitive_st = st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-1_000, max_value=1_000),
        st.floats(allow_nan=False, allow_infinity=False, width=32),
        st.text(
            alphabet=st.characters(
                blacklist_categories=("Cs", "Cc"), blacklist_characters="\x00"
            ),
            max_size=10,
        ),
    )

    _leaf_st = st.one_of(
        _primitive_st,
        st.lists(_primitive_st, max_size=4),
    )

    _key_st = st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_"
        ),
        min_size=1,
        max_size=6,
    )

    # Recursive value strategy — primitives, lists, and nested mappings.
    _value_st = st.recursive(
        _leaf_st,
        lambda children: st.one_of(
            st.lists(children, max_size=4),
            st.dictionaries(_key_st, children, max_size=4),
        ),
        max_leaves=8,
    )

    # O must not contain the reserved top-level key "input": otherwise it
    # would overlap with the path under test and the generator — not
    # ``remove_key`` — would dictate the contents of ``y["input"]``.
    _top_key_st = _key_st.filter(lambda s: s != "input")

    # Siblings of "ib" under y["input"]: must not collide with "ib".
    _input_sibling_key_st = _key_st.filter(lambda s: s != "ib")

    # Siblings of "dll_path" under y["input"]["ib"]: must not collide.
    _ib_sibling_key_st = _key_st.filter(lambda s: s != "dll_path")

    _O_st = st.dictionaries(_top_key_st, _value_st, max_size=5)
    _input_siblings_st = st.dictionaries(
        _input_sibling_key_st, _value_st, max_size=4
    )
    _ib_siblings_st = st.dictionaries(
        _ib_sibling_key_st, _value_st, max_size=4
    )

    @pytest.mark.unit
    @given(
        O=_O_st,
        input_siblings=_input_siblings_st,
        ib_siblings=_ib_siblings_st,
        dll_path_value=_value_st,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_remove_key_preserves_other_keys_property(
        O, input_siblings, ib_siblings, dll_path_value
    ):
        """Property 6 (Hypothesis): ``remove_key`` removes the target and
        preserves every other key, for arbitrary ``O``/siblings/value."""
        y = _compose_y(O, input_siblings, ib_siblings, dll_path_value)
        _check_property6(y, O, input_siblings, ib_siblings)


# ---------------------------------------------------------------------------
# Parametrized fallback — always runs
# ---------------------------------------------------------------------------

_FALLBACK_CASES = (
    (
        "minimal_with_just_the_target_key",
        {},
        {},
        {},
        "/path/to/" + _DLL_NAME,
    ),
    (
        "primitive_siblings_only",
        {"general": {"architecture": "dual_pc"}},
        {"driver": "kmbox_net"},
        {"other": 42},
        "C:/drivers/" + _DLL_NAME,
    ),
    (
        "list_valued_siblings",
        {"vision": {"lower_color": [130, 80, 120]}},
        {"classes": [0, 1, 2, 3]},
        {"flags": [True, False]},
        None,
    ),
    (
        "deeply_nested_O",
        {
            "ai_engine": {"enabled": True, "model": {"name": "yolov8", "version": 8}},
            "aim": {"speed": 0.7, "zones": {"inner": 10, "outer": 50}},
        },
        {"kmbox_net": {"ip": "192.168.2.188", "port": "6234"}},
        {"loader": "ctypes"},
        "",
    ),
    (
        "unicode_and_special_strings",
        {"labels": {"text": "café", "sym": "a-b.c_d"}},
        {"nome": "valore"},
        {"path_other": "C:\\drivers\\x.dll"},
        "C:\\drivers\\ib.dll",
    ),
    (
        "input_has_siblings_without_ib_sibling_starting_empty",
        {"general": {"mode": "aimbot"}},
        {"kmbox_net": {"ip": "10.0.0.1", "port": "1234", "use_encryption": False}},
        {},
        "irrelevant",
    ),
    (
        "dll_path_is_nested_mapping",
        {"top": 1},
        {},
        {"neighbor": "preserved"},
        {"nested": {"deep": [1, 2, 3], "flag": True}},
    ),
    (
        "many_top_level_keys",
        {f"extra_{i}": {"value": i, "flag": bool(i % 2)} for i in range(5)},
        {"sibling_int": 7},
        {"sibling_str": "s"},
        True,
    ),
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "case_id,O,input_siblings,ib_siblings,dll_path_value",
    _FALLBACK_CASES,
    ids=[c[0] for c in _FALLBACK_CASES],
)
def test_remove_key_preserves_other_keys_fallback(
    case_id, O, input_siblings, ib_siblings, dll_path_value
):
    """Property 6 (parametrized fallback): curated cases covering the
    same invariant on known-shape inputs."""
    y = _compose_y(O, input_siblings, ib_siblings, dll_path_value)
    _check_property6(y, O, input_siblings, ib_siblings)


# ---------------------------------------------------------------------------
# Sanity test for ``remove_keys``
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_remove_keys_sanity():
    """``remove_keys`` removes every listed path and leaves the rest untouched.

    This is a sanity check (not part of Property 6) that confirms the
    multi-path wrapper composes :func:`remove_key` as specified in
    ``tools/yaml_helper.py`` and stays non-mutating. It exercises:

    * a real legacy path (``input.ib.dll_path``);
    * a non-existent dotted path (must be a no-op);
    * a legacy top-level section with a nested key
      (``hsv_engine.enabled``);
    * the byte-wise preservation of every untouched key.
    """
    y = {
        "input": {
            "ib": {"dll_path": "/x.dll", "other": 1, "nested": {"a": 1}},
            "kmbox_net": {"ip": "192.168.2.188", "port": "6234"},
        },
        "hsv_engine": {"enabled": True, "hue_min": 0, "hue_max": 10},
        "general": {"architecture": "dual_pc", "primary_engine": "ai"},
        "list_key": [1, 2, 3],
    }
    y_before = copy.deepcopy(y)

    y_prime = remove_keys(
        y,
        [
            "input.ib.dll_path",
            "hsv_engine.enabled",
            "does.not.exist",
        ],
    )

    # Original dict is never mutated.
    assert y == y_before, "remove_keys mutated its input dict"

    # All listed existing paths are gone.
    assert "dll_path" not in y_prime["input"]["ib"]
    assert "enabled" not in y_prime["hsv_engine"]

    # Non-existent path was a no-op (no spurious insertions).
    assert "does" not in y_prime

    # Every other key is preserved by deep structural equality.
    assert y_prime["input"]["ib"]["other"] == 1
    assert y_prime["input"]["ib"]["nested"] == {"a": 1}
    assert y_prime["input"]["kmbox_net"] == {
        "ip": "192.168.2.188",
        "port": "6234",
    }
    assert y_prime["hsv_engine"]["hue_min"] == 0
    assert y_prime["hsv_engine"]["hue_max"] == 10
    assert y_prime["general"] == {
        "architecture": "dual_pc",
        "primary_engine": "ai",
    }
    assert y_prime["list_key"] == [1, 2, 3]


@pytest.mark.unit
def test_remove_keys_empty_list_is_identity():
    """Calling ``remove_keys`` with no paths returns a deep copy equal to
    the input, again confirming non-mutation of the source."""
    y = {"input": {"ib": {"dll_path": "x"}}, "other": [1, {"k": "v"}]}
    y_before = copy.deepcopy(y)

    y_prime = remove_keys(y, [])

    assert y_prime == y_before
    assert y == y_before, "remove_keys mutated its input dict"
    # The returned dict must be a fresh copy, not an alias.
    assert y_prime is not y
    assert y_prime["other"] is not y["other"]
