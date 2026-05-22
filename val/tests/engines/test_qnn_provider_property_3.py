"""
Property test for QNNProvider preprocess tensor invariants.

Feature: npu-qnn-provider, Property 3: Preprocess tensor invariants

Validates: Requirements 2.7

The property asserts that after every call to ``QNNProvider.preprocess(frame)`` the
pre-allocated input buffer continues to satisfy the contract demanded by Req 2.7:
    * shape ``(1, 3, imgsz, imgsz)``
    * dtype ``np.float16``
    * values normalized to ``[0.0, 1.0]``
    * **same Python object identity** as the buffer allocated at ``load()`` time
      — i.e. ``preprocess`` writes in place and never reallocates (gap-resolution #6).

QNN is not available on a typical x86_64 development host, so the test bypasses
``load()`` and directly seeds the pre-allocated buffers, exercising the pure
preprocess code path in isolation.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st
from hypothesis.extra import numpy as hnp

# Ensure the project root is on ``sys.path`` so ``engines`` imports the same way
# it does in the rest of the test suite.
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from engines.qnn_provider import QNNProvider  # noqa: E402


# ---------------------------------------------------------------------------
# Hypothesis strategies.
# ---------------------------------------------------------------------------

# Model input edge size used throughout the test. Matches the YOLO11n-416 default
# in ``QNNProvider.__init__``; kept as a module constant so the strategy and the
# provider construction agree.
_IMGSZ = 416


def bgr_frame_strategy(imgsz: int = _IMGSZ):
    """Generate a BGR ``uint8`` frame of shape ``(H, W, 3)`` with ``H, W ∈ [imgsz, 4*imgsz]``.

    Mirrors the strategy described in Req 9.1 / Property 1 so the QNN property
    suite shares a single frame generator across Properties 1, 2, and 3.
    """
    height = st.integers(min_value=imgsz, max_value=4 * imgsz)
    width = st.integers(min_value=imgsz, max_value=4 * imgsz)
    return st.builds(
        lambda h, w: np.random.randint(0, 256, size=(h, w, 3), dtype=np.uint8),
        height,
        width,
    )


# ---------------------------------------------------------------------------
# Fixture — one provider per test session, buffers seeded as load() would.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def seeded_provider() -> QNNProvider:
    """Construct a ``QNNProvider`` and pre-seed the buffers ``load()`` would build.

    ``QNNExecutionProvider`` is not available on a typical x86_64 development
    host, so calling ``load()`` here would short-circuit to ``False`` without
    allocating buffers. The task explicitly directs us to bypass ``load()`` and
    seed ``_input_buffer`` / ``_resize_buffer`` ourselves so the pure preprocess
    code path (Req 2.7) is exercised in isolation.
    """
    provider = QNNProvider("models/v11n-416-2.onnx", imgsz=_IMGSZ, conf=0.55)
    provider._resize_buffer = np.empty((_IMGSZ, _IMGSZ, 3), dtype=np.uint8)
    provider._input_buffer = np.empty(
        (1, 3, _IMGSZ, _IMGSZ), dtype=np.float16
    )
    return provider


# ---------------------------------------------------------------------------
# Property test.
# ---------------------------------------------------------------------------


@given(frame=bgr_frame_strategy())
@settings(max_examples=100)
def test_preprocess_tensor_invariants(seeded_provider: QNNProvider, frame: np.ndarray) -> None:
    """Feature: npu-qnn-provider, Property 3: Preprocess tensor invariants.

    For every drawn BGR frame, ``preprocess(frame)`` must:
        * leave ``_input_buffer.shape == (1, 3, imgsz, imgsz)``,
        * leave ``_input_buffer.dtype == np.float16``,
        * produce values clamped to the unit interval ``[0.0, 1.0]``,
        * preserve the Python object identity of ``_input_buffer`` from before the
          call (no reallocation — preprocess writes in place per gap-resolution #6).

    Validates: Requirements 2.7.
    """
    # Snapshot the buffer identity before each draw — this is the post-load id
    # that the in-place contract must preserve across every preprocess call.
    pre_id = id(seeded_provider._input_buffer)

    seeded_provider.preprocess(frame)

    buf = seeded_provider._input_buffer

    # Shape contract.
    assert buf.shape == (1, 3, _IMGSZ, _IMGSZ), (
        f"expected shape (1, 3, {_IMGSZ}, {_IMGSZ}); got {buf.shape}"
    )

    # Dtype contract.
    assert buf.dtype == np.float16, f"expected dtype float16; got {buf.dtype}"

    # Range contract — values divided by 255 from a uint8 source must lie in [0, 1].
    buf_min = float(buf.min())
    buf_max = float(buf.max())
    assert 0.0 <= buf_min, f"_input_buffer.min()={buf_min} below 0.0"
    assert buf_max <= 1.0, f"_input_buffer.max()={buf_max} above 1.0"

    # Identity contract — the in-place preprocess must reuse the same buffer.
    assert id(buf) == pre_id, (
        "QNNProvider.preprocess reallocated _input_buffer "
        "(violates gap-resolution #6 / Req 2.7 in-place write)"
    )
