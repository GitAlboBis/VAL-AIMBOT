"""
Unit/example tests for ``engines.qnn_provider.QNNProvider``.

Feature: npu-qnn-provider, Task 4.5 — QNNProvider unit tests.

These tests exercise the QNN provider's lifecycle (construction validation, ``load``
guard rails, three-inference warmup, ``release`` idempotence and threading
relaxation) and the HTP burst configuration plumbing — all without requiring an
ONNX Runtime install. ``onnxruntime`` is stubbed via ``sys.modules`` so the suite
runs on x86_64 development hosts. See the spec at
``.kiro/specs/npu-qnn-provider/{requirements,design,tasks}.md`` for the contract
each test validates.

Each test annotates the requirement(s) it validates per the task definition
in ``.kiro/specs/npu-qnn-provider/tasks.md``.
"""

from __future__ import annotations

import builtins
import importlib
import logging
import sys
import threading
import time
from typing import Tuple
from unittest.mock import MagicMock

import numpy as np
import pytest

from engines.qnn_provider import QNNProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_model_path(tmp_path) -> str:
    """A real on-disk path that ``os.path.exists`` returns ``True`` for."""
    p = tmp_path / "fake_model.onnx"
    p.write_bytes(b"\x00")
    return str(p)


def _build_mock_ort(output_tensor: np.ndarray) -> Tuple[MagicMock, MagicMock, MagicMock]:
    """
    Construct a structurally complete ``onnxruntime`` MagicMock.

    Returns:
        ``(mock_ort, mock_session, mock_io_binding)`` so tests can assert on call
        counts and arguments without re-traversing the mock graph.
    """
    mock_ort = MagicMock(name="mock_onnxruntime")

    # SessionOptions: each call yields a fresh sub-mock (so .graph_optimization_level etc.
    # assignments do not collide between tests sharing the fixture).
    mock_ort.SessionOptions.side_effect = lambda: MagicMock(name="SessionOptions")

    # Enum sentinels — values are arbitrary but must be present.
    mock_ort.GraphOptimizationLevel.ORT_ENABLE_ALL = "ORT_ENABLE_ALL"
    mock_ort.ExecutionMode.ORT_SEQUENTIAL = "ORT_SEQUENTIAL"

    # Available providers includes QNN by default.
    mock_ort.get_available_providers.return_value = [
        "QNNExecutionProvider",
        "CPUExecutionProvider",
    ]

    # Session.
    mock_session = MagicMock(name="InferenceSession")
    input_meta = MagicMock(name="InputMeta")
    input_meta.name = "images"
    mock_session.get_inputs.return_value = [input_meta]
    output_meta = MagicMock(name="OutputMeta")
    output_meta.name = "output0"
    mock_session.get_outputs.return_value = [output_meta]
    mock_session.get_providers.return_value = [
        "QNNExecutionProvider",
        "CPUExecutionProvider",
    ]

    # IOBinding — .copy_outputs_to_cpu() must return a list whose first element
    # is a tensor compatible with ``QNNProvider.postprocess``.
    mock_io_binding = MagicMock(name="IOBinding")
    mock_io_binding.copy_outputs_to_cpu.return_value = [output_tensor]
    mock_session.io_binding.return_value = mock_io_binding

    mock_ort.InferenceSession.return_value = mock_session

    # OrtValue.ortvalue_from_numpy returns a stub OrtValue regardless of args.
    mock_ortvalue = MagicMock(name="OrtValue")
    mock_ort.OrtValue.ortvalue_from_numpy.return_value = mock_ortvalue

    return mock_ort, mock_session, mock_io_binding


