"""
Unit/example tests for ``AIVisionEngine`` QNN integration.

Feature: npu-qnn-provider, Task 6.4 — AIVisionEngine QNN integration tests.

These tests exercise the engine-level wiring around the QNN execution provider:
the cascade-driven backend selection, ``process_frame`` dispatch to
``_process_qnn``, ``update_config`` confidence propagation (and rejection of
out-of-range values), ``release`` plumbing, the once-per-process WARN/INFO
latches for QNN/DirectML coexistence and the arm64 install hint, and the
strict-equality contract on ``shared_state["ai_backend"]`` after a pinned-QNN
failure.

All tests run on x86_64 development hosts: the ONNX Runtime, QNN, and
DirectML imports are either stubbed via ``sys.modules`` or short-circuited
through ``monkeypatch.setattr`` before they are reached. No real model file,
NPU, or GPU is required.

Each test is annotated with the requirement(s) it validates per the task
definition in ``.kiro/specs/npu-qnn-provider/tasks.md``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

import engines.ai_engine as ai_engine_module
from engines.ai_engine import AIVisionEngine, Detection
from exceptions import AIEngineException
from gui.shared_state import SharedState


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_module_latches(monkeypatch):
    """Reset the once-per-process WARN/INFO latches between tests.

    ``engines.ai_engine`` keeps two module-level booleans
    (``_qnn_dml_coexistence_warned`` and ``_qnn_hint_emitted``) so the
    coexistence WARN and the arm64 install hint each fire exactly once per
    process. Tests that count log records depend on these flags starting
    in the unset state, so we reset them at the top of every test via
    ``monkeypatch`` (which restores the original values on teardown).
    """
    monkeypatch.setattr(
        ai_engine_module, "_qnn_dml_coexistence_warned", False, raising=True
    )
    monkeypatch.setattr(
        ai_engine_module, "_qnn_hint_emitted", False, raising=True
    )


@pytest.fixture
def fake_onnx_path(tmp_path) -> str:
    """A real on-disk ``.onnx`` file so ``_find_model`` resolves it."""
    p = tmp_path / "fake_model.onnx"
    p.write_bytes(b"\x00")
    return str(p)


@pytest.fixture
def base_config(fake_onnx_path) -> Dict[str, Any]:
    """Minimal valid AIVisionEngine config pointing at ``fake_onnx_path``."""
    return {
        "enabled": True,
        "model_path": fake_onnx_path,
        "confidence": 0.55,
        "iou_threshold": 0.45,
        "capture_size": 320,
        "headshot_bias": 0.30,
        "target_classes": [0],
        "execution_provider": "auto",
    }


@pytest.fixture
def shared_state() -> SharedState:
    """A ``SharedState`` with no error handler — sufficient for these tests."""
    return SharedState(error_handler=None)


@pytest.fixture
def valid_frame(base_config) -> np.ndarray:
    """A BGR uint8 frame matching ``base_config['capture_size']``."""
    size = base_config["capture_size"]
    return np.zeros((size, size, 3), dtype=np.uint8)


def _make_qnn_provider_mock(conf: float = 0.55) -> MagicMock:
    """Build a mock ``QNNProvider`` exposing the attributes the engine touches."""
    provider = MagicMock(name="QNNProviderMock")
    provider.conf = conf
    provider.provider_name = "QNNExecutionProvider"
    # ``infer`` returns ``(detections_list, elapsed_ms)`` per Req 2.1.
    provider.infer.return_value = ([], 1.0)
    provider.load.return_value = True
    return provider


def _patch_select_provider_to_qnn(
    monkeypatch, qnn_provider: MagicMock
) -> MagicMock:
    """Patch ``engines.ep_selector.select_provider`` to return ``(qnn_provider, "qnn")``.

    ``AIVisionEngine.load_model`` imports ``select_provider`` lazily inside
    the method body via ``from engines.ep_selector import select_provider``,
    so the patch must target the attribute on the ``engines.ep_selector``
    module (the lazy import re-binds against the module each time).
    """
    import engines.ep_selector as ep_selector_module

    selector_mock = MagicMock(
        name="select_provider", return_value=(qnn_provider, "qnn")
    )
    monkeypatch.setattr(ep_selector_module, "select_provider", selector_mock)
    return selector_mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAIEngineBackendName:
    """Backend identifier surfaces through ``backend_name`` and shared state."""

    def test_ai_engine_backend_name_qnn_when_active(
        self,
        monkeypatch,
        base_config,
        shared_state,
    ):
        """Validates: Requirements 5.1, 5.4, 5.4a — backend strict equality.

        After ``load_model`` selects QNN through the cascade, ``backend_name``
        equals ``"qnn"`` and ``shared_state["ai_backend"]`` equals ``"qnn"``.
        """
        # Force the host_arch path so the cascade's arm64 branch is taken.
        monkeypatch.setattr(
            ai_engine_module, "_normalize_host_arch", lambda: "arm64"
        )
        monkeypatch.setattr(
            ai_engine_module,
            "_snapshot_available_providers",
            lambda: ["QNNExecutionProvider", "CPUExecutionProvider"],
        )
        qnn_provider = _make_qnn_provider_mock()
        _patch_select_provider_to_qnn(monkeypatch, qnn_provider)

        engine = AIVisionEngine(base_config, shared_state=shared_state)
        result = engine.load_model()

        assert result is True
        assert engine.backend_name == "qnn"
        # Strict-equality contract on shared state (Req 5.4a).
        assert shared_state.get_state("ai_backend") == "qnn"
        # The provider was attached on the right slot.
        assert engine._qnn_provider is qnn_provider


class TestAIEngineHealthStatus:
    """``get_health_status`` exposes QNN-specific keys when the backend is QNN."""

    def test_ai_engine_health_status_includes_execution_provider_and_htp_mode(
        self,
        monkeypatch,
        base_config,
        shared_state,
    ):
        """Validates: Requirement 5.3 — execution_provider and htp_performance_mode.

        When the active backend is ``qnn``, the dict returned by
        ``get_health_status()`` includes ``execution_provider ==
        "QNNExecutionProvider"`` and ``htp_performance_mode == "burst"``.
        """
        monkeypatch.setattr(
            ai_engine_module, "_normalize_host_arch", lambda: "arm64"
        )
        monkeypatch.setattr(
            ai_engine_module,
            "_snapshot_available_providers",
            lambda: ["QNNExecutionProvider", "CPUExecutionProvider"],
        )
        qnn_provider = _make_qnn_provider_mock()
        _patch_select_provider_to_qnn(monkeypatch, qnn_provider)

        engine = AIVisionEngine(base_config, shared_state=shared_state)
        engine.load_model()

        status = engine.get_health_status()

        assert status["execution_provider"] == "QNNExecutionProvider"
        assert status["htp_performance_mode"] == "burst"
        # The base health-status keys remain present.
        assert status["backend"] == "qnn"
        assert status["model_loaded"] is True


class TestAIEngineProcessFrameDispatch:
    """``process_frame`` routes through ``_process_qnn`` when backend is QNN."""

    def test_ai_engine_dispatches_to_process_qnn_when_backend_qnn(
        self,
        base_config,
        shared_state,
        valid_frame,
    ):
        """Validates: Requirement 5.2 — dispatch to ``_process_qnn``.

        With ``self._backend == "qnn"`` and ``model_loaded == True``,
        ``process_frame`` invokes ``_process_qnn`` exactly once and does
        not invoke ``_process_directml``.
        """
        engine = AIVisionEngine(base_config, shared_state=shared_state)
        # Set engine state directly — load_model is exercised elsewhere.
        engine._backend = "qnn"
        engine.model_loaded = True

        with patch.object(
            engine, "_process_qnn", return_value=None
        ) as mock_qnn, patch.object(
            engine, "_process_directml", return_value=None
        ) as mock_dml:
            result = engine.process_frame(valid_frame)

        assert result is None  # ``_process_qnn`` returned None
        assert mock_qnn.call_count == 1
        # First positional arg passed to ``_process_qnn`` is the frame.
        assert mock_qnn.call_args.args[0] is valid_frame
        assert mock_dml.call_count == 0


class TestAIEngineUpdateConfigConfidence:
    """``update_config`` propagates confidence to the QNN provider."""

    def test_ai_engine_update_config_propagates_confidence_to_qnn_provider(
        self,
        base_config,
        shared_state,
    ):
        """Validates: Requirements 5.5, 2.4b — propagate without reload.

        After ``update_config({"confidence": 0.7})`` the engine writes the
        new value to ``self._qnn_provider.conf`` and does not invoke
        ``load_model`` again (the confidence is consumed at postprocess
        time so a reload is unnecessary).
        """
        engine = AIVisionEngine(base_config, shared_state=shared_state)
        # Attach a mock QNN provider directly — load_model is not under test.
        qnn_provider = _make_qnn_provider_mock(conf=base_config["confidence"])
        engine._qnn_provider = qnn_provider
        engine._backend = "qnn"
        engine.model_loaded = True

        with patch.object(engine, "load_model") as mock_load:
            engine.update_config({"confidence": 0.7})

        assert qnn_provider.conf == 0.7
        assert engine.confidence_threshold == 0.7
        # No session reload occurred.
        assert mock_load.call_count == 0

    def test_ai_engine_update_config_rejects_out_of_range_confidence_with_warn(
        self,
        base_config,
        shared_state,
        caplog,
    ):
        """Validates: Requirement 2.4b — out-of-range rejected, prior preserved.

        Passing ``confidence=1.5`` to ``update_config`` does not change the
        previously configured threshold and produces a WARN in ``caplog``
        identifying the offending value.
        """
        engine = AIVisionEngine(base_config, shared_state=shared_state)
        qnn_provider = _make_qnn_provider_mock(conf=0.55)
        engine._qnn_provider = qnn_provider
        engine._backend = "qnn"
        engine.confidence_threshold = 0.55
        original_conf_threshold = engine.confidence_threshold
        original_provider_conf = qnn_provider.conf

        with caplog.at_level(logging.WARNING, logger="engines.ai_engine"):
            engine.update_config({"confidence": 1.5})

        # Threshold preserved — neither engine attribute nor provider attr moved.
        assert engine.confidence_threshold == original_conf_threshold
        assert qnn_provider.conf == original_provider_conf
        # WARN emitted, and the offending value (or its repr) is mentioned.
        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "1.5" in r.getMessage() for r in warn_records
        ), (
            "Expected a WARN log mentioning 1.5; "
            f"got {[r.getMessage() for r in caplog.records]}"
        )


class TestAIEngineRelease:
    """``release`` invokes the QNN provider's ``release`` and clears the ref."""

    def test_ai_engine_release_invokes_qnn_provider_release(
        self,
        base_config,
        shared_state,
    ):
        """Validates: Requirement 5.6 — release plumbing for QNN.

        When the active backend is QNN, ``engine.release()`` calls
        ``self._qnn_provider.release()`` exactly once and clears the
        reference (``engine._qnn_provider is None``).
        """
        engine = AIVisionEngine(base_config, shared_state=shared_state)
        qnn_provider = _make_qnn_provider_mock()
        engine._qnn_provider = qnn_provider
        engine._backend = "qnn"
        engine.model_loaded = True

        engine.release()

        assert qnn_provider.release.call_count == 1
        assert engine._qnn_provider is None
        # Backend cleared per Req 5.4a.
        assert engine.backend_name == "none"
        assert shared_state.get_state("ai_backend") == "none"


