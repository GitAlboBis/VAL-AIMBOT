"""
Property test — Task 2.4 of spec ``npu-qnn-provider``.

Feature: npu-qnn-provider, Property 5: EP_Selector QNN preference

**Property 5: EP_Selector QNN preference**

    *For all* inputs in which

        host_arch == "arm64"
        "QNNExecutionProvider" in available_providers
        qnn_load_ok == True
        config_override == "auto"

    the call ``select_provider(...)`` SHALL return a tuple whose
    ``backend_name`` element equals the literal string ``"qnn"``.

**Validates: Requirements 3.8**

Implementation notes
--------------------
The property captures the design's "preference" rule: on an ARM64 host
where the QNN execution provider is exposed by ``onnxruntime.get_available_providers()``
and the QNN provider's ``load()`` succeeds, the auto cascade
``["qnn", "directml", "cpu"]`` MUST resolve to ``"qnn"`` regardless of
the load outcomes of the lower-priority candidates and regardless of
which other providers happen to be present in ``available_providers``.

The Hypothesis strategy fixes the four precondition variables to their
required values and freely varies the remaining state — DirectML/CPU
provider availability flags inside ``available_providers`` and the
``dml_load_ok`` / ``cpu_load_ok`` flags — so the property body asserts
the invariant across the entire restricted slice of the EP_Selector
input space.

Stub providers replace the real ``QNNProvider`` / ``DirectMLProvider`` /
``UltralyticsProvider`` so the test runs on any host (ARM64 or x86_64)
and never imports ``onnxruntime``. Each factory returns a fresh stub
whose ``.load()`` returns the boolean drawn by the strategy; the
selector's iteration order is the only dynamic input under test.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

import pytest
from hypothesis import given, settings, strategies as st

from engines.ep_selector import select_provider


# ---------------------------------------------------------------------------
# Stub provider + factory helpers
# ---------------------------------------------------------------------------


class _StubProvider:
    """Minimal Provider implementation used as the cascade target.

    Satisfies the duck-typed contract expected by ``select_provider``:
    ``.load() -> bool`` and ``.release() -> None``. The constructor takes
    a deterministic ``load_ok`` flag so the strategy can drive the
    selector's iteration outcome without any randomness inside the stub.
    """

    def __init__(self, name: str, load_ok: bool) -> None:
        self.name = name
        self._load_ok = load_ok

    def load(self) -> bool:
        return self._load_ok

    def release(self) -> None:  # pragma: no cover — never called by selector
        return None


def _make_factory(name: str, load_ok: bool) -> Callable[[], _StubProvider]:
    """Return a zero-arg factory yielding a fresh stub on every call.

    A new instance per call mirrors the real ``_build_*_provider`` closures
    in ``AIVisionEngine.load_model`` (each invocation constructs a brand
    new provider) so the selector cannot accidentally rely on cross-call
    state.
    """
    return lambda: _StubProvider(name, load_ok)


# ---------------------------------------------------------------------------
# Hypothesis strategy
# ---------------------------------------------------------------------------


@st.composite
def _qnn_preference_inputs(draw: st.DrawFn) -> Dict[str, Any]:
    """Enumerate the input slice on which Property 5 must hold.

    Fixed dimensions (preconditions for Property 5):
        host_arch         == "arm64"
        config_override   == "auto"
        qnn_load_ok       is True
        "QNNExecutionProvider" in available_providers

    Free dimensions (the property must hold for every combination):
        DmlExecutionProvider present in available_providers     (bool)
        CPUExecutionProvider present in available_providers     (bool)
        dml_load_ok                                             (bool)
        cpu_load_ok                                             (bool)

    The free dimensions exist because the cascade only inspects the
    QNN slot first; once QNN's load succeeds the loop returns and the
    other slots are never invoked. Varying them anyway proves the
    property survives factory short-circuiting (Req 3.6).
    """
    has_dml_provider = draw(st.booleans())
    has_cpu_provider = draw(st.booleans())

    # ``QNNExecutionProvider`` is fixed — it is part of the precondition.
    available_providers: List[str] = ["QNNExecutionProvider"]
    if has_dml_provider:
        available_providers.append("DmlExecutionProvider")
    if has_cpu_provider:
        available_providers.append("CPUExecutionProvider")

    return {
        "available_providers": available_providers,
        "dml_load_ok": draw(st.booleans()),
        "cpu_load_ok": draw(st.booleans()),
    }


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@pytest.mark.unit
@given(inputs=_qnn_preference_inputs())
@settings(max_examples=100)
def test_qnn_preferred_when_arm64_qnn_available_and_load_ok(
    inputs: Dict[str, Any],
) -> None:
    """Property 5: EP_Selector QNN preference.

    Feature: npu-qnn-provider, Property 5: EP_Selector QNN preference

    For every drawn input in the restricted slice
    ``host_arch == "arm64" AND "QNNExecutionProvider" in available_providers
    AND qnn_load_ok == True AND config_override == "auto"``, the selector
    SHALL return ``backend_name == "qnn"``. The lower-priority load flags
    (``dml_load_ok``, ``cpu_load_ok``) and the presence of additional
    providers in ``available_providers`` SHALL NOT influence the outcome.

    Validates: Requirements 3.8.
    """
    candidate_factories: Dict[str, Callable[[], _StubProvider]] = {
        "qnn": _make_factory("qnn", load_ok=True),
        "directml": _make_factory("directml", load_ok=inputs["dml_load_ok"]),
        "cpu": _make_factory("cpu", load_ok=inputs["cpu_load_ok"]),
    }

    provider, backend_name = select_provider(
        host_arch="arm64",
        available_providers=inputs["available_providers"],
        config_override="auto",
        candidate_factories=candidate_factories,
    )

    # Primary invariant — Req 3.8.
    assert backend_name == "qnn", (
        f"Property 5 violation: expected backend_name='qnn' under preconditions "
        f"(host_arch='arm64', QNN available, qnn_load_ok=True, override='auto'); "
        f"got {backend_name!r}. available_providers={inputs['available_providers']}, "
        f"dml_load_ok={inputs['dml_load_ok']}, cpu_load_ok={inputs['cpu_load_ok']}"
    )

    # Secondary sanity: the returned provider is the one whose factory was
    # invoked for the "qnn" slot. Anchors the property to the actual cascade
    # entry rather than to a stale or mis-routed provider.
    assert isinstance(provider, _StubProvider)
    assert provider.name == "qnn"
