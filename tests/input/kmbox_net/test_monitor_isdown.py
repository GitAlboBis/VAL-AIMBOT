"""
Property test — Task 7.5 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 12: ``isdown_*`` reflects latest snapshot.

**Property 12: ``isdown_*`` reflects latest snapshot**

    *For each* ``B ∈ {left, middle, right}`` with masks
    ``{0x01, 0x04, 0x02}`` respectively, and *for any* sequence of
    Monitor_Channel snapshots delivered to the driver's
    ``_MonitorListener`` via :class:`FakeMonitorSocket`, the driver
    SHALL satisfy:

      * When the Monitor_Channel state is enabled and at least one
        snapshot has been received since the most recent enable
        transition, ``isdown_B()`` returns ``1`` iff
        ``(latest.buttons & MASK_B) != 0``; otherwise ``0``.
      * When the Monitor_Channel state is disabled OR no snapshot has
        been received since the most recent enable transition,
        ``isdown_B()`` returns ``0``.
      * In either case ``FakeUdpSocket.sendto`` (the *send-path*
        socket) is invoked zero times by the ``isdown_*`` reads
        themselves — they are pure local memory reads.

**Validates: Requirements 6.4, 6.5, 6.6, 6.7**

Requirement 6.4 binds ``isdown_left()`` to the bit0 of the latest
snapshot's ``buttons`` byte. Requirement 6.5 binds ``isdown_middle()``
to bit2. Requirement 6.7 binds ``isdown_right()`` to bit1. Requirement
6.6 covers the disabled / no-snapshot-yet case for all three readers.
The masks are pinned by the wire layout of ``soft_mouse_t.button``
(``c++_demo/NetConfig/kmboxNet.h``) and the matching bit assignments in
``_MonitorListener.run``:

    self._driver._mon_left   = 1 if buttons & 0x01 else 0
    self._driver._mon_right  = 1 if buttons & 0x02 else 0
    self._driver._mon_middle = 1 if buttons & 0x04 else 0

so the per-button masks the property quotes —
``{left: 0x01, middle: 0x04, right: 0x02}`` — match the listener's
observable behaviour exactly.

Implementation notes
--------------------

The driver creates two distinct UDP sockets across its lifetime:

  1. **Send-path socket** — opened in ``__init__`` and wrapped by
     ``UdpSocket``. Carries every command emitted via
     ``_dispatch_call`` (Init_Handshake, ``cmd_monitor``, …). The
     ``isdown_*`` readers MUST NOT touch this socket per Requirement
     6.4 / 6.5 / 6.7.
  2. **Listener socket** — opened in ``_MonitorListener.__init__``
     (only when ``monitor(port != 0)`` is invoked) and bound to
     ``('0.0.0.0', port)``. Receives 20-byte snapshot datagrams from
     the device.

The test monkey-patches ``socket.socket`` so the *first* constructed
socket is a :class:`FakeUdpSocket` (the send-path) and every
*subsequent* socket is a :class:`FakeMonitorSocket` (the listener).
The :class:`FakeDevice` is attached to the first socket so the
Init_Handshake completes deterministically.

Snapshots are injected via :meth:`FakeMonitorSocket.push_snapshot`,
which frames a ``standard_mouse_report_t`` (8 B) +
``standard_keyboard_report_t`` (12 B) datagram from the supplied
``buttons`` byte and enqueues it on the listener socket's recv queue.
The listener's daemon ``run`` loop consumes the datagram, parses the
``buttons`` byte, and writes ``_mon_left`` / ``_mon_right`` /
``_mon_middle`` followed by ``_mon_seen = 1`` (the listener writes
``_mon_seen`` *last* per the design's threading-model section so a
concurrent ``isdown_*`` reader observing ``_mon_seen == 1`` is
guaranteed to see the matching button bits already updated).

After pushing a snapshot the test polls ``driver._mon_seen`` (and
the per-button scalars) up to a short timeout to wait for the listener
thread to consume the datagram. The polling is necessary because the
listener runs on a background thread; a fixed ``time.sleep`` would be
flaky on a busy CI host. The polling loop also breaks out as soon as
the expected ``_mon_left`` / ``_mon_middle`` / ``_mon_right`` values
land, so each Hypothesis example completes in a few milliseconds in
the common case.

Why a property test (rather than a single-example unit test)
-------------------------------------------------------------

The property covers the full 256-value space of the ``buttons`` byte
across arbitrary-length snapshot sequences with interleaved enable /
disable transitions. A single example would not exercise:

  * the bit-isolation property (a regression that swapped masks
    between left/middle/right would only be caught by sampling
    multiple distinct ``buttons`` values);
  * the *latest-snapshot wins* rule (Requirements 6.4 / 6.5 / 6.7
    pin the readers to the *most recent* snapshot, not to the
    cumulative OR — a sequence of pushes ending with ``buttons=0``
    must produce ``isdown_*() == 0`` even if a prior snapshot in
    the same enable transition had bits set);
  * the disable-resets-snapshot-state rule (Requirement 6.6 — after
    ``monitor(0)`` the readers must return ``0`` even though the
    listener may have observed many snapshots while enabled).

Hypothesis explores all three dimensions in a single test body.
"""

