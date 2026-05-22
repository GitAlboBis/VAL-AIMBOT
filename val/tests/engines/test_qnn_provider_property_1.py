"""
Property test for QNN detection well-formedness.

Feature: npu-qnn-provider, Property 1: Detection well-formedness

Validates: Requirements 2.1, 2.2, 2.3, 2.3a, 2.4, 2.7, 2.8, 9.1, 9.3

The property exercises ``QNNProvider.infer`` end-to-end against synthesized BGR
frames and synthesized ``(1, 6, N)`` FP16 model outputs, with the ONNX Runtime
session and IOBinding mocked. Generated outputs intentionally mix in-bounds and
out-of-bounds bbox values so the clamp + zero-area-drop branches in
``postprocess`` are exercised.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st
from hypothesis.extra import numpy as hnp

# Ensure the project root is on ``sys.path`` so ``engines`` imports resolve
# the same way they do in the rest of the test suite.
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from engines.qnn_provider import QNNProvider  # noqa: E402


# ---------------------------------------------------------------------------
# Test parameters
# ---------------------------------------------------------------------------

# Small input edge keeps each example fast while still exercising the full
# preprocess/postprocess path. The model is assumed to output 4 box channels
# (cx, cy, w, h) plus 2 class-score channels — hence the ``(1, 6, N)`` shape
# that this test synthesizes.
_IMGSZ = 32
_NUM_CLASSES = 2
_CONF = 0.25  # confidence threshold; allows a healthy mix of pass/drop draws


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------


@st.composite
def bgr_frame_strategy(draw: Any) -> np.ndarray:
    """Generate ``(H, W, 3)`` BGR ``uint8`` frames with ``H, W ∈ [imgsz, 4*imgsz]``.

    Pixel values cover the full ``[0, 255]`` range so resize + colour-convert
    paths see realistic content.
    """
    h = draw(st.integers(min_value=_IMGSZ, max_value=4 * _IMGSZ))
    w = draw(st.integers(min_value=_IMGSZ, max_value=4 * _IMGSZ))
    return draw(
        hnp.arrays(
            dtype=np.uint8,
            shape=(h, w, 3),
            elements=st.integers(min_value=0, max_value=255),
        )
    )


@st.composite
def yolo_output_strategy(draw: Any) -> np.ndarray:
    """Generate a ``(1, 6, N)`` FP16 raw YOLO output tensor.

    * ``N ∈ [0, 200]`` covers both the empty-output short-circuit and the
      typical post-NMS density.
    * Box channels (``cx, cy, w, h``) are drawn from ``[-imgsz, 2*imgsz]`` so
      both the low (``< 0``) and high (``> imgsz``) clamp branches in
      ``postprocess`` execute, plus the zero-area drop fires when a width or
      height clamps to ``0.0``.
    * Class-score channels are drawn from ``[0.0, 1.0]`` so per-detection
      ``np.max(class_scores, axis=1)`` stays inside the contractual range
      ``[0.0, 1.0]`` (Req 9.3 numerical bound).
    """
    n = draw(st.integers(min_value=0, max_value=200))
    if n == 0:
        return np.zeros((1, 6, 0), dtype=np.float16)

    box_low = -float(_IMGSZ)
    box_high = 2.0 * float(_IMGSZ)
    boxes = draw(
        hnp.arrays(
            dtype=np.float16,
            shape=(4, n),
            elements=st.floats(
                min_value=box_low,
                max_value=box_high,
                allow_nan=False,
                allow_infinity=False,
                width=16,
            ),
        )
    )
    scores = draw(
        hnp.arrays(
            dtype=np.float16,
            shape=(_NUM_CLASSES, n),
            elements=st.floats(
                min_value=0.0,
                max_value=1.0,
                allow_nan=False,
                allow_infinity=False,
                width=16,
            ),
        )
    )

    output = np.empty((1, 6, n), dtype=np.float16)
    output[0, :4, :] = boxes
    output[0, 4:, :] = scores
    return output


# ---------------------------------------------------------------------------
# Provider construction with mocked ORT session
# ---------------------------------------------------------------------------


def _make_mocked_provider(output_tensor: np.ndarray) -> QNNProvider:
    """Construct a ``QNNProvider`` whose ORT session is fully mocked.

    ``load()`` is bypassed by directly populating the attributes that ``infer``
    depends on:

    * ``session`` and ``_io_binding`` are :class:`unittest.mock.MagicMock`
      instances. ``session.run_with_iobinding`` is a no-op;
      ``_io_binding.synchronize_inputs`` is a no-op;
      ``_io_binding.copy_outputs_to_cpu`` returns ``[output_tensor]``.
    * ``_input_buffer`` and ``_resize_buffer`` are pre-allocated to the same
      shapes ``load()`` would produce, so ``preprocess`` writes in place
      without per-frame allocations (Req 2.7).
    * ``_load_thread_id`` is set so any later ``release()`` does not log a
      cross-thread WARN.

    This keeps the property test runnable on x86_64 CI hosts where the QNN EP
    is not installed.
    """
    provider = QNNProvider("dummy.onnx", imgsz=_IMGSZ, conf=_CONF)

    session = MagicMock(name="ort.InferenceSession")
    session.run_with_iobinding = MagicMock(return_value=None)

    io_binding = MagicMock(name="ort.IOBinding")
    io_binding.synchronize_inputs = MagicMock(return_value=None)
    io_binding.copy_outputs_to_cpu = MagicMock(return_value=[output_tensor])

    provider.session = session
    provider._io_binding = io_binding
    provider.input_name = "images"
    provider.output_names = ["output0"]
    provider._input_buffer = np.empty(
        (1, 3, _IMGSZ, _IMGSZ), dtype=np.float16
    )
    provider._resize_buffer = np.empty(
        (_IMGSZ, _IMGSZ, 3), dtype=np.uint8
    )
    provider._load_thread_id = threading.get_ident()
    provider.provider_used = "QNNExecutionProvider"
    return provider


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@given(frame=bgr_frame_strategy(), output_tensor=yolo_output_strategy())
@settings(max_examples=100)
def test_qnn_detection_well_formedness(
    frame: np.ndarray, output_tensor: np.ndarray
) -> None:
    """Feature: npu-qnn-provider, Property 1: Detection well-formedness.

    For every drawn frame and every drawn ``(1, 6, N)`` FP16 model output, the
    list of detections returned by ``QNNProvider.infer`` must satisfy:

    * The function returns ``(list, float)`` with a non-negative
      ``elapsed_ms`` (Req 2.1).
    * Every detection has exactly the six keys
      ``{class_id, confidence, x, y, w, h}`` (Req 2.2).
    * ``class_id`` is a Python ``int`` ``>= 0`` and ``confidence`` is a Python
      ``float`` in ``[self.conf, 1.0]`` (Reqs 2.2, 2.3, 2.4, 9.3).
    * ``(x, y)`` is the bbox centre clamped to ``[0, W] × [0, H]`` and
      ``(w, h)`` is the bbox size clamped to ``(0, W] × (0, H]`` after
      independent x/y scaling (Reqs 2.3, 2.3a, 2.7, 2.8, 9.1).
    """
    provider = _make_mocked_provider(output_tensor)
    H, W = frame.shape[:2]

    result = provider.infer(frame)

    # Return shape contract — Req 2.1.
    assert isinstance(result, tuple), f"infer() returned {type(result).__name__}"
    assert len(result) == 2, f"infer() returned tuple of len {len(result)}"
    detections, elapsed_ms = result
    assert isinstance(detections, list), (
        f"detections has type {type(detections).__name__}"
    )
    assert isinstance(elapsed_ms, float), (
        f"elapsed_ms has type {type(elapsed_ms).__name__}"
    )
    assert elapsed_ms >= 0.0, f"elapsed_ms={elapsed_ms!r} is negative"

    expected_keys = {"class_id", "confidence", "x", "y", "w", "h"}
    W_f = float(W)
    H_f = float(H)

    for d in detections:
        # Schema invariance — Req 2.2 / 9.1.
        assert set(d.keys()) == expected_keys, (
            f"detection keys {set(d.keys())!r} != {expected_keys!r}"
        )

        # Native Python types — Req 2.2.
        assert isinstance(d["class_id"], int), (
            f"class_id has type {type(d['class_id']).__name__}"
        )
        assert d["class_id"] >= 0, f"class_id={d['class_id']!r} is negative"

        assert isinstance(d["confidence"], float), (
            f"confidence has type {type(d['confidence']).__name__}"
        )
        # Confidence range — Req 2.4 lower bound, Req 9.3 upper bound.
        assert provider.conf <= d["confidence"] <= 1.0, (
            f"confidence={d['confidence']!r} not in [{provider.conf}, 1.0]"
        )

        # Bbox centre clamp — Reqs 2.3, 2.3a, 2.8.
        assert 0.0 <= d["x"] <= W_f, f"x={d['x']!r} not in [0.0, {W_f}]"
        assert 0.0 <= d["y"] <= H_f, f"y={d['y']!r} not in [0.0, {H_f}]"

        # Bbox size strictly positive (zero-area dropped) — Req 2.3a.
        assert 0.0 < d["w"] <= W_f, f"w={d['w']!r} not in (0.0, {W_f}]"
        assert 0.0 < d["h"] <= H_f, f"h={d['h']!r} not in (0.0, {H_f}]"


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
