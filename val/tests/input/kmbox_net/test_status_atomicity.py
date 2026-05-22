"""
Concurrency test — Task 5.6 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 18: ``connection_status`` read atomicity.

**Property 18: ``connection_status`` read atomicity**

    *For any* concurrent schedule in which a single writer thread
    drives ``KmBoxNetDriver.connection_status`` through the lifecycle
    cycle ``disconnected → connecting → connected →
    disconnected/failed`` while N reader threads concurrently sample
    ``driver.connection_status``, every observed value SHALL be a
    member of :class:`~input.kmbox_net_driver.ConnectionStatus` and no
    reader SHALL raise any exception.

**Validates: Requirements 10.1, 10.6**

Implementation notes
--------------------

This is a concurrency test, not a Hypothesis property test. The task
file (5.6) explicitly calls for a *fixed-N / fixed-iterations* design
because the property is over the *concurrent schedule* of attribute
reads/writes rather than over a parameterised input space — the same
shape used by ``test_dispatch_lock.py`` for Property 1.

Design
~~~~~~

* **One writer thread.** Cycles ``connection_status`` through the
  four-step lifecycle pattern ``DISCONNECTED → CONNECTING → CONNECTED
  → {DISCONNECTED, FAILED}`` (alternating between the two terminal
  states across cycles to exercise both spellings) for
  ``_WRITER_CYCLES`` iterations. Each write is a single attribute
  assignment of an immutable ``ConnectionStatus`` member; per the
  design "Threading model" section these assignments are atomic under
  CPython's GIL, satisfying Requirement 10.6.

* **N reader threads.** Each reader spins on
  ``driver.connection_status`` until the writer signals ``stop_event``,
  capturing every observed value into a per-thread list. After the
  threads join, the test asserts:

    1. Every observed value is an instance of :class:`ConnectionStatus`
       (or, equivalently, equal to one of the five documented status
       strings — the ``str``-enum subclassing means both checks
       coincide).
    2. No reader thread raised any exception (collected into
       ``reader_errors``).
    3. The full set of observed values across all readers contains at
       least :data:`ConnectionStatus.CONNECTING` and at least one of
       :data:`ConnectionStatus.DISCONNECTED` / :data:`ConnectionStatus.FAILED`,
       proving the readers actually witnessed the writer's transitions
       rather than only sampling a steady state.

* **Synchronization.** A ``threading.Barrier`` aligns the writer and
  every reader so the contention starts simultaneously, amplifying any
  read-during-write hazard. A ``threading.Event`` signals readers to
  stop after the writer has completed its cycles.

* **No locks on reads.** The whole point of Property 18 is that
  readers do **not** acquire any lock — they perform a single
  attribute read of an immutable ``str`` enum value. The test would
  not catch a regression that introduced a lock on the reader path
  (such a regression would still pass), but it would catch a
  regression that broke the atomicity guarantee, e.g. by replacing
  ``connection_status`` with a non-immutable wrapper or by mutating it
  field-by-field during a transition.

Driver setup
~~~~~~~~~~~~

The driver is built with the same inline ``socket.socket``
monkey-patching pattern used in ``test_dispatch_oserror_isolation.py``
and ``test_dispatch_encrypt_isolation.py``: the constructor runs a
real Init_Handshake against a :class:`FakeUdpSocket` /
:class:`FakeDevice` so the driver lands in
:data:`ConnectionStatus.CONNECTED`, then the writer thread takes
direct control of the attribute. Encryption is disabled
(``use_encryption=False``) because the handshake send path is
incidental to this property; only the post-construction attribute
mutations are under test.
"""

from __future__ import annotations

import socket as _stdlib_socket
import sys
import threading
import time
from pathlib import Path
from typing import List, Tuple

# Make the ``input`` package importable when pytest is launched from
# the repository root or any sub-directory. The driver ships as
# ``input/kmbox_net_driver.py`` at the project root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from input.kmbox_net_driver import (  # noqa: E402  — sys.path manipulation above
    ConnectionStatus,
    KmBoxNetDriver,
)
from tests.input.kmbox_net.conftest import (  # noqa: E402
    FakeDevice,
    FakeUdpSocket,
)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Number of concurrent reader threads. Picked large enough to expose a
# real read-during-write race on a multi-core ARM64 host but small
# enough that the test stays well under one second per pytest run.
_READER_COUNT: int = 4

# Number of full ``DISCONNECTED → CONNECTING → CONNECTED →
# {DISCONNECTED, FAILED}`` cycles the writer performs. Four writes
# per cycle × ``_WRITER_CYCLES`` cycles = 4 * _WRITER_CYCLES total
# transitions, providing ample windows for readers to land mid-write.
_WRITER_CYCLES: int = 50

