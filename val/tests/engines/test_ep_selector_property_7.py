"""
Property test for ``engines.ep_selector.select_provider`` — idempotence.

Feature: npu-qnn-provider, Property 7: EP_Selector idempotence
Validates: Requirements 3.10, 9.4

Per Req 9.4 (idempotence property), two consecutive evaluations of
``select_provider`` against the same arguments — with deterministic stub factories —
must produce the same ``backend_name``, or both must raise the same exception type.
This follows from Req 3.10 (the selector is a pure function of its arguments) and
guarantees that ``shared_state["ai_backend"]`` cannot drift across re-loads triggered
by the same configuration on the same host.

The Hypothesis strategy enumerates the same input space used for Property 4
(``host_arch ∈ {"arm64", "x86_64", "other"}``,
``available_providers ⊆ {QNN, DML, CPU} EPs``,
``config_override ∈ {"auto", "qnn", "directml", "cpu", "<garbage>"}``,
``(qnn_load_ok, dml_load_ok, cpu_load_ok) ∈ {True, False}^3``) and runs each
drawn case through ``select_provider`` twice.
"""

from __future__ import annotations

from typing import Any, Sequence, Tuple

from hypothesis import given, settings, strategies as st

from engines.ep_selector import select_provider
from exceptions import AIEngineException


# Enumerated input space — mirrors the Property 4 strategy verbatim so that
# Properties 4, 5, 6, and 7 share a single source of truth.
_HOST_ARCHS = ("arm64", "x86_64", "other")
_ALL_EPS = ("QNNExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider")
_OVERRIDES = ("auto", "qnn", "directml", "cpu", "<garbage>")


class _StubProvider:
    """Deterministic stand-in for a real ``Inference_Provider``.

    ``load()`` returns a fixed boolean baked in at construction; ``release()`` is a
    no-op. Crucially, two distinct ``_StubProvider`` instances built with the same
    ``load_ok`` value behave identically — that is what makes the surrounding
    factories deterministic and lets the idempotence assertion be meaningful even
    though ``select_provider`` constructs a *fresh* provider on each call.
    """

    def __init__(self, load_ok: bool) -> None:
        self._load_ok = load_ok

    def load(self) -> bool:
        return self._load_ok

    def release(self) -> None:  # pragma: no cover — never invoked by the selector
        return None


def _make_factory(load_ok: bool):
    """Build a deterministic zero-argument factory returning a fresh stub.

    Each invocation yields a new ``_StubProvider`` whose ``load()`` outcome is
    exactly ``load_ok``. No hidden state, no clock, no environment reads — so
    repeated calls produce equivalent providers.
    """

    def _factory() -> _StubProvider:
        return _StubProvider(load_ok)

    return _factory


def _evaluate(
    host_arch: str,
    available_providers: Sequence[str],
    config_override: str,
    qnn_load_ok: bool,
    dml_load_ok: bool,
    cpu_load_ok: bool,
) -> Tuple[str, Any]:
    """Run ``select_provider`` once and return a comparable outcome.

    Returns ``("ok", backend_name)`` on a successful selection or
    ``("raised", exc_type)`` when the cascade is exhausted. The provider object
    itself is intentionally discarded — Property 7 cares only about backend
    identity / exception type, not provider instance equality.
    """
    factories = {
        "qnn": _make_factory(qnn_load_ok),
        "directml": _make_factory(dml_load_ok),
        "cpu": _make_factory(cpu_load_ok),
    }
    try:
        _provider, backend_name = select_provider(
            host_arch=host_arch,
            available_providers=list(available_providers),
            config_override=config_override,
            candidate_factories=factories,
        )
        return ("ok", backend_name)
    except AIEngineException:
        return ("raised", AIEngineException)


@settings(max_examples=100)
@given(
    host_arch=st.sampled_from(_HOST_ARCHS),
    available_providers=st.lists(
        st.sampled_from(_ALL_EPS), unique=True, min_size=0, max_size=3
    ),
    config_override=st.sampled_from(_OVERRIDES),
    qnn_load_ok=st.booleans(),
    dml_load_ok=st.booleans(),
    cpu_load_ok=st.booleans(),
)
def test_ep_selector_is_idempotent(
    host_arch: str,
    available_providers: list,
    config_override: str,
    qnn_load_ok: bool,
    dml_load_ok: bool,
    cpu_load_ok: bool,
) -> None:
    """Feature: npu-qnn-provider, Property 7: EP_Selector idempotence.

    For every drawn ``(host_arch, available_providers, config_override,
    qnn_load_ok, dml_load_ok, cpu_load_ok)``, two back-to-back evaluations of
    ``select_provider`` with deterministic stub factories must agree on either
    the chosen ``backend_name`` or the raised exception type.

    Validates: Requirements 3.10, 9.4.
    """
    first = _evaluate(
        host_arch,
        available_providers,
        config_override,
        qnn_load_ok,
        dml_load_ok,
        cpu_load_ok,
    )
    second = _evaluate(
        host_arch,
        available_providers,
        config_override,
        qnn_load_ok,
        dml_load_ok,
        cpu_load_ok,
    )

    assert first == second, (
        "select_provider is not idempotent: "
        f"first={first!r}, second={second!r} "
        f"(host_arch={host_arch!r}, "
        f"available_providers={available_providers!r}, "
        f"config_override={config_override!r}, "
        f"qnn_load_ok={qnn_load_ok}, "
        f"dml_load_ok={dml_load_ok}, "
        f"cpu_load_ok={cpu_load_ok})"
    )
