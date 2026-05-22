"""
Property test — Config_File round-trip (single-config-streamlining spec).

**Property 5: Round-trip del Config_File**

*For any* dictionary ``d`` valid according to the Target_Configuration (i.e.
``d`` contains ``general.architecture = dual_pc``,
``capture.backend = capture_card``, ``general.primary_engine = ai``, and
``input.driver = kmbox_net``), the sequence::

    yaml.safe_dump(d) -> write to temp file -> config.load_config()

SHALL return a dictionary ``d1`` such that, for every key present in ``d``,
``d1[k] == d[k]`` (after applying the target defaults). Repeating the
sequence a second time::

    yaml.safe_dump(d1) -> write to temp file -> config.load_config()

SHALL return a dictionary ``d2`` structurally equal to ``d1``
(idempotent round-trip).

**Validates: Requirements 7 (roundtrip property)**

Implementation notes:

* The test monkeypatches ``config._CONFIG_FILE`` to a temporary YAML file so
  each invocation of :func:`config.load_config` reads the dictionary under
  test.
* Hypothesis is the preferred generator. If Hypothesis is not installed in
  the environment a ``pytest.mark.parametrize`` fallback enumerates a
  representative set of valid configurations built from the real
  ``config.yaml`` shape plus synthetic extras designed to stress nesting,
  primitive types, collections, and the presence/absence of non-target
  sections.
"""

from __future__ import annotations

import copy
import os
from typing import Any, Dict, Iterable, Tuple

import pytest
import yaml

import config

try:  # pragma: no cover - availability depends on the runner environment
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    HAS_HYPOTHESIS = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Keys that — when present and holding a non-target value — make ``d`` invalid
# with respect to the Target_Configuration. The round-trip property is stated
# only for valid ``d`` so the base builder always forces the target value for
# these paths, regardless of what the generator proposed.
_TARGET_VALUES: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("general", "architecture"), "dual_pc"),
    (("capture", "backend"), "capture_card"),
    (("general", "primary_engine"), "ai"),
    (("input", "driver"), "kmbox_net"),
)


def _ensure_target_values(d: Dict[str, Any]) -> Dict[str, Any]:
    """Force every Target_Configuration key in ``d`` to its target value.

    Mutates and returns ``d``. If an intermediate key exists but is not a
    mapping (e.g. the extras generator produced ``d["general"] = 42``), the
    non-mapping value is replaced with a fresh dict so the target pair can
    be inserted without type conflict.
    """
    for path, target_value in _TARGET_VALUES:
        node: Dict[str, Any] = d
        for segment in path[:-1]:
            existing = node.get(segment)
            if not isinstance(existing, dict):
                existing = {}
                node[segment] = existing
            node = existing
        node[path[-1]] = target_value
    return d


def _write_yaml(path, data: Dict[str, Any]) -> None:
    """Serialize ``data`` with ``yaml.safe_dump`` into ``path``."""
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=True)


def _load_from(monkeypatch: pytest.MonkeyPatch, tmp_file) -> Dict[str, Any]:
    """Call :func:`config.load_config` with ``_CONFIG_FILE`` pointing at
    ``tmp_file``.
    """
    monkeypatch.setattr(config, "_CONFIG_FILE", str(tmp_file))
    return config.load_config()


