"""
Property test — Task 7.7 of spec ``kmbox-net-integration``.

# Feature: kmbox-net-integration, Property 7: Reconnect FSM converges
#   within the 3-attempt budget.

**Property 7: Reconnect FSM converges within the 3-attempt budget**

    *For any* tuple ``(o1, o2, o3)`` of three booleans representing the
    outcomes of three sequential ``kmNet.init`` invocations issued by
    :meth:`KmBoxNetDriver._enter_reconnect_fsm` — where ``True`` means
    the call returns the success code ``0`` and ``False`` means the call
    returns a non-zero result code — the FSM SHALL terminate with:

      * ``connection_status == CONNECTED`` and ``initialized is True``
        if **any** element of the tuple is ``True``, after exactly
        ``index_of_first_True + 1`` invocations of ``kmNet.init``;
      * ``connection_status == FAILED`` and ``initialized is False`` if
        **all** three elements are ``False``, after exactly three
        invocations of ``kmNet.init``.

    In every case the universal invariant ``kmNet.init.call_count <= 3``
    SHALL hold — the FSM never issues a fourth attempt regardless of
    outcome.

**Validates: Requirements 6.6, 6.7, 6.8**

Implementation notes
--------------------
The FSM is invoked from :meth:`KmBoxNetDriver._heartbeat_loop` whenever
a heartbeat probe fails (timeout, exception, or non-zero result).
Property 7 captures the design's hard cap on reconnect attempts and the
two terminal-state contracts:

* Req 6.6 — three attempts maximum, 500 ms (``_heartbeat_stop.wait(0.5)``)
  between attempts.
* Req 6.7 — a successful attempt resumes ``CONNECTED`` and stops further
  attempts.
* Req 6.8 — three exhausted attempts terminate in ``FAILED``.

Threading and timing patches
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* :meth:`KmBoxNetDriver._heartbeat_loop` is replaced with a no-op for the
  duration of construction so the daemon heartbeat thread exits
  immediately. Without this patch the heartbeat thread would race the
  test body — its first probe (``kmNet.monitor(0)``) returns a
  ``MagicMock`` that compares unequal to ``0`` (``MagicMock.__eq__``
  returns ``NotImplemented`` → Python falls back to identity), so
  ``_heartbeat_call`` reports failure and the loop enters the same FSM
  the property is trying to characterize, polluting ``kmNet.init``'s
  call count before the test even configures the outcome script.

* ``driver._heartbeat_stop`` is swapped for a :class:`_NoWaitEvent` after
  construction. The FSM's inter-attempt backoff calls
  ``self._heartbeat_stop.wait(0.5)`` between failed attempts; a real
  :class:`threading.Event` would impose a 500 ms wait per gap (1 s per
  example for the all-fail case, ~100 s across 100 Hypothesis examples).
  The fake's ``wait()`` returns ``False`` immediately so the FSM
  proceeds to the next attempt without delay, and ``is_set()`` returns
  ``False`` so the FSM never short-circuits via the
  release-interrupt branch.

The :meth:`KmBoxNetDriver._connect` worker thread is **not** patched —
the bounded ``queue.Queue + Thread.join(timeout=5.0)`` pattern resolves
in microseconds because ``mock.init`` returns synchronously.
:meth:`KmBoxNetDriver._connect` itself is the unit under test and must
be exercised through its real control-flow path (lock acquisition,
state transitions) so the FSM's interaction with it is faithful.

Outcome-to-script translation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``mock.init.side_effect`` is set to a 3-element list ``[0 if ok else 1
for ok in outcome]``. The vendor contract uses ``0`` as success and any
non-zero as failure, which :meth:`KmBoxNetDriver._connect` checks
explicitly (``if payload != 0: ... return False``). A 3-element list is
sufficient because :meth:`KmBoxNetDriver._enter_reconnect_fsm` is
hard-capped at three calls (``for attempt in range(1, 4)``); the test's
``mock.init.call_count <= 3`` assertion is the structural check on
that cap.
"""

from __future__ import annotations