from __future__ import annotations

import socket as _stdlib_socket
import sys
import time as _stdlib_time
from pathlib import Path

# Make the ``input`` package importable when pytest is launched from
# the repository root or any sub-directory. The driver ships as
# ``input/kmbox_net_driver.py`` at the project root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from input.kmbox_net_driver import (  # noqa: E402
    ConnectionStatus,
    KmBoxNetDriver,
)
from tests.input.kmbox_net.conftest import (  # noqa: E402
    FakeDevice,
    FakeMonitorSocket,
    FakeUdpSocket,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Per-button masks pinned by ``_MonitorListener.run`` and
# ``soft_mouse_t.button`` (``c++_demo/NetConfig/kmboxNet.h``).
# Property 12 explicitly names these three masks; the test uses them
# verbatim so a regression in either the wire mask or the reader
# wiring would surface as a property failure rather than a silent
# off-by-one.
MASK_LEFT = 0x01
MASK_RIGHT = 0x02
MASK_MIDDLE = 0x04

# Monitor_Channel listener bind port for the test. Any value in the
# valid range ``[1024, 49151]`` per Requirement 6.1 works; ``16800``
# is arbitrary but stable so the FakeMonitorSocket's ``bound_address``
# is predictable for diagnostic output. The fake never actually opens
# an OS-level UDP socket, so port collisions across parallel test
# runs are impossible.
TEST_MONITOR_PORT = 16800

# Maximum wall-clock seconds to wait for the listener thread to
# consume a pushed snapshot. The listener runs with a 0.25 s recv
# timeout and processes a queued datagram on the next ``recvfrom``,
# so 2 s is comfortably above the worst-case scheduler latency on a
# loaded CI host while still keeping a stuck listener from pinning
# the test indefinitely.
SNAPSHOT_WAIT_TIMEOUT_S = 2.0

# Polling interval inside the wait loop. Short enough that the loop
# breaks out within a few iterations of the listener consuming the
# snapshot.
SNAPSHOT_POLL_INTERVAL_S = 0.005


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Full byte space for ``standard_mouse_report_t.buttons``. The
# upstream layout uses an unsigned 8-bit field (bit0=L, bit1=R,
# bit2=M, bit3=Side1, bit4=Side2, bits 5..7 reserved). Property 12
# only asserts on bits 0..2, but exercising the full byte ensures
# unrelated bits do not bleed into the readers.
_st_buttons = st.integers(min_value=0, max_value=255)

# Sequence of snapshot ``buttons`` values to push during a single
# enable transition. ``min_size=1`` so the test always exercises the
# "at least one snapshot received" branch; ``max_size=4`` keeps each
# Hypothesis example fast (each snapshot incurs one cross-thread
# wait of up to 2 s in the worst case, though typically completes in
# a few milliseconds).
_st_snapshot_sequence = st.lists(
    _st_buttons, min_size=1, max_size=4
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_driver_with_monitor_factory() -> tuple[
    KmBoxNetDriver, FakeUdpSocket, list[FakeMonitorSocket]
]:
    """Construct a connected ``KmBoxNetDriver`` whose listener socket is fake.

    Patches ``socket.socket`` so that:

      * the *first* ``socket.socket(...)`` call (the send-path socket
        opened in ``UdpSocket.__init__``) returns a
        :class:`FakeUdpSocket`. The :class:`FakeDevice` is attached
        to that socket so the Init_Handshake reply is pre-queued.
      * every *subsequent* ``socket.socket(...)`` call returns a
        :class:`FakeMonitorSocket`. The :class:`FakeMonitorSocket`
        inherits :class:`FakeUdpSocket` semantics (bind / settimeout
        / recvfrom / close) and adds a :meth:`push_snapshot` helper
        that frames a 20-byte Monitor_Channel datagram from a
        ``buttons`` byte and enqueues it on the recv side.

    The patch covers the full lifetime of the test (both the
    ``__init__`` handshake and any later ``monitor(port)`` calls)
    because the driver re-uses the same module-level
    ``socket.socket`` symbol every time it needs a fresh socket. The
    test body is responsible for calling :func:`_restore_socket` (or
    using a try/finally guard) to revert the patch before the
    function returns to pytest.

    Returns:
        Tuple of ``(driver, fake_udp_socket, monitor_sockets_list)``.

        * ``fake_udp_socket`` — the send-path :class:`FakeUdpSocket`.
          Inspect ``.sent`` to verify which commands reached the wire.
        * ``monitor_sockets_list`` — a *reference* to the list the
          factory appends to on every monitor-socket creation. The
          list grows as ``monitor(port)`` is invoked. After a
          successful ``monitor(port)`` call the most recent listener's
          fake socket is at ``monitor_sockets_list[-1]``; calling
          ``push_snapshot`` on it injects a snapshot for the listener
          thread to consume.
    """
    udp_sockets: list[FakeUdpSocket] = []
    monitor_sockets: list[FakeMonitorSocket] = []
    device = FakeDevice(outcome=FakeDevice.HandshakeOutcome.SUCCESS)

    def _factory(family: int = _stdlib_socket.AF_INET,
                 type_: int = _stdlib_socket.SOCK_DGRAM,
                 proto: int = 0,
                 fileno: int | None = None,
                 **_kwargs) -> FakeUdpSocket:
        # First socket is the send-path UDP socket; every subsequent
        # socket is a Monitor_Channel listener. ``_MonitorListener``
        # constructs its socket eagerly inside ``__init__`` (so a
        # bind failure surfaces to the ``monitor()`` caller rather
        # than the daemon thread), so the very first call after the
        # driver's ``__init__`` returns will land on this branch.
        if not udp_sockets:
            sock: FakeUdpSocket = FakeUdpSocket(family=family, type_=type_)
            sock.proto = proto
            udp_sockets.append(sock)
            device.attach(sock)
            return sock
        sock = FakeMonitorSocket(family=family, type_=type_)
        sock.proto = proto
        monitor_sockets.append(sock)
        return sock

    original = _stdlib_socket.socket
    _stdlib_socket.socket = _factory  # type: ignore[assignment]
    try:
        driver = KmBoxNetDriver(
            ip="192.168.2.188",
            port="41990",
            uuid="01FBC068",
            # Plaintext so any inadvertent ``isdown_*`` regression
            # that emitted a packet would surface as a recognisable
            # 72-byte mouse-class layout rather than a 128-byte
            # encrypted blob in the failure diagnostic.
            use_encryption=False,
        )
    except Exception:
        _stdlib_socket.socket = original  # type: ignore[assignment]
        raise

    # NB: the patch is *intentionally* left in place — the test body
    # invokes ``monitor(port)`` after construction and that call
    # creates the listener socket via the patched ``socket.socket``.
    # The caller restores the patch via the cleanup helper below.
    if not udp_sockets:
        _stdlib_socket.socket = original  # type: ignore[assignment]
        raise RuntimeError(
            "test harness invariant violated: KmBoxNetDriver did not "
            "construct any UDP socket"
        )

    # Stash the original on the driver so the test can restore it
    # without having to thread the value through every helper.
    driver._test_original_socket = original  # type: ignore[attr-defined]
    return driver, udp_sockets[0], monitor_sockets


def _restore_socket(driver: KmBoxNetDriver) -> None:
    """Revert the ``socket.socket`` monkey-patch installed by the helper."""
    original = getattr(driver, "_test_original_socket", None)
    if original is not None:
        _stdlib_socket.socket = original  # type: ignore[assignment]


def _wait_for_snapshot(
    driver: KmBoxNetDriver,
    expected_buttons: int,
    *,
    timeout_s: float = SNAPSHOT_WAIT_TIMEOUT_S,
) -> bool:
    """Block until the listener has consumed a snapshot with ``expected_buttons``.

    The listener thread writes the per-button scalars before
    ``_mon_seen``, so once we observe ``_mon_seen == 1`` *and* the
    per-button scalars match the expected button bits, the snapshot
    has fully landed and ``isdown_*`` is safe to query.

    Returns ``True`` on success, ``False`` if the timeout expired.
    """
    expected_left = 1 if (expected_buttons & MASK_LEFT) else 0
    expected_right = 1 if (expected_buttons & MASK_RIGHT) else 0
    expected_middle = 1 if (expected_buttons & MASK_MIDDLE) else 0
    deadline = _stdlib_time.monotonic() + timeout_s
    while _stdlib_time.monotonic() < deadline:
        # Read the four scalars in the same order as ``isdown_*`` —
        # ``_mon_seen`` is the gate, so wait for it to flip first.
        if (
            driver._mon_seen == 1
            and driver._mon_left == expected_left
            and driver._mon_right == expected_right
            and driver._mon_middle == expected_middle
        ):
            return True
        _stdlib_time.sleep(SNAPSHOT_POLL_INTERVAL_S)
    return False


# ---------------------------------------------------------------------------
# Property 12
# ---------------------------------------------------------------------------


@settings(max_examples=20, deadline=None)
@given(snapshot_sequence=_st_snapshot_sequence)
def test_isdown_reflects_latest_snapshot(
    snapshot_sequence: list[int],
) -> None:
    """``isdown_left/middle/right`` mirror the latest snapshot's button bits.

    Per Property 12 (design.md) and Requirements 6.4, 6.5, 6.6, 6.7:

      * **State 1: pre-monitor.** Before any ``monitor(port)`` call
        the Monitor_Channel state is disabled and no snapshot has
        been observed. All three readers return ``0`` and emit zero
        send-path packets.

      * **State 2: enabled with snapshots.** After ``monitor(port)``
        the listener consumes the pushed snapshot and updates the
        ``_mon_*`` scalars. For each ``B ∈ {left, middle, right}``
        with mask ``MASK_B``: ``isdown_B()`` returns ``1`` iff
        ``(buttons & MASK_B) != 0``. The send-path socket records no
        new packets across the reader calls (the only packet on the
        wire is the ``cmd_monitor`` enable packet emitted by
        ``monitor(port)`` itself, which is *not* an ``isdown_*``
        invocation).

      * **State 3: disabled.** After ``monitor(0)`` the
        Monitor_Channel state flips back to disabled. All three
        readers return ``0`` regardless of the most recent
        snapshot's button bits, and the listener thread has been
        stopped + joined. The send-path socket records the
        ``cmd_monitor`` disable packet (one extra packet); the
        ``isdown_*`` reads themselves still emit zero.

    Validates: Requirements 6.4, 6.5, 6.6, 6.7.
    """
    driver, fake_sock, monitor_sockets = _build_driver_with_monitor_factory()
    try:
        # ── Pre-condition ──────────────────────────────────────────
        # Handshake succeeded; driver is in CONNECTED with one
        # connect packet on the wire.
        assert driver.connection_status == ConnectionStatus.CONNECTED, (
            "test pre-condition: handshake must succeed; got %r"
            % (driver.connection_status,)
        )
        assert driver.initialized is True
        handshake_packet_count = len(fake_sock.sent)
        assert handshake_packet_count == 1, (
            "test pre-condition: exactly one handshake packet "
            "expected before monitor(); got %d"
            % handshake_packet_count
        )

        # ── State 1: pre-monitor ──────────────────────────────────
        # Before any ``monitor()`` call ``_monitor_enabled`` is
        # ``False`` and ``_mon_seen`` is ``0``. Per Requirement 6.6
        # all three readers return ``0`` and MUST NOT touch the
        # send-path socket.
        sent_before = len(fake_sock.sent)
        assert driver.isdown_left() == 0, (
            "Requirement 6.6: isdown_left() must return 0 before "
            "monitor() is called; got %r" % (driver.isdown_left(),)
        )
        assert driver.isdown_middle() == 0, (
            "Requirement 6.6: isdown_middle() must return 0 before "
            "monitor() is called; got %r" % (driver.isdown_middle(),)
        )
        assert driver.isdown_right() == 0, (
            "Requirement 6.6: isdown_right() must return 0 before "
            "monitor() is called; got %r" % (driver.isdown_right(),)
        )
        assert len(fake_sock.sent) == sent_before, (
            "Requirement 6.4 / 6.5 / 6.7: isdown_* readers must not "
            "invoke sendto on the send-path socket. Pre-monitor "
            "wire-packet count grew from %d to %d."
            % (sent_before, len(fake_sock.sent))
        )

        # ── Enable Monitor_Channel ────────────────────────────────
        driver.monitor(TEST_MONITOR_PORT)
        # ``monitor(port != 0)`` emits exactly one ``cmd_monitor``
        # packet (covered by Property 11) and spawns the daemon
        # listener. Confirm the listener's fake socket is bound to
        # the expected port so the snapshot push targets the right
        # listener instance.
        assert len(monitor_sockets) >= 1, (
            "test invariant: monitor(%d) must spawn a listener "
            "socket via the patched socket.socket factory; got "
            "%d monitor sockets" % (TEST_MONITOR_PORT, len(monitor_sockets))
        )
        listener_sock = monitor_sockets[-1]
        assert listener_sock.bound_address == ("0.0.0.0", TEST_MONITOR_PORT), (
            "Requirement 6.1: listener must bind to "
            "('0.0.0.0', %d); got %r"
            % (TEST_MONITOR_PORT, listener_sock.bound_address)
        )

        # ── State 2: enabled, no snapshot yet ─────────────────────
        # The listener has started but no datagram has been
        # received yet; ``_mon_seen`` is ``0``. Per Requirement 6.6
        # all three readers must still return ``0``.
        sent_before = len(fake_sock.sent)
        assert driver.isdown_left() == 0, (
            "Requirement 6.6: isdown_left() must return 0 when "
            "no snapshot has been received since the most recent "
            "enable transition; got %r" % (driver.isdown_left(),)
        )
        assert driver.isdown_middle() == 0, (
            "Requirement 6.6: isdown_middle() must return 0 when "
            "no snapshot has been received since the most recent "
            "enable transition; got %r" % (driver.isdown_middle(),)
        )
        assert driver.isdown_right() == 0, (
            "Requirement 6.6: isdown_right() must return 0 when "
            "no snapshot has been received since the most recent "
            "enable transition; got %r" % (driver.isdown_right(),)
        )
        assert len(fake_sock.sent) == sent_before, (
            "Requirement 6.4 / 6.5 / 6.7: isdown_* readers must "
            "not invoke sendto. Wire-packet count grew from %d "
            "to %d." % (sent_before, len(fake_sock.sent))
        )

        # ── State 2: enabled, push snapshots ──────────────────────
        # Push each generated ``buttons`` value, wait for the
        # listener thread to consume it, then assert the readers
        # mirror the latest snapshot exactly. Across the sequence
        # the *latest* snapshot wins (Requirements 6.4 / 6.5 / 6.7
        # — the readers track the most recent observation, not a
        # cumulative OR).
        for index, buttons in enumerate(snapshot_sequence):
            listener_sock.push_snapshot(buttons=buttons)
            assert _wait_for_snapshot(driver, buttons), (
                "snapshot %d (buttons=0x%02X): listener did not "
                "consume the pushed datagram within %.1fs. "
                "_mon_seen=%r, _mon_left=%r, _mon_right=%r, "
                "_mon_middle=%r"
                % (
                    index,
                    buttons,
                    SNAPSHOT_WAIT_TIMEOUT_S,
                    driver._mon_seen,
                    driver._mon_left,
                    driver._mon_right,
                    driver._mon_middle,
                )
            )
            # Snapshot the wire-packet count *before* the
            # ``isdown_*`` reads so the "zero new packets" assertion
            # compares to the immediate-prior count, not the
            # post-handshake baseline. Across the snapshot loop the
            # send-path socket must remain at ``handshake_packet_count
            # + 1`` (the handshake plus the ``cmd_monitor`` enable
            # packet) — no ``isdown_*`` read may add to that.
            sent_before = len(fake_sock.sent)
            expected_left = 1 if (buttons & MASK_LEFT) else 0
            expected_right = 1 if (buttons & MASK_RIGHT) else 0
            expected_middle = 1 if (buttons & MASK_MIDDLE) else 0

            actual_left = driver.isdown_left()
            actual_middle = driver.isdown_middle()
            actual_right = driver.isdown_right()

            assert actual_left == expected_left, (
                "Requirement 6.4: isdown_left() must return %d "
                "when latest snapshot has buttons=0x%02X "
                "(MASK_LEFT=0x%02X); got %r."
                % (expected_left, buttons, MASK_LEFT, actual_left)
            )
            assert actual_middle == expected_middle, (
                "Requirement 6.5: isdown_middle() must return %d "
                "when latest snapshot has buttons=0x%02X "
                "(MASK_MIDDLE=0x%02X); got %r."
                % (expected_middle, buttons, MASK_MIDDLE, actual_middle)
            )
            assert actual_right == expected_right, (
                "Requirement 6.7: isdown_right() must return %d "
                "when latest snapshot has buttons=0x%02X "
                "(MASK_RIGHT=0x%02X); got %r."
                % (expected_right, buttons, MASK_RIGHT, actual_right)
            )
            assert len(fake_sock.sent) == sent_before, (
                "Requirement 6.4 / 6.5 / 6.7: isdown_* readers "
                "must not invoke sendto. Snapshot %d "
                "(buttons=0x%02X) caused wire-packet count to "
                "grow from %d to %d."
                % (
                    index,
                    buttons,
                    sent_before,
                    len(fake_sock.sent),
                )
            )

        # ── State 3: disable ──────────────────────────────────────
        # ``monitor(0)`` emits one ``cmd_monitor`` disable packet
        # (head.rand=0), stops the listener thread, and resets the
        # ``_mon_*`` scalars including ``_mon_seen``. Per
        # Requirement 6.6 the readers return ``0`` even though the
        # listener observed snapshots while enabled.
        sent_before_disable = len(fake_sock.sent)
        driver.monitor(0)
        assert len(fake_sock.sent) == sent_before_disable + 1, (
            "test invariant: monitor(0) must emit exactly one "
            "cmd_monitor disable packet; wire-packet count grew "
            "from %d to %d."
            % (sent_before_disable, len(fake_sock.sent))
        )

        # Snapshot the wire-packet count *after* the disable packet
        # so the post-disable ``isdown_*`` reads compare to the
        # post-disable baseline.
        sent_after_disable = len(fake_sock.sent)
        assert driver.isdown_left() == 0, (
            "Requirement 6.6: isdown_left() must return 0 after "
            "monitor(0) regardless of the most recent snapshot; "
            "got %r." % (driver.isdown_left(),)
        )
        assert driver.isdown_middle() == 0, (
            "Requirement 6.6: isdown_middle() must return 0 after "
            "monitor(0) regardless of the most recent snapshot; "
            "got %r." % (driver.isdown_middle(),)
        )
        assert driver.isdown_right() == 0, (
            "Requirement 6.6: isdown_right() must return 0 after "
            "monitor(0) regardless of the most recent snapshot; "
            "got %r." % (driver.isdown_right(),)
        )
        assert len(fake_sock.sent) == sent_after_disable, (
            "Requirement 6.4 / 6.5 / 6.7: isdown_* readers must "
            "not invoke sendto on the post-disable path. "
            "Wire-packet count grew from %d to %d."
            % (sent_after_disable, len(fake_sock.sent))
        )
    finally:
        # Always release the driver and revert the socket patch so
        # subsequent Hypothesis examples (and pytest sessions) start
        # from a clean state. ``release()`` joins the listener
        # thread (if any) with a 1-second timeout, closes the
        # send-path socket, and flips ``_released`` so any stray
        # ``isdown_*`` race after teardown is itself silenced.
        try:
            driver.release()
        finally:
            _restore_socket(driver)
