"""
Property test — Task 3.10 of spec ``aim-pipeline-simplification``.

# Feature: aim-pipeline-simplification, Property 7: HSV Tracker

**Property 7: HSV head-target + structural no-click** —

  *(a)* for all frames containing one purple blob,
  ``pick_hsv_target`` returns a delta whose y-component is *above*
  the body center of the blob in capture-frame coordinates
  (``dy < (by + bh*0.5 - frame_h/2)``).

  *(b)* the ``engines/hsv_tracker`` module does NOT import
  ``input.base_mouse``. The "no click" guarantee of req 2.10 is
  enforced by absence of the click-capable type.

**Validates: Requirements 2.10, 2.13** — "WHEN the ``TargetTracker``
HSV fallback is the active source THEN the system SHALL aim at the
head of the color blob (top ``vision.head_roi_ratio`` fraction of
the blob's vertical extent) and SHALL NOT issue any click event
under any condition." / "WHEN the HSV fallback path is the active
source THEN it SHALL be implemented in a single module of ≤ 250
lines that exposes one entry point of the form
``pick_hsv_target(frame_bgr, fov_radius_px, hsv_lower, hsv_upper)
-> Optional[(dx, dy)]``."

The unfixed pipeline aimed at the body / legs of the color blob
(defect 1.10) and conflated the HSV path with click logic via
``TargetTracker.trigger`` and the ``trigger_threshold`` config key.
The simplification replaces the 2,633-line ``target_tracker.py``
with a stateless ≤100-line ``pick_hsv_target`` (req 4.4); this test
gates both the head-aim semantics and the structural no-click
guarantee.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from engines.hsv_tracker import (
    DEFAULT_HEAD_ROI_RATIO,
    DEFAULT_LOWER,
    DEFAULT_UPPER,
    pick_hsv_target,
)


FRAME_SIZE = 200


def _draw_purple_blob(
    frame_h: int,
    frame_w: int,
    blob_x: int,
    blob_y: int,
    blob_w: int,
    blob_h: int,
) -> np.ndarray:
    """Render a single purple-rectangle blob on a black BGR frame.

    The blob's HSV value is chosen so it falls inside the default
    ``DEFAULT_LOWER`` / ``DEFAULT_UPPER`` range. We use BGR
    ``(180, 0, 140)`` which converts to HSV ≈ (147, 255, 180) — well
    inside ``[130, 80, 120]`` … ``[170, 255, 255]``.
    """
    frame = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)
    # BGR for a saturated purple inside the default mask range.
    purple_bgr = np.array([180, 0, 140], dtype=np.uint8)
    x0 = max(0, blob_x)
    y0 = max(0, blob_y)
    x1 = min(frame_w, blob_x + blob_w)
    y1 = min(frame_h, blob_y + blob_h)
    if x1 > x0 and y1 > y0:
        frame[y0:y1, x0:x1] = purple_bgr
    return frame


@st.composite
def _purple_blob_scene(draw: st.DrawFn) -> Tuple[np.ndarray, int, int, int, int]:
    """Generate a frame with one purple blob and return its bbox."""
    bw = draw(st.integers(min_value=20, max_value=60))
    bh = draw(st.integers(min_value=40, max_value=120))
    # Place inside the FOV crop (centered window of side
    # 2 * fov_radius). With FRAME_SIZE = 200 and fov_radius_px = 80
    # the FOV window is x in [20, 180], y in [20, 180].
    fov_radius = 80
    x_min = FRAME_SIZE // 2 - fov_radius + 5
    x_max = FRAME_SIZE // 2 + fov_radius - 5 - bw
    y_min = FRAME_SIZE // 2 - fov_radius + 5
    y_max = FRAME_SIZE // 2 + fov_radius - 5 - bh
    bx = draw(st.integers(min_value=x_min, max_value=x_max))
    by = draw(st.integers(min_value=y_min, max_value=y_max))
    frame = _draw_purple_blob(FRAME_SIZE, FRAME_SIZE, bx, by, bw, bh)
    return frame, bx, by, bw, bh


@pytest.mark.unit
@given(scene=_purple_blob_scene())
@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_pick_hsv_target_returns_head_above_body_center(
    scene: Tuple[np.ndarray, int, int, int, int],
) -> None:
    """Validates: Requirement 2.10 — HSV path aims at head, not body.

    Renders a single purple rectangle whose color falls inside the
    default HSV mask range, then asserts ``pick_hsv_target`` returns
    a ``(dx, dy)`` delta with the y-component *above* the body
    center: ``dy < (by + bh*0.5 - frame_h/2)``. The default
    ``head_roi_ratio = 0.35`` places the head point at
    ``by + bh*0.35*0.5 = by + 0.175*bh``, so the head is 0.325·bh
    above the body center — comfortably satisfying the assertion.
    """
    frame, bx, by, bw, bh = scene
    fov_radius_px = 80
    delta = pick_hsv_target(
        frame_bgr=frame,
        fov_radius_px=fov_radius_px,
        hsv_lower=DEFAULT_LOWER,
        hsv_upper=DEFAULT_UPPER,
        head_roi_ratio=DEFAULT_HEAD_ROI_RATIO,
    )
    assert delta is not None, (
        f"Property 7a (HSV head, req 2.10): pick_hsv_target returned "
        f"None for a clearly visible purple blob bx={bx} by={by} "
        f"bw={bw} bh={bh}; the function must detect blobs above the "
        f"min_blob_area_px floor (default 60 px²)"
    )
    dx, dy = delta
    body_center_y_offset = (by + bh * 0.5) - (FRAME_SIZE / 2.0)
    assert dy < body_center_y_offset - 1e-6, (
        f"Property 7a (HSV head, req 2.10): returned dy={dy:.3f} is "
        f"NOT above the body center (body_center_y - frame_h/2 = "
        f"{body_center_y_offset:.3f}). The HSV path must aim at "
        f"the head ROI (top {DEFAULT_HEAD_ROI_RATIO} of the blob), "
        f"not the body."
    )
    # Sanity: the head point's x SHOULD sit within the blob's
    # horizontal extent — the simplified function picks the
    # bounding-rect horizontal center.
    body_center_x_offset = (bx + bw * 0.5) - (FRAME_SIZE / 2.0)
    assert abs(dx - body_center_x_offset) < bw * 0.5 + 1.0, (
        f"Property 7a (HSV head, req 2.10): returned dx={dx:.3f} is "
        f"outside the blob's horizontal extent (body_center_x = "
        f"{body_center_x_offset:.3f}, half-width = {bw * 0.5}). The "
        f"head point must sit on the blob's vertical axis."
    )


@pytest.mark.unit
def test_hsv_tracker_returns_none_on_empty_frame() -> None:
    """req 2.13 — function returns None when no qualifying blob."""
    frame = np.zeros((FRAME_SIZE, FRAME_SIZE, 3), dtype=np.uint8)
    result = pick_hsv_target(
        frame_bgr=frame,
        fov_radius_px=80,
        hsv_lower=DEFAULT_LOWER,
        hsv_upper=DEFAULT_UPPER,
    )
    assert result is None, (
        "Property 7 (req 2.13): pick_hsv_target on a black frame "
        "must return None — there is no purple blob to target"
    )


@pytest.mark.unit
def test_hsv_tracker_module_does_not_import_base_mouse() -> None:
    """Validates: Requirement 2.10 — HSV path issues no clicks.

    Per req 2.10's structural guarantee documented in
    ``engines/hsv_tracker.py`` ("this module MUST NOT import
    ``input.base_mouse``"), the HSV module cannot reach the
    click-capable driver type. We verify by parsing the module
    source for any import statement that mentions
    ``input.base_mouse`` or ``BaseMouse``.
    """
    import os
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = os.path.join(repo_root, "engines", "hsv_tracker.py")
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()

    # Reject any line that imports the click-capable types. We allow
    # the strings to appear in docstrings / comments (the module
    # *describes* the no-import invariant in its own docstring), so
    # we restrict the check to actual ``import`` lines.
    bad: list[str] = []
    for lineno, raw in enumerate(source.splitlines(), start=1):
        stripped = raw.strip()
        if not (stripped.startswith("import ") or stripped.startswith("from ")):
            continue
        if "input.base_mouse" in stripped or "BaseMouse" in stripped:
            bad.append(f"{lineno}: {raw.rstrip()}")

    assert not bad, (
        "Property 7b (HSV no-click, req 2.10): ``engines/hsv_tracker.py`` "
        "imports ``input.base_mouse`` or ``BaseMouse``. The module "
        "must NOT import a click-capable driver type — req 2.10 "
        "forbids click events on the HSV path, and the structural "
        "guarantee is the absence of the import.\nViolations:\n  "
        + "\n  ".join(bad)
    )


@pytest.mark.unit
def test_hsv_tracker_module_size_under_250_lines() -> None:
    """req 2.13 — module is ≤ 250 lines."""
    import os
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = os.path.join(repo_root, "engines", "hsv_tracker.py")
    with open(path, "r", encoding="utf-8") as fh:
        n_lines = sum(1 for _ in fh)
    assert n_lines <= 250, (
        f"Property 7 (req 2.13): engines/hsv_tracker.py is "
        f"{n_lines} lines (> 250). The simplified HSV module must "
        f"stay at or below the 250-line cap."
    )