from typing import Tuple
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from input import kmbox_net_driver
from input.kmbox_net_driver import ConnectionStatus, KmBoxNetDriver


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Sentinel constructor args mirroring the canonical ``config.yaml`` entries.
_TEST_IP = "192.168.2.188"
_TEST_PORT = "6234"
_TEST_UUID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _NoWaitEvent:
    """Stand-in for :class:`threading.Event` whose ``wait`` returns instantly.

    Replaces ``driver._heartbeat_stop`` for the FSM-under-test so the
    inter-attempt backoff call ``self._heartbeat_stop.wait(0.5)`` does not
    impose a 500 ms wall-clock delay per gap. Returning ``False`` from
    ``wait`` and ``is_set`` mirrors a "release was never called" event:
    the FSM neither short-circuits via its release-interrupt branch nor
    sleeps between attempts.

    ``set`` and ``clear`` are no-ops; the FSM does not call them but the
    interface is kept symmetric so a future change that does call them
    will not :class:`AttributeError`.
    """

    __slots__ = ()

    def is_set(self) -> bool:
        return False

    def set(self) -> None:  # pragma: no cover - defensive, not exercised
        return None

    def clear(self) -> None:  # pragma: no cover - defensive, not exercised
        return None

    def wait(self, timeout: float | None = None) -> bool:
        # Returning False means "event was not set within the timeout".
        # The FSM treats this as "no release request, continue with next
        # attempt" and proceeds without delay.
        return False


def _build_connected_driver(mock: MagicMock) -> KmBoxNetDriver:
    """Construct a CONNECTED driver with a no-op heartbeat thread.

    Patching :meth:`KmBoxNetDriver._heartbeat_loop` to a no-op for the
    duration of construction prevents the daemon heartbeat thread from
    racing the test body. ``mock.init`` is left at its default return
    value of ``0`` so the initial connect lands in ``CONNECTED`` (the
    state from which a heartbeat failure would normally trigger the FSM
    that this property characterizes).
    """
    # ``_heartbeat_loop`` is the target of the daemon ``_heartbeat_thread``
    # spawned at the end of ``__init__``. Replacing it with a no-op means
    # the thread runs the lambda and exits immediately, leaving the
    # driver in the same CONNECTED state ``__init__`` produced — but
    # without an active probe loop racing our FSM invocation.
    with patch.object(KmBoxNetDriver, "_heartbeat_loop", lambda self: None):
        driver = KmBoxNetDriver(
            ip=_TEST_IP,
            port=_TEST_PORT,
            uuid=_TEST_UUID,
            use_encryption=False,
            target_cps=10.0,
        )

    # Wait for the no-op heartbeat thread to exit. Hygiene only — the
    # lambda body is empty so the thread typically exits before this
    # line is reached.
    if driver._heartbeat_thread is not None:
        driver._heartbeat_thread.join(timeout=1.0)

    return driver


# ---------------------------------------------------------------------------
# Hypothesis strategy and settings
# ---------------------------------------------------------------------------

# Three-element outcome tuple. Each element selects success (True → 0)
# or failure (False → 1) for the corresponding ``kmNet.init`` invocation
# the FSM issues. Hypothesis's default ``booleans`` strategy explores all
# 8 possibilities; with ``max_examples=100`` each branch is sampled
# multiple times (the all-fail case is the FAILED-terminal branch; the
# three first-True positions exercise the early-exit short-circuit at
# attempts 1, 2, and 3 respectively).
_OUTCOME_STRATEGY = st.tuples(st.booleans(), st.booleans(), st.booleans())

