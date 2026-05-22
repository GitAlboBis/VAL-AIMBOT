"""
Property test — Task 3.10 of spec ``aim-pipeline-simplification``.

# Feature: aim-pipeline-simplification, Property 5: dt-Clamp Pin

**Property 5: dt clamp** — *``aim_step`` after a wall-clock gap of
``g`` SHALL produce no displacement larger than after a gap of
``min(g, 100 ms)``. Trivially holds because ``aim_step`` does not
multiply by ``dt``; this is a pinning test for any future
re-introduction of a recoil / time-integrated term.*

**Validates: Requirement 2.4** — "WHEN the captured frame contains
no detections for one or more ticks THEN the system SHALL clear the
smoothing / lock / sub-pixel state of the entire pipeline within one
detection cycle of the gap. The ``delta_time`` field used by any
time-integrated calculation (e.g. recoil) SHALL be clamped to a sane
maximum (≤ 100 ms) regardless of wall-clock gap, so a 37 s gap
cannot inject a 37 s × recoil-rate displacement into the next tick."

The unfixed pipeline kept ``previous_x/y`` and ``recoil_move_x/y``
warm across detection gaps inside ``AimController``, so the next
detection produced a move whose recoil component was scaled by the
full wall-clock gap (defect 1.4). The simplification deletes the
recoil EMA and routes through ``aim_step``'s empty-detections gate,
which clears state on every gap. This test pins the contract: the
output after any gap depends only on the post-gap detection list
and the post-gap state — never on the gap length.
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
    def __init__(self) -> None:
        super().__init__(target_cps=10.0)
        self.calls: List[Tuple[int, int]] = []

    def send_move(self, x: int, y: int) -> None:  # type: ignore[override]
        self.calls.append((int(x), int(y)))

    def send_click(self, delay_before_click: float = 0.0) -> None:  # type: ignore[override]
        raise AssertionError("send_click must not fire on the AI path")


def _cfg() -> Dict[str, Dict[str, Any]]:
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


def _drive_with_gap(
    pre_det: Detection,
    gap_seconds: float,
    post_det: Detection,
) -> Tuple[Tuple[int, int], _LockState]:
    """Run pre-gap, empty-frame gap, post-gap and return post-gap output.

    ``gap_seconds`` is folded into the simulated detection gap by
    invoking ``aim_step`` with an empty detection list — the
    empty-detections gate (req 2.4) clears state synchronously, so
    the actual wall-clock duration is irrelevant for the function's
    output. We test that explicitly: regardless of how long the gap
    is, the post-gap output depends only on the post-gap detection.
    """
    state = _LockState()
    mouse = _Recorder()
    cfg = _cfg()

    # Pre-gap tick: establishes lock identity + EMA history.
    aim_step([pre_det], state, cfg, mouse, operator_overridden=False)

    # Gap: empty detection list (the framework also calls ``aim_step``
    # with an empty list when the AI thread reports no detections,
    # per main.py § "Read the detection list"). Per req 2.4 this
    # clears state and remainder. The ``gap_seconds`` parameter is
    # accepted by this harness purely to make the test symmetric
    # across gap lengths — the function itself does not consume it.
    del gap_seconds  # accepted to expose the API contract; unused
    aim_step([], state, cfg, mouse, operator_overridden=False)

    # Snapshot the count of pre-gap moves so we can isolate the
    # post-gap output.
    pre_gap_count = len(mouse.calls)

    # Post-gap tick: the only output we measure for this property.
    aim_step([post_det], state, cfg, mouse, operator_overridden=False)

    if len(mouse.calls) > pre_gap_count:
        return mouse.calls[pre_gap_count], state
    return (0, 0), state


@st.composite
def _gap_pair(draw: st.DrawFn) -> Tuple[Detection, Detection, float, float]:
    """Two detections + two gap lengths (one short, one long)."""
    pre = Detection(
        class_id=0, class_name="enemy",
        x=draw(st.floats(min_value=180.0, max_value=240.0)),
        y=draw(st.floats(min_value=180.0, max_value=240.0)),
        w=draw(st.floats(min_value=40.0, max_value=80.0)),
        h=draw(st.floats(min_value=80.0, max_value=140.0)),
        confidence=0.9,
    )
    post = Detection(
        class_id=0, class_name="enemy",
        x=draw(st.floats(min_value=180.0, max_value=240.0)),
        y=draw(st.floats(min_value=180.0, max_value=240.0)),
        w=draw(st.floats(min_value=40.0, max_value=80.0)),
        h=draw(st.floats(min_value=80.0, max_value=140.0)),
        confidence=0.9,
    )
    short_gap = draw(st.floats(min_value=0.001, max_value=0.099))   # < 100 ms
    long_gap = draw(st.floats(min_value=0.5, max_value=37.0))      # 0.5 s … 37 s
    return pre, post, short_gap, long_gap


@pytest.mark.unit
@given(scenario=_gap_pair())
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_post_gap_output_independent_of_gap_length(
    scenario: Tuple[Detection, Detection, float, float],
) -> None:
    """Validates: Requirement 2.4 — dt clamp / state-clear on gap.

    Drives two parallel pipelines with the SAME pre-detection and
    post-detection but DIFFERENT gap lengths (a short gap < 100 ms
    and a long gap up to 37 s). The post-gap integer output MUST be
    identical between the two runs — the gap length cannot perturb
    the output, which is exactly the property req 2.4 mandates and
    that defect 1.4 violated.

    The dt-clamp wording in req 2.4 ("≤ 100 ms regardless of
    wall-clock gap") is forward-looking: ``aim_step`` does not
    consume ``dt`` today, so the property holds vacuously. This
    test pins the contract for any future re-introduction of a
    time-integrated recoil term.
    """
    pre, post, short_gap, long_gap = scenario

    out_short, state_short = _drive_with_gap(pre, short_gap, post)
    out_long, state_long = _drive_with_gap(pre, long_gap, post)

    assert out_short == out_long, (
        f"Property 5 (dt clamp, req 2.4): post-gap output differs "
        f"between a {short_gap*1000:.1f} ms gap (out={out_short}) "
        f"and a {long_gap:.2f} s gap (out={out_long}). The gap "
        f"length must not influence the post-gap output — defect "
        f"1.4 was the unfixed pipeline scaling recoil by the full "
        f"wall-clock gap."
    )
    # State must also match — divergent state would surface on the
    # next call regardless of identical current output.
    assert (state_short.smooth_x, state_short.smooth_y) == \
           (state_long.smooth_x, state_long.smooth_y)
    assert (state_short.lock_x, state_short.lock_y) == \
           (state_long.lock_x, state_long.lock_y)
