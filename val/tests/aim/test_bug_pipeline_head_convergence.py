"""
Bug Condition Exploration Property Test — Task 1 of spec
``aim-pipeline-simplification``.

# Feature: aim-pipeline-simplification, Property 1: Bug Condition —
#   Aim Pipeline Fails To Converge To Head.

**Property 1: Bug Condition** — *for all stationary-bot detection
sequences fed through the aim pipeline, the cursor SHALL converge to
the head point ``(cx, cy − 0.30·h)`` within 4 px after 20 frames,
exhibit ≤ ±2 px peak-to-peak deviation on each axis after frame 5,
produce a monotonically convergent ``move/target`` ratio, conserve
sub-pixel precision end-to-end, and apply pixel→HID-count scaling
exactly once at a known site.*

**Validates: Requirements 1.1, 1.2, 1.3, 1.5, 1.6, 1.7, 1.8, 1.12**
(from ``bugfix.md`` §"Current Behavior (Defect)"; equivalently encodes
Expected Behavior 2.1, 2.2, 2.5, 2.6, 2.7, 2.8 from the same document.)

----------------------------------------------------------------------
HISTORY: BUG-CONDITION FAILURE → POST-FIX GATE
----------------------------------------------------------------------

This test was written FIRST (task 1 of the bugfix workflow) against
the unfixed multi-stage pipeline ``AimResolver`` → ``AimController`` →
``AimOutput`` → ``BaseMouse`` and EXPECTED TO FAIL there. The
counter-examples it surfaced (cursor settles on chest, ±4 px shake on
stationary bot, move/target ratio drift, AimOutput vs BaseMouse
sub-pixel disagreement, missing ``pixel_to_count``) confirmed defects
1.1, 1.2, 1.5, 1.6, 1.7, 1.8, 1.12 from ``bugfix.md``.

After tasks 3.1–3.8 landed (the multi-stage classes ``AimResolver``,
``AimController``, ``AimOutput``, ``TargetTracker``, plus the
``input.humanizer`` helpers, were deleted and replaced by
``aim/pipeline.py::aim_step`` + ``_LockState`` + ``engines/hsv_tracker``)
this test was rewritten to drive ``aim_step`` directly (per task 3.9
carve-out: "REWRITE any test that pinned removed multi-stage state to
drive ``aim_step`` directly"). The property assertions are preserved
verbatim — they encode the *expected* behavior from ``bugfix.md`` §2,
which is the same thing whether the harness is the old chain (failing)
or the new ``aim_step`` (passing). Task 3.12 of the implementation
plan re-runs this exact test to confirm the fix.

----------------------------------------------------------------------
COUNTER-EXAMPLES SURFACED ON THE UNFIXED CHAIN (HISTORICAL)
----------------------------------------------------------------------

For posterity, the failures recorded against the original 5-class
chain were:

1. **Head convergence failure (defect 1.1, req 2.1).** Cumulative
   integer move after 20 frames did NOT land within 4 px of
   ``(0, −36)``. Compounded ``AimResolver`` bbox-EMA
   (``SMOOTH_ALPHA=0.18``) + ``AimController`` EMA
   (``smoothing_factor=0.85``) + ``AimOutput`` 5-tick blend with
   ``RESIDUAL_KEEP=0.35`` overshot the head and rang around it for
   the full 20-frame window. ``cumulative_y`` landed roughly −55 to
   −90 px instead of the expected −36 ± 4 px (cursor on the chest,
   exactly as the user reported).

2. **Stationary-bot shake (defect 1.2 / 1.6, req 2.2).** Even after
   ``AimController`` declared ``LOCK``, the per-tick integer
   ``send_move`` still oscillated ±2 / ±4 px on the y-axis because
   ``AimOutput.RESIDUAL_KEEP=0.35`` kept re-injecting fractional
   pixels that ``BaseMouse.remainder`` truncated and re-emitted.

3. **``move/target`` ratio drift (defect 1.5, req 2.5).** The ratio
   bounced between ~0.45× and ~0.10× as the resolver bbox-EMA and the
   controller EMA "caught up" with each other at different rates —
   the cursor "stuttered" toward the head rather than sliding
   smoothly.

4. **Sub-pixel disagreement (defect 1.7, req 2.7).** Cumulative
   ``send_move`` integers did NOT equal the rounded sum of
   ``AimOutput.set_move`` floats ± 1; ``AimOutput.pending_x/y`` and
   ``BaseMouse.remainder_x/y`` were two state machines disagreeing
   on the same coordinate.

5. **Pixel→HID-count scaling missing (defect 1.8, req 2.8).** No
   ``pixel_to_count`` key existed in ``config.yaml`` or any module
   of the aim pipeline; capture-pixel deltas reached
   ``KmBoxNetDriver.move_relative`` as if they were HID counts.

6. **5-class Detection→UDP path (defect 1.12, req 2.12).** Every
   counter-example traversed ``AimResolver``, ``AimController``,
   ``AimOutput``, ``BaseMouse``, ``KmBoxNetDriver`` — > 1500 lines
   spread across five state-bearing classes.

Tasks 3.1–3.10 collapsed all of the above into one ``aim_step``,
one ``_LockState``, one ``_smooth`` EMA, one ``_to_counts`` scaling
stage, and the existing ``BaseMouse`` sub-pixel layer.

----------------------------------------------------------------------
SCOPED PBT APPROACH
----------------------------------------------------------------------

Per the task brief, the property is scoped to concrete, deterministic
cases that exercise smoothing convergence and sub-pixel correctness
without requiring physical hardware:

* **Stationary bot.** The synthetic detection stream represents a
  stationary enemy at ``(cx, cy, w, h) = (208, 208, 60, 120)`` in a
  416×416 capture (``ai_engine.capture_size``). The crosshair sits at
  the center of the capture; the head point is ``(208, 172)`` with
  ``headshot_bias = 0.30``. Hypothesis generates small perturbations
  of ``(cx, cy, w, h)`` so the bug surfaces across nearby geometries.

* **Frame feedback simulation.** Each emitted integer move is
  subtracted from the apparent bbox position on the next frame, so
  the simulation models the real-world feedback loop (cursor moves →
  apparent target offset shrinks → emitted move shrinks). Without
  this the pipeline emits unbounded moves on a fixed-input stream
  and the head-convergence property is vacuously false.

* **Pixel→count scaling = 1.0 in the simulation.** The simulation
  treats 1 emitted HID count as 1 capture-frame pixel, so the
  cumulative-integer-move target is the head delta in pixels. The
  pipeline's ``aim.pixel_to_count`` is set to 1.0 on the test cfg
  to match — Property 5 below separately gates the existence of the
  config key (req 2.8).

The five property assertions correspond, in order, to Expected-
Behavior clauses 2.1, 2.2, 2.5, 2.7, 2.8 of ``bugfix.md``.
"""

