"""
Unit/example tests for ``engines.ep_selector.select_provider``.

Feature: npu-qnn-provider, Task 2.2 — EP_Selector unit tests.

These tests cover the behavioural contract of the pure cascade-selection function
extracted from ``AIVisionEngine.load_model``. They use ``unittest.mock.Mock`` factories
that hand back stub providers exposing only the ``.load()`` method the selector calls,
so the suite runs on any host without ONNX Runtime, DirectML, or QNN installed.

Each test is annotated with the requirement(s) it validates per the task definition
in ``.kiro/specs/npu-qnn-provider/tasks.md``.
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from unittest.mock import Mock

import pytest

from engines.ep_selector import select_provider
from exceptions import AIEngineException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(load_return: bool = True, load_exc: Optional[Exception] = None) -> Mock:
    """Return a stub provider whose ``.load()`` call returns or raises as configured."""
    provider = Mock(name="StubProvider")
    if load_exc is not None:
        provider.load.side_effect = load_exc
    else:
        provider.load.return_value = load_return
    return provider


def _make_factory(provider: Optional[Mock] = None, **provider_kwargs) -> Mock:
    """Return a Mock factory callable that yields a fresh stub provider when invoked."""
    if provider is None:
        provider = _make_provider(**provider_kwargs)
    factory = Mock(name="StubFactory", return_value=provider)
    # Stash the provider for assertions in the test body.
    factory.provider = provider  # type: ignore[attr-defined]
    return factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestArm64AutoCascade:
    """Auto-mode cascade behaviour on arm64 hosts."""

    def test_arm64_cascade_prefers_qnn_when_load_succeeds(self):
        """Validates: Requirements 3.1, 3.8 — preference for QNN when available.

        On arm64 with QNNExecutionProvider available and QNN.load() == True, the qnn
        factory must be invoked first and the directml/cpu factories must not be
        invoked at all. Order is asserted via ``call_args_list``.
        """
        qnn_factory = _make_factory(load_return=True)
        dml_factory = _make_factory(load_return=True)
        cpu_factory = _make_factory(load_return=True)

        provider, backend_name = select_provider(
            host_arch="arm64",
            available_providers=["QNNExecutionProvider", "DmlExecutionProvider"],
            config_override="auto",
            candidate_factories={
                "qnn": qnn_factory,
                "directml": dml_factory,
                "cpu": cpu_factory,
            },
        )

        from unittest.mock import call

        assert backend_name == "qnn"
        assert provider is qnn_factory.provider
        # Factory invocation order: qnn first, exactly once, with no positional args.
        assert qnn_factory.call_args_list == [call()]
        # qnn was invoked first and won — no other factory should have been called.
        assert dml_factory.call_count == 0
        assert cpu_factory.call_count == 0

    def test_arm64_qnn_load_false_falls_back_to_directml_with_single_info_log(self, caplog):
        """Validates: Requirements 3.4, 6.5 — single INFO fallback record.

        When QNN.load() returns False, the cascade falls through to DirectML and the
        selector emits exactly one INFO-level log record matching
        ``EP fallback: qnn -> directml (reason: load() returned False)``.
        """
        qnn_factory = _make_factory(load_return=False)
        dml_factory = _make_factory(load_return=True)
        cpu_factory = _make_factory(load_return=True)

        with caplog.at_level(logging.INFO, logger="engines.ep_selector"):
            provider, backend_name = select_provider(
                host_arch="arm64",
                available_providers=["QNNExecutionProvider", "DmlExecutionProvider"],
                config_override="auto",
                candidate_factories={
                    "qnn": qnn_factory,
                    "directml": dml_factory,
                    "cpu": cpu_factory,
                },
            )

        assert backend_name == "directml"
        assert provider is dml_factory.provider
        assert qnn_factory.call_count == 1
        assert dml_factory.call_count == 1
        assert cpu_factory.call_count == 0

        pattern = re.compile(
            r"EP fallback: qnn -> directml \(reason: load\(\) returned False\)"
        )
        info_matches = [
            rec for rec in caplog.records
            if rec.levelno == logging.INFO and pattern.search(rec.getMessage())
        ]
        assert len(info_matches) == 1, (
            f"Expected exactly one INFO fallback record, got "
            f"{[r.getMessage() for r in caplog.records]}"
        )

    def test_arm64_qnn_factory_not_invoked_when_provider_absent(self):
        """Validates: Requirement 3.6 — short-circuit when QNN EP is not available.

        On arm64 but with QNNExecutionProvider missing from available_providers, the
        qnn factory must never be invoked; the cascade is ``[directml, cpu]``.
        """
        qnn_factory = _make_factory(load_return=True)
        dml_factory = _make_factory(load_return=True)
        cpu_factory = _make_factory(load_return=True)

        provider, backend_name = select_provider(
            host_arch="arm64",
            # Note: QNNExecutionProvider intentionally absent.
            available_providers=["DmlExecutionProvider", "CPUExecutionProvider"],
            config_override="auto",
            candidate_factories={
                "qnn": qnn_factory,
                "directml": dml_factory,
                "cpu": cpu_factory,
            },
        )

        assert backend_name == "directml"
        assert provider is dml_factory.provider
        assert qnn_factory.call_count == 0
        assert dml_factory.call_count == 1
        assert cpu_factory.call_count == 0


class TestPinnedOverrides:
    """Behaviour when ``config_override`` pins a specific provider."""

    def test_pinned_qnn_override_raises_aiengineexception_when_load_fails(self):
        """Validates: Requirement 4.7 — pinned QNN never silently falls back.

        With config_override='qnn', the cascade has length 1. When QNN.load() returns
        False, AIEngineException is raised and the message enumerates the qnn failure.
        """
        qnn_factory = _make_factory(load_return=False)
        dml_factory = _make_factory(load_return=True)  # must NOT be invoked
        cpu_factory = _make_factory(load_return=True)  # must NOT be invoked

        with pytest.raises(AIEngineException) as exc_info:
            select_provider(
                host_arch="arm64",
                available_providers=["QNNExecutionProvider", "DmlExecutionProvider"],
                config_override="qnn",
                candidate_factories={
                    "qnn": qnn_factory,
                    "directml": dml_factory,
                    "cpu": cpu_factory,
                },
            )

        assert "qnn:" in str(exc_info.value)
        assert qnn_factory.call_count == 1
        # Pinned cascade has length 1 — siblings must not be touched.
        assert dml_factory.call_count == 0
        assert cpu_factory.call_count == 0

    def test_pinned_directml_override_evaluates_only_directml(self):
        """Validates: Requirement 4.4 — pinned directml cascade is length 1.

        With config_override='directml', the qnn factory must not be invoked at all
        and the directml factory must be invoked exactly once.
        """
        qnn_factory = _make_factory(load_return=True)
        dml_factory = _make_factory(load_return=True)
        cpu_factory = _make_factory(load_return=True)

        provider, backend_name = select_provider(
            host_arch="arm64",
            available_providers=["QNNExecutionProvider", "DmlExecutionProvider"],
            config_override="directml",
            candidate_factories={
                "qnn": qnn_factory,
                "directml": dml_factory,
                "cpu": cpu_factory,
            },
        )

        assert backend_name == "directml"
        assert provider is dml_factory.provider
        assert qnn_factory.call_count == 0
        assert dml_factory.call_count == 1
        assert cpu_factory.call_count == 0

    def test_pinned_cpu_override_evaluates_only_ultralytics_factory(self):
        """Validates: Requirement 4.5 — pinned cpu cascade is length 1.

        With config_override='cpu', select_provider returns backend_name == 'cpu'
        (which the AIVisionEngine call site maps to public 'ultralytics' per
        gap-resolution #11). The cpu factory is invoked exactly once.
        """
        qnn_factory = _make_factory(load_return=True)
        dml_factory = _make_factory(load_return=True)
        cpu_factory = _make_factory(load_return=True)

        provider, backend_name = select_provider(
            host_arch="x86_64",
            available_providers=["DmlExecutionProvider", "CPUExecutionProvider"],
            config_override="cpu",
            candidate_factories={
                "qnn": qnn_factory,
                "directml": dml_factory,
                "cpu": cpu_factory,
            },
        )

        # select_provider returns the cascade key; mapping to "ultralytics" is
        # performed at the AIVisionEngine call site, not here.
        assert backend_name == "cpu"
        assert provider is cpu_factory.provider
        assert qnn_factory.call_count == 0
        assert dml_factory.call_count == 0
        assert cpu_factory.call_count == 1


class TestOverrideNormalisation:
    """Behaviour for malformed/unknown override values."""

    def test_unknown_override_value_warns_and_falls_back_to_auto(self, caplog):
        """Validates: Requirement 4.6 — unknown override warns and falls back to auto.

        Passing an unrecognised string must (1) emit a WARN identifying the offending
        value, and (2) cause the selector to behave exactly as if config_override
        were 'auto'.
        """
        qnn_factory = _make_factory(load_return=True)
        dml_factory = _make_factory(load_return=True)
        cpu_factory = _make_factory(load_return=True)

        with caplog.at_level(logging.WARNING, logger="engines.ep_selector"):
            provider, backend_name = select_provider(
                host_arch="arm64",
                available_providers=["QNNExecutionProvider", "DmlExecutionProvider"],
                config_override="hexagon",  # not in the allowed set
                candidate_factories={
                    "qnn": qnn_factory,
                    "directml": dml_factory,
                    "cpu": cpu_factory,
                },
            )

        # Behaved as 'auto' on arm64 with QNN available => qnn wins.
        assert backend_name == "qnn"
        assert provider is qnn_factory.provider

        warn_matches = [
            rec for rec in caplog.records
            if rec.levelno == logging.WARNING and "hexagon" in rec.getMessage()
        ]
        assert len(warn_matches) >= 1, (
            f"Expected a WARN identifying 'hexagon', got "
            f"{[r.getMessage() for r in caplog.records]}"
        )


class TestCascadeExhaustion:
    """Behaviour when every candidate fails to load."""

    def test_all_candidates_fail_raises_aiengineexception_enumerating_each(self):
        """Validates: Requirements 3.5, 4.7 — exhaustion enumerates every candidate.

        When every factory in the cascade fails (mix of False return and raised
        exception), AIEngineException is raised with a message that contains every
        cascade name and the reason for each failure.
        """
        qnn_factory = _make_factory(load_return=False)
        dml_factory = _make_factory(load_exc=RuntimeError("boom-dml"))
        cpu_factory = _make_factory(load_return=False)

        with pytest.raises(AIEngineException) as exc_info:
            select_provider(
                host_arch="arm64",
                available_providers=["QNNExecutionProvider", "DmlExecutionProvider"],
                config_override="auto",
                candidate_factories={
                    "qnn": qnn_factory,
                    "directml": dml_factory,
                    "cpu": cpu_factory,
                },
            )

        msg = str(exc_info.value)
        # Every candidate name appears in the message.
        assert "qnn" in msg
        assert "directml" in msg
        assert "cpu" in msg
        # Reasons are enumerated for each failure.
        assert "load() returned False" in msg  # qnn and cpu use this reason
        assert "boom-dml" in msg                # dml raised, reason is exception text
        # Each factory got invoked exactly once.
        assert qnn_factory.call_count == 1
        assert dml_factory.call_count == 1
        assert cpu_factory.call_count == 1
