"""
Property test for shared_state ai_backend strict equality.

Feature: npu-qnn-provider, Property 9: shared_state ai_backend strict equality
Validates: Requirements 5.4, 5.4a

The property generates arbitrary finite sequences of operations from the alphabet

    {load_qnn_ok, load_qnn_fail, load_dml_ok, load_dml_fail,
     load_ul_ok, load_ul_fail, release}

and replays them against a freshly constructed :class:`engines.ai_engine.AIVisionEngine`
with a mocked provider cascade. After every operation the strict-equality invariant

    shared_state["ai_backend"] == engine.backend_name
    engine.backend_name in {"qnn", "directml", "ultralytics", "none"}

SHALL hold (Reqs 5.4, 5.4a). The cascade is mocked at its boundary
(``engines.ep_selector.select_provider``) so each op resolves deterministically:

* ``load_qnn_ok`` / ``load_dml_ok`` / ``load_ul_ok`` — the stub returns a
  ``MagicMock`` provider together with the matching cascade key
  (``"qnn"``, ``"directml"``, or ``"cpu"``). The engine maps ``"cpu"`` to the
  public backend_name ``"ultralytics"`` per gap-resolution #11.
* ``load_qnn_fail`` / ``load_dml_fail`` / ``load_ul_fail`` — the stub raises
  :class:`exceptions.AIEngineException` mirroring real cascade exhaustion;
  ``load_model`` catches it, calls ``_set_backend(None)`` (which writes
  ``"none"`` to shared state per Req 5.4a), and re-raises. The test catches
  the re-raised exception so the sequence can continue.
* ``release`` — invokes :meth:`AIVisionEngine.release` directly, which clears
  every provider reference and calls ``_set_backend(None)``.

``_find_model`` is patched to a fixed ``.onnx`` path so the engine takes the
ONNX cascade branch (rather than the legacy ``.pt`` / ``.engine`` short-circuit)
without depending on what files happen to live in ``./models/`` at test time.
"""

from __future__ import annotations

import os
import sys
from typing import List, Tuple
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, strategies as st

# Ensure the project root is on ``sys.path`` so ``engines`` and ``exceptions``
# import the same way the rest of the test suite does.
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from engines.ai_engine import AIVisionEngine  # noqa: E402
from exceptions import AIEngineException  # noqa: E402
from gui.shared_state import SharedState  # noqa: E402


# ---------------------------------------------------------------------------
# Operation alphabet and cascade-key mapping.
# ---------------------------------------------------------------------------

_OP_ALPHABET: Tuple[str, ...] = (
    "load_qnn_ok",
    "load_qnn_fail",
    "load_dml_ok",
    "load_dml_fail",
    "load_ul_ok",
    "load_ul_fail",
    "release",
)

# load_*_ok ops resolve to a cascade key returned by ``select_provider``.
# The engine then maps the key ``"cpu"`` to the public backend_name
# ``"ultralytics"`` (gap-resolution #11) before writing shared state.
_LOAD_OK_TO_CASCADE_KEY = {
    "load_qnn_ok": "qnn",
    "load_dml_ok": "directml",
    "load_ul_ok": "cpu",
}

_LOAD_FAIL_TO_CASCADE_KEY = {
    "load_qnn_fail": "qnn",
    "load_dml_fail": "directml",
    "load_ul_fail": "cpu",
}

# Strict-equality target set per Req 5.4a.
_VALID_BACKENDS = frozenset({"qnn", "directml", "ultralytics", "none"})


# ---------------------------------------------------------------------------
# Mocked provider cascade.
# ---------------------------------------------------------------------------


def _select_provider_for(op: str):
    """Return a ``select_provider`` replacement matching the requested op outcome.

    The returned callable matches the real selector's signature
    ``(host_arch, available_providers, config_override, candidate_factories)`` and
    deterministically resolves the cascade per the op token. ``load_*_fail`` ops
    surface as :class:`AIEngineException` exactly as cascade exhaustion would in
    production code, so the ``load_model`` exception-handling branch (which calls
    ``_set_backend(None)`` before re-raising) is exercised end-to-end.
    """
    if op in _LOAD_OK_TO_CASCADE_KEY:
        cascade_key = _LOAD_OK_TO_CASCADE_KEY[op]

        def _ok_stub(host_arch, available_providers, config_override, candidate_factories):
            return MagicMock(name=f"{cascade_key}_provider"), cascade_key

        return _ok_stub

    if op in _LOAD_FAIL_TO_CASCADE_KEY:
        cascade_key = _LOAD_FAIL_TO_CASCADE_KEY[op]

        def _fail_stub(host_arch, available_providers, config_override, candidate_factories):
            raise AIEngineException(
                f"all execution providers failed: {cascade_key}: load() returned False"
            )

        return _fail_stub

    raise AssertionError(  # pragma: no cover — strategy is closed over the alphabet
        f"unexpected op {op!r}; not a load_*_(ok|fail)"
    )


