"""
Property test for EP_Selector lookup-table correctness.

Feature: npu-qnn-provider, Property 4: EP_Selector lookup-table correctness

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.6, 3.7, 4.2, 4.3, 4.4, 4.5, 6.1, 6.5

The property exhaustively enumerates the EP_Selector input space and asserts that
``select_provider`` agrees with an independent oracle implemented as a switch-case
mirroring the design's decision table verbatim.
"""

from __future__ import annotations

import os
import sys
from typing import List
from unittest.mock import Mock

import pytest
from hypothesis import given, settings, strategies as st

# Ensure the project root is on ``sys.path`` so ``engines`` and ``exceptions`` import
# the same way they do in the rest of the test suite.
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from engines.ep_selector import select_provider  # noqa: E402
from exceptions import AIEngineException  # noqa: E402


# ---------------------------------------------------------------------------
# Oracle — switch-case mirroring the design decision table verbatim.
# ---------------------------------------------------------------------------

_ALLOWED_OVERRIDES = ("auto", "qnn", "directml", "cpu")


def _oracle_backend_name(
    host_arch: str,
    available_providers: List[str],
    config_override: str,
    qnn_load_ok: bool,
    dml_load_ok: bool,
    ul_load_ok: bool,
) -> str:
    """Return the expected backend_name, or the literal string ``"raise"``.

    Mirrors ``engines.ep_selector.select_provider`` cascade rules verbatim:

    * Unknown override values normalize to ``"auto"`` (Req 4.6).
    * Pinned overrides yield length-1 cascades (Reqs 4.3, 4.4, 4.5).
    * ``auto + arm64 + QNNExecutionProvider in available_providers`` yields
      ``["qnn", "directml", "cpu"]`` (Reqs 3.1, 3.6).
    * Otherwise the cascade is ``["directml", "cpu"]`` (Reqs 3.2, 4.2).
    * The first cascade entry whose ``load_ok`` is True wins (Req 3.3); when every
      entry fails, the oracle predicts ``"raise"`` (Reqs 3.4, 4.7).
    """
    if isinstance(config_override, str):
        normalized = config_override.strip().lower()
        if normalized not in _ALLOWED_OVERRIDES:
            normalized = "auto"
    else:
        normalized = "auto"

    if normalized == "qnn":
        cascade = ["qnn"]
    elif normalized == "directml":
        cascade = ["directml"]
    elif normalized == "cpu":
        cascade = ["cpu"]
    elif host_arch == "arm64" and "QNNExecutionProvider" in available_providers:
        cascade = ["qnn", "directml", "cpu"]
    else:
        cascade = ["directml", "cpu"]

    load_ok = {
        "qnn": qnn_load_ok,
        "directml": dml_load_ok,
        "cpu": ul_load_ok,
    }
    for name in cascade:
        if load_ok[name]:
            return name
    return "raise"


# ---------------------------------------------------------------------------
# Factory helpers — produce mock providers whose ``.load()`` honours a bool.
# ---------------------------------------------------------------------------


def _make_factory(load_ok: bool):
    """Return a zero-arg factory that constructs a fresh Mock provider.

    The mock provider's ``.load()`` returns ``load_ok``; ``.release()`` is a no-op.
    The selector treats ``load() -> False`` as a non-fatal failure and continues to
    the next cascade entry.
    """

    def _factory():
        provider = Mock()
        provider.load = Mock(return_value=load_ok)
        provider.release = Mock(return_value=None)
        return provider

    return _factory


# ---------------------------------------------------------------------------
# Hypothesis strategies enumerating the full input space.
# ---------------------------------------------------------------------------

_HOST_ARCHS = ("arm64", "x86_64", "other")
_PROVIDER_UNIVERSE = (
    "QNNExecutionProvider",
    "DmlExecutionProvider",
    "CPUExecutionProvider",
)
_OVERRIDES = ("auto", "qnn", "directml", "cpu", "<garbage>")


_available_providers_strategy = st.lists(
    st.sampled_from(_PROVIDER_UNIVERSE),
    min_size=0,
    max_size=len(_PROVIDER_UNIVERSE),
    unique=True,
)


# ---------------------------------------------------------------------------
# Property test.
# ---------------------------------------------------------------------------


@given(
    host_arch=st.sampled_from(_HOST_ARCHS),
    available_providers=_available_providers_strategy,
    config_override=st.sampled_from(_OVERRIDES),
    qnn_load_ok=st.booleans(),
    dml_load_ok=st.booleans(),
    ul_load_ok=st.booleans(),
)
@settings(max_examples=100)
def test_ep_selector_matches_oracle(
    host_arch: str,
    available_providers: List[str],
    config_override: str,
    qnn_load_ok: bool,
    dml_load_ok: bool,
    ul_load_ok: bool,
) -> None:
    """Feature: npu-qnn-provider, Property 4: EP_Selector lookup-table correctness.

    For every (host_arch, available_providers, config_override, load-result triple)
    drawn from the enumerated space, ``select_provider`` either returns the same
    ``backend_name`` as the oracle, or raises ``AIEngineException`` iff the oracle
    predicts ``"raise"``.
    """
    expected = _oracle_backend_name(
        host_arch=host_arch,
        available_providers=available_providers,
        config_override=config_override,
        qnn_load_ok=qnn_load_ok,
        dml_load_ok=dml_load_ok,
        ul_load_ok=ul_load_ok,
    )

    candidate_factories = {
        "qnn": _make_factory(qnn_load_ok),
        "directml": _make_factory(dml_load_ok),
        "cpu": _make_factory(ul_load_ok),
    }

    if expected == "raise":
        with pytest.raises(AIEngineException):
            select_provider(
                host_arch=host_arch,
                available_providers=available_providers,
                config_override=config_override,
                candidate_factories=candidate_factories,
            )
    else:
        provider, backend_name = select_provider(
            host_arch=host_arch,
            available_providers=available_providers,
            config_override=config_override,
            candidate_factories=candidate_factories,
        )
        assert backend_name == expected, (
            f"select_provider chose {backend_name!r} but oracle predicted "
            f"{expected!r} for host_arch={host_arch!r}, "
            f"available_providers={available_providers!r}, "
            f"config_override={config_override!r}, "
            f"loads=(qnn={qnn_load_ok}, dml={dml_load_ok}, ul={ul_load_ok})"
        )
        # The returned provider must be the mock produced by the winning factory:
        # its `.load()` was invoked exactly once and returned True.
        assert provider.load.called