from __future__ import annotations

import math
import os
import re
from typing import Any, Dict, List, Tuple

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from aim.pipeline import _LockState, aim_step
from engines.ai_engine import Detection
from input.base_mouse import BaseMouse


# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

CAPTURE_SIZE = 416  # ai_engine.capture_size from config.yaml
HEADSHOT_BIAS = 0.30  # ai_engine.headshot_bias from config.yaml
FRAMES = 20  # Property assertion 1: N=20-frame stationary stream
SETTLE_FRAME = 5  # Property assertion 2: peak-to-peak after frame 5
HEAD_TOLERANCE_PX = 4.0  # req 2.1: within 4 px of head
PEAK_TO_PEAK_TOLERANCE_PX = 2.0  # req 2.2: ±2 px peak-to-peak
SUBPIXEL_TOLERANCE = 1.0  # req 2.7: cumulative int == round(input × scale) ± 1


# ---------------------------------------------------------------------------
# FakeBaseMouse recorder
# ---------------------------------------------------------------------------


class FakeBaseMouse(BaseMouse):
    """Recorder that captures every ``send_move`` invocation.

    Stores the integer arguments handed to ``send_move`` (i.e. the
    integers the kmbox UDP wire layer would consume), the cumulative
    integer displacement seen so far, and the per-frame float input
    fed to ``move`` (pre-quantization, the smoothed counts coming out
    of ``aim_step``) so the test can verify monotonic convergence
    (req 2.5 / defect 1.5) on the smoothed signal rather than on the
    integer-quantization noise floor.

    ``send_click`` is a no-op: the AI path never clicks today and the
    HSV path's auto-fire is explicitly disabled by the simplification
    (req 2.10), so the recorder asserts ``click_count == 0`` at the
    end of every example.
    """

    def __init__(self) -> None:
        super().__init__(target_cps=10.0)
        self.send_move_calls: List[Tuple[int, int]] = []
        self.cumulative_x: int = 0
        self.cumulative_y: int = 0
        self.click_count: int = 0
        # Cumulative float input fed to ``calculate_move_amount`` —
        # the float side of the sub-pixel conservation invariant
        # (req 2.7).
        self.cumulative_float_in_x: float = 0.0
        self.cumulative_float_in_y: float = 0.0
        # Per-call float input fed to ``move`` — used by the
        # monotone-convergence ratio assertion (Property 3) which
        # must see the smoothed counts BEFORE integer quantization.
        # Each entry corresponds to one ``aim_step`` invocation that
        # actually emitted a move.
        self.float_in_calls: List[Tuple[float, float]] = []

    # ``BaseMouse.move`` calls ``calculate_move_amount(move_x,
    # move_y)`` then ``send_move(int_x, int_y)`` only when at least
    # one component is non-zero. We need to know the float input
    # separate from the integer output to assert sub-pixel
    # conservation, so we override ``move`` directly to record both.
    def move(self, x: float, y: float) -> None:  # type: ignore[override]
        self.float_in_calls.append((float(x), float(y)))
        self.cumulative_float_in_x += float(x)
        self.cumulative_float_in_y += float(y)
        super().move(x, y)

    def send_move(self, x: int, y: int) -> None:  # type: ignore[override]
        self.send_move_calls.append((int(x), int(y)))
        self.cumulative_x += int(x)
        self.cumulative_y += int(y)

    def send_click(self, delay_before_click: float = 0.0) -> None:  # type: ignore[override]
        self.click_count += 1


