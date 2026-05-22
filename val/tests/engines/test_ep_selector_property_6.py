"""
Property test — EP_Selector no-spurious-QNN.

Feature: npu-qnn-provider, Property 6: EP_Selector no-spurious-QNN

**Validates: Requirements 3.9**

The no-spurious-selection property guarantees that ``select_provider`` never
returns ``backend_name == "qnn"`` when any QNN precondition is unmet under
the *auto-cascade* path. The qualifying precondition set, per Req 3.9, is:

* ``host_arch != "arm64"``                   — host is not Snapdragon ARM64,
* ``"QNNExecutionProvider"`` is missing      — ORT did not expose QNN,
* ``qnn_load_ok is False``                   — the QNN factory's ``load()`` failed.

If any of those is true (and ``config_override == "auto"``), the selector
either:

* returns a backend whose name is not ``"qnn"``, or
* raises ``AIEngineException`` because every cascade candidate failed.

# Scope refinement (user-approved):
# Property 6 applies to the **auto cascade only**. Pinned overrides
# (``config_override == "qnn"``) intentionally bypass this no-spurious rule —
# Req 4.3 mandates that a pinned ``"qnn"`` override evaluates a length-1
# cascade ``[QNN_Provider]`` and Req 4.7 dictates that it raises
# ``AIEngineException`` (without falling back) if the QNN load fails. That
# pinned-failure path is *not* a spurious selection — it is the documented
# pinned-failure contract — and therefore lies outside Property 6's scope.
# We therefore pin ``config_override = "auto"`` for this property, mirroring
# Property 5's scoping convention.

The test enumerates the EP_Selector input space (mirroring Property 4's
strategy minus ``config_override``, which is fixed at ``"auto"``) and uses
``hypothesis.assume`` to narrow draws to the no-spurious subspace. Stub
factories are deterministic ``MagicMock`` providers whose ``.load()`` returns
the per-draw boolean.

Implementation language: Python with Hypothesis (per design.md §Testing).
"""

from __future__ import annotations

from typing import Callable, List, Mapping
from unittest.mock import MagicMock

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from engines.ep_selector import select_provider
from exceptions import AIEngineException


# ---------------------------------------------------------------------------
# Strategy parameters — mirror Property 4's enumerated input space, except
# ``config_override`` is fixed at ``"auto"`` (see scope refinement above).
# ---------------------------------------------------------------------------

_HOST_ARCHS = ["arm64", "x86_64", "other"]
_PROVIDER_NAMES = [
    "QNNExecutionProvider",
    "DmlExecutionProvider",
    "CPUExecutionProvider",
]


# ---------------------------------------------------------------------------
# Deterministic stub factory — minimal Provider surface used by select_provider.
# ---------------------------------------------------------------------------

def _make_factory(load_ok: bool) -> Callable[[], MagicMock]:
    """Return a zero-arg factory producing a stub provider with ``load() -> load_ok``.

    The stub also exposes a no-op ``release()`` so the contract assumed by
    ``select_provider`` is satisfied even though the selector never invokes
    it on the success path.
    """

    def _factory() -> MagicMock:
        provider = MagicMock()
        provider.load = MagicMock(return_value=load_ok)
        provider.release = MagicMock(return_value=None)
        return provider

    return _factory


# ---------------------------------------------------------------------------
# Property 6 — EP_Selector no-spurious-QNN (auto-cascade scope).
# ---------------------------------------------------------------------------

@pytest.mark.unit
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    host_arch=st.sampled_from(_HOST_ARCHS),
    available_providers=st.lists(
        st.sampled_from(_PROVIDER_NAMES),
        max_size=len(_PROVIDER_NAMES),
        unique=True,
    ),
    qnn_load_ok=st.booleans(),
    dml_load_ok=st.booleans(),
    ul_load_ok=st.booleans(),
)
def test_ep_selector_no_spurious_qnn(
    host_arch: str,
    available_providers: List[str],
    qnn_load_ok: bool,
    dml_load_ok: bool,
    ul_load_ok: bool,
) -> None:
    """Feature: npu-qnn-provider, Property 6: EP_Selector no-spurious-QNN.

    **Validates: Requirements 3.9**

    For every drawn input under ``config_override == "auto"`` in which
    ``host_arch != "arm64"`` OR ``"QNNExecutionProvider" not in
    available_providers`` OR ``qnn_load_ok is False``,
    ``select_provider(...)`` MUST either return ``backend_name != "qnn"`` or
    raise ``AIEngineException``.
    """
    # Restrict to the no-spurious subspace per the task's filter spec.
    assume(
        host_arch != "arm64"
        or "QNNExecutionProvider" not in available_providers
        or qnn_load_ok is False
    )

    candidate_factories: Mapping[str, Callable[[], MagicMock]] = {
        "qnn": _make_factory(qnn_load_ok),
        "directml": _make_factory(dml_load_ok),
        "cpu": _make_factory(ul_load_ok),
    }

    try:
        _provider, backend_name = select_provider(
            host_arch=host_arch,
            available_providers=available_providers,
            config_override="auto",
            candidate_factories=candidate_factories,
        )
    except AIEngineException:
        # Cascade exhausted with no successful load — acceptable outcome.
        return

    assert backend_name != "qnn", (
        "select_provider returned 'qnn' under no-spurious preconditions: "
        f"host_arch={host_arch!r}, "
        f"available_providers={available_providers!r}, "
        f"config_override='auto', "
        f"qnn_load_ok={qnn_load_ok!r}, "
        f"dml_load_ok={dml_load_ok!r}, "
        f"ul_load_ok={ul_load_ok!r}"
    )
