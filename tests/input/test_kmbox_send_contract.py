"""
Example tests — Task 4.9 of spec ``kmbox-net-integration``.

Two contract checks for ``KmBoxNetDriver._dispatch_call`` that the property
suite (Tasks 4.5–4.8) does not naturally exercise:

  1. ``test_udp_failure_preserves_remainders`` — Req 1.8.
     A UDP transmission failure inside the underlying ``kmNet.*`` call
     MUST propagate to the caller and MUST leave ``remainder_x`` /
     ``remainder_y`` at the values ``calculate_move_amount`` produced. The
     driver must not roll the accumulator back.

  2. ``test_send_lock_serializes_concurrent_calls`` — Req 2.8.
     ``_send_lock`` is the single leaf-level lock held across each
     ``kmNet.*`` invocation. Concurrent sends from any combination of
     threads MUST observe strict mutual exclusion: no two ``kmNet.*``
     calls execute with overlapping wall-clock intervals.

**Validates: Requirements 1.8, 2.8**

Implementation notes
--------------------
The fixture pattern mirrors ``tests/input/test_kmbox_connect.py``:
``input.kmbox_net_driver.kmNet`` is the single chokepoint for vendor calls,
so replacing that module-level binding with a ``MagicMock`` is sufficient
to observe and inject every send. ``_ensure_kmnet`` is a no-op once the
binding is non-None, so no real import attempt is made.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Iterator
from unittest.mock import MagicMock

import pytest

from input import kmbox_net_driver
from input.kmbox_net_driver import ConnectionStatus, KmBoxNetDriver


# ---------------------------------------------------------------------------
# Constants and fixtures
# ---------------------------------------------------------------------------

_TEST_IP = "192.168.2.188"
_TEST_PORT = "6234"
_TEST_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def kmnet_mock() -> Iterator[MagicMock]:
    """
    Replace ``input.kmbox_net_driver.kmNet`` with a fresh ``MagicMock``.

    ``init`` returns ``0`` by default so construction reaches the
    ``CONNECTED`` state and ``_dispatch_call`` does not short-circuit on
    the connection-status gate. Tests that need a different scenario for
    a particular method (e.g. ``move`` raising) override that attribute's
    ``side_effect`` after fixture setup.

    The original binding is restored on teardown so test order is
    irrelevant.
    """
    original = kmbox_net_driver.kmNet
    mock = MagicMock(name="kmNet")
    mock.init.return_value = 0
    kmbox_net_driver.kmNet = mock
    try:
        yield mock
    finally:
        kmbox_net_driver.kmNet = original


def _make_driver(**overrides) -> KmBoxNetDriver:
    """Construct a ``KmBoxNetDriver`` with the canonical test args."""
    kwargs = {
        "ip": _TEST_IP,
        "port": _TEST_PORT,
        "uuid": _TEST_UUID,
        # Use plaintext routing so the patched ``kmNet.move`` (not
        # ``kmNet.enc_move``) is the active path. The encryption-routing
        # property suite (Task 4.5, P1) covers the encrypted variant
        # separately; this test focuses on the failure-propagation
        # contract which is identical between the two tables.
        "use_encryption": False,
        "target_cps": 10.0,
    }
    kwargs.update(overrides)
    return KmBoxNetDriver(**kwargs)


# ---------------------------------------------------------------------------
# Req 1.8 — UDP failure preserves accumulator state
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_udp_failure_preserves_remainders(kmnet_mock: MagicMock) -> None:
    """
    Validates Req 1.8.

    When the underlying ``kmNet.move`` call raises a transmission error,
    the driver MUST:

      - propagate the exception to the caller (no swallowing inside
        ``_dispatch_call`` or ``send_move``),
      - leave ``remainder_x`` / ``remainder_y`` at the values
        ``calculate_move_amount`` produced — the accumulator is NOT
        rolled back to the pre-call state.

    The chosen input ``(1.7, 2.3)`` produces an integer delta of ``(1, 2)``
    via ``BaseMouse.calculate_move_amount`` and leaves the remainders at
    approximately ``(0.7, 0.3)``. Those are the values the driver MUST
    preserve when ``kmNet.move(1, 2)`` raises ``OSError``.
    """
    # Plaintext routing — the patched ``kmNet.move`` is the active path.
    kmnet_mock.move.side_effect = OSError("transient UDP failure")

    driver = _make_driver()
    # Sanity: the driver must be CONNECTED before the dispatch reaches
    # the patched ``kmNet.move``; otherwise ``_dispatch_call`` would
    # silently drop the call (Req 6.9) and we would observe no exception.
    assert driver.connection_status is ConnectionStatus.CONNECTED
    assert driver.remainder_x == 0.0
    assert driver.remainder_y == 0.0

    # The exception MUST propagate. Asserting ``OSError`` (rather than
    # the broader ``Exception``) keeps the contract sharp: a different
    # exception class would indicate the driver has wrapped or replaced
    # the original.
    with pytest.raises(OSError, match="transient UDP failure"):
        driver.move(1.7, 2.3)

    # ``kmNet.move`` was reached exactly once with the integer delta
    # produced by ``calculate_move_amount`` — confirms the failure
    # occurred inside the dispatch path, not before.
    kmnet_mock.move.assert_called_once_with(1, 2)
    # And no plaintext fallback or alternate call was issued.
    kmnet_mock.enc_move.assert_not_called()

    # The accumulator state ``calculate_move_amount`` produces from
    # ``(1.7, 2.3)`` with starting remainders ``(0.0, 0.0)``:
    #
    #     remainder_x = 1.7 - int(1.7) = 0.7  (approx, float precision)
    #     remainder_y = 2.3 - int(2.3) = 0.3  (approx, float precision)
    #
    # Req 1.8 requires these values be preserved as-is on the failure
    # path. ``pytest.approx`` absorbs the float noise from the subtract.
    assert driver.remainder_x == pytest.approx(0.7)
    assert driver.remainder_y == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Req 2.8 — _send_lock serializes concurrent UDP sends
# ---------------------------------------------------------------------------


# Number of worker threads that race ``_dispatch_call``. 8 threads is enough
# to make a missing ``_send_lock`` show up as overlapping intervals on a
# typical multi-core machine while keeping the wall-clock cost of the test
# bounded.
_CONCURRENT_THREADS = 8

# Calls per worker thread. With 8 threads × 6 calls × 2 ms = ~96 ms of
# serialized work, which is fast enough for unit-test runtimes.
_CALLS_PER_THREAD = 6

# Wall-clock duration of each instrumented ``kmNet.*`` invocation. The
# sleep needs to be long enough that two un-serialized invocations on
# different threads would visibly overlap, but short enough to keep the
# total test cost reasonable. 2 ms per call × 48 calls = ~96 ms baseline.
_CALL_SLEEP_S = 0.002

# Logical commands routed through ``_dispatch_call``. Mixed across
# threads to reproduce the realistic call pattern (move from AimOutput,
# button edges from click thread, scroll, keys from key_press).
_COMMAND_POOL = ("move", "left", "right", "middle", "wheel", "keydown", "keyup")


@pytest.mark.unit
def test_send_lock_serializes_concurrent_calls(kmnet_mock: MagicMock) -> None:
    """
    Validates Req 2.8.

    ``_send_lock`` is held across each ``kmNet.*`` call inside
    ``_dispatch_call``. With ``_CONCURRENT_THREADS`` workers issuing a
    random mix of dispatch calls, the captured ``(entry, exit)`` intervals
    MUST be pairwise non-overlapping — i.e. for any two intervals
    ``(s1, e1)`` and ``(s2, e2)`` the relation ``e1 <= s2 OR e2 <= s1``
    holds.

    The instrumentation: every ``kmNet.*`` mock attribute is configured
    with a single shared ``side_effect`` that records ``(start, end)``
    timestamps and sleeps for a fixed interval inside the (presumed) lock.
    If ``_dispatch_call`` failed to acquire ``_send_lock``, two workers
    could enter the side_effect concurrently and produce overlapping
    intervals — the assertion below would catch that.
    """
    intervals: list[tuple[float, float]] = []
    intervals_lock = threading.Lock()

    def instrumented(*_args, **_kwargs) -> int:
        # Stamp the interval boundaries around a fixed sleep. The sleep
        # is what makes overlap detectable: if two threads enter
        # concurrently, their intervals will overlap by at least
        # ``_CALL_SLEEP_S`` minus scheduling jitter.
        start = time.monotonic()
        time.sleep(_CALL_SLEEP_S)
        end = time.monotonic()
        # The append itself must be safe under concurrency; we use a
        # separate lock so the test fixture does not piggy-back on
        # ``_send_lock`` and accidentally enforce serialization that the
        # driver is not providing.
        with intervals_lock:
            intervals.append((start, end))
        return 0

    # Wire the instrumented side_effect into every command attribute the
    # plaintext dispatch table will reach.
    for fn_name in KmBoxNetDriver._PLAINTEXT_FN.values():
        getattr(kmnet_mock, fn_name).side_effect = instrumented

    driver = _make_driver()
    assert driver.connection_status is ConnectionStatus.CONNECTED

    # Per-thread random sequence generated up front so the workers do not
    # contend on a shared RNG (which would itself need a lock and add
    # noise to the timing). ``Random(seed)`` per thread keeps the test
    # deterministic across runs.
    rng = random.Random(0xC0FFEE)
    per_thread_cmds: list[list[str]] = [
        [rng.choice(_COMMAND_POOL) for _ in range(_CALLS_PER_THREAD)]
        for _ in range(_CONCURRENT_THREADS)
    ]

    # Barrier synchronizes the worker entry so all threads start their
    # first dispatch call at roughly the same wall-clock instant. This
    # maximizes the probability of overlap if ``_send_lock`` were absent
    # — a sequential start would naturally space the calls and hide the
    # bug.
    barrier = threading.Barrier(_CONCURRENT_THREADS)

    def worker(cmds: list[str]) -> None:
        barrier.wait()
        for cmd in cmds:
            # The dispatched arg pattern mirrors the real send-sites
            # (e.g. ``move(int, int)``, ``left(state)``); the values
            # themselves are irrelevant — only the dispatch and locking
            # behaviour is under test.
            if cmd == "move":
                driver._dispatch_call(cmd, 1, 2)
            elif cmd == "wheel":
                driver._dispatch_call(cmd, 1)
            else:
                driver._dispatch_call(cmd, 1)

    threads = [
        threading.Thread(
            target=worker,
            args=(per_thread_cmds[i],),
            name=f"KmBoxSendWorker-{i}",
            daemon=True,
        )
        for i in range(_CONCURRENT_THREADS)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
        assert not t.is_alive(), f"worker {t.name} did not terminate"

    # Every dispatch call must have reached the side_effect. If any were
    # silently dropped (e.g. by a connection-status check we did not
    # account for) the overlap assertion below would be vacuously true
    # against a small sample, so verify the count first.
    expected_calls = _CONCURRENT_THREADS * _CALLS_PER_THREAD
    assert len(intervals) == expected_calls, (
        f"expected {expected_calls} dispatch calls, got {len(intervals)}"
    )

    # Sort by start time and check adjacency: with serialized execution,
    # ``intervals[i].end <= intervals[i + 1].start`` for every pair. We
    # use ``<=`` (not ``<``) because two adjacent intervals with the
    # same monotonic timestamp at the boundary are still non-overlapping.
    intervals.sort(key=lambda iv: iv[0])
    for i in range(len(intervals) - 1):
        s1, e1 = intervals[i]
        s2, e2 = intervals[i + 1]
        assert e1 <= s2, (
            f"_send_lock failed to serialize: interval[{i}]=({s1:.6f}, {e1:.6f}) "
            f"overlaps interval[{i + 1}]=({s2:.6f}, {e2:.6f}) "
            f"by {e1 - s2:.6f}s"
        )
