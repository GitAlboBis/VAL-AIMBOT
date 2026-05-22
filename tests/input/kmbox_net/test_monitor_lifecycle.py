"""
Property test — Task 7.4 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 11: ``monitor`` channel lifecycle.

**Property 11: ``monitor`` channel lifecycle**

    *For any* ``port ∈ [1024, 49151]``, calling ``monitor(port)`` emits
    exactly one UDP packet with ``head.cmd == CMD_MONITOR`` and
    ``head.rand == port | (0xaa55 << 16)``, and after the call returns
    the driver owns a UDP listener bound to ``('0.0.0.0', port)`` and
    the Monitor_Channel state is enabled. Calling ``monitor(0)`` after
    that emits exactly one UDP packet with ``head.cmd == CMD_MONITOR``
    and ``head.rand == 0``, closes the previously-bound listener, and
    sets the Monitor_Channel state to disabled.

**Validates: Requirements 6.1, 6.2**

Implementation notes
--------------------

The test follows the same inline ``socket.socket`` monkey-patching
pattern used in :mod:`tests.input.kmbox_net.test_dispatch_encrypt_isolation`
rather than the shared :func:`socket_factory` fixture: Hypothesis runs
the test body many times per pytest invocation, and a function-scoped
fixture would retain state across examples (``FakeDevice`` only
publishes its handshake reply once). Constructing the fakes inside the
test body — and patching ``socket.socket`` for the duration of *both*
the constructor and the ``monitor`` calls — keeps every example
deterministic.

Both :class:`KmBoxNetDriver`'s send-side ``UdpSocket`` and the
:class:`_MonitorListener` thread construct ``socket.socket(AF_INET,
SOCK_DGRAM)`` directly, so the same monkey-patch transparently
intercepts both: ``sockets[0]`` is the driver's send socket (used for
the handshake + the two ``cmd_monitor`` emissions), and ``sockets[1]``
is the listener socket bound to ``('0.0.0.0', port)``.

The driver is instantiated with ``use_encryption=False`` so the wire
bytes for the ``cmd_monitor`` packet are byte-for-byte the plaintext
``cmd_head_t`` layout — the ``head.cmd`` / ``head.rand`` fields can be
decoded via a single ``struct.unpack('<IIII', …)`` without going
through :class:`PacketEncryptor`. The encryption flag is orthogonal to
the lifecycle property under test (Property 14 / 15 cover the
encryption dispatch); decoupling them here keeps this test focused on
the ``monitor`` state machine.
"""

from __future__ import annotations

