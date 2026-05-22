"""
Property test for QNNProvider release idempotence.

Feature: npu-qnn-provider, Property 8: QNNProvider release idempotence
Validates: Requirements 1.8, 1.8b, 8.3, 8.4

The property generates arbitrary finite sequences of ``"load"`` and ``"release"``
operations against a freshly constructed :class:`engines.qnn_provider.QNNProvider`
and asserts:

* No call in the sequence raises an exception.
* After every ``release()`` invocation, the provider's session-owned references —
  ``session``, ``_io_binding``, ``_input_ortvalue``, ``_input_buffer``, and
  ``_resize_buffer`` — are all ``None``.

This guarantees the lifecycle defined by Requirements 1.8 (idempotent release),
1.8b (cross-thread tolerance), 8.3 (same-thread completion), and 8.4 (foreign-thread
no-raise drop). The companion parametrized test exercises the cross-thread case by
invoking ``release()`` from a worker :class:`threading.Thread`.

The entire ONNX Runtime layer is replaced by a :class:`unittest.mock.MagicMock`
installed at ``sys.modules["onnxruntime"]`` so ``load()`` succeeds deterministically
on x86_64 CI hosts where the QNN execution provider is not available. The HTP
backend resolver is patched to return a non-``None`` path and ``os.path.exists`` is
patched to ``True`` so ``load()`` proceeds past its file/availability gates without
touching the filesystem.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import List, Tuple
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

# Ensure the project root is on ``sys.path`` so ``engines.qnn_provider`` imports the
# same way the rest of the test suite does.
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from engines.qnn_provider import QNNProvider  # noqa: E402


# ---------------------------------------------------------------------------
# Mocked ONNX Runtime layer.
# ---------------------------------------------------------------------------


def _build_onnxruntime_mock() -> Tuple[MagicMock, MagicMock]:
    """Construct a ``MagicMock`` that stands in for ``onnxruntime`` during ``load()``.

    The shape of the mock is just enough to satisfy every attribute access made by
    :meth:`QNNProvider.load` so the function returns ``True`` without touching real
    ONNX Runtime. Returns ``(ort_mock, session_mock)``; the session mock is also
    available as ``ort_mock.InferenceSession.return_value`` if a caller wants to
    introspect calls.
    """
    ort = MagicMock(name="onnxruntime")

    # Provider availability gate (Req 1.2 prereq, Req 6.1).
    ort.get_available_providers.return_value = ["QNNExecutionProvider"]

    # SessionOptions and the two enum tokens read by load() are accessed by
    # attribute on the ``ort`` namespace; MagicMock auto-creates them, but we
    # set explicit values to avoid surprises if attribute equality is asserted
    # downstream.
    ort.SessionOptions.return_value = MagicMock(name="SessionOptions")
    ort.GraphOptimizationLevel.ORT_ENABLE_ALL = "ORT_ENABLE_ALL"
    ort.ExecutionMode.ORT_SEQUENTIAL = "ORT_SEQUENTIAL"

    # InferenceSession metadata. ``load()`` reads:
    #   session.get_inputs()[0].name
    #   [o.name for o in session.get_outputs()]
    #   session.get_providers()[0]  # asserted == "QNNExecutionProvider"
    session = MagicMock(name="InferenceSession")
    input_meta = MagicMock(name="input_meta")
    input_meta.name = "images"
    session.get_inputs.return_value = [input_meta]
    output_meta = MagicMock(name="output_meta")
    output_meta.name = "output0"
    session.get_outputs.return_value = [output_meta]
    session.get_providers.return_value = ["QNNExecutionProvider"]
    ort.InferenceSession.return_value = session

    # OrtValue used to wrap the pre-allocated FP16 input buffer. The first call
    # path (with ``"qnn", 0`` device kwargs) and the pinned-host fallback both
    # return the same mock, which is sufficient to satisfy IO binding setup.
    ortvalue = MagicMock(name="OrtValue")
    ort.OrtValue.ortvalue_from_numpy.return_value = ortvalue

    # IOBinding methods called inside the warmup loop.
    io_binding = MagicMock(name="IOBinding")
    session.io_binding.return_value = io_binding

    return ort, session


# ---------------------------------------------------------------------------
# Helpers shared between the property test and the cross-thread companion.
# ---------------------------------------------------------------------------


_RELEASE_NULLED_ATTRS = (
    "session",
    "_io_binding",
    "_input_ortvalue",
    "_input_buffer",
    "_resize_buffer",
)


def _assert_post_release_state(provider: QNNProvider) -> None:
    """Assert every session-owned reference is ``None`` after ``release()``."""
    for attr in _RELEASE_NULLED_ATTRS:
        actual = getattr(provider, attr)
        assert actual is None, (
            f"after release(), provider.{attr} expected None, got {actual!r}"
        )


def _apply_op(provider: QNNProvider, op: str) -> None:
    """Dispatch ``"load"`` or ``"release"`` to the provider."""
    if op == "load":
        provider.load()
    elif op == "release":
        provider.release()
    else:  # pragma: no cover — strategy is closed over the two literals
        raise AssertionError(f"unexpected op {op!r}")


# ---------------------------------------------------------------------------
# Property test — arbitrary load/release sequences.
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    ops=st.lists(
        st.sampled_from(["load", "release"]),
        min_size=0,
        max_size=8,
    ),
)
def test_qnn_provider_release_is_idempotent_under_arbitrary_call_sequences(
    ops: List[str],
) -> None:
    """Feature: npu-qnn-provider, Property 8: QNNProvider release idempotence.

    For every drawn sequence of ``load`` / ``release`` operations, replay the
    sequence against a freshly constructed :class:`QNNProvider` with the
    onnxruntime layer mocked. Assert that no call raises and that after every
    ``release()`` the provider's session-owned references are all ``None``.

    Validates: Requirements 1.8 (idempotent release; ``release()`` callable when
    ``load()`` never ran or after a previous ``release()``), 1.8b (cross-thread
    tolerance — exercised in the companion parametrized test), 8.3 (same-thread
    release completes without raising), 8.4 (state drop is unconditional).
    """
    ort_mock, _session = _build_onnxruntime_mock()

    with (
        patch.dict(sys.modules, {"onnxruntime": ort_mock}),
        patch(
            "engines.qnn_provider._resolve_htp_backend_path",
            return_value="/mock/QnnHtp.dll",
        ),
        patch.object(os.path, "exists", return_value=True),
    ):
        provider = QNNProvider("/mock/model.onnx", imgsz=4, conf=0.55)
        for op in ops:
            _apply_op(provider, op)
            if op == "release":
                _assert_post_release_state(provider)


# ---------------------------------------------------------------------------
# Cross-thread companion — Reqs 1.8b, 8.4.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "preceded_by_load",
    [
        pytest.param(True, id="release-after-load"),
        pytest.param(False, id="release-without-load"),
    ],
)
def test_qnn_provider_release_from_worker_thread_does_not_raise(
    preceded_by_load: bool,
) -> None:
    """Feature: npu-qnn-provider, Property 8 (cross-thread case).

    Per Requirements 1.8b and 8.4, calling ``release()`` from a thread other
    than the one that performed ``load()`` must drop the session reference
    idempotently and never raise. This companion test exercises the cross-
    thread path explicitly — the property test above runs entirely on the
    main thread, so without this case the foreign-thread guard would go
    untested.

    Both branches of the parametrization matter: the post-load case verifies
    the WARN-and-best-effort path through the foreign-thread guard, and the
    pre-load case verifies that ``release()`` is safe to call before
    ``load()`` ever ran (Req 1.8 idempotence boundary condition that also
    happens cross-thread).

    Validates: Requirements 1.8b, 8.4.
    """
    ort_mock, _session = _build_onnxruntime_mock()

    with (
        patch.dict(sys.modules, {"onnxruntime": ort_mock}),
        patch(
            "engines.qnn_provider._resolve_htp_backend_path",
            return_value="/mock/QnnHtp.dll",
        ),
        patch.object(os.path, "exists", return_value=True),
    ):
        provider = QNNProvider("/mock/model.onnx", imgsz=4, conf=0.55)
        if preceded_by_load:
            assert provider.load() is True, (
                "load() should succeed deterministically with the mocked ORT layer"
            )

        errors: List[BaseException] = []

        def _worker() -> None:
            try:
                provider.release()
            except BaseException as exc:  # noqa: BLE001 — we want to catch *anything*
                errors.append(exc)

        worker = threading.Thread(target=_worker, name="qnn-release-worker")
        worker.start()
        worker.join(timeout=5.0)

        assert not worker.is_alive(), "release() worker thread did not finish in time"
        assert not errors, (
            "release() raised from a worker thread: "
            f"{type(errors[0]).__name__}: {errors[0]}"
        )

        _assert_post_release_state(provider)