@pytest.fixture
def mock_qnn_runtime(monkeypatch, tmp_path):
    """
    Inject a MagicMock ``onnxruntime`` into ``sys.modules`` and patch the HTP
    backend path resolver to a real (but fake) on-disk file so
    ``QNNProvider.load()`` can run end-to-end with no ORT install.

    Yields ``(mock_ort, mock_session, mock_io_binding)``.
    """
    # All-zero output → postprocess returns [] (no spurious detections in tests).
    output_tensor = np.zeros((1, 6, 10), dtype=np.float32)
    mock_ort, mock_session, mock_io_binding = _build_mock_ort(output_tensor)

    # Inject the mock and remember any prior cached value so we can restore it.
    saved = sys.modules.get("onnxruntime")
    sys.modules["onnxruntime"] = mock_ort

    # Patch HTP DLL resolution to a real on-disk file (so the ``os.path.exists``
    # gate in the loader passes without depending on a real Snapdragon X host).
    fake_dll = tmp_path / "QnnHtp.dll"
    fake_dll.write_bytes(b"fake")
    import engines.qnn_provider as qnn_mod
    monkeypatch.setattr(
        qnn_mod, "_resolve_htp_backend_path", lambda: str(fake_dll)
    )

    try:
        yield mock_ort, mock_session, mock_io_binding
    finally:
        if saved is None:
            sys.modules.pop("onnxruntime", None)
        else:
            sys.modules["onnxruntime"] = saved


# ---------------------------------------------------------------------------
# load() — error paths
# ---------------------------------------------------------------------------


class TestQNNLoadErrorPaths:
    """``load()`` returns False (does not raise) for every recoverable failure mode."""

    def test_qnn_load_returns_false_when_provider_missing(
        self, mock_qnn_runtime, fake_model_path, caplog
    ):
        """Validates: Requirements 1.2 (prereq), 6.1 — skip without invoking session.

        When ``QNNExecutionProvider`` is not in
        ``onnxruntime.get_available_providers()``, ``load()`` returns ``False`` and
        ``InferenceSession`` is never invoked.
        """
        mock_ort, mock_session, _ = mock_qnn_runtime
        # QNN not in the provider list → loader must skip.
        mock_ort.get_available_providers.return_value = [
            "DmlExecutionProvider", "CPUExecutionProvider"
        ]

        provider = QNNProvider(fake_model_path, imgsz=416, conf=0.55)
        with caplog.at_level(logging.INFO, logger="engines.qnn_provider"):
            result = provider.load()

        assert result is False
        # Session never constructed when QNN is absent.
        assert mock_ort.InferenceSession.call_count == 0
        # State is consistent with "never loaded".
        assert provider.session is None
        assert provider.provider_used == "none"

    def test_qnn_load_returns_false_when_model_missing(
        self, mock_qnn_runtime, tmp_path, caplog
    ):
        """Validates: Requirement 1.4 — ERROR log includes the missing path."""
        missing_path = str(tmp_path / "definitely-not-here.onnx")
        provider = QNNProvider(missing_path, imgsz=416, conf=0.55)

        with caplog.at_level(logging.ERROR, logger="engines.qnn_provider"):
            result = provider.load()

        assert result is False
        # The missing path must appear in the ERROR record, so operators can
        # locate the expected model file.
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert any(missing_path in r.getMessage() for r in error_records), (
            f"Expected an ERROR log mentioning the missing path {missing_path!r}; "
            f"got {[r.getMessage() for r in caplog.records]}"
        )

    def test_qnn_load_returns_false_when_onnxruntime_not_importable(
        self, monkeypatch, fake_model_path, caplog
    ):
        """Validates: Requirement 1.5 — install hint mentions ``pip install onnxruntime-qnn``."""
        # Block the ``import onnxruntime`` performed lazily inside ``load()``.
        # Even on hosts where onnxruntime is *not* installed, this guard makes the
        # behaviour deterministic across CI runners.
        sys.modules.pop("onnxruntime", None)
        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "onnxruntime":
                raise ImportError("blocked for test")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked_import)

        provider = QNNProvider(fake_model_path, imgsz=416, conf=0.55)
        with caplog.at_level(logging.INFO, logger="engines.qnn_provider"):
            result = provider.load()

        assert result is False
        assert any(
            "pip install onnxruntime-qnn" in r.getMessage()
            for r in caplog.records
        ), (
            f"Expected an INFO record with the install hint, got "
            f"{[r.getMessage() for r in caplog.records]}"
        )

    def test_qnn_load_session_exception_returns_false_with_no_npu_in_log(
        self, mock_qnn_runtime, fake_model_path, caplog
    ):
        """Validates: Requirements 1.6, 6.2 — ``no NPU detected`` substring preserved."""
        mock_ort, _, _ = mock_qnn_runtime
        mock_ort.InferenceSession.side_effect = RuntimeError("no NPU detected")

        provider = QNNProvider(fake_model_path, imgsz=416, conf=0.55)
        with caplog.at_level(logging.ERROR, logger="engines.qnn_provider"):
            result = provider.load()

        assert result is False
        # Message text must surface the underlying ORT error so EP_Selector can
        # match the ``no NPU detected`` substring per Req 6.2.
        assert "no NPU detected" in caplog.text


