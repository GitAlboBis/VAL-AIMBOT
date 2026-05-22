"""HSV color-blob fallback tracker.

Replaces ``engines/target_tracker.py`` (2,633 lines → ~80 lines) per
requirements 2.10, 2.13, and 4.4 of the aim-pipeline-simplification spec.

The single entry point :func:`pick_hsv_target` is **stateless** and emits
**no click events**. Sticky-lock identity, smoothing, sub-pixel
quantization, and pixel→HID-count scaling are owned by ``aim/pipeline.py``
downstream — none of those concerns leak into this module.

Structural invariant (req 2.10): this module MUST NOT import
``input.base_mouse``. The "no click" guarantee is enforced by absence of
the click-capable driver type rather than by a runtime check.
"""

from typing import Optional, Tuple

import cv2
import numpy as np

# Defaults applied uniformly per req 2.13 — no per-distance interpolation,
# no `aim_height_far/mid/near`, no `head_offset_far`. One ratio, one mask.
DEFAULT_HEAD_ROI_RATIO: float = 0.35
DEFAULT_LOWER: np.ndarray = np.array([130, 80, 120], dtype=np.uint8)
DEFAULT_UPPER: np.ndarray = np.array([170, 255, 255], dtype=np.uint8)
DEFAULT_MIN_BLOB_AREA_PX: int = 60


def pick_hsv_target(
    frame_bgr: np.ndarray,
    fov_radius_px: int,
    hsv_lower: np.ndarray = DEFAULT_LOWER,
    hsv_upper: np.ndarray = DEFAULT_UPPER,
    head_roi_ratio: float = DEFAULT_HEAD_ROI_RATIO,
    min_blob_area_px: int = DEFAULT_MIN_BLOB_AREA_PX,
) -> Optional[Tuple[float, float]]:
    """Return ``(dx, dy)`` head offset from the frame center, or ``None``.

    Implements req 2.13 in five steps:

    1. Center-crop the frame to a square of side ``2 * fov_radius_px``.
    2. HSV-mask the crop using the configured lower/upper bounds, then
       run a single 3×3 closing pass to bridge anti-aliased outline gaps.
    3. Find the largest external contour above ``min_blob_area_px``.
    4. Compute the head point: vertical center of the top
       ``head_roi_ratio`` slice of the bounding rect (req 2.10 — head, not
       body); horizontal center of the bounding rect.
    5. Return the head point as a delta from the frame center.

    Parameters
    ----------
    frame_bgr:
        Capture-frame BGR image (e.g. 416×416 YOLO crop or 1920×1080 raw).
    fov_radius_px:
        Half-side of the square FOV crop, in capture-frame pixels.
    hsv_lower, hsv_upper:
        Inclusive HSV bounds for ``cv2.inRange``. ``vision.lower_color``
        and ``vision.upper_color`` from ``config.yaml``.
    head_roi_ratio:
        Fraction of the blob's vertical extent treated as the head ROI.
        ``vision.head_roi_ratio`` from ``config.yaml`` (default 0.35).
    min_blob_area_px:
        Area floor (px²) below which contours are rejected as noise.

    Returns
    -------
    ``(dx, dy)`` in capture-frame pixel units relative to the frame
    center, or ``None`` if no qualifying blob was found.
    """
    if frame_bgr is None or frame_bgr.size == 0:
        return None

    h, w = frame_bgr.shape[:2]
    cx_frame, cy_frame = w // 2, h // 2

    # 1. FOV crop — clamp to frame bounds so partial crops still work.
    r = max(1, int(fov_radius_px))
    x0 = max(0, cx_frame - r)
    y0 = max(0, cy_frame - r)
    x1 = min(w, cx_frame + r)
    y1 = min(h, cy_frame + r)
    fov = frame_bgr[y0:y1, x0:x1]
    if fov.size == 0:
        return None

    # 2. HSV mask + one closing pass (3×3). Nothing else.
    lower = np.asarray(hsv_lower, dtype=np.uint8)
    upper = np.asarray(hsv_upper, dtype=np.uint8)
    hsv = cv2.cvtColor(fov, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lower, upper)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    # 3. Largest contour above the area floor.
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < float(min_blob_area_px):
        return None
    bx, by, bw, bh = cv2.boundingRect(largest)

    # 4. Head point: top `head_roi_ratio` of the bounding rect, vertical
    #    center of that ROI. Translate FOV-local coords back to the frame.
    head_x = bx + bw / 2.0 + x0
    head_y = by + bh * head_roi_ratio * 0.5 + y0

    # 5. Delta from frame center (req 2.10 — head, not body).
    return (head_x - cx_frame, head_y - cy_frame)