def _iter_leaves(node: Any, prefix: Tuple[str, ...] = ()) -> Iterable[Tuple[Tuple[str, ...], Any]]:
    """Yield ``(path_tuple, value)`` for every leaf of a nested mapping."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _iter_leaves(value, prefix + (str(key),))
    else:
        yield prefix, node


def _get_path(d: Dict[str, Any], path: Tuple[str, ...]) -> Any:
    node: Any = d
    for segment in path:
        if not isinstance(node, dict) or segment not in node:
            return _MISSING
        node = node[segment]
    return node


_MISSING = object()


def _assert_superset(d1: Dict[str, Any], d: Dict[str, Any]) -> None:
    """Assert that for every leaf key present in ``d``, ``d1`` holds the
    same value at the same path.
    """
    for path, value in _iter_leaves(d):
        got = _get_path(d1, path)
        assert got == value, (
            f"round-trip mismatch at {'.'.join(path)}: "
            f"expected {value!r}, got {got!r}"
        )


def _roundtrip_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path, data: Dict[str, Any], filename: str
) -> Dict[str, Any]:
    """Write ``data`` to ``tmp_path/filename`` and call ``load_config``."""
    tmp_file = tmp_path / filename
    _write_yaml(tmp_file, data)
    return _load_from(monkeypatch, tmp_file)


# ---------------------------------------------------------------------------
# Minimal known-good base (mirrors the repository ``config.yaml`` shape so
# hypothesis/extras can overlay arbitrary additions on top without needing
# to regenerate the full schema).
# ---------------------------------------------------------------------------

_BASE_CONFIG: Dict[str, Any] = {
    "general": {
        "architecture": "dual_pc",
        "primary_engine": "ai",
        "log_level": "INFO",
        "mode": "aimbot",
        "overlay": False,
    },
    "capture": {
        "backend": "capture_card",
        "device_index": 0,
        "fps_cap": 60,
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


def _make_valid_config(extras: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ``extras`` over a deep copy of ``_BASE_CONFIG`` and re-pin the
    Target_Configuration keys, producing a dict that satisfies Property 5's
    validity precondition.
    """
    merged = copy.deepcopy(_BASE_CONFIG)

    def _merge(dst: Dict[str, Any], src: Dict[str, Any]) -> None:
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                _merge(dst[k], v)
            else:
                dst[k] = v

    _merge(merged, copy.deepcopy(extras))
    _ensure_target_values(merged)
    return merged


# ---------------------------------------------------------------------------
# Shared assertion: the full round-trip property (used by both the
# hypothesis-driven test and the parametrized fallback).
# ---------------------------------------------------------------------------


def _check_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path, d: Dict[str, Any]
) -> None:
    """Run the two-pass round-trip and assert both invariants.

    Invariant 1 — first pass preserves every key present in ``d``.
    Invariant 2 — second pass is idempotent (``d2 == d1``).
    """
    d1 = _roundtrip_once(monkeypatch, tmp_path, d, "config_pass1.yaml")
    _assert_superset(d1, d)

    d2 = _roundtrip_once(monkeypatch, tmp_path, d1, "config_pass2.yaml")
    assert d2 == d1, "second round-trip is not idempotent"


# ---------------------------------------------------------------------------
# Hypothesis-driven test (skipped automatically when Hypothesis is missing).
# ---------------------------------------------------------------------------

if HAS_HYPOTHESIS:
    # Primitive leaf values accepted by ``yaml.safe_dump``. ``None`` is
    # deliberately excluded from the generator because YAML ``null`` survives
    # the round-trip but can collide with default-application for the four
    # Target_Configuration keys (handled separately by ``_ensure_target_values``).
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

    _leaf_st = st.one_of(
        _primitive_st,
        st.lists(_primitive_st, max_size=4),
    )

    # Top-level keys must be plain identifiers so they cannot accidentally
    # create a dotted collision with the Target_Configuration paths.
    _top_key_st = st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu"), whitelist_characters="_"),
        min_size=1,
        max_size=6,
    ).filter(lambda s: s not in {"general", "capture", "input", "ai_engine"})

    _subsection_key_st = st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu"), whitelist_characters="_"),
        min_size=1,
        max_size=6,
    )

    _extras_st = st.dictionaries(
        keys=_top_key_st,
        values=st.one_of(
            _leaf_st,
            st.dictionaries(keys=_subsection_key_st, values=_leaf_st, max_size=4),
        ),
        max_size=4,
    )

    @pytest.mark.unit
    @given(extras=_extras_st)
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_config_roundtrip_property(extras, monkeypatch, tmp_path):
        """Property 5 (Hypothesis): round-trip holds for arbitrary extras."""
        d = _make_valid_config(extras)
        _check_roundtrip(monkeypatch, tmp_path, d)


# ---------------------------------------------------------------------------
# Parametrized fallback — always runs. Provides deterministic coverage even
# when Hypothesis is available, and is the sole source of coverage when it
# is not.
# ---------------------------------------------------------------------------