# ---------------------------------------------------------------------------
# load() — happy path behaviour
# ---------------------------------------------------------------------------


class TestQNNLoadConfiguration:
    """``load()`` configures HTP burst mode and runs the warmup as designed."""

    def test_qnn_load_uses_burst_performance_mode(
        self, mock_qnn_runtime, fake_model_path
    ):
        """Validates: Requirement 1.2 — ``htp_performance_mode == 'burst'`` is hardcoded.

        Inspects the ``providers`` argument that was passed to
        ``InferenceSession`` and asserts that the QNN entry's options dict pins
        ``htp_performance_mode`` to ``burst`` (gap-resolution #1).
        """
        mock_ort, _, _ = mock_qnn_runtime

        provider = QNNProvider(fake_model_path, imgsz=416, conf=0.55)
        assert provider.load() is True

        assert mock_ort.InferenceSession.call_count == 1
        call_kwargs = mock_ort.InferenceSession.call_args.kwargs
        # The implementation passes ``providers`` as a kwarg.
        providers_arg = call_kwargs["providers"]
        # Cascade is [(QNN, opts), CPU].
        qnn_entry = providers_arg[0]
        assert qnn_entry[0] == "QNNExecutionProvider"
        provider_options = qnn_entry[1]
        assert provider_options["htp_performance_mode"] == "burst"
        # backend_path resolved from the fixture's fake DLL.
        assert provider_options["backend_path"].endswith("QnnHtp.dll")

    def test_qnn_warmup_runs_three_inferences(
        self, mock_qnn_runtime, fake_model_path
    ):
        """Validates: Requirement 1.7 — exactly three warmup inferences in ``load()``."""
        _, mock_session, _ = mock_qnn_runtime

        provider = QNNProvider(fake_model_path, imgsz=416, conf=0.55)
        assert provider.load() is True

        # Three warmup runs and zero user inferences yet.
        assert mock_session.run_with_iobinding.call_count == 3


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestQNNConstructorValidation:
    """``__init__`` enforces ``conf`` bounds (Req 2.4a)."""

    def test_qnn_init_rejects_conf_outside_unit_interval(self, fake_model_path):
        """Validates: Requirement 2.4a — ``ValueError`` references the offending value."""
        with pytest.raises(ValueError, match="1.5"):
            QNNProvider(fake_model_path, imgsz=416, conf=1.5)

        with pytest.raises(ValueError, match=r"-0\.1"):
            QNNProvider(fake_model_path, imgsz=416, conf=-0.1)


# ---------------------------------------------------------------------------
# release() — idempotence, threading, timing
# ---------------------------------------------------------------------------