# ``max_examples=100`` matches the task plan's directive. ``deadline=None``
# disables the per-example time budget — each example spawns three
# real worker threads (one per ``_connect()`` attempt) for ``kmNet.init``
# and Windows scheduler jitter can flag spurious deadline failures on
# CI even though the wall-clock cost is negligible.
_PROPERTY_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        # The kmNet mock and ``_heartbeat_loop`` patch are reinstalled
        # per Hypothesis example inside the test body, not via a
        # function-scoped fixture; the suppression matches the rest of
        # the kmbox property-test suite.
        HealthCheck.function_scoped_fixture,
        HealthCheck.differing_executors,
    ],
)


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@pytest.mark.unit
@given(outcome=_OUTCOME_STRATEGY)
@_PROPERTY_SETTINGS
def test_reconnect_fsm_converges_within_three_attempts(
    outcome: Tuple[bool, bool, bool],
) -> None:
    """
    Property 7: Reconnect FSM converges within the 3-attempt budget.

    For every tuple ``(o1, o2, o3)`` of three booleans representing the
    outcomes of the FSM's three sequential ``kmNet.init`` invocations:

      * ``mock.init.call_count <= 3`` (universal invariant — Req 6.6).
      * If ``any(outcome)``: terminal ``connection_status == CONNECTED``,
        ``initialized is True``, and exactly ``outcome.index(True) + 1``
        invocations of ``kmNet.init`` occurred (Req 6.7 — the FSM stops
        at the first success).
      * If ``not any(outcome)``: terminal ``connection_status == FAILED``,
        ``initialized is False``, and exactly three invocations of
        ``kmNet.init`` occurred (Req 6.8 — three exhausted attempts).

    Validates: Requirements 6.6, 6.7, 6.8.
    """
    original = kmbox_net_driver.kmNet
    mock = MagicMock(name="kmNet")
    # Default success code so the initial ``__init__`` connect lands in
    # CONNECTED. The FSM-specific script is installed below after the
    # construction call returns.
    mock.init.return_value = 0
    kmbox_net_driver.kmNet = mock

    try:
        driver = _build_connected_driver(mock)

        # Sanity: construction must have left the driver in CONNECTED,
        # otherwise the FSM's entry transition (RECONNECTING) would be
        # measured against the wrong baseline.
        assert driver.connection_status == ConnectionStatus.CONNECTED, (
            f"precondition violated: expected CONNECTED after __init__, "
            f"got {driver.connection_status!r}"
        )

        # Replace the real Event with a no-wait fake so the FSM's
        # 500 ms inter-attempt backoff collapses to zero wall-clock time.
        # The fake's ``is_set()`` also returns False so the FSM never
        # short-circuits via the release-interrupt branch — that branch
        # is exercised separately in the heartbeat example tests
        # (Task 7.9), not here.
        driver._heartbeat_stop = _NoWaitEvent()

        # Reset the call counter so the FSM-issued calls are the only
        # ones the property observes. The construction-time
        # ``kmNet.init(ip, port, uuid)`` call (counted as 1 before this
        # reset) is not part of the FSM's budget per Req 6.6.
        mock.init.reset_mock()

        # Outcome-to-script translation. ``side_effect`` as a list makes
        # the mock return successive values on successive calls; the
        # 3-element length is sufficient because the FSM is hard-capped
        # at three calls and the property's universal invariant
        # ``call_count <= 3`` is the structural check on that cap.
        mock.init.side_effect = [0 if ok else 1 for ok in outcome]

        # Invoke the FSM directly. The driver's heartbeat thread has
        # already exited (no-op patch above), so this is the only code
        # path that will touch ``mock.init`` from this point forward.
        driver._enter_reconnect_fsm()

        # ─── Universal invariant ─────────────────────────────────────
        # The FSM never issues a fourth attempt. This is the headline
        # claim of Property 7 and the strongest assertion against a
        # hypothetical regression that loosened the loop bound (Req 6.6).
        assert mock.init.call_count <= 3, (
            f"FSM exceeded 3-attempt budget: call_count="
            f"{mock.init.call_count}, outcome={outcome!r}"
        )

        # ─── Branch invariants ───────────────────────────────────────
        if any(outcome):
            # Req 6.7 — first success terminates the FSM in CONNECTED.
            # The exact call count is ``outcome.index(True) + 1`` because
            # the FSM consumes one ``side_effect`` entry per attempt and
            # returns immediately when ``_connect()`` reports True.
            first_success_index = outcome.index(True)
            expected_calls = first_success_index + 1

            assert mock.init.call_count == expected_calls, (
                f"expected exactly {expected_calls} init calls (first "
                f"success at index {first_success_index}), got "
                f"{mock.init.call_count}; outcome={outcome!r}"
            )
            assert driver.connection_status == ConnectionStatus.CONNECTED, (
                f"expected terminal CONNECTED on any-success outcome, "
                f"got {driver.connection_status!r}; outcome={outcome!r}"
            )
            assert driver.initialized is True, (
                f"expected initialized=True on any-success outcome, "
                f"got {driver.initialized!r}; outcome={outcome!r}"
            )
        else:
            # Req 6.8 — three exhausted failures terminate in FAILED.
            # The all-fail case is the only path that consumes the full
            # ``side_effect`` script.
            assert mock.init.call_count == 3, (
                f"expected exactly 3 init calls on all-fail outcome, "
                f"got {mock.init.call_count}; outcome={outcome!r}"
            )
            assert driver.connection_status == ConnectionStatus.FAILED, (
                f"expected terminal FAILED on all-fail outcome, "
                f"got {driver.connection_status!r}; outcome={outcome!r}"
            )
            assert driver.initialized is False, (
                f"expected initialized=False on all-fail outcome, "
                f"got {driver.initialized!r}; outcome={outcome!r}"
            )
    finally:
        # Restore the original module-level ``kmNet`` binding regardless
        # of test outcome so subsequent tests start from a clean slate.
        kmbox_net_driver.kmNet = original