_FALLBACK_EXTRAS: Tuple[Tuple[str, Dict[str, Any]], ...] = (
    ("empty_extras", {}),
    (
        "primitives_only",
        {"alpha": 1, "beta": "text", "gamma": True, "delta": 3.14},
    ),
    (
        "nested_subsections",
        {
            "aim": {
                "speed": 0.7,
                "smoothing_factor": 0.8,
                "max_step": 120.0,
                "output_hz": 240,
            },
            "vision": {"debug": False, "capture_fov_x": 420, "capture_fov_y": 420},
        },
    ),
    (
        "lists_and_mixed_types",
        {
            "ai_engine": {
                "target_classes": [0, 1, 2],
                "iou_threshold": 0.45,
            },
            "vision": {
                "lower_color": [130, 80, 120],
                "upper_color": [170, 255, 255],
                "group_close_target_blobs_threshold": [5, 5],
            },
        },
    ),
    (
        "deep_nesting_and_booleans",
        {
            "input": {
                "magnetic_zones": {
                    "acceleration_radius": 150.0,
                    "y_axis_freedom": True,
                    "slowdown_power": 2.0,
                },
            },
            "recoil": {"mode": "off", "recoil_y": 35.0, "recover": 0.0},
        },
    ),
    (
        "overrides_that_must_not_break_target_keys",
        {
            # Deliberately attempt to override target keys; the helper must
            # re-pin them to the target values so the resulting ``d`` is
            # still valid.
            "general": {"architecture": "single_pc", "primary_engine": "hsv"},
            "capture": {"backend": "dxgi"},
            "input": {"driver": "makcu"},
        },
    ),
    (
        "coexisting_legacy_warnable_keys",
        {
            # Legacy keys produce warnings at load time but MUST NOT alter
            # the loaded dictionary, so the round-trip must still hold.
            "hsv_engine": {"enabled": False, "hue_min": 0, "hue_max": 10},
            "memory_esp": {"enabled": False, "process_name": "game.exe"},
        },
    ),
    (
        "unicode_and_special_strings",
        {
            "labels": {
                "greeting": "ciao mondo",
                "emoji_free_unicode": "café",
                "punctuation": "a-b_c.d",
            },
        },
    ),
    (
        "many_top_level_keys",
        {f"extra_{i}": {"value": i, "flag": bool(i % 2)} for i in range(6)},
    ),
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "case_id,extras",
    _FALLBACK_EXTRAS,
    ids=[case_id for case_id, _ in _FALLBACK_EXTRAS],
)
def test_config_roundtrip_fallback(case_id, extras, monkeypatch, tmp_path):
    """Property 5 (parametrized fallback): round-trip on curated configs."""
    d = _make_valid_config(extras)
    _check_roundtrip(monkeypatch, tmp_path, d)


# ---------------------------------------------------------------------------
# Sanity checks — ensure the helpers themselves behave so a failing Property
# 5 assertion is not masked by a bug in the test scaffolding.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_helper_ensure_target_values_pins_targets():
    """`_ensure_target_values` must overwrite non-target values in place."""
    d: Dict[str, Any] = {
        "general": {"architecture": "single_pc", "primary_engine": "hsv"},
        "capture": {"backend": "dxgi"},
        "input": {"driver": "makcu"},
    }
    _ensure_target_values(d)
    assert d["general"]["architecture"] == "dual_pc"
    assert d["general"]["primary_engine"] == "ai"
    assert d["capture"]["backend"] == "capture_card"
    assert d["input"]["driver"] == "kmbox_net"


@pytest.mark.unit
def test_helper_ensure_target_values_repairs_non_mapping_parents():
    """Non-dict intermediates must be replaced without raising."""
    d: Dict[str, Any] = {"general": 42, "capture": "oops", "input": None}
    _ensure_target_values(d)
    assert d["general"]["architecture"] == "dual_pc"
    assert d["capture"]["backend"] == "capture_card"
    assert d["input"]["driver"] == "kmbox_net"


@pytest.mark.unit
def test_baseline_config_roundtrip(monkeypatch, tmp_path):
    """The minimal base config on its own must round-trip."""
    d = _make_valid_config({})
    _check_roundtrip(monkeypatch, tmp_path, d)