class TestQNNRelease:
    """``release()`` lifecycle guarantees (Reqs 1.8, 1.8a, 1.8b, 8.3, 8.4)."""

    def test_qnn_release_is_idempotent_after_failed_load(self, fake_model_path):
        """Validates: Requirement 1.8 — release is safe before/without a successful load.

        Constructing the provider but never calling ``load()`` and then calling
        ``release()`` twice must not raise. Both calls are no-ops.
        """
        provider = QNNProvider(fake_model_path, imgsz=416, conf=0.55)
        # No load() call.
        provider.release()  # first call
        provider.release()  # second call — must remain a no-op
        # Final state: nothing held, public name reset.
        assert provider.session is None
        assert provider._io_binding is None
        assert provider._input_buffer is None
        assert provider._resize_buffer is None
        assert provider.provider_used == "none"

    def test_qnn_release_from_other_thread_warns_does_not_raise(
        self, mock_qnn_runtime, fake_model_path, caplog
    ):
        """Validates: Requirements 1.8b, 8.4 — cross-thread release is best-effort."""
        provider = QNNProvider(fake_model_path, imgsz=416, conf=0.55)
        assert provider.load() is True

        errors: list[BaseException] = []

        def worker():
            try:
                provider.release()
            except BaseException as e:  # noqa: BLE001 — capture anything for assertion
                errors.append(e)

        with caplog.at_level(logging.WARNING, logger="engines.qnn_provider"):
            t = threading.Thread(target=worker)
            t.start()
            t.join(timeout=5.0)

        assert not t.is_alive(), "release() blocked for >5s on a worker thread"
        assert errors == [], f"release() raised on worker thread: {errors!r}"
        # The cross-thread WARN must mention "thread".
        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("thread" in r.getMessage().lower() for r in warn_records), (
            f"Expected a WARN mentioning 'thread', got "
            f"{[r.getMessage() for r in warn_records]}"
        )

    def test_qnn_release_completes_under_2_seconds_budget(
        self, mock_qnn_runtime, fake_model_path
    ):
        """Validates: Requirements 1.8a, 8.3 — release finishes under 2 s on happy path."""
        provider = QNNProvider(fake_model_path, imgsz=416, conf=0.55)
        assert provider.load() is True

        t0 = time.perf_counter()
        provider.release()
        elapsed = time.perf_counter() - t0
        assert elapsed < 2.0, f"release() took {elapsed:.3f}s (budget 2.0s)"

    def test_qnn_release_drops_session_silently_on_attr_error(
        self, monkeypatch, mock_qnn_runtime, fake_model_path, caplog
    ):
        """Validates: Requirement 1.8 + gap-resolution #2 — exceptions during teardown
        are swallowed; the provider still ends up in a clean state.

        Hooks ``__setattr__`` to raise *after* assigning the value to
        ``_resize_buffer`` (the last drop step). The exception must be caught and
        logged, the ``provider_used = "none"`` reset in ``finally`` must still
        execute, and every dropped field must be ``None``.
        """
        provider = QNNProvider(fake_model_path, imgsz=416, conf=0.55)
        assert provider.load() is True

        original_setattr = QNNProvider.__setattr__
        raised = {"flag": False}

        def patched_setattr(self, name, value):
            # Set first, then raise *once* on the dedicated drop step. Setting
            # before raising preserves the "all fields None" final-state assertion
            # below; raising once keeps the ``finally`` reset unobstructed.
            original_setattr(self, name, value)
            if (
                self is provider
                and name == "_resize_buffer"
                and value is None
                and not raised["flag"]
            ):
                raised["flag"] = True
                raise RuntimeError("attr_error_test")

        monkeypatch.setattr(QNNProvider, "__setattr__", patched_setattr)

        with caplog.at_level(logging.WARNING, logger="engines.qnn_provider"):
            # Must not raise — the implementation catches and logs at WARN.
            provider.release()

        # The intentional teardown error was logged at WARN.
        assert any(
            "attr_error_test" in r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING
        ), (
            f"Expected a WARN containing 'attr_error_test', got "
            f"{[r.getMessage() for r in caplog.records]}"
        )

        # Final state: all dropped fields are None and the public name is reset.
        assert provider.session is None
        assert provider._io_binding is None
        assert provider._input_ortvalue is None
        assert provider._input_buffer is None
        assert provider._resize_buffer is None
        assert provider.provider_used == "none"


