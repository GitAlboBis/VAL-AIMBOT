"""
Property test — Task 3.10 of spec ``aim-pipeline-simplification``.

# Feature: aim-pipeline-simplification, Property 4: Sub-pixel E2E

**Property 4: End-to-end sub-pixel conservation** — *for any
sequence of N detections fed through ``aim_step``, the cumulative
``sum(driver.send_move int outputs)`` equals
``round(sum(aim_step desired counts))`` ± 1 on each axis.*

**Validates: Requirement 3.7** (end-to-end variant) — "WHEN
``BaseMouse.calculate_move_amount(move_x, move_y)`` is invoked with
floating-point input THEN the system SHALL CONTINUE TO accumulate
the sub-pixel remainder in ``remainder_x, remainder_y`` and emit
truncated integer moves whose remainder fed back through the
accumulator converges to the exact requested displacement over
time. This is the canonical sub-pixel layer per req 2.7."

The unfixed pipeline disagreed on the sub-pixel state across
``AimOutput.pending_x/y`` and ``BaseMouse.remainder_x/y`` (defect
1.7), so the cumulative integer output diverged from the cumulative
float input by more than ±1. The simplification routes
``aim_step``'s smoothed counts directly into ``BaseMouse.move``,
which calls ``calculate_move_amount`` once. The integer output is
``floor(input + remainder_in)`` and the remainder is the fractional
leftover; cumulatively this is the input modulo 1, bounded by ±1.
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
SUBPIXEL_TOLERANCE = 1.0


class _Recorder(BaseMouse):
    """Capture float inputs to ``move`` and integer outputs of ``send_move``."""

    def __init__(self) -> None:
        super().__init__(target_cps=10.0)
        self.float_in_x = 0.0
        self.float_in_y = 0.0
        self.int_out_x = 0
        self.int_out_y = 0

    def move(self, x: float, y: float) -> None:  # type: ignore[override]
        self.float_in_x += float(x)
        self.float_in_y += float(y)
        super().move(x, y)

    def send_move(self, x: int, y: int) -> None:  # type: ignore[override]
        self.int_out_x += int(x)
        self.int_out_y += int(y)

    def send_click(self, delay_before_click: float = 0.0) -> None:  # type: ignore[override]
        raise AssertionError("send_click must not fire on the AI path")


def _cfg(pixel_to_count: float) -> Dict[str, Dict[str, Any]]:
    return {
        "aim": {
            "smoothing_factor": 0.85,
            "max_step": 60.0,
            "max_fov_radius": 200.0,
            "lock_radius_px": 70.0,
            "lock_timeout_s": 0.5,
            "pixel_to_count": pixel_to_count,
        },
        "ai_engine": {
            "capture_size": CAPTURE_SIZE,
            "headshot_bias": HEADSHOT_BIAS,
        },
    }


@st.composite
def _stream(draw: st.DrawFn) -> Tuple[List[Detection], float]:
    """Generate a detection stream and a ``pixel_to_count`` value.

    The stream is a sequence of in-FOV detections with varied bbox
    geometry; ``pixel_to_count`` is drawn from a band that exercises
    irrational fractional outputs (so the remainder accumulator must
    actually carry fractions across frames). The bbox center stays
    inside the FOV envelope on every frame.
    """
    n = draw(st.integers(min_value=1, max_value=15))
    seq: List[Detection] = []
    for _ in range(n):
        seq.append(
            Detection(
                class_id=0, class_name="enemy",
                x=draw(st.floats(min_value=180.0, max_value=240.0)),
                y=draw(st.floats(min_value=180.0, max_value=240.0)),
                w=draw(st.floats(min_value=40.0, max_value=80.0)),
                h=draw(st.floats(min_value=80.0, max_value=140.0)),
                confidence=draw(st.floats(min_value=0.55, max_value=0.99)),
            )
        )
    p2c = draw(st.floats(min_value=0.10, max_value=2.50))
    return seq, p2c


@pytest.mark.unit
@given(stream=_stream())
@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_subpixel_conservation_e2e(
    stream: Tuple[List[Detection], float],
) -> None:
    """Validates: Requirement 3.7 — sub-pixel conservation E2E.

    Drives a fresh ``aim_step`` chain and a ``_Recorder`` mouse with
    the generated detection stream, then asserts the cumulative
    integer output (post-``BaseMouse.calculate_move_amount``) sits
    within ±1 of the rounded cumulative float input on each axis.
    The tolerance is tight (±1, not ±N) precisely because the
    canonical sub-pixel layer is the *only* state machine in the
    integer-quantization pipeline post-simplification.
    """
    detections, pixel_to_count = stream
    state = _LockState()
    mouse = _Recorder()
    cfg = _cfg(pixel_to_count)

    for det in detections:
        aim_step([det], state, cfg, mouse, operator_overridden=False)

    expected_x = round(mouse.float_in_x)
    expected_y = round(mouse.float_in_y)
    assert abs(mouse.int_out_x - expected_x) <= SUBPIXEL_TOLERANCE, (
        f"Property 4 (sub-pixel E2E X, req 3.7): cumulative "
        f"send_move int_x={mouse.int_out_x} differs from "
        f"round(BaseMouse.move float input)={expected_x} by "
        f"{mouse.int_out_x - expected_x} (> ±{SUBPIXEL_TOLERANCE}). "
        f"Sub-pixel conservation requires BaseMouse.calculate_move_amount "
        f"to be the ONLY sub-pixel state machine on the path "
        f"(req 2.7 / 3.7)."
    )
    assert abs(mouse.int_out_y - expected_y) <= SUBPIXEL_TOLERANCE, (
        f"Property 4 (sub-pixel E2E Y, req 3.7): cumulative "
        f"send_move int_y={mouse.int_out_y} differs from "
        f"round(BaseMouse.move float input)={expected_y} by "
        f"{mouse.int_out_y - expected_y} (> ±{SUBPIXEL_TOLERANCE}). "
        f"Sub-pixel conservation requires BaseMouse.calculate_move_amount "
        f"to be the ONLY sub-pixel state machine on the path "
        f"(req 2.7 / 3.7)."
    )

    # Tighter check: when we add the still-pending remainder back to
    # the cumulative integer output, the result MUST equal the
    # cumulative float input (within float epsilon). This is the
    # inviolable conservation law of the canonical sub-pixel layer
    # per the existing ``tests/input/test_kmbox_subpixel_conservation.py``
    # test, here re-verified end-to-end through ``aim_step``.
    reconstructed_x = mouse.int_out_x + mouse.remainder_x
    reconstructed_y = mouse.int_out_y + mouse.remainder_y
    assert abs(reconstructed_x - mouse.float_in_x) < 1e-6, (
        f"sub-pixel conservation X violated: "
        f"int_out + remainder = {reconstructed_x} ≠ float_in = "
        f"{mouse.float_in_x}"
    )
    assert abs(reconstructed_y - mouse.float_in_y) < 1e-6, (
        f"sub-pixel conservation Y violated: "
        f"int_out + remainder = {reconstructed_y} ≠ float_in = "
        f"{mouse.float_in_y}"
    )