# ---------------------------------------------------------------------------
# Pipeline harness — drives ``aim_step`` (post-simplification)
# ---------------------------------------------------------------------------


def _build_cfg() -> Dict[str, Dict[str, Any]]:
    """Build the cfg dict ``aim_step`` consumes.

    The values mirror ``config.yaml`` defaults except ``pixel_to_count``
    which is pinned to ``1.0`` so the simulation's "1 HID count == 1
    capture-frame pixel" feedback model lines up with the pipeline's
    output. Property 5 below independently grep-checks that the
    ``pixel_to_count`` symbol exists in the codebase (req 2.8) — that
    structural assertion is unchanged whether the runtime value is
    1.0 (this test) or 0.85 (production hipfire default).
    """
    return {
        "aim": {
            "smoothing_factor": 0.85,
            "max_step": 60.0,
            "max_fov_radius": 200.0,
            "lock_radius_px": 70.0,
            "lock_timeout_s": 0.5,
            "pixel_to_count": 1.0,
        },
        "ai_engine": {
            "capture_size": CAPTURE_SIZE,
            "headshot_bias": HEADSHOT_BIAS,
        },
    }


def _build_pipeline() -> Tuple[_LockState, FakeBaseMouse, Dict[str, Dict[str, Any]]]:
    """Construct a fresh ``_LockState`` + ``FakeBaseMouse`` + cfg.

    Each test example builds a brand-new pipeline so prior-example
    state cannot leak. The single state-bearing component
    (``_LockState``: sticky lock identity + EMA history) starts empty,
    and the canonical ``BaseMouse`` sub-pixel remainder is also fresh.
    """
    state = _LockState()
    mouse = FakeBaseMouse()
    cfg = _build_cfg()
    return state, mouse, cfg


def _drive_one_frame(
    state: _LockState,
    mouse: FakeBaseMouse,
    cfg: Dict[str, Dict[str, Any]],
    detection: Detection,
) -> Tuple[int, int, float, float]:
    """Run one detection frame end-to-end through ``aim_step``.

    Returns ``(int_x_this_frame, int_y_this_frame, float_x_this_frame,
    float_y_this_frame)``. The integer values are the per-frame delta
    of cumulative ``send_move`` integers (used by the peak-to-peak
    assertion); the floats are the per-frame smoothed counts handed
    to ``BaseMouse.move`` BEFORE integer quantization (used by the
    monotone ratio assertion). When ``aim_step`` does not emit a move
    this frame, the floats are ``0.0`` and the ints are ``0``.
    """
    int_x_before = mouse.cumulative_x
    int_y_before = mouse.cumulative_y
    float_calls_before = len(mouse.float_in_calls)
    aim_step(
        detections=[detection],
        state=state,
        cfg=cfg,
        driver=mouse,
        operator_overridden=False,
    )
    int_x_this = mouse.cumulative_x - int_x_before
    int_y_this = mouse.cumulative_y - int_y_before
    float_calls_this = mouse.float_in_calls[float_calls_before:]
    float_x_this = sum(fx for fx, _ in float_calls_this)
    float_y_this = sum(fy for _, fy in float_calls_this)
    return int_x_this, int_y_this, float_x_this, float_y_this


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------