# ---------------------------------------------------------------------------
# infer() — buffer reuse and exception passthrough
# ---------------------------------------------------------------------------


class TestQNNInfer:
    """``infer()`` invariants for the steady-state hot path."""

    def test_qnn_infer_reuses_preallocated_buffer(
        self, mock_qnn_runtime, fake_model_path
    ):
        """Validates: gap-resolution #6 — ``_input_buffer`` is allocated once.

        Records ``id(provider._input_buffer)`` after ``load()`` and asserts the
        identity is unchanged after 100 ``infer()`` calls — the FP16 NCHW tensor
        is overwritten in place via ``np.divide(..., out=...)`` rather than
        re-allocated per frame.
        """
        provider = QNNProvider(fake_model_path, imgsz=416, conf=0.55)
        assert provider.load() is True

        initial_id = id(provider._input_buffer)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        for _ in range(100):
            provider.infer(frame)

        assert id(provider._input_buffer) == initial_id

    def test_qnn_infer_reuses_preallocated_resize_buffer(
        self, mock_qnn_runtime, fake_model_path
    ):
        """Validates: gap-resolution #6 — ``_resize_buffer`` identity invariant."""
        provider = QNNProvider(fake_model_path, imgsz=416, conf=0.55)
        assert provider.load() is True

        initial_id = id(provider._resize_buffer)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        for _ in range(100):
            provider.infer(frame)

        assert id(provider._resize_buffer) == initial_id

    def test_qnn_infer_reraises_provider_exceptions(
        self, mock_qnn_runtime, fake_model_path
    ):
        """Validates: Requirement 6.4 — provider exceptions propagate from ``infer()``.

        ``QNNProvider.infer()`` does *not* swallow inference-time errors;
        ``AIVisionEngine._process_qnn`` is responsible for wrapping them in
        ``AIEngineException``.
        """
        _, mock_session, _ = mock_qnn_runtime
        provider = QNNProvider(fake_model_path, imgsz=416, conf=0.55)
        assert provider.load() is True

        # Now make the next session run blow up.
        mock_session.run_with_iobinding.side_effect = RuntimeError("inference exploded")

        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        with pytest.raises(RuntimeError, match="inference exploded"):
            provider.infer(frame)


# ---------------------------------------------------------------------------
# Module import semantics
# ---------------------------------------------------------------------------


class TestQNNProviderModuleImport:
    """The module must not import ``onnxruntime`` at import time (Req 7.5)."""

    def test_qnn_provider_does_not_import_onnxruntime_at_module_import(self):
        """Validates: Requirement 7.5 — lazy import of ``onnxruntime``.

        Importing ``engines.qnn_provider`` from a clean ``sys.modules`` must not
        cause ``onnxruntime`` to appear in ``sys.modules``. The provider
        deferred-imports ORT inside ``load()`` and the diagnostics helpers, so a
        host without ORT installed can still ``import engines.qnn_provider``.
        """
        # Snapshot any cached entries so we can restore them on teardown.
        saved_ort = sys.modules.pop("onnxruntime", None)
        saved_qnn_mod = sys.modules.pop("engines.qnn_provider", None)
        try:
            importlib.import_module("engines.qnn_provider")
            assert "onnxruntime" not in sys.modules, (
                "engines.qnn_provider must not import onnxruntime at module import "
                "time (Req 7.5)"
            )
        finally:
            # Restore prior state so subsequent tests see the module they expected.
            sys.modules.pop("engines.qnn_provider", None)
            if saved_qnn_mod is not None:
                sys.modules["engines.qnn_provider"] = saved_qnn_mod
            else:
                # Re-import so the rest of the suite still has a working module.
                importlib.import_module("engines.qnn_provider")
            if saved_ort is not None:
                sys.modules["onnxruntime"] = saved_ort