# Writer's per-transition pause. A non-zero sleep is required to
# force the OS scheduler to actually hand the GIL to a reader between
# transitions: under Python 3.12+'s 5 ms default GIL switch interval,
# a writer that issues 4 × _WRITER_CYCLES = 200 attribute writes in
# tight succession runs to completion in a single scheduler slice and
# the readers only ever observe the post-loop value. A bare
# ``time.sleep(0)`` is *not* sufficient on Windows + many readers —
# the OS may bounce the GIL among readers without ever returning it
# to the writer, starving the writer. A small positive sleep
# (~50 µs) defers to the OS timer and reliably round-robins the
# scheduler.
_WRITER_TRANSITION_PAUSE_S: float = 5e-5

# Cap the per-reader observation list so a slow CI host that scales
# the spin loop into the millions of iterations does not exhaust
# memory. The cap is *much* larger than the writer's transition count
# so readers consistently observe every emitted value at least once.
_READER_OBSERVATIONS_CAP: int = 100_000

# Set of valid status values per Requirement 10.1.
_VALID_STATUSES = {
    ConnectionStatus.DISCONNECTED,
    ConnectionStatus.CONNECTING,
    ConnectionStatus.CONNECTED,
    ConnectionStatus.RECONNECTING,
    ConnectionStatus.FAILED,
}


# ---------------------------------------------------------------------------
# Driver build helper
# ---------------------------------------------------------------------------


def _build_connected_driver() -> Tuple[KmBoxNetDriver, FakeUdpSocket]:
    """Construct a ``KmBoxNetDriver`` in the ``CONNECTED`` state.

    Patches ``socket.socket`` for the duration of the constructor so
    the driver creates a :class:`FakeUdpSocket` instead of a real one,
    and attaches a successful :class:`FakeDevice` so the handshake
    ``recvfrom`` resolves to a zero-result-code reply. The patch is
    reverted before returning — the test body does not need socket
    interception any more once the driver is built.

    Returns:
        Tuple of (driver, fake_udp_socket). The driver lands in
        :data:`ConnectionStatus.CONNECTED` so subsequent writer-thread
        transitions exercise a realistic starting state.
    """
    sockets: List[FakeUdpSocket] = []
    device = FakeDevice(outcome=FakeDevice.HandshakeOutcome.SUCCESS)

    def _factory(family: int = _stdlib_socket.AF_INET,
                 type_: int = _stdlib_socket.SOCK_DGRAM,
                 proto: int = 0,
                 fileno: int | None = None,
                 **_kwargs) -> FakeUdpSocket:
        sock = FakeUdpSocket(family=family, type_=type_)
        sock.proto = proto
        sockets.append(sock)
        # Attach the device on the *first* socket only so handshake
        # replies are queued before the driver's ``recvfrom``.
        if len(sockets) == 1:
            device.attach(sock)
        return sock

    original = _stdlib_socket.socket
    _stdlib_socket.socket = _factory  # type: ignore[assignment]
    try:
        driver = KmBoxNetDriver(
            ip="192.168.2.188",
            port="41990",
            uuid="01FBC068",
            use_encryption=False,
        )
    finally:
        _stdlib_socket.socket = original  # type: ignore[assignment]

    if not sockets:
        raise RuntimeError(
            "test harness invariant violated: KmBoxNetDriver did not "
            "construct any UDP socket"
        )
    if driver.connection_status != ConnectionStatus.CONNECTED:
        raise RuntimeError(
            "test harness invariant violated: handshake did not land "
            f"the driver in CONNECTED; got {driver.connection_status!r}"
        )
    return driver, sockets[0]


# ---------------------------------------------------------------------------
# Property 18 — concurrent reads observe only valid ConnectionStatus members
# ---------------------------------------------------------------------------