class TestAIEngineCoexistenceWarning:
    """Once-per-process WARN when both QNN and DirectML EPs are present."""

    def test_ai_engine_warns_once_on_qnn_dml_coexistence(
        self,
        monkeypatch,
        base_config,
        shared_state,
        caplog,
    ):
        """Validates: Requirement 7.6 — single WARN across multiple load_model calls.

        When ``onnxruntime.get_available_providers()`` returns both
        ``QNNExecutionProvider`` and ``DmlExecutionProvider``, the engine
        emits exactly one WARN per process even if ``load_model`` is
        invoked multiple times.
        """
        monkeypatch.setattr(
            ai_engine_module, "_normalize_host_arch", lambda: "arm64"
        )
        monkeypatch.setattr(
            ai_engine_module,
            "_snapshot_available_providers",
            lambda: [
                "QNNExecutionProvider",
                "DmlExecutionProvider",
                "CPUExecutionProvider",
            ],
        )
        qnn_provider = _make_qnn_provider_mock()
        _patch_select_provider_to_qnn(monkeypatch, qnn_provider)

        engine = AIVisionEngine(base_config, shared_state=shared_state)

        with caplog.at_level(logging.WARNING, logger="engines.ai_engine"):
            engine.load_model()
            # Second invocation must not re-emit the WARN.
            engine.load_model()

        coexistence_records = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING
            and "Both QNN and DirectML" in r.getMessage()
        ]
        assert len(coexistence_records) == 1, (
            "Expected exactly one coexistence WARN across two load_model "
            f"calls; got {[r.getMessage() for r in coexistence_records]}"
        )


