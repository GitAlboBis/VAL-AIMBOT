"""
Property test — Task 8.4 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 6: ``send_click`` press-release ordering.

**Property 6: ``send_click`` press-release ordering**

    *For any* ``delay ∈ [0.0, 5.0]`` while
    ``connection_status == 'connected'``, an admitted
    ``send_click(delay)`` invocation SHALL satisfy:

      * Exactly two UDP packets reach the wire.
      * The first packet has ``head.cmd == CMD_MOUSE_LEFT`` and
        ``soft_mouse_t.button & 0x01 == 1`` (left-button press).
      * The second packet has ``head.cmd == CMD_MOUSE_LEFT`` and
        ``soft_mouse_t.button & 0x01 == 0`` (left-button release).
      * The wall-clock time between call entry and the first emitted
        packet is at least ``delay`` seconds within ±10 ms (using
        :class:`FakeClock` so the test is deterministic and fast).

**Validates: Requirements 3.9**

Implementation notes
--------------------

The test instantiates a real :class:`KmBoxNetDriver` so the
constructor exercises the full Init_Handshake send + recv path against
a :class:`FakeUdpSocket` and a :class:`FakeDevice` configured for a
successful reply, leaving the driver in
:data:`ConnectionStatus.CONNECTED`. The handshake itself emits one
packet to ``fake_sock.sent`` — the test snapshots that count after
construction so the "exactly two new packets" assertion compares to
the post-handshake baseline.

``time.sleep`` is monkey-patched at module level to record (rather
than perform) the requested delay; the recorded value is compared
against the input ``delay`` to verify Requirement 3.9's "wait for
``delay_before_click`` seconds" clause. Recording rather than
sleeping keeps the property test fast enough to run 100+ Hypothesis
examples without the test suite stalling on real wall-clock waits up
to 5 seconds per example.

The socket setup is done inline (rather than through pytest fixtures)
because Hypothesis runs the test body many times per pytest
invocation: function-scoped fixtures retain state across examples
and the :class:`FakeDevice` only publishes its handshake reply once.
Constructing fresh fakes per example keeps each
``KmBoxNetDriver()`` call deterministic. This mirrors the
``_build_connected_driver`` pattern used in
``test_dispatch_oserror_isolation.py``,
``test_dispatch_encrypt_isolation.py``, and
``test_status_gated_send.py``.

Encryption is disabled (``use_encryption=False``) so the two
mouse-button packets land on the wire as plaintext 72-byte
``cmd_head_t + soft_mouse_t`` records that the test can decode with
``struct.unpack`` without needing to model the encryptor's keystream.
Property 6 is independent of the ``use_encryption`` flag (the
press-release ordering is determined by ``send_click`` itself, not
by the wire-encoding stage), so the plaintext decoding is purely a
test-harness convenience.

``send_click`` is the synchronous variant (per Requirements 3.9 /
3.10) — it does *not* spawn a background click thread, so the test
runs entirely in the calling thread with no thread-join or polling
required.
"""

from __future__ import annotations

import socket as _stdlib_socket
import struct
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
    CMD_HEAD_FORMAT,
    CMD_HEAD_SIZE,
    CMD_MOUSE_LEFT,
    MOUSE_BUTTON_LEFT_BIT,
    SOFT_MOUSE_FORMAT,
    SOFT_MOUSE_SIZE,
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


