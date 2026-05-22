"""
Preservation property tests for Bug 1 (codebase-bug-fixes spec).

Property 2: Preservation - `AIVisionEngine` Public API and Health Dict Shape
Unchanged.

These tests encode the baseline behavior that the Bug 1 fix (removing the
duplicate `get_health_status` below `release`) MUST preserve. They are written
against the UNFIXED code following the observation-first methodology from
`design.md` and `tasks.md` Task 2, and they MUST PASS on the unfixed code.

**Validates: Requirements 3.1**

The three properties from Task 2 are:

1. For any fixture `AIVisionEngine` state, `get_health_status()` returns a
   dict whose key set equals
   `{"operational", "model_loaded", "backend", "avg_inference_ms", "enabled"}`
   and whose value types match the observed types.

2. The set of public method names and signatures on `AIVisionEngine`
   (other than the duplicated `get_health_status`) equals the observed set.

3. `engines.ai_engine.__all__ == ['AIVisionEngine', 'Detection']`.

Hypothesis is NOT installed in this environment (per the Task 1 execution),
so property-based coverage is achieved by pytest parameterization over a
diverse set of fixture engine states that exercise the full observed value
space of `get_health_status()` (`operational`, `model_loaded`, `backend`,
`avg_inference_ms`, `enabled`).
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, List, Tuple

import pytest

import engines.ai_engine as ai_engine_module
from engines.ai_engine import AIVisionEngine, Detection


# ---------------------------------------------------------------------------
# Observed baselines (captured against UNFIXED engines/ai_engine.py).
# ---------------------------------------------------------------------------

# Property 1 baseline: dict shape returned by get_health_status().
EXPECTED_HEALTH_KEYS: frozenset = frozenset(
    {"operational", "model_loaded", "backend", "avg_inference_ms", "enabled"}
)
EXPECTED_HEALTH_VALUE_TYPES: Dict[str, type] = {
    "operational": bool,
    "model_loaded": bool,
    "backend": str,
    "avg_inference_ms": float,
    "enabled": bool,
}

# Property 2 baseline: public method names → signature strings observed on
# the unfixed AIVisionEngine. `get_health_status` is intentionally EXCLUDED
# because the Bug 1 fix removes the duplicate definition; the preservation
# guarantee for its signature is covered by Property 1.
#
# Updated for the aim-pipeline-simplification spec, task 3.4:
# * `get_aim_delta` is REMOVED (head-point math moves into `aim_step` per
#   req 4.9 of the simplification spec).
# * `process_frame` return type changes from `Optional[Detection]` to
#   `List[Detection]` (req 4.9: AI engine returns raw detections only;
#   selection / head-bias / sticky-lock live in exactly ONE place
#   downstream — `aim_step._select_sticky`).
OBSERVED_PUBLIC_MEMBERS: Dict[str, str] = {
    "backend_name": "__property__",  # sentinel for a @property
    "get_avg_inference_ms": "(self) -> float",
    "load_model": "(self) -> bool",
    "process_frame": (
        "(self, frame: numpy.ndarray) -> "
        "List[engines.ai_engine.Detection]"
    ),
    "release": "(self)",
    "update_config": "(self, config: dict)",
}

# Property 3 baseline: module-level __all__.
EXPECTED_ALL: List[str] = ["AIVisionEngine", "Detection"]


# ---------------------------------------------------------------------------
# Fixture engine states — parameterization stands in for Hypothesis.
# ---------------------------------------------------------------------------

def _base_config() -> Dict[str, Any]:
    """Minimal valid config for constructing `AIVisionEngine`."""
    return {
        "enabled": True,
        "model_path": "",
        "confidence": 0.55,
        "iou_threshold": 0.45,
        "capture_size": 320,
        "headshot_bias": 0.30,
        "target_classes": [0],
    }


def _make_engine(
    *,
    enabled: bool = True,
    model_loaded: bool = False,
    backend: Any = None,
    inference_times: Tuple[float, ...] = (),
) -> AIVisionEngine:
    """Build an `AIVisionEngine` in a specific observable state.

    The state is constructed by mutating the public/internal attributes the
    canonical `get_health_status` reads — `enabled`, `model_loaded`,
    `_backend`, `_inference_times`. Every attribute access here is read by
    the canonical `get_health_status` definition in the unfixed file, so the
    parameterization reaches the full value-type space of the returned dict.
    """
    config = _base_config()
    config["enabled"] = enabled
    engine = AIVisionEngine(config)
    engine.model_loaded = model_loaded
    engine._backend = backend
    engine._inference_times = list(inference_times)
    return engine


# A deliberately varied set of fixture states. Each tuple exercises a
# different corner of the observable state space — disabled/enabled,
# loaded/unloaded, every possible backend tag including `None`, and a range
# of inference-time histories (empty, single-sample, rolling buffer).
FIXTURE_STATES: List[Tuple[str, Dict[str, Any]]] = [
    (
        "default_off",
        dict(enabled=False, model_loaded=False, backend=None,
             inference_times=()),
    ),
    (
        "enabled_unloaded",
        dict(enabled=True, model_loaded=False, backend=None,
             inference_times=()),
    ),
    (
        "directml_ready",
        dict(enabled=True, model_loaded=True, backend="directml",
             inference_times=(2.3,)),
    ),
    (
        "ultralytics_ready",
        dict(enabled=True, model_loaded=True, backend="ultralytics",
             inference_times=(8.1, 7.9, 8.4)),
    ),
    (
        "loaded_but_disabled",
        dict(enabled=False, model_loaded=True, backend="directml",
             inference_times=(1.8, 2.0, 1.9, 2.1)),
    ),
    (
        "rolling_buffer_full",
        dict(
            enabled=True,
            model_loaded=True,
            backend="ultralytics",
            inference_times=tuple(float(i) for i in range(1, 101)),
        ),
    ),
    (
        "backend_tag_none_but_loaded",
        # Not a realistic state, but it exercises the `self._backend or 'none'`
        # fallback branch in get_health_status.
        dict(enabled=True, model_loaded=True, backend=None,
             inference_times=(5.0,)),
    ),
]


# ---------------------------------------------------------------------------
# Property 1: get_health_status() dict shape is preserved.
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPreserveHealthStatusShape:
    """Property 2.1: get_health_status() returns the observed dict shape.

    For every fixture `AIVisionEngine` state, the returned dict has:
      * the exact key set `EXPECTED_HEALTH_KEYS`
      * value types matching `EXPECTED_HEALTH_VALUE_TYPES` (isinstance-based
        so that bool is distinguished from int, and the float channel stays
        float, not int)
      * no unexpected extra keys
    """

    @pytest.mark.parametrize(
        "state_name,state_kwargs",
        FIXTURE_STATES,
        ids=[name for name, _ in FIXTURE_STATES],
    )
    def test_key_set_matches_observed(
        self, state_name: str, state_kwargs: Dict[str, Any]
    ) -> None:
        engine = _make_engine(**state_kwargs)
        health = engine.get_health_status()

        assert isinstance(health, dict), (
            f"[{state_name}] get_health_status returned "
            f"{type(health).__name__}, expected dict"
        )
        assert set(health.keys()) == EXPECTED_HEALTH_KEYS, (
            f"[{state_name}] keys drifted: got {set(health.keys())}, "
            f"expected {set(EXPECTED_HEALTH_KEYS)}"
        )

    @pytest.mark.parametrize(
        "state_name,state_kwargs",
        FIXTURE_STATES,
        ids=[name for name, _ in FIXTURE_STATES],
    )
    def test_value_types_match_observed(
        self, state_name: str, state_kwargs: Dict[str, Any]
    ) -> None:
        engine = _make_engine(**state_kwargs)
        health = engine.get_health_status()

        for key, expected_type in EXPECTED_HEALTH_VALUE_TYPES.items():
            value = health[key]
            if expected_type is bool:
                # isinstance(x, int) is True for bool; enforce strict bool.
                assert isinstance(value, bool), (
                    f"[{state_name}] health[{key!r}] type drifted: "
                    f"got {type(value).__name__}, expected bool"
                )
            elif expected_type is float:
                # Allow int-like promotions only if the numeric value is 0,
                # because float(0) is the documented default. In practice
                # `avg_inference_ms` is produced by `sum(...) / len(...)`
                # which is always float, so enforce float strictly.
                assert isinstance(value, float), (
                    f"[{state_name}] health[{key!r}] type drifted: "
                    f"got {type(value).__name__}, expected float"
                )
            else:
                assert isinstance(value, expected_type), (
                    f"[{state_name}] health[{key!r}] type drifted: "
                    f"got {type(value).__name__}, "
                    f"expected {expected_type.__name__}"
                )


# ---------------------------------------------------------------------------
# Property 2: public method names and signatures are preserved.
# ---------------------------------------------------------------------------

def _public_members(cls: type) -> Dict[str, Any]:
    """Return `{name: member}` for every public attribute on `cls`.

    Public = not starting with `_`. Includes functions, methods, and
    properties; excludes dunder attributes and anything defined on `object`.
    """
    members: Dict[str, Any] = {}
    for name, value in inspect.getmembers(cls):
        if name.startswith("_"):
            continue
        if getattr(object, name, None) is value:
            continue
        members[name] = value
    return members


def _signature_of(member: Any) -> str:
    """Return the stable signature string used for comparison.

    Properties are represented by the sentinel `"__property__"` so that the
    comparison mirrors how `OBSERVED_PUBLIC_MEMBERS` recorded them.
    """
    if isinstance(member, property):
        return "__property__"
    return str(inspect.signature(member))


@pytest.mark.unit
class TestPreservePublicSurface:
    """Property 2.2: public members on `AIVisionEngine` match the baseline.

    The duplicated `get_health_status` is EXCLUDED from the comparison — its
    preservation is covered by `TestPreserveHealthStatusShape`. Every other
    public method/property name and signature must be byte-identical to the
    observed baseline.
    """

    def test_public_member_names_match_observed_excluding_get_health_status(
        self,
    ) -> None:
        members = _public_members(AIVisionEngine)
        names = {n for n in members if n != "get_health_status"}

        expected_names = set(OBSERVED_PUBLIC_MEMBERS.keys())
        assert names == expected_names, (
            "Public method name set on AIVisionEngine drifted from baseline. "
            f"observed={sorted(expected_names)}, actual={sorted(names)}, "
            f"missing={sorted(expected_names - names)}, "
            f"unexpected={sorted(names - expected_names)}"
        )

    @pytest.mark.parametrize(
        "member_name,expected_signature",
        sorted(OBSERVED_PUBLIC_MEMBERS.items()),
    )
    def test_public_member_signatures_match_observed(
        self, member_name: str, expected_signature: str
    ) -> None:
        members = _public_members(AIVisionEngine)
        assert member_name in members, (
            f"AIVisionEngine lost public member `{member_name}` "
            "relative to the baseline."
        )
        actual_signature = _signature_of(members[member_name])
        assert actual_signature == expected_signature, (
            f"Signature for AIVisionEngine.{member_name} drifted: "
            f"observed {expected_signature!r}, got {actual_signature!r}"
        )

    def test_get_health_status_is_still_callable_on_instance(self) -> None:
        """Even though we exclude it from the set comparison, the name must
        stay bound to a callable on the class — otherwise Property 1 above
        couldn't run post-fix."""
        members = _public_members(AIVisionEngine)
        assert "get_health_status" in members, (
            "AIVisionEngine.get_health_status disappeared from the public "
            "surface — Bug 1 fix must keep exactly one definition."
        )
        assert callable(members["get_health_status"]), (
            "AIVisionEngine.get_health_status is no longer callable."
        )
        # And the preserved signature shape is `(self) -> dict`.
        assert _signature_of(members["get_health_status"]) == "(self) -> dict"


# ---------------------------------------------------------------------------
# Property 3: module-level __all__ is preserved.
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPreserveModuleAll:
    """Property 2.3: `engines.ai_engine.__all__ == ['AIVisionEngine', 'Detection']`."""

    def test_all_is_exact_observed_list(self) -> None:
        assert hasattr(ai_engine_module, "__all__"), (
            "engines.ai_engine lost its `__all__` declaration."
        )
        assert ai_engine_module.__all__ == EXPECTED_ALL, (
            f"engines.ai_engine.__all__ drifted: "
            f"observed {EXPECTED_ALL!r}, got {ai_engine_module.__all__!r}"
        )

    def test_all_entries_are_actually_exported(self) -> None:
        """Sanity check that every name in `__all__` resolves on the module."""
        for name in EXPECTED_ALL:
            assert hasattr(ai_engine_module, name), (
                f"engines.ai_engine.__all__ lists {name!r} but the module "
                "has no such attribute."
            )
        # And the exported symbols are the ones we expect.
        assert ai_engine_module.AIVisionEngine is AIVisionEngine
        assert ai_engine_module.Detection is Detection
