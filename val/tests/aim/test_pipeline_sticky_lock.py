"""Closest-enemy selection — minimal pipeline.

The previous architecture maintained an explicit sticky-lock identity
(``_LockState.lock_x`` / ``lock_y`` plus a ``lock_seen_t`` timeout) so
target identity persisted across frames even when an adjacent enemy
moved closer to the crosshair. Live testing showed the lock object
was a source of bugs — it stuck on dead targets, missed re-acquisitions,
and held stale identities under EMA drift.

The minimal pipeline (see ``aim/pipeline.py``) does not maintain a
lock object. Instead, it picks the enemy whose head point is closest
to the crosshair every frame. Because every frame the cursor has just
moved toward the previously-closest enemy, the same enemy stays
closest on the next frame — the "lock" emerges naturally from the
closest-selection rule without an explicit identity. When the operator
moves the mouse physically (or the previously-locked enemy
disappears), the next frame's closest enemy is whichever bot is now
nearest; re-acquisition is free.

These tests pin the closest-enemy contract: given a list of detections,
``aim_step`` aims at the one nearest to the crosshair (with the head
offset applied) regardless of any prior frame's selection.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

from aim.pipeline import _LockState, aim_step
from engines.ai_engine import Detection


def _det(x: float, y: float, w: float = 60.0, h: float = 120.0,
         confidence: float = 0.9) -> Detection:
    """Build a Detection at the given bbox center."""
    return Detection(
        class_id=0, class_name="enemy",
        x=x, y=y, w=w, h=h, confidence=confidence,
    )


def _cfg(capture_size: int = 416,
         max_fov_radius: float = 200.0,
         pixel_to_count: float = 1.0,
         max_step: float = 60.0,
         headshot_bias: float = 0.30) -> dict:
    """Build a minimal cfg mapping for ``aim_step``."""
    return {
        "ai_engine": {
            "capture_size": capture_size,
            "headshot_bias": headshot_bias,
        },
        "aim": {
            "max_fov_radius": max_fov_radius,
            "max_step": max_step,
            "pixel_to_count": pixel_to_count,
        },
    }


def _capture_move_args(driver_mock: MagicMock):
    """Return the (cx_counts, cy_counts) of the LAST ``driver.move`` call.

    Returns ``None`` when ``driver.move`` was not called.
    """
    if driver_mock.move.call_args is None:
        return None
    return driver_mock.move.call_args.args


def test_aim_step_picks_closest_enemy_to_crosshair() -> None:
    """Two enemies, closer one wins.

    With the crosshair at ``(208, 208)`` (center of a 416×416 frame),
    enemy A at ``(190, 200)`` is closer than enemy B at ``(300, 300)``.
    ``aim_step`` must dispatch a move whose direction matches the head
    point of A.
    """
    driver = MagicMock()
    cfg = _cfg(capture_size=416, headshot_bias=0.30,
               max_fov_radius=200.0, pixel_to_count=1.0,
               max_step=200.0)
    state = _LockState()

    a = _det(x=190.0, y=200.0, w=40.0, h=80.0)
    b = _det(x=300.0, y=300.0, w=40.0, h=80.0)

    aim_step([a, b], state, cfg, driver)

    # Head point of A is (190, 200 - 80*0.30) = (190, 176).
    # Crosshair is (208, 208). dx=-18, dy=-32.
    args = _capture_move_args(driver)
    assert args is not None, "aim_step should have dispatched a move for the closer enemy A"
    cx_counts, cy_counts = args
    assert cx_counts < 0, "x must be negative — A is to the LEFT of the crosshair"
    assert cy_counts < 0, "y must be negative — A's head is ABOVE the crosshair"


def test_aim_step_skips_when_no_detections() -> None:
    """An empty detection list dispatches no move."""
    driver = MagicMock()
    cfg = _cfg()
    state = _LockState()
    aim_step([], state, cfg, driver)
    driver.move.assert_not_called()


def test_aim_step_skips_when_only_target_outside_fov() -> None:
    """A single enemy outside ``max_fov_radius`` is rejected."""
    driver = MagicMock()
    cfg = _cfg(capture_size=416, max_fov_radius=50.0,
               headshot_bias=0.30, pixel_to_count=1.0)
    state = _LockState()

    far = _det(x=100.0, y=100.0)
    aim_step([far], state, cfg, driver)
    driver.move.assert_not_called()


def test_aim_step_picks_only_in_range_enemy_when_others_are_out() -> None:
    """Mixed in/out-of-range scene: only the in-range enemy is considered.

    ``aim_step`` must not pick a closer-but-out-of-range enemy over
    the in-range candidate. The selector applies the FOV filter
    BEFORE the closest comparison.
    """
    driver = MagicMock()
    cfg = _cfg(capture_size=416, max_fov_radius=80.0,
               headshot_bias=0.30, pixel_to_count=1.0,
               max_step=200.0)
    state = _LockState()

    near = _det(x=240.0, y=210.0, w=40.0, h=80.0)  # ~32 px from center, in range
    far_but_centered_x = _det(x=210.0, y=350.0, w=40.0, h=80.0)  # too far

    aim_step([near, far_but_centered_x], state, cfg, driver)
    args = _capture_move_args(driver)
    assert args is not None, "aim_step should have selected the in-range enemy"
    cx_counts, cy_counts = args
    # The near enemy's head point is (240, 210 - 80*0.30) = (240, 186).
    # Crosshair is (208, 208). dx=+32, dy=-22.
    assert cx_counts > 0, "near enemy is to the RIGHT of crosshair"
    assert cy_counts < 0, "near enemy's head is ABOVE crosshair"


def test_aim_step_pixel_to_count_scales_output() -> None:
    """Doubling ``pixel_to_count`` doubles the dispatched counts."""
    driver_a = MagicMock()
    driver_b = MagicMock()
    state = _LockState()

    enemy = _det(x=240.0, y=240.0, w=40.0, h=80.0)
    cfg_a = _cfg(pixel_to_count=1.0, max_fov_radius=200.0, max_step=200.0)
    cfg_b = _cfg(pixel_to_count=2.0, max_fov_radius=200.0, max_step=200.0)

    aim_step([enemy], state, cfg_a, driver_a)
    aim_step([enemy], state, cfg_b, driver_b)

    args_a = _capture_move_args(driver_a)
    args_b = _capture_move_args(driver_b)
    assert args_a is not None and args_b is not None
    # Within 1e-6 the b-counts equal 2× the a-counts on both axes.
    assert math.isclose(args_b[0], 2.0 * args_a[0], rel_tol=1e-6)
    assert math.isclose(args_b[1], 2.0 * args_a[1], rel_tol=1e-6)


def test_aim_step_clamp_step_bounds_per_tick_displacement() -> None:
    """A very-far in-range enemy is clamped by ``max_step``.

    ``aim_step`` clamps the per-tick magnitude at ``aim.max_step``
    (preserving direction) so a single move can never warp the
    cursor across the screen.
    """
    driver = MagicMock()
    cfg = _cfg(capture_size=416, max_fov_radius=300.0,
               headshot_bias=0.0, pixel_to_count=1.0,
               max_step=10.0)
    state = _LockState()

    # Enemy is at (400, 208) — 192 px right of crosshair, but max_step=10
    # so the dispatched x must be ≤ 10.
    enemy = _det(x=400.0, y=208.0, w=40.0, h=80.0)
    aim_step([enemy], state, cfg, driver)
    args = _capture_move_args(driver)
    assert args is not None
    cx_counts, _ = args
    assert 0.0 < cx_counts <= 10.0 + 1e-6, (
        f"clamp_step should have capped x at max_step=10, got {cx_counts}"
    )


def test_aim_step_does_not_touch_lock_state() -> None:
    """The minimal pipeline does not maintain ``_LockState`` between ticks.

    A ``_LockState`` passed to ``aim_step`` must remain at its
    constructor defaults; the function reads no state and writes no
    state. (The orchestrator still calls ``state.clear()`` on its
    own reset edges; that is tested separately in
    ``test_master_toggle_reset.py``.)
    """
    driver = MagicMock()
    cfg = _cfg()
    state = _LockState()
    enemy = _det(x=240.0, y=240.0, w=40.0, h=80.0)

    aim_step([enemy], state, cfg, driver)

    # Every field stays at its dataclass default after a tick.
    assert state.lock_x is None
    assert state.lock_y is None
    assert state.lock_seen_t == 0.0
    assert state.smooth_x == 0.0
    assert state.smooth_y == 0.0
    assert state.last_aim_t is None