def test_connection_status_read_atomicity() -> None:
    """Concurrent reads of ``connection_status`` are atomic and total.

    Spawns ``_READER_COUNT`` reader threads that spin on
    ``driver.connection_status`` while a single writer thread drives
    the attribute through ``_WRITER_CYCLES`` iterations of the
    lifecycle pattern ``DISCONNECTED → CONNECTING → CONNECTED →
    {DISCONNECTED, FAILED}``. After all threads join, the test
    asserts:

      * **Reader totality (Requirement 10.1).** Every observed value
        across every reader is a member of :class:`ConnectionStatus`,
        which by construction means it equals one of the five
        documented status strings ``{disconnected, connecting,
        connected, reconnecting, failed}``. A regression that
        replaced the attribute with a non-enum sentinel
        (``"transitioning"``, ``None``, a partially-built object)
        would surface here.

      * **Reader robustness (Requirement 10.6).** No reader thread
        raised an exception. ``connection_status`` reads must be
        safe to perform from any thread without coordination — the
        writer's mid-transition state must never leak through as a
        ``TypeError``, ``AttributeError``, or any other failure.

      * **Writer robustness.** The writer thread itself completed
        ``_WRITER_CYCLES`` cycles without raising. (Requirements 10.2,
        10.5 already cover the individual writes; this test merely
        confirms the writer runs to completion alongside the
        contending readers.)

      * **Transition coverage.** The collective set of values seen by
        all readers contains at least :data:`ConnectionStatus.CONNECTING`
        and at least one of :data:`ConnectionStatus.DISCONNECTED` /
        :data:`ConnectionStatus.FAILED`. Without this clause a
        regression that froze ``connection_status`` at ``CONNECTED``
        could pass the value-membership check vacuously.

    Validates: Requirements 10.1, 10.6.
    """
    driver, _fake_sock = _build_connected_driver()

    # ── Synchronization primitives ────────────────────────────────
    barrier = threading.Barrier(parties=1 + _READER_COUNT)
    stop_event = threading.Event()

    # ── Per-thread error capture ──────────────────────────────────
    reader_errors: List[BaseException] = []
    reader_errors_lock = threading.Lock()
    writer_error: List[BaseException] = []  # length 0 or 1

    # ── Reader observation lists ──────────────────────────────────
    # One list per reader so threads do not contend on a shared list
    # (which would itself involve a lock and bias the schedule).
    reader_observations: List[List[ConnectionStatus]] = [
        [] for _ in range(_READER_COUNT)
    ]

    # ── Writer cycle pattern ──────────────────────────────────────
    #
    # Each cycle issues four writes in order. The terminal state
    # alternates between DISCONNECTED and FAILED across cycles so
    # both spellings of "link is not alive" are exercised under
    # contention — matching the task description's
    # ``disconnected/failed`` notation.
    def _cycle_states(cycle_index: int) -> Tuple[
        ConnectionStatus, ConnectionStatus, ConnectionStatus, ConnectionStatus
    ]:
        terminal = (
            ConnectionStatus.FAILED
            if cycle_index % 2 == 0
            else ConnectionStatus.DISCONNECTED
        )
        return (
            ConnectionStatus.DISCONNECTED,
            ConnectionStatus.CONNECTING,
            ConnectionStatus.CONNECTED,
            terminal,
        )

    # ── Writer thread ─────────────────────────────────────────────
    def writer() -> None:
        try:
            barrier.wait()
            for cycle in range(_WRITER_CYCLES):
                for state in _cycle_states(cycle):
                    # Single-attribute assignment of an immutable
                    # ``str``-enum member: atomic under CPython's GIL
                    # per the design "Threading model" section.
                    driver.connection_status = state
                    # Yield to the OS scheduler so reader threads
                    # actually get scheduled between transitions —
                    # see comment on ``_WRITER_TRANSITION_PAUSE_S``
                    # for why a non-zero sleep (rather than
                    # ``sleep(0)``) is necessary to avoid writer
                    # starvation under the Windows scheduler.
                    time.sleep(_WRITER_TRANSITION_PAUSE_S)
        except BaseException as exc:  # noqa: BLE001 — surface to test
            writer_error.append(exc)
        finally:
            # Always release the readers — even if the writer raised,
            # we want the readers to wind down so the join below
            # completes and the test reports the writer's exception.
            stop_event.set()

    # ── Reader thread factory ─────────────────────────────────────
    def reader(slot: int) -> None:
        observations = reader_observations[slot]
        cap = _READER_OBSERVATIONS_CAP
        try:
            barrier.wait()
            # Spin until the writer signals stop. ``stop_event.is_set``
            # is itself a thread-safe read; sampling
            # ``connection_status`` between checks gives the reader
            # plenty of opportunities to observe a mid-transition
            # value if Requirement 10.6 were violated.
            while not stop_event.is_set():
                value = driver.connection_status
                if len(observations) < cap:
                    observations.append(value)
                # Yield the GIL so the writer thread is not
                # starved. Without this yield, four readers in tight
                # spin loops monopolise the GIL on Windows under
                # CPython 3.12+ (the "fair" GIL hands the lock back
                # to whichever thread released it most recently,
                # which in a busy-spin loop is whichever reader
                # most recently completed its iteration). The
                # writer wakes from its ``time.sleep`` and then
                # waits indefinitely for the GIL — observed
                # empirically as a writer-thread hang under the
                # Windows scheduler. A bare ``sleep(0)`` defers to
                # the scheduler without changing the wall-clock
                # cadence and round-robins the GIL fairly.
                time.sleep(0)
        except BaseException as exc:  # noqa: BLE001 — surface to test
            with reader_errors_lock:
                reader_errors.append(exc)

    # ── Spawn and run ─────────────────────────────────────────────
    writer_thread = threading.Thread(target=writer, daemon=True)
    reader_threads = [
        threading.Thread(target=reader, args=(i,), daemon=True)
        for i in range(_READER_COUNT)
    ]

    writer_thread.start()
    for t in reader_threads:
        t.start()

    # Bound the join so a regression that hangs (e.g. the writer
    # blocking on a never-released lock) fails the test in seconds
    # rather than wedging the suite indefinitely.
    writer_thread.join(timeout=10.0)
    assert not writer_thread.is_alive(), (
        "writer thread did not finish within 10 s — Requirement 10.6 "
        "regression suspect (writer blocked on a synchronization "
        "primitive on the connection_status write path)."
    )
    for t in reader_threads:
        t.join(timeout=10.0)
        assert not t.is_alive(), (
            "reader thread did not finish within 10 s after stop_event "
            "was set — Requirement 10.6 regression suspect."
        )

    # ── Post-condition 1: writer completed ───────────────────────
    assert not writer_error, (
        "writer thread raised an exception while driving "
        f"connection_status transitions: {writer_error[0]!r}"
    )

    # ── Post-condition 2: no reader raised ───────────────────────
    #
    # Requirement 10.6: any read by a thread other than the writer
    # observes either the pre-transition value or the
    # post-transition value, and never an intermediate or partially
    # constructed value. A regression that allowed the readers to
    # see a torn write would most often surface as an
    # ``AttributeError`` (descriptor lookup landing on a
    # half-installed object) or a ``TypeError`` (the comparison in
    # ``str.__eq__`` failing against a non-string sentinel). Either
    # would bubble out of ``driver.connection_status`` and land in
    # ``reader_errors``.
    assert not reader_errors, (
        f"{len(reader_errors)} reader thread(s) raised while reading "
        f"connection_status; first exception: {reader_errors[0]!r}"
    )

    # ── Post-condition 3: every observed value is a ConnectionStatus
    # member naming one of the five Requirement 10.1 vocabulary
    # entries ──────────────────────────────────────────────────────
    seen: set = set()
    total_observations = 0
    for slot, observations in enumerate(reader_observations):
        total_observations += len(observations)
        for value in observations:
            # Membership check #1: ``value`` is an instance of the
            # ``ConnectionStatus`` enum.
            assert isinstance(value, ConnectionStatus), (
                f"reader {slot} observed a non-ConnectionStatus value "
                f"{value!r} (type {type(value).__name__}); "
                "Requirement 10.1 requires every observed value to be "
                "one of the five documented status strings."
            )
            # Membership check #2: ``value`` is one of the five
            # documented members. The first check already implies
            # this for any well-formed enum; this redundant check
            # catches the regression where ConnectionStatus is
            # extended with a new member that has not been added to
            # ``_VALID_STATUSES`` (i.e. forces this test to be
            # updated alongside the requirements).
            assert value in _VALID_STATUSES, (
                f"reader {slot} observed ConnectionStatus member "
                f"{value!r} which is not in the Requirement 10.1 "
                f"vocabulary {_VALID_STATUSES!r}."
            )
            seen.add(value)

    # Sanity: readers actually got CPU time. With 8 readers spinning
    # against 1000 writes, the total observation count should be
    # comfortably in the thousands; if it is zero, the readers
    # never got a chance to run and the test would otherwise pass
    # vacuously.
    assert total_observations > 0, (
        "reader threads recorded zero observations — the test did "
        "not actually exercise the property. Suspect a regression "
        "in the threading harness rather than in the driver."
    )

    # ── Post-condition 4: transitions actually happened ──────────
    #
    # The writer issued ``CONNECTING`` exactly once per cycle; the
    # readers' busy-spin almost always catches it. Requiring this
    # member in the observation set guards against a regression
    # that froze ``connection_status`` at ``CONNECTED`` and made
    # post-conditions 2 and 3 vacuously true.
    assert ConnectionStatus.CONNECTING in seen, (
        "readers never observed ConnectionStatus.CONNECTING despite "
        f"{_WRITER_CYCLES} writer cycles — readers did not actually "
        "race against the writer's transitions."
    )
    # At least one terminal state must also have been observed; the
    # writer alternates between DISCONNECTED and FAILED across
    # cycles, so observing either suffices.
    assert (
        ConnectionStatus.DISCONNECTED in seen
        or ConnectionStatus.FAILED in seen
    ), (
        "readers never observed a terminal status "
        f"({ConnectionStatus.DISCONNECTED!r} or "
        f"{ConnectionStatus.FAILED!r}) despite {_WRITER_CYCLES} "
        "writer cycles — readers did not actually race against the "
        "writer's transitions."
    )