import socket as _stdlib_socket
import struct
import sys
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
    CMD_HEAD_FORMAT,
    CMD_HEAD_SIZE,
    CMD_MONITOR,
    ConnectionStatus,
    KmBoxNetDriver,
)
from tests.input.kmbox_net.conftest import (  # noqa: E402
    FakeDevice,
    FakeUdpSocket,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


# ``valid_port = st.integers(1024, 49151)`` per design.md generators
# (Requirement 6.1: monitor port range).
_st_valid_port = st.integers(min_value=1024, max_value=49151)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_connected_driver_with_sockets() -> tuple[KmBoxNetDriver, list[FakeUdpSocket]]:
    """Construct a connected ``KmBoxNetDriver`` and return the captured fake sockets.

    Patches ``socket.socket`` for the duration of the constructor (and
    leaves the patch in place — see the caller below — so subsequent
    socket constructions inside ``monitor(port)`` are also captured)
    and attaches a successful :class:`FakeDevice` to the first socket
    so the handshake ``recvfrom`` resolves to a zero-result-code reply.

    The driver is built with ``use_encryption=False`` so the
    ``cmd_monitor`` packets reach the wire as plaintext
    ``cmd_head_t`` blocks; the test can then decode them directly via
    :func:`struct.unpack`.

    Returns:
        Tuple of ``(driver, sockets)``. ``sockets[0]`` is the driver's
        send-side UDP socket; later entries are appended as the driver
        spawns additional sockets (e.g. the Monitor_Channel listener).
    """
    sockets: list[FakeUdpSocket] = []
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
        # replies are queued before the driver's ``recvfrom``. Later
        # sockets (the monitor listener) are pure receivers — the
        # device never replies on them in this test, so the listener
        # thread will exit on ``stop()`` via the
        # ``socket.timeout``/``OSError`` path described in
        # ``_MonitorListener.run``.
        if len(sockets) == 1:
            device.attach(sock)
        return sock

    # NOTE: the patch is intentionally NOT reverted before returning.
    # The caller is responsible for restoring ``socket.socket`` after
    # exercising the driver's ``monitor()`` calls so that subsequent
    # ``_MonitorListener`` constructions also operate on
    # :class:`FakeUdpSocket`.
    _original = _stdlib_socket.socket
    _stdlib_socket.socket = _factory  # type: ignore[assignment]

    try:
        driver = KmBoxNetDriver(
            ip="192.168.2.188",
            port="41990",
            uuid="01FBC068",
            use_encryption=False,
        )
    except BaseException:
        # If construction fails, restore the patch before re-raising
        # so the test runner's environment is not left in a corrupted
        # state.
        _stdlib_socket.socket = _original  # type: ignore[assignment]
        raise

    # Stash the original on the driver so the caller can restore it
    # after the test body is done.
    driver._test_original_socket_factory = _original  # type: ignore[attr-defined]
    return driver, sockets


def _restore_socket(driver: KmBoxNetDriver) -> None:
    """Restore the real ``socket.socket`` after the test has run."""
    original = getattr(driver, "_test_original_socket_factory", None)
    if original is not None:
        _stdlib_socket.socket = original  # type: ignore[assignment]


def _decode_head(packet: bytes) -> tuple[int, int, int, int]:
    """Unpack a 16-byte ``cmd_head_t`` and return ``(mac, rand, indexpts, cmd)``.

    The plaintext ``cmd_monitor`` packet is exactly 16 bytes (header
    only — no payload). Decoding via :data:`CMD_HEAD_FORMAT` keeps the
    test in lock-step with the driver's own header layout constant so
    a future change to the wire format would surface here as well.
    """
    assert len(packet) == CMD_HEAD_SIZE, (
        "test invariant: cmd_monitor plaintext packet must be exactly "
        "%d bytes (got %d)" % (CMD_HEAD_SIZE, len(packet))
    )
    return struct.unpack(CMD_HEAD_FORMAT, packet)


# ---------------------------------------------------------------------------
# Property 11
# ---------------------------------------------------------------------------


@settings(max_examples=30, deadline=None)
@given(port=_st_valid_port)
def test_monitor_channel_lifecycle(port: int) -> None:
    """``monitor(port)`` then ``monitor(0)`` follow the lifecycle contract.

    Validates: Requirements 6.1, 6.2.

    The test exercises the full lifecycle on a single connected
    driver instance per Hypothesis example:

      1. Build a connected driver under a monkey-patched
         ``socket.socket``. The handshake emits one packet on
         ``sockets[0]``.
      2. Call ``driver.monitor(port)`` and assert:
           * exactly one *new* packet on ``sockets[0]`` (so two total
             after the handshake), with ``head.cmd == CMD_MONITOR``
             and ``head.rand == port | (0xaa55 << 16)``;
           * ``sockets[1]`` exists (the ``_MonitorListener`` socket),
             is bound to ``('0.0.0.0', port)``, and is not yet closed;
           * ``driver._monitor_enabled is True``;
           * ``driver._monitor_listener is not None``.
      3. Call ``driver.monitor(0)`` and assert:
           * exactly one *new* packet on ``sockets[0]``, with
             ``head.cmd == CMD_MONITOR`` and ``head.rand == 0``;
           * the previously-spawned listener socket
             (``sockets[1]``) is now closed;
           * ``driver._monitor_enabled is False``;
           * ``driver._monitor_listener is None``.
    """
    driver, sockets = _build_connected_driver_with_sockets()
    try:
        # Sanity pre-conditions — the handshake is the only packet on
        # the wire so far, and the listener has not been spawned yet.
        assert driver.connection_status == ConnectionStatus.CONNECTED, (
            "test pre-condition: handshake must succeed; got %r"
            % (driver.connection_status,)
        )
        assert driver.use_encryption is False, (
            "test pre-condition: use_encryption=False so cmd_monitor "
            "packets reach the wire as plaintext cmd_head_t blocks"
        )
        assert len(sockets) == 1, (
            "test pre-condition: exactly one socket should have been "
            "constructed before monitor(); got %d" % len(sockets)
        )
        send_socket = sockets[0]
        assert len(send_socket.sent) == 1, (
            "test pre-condition: exactly one handshake packet should "
            "have been emitted; got %d" % len(send_socket.sent)
        )

        # ---- 1. monitor(port) — enable path -----------------------

        sent_before = len(send_socket.sent)
        sockets_before = len(sockets)

        driver.monitor(port)

        # Exactly one new packet on the wire.
        assert len(send_socket.sent) == sent_before + 1, (
            "monitor(%d): expected exactly one new UDP packet on the "
            "send socket; got %d → %d"
            % (port, sent_before, len(send_socket.sent))
        )
        enable_packet, enable_addr = send_socket.sent[-1]
        # The packet was routed to the device's (ip, port).
        assert enable_addr == ("192.168.2.188", 41990), (
            "monitor(%d): cmd_monitor packet must be routed to the "
            "configured device address; got %r" % (port, enable_addr)
        )
        _mac, head_rand, _indexpts, head_cmd = _decode_head(enable_packet)
        # head.cmd == CMD_MONITOR — Requirement 6.1.
        assert head_cmd == CMD_MONITOR, (
            "monitor(%d): expected head.cmd == CMD_MONITOR (0x%08x); "
            "got 0x%08x" % (port, CMD_MONITOR, head_cmd)
        )
        # head.rand == port | (0xaa55 << 16) — Requirement 6.1
        # encoding per ``c++_demo/NetConfig/kmboxNet.cpp:kmNet_monitor``.
        expected_rand = (port | (0xAA55 << 16)) & 0xFFFFFFFF
        assert head_rand == expected_rand, (
            "monitor(%d): expected head.rand == 0x%08x "
            "(port | (0xaa55 << 16)); got 0x%08x"
            % (port, expected_rand, head_rand)
        )

        # The ``_MonitorListener`` constructed exactly one new socket
        # bound to ``('0.0.0.0', port)`` — Requirement 6.1.
        assert len(sockets) == sockets_before + 1, (
            "monitor(%d): expected exactly one new socket for the "
            "monitor listener; got %d → %d"
            % (port, sockets_before, len(sockets))
        )
        listener_sock = sockets[-1]
        assert listener_sock.bound_address == ("0.0.0.0", port), (
            "monitor(%d): listener socket must be bound to "
            "('0.0.0.0', %d); got %r"
            % (port, port, listener_sock.bound_address)
        )
        assert listener_sock.closed is False, (
            "monitor(%d): listener socket must be open after enable"
            % port
        )

        # Driver-level Monitor_Channel state is enabled — Requirement 6.1.
        assert driver._monitor_enabled is True, (
            "monitor(%d): driver._monitor_enabled must be True after "
            "enable" % port
        )
        assert driver._monitor_listener is not None, (
            "monitor(%d): driver._monitor_listener must be a live "
            "thread reference after enable" % port
        )

        # ---- 2. monitor(0) — disable path -------------------------

        sent_before = len(send_socket.sent)

        driver.monitor(0)

        # Exactly one new packet on the wire.
        assert len(send_socket.sent) == sent_before + 1, (
            "monitor(0) (was %d): expected exactly one new UDP "
            "packet on the send socket; got %d → %d"
            % (port, sent_before, len(send_socket.sent))
        )
        disable_packet, disable_addr = send_socket.sent[-1]
        assert disable_addr == ("192.168.2.188", 41990), (
            "monitor(0) (was %d): cmd_monitor packet must be routed "
            "to the configured device address; got %r"
            % (port, disable_addr)
        )
        _mac, head_rand, _indexpts, head_cmd = _decode_head(disable_packet)
        # head.cmd still CMD_MONITOR — Requirement 6.2.
        assert head_cmd == CMD_MONITOR, (
            "monitor(0) (was %d): expected head.cmd == CMD_MONITOR "
            "(0x%08x); got 0x%08x"
            % (port, CMD_MONITOR, head_cmd)
        )
        # head.rand == 0 — Requirement 6.2 disable encoding.
        assert head_rand == 0, (
            "monitor(0) (was %d): expected head.rand == 0 on the "
            "disable packet; got 0x%08x" % (port, head_rand)
        )

        # The previously-bound listener socket is now closed —
        # Requirement 6.2 ("close the local UDP listener").
        assert listener_sock.closed is True, (
            "monitor(0) (was %d): the listener socket must be "
            "closed after disable" % port
        )
        # Driver-level Monitor_Channel state is disabled —
        # Requirement 6.2.
        assert driver._monitor_enabled is False, (
            "monitor(0) (was %d): driver._monitor_enabled must be "
            "False after disable" % port
        )
        assert driver._monitor_listener is None, (
            "monitor(0) (was %d): driver._monitor_listener must be "
            "None after disable" % port
        )
    finally:
        # Tear the driver down so any spawned listener thread is
        # joined and the UDP socket is closed before the next
        # Hypothesis example runs. ``release()`` is idempotent
        # (Property 5) so a second call from the test cleanup path
        # below would be safe — we keep this single explicit call
        # for clarity.
        try:
            driver.release()
        finally:
            _restore_socket(driver)
