"""Operator-override path — minimal pipeline (intentionally a no-op).

The previous operator-override design tried to detect physical operator
input via the kmbox Monitor_Channel echo and gate the aim pipeline on
the detection. Live testing on the Valorant range showed the framework
was tripping its own override on its own move-echoes, freezing the
pipeline after the first acquisition. The minimal pipeline (see
``aim/pipeline.py``) does not need an explicit override gate: when the
operator moves the mouse, the next detection frame's closest-enemy
selection naturally re-anchors to whichever bot is now near the new
crosshair position.

``aim/override.py`` is kept as a quiet no-op shim so existing call
sites in ``main.py`` do not break. These tests pin that no-op
contract: every method exists, accepts the documented arguments, does
not raise, and ``is_overridden`` always returns ``False`` so the aim
pipeline never gates on it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from aim.override import (
    DEFAULT_THRESHOLD_COUNTS,
    DEFAULT_WINDOW_S,
    OperatorOverride,
)


def _make_override() -> OperatorOverride:
    """Construct an override against a mocked driver.

    The override is a no-op shim — it does not register any callback
    on the driver — so a ``MagicMock`` substitute satisfies the
    constructor's type contract without touching the real driver.
    """
    return OperatorOverride(
        driver=MagicMock(name="KmBoxNetDriverMock"),
        threshold_counts=DEFAULT_THRESHOLD_COUNTS,
        window_s=DEFAULT_WINDOW_S,
    )


def test_override_is_a_quiet_noop_after_construction() -> None:
    """Constructor + ``is_overridden`` contract.

    A freshly-constructed override never reports overridden, regardless
    of the constructor arguments. The shim does not register a
    Monitor_Channel callback, so the driver's listener thread never
    invokes anything that could flip the flag.
    """
    override = _make_override()
    assert override.is_overridden() is False


def test_override_lifecycle_methods_do_not_raise() -> None:
    """``start`` / ``stop`` / ``clear`` / ``note_self_move`` are no-ops.

    The orchestrator calls these from ``initialize_input`` and
    ``cleanup``; they must accept the documented arguments and not
    raise so the orchestrator's lifecycle is uninterrupted.
    """
    override = _make_override()
    override.start()
    override.note_self_move()
    override.clear()
    override.stop()
    # Re-entry is safe — calling stop twice or clear after stop must
    # not raise either.
    override.stop()
    override.clear()
    assert override.is_overridden() is False


def test_override_never_flips_under_synthetic_events() -> None:
    """No external trigger can flip ``is_overridden`` to ``True``.

    The shim has no public surface for accumulating events, so even
    a malicious caller calling every method in every order leaves the
    flag at ``False``.
    """
    override = _make_override()
    for _ in range(100):
        override.note_self_move()
        override.clear()
    assert override.is_overridden() is False
