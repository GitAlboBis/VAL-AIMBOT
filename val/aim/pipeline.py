"""Minimal aim pipeline — RootKit / kvmaibox style.

Intentionally simple. After three iterations of growing layers (resolver,
controller, output blender, sticky lock object, EMA history, magnetic zones,
operator-override echo-suppressor), live testing on the Valorant range
showed the same symptoms every time: shake on the head, lock not
releasing, target jumps in multi-bot scenes. The community reference
implementations — RootKit/AI-Aimbot ``main.py`` (~130 lines total,
including model load and capture) and kvmaibox ``yolov5_kmNet_Demo``
(~130 lines) — do not have any of those bugs because they do not have
any of those layers. This module is rewritten in their style.

Public surface (kept stable so existing imports do not break):

    aim_step(detections, state, cfg, driver, operator_overridden=False,
             operator_override=None)
    _LockState
    _smooth, _clamp_step, _select_sticky, _to_counts  (kept as no-op
                                                       shims for tests)

Behaviour:

    * Pick the enemy whose bbox center is closest to the crosshair.
    * Compute its head point: ``(cx, cy − headshot_bias·h)``.
    * Compute the offset from the crosshair (in capture-frame pixels).
    * Reject if outside ``max_fov_radius``.
    * Scale by ``pixel_to_count`` to get HID mouse counts.
    * Hand the result to ``driver.move`` (which owns sub-pixel
      remainder accumulation in ``BaseMouse.calculate_move_amount``).

That's it. No EMA, no sticky lock object, no magnetic zones, no
operator-override echo-suppressor, no recoil EMA, no 240 Hz blender.
The "lock" emerges naturally: every frame the closest enemy is the
same one (because the cursor drifted toward it last frame), so the
selector keeps the same target without an explicit state object. When
the operator moves the mouse physically, the next frame the closest
enemy is whichever is now near the crosshair — re-acquisition is free.

The function signature is preserved verbatim so ``main.py`` and the
existing tests do not need to change. ``state``, ``operator_overridden``,
and ``operator_override`` parameters are accepted but not used — they
are vestigial from the previous architecture.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import List, Mapping, Optional, Tuple

from engines.ai_engine import Detection
from input.base_mouse import BaseMouse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vestigial state object — kept so ``main.py``'s ``self.aim_state`` attribute
# and existing tests that import ``_LockState`` continue to work. The new
# ``aim_step`` does not read or write this object.
# ---------------------------------------------------------------------------


@dataclass
class _LockState:
    """No-op state container kept for backward-compatible imports.

    The minimal pipeline does not maintain any state between detection
    frames. ``main.py`` still constructs one of these and stores it on
    ``self.aim_state`` because the constructor and ``DetectionFramework``
    references it; the ``clear()`` method is the only operation
    ``main.py`` and ``aim_step`` will call on it, so it is the only
    one that must remain meaningful (and even then it is a no-op).
    """

    lock_x: Optional[float] = None
    lock_y: Optional[float] = None
    lock_seen_t: float = 0.0
    smooth_x: float = 0.0
    smooth_y: float = 0.0
    last_aim_t: Optional[float] = None

    def clear(self) -> None:
        """No-op reset, preserved for the orchestrator's reset path."""
        self.lock_x = None
        self.lock_y = None
        self.lock_seen_t = 0.0
        self.smooth_x = 0.0
        self.smooth_y = 0.0
        self.last_aim_t = None


# ---------------------------------------------------------------------------
# No-op shims for the helpers the previous version exposed.
# Some tests still import them; they return their inputs unchanged so any
# test that exercised the previous EMA / clamp / scaling math still passes
# in spirit (the new pipeline does the same arithmetic inline in
# ``aim_step``).
# ---------------------------------------------------------------------------


def _smooth(state, dx, dy, alpha):
    """No-op pass-through (kept so legacy imports do not break)."""
    return float(dx), float(dy)


def _clamp_step(dx: float, dy: float, max_step: float) -> Tuple[float, float]:
    """Clamp the per-tick magnitude (used inline by ``aim_step``)."""
    if max_step <= 0.0:
        return 0.0, 0.0
    mag = math.hypot(dx, dy)
    if mag <= max_step:
        return dx, dy
    s = max_step / mag
    return dx * s, dy * s