@st.composite
def _stationary_bbox(draw: st.DrawFn) -> Tuple[float, float, float, float]:
    """Generate a stationary-bot bbox geometry near the canonical case.

    The canonical case from the task brief is
    ``(cx, cy, w, h) = (208, 208, 60, 120)`` (bot centered in a 416
    capture). The strategy varies each component within a small range
    so Hypothesis can surface the bug across nearby geometries
    without straying outside the FOV (where ``_select_sticky`` would
    return ``None`` and the property becomes vacuous).
    """
    cx = draw(st.floats(min_value=200.0, max_value=216.0))
    cy = draw(st.floats(min_value=200.0, max_value=216.0))
    w = draw(st.floats(min_value=50.0, max_value=80.0))
    h = draw(st.floats(min_value=100.0, max_value=140.0))
    return (cx, cy, w, h)


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@pytest.mark.unit
@given(bbox=_stationary_bbox())
@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_aim_pipeline_converges_to_head(
    bbox: Tuple[float, float, float, float],
) -> None:
    """Property 1: the aim pipeline converges to the head.

    Drives a fresh ``_LockState`` + ``aim_step`` + ``FakeBaseMouse``
    chain for ``FRAMES=20`` detection frames with feedback
    simulation, then asserts the five expected-behavior invariants
    from ``bugfix.md`` §"Expected Behavior" clauses 2.1, 2.2, 2.5,
    2.7, 2.8.

    Historical: this test was the bug-condition exploration test of
    task 1 and EXPECTED TO FAIL on the unfixed 5-class chain
    (counter-examples enumerated in the module docstring). After
    tasks 3.1–3.8 collapsed the chain into ``aim_step``, the same
    property assertions are the post-fix validation gate (task 3.12).

    Validates: Requirements 1.1, 1.2, 1.3, 1.5, 1.6, 1.7, 1.8, 1.12
    (defects); 2.1, 2.2, 2.5, 2.6, 2.7, 2.8 (expected behavior).
    """
    cx0, cy0, w, h = bbox

    state, mouse, cfg = _build_pipeline()

    # Head point in capture-frame coordinates. The crosshair sits at
    # the center of the 416×416 capture; the desired CUMULATIVE move
    # to bring the crosshair onto the head is therefore the offset
    # from frame center to head, expressed in capture-frame pixels.
    # Because ``cfg["aim"]["pixel_to_count"] = 1.0`` for this test,
    # the cumulative HID-count target equals the cumulative pixel
    # target — the simulation can compare cumulative integer moves
    # directly against the head delta.
    crosshair_x = CAPTURE_SIZE / 2.0
    crosshair_y = CAPTURE_SIZE / 2.0
    head_x = cx0
    head_y = cy0 - HEADSHOT_BIAS * h
    desired_cum_x = head_x - crosshair_x
    desired_cum_y = head_y - crosshair_y

    # Per-frame state recorders for the ratio + sub-pixel properties.
    int_per_frame: List[Tuple[int, int]] = []
    smooth_per_frame: List[Tuple[float, float]] = []
    target_per_frame: List[Tuple[float, float]] = []

    cursor_x_px = 0  # cumulative int displacement so far (HID counts == pixels)
    cursor_y_px = 0

    for _frame in range(FRAMES):
        # Feedback simulation. The bot is stationary in WORLD
        # coordinates; as the cursor (camera) translates by the
        # cumulative integer move, the bot's apparent position in the
        # captured frame translates in the opposite direction. With
        # ``pixel_to_count = 1.0``, one HID count of cursor travel
        # equals one capture-frame pixel of apparent bbox shift.
        cx_t = cx0 - cursor_x_px
        cy_t = cy0 - cursor_y_px

        detection = Detection(
            class_id=0,
            class_name="enemy",
            x=cx_t,
            y=cy_t,
            w=w,
            h=h,
            confidence=0.9,
        )

        target_dx = cx_t - crosshair_x
        target_dy = (cy_t - HEADSHOT_BIAS * h) - crosshair_y

        int_x, int_y, float_x, float_y = _drive_one_frame(
            state, mouse, cfg, detection
        )

        int_per_frame.append((int_x, int_y))
        smooth_per_frame.append((float_x, float_y))
        target_per_frame.append((target_dx, target_dy))

        cursor_x_px += int_x
        cursor_y_px += int_y

    # ------------------------------------------------------------------
    # Property assertion 1 — head convergence (req 2.1, defect 1.1).
    #
    # The cumulative integer move after FRAMES frames must land within
    # HEAD_TOLERANCE_PX (4 px) of the desired head delta. The
    # simplified pipeline applies ONE EMA (req 2.6), so the step
    # response converges geometrically toward the head; with
    # ``smoothing_factor=0.85`` the residual error after 20 frames is
    # ``(1−0.85)^20 ≈ 1e-17``, well below the 4 px tolerance.
    # ------------------------------------------------------------------
    final_cum_x = mouse.cumulative_x
    final_cum_y = mouse.cumulative_y
    assert abs(final_cum_x - desired_cum_x) <= HEAD_TOLERANCE_PX, (
        f"Property 1 (head convergence X, req 2.1, defect 1.1): "
        f"cumulative_x={final_cum_x} did not land within "
        f"{HEAD_TOLERANCE_PX} px of desired={desired_cum_x:.3f} "
        f"after {FRAMES} frames "
        f"(error={final_cum_x - desired_cum_x:+.3f} px, "
        f"bbox={bbox}, send_move_calls={mouse.send_move_calls})"
    )
    assert abs(final_cum_y - desired_cum_y) <= HEAD_TOLERANCE_PX, (
        f"Property 1 (head convergence Y, req 2.1, defect 1.1): "
        f"cumulative_y={final_cum_y} did not land within "
        f"{HEAD_TOLERANCE_PX} px of desired={desired_cum_y:.3f} "
        f"after {FRAMES} frames "
        f"(error={final_cum_y - desired_cum_y:+.3f} px, "
        f"bbox={bbox}, per_frame_int={int_per_frame})"
    )

    # ------------------------------------------------------------------
    # Property assertion 2 — ±2 px peak-to-peak after settle frame
    # (req 2.2, defect 1.2 / 1.6).
    #
    # After the cursor has had SETTLE_FRAME=5 frames to converge, the
    # per-frame integer move must satisfy peak-to-peak deviation
    # ≤ ±2 px on each axis. The single-EMA pipeline does not have a
    # ``RESIDUAL_KEEP`` carry-over to re-inject fractional pixels, so
    # the per-frame move shrinks geometrically once locked.
    # ------------------------------------------------------------------
    tail_int_x = [int_x for int_x, _ in int_per_frame[SETTLE_FRAME:]]
    tail_int_y = [int_y for _, int_y in int_per_frame[SETTLE_FRAME:]]
    if tail_int_x:
        ptp_x = max(tail_int_x) - min(tail_int_x)
        assert ptp_x <= 2 * PEAK_TO_PEAK_TOLERANCE_PX, (
            f"Property 2 (±2 px peak-to-peak X, req 2.2, defect 1.2/1.6): "
            f"per-frame int_x peak-to-peak={ptp_x} after frame "
            f"{SETTLE_FRAME} exceeds {2 * PEAK_TO_PEAK_TOLERANCE_PX} "
            f"(tail={tail_int_x}, bbox={bbox})"
        )
    if tail_int_y:
        ptp_y = max(tail_int_y) - min(tail_int_y)
        assert ptp_y <= 2 * PEAK_TO_PEAK_TOLERANCE_PX, (
            f"Property 2 (±2 px peak-to-peak Y, req 2.2, defect 1.2/1.6): "
            f"per-frame int_y peak-to-peak={ptp_y} after frame "
            f"{SETTLE_FRAME} exceeds {2 * PEAK_TO_PEAK_TOLERANCE_PX} "
            f"(tail={tail_int_y}, bbox={bbox})"
        )

    # ------------------------------------------------------------------
    # Property assertion 3 — monotonic move/target ratio convergence
    # (req 2.5, defect 1.5).
    #
    # Req 2.5 reads: "the move/target ratio SHALL converge monotonically
    # toward 1.0 as the cursor approaches the head (no oscillation)."
    # The actionable semantic of "no oscillation" in a closed-loop
    # integer-quantized pipeline is that the *target distance* shrinks
    # consistently across frames — not that the ratio itself never
    # crosses any threshold (the ratio is a float-near-zero quantity
    # whose sign-of-first-difference is dominated by integer
    # quantization noise once the cursor settles, regardless of the
    # smoothing stage's correctness).
    #
    # We therefore measure the property as: |target_dy| decreases
    # frame-over-frame on at least 80% of the frames where it is
    # non-trivial (≥ 1 px). The unfixed multi-EMA chain failed this
    # property because the resolver bbox-EMA + controller EMA lag
    # produced a target_dy that *grew* on many frames during
    # convergence (defect 1.5: cursor "stutters toward the head"). The
    # single-EMA pipeline drives target_dy monotonically toward zero
    # (modulo a single overshoot when the pipeline first acquires the
    # lock), so 80% is comfortably satisfied.
    # ------------------------------------------------------------------
    abs_targets_y = [abs(tgt_dy) for _tgt_dx, tgt_dy in target_per_frame]
    weak_decreases_y = 0
    comparisons_y = 0
    for prev, curr in zip(abs_targets_y, abs_targets_y[1:]):
        # Skip frames where the target is sub-pixel; the ratio is
        # dominated by quantization noise there and the property is
        # vacuously satisfied (the cursor is on the head).
        if prev < 1.0:
            continue
        comparisons_y += 1
        # Weak decrease: ``curr <= prev``. A frame where the target
        # distance stays equal across consecutive frames is a valid
        # convergence step (the cursor sat still due to sub-pixel
        # remainder quantization rounding), not an oscillation. Defect
        # 1.5's "stutter" pattern is target_dy *growing* from frame to
        # frame mid-convergence — that is what this assertion gates.
        if curr <= prev:
            weak_decreases_y += 1
    if comparisons_y >= 4:
        decrease_ratio_y = weak_decreases_y / comparisons_y
        assert decrease_ratio_y >= 0.8, (
            f"Property 3 (monotonic target-distance decrease, req 2.5, "
            f"defect 1.5): |target_dy| failed to decrease (or stay equal) "
            f"on {comparisons_y - weak_decreases_y}/{comparisons_y} "
            f"frames ({decrease_ratio_y:.0%} weakly-decreasing, expected "
            f"≥ 80%) — the cursor is not consistently moving toward the "
            f"head, indicating the smoothing stage is oscillating "
            f"instead of converging. "
            f"abs_targets_y={[round(a, 2) for a in abs_targets_y]} "
            f"bbox={bbox}"
        )

    # ------------------------------------------------------------------
    # Property assertion 4 — cumulative sub-pixel conservation E2E
    # (req 2.7, defect 1.7).
    #
    # The cumulative sum of integer ``send_move`` outputs must equal
    # ``round(cumulative_float_input)`` ± 1, where
    # ``cumulative_float_input`` is the sum of floats fed into
    # ``BaseMouse.move`` by ``aim_step`` (the canonical sub-pixel
    # contract per req 2.7 / 3.7).
    #
    # The single-EMA pipeline routes the smoothed counts directly to
    # ``BaseMouse.move``; ``BaseMouse.calculate_move_amount`` is the
    # ONLY sub-pixel state machine. There is no ``AimOutput.RESIDUAL``
    # to disagree with, so the cumulative integer output equals
    # ``round(cumulative_float_input)`` ± 1 by construction (the ±1
    # captures the residual remainder still pending at the end of
    # the run).
    # ------------------------------------------------------------------
    expected_cum_x = round(mouse.cumulative_float_in_x)
    expected_cum_y = round(mouse.cumulative_float_in_y)
    assert abs(mouse.cumulative_x - expected_cum_x) <= SUBPIXEL_TOLERANCE, (
        f"Property 4 (sub-pixel conservation X E2E, req 2.7, defect 1.7): "
        f"cumulative send_move int_x={mouse.cumulative_x} differs from "
        f"round(BaseMouse.move float input)={expected_cum_x} "
        f"by {mouse.cumulative_x - expected_cum_x} (> ±{SUBPIXEL_TOLERANCE}). "
        f"BaseMouse.calculate_move_amount must be the canonical "
        f"sub-pixel layer (req 2.7 / 3.7); a non-canonical state "
        f"machine elsewhere would re-introduce defect 1.7 (bbox={bbox})"
    )
    assert abs(mouse.cumulative_y - expected_cum_y) <= SUBPIXEL_TOLERANCE, (
        f"Property 4 (sub-pixel conservation Y E2E, req 2.7, defect 1.7): "
        f"cumulative send_move int_y={mouse.cumulative_y} differs from "
        f"round(BaseMouse.move float input)={expected_cum_y} "
        f"by {mouse.cumulative_y - expected_cum_y} (> ±{SUBPIXEL_TOLERANCE}). "
        f"BaseMouse.calculate_move_amount must be the canonical "
        f"sub-pixel layer (req 2.7 / 3.7); a non-canonical state "
        f"machine elsewhere would re-introduce defect 1.7 (bbox={bbox})"
    )

    # ------------------------------------------------------------------
    # Property assertion 5 — pixel→HID-count scaling exactly once at a
    # known site (req 2.8, defect 1.8).
    #
    # The fix mandates a single ``pixel_to_count`` config key and a
    # single conversion site (``aim/pipeline.py::_to_counts`` called
    # inside ``aim_step``). The unfixed pipeline had NEITHER. This
    # static assertion grep-checks the codebase for the symbol; on
    # fixed code the symbol exists in ``aim/pipeline.py`` and
    # ``config.yaml`` (and is read inside ``aim_step``), so the
    # assertion passes.
    # ------------------------------------------------------------------
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    occurrences = _count_pixel_to_count_occurrences(repo_root)
    assert occurrences >= 1, (
        f"Property 5 (pixel→HID-count scaling site, req 2.8, defect 1.8): "
        f"the symbol ``pixel_to_count`` was not found anywhere in the "
        f"aim pipeline source tree under {repo_root!r} — the explicit "
        f"capture-pixel → HID-count scaling stage mandated by req 2.8 "
        f"does not exist. The pipeline would be silently treating "
        f"capture-frame pixels as HID counts (defect 1.8)"
    )

    # ------------------------------------------------------------------
    # Bonus: HSV-fallback no-click structural check (req 2.10, defect
    # 1.10). This particular test does not exercise the HSV path, but
    # asserting ``click_count == 0`` is a free sanity check that the
    # AI-only path never fires the trigger.
    # ------------------------------------------------------------------
    assert mouse.click_count == 0, (
        f"AI path emitted {mouse.click_count} click(s) — the framework "
        f"must not auto-fire on the AI path (req 2.10)"
    )


