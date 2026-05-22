"""
Property test for schema parity QNN ↔ DirectML.

Feature: npu-qnn-provider, Property 2: Schema parity QNN ↔ DirectML

Validates: Requirements 2.6, 9.2

This property checks that for any valid BGR frame, the Detection_Dict instances
returned by ``QNNProvider.infer`` and ``DirectMLProvider.infer`` carry the same
set of keys. Numerical equality is **not** asserted — FP16 (QNN) and FP32
(DirectML) post-processing legitimately produce different bbox values.

Both providers are mocked at the ONNX Runtime layer so the test runs on x86_64
CI hosts without ``onnxruntime-qnn`` installed.

Per gap-resolution #3, both detection lists are sorted by
``(class_id, confidence)`` before comparison. Per the task instructions, when
the sorted lengths differ (e.g. NMS or the QNN zero-area drop yields different
counts), schema parity is asserted only on the prefix of common length —
this is schema parity, not count parity.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

# Ensure the project root is on sys.path so ``engines`` resolves the same way
# the rest of the test suite relies on.
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from engines.directml_provider import DirectMLProvider  # noqa: E402
from engines.qnn_provider import QNNProvider  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IMGSZ = 416
CONF = 0.55

# Canonical Detection_Dict key set per Req 2.2.
_DETECTION_KEYS = frozenset({"class_id", "confidence", "x", "y", "w", "h"})


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------


@st.composite
def _bgr_frame_strategy(draw) -> np.ndarray:
    """Generate a BGR ``uint8`` frame of shape ``(H, W, 3)``.

    ``H, W`` are drawn from ``[IMGSZ, 4 * IMGSZ]`` per Req 9.1 / 9.2. Pixel
    content is uniformly distributed; we use a numpy ``Generator`` seeded by a
    drawn integer rather than ``hnp.arrays`` so frame construction is O(H*W*3)
    in numpy C, not in Python — at 4*IMGSZ on each axis the latter takes
    seconds per example.
    """
    h = draw(st.integers(min_value=IMGSZ, max_value=4 * IMGSZ))
    w = draw(st.integers(min_value=IMGSZ, max_value=4 * IMGSZ))
    seed = draw(st.integers(min_value=0, max_value=2**31 - 1))
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)


@st.composite
def _model_output_strategy(draw) -> np.ndarray:
    """Generate a YOLO ``(1, 6, N)`` raw output tensor in FP32.

    Channels: ``[cx, cy, w, h, cls0_conf, cls1_conf]`` in model-input pixel
    space (range ``[0, IMGSZ]`` for the box geometry, ``[0, 1]`` for class
    confidences). ``N`` is drawn from ``[0, 200]`` per the design strategy
    sketch. A small fraction of bbox values are pushed slightly out-of-bounds
    so the QNN clamp + zero-area-drop branches are exercised.

    The tensor is FP32; the per-provider mocks cast to the appropriate dtype
    before handing it to ``postprocess``.
    """
    n = draw(st.integers(min_value=0, max_value=200))
    if n == 0:
        return np.zeros((1, 6, 0), dtype=np.float32)

    seed = draw(st.integers(min_value=0, max_value=2**31 - 1))
    rng = np.random.default_rng(seed)

    # Bbox geometry — slightly wider than [0, IMGSZ] so a fraction lands
    # outside and the QNN clamp branch fires; zero-area boxes are possible
    # via this distribution and exercise the silent-drop path.
    cx = rng.uniform(-32.0, IMGSZ + 32.0, size=n).astype(np.float32)
    cy = rng.uniform(-32.0, IMGSZ + 32.0, size=n).astype(np.float32)
    bw = rng.uniform(0.0, IMGSZ + 32.0, size=n).astype(np.float32)
    bh = rng.uniform(0.0, IMGSZ + 32.0, size=n).astype(np.float32)

    # Class confidences in [0, 1]; with conf=0.55 about half pass on average.
    cls0 = rng.uniform(0.0, 1.0, size=n).astype(np.float32)
    cls1 = rng.uniform(0.0, 1.0, size=n).astype(np.float32)

    return np.stack([cx, cy, bw, bh, cls0, cls1], axis=0)[None, ...]


# ---------------------------------------------------------------------------
# Provider construction with mocked ORT layer
# ---------------------------------------------------------------------------


def _make_qnn_provider(model_output_fp32: np.ndarray) -> QNNProvider:
    """Build a ``QNNProvider`` ready for ``.infer()`` with a mocked ORT layer.

    ``QNNProvider.load`` is bypassed because (a) it requires a real
    ``onnxruntime-qnn`` install and a Hexagon NPU, and (b) the property under
    test is about ``infer``'s output schema, not about session construction.
    Instead we construct the provider, then attach the post-load attributes
    (``session``, ``_io_binding``, ``_input_buffer``, ``_resize_buffer``,
    ``input_name``, ``output_names``, ``provider_used``) directly so that
    ``preprocess`` and ``infer`` can run end-to-end on x86_64.
    """
    provider = QNNProvider("/nonexistent.onnx", imgsz=IMGSZ, conf=CONF)

    # Pre-allocated buffers as load() would have created.
    provider._resize_buffer = np.empty((IMGSZ, IMGSZ, 3), dtype=np.uint8)
    provider._input_buffer = np.empty((1, 3, IMGSZ, IMGSZ), dtype=np.float16)

    # Mocked ORT objects. ``copy_outputs_to_cpu`` returns a list of arrays;
    # we cast the FP32 reference output to FP16 to mirror the QNN HTP path.
    binding = MagicMock()
    binding.synchronize_inputs = MagicMock(return_value=None)
    binding.copy_outputs_to_cpu = MagicMock(
        return_value=[model_output_fp32.astype(np.float16)]
    )
    session = MagicMock()
    session.run_with_iobinding = MagicMock(return_value=None)

    provider.session = session
    provider._io_binding = binding
    provider._input_ortvalue = MagicMock()
    provider.input_name = "images"
    provider.output_names = ["output0"]
    provider.provider_used = "QNNExecutionProvider"
    return provider


def _make_dml_provider(model_output_fp32: np.ndarray) -> DirectMLProvider:
    """Build a ``DirectMLProvider`` ready for ``.infer()`` with a mocked ORT layer."""
    provider = DirectMLProvider("/nonexistent.onnx", imgsz=IMGSZ, conf=CONF)

    session = MagicMock()
    # DirectMLProvider.infer calls ``session.run(output_names, feeds)``.
    session.run = MagicMock(return_value=[model_output_fp32.astype(np.float32)])

    provider.session = session
    provider.input_name = "images"
    provider.output_names = ["output0"]
    provider._provider_used = "DmlExecutionProvider"
    return provider


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@given(
    frame=_bgr_frame_strategy(),
    model_output=_model_output_strategy(),
)
@settings(
    max_examples=100,
    # Frame generation up to 1664x1664x3 uint8 plus two cv2.resize / NMS passes
    # per example pushes the per-example wall-clock above the default Hypothesis
    # warning threshold; the work is real numpy/OpenCV, not Python loops.
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    deadline=None,
)
def test_property_2_schema_parity_qnn_directml(
    frame: np.ndarray, model_output: np.ndarray
) -> None:
    """Feature: npu-qnn-provider, Property 2: Schema parity QNN ↔ DirectML.

    For any drawn frame and model output, the Detection_Dict instances produced
    by ``QNNProvider.infer`` and ``DirectMLProvider.infer`` carry equal key
    sets when paired by their ``(class_id, confidence)`` sort order. Numerical
    equality is intentionally **not** asserted — FP16 vs FP32 differs by design.
    """
    qnn_provider = _make_qnn_provider(model_output)
    dml_provider = _make_dml_provider(model_output)

    qnn_dets, qnn_ms = qnn_provider.infer(frame)
    dml_dets, dml_ms = dml_provider.infer(frame)

    # Both providers must return (list, non-negative-float).
    assert isinstance(qnn_dets, list)
    assert isinstance(dml_dets, list)
    assert isinstance(qnn_ms, float) and qnn_ms >= 0.0
    assert isinstance(dml_ms, float) and dml_ms >= 0.0

    # Sort by (class_id, confidence) per gap-resolution #3.
    def _sort_key(d: dict):
        return (d["class_id"], d["confidence"])

    qnn_sorted = sorted(qnn_dets, key=_sort_key)
    dml_sorted = sorted(dml_dets, key=_sort_key)

    # Schema parity, not count parity: compare the prefix of common length.
    # If NMS / the QNN zero-area drop yield different counts, the trailing
    # tail of the longer list is ignored (this is Property 2's contract).
    common_n = min(len(qnn_sorted), len(dml_sorted))
    for i in range(common_n):
        qnn_keys = set(qnn_sorted[i].keys())
        dml_keys = set(dml_sorted[i].keys())
        assert qnn_keys == dml_keys, (
            f"Schema mismatch at sorted index {i}: "
            f"qnn_keys={qnn_keys!r} vs dml_keys={dml_keys!r}"
        )
        # Both providers must also match the canonical six-key set (Req 2.2).
        assert qnn_keys == _DETECTION_KEYS, (
            f"QNN detection at index {i} has non-canonical keys: {qnn_keys!r}"
        )
        assert dml_keys == _DETECTION_KEYS, (
            f"DML detection at index {i} has non-canonical keys: {dml_keys!r}"
        )