# ``valid_delay`` — finite floats in the inclusive range ``[0.0, 5.0]``
# per Requirements 3.2 / 3.9 / 3.10. NaN and ±inf are excluded because
# they are out-of-range per Requirement 3.10 and would be silently
# dropped by ``send_click`` — Property 6 is the *admitted* path, so
# the strategy stays inside the accepted range.
_st_delay = st.floats(
    min_value=0.0,
    max_value=5.0,
    allow_nan=False,
    allow_infinity=False,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_connected_driver() -> tuple[KmBoxNetDriver, FakeUdpSocket]:
    """Construct a ``KmBoxNetDriver`` whose handshake succeeds against a fake.

    Patches ``socket.socket`` for the duration of the constructor so
    the driver creates a :class:`FakeUdpSocket` instead of a real one,
    and attaches a successful :class:`FakeDevice` so the handshake
    ``recvfrom`` resolves to a zero-result-code reply. The patch is
    reverted before the function returns.

    The returned driver is in ``ConnectionStatus.CONNECTED`` with
    ``initialized == True`` and ``use_encryption == False`` so the two
    mouse-button packets emitted by ``send_click`` are plaintext
    72-byte ``cmd_head_t + soft_mouse_t`` records that the test can
    decode without modelling the encryptor's keystream.

    Returns:
        Tuple of (driver, fake_udp_socket). The ``fake_udp_socket`` is
        the underlying transport the driver bound during construction;
        ``fake_udp_socket.sent`` records every packet the driver has
        emitted, including the handshake.
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
    return driver, sockets[0]


def _decode_mouse_packet(
    packet: bytes,
) -> tuple[int, int]:
    """Decode the ``head.cmd`` and ``soft_mouse_t.button`` fields.

    Mouse-class packets are exactly ``CMD_HEAD_SIZE + SOFT_MOUSE_SIZE``
    bytes (16 + 56 = 72 bytes) per the design's "Per-command payload
    encoding" table. The header layout
    ``(mac, rand, indexpts, cmd)`` is little-endian, and the payload
    starts at offset ``CMD_HEAD_SIZE`` with the ``button`` field as
    the first ``int32`` of the ``soft_mouse_t`` struct (per the
    ``"<iiii10i"`` format string in :data:`SOFT_MOUSE_FORMAT`).

    Returns:
        Tuple of ``(head.cmd, soft_mouse_t.button)``.
    """
    expected = CMD_HEAD_SIZE + SOFT_MOUSE_SIZE
    assert len(packet) == expected, (
        f"mouse-class packet must be exactly {expected} bytes "
        f"(header + soft_mouse_t); got {len(packet)}"
    )
    _mac, _rand, _indexpts, head_cmd = struct.unpack(
        CMD_HEAD_FORMAT, packet[:CMD_HEAD_SIZE]
    )
    fields = struct.unpack(
        SOFT_MOUSE_FORMAT, packet[CMD_HEAD_SIZE:expected]
    )
    button = fields[0]
    return head_cmd, button


# ---------------------------------------------------------------------------
# Property 6
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(delay=_st_delay)
def test_send_click_press_release_ordering(delay: float) -> None:
    """``send_click(delay)`` emits press-then-release with a ≥ ``delay`` wait.

    For each generated ``delay ∈ [0.0, 5.0]`` the test:

      1. Builds a connected driver (handshake against a
         :class:`FakeDevice`, encryption disabled so packets are
         plaintext).
      2. Patches ``time.sleep`` and ``time.monotonic`` at module
         level (with ``try`` / ``finally`` restoration) to record the
         requested delay in ``recorded_sleeps`` *and* advance a
         virtual clock — this takes the role of the design's
         :class:`FakeClock` for Property 6 without imposing real
         wall-clock waits. Direct module-level patching (rather
         than the ``monkeypatch`` fixture) is required because
         pytest's function-scoped fixtures are not reset between
         Hypothesis examples.
      3. Calls ``driver.send_click(delay)``.
      4. Decodes the two new packets in ``fake_sock.sent`` and
         asserts the press-then-release ordering.
      5. Asserts ``time.sleep`` was called with ``delay`` (within
         ±10 ms tolerance per Property 6).

    Validates: Requirements 3.9.
    """
    # 1. Build a connected driver against the fakes. The handshake
    # itself emits one packet to ``fake_sock.sent``, so the
    # post-handshake baseline is 1.
    driver, fake_sock = _build_connected_driver()
    assert driver.connection_status == ConnectionStatus.CONNECTED, (
        "test pre-condition: handshake must succeed so send_click "
        "is not gated out by the status check; got %r"
        % (driver.connection_status,)
    )
    assert driver.initialized is True
    assert driver.use_encryption is False
    assert fake_sock.closed is False

    handshake_packet_count = len(fake_sock.sent)
    assert handshake_packet_count == 1, (
        "test pre-condition: exactly one handshake packet should "
        "have been emitted before send_click; got %d"
        % handshake_packet_count
    )

    # 2. Patch ``time.sleep`` and ``time.monotonic`` to record
    # (rather than perform) the delay and advance a virtual clock.
    # We use ``try`` / ``finally`` for restoration because pytest's
    # ``monkeypatch`` fixture is function-scoped and would not be
    # reset between Hypothesis examples (it would carry the patched
    # values across iterations and trigger Hypothesis's
    # ``function_scoped_fixture`` health check).
    recorded_sleeps: list[float] = []
    virtual_now: list[float] = [0.0]

    def _fake_sleep(seconds: float) -> None:
        recorded_sleeps.append(float(seconds))
        # Advance the virtual clock by the requested duration so the
        # ``time.monotonic`` measurement below reflects the
        # accumulated sleep time, not real wall-clock time.
        virtual_now[0] += max(0.0, float(seconds))

    def _fake_monotonic() -> float:
        return virtual_now[0]

    original_sleep = _stdlib_time.sleep
    original_monotonic = _stdlib_time.monotonic
    _stdlib_time.sleep = _fake_sleep  # type: ignore[assignment]
    _stdlib_time.monotonic = _fake_monotonic  # type: ignore[assignment]
    try:
        # 3. Snapshot the wall-clock entry time and invoke
        # ``send_click``. ``send_click`` is the synchronous variant
        # (Requirements 3.9 / 3.10) — it does NOT spawn a thread, so
        # by the time the call returns both packets are already on
        # the wire.
        sent_before = len(fake_sock.sent)
        t_entry = _stdlib_time.monotonic()
        driver.send_click(delay)
        t_exit = _stdlib_time.monotonic()
    finally:
        _stdlib_time.sleep = original_sleep  # type: ignore[assignment]
        _stdlib_time.monotonic = original_monotonic  # type: ignore[assignment]

    # 4. Verify exactly two new packets reached the wire.
    sent_after = len(fake_sock.sent)
    new_packets = fake_sock.sent[sent_before:sent_after]
    assert len(new_packets) == 2, (
        "send_click(%r) must emit exactly two UDP packets (press + "
        "release) per Requirement 3.9; got %d new packets in "
        "fake_sock.sent."
        % (delay, len(new_packets))
    )

    # 5. Decode the two packets and verify ordering.
    press_packet, _press_addr = new_packets[0]
    release_packet, _release_addr = new_packets[1]

    press_cmd, press_button = _decode_mouse_packet(press_packet)
    release_cmd, release_button = _decode_mouse_packet(release_packet)

    # Clause 1 — both packets target ``CMD_MOUSE_LEFT`` per
    # Requirement 3.9 ("press the left mouse button" / "release the
    # left mouse button").
    assert press_cmd == CMD_MOUSE_LEFT, (
        "send_click(%r): first packet head.cmd must be "
        "CMD_MOUSE_LEFT (=%d); got %d."
        % (delay, CMD_MOUSE_LEFT, press_cmd)
    )
    assert release_cmd == CMD_MOUSE_LEFT, (
        "send_click(%r): second packet head.cmd must be "
        "CMD_MOUSE_LEFT (=%d); got %d."
        % (delay, CMD_MOUSE_LEFT, release_cmd)
    )

    # Clause 2 — the first packet is a press (button bit 0 = 1) and
    # the second is a release (button bit 0 = 0). Property 6
    # specifies the assertion in terms of ``button & 0x01``; the
    # ``MOUSE_BUTTON_LEFT_BIT`` constant equals ``0x01`` per the
    # ``soft_mouse_t`` field documentation.
    assert MOUSE_BUTTON_LEFT_BIT == 0x01, (
        "test harness invariant: MOUSE_BUTTON_LEFT_BIT must be 0x01 "
        "per the design's soft_mouse_t button-bit table; got %r."
        % (MOUSE_BUTTON_LEFT_BIT,)
    )
    assert (press_button & 0x01) == 1, (
        "send_click(%r): first packet must press the left button "
        "(soft_mouse_t.button & 0x01 == 1); got button=%d."
        % (delay, press_button)
    )
    assert (release_button & 0x01) == 0, (
        "send_click(%r): second packet must release the left button "
        "(soft_mouse_t.button & 0x01 == 0); got button=%d."
        % (delay, release_button)
    )

    # Clause 3 — Requirement 3.9's "wait for ``delay_before_click``
    # seconds" clause. ``send_click`` calls ``time.sleep(delay)``
    # exactly once before the press packet, so ``recorded_sleeps``
    # must contain at least one entry whose value equals ``delay``
    # within the floating-point tolerance dictated by Property 6
    # (±10 ms).
    assert len(recorded_sleeps) >= 1, (
        "send_click(%r) must call time.sleep at least once before "
        "emitting the press packet (Requirement 3.9); got "
        "recorded_sleeps=%r."
        % (delay, recorded_sleeps)
    )
    # The first sleep is the inter-call delay. There should be only
    # one ``time.sleep`` invocation inside ``send_click`` per the
    # implementation; assert that to catch a regression that would
    # double the wait.
    assert len(recorded_sleeps) == 1, (
        "send_click(%r) is expected to call time.sleep exactly once "
        "(for the pre-press delay); got %d sleeps with values %r."
        % (delay, len(recorded_sleeps), recorded_sleeps)
    )
    actual_sleep = recorded_sleeps[0]
    assert abs(actual_sleep - delay) <= 0.010, (
        "send_click(%r): time.sleep must be called with the requested "
        "delay within ±10 ms tolerance per Property 6; got %r "
        "(difference %r s)."
        % (delay, actual_sleep, actual_sleep - delay)
    )

    # Clause 4 — the *virtual* wall-clock time (driven by
    # ``time.monotonic`` which we patched to follow the
    # ``time.sleep`` advance) between call entry and call exit must
    # be at least ``delay`` seconds within ±10 ms. Because
    # ``send_click`` is synchronous and emits the press packet
    # immediately after ``time.sleep`` returns, the entry-to-exit
    # span bounds the entry-to-first-packet span from above.
    elapsed = t_exit - t_entry
    assert elapsed + 0.010 >= delay, (
        "send_click(%r): wall-clock time between call entry and "
        "call exit must be ≥ delay within ±10 ms (Property 6); "
        "got entry=%r exit=%r elapsed=%r."
        % (delay, t_entry, t_exit, elapsed)
    )
    # Upper bound: the entry-to-exit span equals the recorded sleep
    # plus the bounded build/encrypt/sendto cost of two packets.
    # Hypothesis tolerates ±10 ms here too — anything larger would
    # indicate the synchronous ``send_click`` accidentally spawned a
    # background thread or otherwise added a non-deterministic wait.
    assert elapsed <= delay + 0.010, (
        "send_click(%r): wall-clock time between call entry and "
        "call exit must be ≤ delay + 10 ms (Property 6); got "
        "entry=%r exit=%r elapsed=%r."
        % (delay, t_entry, t_exit, elapsed)
    )

    # 6. Driver invariants must hold across the call: the gate's
    # status / initialized flags MUST NOT change on the admitted
    # path, and the underlying socket MUST stay open.
    assert driver.connection_status == ConnectionStatus.CONNECTED
    assert driver.initialized is True
    assert fake_sock.closed is False
