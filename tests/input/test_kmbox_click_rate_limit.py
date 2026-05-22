"""
Property test — Task 4.8 of spec ``kmbox-net-integration``.

# Feature: kmbox-net-integration, Property 4: ``click()`` rate limit at
#   ``target_cps``.

**Property 4: ``click()`` rate limit at ``target_cps``**

    *For any* sequence of ``click()`` invocations on the driver, the number
    of admitted ``click`` press+release pairs emitted within any sliding
    window of length ``1.0 / target_cps`` seconds SHALL be at most one.
    Equivalently, for every pair of consecutive admitted clicks at fake
    monotonic times ``t_a`` and ``t_b`` (with ``t_a < t_b``):

        t_b - t_a  >=  1.0 / target_cps

**Validates: Requirements 1.5**

Implementation notes
--------------------
``KmBoxNetDriver.click`` enforces the rate limit in the *calling* thread,
BEFORE spawning the per-click worker thread that runs ``send_click``. The
limiter reads ``time.monotonic()`` (not ``time.time()`` — Req 1.5 must be
immune to wall-clock adjustments) and compares the elapsed time against
``1.0 / self.target_cps`` keyed off ``self._last_click_monotonic``. If the
window is open, the click is admitted and ``_last_click_monotonic`` is
stamped with the current monotonic time.

We exercise the contract deterministically by:

  1. Replacing the driver-module-local ``time.monotonic`` with a fake
     clock controlled by the test (``patch('input.kmbox_net_driver.time.monotonic', new=...)``).
     Patching the dotted path keeps the substitution scoped to the
     ``with`` block so other tests run with the real clock.
  2. Replacing ``threading.Thread`` inside the driver module with a
     ``FakeThread`` whose ``start()`` is a no-op and whose ``is_alive()``
     is permanently ``False``. This (a) prevents the click worker from
     running in real wall time and racing the test, and (b) keeps
     ``self.click_thread.is_alive()`` ``False`` between calls so the
     parent ``BaseMouse.click`` "thread already in flight" gate cannot
     mask a Req 1.5 admission.
  3. Driving the fake clock forward by the Hypothesis-generated
     inter-click delays and recording, after each ``click()``, whether
     ``_last_click_monotonic`` was updated. Updates correspond exactly to
     admissions (the only place the driver writes ``_last_click_monotonic``
     is on the admit path inside ``click``).

Crucially, the driver is constructed BEFORE the patches are installed:
``_connect()`` itself spawns a real daemon worker thread to bound
``kmNet.init`` against the 5-second cap (Req 2.4), so the real
``threading.Thread`` must be in place during construction.

The strategy ranges (``inter-click delay`` in ``[0.0, 1.0]``s and
``target_cps`` in ``[1.0, 1000.0]``) match the task plan verbatim.
"""

from __future__ import annotations

import math
from typing import Any, List, Tuple
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from input import kmbox_net_driver
from input.kmbox_net_driver import ConnectionStatus, KmBoxNetDriver


# ---------------------------------------------------------------------------
# Constants and strategies
# ---------------------------------------------------------------------------

# Sentinel constructor args reused across every driver instance built in
# this module. Values mirror the live ``config.yaml`` entries.
_TEST_IP = "192.168.2.188"
_TEST_PORT = "6234"
_TEST_UUID = "00000000-0000-0000-0000-000000000000"

# Inter-click delay in seconds. ``allow_nan`` / ``allow_infinity`` are
# disabled because the rate-limit window arithmetic is undefined for
# those values; non-finite delays are not part of the Req 1.5 contract.
# ``min_value=0.0`` deliberately includes the boundary so the strategy
# exercises the "two clicks at the same monotonic instant" case
# (the second MUST be dropped for any ``target_cps < +inf``).
_DELAY_STRATEGY = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

# A sequence of inter-click delays. ``min_size=0`` covers the trivial
# empty-sequence case (no clicks → no pairs → vacuously satisfied).
# ``max_size=50`` keeps each example bounded but long enough for both
# admitted and dropped runs to interleave.
_DELAY_SEQUENCE_STRATEGY = st.lists(
    _DELAY_STRATEGY, min_size=0, max_size=50
)

