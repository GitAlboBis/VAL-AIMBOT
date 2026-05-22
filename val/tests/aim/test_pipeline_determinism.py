"""
Property test — Task 3.10 of spec ``aim-pipeline-simplification``.

# Feature: aim-pipeline-simplification, Property 1: Pipeline Determinism

**Property 1: Determinism** — *for any sequence of detections fed
through ``aim_step``, two freshly-initialized ``_LockState``s driven
by the same input SHALL produce byte-identical ``BaseMouse.send_move``
recordings.*

**Validates: Requirement 2.5** — "WHEN the resolver / controller
computes ``move_x, move_y`` for a given target delta THEN the move
SHALL be a deterministic function of ``(distance, smoothing,
sub-pixel-remainder)`` only — the same input to a freshly-initialized
pipeline SHALL produce the same output, and the move/target ratio
SHALL converge monotonically toward 1.0."

The unfixed pipeline failed this property because four independent
EMA / blend / residual / remainder state machines composed with each
other in time-dependent ways (defects 1.5, 1.6, 1.7). The simplified
pipeline carries state in exactly one place — ``_LockState`` — and
calls ``BaseMouse.move`` with floats; sub-pixel quantization happens
inside the canonical ``BaseMouse.calculate_move_amount``. With both
state machines reset to identical zero-state, the same detection
sequence MUST produce identical byte streams.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from aim.pipeline import _LockState, aim_step
from engines.ai_engine import Detection
from input.base_mouse import BaseMouse


CAPTURE_SIZE = 416
HEADSHOT_BIAS = 0.30


class _Recorder(BaseMouse):
    """Capture every ``(int_x, int_y)`` handed to ``send_move``."""

    def __init__(self) -> None:
        super().__init__(target_cps=10.0)
        self.calls: List[Tuple[int, int]] = []

    def send_move(self, x: int, y: int) -> None:  # type: ignore[override]
        self.calls.append((int(x), int(y)))

    def send_click(self, delay_before_click: float = 0.0) -> None:  # type: ignore[override]
        # No-op; the AI path never clicks (req 2.10) — but a recorder
        # ought to crash loudly if anyone tries.
        raise AssertionError("send_click must not fire on the AI path")


def _cfg() -> Dict[str, Dict[str, Any]]:
    """Mirror the ``config.yaml`` defaults used by ``aim_step``."""
    return {
        "aim": {
            "smoothing_factor": 0.85,
            "max_step": 60.0,
            "max_fov_radius": 200.0,
            "lock_radius_px": 70.0,
            "lock_timeout_s": 0.5,
            "pixel_to_count": 0.85,
        },
        "ai_engine": {
            "capture_size": CAPTURE_SIZE,
            "headshot_bias": HEADSHOT_BIAS,
        },
    }


@st.composite
def _detection_sequence(draw: st.DrawFn) -> List[Detection]:
    """Generate a short detection stream centred near the crosshair.

    Each frame yields exactly one in-FOV detection so ``_select_sticky``
    consistently emits a head point (the determinism property is
    vacuously true on empty-detection frames because both runs would
    take the early-return branch identically). The bbox geometry
    varies slightly per frame so sticky-lock identity is exercised.
    """
    n = draw(st.integers(min_value=1, max_value=12))
    seq: List[Detection] = []
    for _ in range(n):
        seq.append(
            Detection(
                class_id=0,
                class_name="enemy",
                x=draw(st.floats(min_value=180.0, max_value=240.0)),
                y=draw(st.floats(min_value=180.0, max_value=240.0)),
                w=draw(st.floats(min_value=40.0, max_value=80.0)),
                h=draw(st.floats(min_value=80.0, max_value=140.0)),
                confidence=draw(st.floats(min_value=0.55, max_value=0.99)),
            )
        )
    return seq


@pytest.mark.unit
@given(seq=_detection_sequence())
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_two_fresh_lockstates_produce_identical_recordings(
    seq: List[Detection],
) -> None:
    """Validates: Requirement 2.5 — deterministic pipeline.

    Drives two independent ``_LockState`` + ``_Recorder`` chains with
    the same detection sequence and the same cfg dict, then asserts
    the recorded ``send_move`` byte streams match exactly. The
    pipeline does not multiply by ``dt`` (req 2.4 design rationale),
    so wall-clock variance between the two runs cannot perturb the
    output — determinism is a property of pure data flow.
    """
    cfg = _cfg()

    state_a, mouse_a = _LockState(), _Recorder()
    state_b, mouse_b = _LockState(), _Recorder()

    for det in seq:
        aim_step([det], state_a, cfg, mouse_a, operator_overridden=False)
        aim_step([det], state_b, cfg, mouse_b, operator_overridden=False)

    assert mouse_a.calls == mouse_b.calls, (
        f"Property 1 (determinism, req 2.5): two freshly-initialized "
        f"_LockState pipelines produced different send_move recordings "
        f"on the same input.\n"
        f"  a: {mouse_a.calls}\n  b: {mouse_b.calls}"
    )
    # The internal state must also match — any divergence in EMA /
    # lock identity would surface on the next call even when the
    # current call recorded the same bytes.
    assert (state_a.smooth_x, state_a.smooth_y) == (state_b.smooth_x, state_b.smooth_y)
    assert (state_a.lock_x, state_a.lock_y) == (state_b.lock_x, state_b.lock_y)
