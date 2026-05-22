"""Master-toggle reset semantics — minimal pipeline.

The previous architecture maintained EMA history and sticky-lock
identity across detection frames; the master-toggle reset path had to
clear all of that synchronously to give the user a clean re-entry. The
minimal pipeline (see ``aim/pipeline.py``) does not maintain any
inter-frame state, so the reset is trivially correct: there is nothing
to clear.

We keep one test in this file to pin the contract that
``_LockState.clear()`` does not raise and leaves the no-op state
container in a fully-cleared shape — the orchestrator still calls it.
"""

from __future__ import annotations

from aim.pipeline import _LockState


def test_lock_state_clear_is_idempotent_and_does_not_raise() -> None:
    """The orchestrator's master-toggle reset path calls ``clear()``.

    Even though the minimal pipeline maintains no state, the
    orchestrator still calls ``self.aim_state.clear()`` on every
    OFF→ON transition (and on every empty-detection tick). The call
    must:

      * not raise,
      * leave every attribute at its declared default,
      * be idempotent (a second consecutive call is a no-op).
    """
    state = _LockState()
    # Seed all six fields to non-default values to confirm ``clear()``
    # actually resets them (and does so deterministically).
    state.lock_x = 12.34
    state.lock_y = -56.78
    state.lock_seen_t = 999.0
    state.smooth_x = 7.7
    state.smooth_y = -3.3
    state.last_aim_t = 1234.5

    state.clear()
    assert state.lock_x is None
    assert state.lock_y is None
    assert state.lock_seen_t == 0.0
    assert state.smooth_x == 0.0
    assert state.smooth_y == 0.0
    assert state.last_aim_t is None

    # Idempotent — calling twice is the same as calling once.
    state.clear()
    assert state.lock_x is None
    assert state.lock_y is None
    assert state.lock_seen_t == 0.0
    assert state.smooth_x == 0.0
    assert state.smooth_y == 0.0
    assert state.last_aim_t is None