class TestAIEngineInstallHint:
    """Once-per-process INFO install hint on arm64 hosts without QNN."""

    def test_ai_engine_logs_install_hint_once_when_arm64_and_no_qnn(
        self,
        monkeypatch,
        base_config,
        shared_state,
        caplog,
    ):
        """Validates: Requirement 7.3 — single INFO install hint per process.

        On arm64 hosts where ``QNNExecutionProvider`` is unavailable, the
        engine logs ``pip install onnxruntime-qnn`` exactly once across
        multiple ``load_model`` invocations within the same process.
        """
        monkeypatch.setattr(
            ai_engine_module, "_normalize_host_arch", lambda: "arm64"
        )
        # No QNN in the available providers list.
        monkeypatch.setattr(
            ai_engine_module,
            "_snapshot_available_providers",
            lambda: ["CPUExecutionProvider"],
        )

        # Patch ``has_qnn`` on the qnn_provider module; the engine imports it
        # lazily via ``from engines.qnn_provider import has_qnn``.
        import engines.qnn_provider as qnn_provider_module
        monkeypatch.setattr(qnn_provider_module, "has_qnn", lambda: False)

        # Mock select_provider to return a non-QNN provider so load_model
        # completes successfully (avoids cascading exceptions hiding the
        # INFO log assertion).
        non_qnn_provider = MagicMock(name="UltralyticsProviderMock")
        non_qnn_provider.load.return_value = True
        import engines.ep_selector as ep_selector_module
        monkeypatch.setattr(
            ep_selector_module,
            "select_provider",
            MagicMock(return_value=(non_qnn_provider, "cpu")),
        )

        engine = AIVisionEngine(base_config, shared_state=shared_state)

        with caplog.at_level(logging.INFO, logger="engines.ai_engine"):
            engine.load_model()
            engine.load_model()

        hint_records = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO
            and "pip install onnxruntime-qnn" in r.getMessage()
        ]
        assert len(hint_records) == 1, (
            "Expected exactly one INFO install hint across two load_model "
            f"calls; got {[r.getMessage() for r in hint_records]}"
        )