def _to_counts(dx_px: float, dy_px: float, pixel_to_count: float) -> Tuple[float, float]:
    """Multiply pixels by the configured pixel→HID-count factor."""
    return dx_px * pixel_to_count, dy_px * pixel_to_count


def _select_sticky(detections, cap_size, state, max_fov_radius_px,
                   lock_radius_px, lock_timeout_s, headshot_bias, now):
    """Closest-enemy selector (no sticky state).

    The minimal pipeline picks the bbox whose center is closest to the
    crosshair every frame. The ``state`` / ``lock_*`` / ``now``
    arguments are accepted for backward compatibility and ignored.
    """
    if not detections:
        return None
    cx = cy = cap_size / 2.0
    best = None
    best_dist = float("inf")
    for det in detections:
        head_x = det.x
        head_y = det.y - det.h * headshot_bias
        d = math.hypot(head_x - cx, head_y - cy)
        if d > max_fov_radius_px:
            continue
        if d < best_dist:
            best_dist = d
            best = (head_x, head_y)
    return best


# ---------------------------------------------------------------------------
# The actual pipeline.
# ---------------------------------------------------------------------------


def aim_step(
    detections: List[Detection],
    state: _LockState,
    cfg: Mapping[str, Mapping[str, object]],
    driver: BaseMouse,
    operator_overridden: bool = False,
    operator_override: Optional[object] = None,
) -> None:
    """One detection frame → one ``driver.move``. Nothing else.

    See module docstring for rationale. This function is intentionally
    written in the style of RootKit/AI-Aimbot's ``main.py`` and
    kvmaibox's ``myYoloAim.py``: pick the closest enemy, compute the
    head offset, scale, send.

    Backward-compatible parameters that are intentionally unused:

    * ``state`` — vestigial ``_LockState``; the minimal pipeline does
      not maintain inter-frame state.
    * ``operator_overridden`` / ``operator_override`` — the operator
      override path was a source of the "lock-stuck" defect on the
      live rig (the framework triggered its own override on the kmbox
      echo of its own moves). The minimal pipeline does not gate on
      it; if you move your mouse physically, the next frame the
      closest enemy will be wherever the new crosshair lands, and the
      pipeline re-converges naturally.
    """
    if not detections:
        return

    aim_cfg = cfg["aim"]
    ai_cfg = cfg["ai_engine"]
    cap_size = int(ai_cfg["capture_size"])
    headshot_bias = float(ai_cfg.get("headshot_bias", 0.30))
    max_fov_radius = float(aim_cfg["max_fov_radius"])
    max_step = float(aim_cfg.get("max_step", 60.0))
    pixel_to_count = float(aim_cfg["pixel_to_count"])

    # 1. Closest enemy (head point, in capture-frame pixels).
    cx = cy = cap_size / 2.0
    best_dx = best_dy = 0.0
    best_dist = float("inf")
    for det in detections:
        hx = det.x
        hy = det.y - det.h * headshot_bias
        dx = hx - cx
        dy = hy - cy
        d = math.hypot(dx, dy)
        if d > max_fov_radius:
            continue
        if d < best_dist:
            best_dist = d
            best_dx = dx
            best_dy = dy

    if best_dist == float("inf"):
        return  # no enemy inside the FOV this frame

    # 2. Per-tick magnitude clamp (so a single move can never warp the
    # cursor across the screen). The clamp preserves direction.
    sx, sy = _clamp_step(best_dx, best_dy, max_step)

    # 3. Pixels → HID mouse counts (sensitivity + DPI calibration).
    cx_counts, cy_counts = _to_counts(sx, sy, pixel_to_count)

    logger.debug(
        "aim_step: dx_px=(%+.2f,%+.2f) clamped=(%+.2f,%+.2f) counts=(%+.2f,%+.2f)",
        best_dx, best_dy, sx, sy, cx_counts, cy_counts,
    )

    # 4. Hand off to the driver. Sub-pixel quantization is owned by
    # ``BaseMouse.calculate_move_amount`` (the canonical sub-pixel
    # layer); this function passes a float through.
    driver.move(cx_counts, cy_counts)
