"""
Property test — Task 4.3 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 1: Send_Lock discipline.

**Property 1: Send_Lock discipline**

    For any sequence of public-API calls executed concurrently on a
    single :class:`~input.kmbox_net_driver.KmBoxNetDriver` instance,
    the ``Send_Lock`` (``driver._send_lock``) is held by exactly one
    thread for the full duration of every ``UDP_Socket.sendto`` call,
    and the lock is released on both the normal-return path and every
    exception path raised by ``sendto``.

**Validates: Requirements 1.7**

Implementation notes
--------------------

The driver's ``_dispatch_call`` opens a ``with self._send_lock:`` block
whose only statement is the ``self.udp_socket.sendto(payload, addr)``
call (Requirement 1.7). To prove the invariant under concurrent load
this test:

  1. Drives the driver to ``connected`` via the standard
     :class:`~tests.input.kmbox_net.conftest.FakeDevice` handshake so
     ``_dispatch_call`` actually sends rather than dropping.
  2. Wraps ``FakeUdpSocket.sendto`` with an instrumented version that
     a) verifies the Send_Lock is held (a non-blocking
        ``driver._send_lock.acquire(blocking=False)`` MUST fail because
        ``threading.Lock`` is non-reentrant — if the calling thread
        already holds the lock, the re-acquire fails; if a *different*
        thread held it, the re-acquire also fails because the lock is
        non-reentrant), and
     b) counts in-flight ``sendto`` calls under a separate auxiliary
        lock so any moment with two simultaneous calls is observed —
        the design's "cleaner approach" referenced in tasks.md task 4.3.
  3. Spawns N worker threads, each calling ``_dispatch_call("move",
     x, y)`` repeatedly. A ``threading.Barrier`` aligns the threads so
     they all start contending at the same time.
  4. Asserts the maximum in-flight count never exceeded ``1`` and
     every recorded ``lock_held`` flag is ``True``.

A second test injects ``OSError`` via ``FakeUdpSocket.raise_on_send``
and confirms the lock is released after the exception path
(``driver._send_lock.acquire(blocking=False)`` succeeds afterwards).

A third test confirms the lock is released after the normal-return
path so subsequent dispatches do not block.

The tests do not use Hypothesis: the property is over the *concurrent
schedule* of ``sendto`` calls, not over the (already-trivial) input
domain. Concurrency tests under Hypothesis are flaky and slow; a
fixed N/iterations design with a barrier amplifies real contention.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import List, Tuple

import pytest

# Make the ``input`` package importable when pytest is launched from
# the repository root or any sub-directory. The driver ships as
# ``input/kmbox_net_driver.py`` at the project root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from input.kmbox_net_driver import (  # noqa: E402  (sys.path tweak above)
    ConnectionStatus,
    KmBoxNetDriver,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Number of concurrent worker threads. Picked large enough to expose
# real contention on a multi-core ARM64 host but small enough that a
# pytest run stays well under one second per test on CI.
_WORKER_COUNT = 8

# Number of ``_dispatch_call`` invocations per worker. The product
# (``_WORKER_COUNT * _ITERATIONS_PER_WORKER``) bounds the recorded
# observation list, so keep it modest.
_ITERATIONS_PER_WORKER = 25

# Brief delay inside the instrumented ``sendto`` wrapper, in seconds.
# Amplifies the window during which a *second* thread could observe a
# lock-held violation if the driver ever slipped the ``with`` block
# protection. ``time.sleep(0)`` would be too short under CPython's GIL
# scheduling; ~0.5 ms is plenty without slowing the suite measurably.
_SENDTO_DELAY_S = 0.0005


def _build_connected_driver(socket_factory, fake_device) -> KmBoxNetDriver:
    """Construct a connected ``KmBoxNetDriver`` against the fakes.

    The handshake reply is published into the first ``FakeUdpSocket``
    via ``socket_factory.attach_device(fake_device)`` *before* the
    driver constructor runs, so the driver's ``recvfrom`` returns the
    success reply immediately and the driver transitions to
    ``CONNECTED``.

    ``use_encryption=False`` keeps the wire path one ``sendto`` per
    ``_dispatch_call`` (the encrypted variant emits the same number
    of ``sendto`` calls but adds an extra failure mode covered by
    Property 17 / Task 4.5 — out of scope here).
    """
    socket_factory.attach_device(fake_device)
    driver = KmBoxNetDriver(
        ip="192.168.2.188",
        port="41990",
        uuid="01FBC068",
        use_encryption=False,
    )
    assert driver.initialized is True, (
        "FakeDevice handshake should drive the driver to 'connected' "
        f"but connection_status={driver.connection_status!r}"
    )
    assert driver.connection_status == ConnectionStatus.CONNECTED
    return driver


# ---------------------------------------------------------------------------
# Property 1 — Send_Lock serializes concurrent sendto calls
# ---------------------------------------------------------------------------


def test_send_lock_serializes_concurrent_dispatch(socket_factory, fake_device):
    """Send_Lock holds for the full duration of every ``sendto``.

    Spawns ``_WORKER_COUNT`` threads each issuing
    ``_ITERATIONS_PER_WORKER`` ``_dispatch_call("move", ...)`` calls
    on a single driver instance. The instrumented ``sendto`` wrapper
    records:

      * ``in_flight`` — number of ``sendto`` calls currently executing.
      * ``lock_held`` — whether the Send_Lock could *not* be acquired
        non-reentrantly during the call (truthy means the lock is
        held, satisfying Requirement 1.7).

    Asserts the maximum observed ``in_flight`` count is exactly ``1``
    (mutual exclusion) and every recorded ``lock_held`` is ``True``
    (lock-acquisition is the sole statement preceding ``sendto``).
    """
    driver = _build_connected_driver(socket_factory, fake_device)
    fake_sock = socket_factory.sockets[0]

    # Drain the handshake packet from the recorded log so subsequent
    # assertions only count command sends.
    handshake_count = len(fake_sock.sent)
    assert handshake_count == 1, (
        "Init_Handshake should emit exactly one packet, "
        f"got {handshake_count}"
    )

    # ---- instrumentation -------------------------------------------

    # Aux lock guarding the in-flight counter and the observation log.
    # Distinct from ``driver._send_lock`` so we do not perturb the
    # property under test.
    aux_lock = threading.Lock()
    in_flight = 0
    max_in_flight = 0
    # Each entry: (thread_id, in_flight_at_entry, lock_held_during_call).
    observations: List[Tuple[int, int, bool]] = []

    original_sendto = fake_sock.sendto

    def instrumented_sendto(payload: bytes, addr: Tuple[str, int]) -> int:
        nonlocal in_flight, max_in_flight

        # Probe the Send_Lock. ``threading.Lock`` is non-reentrant, so
        # if the *current* thread already holds it (the expected case
        # under ``with self._send_lock: sendto(...)`` in
        # ``_dispatch_call``), this acquire returns ``False``. If a
        # *different* thread held it, the acquire would also return
        # ``False``. The probe therefore returns ``True`` only when no
        # thread holds the lock — a Property 1 violation.
        could_acquire = driver._send_lock.acquire(blocking=False)
        lock_held = not could_acquire
        if could_acquire:
            # Release immediately so we do not deadlock the test.
            driver._send_lock.release()

        tid = threading.get_ident()
        with aux_lock:
            in_flight += 1
            current = in_flight
            if current > max_in_flight:
                max_in_flight = current
            observations.append((tid, current, lock_held))

        # Hold inside the critical section briefly to amplify any
        # concurrent send that would slip past the Send_Lock. A real
        # ``sendto`` syscall is bounded by kernel scheduling latency;
        # this artificial delay simulates a slow socket without
        # blocking on the GIL alone.
        time.sleep(_SENDTO_DELAY_S)

        try:
            return original_sendto(payload, addr)
        finally:
            with aux_lock:
                in_flight -= 1

    fake_sock.sendto = instrumented_sendto  # type: ignore[assignment]

    # ---- concurrent driver-load ------------------------------------

    barrier = threading.Barrier(_WORKER_COUNT)
    worker_errors: List[BaseException] = []
    worker_errors_lock = threading.Lock()

    def worker(worker_index: int) -> None:
        try:
            barrier.wait()
            for j in range(_ITERATIONS_PER_WORKER):
                # Deterministic-but-distinct integer arguments; the
                # test does not care about the wire bytes — only that
                # ``sendto`` is invoked one packet per call.
                x = (worker_index * 1000 + j) % 32768
                y = (worker_index * 7 - j) % 32768
                driver._dispatch_call("move", x, y)
        except BaseException as exc:  # noqa: BLE001 — propagate to test
            with worker_errors_lock:
                worker_errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(i,), daemon=True)
        for i in range(_WORKER_COUNT)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
        assert not t.is_alive(), "worker thread did not finish in 10 s"

    assert not worker_errors, (
        f"worker threads raised: {worker_errors!r}"
    )

    # ---- assertions ------------------------------------------------

    expected_command_packets = _WORKER_COUNT * _ITERATIONS_PER_WORKER
    assert len(fake_sock.sent) - handshake_count == expected_command_packets, (
        "Each ``_dispatch_call('move', ...)`` should emit exactly one "
        f"UDP packet; expected {expected_command_packets} command packets, "
        f"got {len(fake_sock.sent) - handshake_count}."
    )

    assert len(observations) == expected_command_packets, (
        "Instrumented sendto recorded the wrong number of observations: "
        f"expected {expected_command_packets}, got {len(observations)}."
    )

    # **Property 1, clause 1:** at most one thread holds the lock during
    # any sendto — i.e. the maximum number of concurrent in-flight
    # sendto calls is exactly 1.
    assert max_in_flight == 1, (
        "Send_Lock did not serialize concurrent sendto calls: "
        f"max in-flight count was {max_in_flight} (expected 1). "
        "Multiple threads entered the critical section simultaneously, "
        "violating Requirement 1.7."
    )

    # **Property 1, clause 1 (corroborating):** every recorded sendto
    # observed the Send_Lock as held.
    for tid, current, lock_held in observations:
        assert lock_held, (
            f"Thread {tid} executed FakeUdpSocket.sendto while the "
            f"Send_Lock was NOT held (in_flight={current}). "
            "Requirement 1.7 mandates lock acquisition is the sole "
            "statement preceding the sendto invocation."
        )

    # **Property 1, clause 2 (normal-return path):** after every
    # dispatch returns, the lock is released — verified by acquiring
    # it from the test thread without contention.
    final_acquired = driver._send_lock.acquire(blocking=False)
    assert final_acquired, (
        "Send_Lock not released after concurrent dispatches completed; "
        "Requirement 1.7 second clause violated on the normal-return path."
    )
    driver._send_lock.release()


# ---------------------------------------------------------------------------
# Property 1 — lock released on the OSError exception path
# ---------------------------------------------------------------------------


def test_send_lock_released_on_oserror_path(socket_factory, fake_device):
    """Send_Lock is released when ``sendto`` raises ``OSError``.

    Configures ``FakeUdpSocket.raise_on_send`` so the next ``sendto``
    raises ``OSError``, then invokes ``_dispatch_call``. The driver
    catches the ``OSError`` per Requirement 1.8, but *before* the
    ``except`` clause runs the ``with self._send_lock:`` block must
    have already released the lock (Requirement 1.7).

    Verifies the release by:

      1. Acquiring the lock non-blocking from the test thread after
         the dispatch returns — this MUST succeed.
      2. Issuing a second ``_dispatch_call`` (with the fault cleared)
         and verifying it sends a packet rather than blocking.
    """
    driver = _build_connected_driver(socket_factory, fake_device)
    fake_sock = socket_factory.sockets[0]
    handshake_count = len(fake_sock.sent)

    # Configure the fake socket to raise OSError on the *next* sendto.
    # The raise persists across calls (raise_once=False, default) so
    # we can prove the dispatch path swallows it without changing the
    # raise condition mid-test.
    injected = OSError(57, "kmbox_net test: injected sendto failure")
    fake_sock.raise_on_send = injected

    # Lock must be released BEFORE the dispatch (sanity check).
    pre_acquired = driver._send_lock.acquire(blocking=False)
    assert pre_acquired, "Send_Lock was already held before dispatch"
    driver._send_lock.release()

    # Dispatch — the driver should swallow the OSError, log once, and
    # return None per Requirement 1.8. The Send_Lock MUST be released
    # on the exception path per Requirement 1.7.
    result = driver._dispatch_call("move", 10, 20)
    assert result is None, (
        "_dispatch_call should return None on the OSError path "
        "(Requirement 1.8)"
    )

    # No packet was added to the sent log because sendto raised.
    assert len(fake_sock.sent) == handshake_count, (
        "FakeUdpSocket should not record a packet when sendto raises "
        f"OSError; got {len(fake_sock.sent) - handshake_count} extra "
        "packets after the failing dispatch."
    )

    # **Property 1, clause 2 (exception path):** the lock is released
    # after the OSError. Acquire non-blocking from the test thread —
    # MUST succeed.
    post_acquired = driver._send_lock.acquire(blocking=False)
    assert post_acquired, (
        "Send_Lock was NOT released on the OSError exception path. "
        "Requirement 1.7 second clause violated — the ``with`` block "
        "must release the lock on every exception raised by sendto."
    )
    driver._send_lock.release()

    # **Requirement 1.8 (corroborating):** the next public-API send
    # call does not raise an exception attributable to the prior
    # OSError. Clear the fault and verify a successful dispatch.
    fake_sock.raise_on_send = None
    driver._dispatch_call("move", 30, 40)
    assert len(fake_sock.sent) == handshake_count + 1, (
        "Subsequent _dispatch_call after OSError should succeed and "
        "emit one UDP packet."
    )


# ---------------------------------------------------------------------------
# Property 1 — lock released on the normal-return path
# ---------------------------------------------------------------------------


def test_send_lock_released_on_normal_return(socket_factory, fake_device):
    """Send_Lock is released after each normal-return dispatch.

    Issues a sequence of ``_dispatch_call`` invocations from the main
    thread (no concurrency) and asserts the lock is acquireable
    non-blocking after each call. This isolates the normal-return
    path from the concurrent test above so a failure here points
    directly at a missing release in the success path.
    """
    driver = _build_connected_driver(socket_factory, fake_device)
    fake_sock = socket_factory.sockets[0]
    handshake_count = len(fake_sock.sent)

    for i in range(10):
        driver._dispatch_call("move", i, -i)

        # Lock must be free immediately after the call returns.
        acquired = driver._send_lock.acquire(blocking=False)
        assert acquired, (
            f"Send_Lock not released after normal-return dispatch #{i}. "
            "Requirement 1.7 second clause violated on the success path."
        )
        driver._send_lock.release()

    assert len(fake_sock.sent) == handshake_count + 10, (
        "Sequential dispatches should each emit one UDP packet."
    )