class TestAIEnginePinnedQNNFailure:
    """Pinned ``execution_provider == 'qnn'`` failures clear backend to 'none'."""

    def test_ai_engine_pinned_qnn_failure_raises_aiengineexception_and_sets_backend_none(
        self,
        monkeypatch,
        base_config,
        shared_state,
    ):
        """Validates: Requirements 4.7, 5.4a — pinned-fail surfaces and clears.

        With ``execution_provider == "qnn"`` and the QNN load mocked to
        fail, ``select_provider`` raises ``AIEngineException``. The engine
        re-raises unchanged after clearing the backend, leaving
        ``shared_state["ai_backend"] == "none"``.
        """
        base_config["execution_provider"] = "qnn"

        monkeypatch.setattr(
            ai_engine_module, "_normalize_host_arch", lambda: "arm64"
        )
        monkeypatch.setattr(
            ai_engine_module,
            "_snapshot_available_providers",
            lambda: ["QNNExecutionProvider", "CPUExecutionProvider"],
        )
        # select_provider raises after exhausting the (length-1) cascade.
        import engines.ep_selector as ep_selector_module
        monkeypatch.setattr(
            ep_selector_module,
            "select_provider",
            MagicMock(
                side_effect=AIEngineException(
                    "all execution providers failed: qnn: load() returned False"
                )
            ),
        )

        engine = AIVisionEngine(base_config, shared_state=shared_state)

        with pytest.raises(AIEngineException) as exc_info:
            engine.load_model()

        # The pinned-failure message survives unchanged (Req 4.7).
        assert "qnn" in str(exc_info.value).lower()
        # Backend cleared to the literal "none" per Req 5.4a.
        assert engine.backend_name == "none"
        assert shared_state.get_state("ai_backend") == "none"


class TestAIEngineProcessFrameWithoutLoad:
    """``process_frame`` is a safe no-op before ``load_model`` is invoked."""

    def test_ai_engine_process_frame_returns_none_before_load_model(
        self,
        base_config,
        shared_state,
        valid_frame,
    ):
        """Validates: Requirement 6.6 — no exception, returns empty list.

        Before ``load_model`` has been called, ``process_frame`` returns
        an empty list (``[]``) and ``model_loaded`` stays ``False``. No
        exception is raised so a transient init order does not crash the
        engine.

        Per task 3.4 of the aim-pipeline-simplification spec, the engine
        now returns ``List[Detection]`` (req 4.9) instead of
        ``Optional[Detection]``; ``[]`` is the empty-result sentinel.
        """
        engine = AIVisionEngine(base_config, shared_state=shared_state)

        # Sanity: load_model was not invoked.
        assert engine.model_loaded is False

        result = engine.process_frame(valid_frame)

        assert result == []
        assert engine.model_loaded is False