# ``target_cps`` in [1.0, 1000.0]. The lower bound matches
# ``BaseMouse.__init__``'s ``max(target_cps, 1.0)`` clamp, so values at
# or above 1.0 are passed through verbatim and the test's
# ``1.0 / target_cps`` window equals the driver's window bit-exactly.
# The upper bound reflects the Req 1.5 wording "strictly greater than 0
# and less than or equal to 1000".
_TARGET_CPS_STRATEGY = st.floats(
    min_value=1.0,
    max_value=1000.0,
    allow_nan=False,
    allow_infinity=False,
)

# ``max_examples=100`` matches the task plan's
# ``@settings(max_examples=100)`` directive. ``deadline=None`` disables
# the per-example time budget — the property body is deterministic
# (the fake clock makes each example a pure function of inputs) but
# Windows scheduler jitter can flag spurious deadline failures on CI.
# ``function_scoped_fixture`` is suppressed because the driver and
# kmNet patch are reinstalled once per Hypothesis example inside the
# test body, not via a function-scoped fixture (see commentary in the
# test docstring).
_PROPERTY_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)


# ---------------------------------------------------------------------------
# Fake-thread helper
# ---------------------------------------------------------------------------


class _FakeThread:
    """
    Drop-in for ``threading.Thread`` that does NOT execute its target.

    ``KmBoxNetDriver.click`` admits a click by:

      1. checking the rate-limit window (the assertion under test),
      2. checking ``self.click_thread.is_alive()`` is ``False``, and
      3. spawning a new daemon ``threading.Thread`` to run
         ``send_click(delay_before_click)``.

    Steps (1) and (2) are what we want to observe; step (3) is incidental
    and would otherwise (a) introduce a real thread that races the test's
    deterministic clock control and (b) call ``time.sleep`` against the
    real wall clock. Replacing ``threading.Thread`` with this fake
    suppresses (3) while keeping ``is_alive()`` ``False`` so subsequent
    iterations are not blocked by a phantom in-flight worker.

    The signature accepts ``*args, **kwargs`` so it tolerates any Thread
    constructor shape (positional ``target``, keyword ``args``, ``name``,
    ``daemon``, …) the driver might use now or in the future.
    """

    __slots__ = ()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Intentionally do nothing — we don't even retain target/args
        # because the property only inspects clock-driven admission, not
        # the worker side effects.
        pass

    def start(self) -> None:
        # Suppress the worker so ``send_click`` never runs on the real
        # clock. The rate-limit gate has already executed in the calling
        # thread by the time we get here.
        pass

    def is_alive(self) -> bool:
        # Permanently False so the ``BaseMouse.click_thread.is_alive()``
        # check inside ``KmBoxNetDriver.click`` never short-circuits.
        return False


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@pytest.mark.unit
@_PROPERTY_SETTINGS
@given(delays=_DELAY_SEQUENCE_STRATEGY, target_cps=_TARGET_CPS_STRATEGY)
def test_click_rate_limit_at_target_cps(
    delays: List[float], target_cps: float
) -> None:
    """
    Validates Req 1.5.

    For any sequence of inter-click delays drawn from ``[0.0, 1.0]`` and
    any ``target_cps`` drawn from ``[1.0, 1000.0]``, the timestamps of the
    clicks admitted by ``KmBoxNetDriver.click`` (under a fake monotonic
    clock controlled by the test) SHALL satisfy:

        for every pair of consecutive admitted timestamps (t_a, t_b):
            t_b - t_a  >=  1.0 / target_cps

    i.e. at most one click admission per sliding window of
    ``1.0 / target_cps`` seconds.
    """
    # ----- Install kmNet mock so _connect() lands in CONNECTED -----------
    # ``_connect()`` calls ``kmNet.init(ip, port, uuid)`` on a real worker
    # thread bounded by ``queue.get(timeout=5.0)``. With ``init`` returning
    # ``0`` immediately the worker completes quickly, the bounded join
    # succeeds, and the driver transitions to CONNECTED so subsequent
    # ``_dispatch_call`` invocations are not silently dropped.
    original_kmnet = kmbox_net_driver.kmNet
    mock_kmnet = MagicMock(name="kmNet")
    mock_kmnet.init.return_value = 0
    kmbox_net_driver.kmNet = mock_kmnet
    try:
        driver = KmBoxNetDriver(
            ip=_TEST_IP,
            port=_TEST_PORT,
            uuid=_TEST_UUID,
            use_encryption=False,
            target_cps=target_cps,
        )
        # Precondition: the property only meaningfully exercises the
        # admit path while the driver is CONNECTED. Failing this here
        # turns a fixture regression into a precondition error rather
        # than a confusing property failure.
        assert driver.connection_status is ConnectionStatus.CONNECTED, (
            "fixture precondition failed: driver did not reach CONNECTED"
        )

        # Sanity: BaseMouse should have clamped target_cps to >=1.0 and
        # since our strategy already starts at 1.0 we expect equality.
        # This makes ``1.0 / target_cps`` in the test equal to the
        # driver's ``1.0 / self.target_cps`` bit-exactly.
        assert driver.target_cps == target_cps, (
            "BaseMouse target_cps clamp altered the test's window; "
            "test assumes target_cps in [1.0, 1000.0] passes through"
        )

        # ----- Fake monotonic clock -----------------------------------
        # ``patch('...time.monotonic', new=...)`` rewrites only the
        # ``monotonic`` attribute on the module's ``time`` reference for
        # the duration of the ``with`` block, then restores it on exit.
        # The driver reads through ``time.monotonic()`` so it sees our
        # function; the rest of the process keeps the real clock.
        fake_clock = {"t": 0.0}

        def fake_monotonic() -> float:
            return fake_clock["t"]

        # ----- Drive the sequence -------------------------------------
        # We patch ``threading.Thread`` to ``_FakeThread`` so click()
        # does not spawn a real worker (which would call ``time.sleep``
        # against the real clock and race the test).
        admitted_timestamps: List[float] = []

        with patch(
            "input.kmbox_net_driver.time.monotonic",
            new=fake_monotonic,
        ), patch(
            "input.kmbox_net_driver.threading.Thread",
            new=_FakeThread,
        ):
            for delay in delays:
                # Advance the fake clock by the Hypothesis-generated
                # inter-click delay. The first click occurs at
                # ``fake_clock['t'] = delays[0]`` (or 0 if delays is empty).
                fake_clock["t"] += delay

                # Snapshot ``_last_click_monotonic`` BEFORE the call so
                # we can detect admission unambiguously: the only place
                # the driver writes this attribute is on the admit path
                # inside ``click()``, so a post-call change == admitted.
                stamp_before = driver._last_click_monotonic

                driver.click()

                stamp_after = driver._last_click_monotonic
                if stamp_after != stamp_before:
                    # Admitted — record the fake-clock timestamp the
                    # admit path stamped (which equals fake_clock['t']
                    # because the driver reads through fake_monotonic).
                    admitted_timestamps.append(stamp_after)

        # ----- Property assertion ------------------------------------
        # For every consecutive pair of admitted timestamps, the gap
        # MUST be at least ``1.0 / target_cps``. The driver's gate is
        # ``elapsed < window → drop``; admitted therefore implies
        # ``elapsed >= window``. Because the test's fake clock is the
        # same source the driver read, the pairwise gap here equals
        # the ``elapsed`` value the driver evaluated, bit-exactly.
        window = 1.0 / target_cps
        for prev, curr in zip(admitted_timestamps, admitted_timestamps[1:]):
            gap = curr - prev
            assert gap >= window, (
                f"Req 1.5 violated: consecutive admitted clicks at "
                f"t={prev!r} and t={curr!r} have gap {gap!r} < window "
                f"{window!r} (target_cps={target_cps!r}); admissions="
                f"{admitted_timestamps!r}, delays={delays!r}"
            )

        # Sanity: every recorded timestamp is finite and monotonically
        # non-decreasing. A regression that, say, stamped a stale time
        # would surface here independent of the window check above.
        for prev, curr in zip(admitted_timestamps, admitted_timestamps[1:]):
            assert math.isfinite(curr), (
                f"non-finite admit timestamp {curr!r}; admissions="
                f"{admitted_timestamps!r}"
            )
            assert curr >= prev, (
                f"non-monotonic admit timestamps: prev={prev!r}, "
                f"curr={curr!r}"
            )
    finally:
        # Restore the module-level kmNet binding regardless of test
        # outcome so subsequent tests in the same session are not
        # contaminated by this test's mock.
        kmbox_net_driver.kmNet = original_kmnet