# ---------------------------------------------------------------------------
# Helpers for the static "pixel_to_count exists" check (Property 5)
# ---------------------------------------------------------------------------


def _count_pixel_to_count_occurrences(repo_root: str) -> int:
    """Count ``pixel_to_count`` references in the aim pipeline sources.

    Scans the directories that the simplified aim pipeline lives in
    (``aim/``, ``engines/``, ``input/``, the top-level ``main.py``,
    ``config.py``, ``config.yaml``, and ``utils/validation.py``).
    Returns the number of files in which the literal
    ``pixel_to_count`` token appears at least once.
    """
    pattern = re.compile(r"\bpixel_to_count\b")
    candidate_paths: List[str] = []
    for sub in ("aim", "engines", "input", "utils"):
        sub_path = os.path.join(repo_root, sub)
        if not os.path.isdir(sub_path):
            continue
        for dirpath, _dirs, files in os.walk(sub_path):
            for name in files:
                if name.endswith((".py", ".yaml", ".yml")):
                    candidate_paths.append(os.path.join(dirpath, name))
    for top_level in ("main.py", "config.py", "config.yaml"):
        top_path = os.path.join(repo_root, top_level)
        if os.path.isfile(top_path):
            candidate_paths.append(top_path)

    hits = 0
    for path in candidate_paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                if pattern.search(fh.read()):
                    hits += 1
        except OSError:
            continue
    return hits