# ---------------------------------------------------------------------------
# Test harness helpers.
# ---------------------------------------------------------------------------


def _build_engine() -> Tuple[AIVisionEngine, SharedState]:
    """Construct a fresh ``AIVisionEngine`` + ``SharedState`` for one example.

    A fresh pair is built per Hypothesis example so the strict-equality
    invariant is asserted from a clean module-level state. The config matches
    what ``conftest.mock_config`` provides for the ``ai_engine`` section, plus
    the ``execution_provider: auto`` key the cascade reads through
    ``self.config.get("execution_provider", "auto")``.
    """
    shared_state = SharedState(error_handler=None)
    config = {
        "enabled": True,
        "confidence": 0.55,
        "iou_threshold": 0.45,
        "capture_size": 416,
        "headshot_bias": 0.30,
        "target_classes": [0],
        "execution_provider": "auto",
    }
    engine = AIVisionEngine(config, shared_state=shared_state)
    return engine, shared_state


def _apply_op(engine: AIVisionEngine, op: str) -> None:
    """Execute one op token against the engine, swallowing expected failures.

    For ``load_*`` ops, ``engines.ep_selector.select_provider`` is patched to
    a deterministic stub and ``_find_model`` is patched to a fixed ``.onnx``
    path so the engine takes the cascade branch unconditionally. For
    ``release``, the engine's own ``release()`` is called directly — no
    cascade involvement.

    Catching :class:`AIEngineException` lets the property test continue past
    expected ``load_*_fail`` outcomes; the post-op invariant is what matters.
    """
    if op == "release":
        engine.release()
        return

    with patch.object(engine, "_find_model", return_value="/mock/model.onnx"), patch(
        "engines.ep_selector.select_provider",
        side_effect=_select_provider_for(op),
    ):
        try:
            engine.load_model()
        except AIEngineException:
            # Expected for load_*_fail ops; the engine has already called
            # ``_set_backend(None)`` so the post-op invariant still holds.
            pass


def _assert_strict_equality(engine: AIVisionEngine, shared_state: SharedState) -> None:
    """Assert the Property 9 invariant after a single op."""
    backend_name = engine.backend_name
    assert backend_name in _VALID_BACKENDS, (
        f"engine.backend_name={backend_name!r} not in {sorted(_VALID_BACKENDS)}"
    )
    actual = shared_state.get_state("ai_backend")
    assert actual == backend_name, (
        f"shared_state['ai_backend']={actual!r} != "
        f"engine.backend_name={backend_name!r}"
    )


# ---------------------------------------------------------------------------
# The property.
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    ops=st.lists(
        st.sampled_from(_OP_ALPHABET),
        min_size=0,
        max_size=10,
    ),
)
def test_shared_state_ai_backend_strict_equality_under_arbitrary_op_sequences(
    ops: List[str],
) -> None:
    """Feature: npu-qnn-provider, Property 9: shared_state ai_backend strict equality.

    For every drawn sequence of operations from the alphabet, replay the
    sequence against a freshly constructed :class:`AIVisionEngine` with the
    provider cascade mocked at the ``select_provider`` boundary. After each
    operation, assert the strict-equality invariant defined by Reqs 5.4 and
    5.4a:

    * ``shared_state["ai_backend"] == engine.backend_name``
    * ``engine.backend_name in {"qnn", "directml", "ultralytics", "none"}``

    The empty sequence is also drawn by Hypothesis; the invariant must hold
    on the initial post-construction state because ``__init__`` calls
    ``_update_state_metrics`` which seeds ``ai_backend`` to ``"none"``.

    Validates: Requirements 5.4 (shared-state update on successful load),
    5.4a (strict-equality state-machine invariant across load success,
    load failure, and release).
    """
    engine, shared_state = _build_engine()

    # Initial state — Req 5.4a holds before any op because the constructor
    # writes ``ai_backend = "none"`` via ``_update_state_metrics``.
    _assert_strict_equality(engine, shared_state)

    for op in ops:
        _apply_op(engine, op)
        _assert_strict_equality(engine, shared_state)
