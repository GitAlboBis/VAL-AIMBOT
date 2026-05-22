"""
Property test — Task 5.3 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 14: Handshake is always plaintext.

**Property 14: Handshake is always plaintext**

    *For any* ``use_encryption ∈ {True, False}`` and any valid
    ``(ip, port, uuid)`` argument tuple, the UDP packet emitted by
    the Init_Handshake at :class:`KmBoxNetDriver.__init__` time
    decodes byte-for-byte against the plaintext ``cmd_head_t``
    layout:

      * ``head.cmd == CMD_CONNECT`` (``0xAF3C2828``),
      * ``head.mac == StrToHex(uuid, 4)``
        (``int(uuid[:8].ljust(8, '0'), 16)`` per
        ``c++_demo/NetConfig/kmboxNet.cpp:StrToHex`` semantics),

    and the :class:`PacketEncryptor` transform is *never* applied to
    this packet — the wire bytes are exactly the 16-byte plaintext
    header. The encrypted form would be 128 bytes (every
    ``kmNet_enc_*`` function in ``kmboxNet.cpp`` calls
    ``sendto(..., (const char*)&tx_enc, 128, ...)``); the length
    itself proves no encryption was applied.

**Validates: Requirements 9.6**

Implementation notes
--------------------

The handshake packet is the *first* packet ``KmBoxNetDriver`` emits.
Subsequent packets sent by the driver during ``__init__`` are zero
(the constructor only sends the handshake; the ``recvfrom`` is a
read), so ``fake_sock.sent[0]`` is unambiguously the handshake.

Unlike pytest fixtures that retain state across Hypothesis examples,
this test follows the inline ``socket.socket`` monkey-patching pattern
used in :mod:`tests.input.kmbox_net.test_dispatch_encrypt_isolation`:
a fresh :class:`FakeUdpSocket` and :class:`FakeDevice` are constructed
per Hypothesis example so cross-example state (queued recv replies,
recorded ``sent`` packets, the device's ``_handshake_published``
flag) does not leak.

The encryption transform is verified to be *not applied* in two
complementary ways:

  1. **Length check (necessary)** — the packet length must equal
     :data:`CMD_HEAD_SIZE` (16). Any application of the encryptor
     would produce a 128-byte ciphertext, so a length of 16 bytes is
     direct evidence that ``PacketEncryptor.encrypt`` was not
     invoked.
  2. **Bytewise plaintext decode (sufficient)** — the four header
     fields ``(mac, rand, indexpts, cmd)`` recovered via
     ``struct.unpack('<IIII', packet[:16])`` must match the
     plaintext ``pack_header(StrToHex(uuid), 0, indexpts,
     CMD_CONNECT)`` layout exactly. A correct 16-byte ciphertext
     under the same MAC-derived key would *not* coincidentally
     decode to the plaintext layout, so this assertion is a strict
     bytewise check.

A third belt-and-braces check installs an instrumentation wrapper
around :meth:`PacketEncryptor.encrypt` *before* the constructor runs;
the wrapper records every call. After ``__init__`` returns the test
asserts the wrapper recorded zero invocations — direct evidence that
the encryption transform was not applied to the handshake packet
even when ``use_encryption=True``. This is the most explicit
encoding of "the encryption transform is never applied to this
packet" from the task description.
"""

from __future__ import annotations

import socket as _stdlib_socket
import struct
import sys
from pathlib import Path

# Make the ``input`` package importable when pytest is launched from
# the repository root or any sub-directory (the driver ships as
# ``input/kmbox_net_driver.py`` at the project root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from input.kmbox_net_driver import (  # noqa: E402  — sys.path manipulation above
    CMD_CONNECT,
    CMD_HEAD_FORMAT,
    CMD_HEAD_SIZE,
    ConnectionStatus,
    KmBoxNetDriver,
    PacketEncryptor,
)
from tests.input.kmbox_net.conftest import (  # noqa: E402
    FakeDevice,
    FakeUdpSocket,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


# ``valid_uuid`` per design.md "Hypothesis strategies": a non-empty
# string of length [1, 64] using hexadecimal characters only. The
# hex-only restriction guarantees ``int(uuid[:8].ljust(8, '0'), 16)``
# inside ``__init__`` does not raise — Property 14 is about the
# *successful* handshake send path, not about ``StrToHex`` failure.
_st_uuid = st.text(
    alphabet="0123456789ABCDEFabcdef",
    min_size=1,
    max_size=64,
)

# ``use_encryption`` covers both arms of Property 14: the plaintext
# handshake invariant must hold regardless of the flag's value.
_st_use_encryption = st.booleans()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _str_to_hex(uuid: str) -> int:
    """Reproduce ``c++_demo/NetConfig/kmboxNet.cpp:StrToHex(uuid, 4)``.

    The upstream ``StrToHex`` reads up to 8 hex characters and packs
    them into a 32-bit big-endian integer
    (``byte0 << 24 | byte1 << 16 | byte2 << 8 | byte3``). The Python
    expression ``int(uuid[:8].ljust(8, '0'), 16)`` produces the
    identical result for any hex-only ``uuid``: ``int(...,16)``
    treats the string as big-endian hex digits, and ``ljust(8, '0')``
    right-pads short ``uuid`` values so a 4-character ``"1234"``
    yields ``0x12340000`` exactly as the upstream would.

    This helper exists as a separate test-side reference so the
    assertion does not silently agree with itself if the driver's
    own MAC parsing regresses.
    """
    return int(uuid[:8].ljust(8, "0"), 16)


def _build_driver_with_fakes(
    *,
    uuid: str,
    use_encryption: bool,
) -> tuple[KmBoxNetDriver, FakeUdpSocket, list[bytes]]:
    """Construct a driver against fresh fakes; return driver, socket, encrypt-log.

    Steps:

      1. Build a fresh :class:`FakeUdpSocket` and a successful
         :class:`FakeDevice` so the constructor's handshake
         ``recvfrom`` resolves without timeout.
      2. Install an instrumentation wrapper around
         :meth:`PacketEncryptor.encrypt` *on the class* so any call
         made during ``__init__`` is recorded. The wrapper still
         delegates to the real transform, but Property 14 expects
         the recorded list to remain empty.
      3. Monkey-patch ``socket.socket`` so the driver's UDP-socket
         construction yields the prepared :class:`FakeUdpSocket`
         instance and the fake device's handshake reply is queued
         on it before the driver issues ``recvfrom``.
      4. Run the constructor and revert the patch.

    A fresh :class:`FakeUdpSocket` and :class:`FakeDevice` per call
    eliminates the cross-example state-leak hazard inherent in
    pytest fixtures used under Hypothesis — the device's
    ``_handshake_published`` flag and the socket's ``sent`` /
    ``_recv_queue`` are all per-example.

    Returns:
        Tuple of (driver, fake_socket, encrypt_call_log). The
        ``encrypt_call_log`` is the list populated by the
        instrumentation wrapper — Property 14 asserts it is empty.
    """
    sockets: list[FakeUdpSocket] = []
    device = FakeDevice(outcome=FakeDevice.HandshakeOutcome.SUCCESS)

    def _factory(
        family: int = _stdlib_socket.AF_INET,
        type_: int = _stdlib_socket.SOCK_DGRAM,
        proto: int = 0,
        fileno: int | None = None,
        **_kwargs,
    ) -> FakeUdpSocket:
        sock = FakeUdpSocket(family=family, type_=type_)
        sock.proto = proto
        sockets.append(sock)
        # Attach the device on the *first* socket only so the
        # handshake reply is queued before the driver's ``recvfrom``.
        if len(sockets) == 1:
            device.attach(sock)
        return sock

    # Install class-level instrumentation around
    # ``PacketEncryptor.encrypt``. Patching on the class (rather
    # than on a per-instance basis) means the wrapper sees calls
    # made through *any* encryptor instance the driver constructs
    # during ``__init__``; if the constructor were to mistakenly
    # build a second encryptor and route the handshake through that,
    # the wrapper would still catch it.
    encrypt_call_log: list[bytes] = []
    real_encrypt = PacketEncryptor.encrypt

    def _instrumented_encrypt(self_enc: PacketEncryptor, plaintext: bytes) -> bytes:
        encrypt_call_log.append(bytes(plaintext))
        return real_encrypt(self_enc, plaintext)

    PacketEncryptor.encrypt = _instrumented_encrypt  # type: ignore[method-assign]

    original_socket = _stdlib_socket.socket
    _stdlib_socket.socket = _factory  # type: ignore[assignment]
    try:
        driver = KmBoxNetDriver(
            ip="192.168.2.188",
            port="41990",
            uuid=uuid,
            use_encryption=use_encryption,
        )
    finally:
        _stdlib_socket.socket = original_socket  # type: ignore[assignment]
        PacketEncryptor.encrypt = real_encrypt  # type: ignore[method-assign]

    if not sockets:
        raise RuntimeError(
            "test harness invariant violated: KmBoxNetDriver did not "
            "construct any UDP socket"
        )
    return driver, sockets[0], encrypt_call_log


# ---------------------------------------------------------------------------
# Property 14
# ---------------------------------------------------------------------------


@settings(
    max_examples=75,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(uuid=_st_uuid, use_encryption=_st_use_encryption)
def test_handshake_is_always_plaintext(uuid: str, use_encryption: bool) -> None:
    """Init_Handshake bytes are plaintext under both encryption flag values.

    For each generated ``(uuid, use_encryption)`` pair the test:

      1. Builds a fresh :class:`KmBoxNetDriver` against a fresh
         :class:`FakeUdpSocket` + :class:`FakeDevice` configured for
         a successful handshake.
      2. Asserts the handshake completed (``connection_status`` is
         :data:`ConnectionStatus.CONNECTED`) so the test is
         exercising the success path that emits the handshake
         packet — not a validation-failure / timeout / OSError
         branch.
      3. Asserts exactly one packet was emitted to the wire — the
         handshake — and that no ``recvfrom`` reply was left
         unconsumed (the device only published one handshake reply,
         which the driver consumed during ``__init__``).
      4. Decodes the first emitted packet as the plaintext
         ``cmd_head_t`` layout via
         ``struct.unpack('<IIII', packet[:16])`` and asserts:

           * the packet length is exactly :data:`CMD_HEAD_SIZE`
             (16 bytes — anything else, in particular 128 bytes,
             is direct evidence that the encryptor was applied);
           * ``cmd == CMD_CONNECT`` (``0xAF3C2828``);
           * ``mac == StrToHex(uuid, 4)``
             (``int(uuid[:8].ljust(8, '0'), 16)``);
           * ``head.rand == 0`` per the driver's
             :meth:`PacketBuilder.build_connect` contract (the
             upstream BSS-initialized ``client_tx`` global has
             ``head.rand == 0`` at handshake time);
           * ``head.indexpts == 1`` — the very first packet emitted
             after construction; ``next_indexpts()`` increments
             from 0 to 1 before the handshake is built.
      5. Asserts the instrumentation wrapper recorded zero calls
         to :meth:`PacketEncryptor.encrypt` during ``__init__`` —
         direct evidence the encryption transform was never applied
         to the handshake packet.

    Validates: Requirements 9.6.
    """
    driver, fake_sock, encrypt_call_log = _build_driver_with_fakes(
        uuid=uuid, use_encryption=use_encryption
    )

    # ---- Pre-conditions: the success path was actually exercised --
    assert driver.connection_status == ConnectionStatus.CONNECTED, (
        "test pre-condition: handshake should have succeeded so that "
        "fake_sock.sent[0] is the Init_Handshake packet on the "
        "success path; got connection_status=%r"
        % (driver.connection_status,)
    )
    assert driver.initialized is True, (
        "test pre-condition: handshake success should set "
        "initialized=True"
    )
    assert driver.use_encryption is bool(use_encryption), (
        "test pre-condition: KmBoxNetDriver should preserve the "
        "use_encryption flag verbatim; got use_encryption=%r, "
        "expected %r" % (driver.use_encryption, use_encryption)
    )

    # ---- Core invariant 1: the encryption transform was never
    # applied to the handshake packet. With ``use_encryption=False``
    # this is trivially true; with ``use_encryption=True`` it is the
    # heart of Requirement 9.6.
    assert encrypt_call_log == [], (
        "Property 14 violated: PacketEncryptor.encrypt was invoked "
        "%d time(s) during __init__ (use_encryption=%r). The "
        "Init_Handshake packet must always be plaintext per "
        "Requirement 9.6, regardless of the use_encryption flag."
        % (len(encrypt_call_log), use_encryption)
    )

    # ---- Core invariant 2: exactly one packet on the wire — the
    # handshake. The constructor sends only the handshake during
    # ``__init__``; subsequent commands have not yet been issued.
    assert len(fake_sock.sent) == 1, (
        "test pre-condition: KmBoxNetDriver.__init__ should emit "
        "exactly one packet (the Init_Handshake) on the success "
        "path; got %d packets" % len(fake_sock.sent)
    )

    handshake_packet, _addr = fake_sock.sent[0]

    # ---- Core invariant 3: packet length is exactly
    # ``CMD_HEAD_SIZE`` (16 bytes). Any application of
    # ``PacketEncryptor.encrypt`` would yield a 128-byte ciphertext
    # per :data:`PacketEncryptor.BLOCK_SIZE_BYTES` — the length
    # itself is direct evidence of the plaintext invariant.
    assert len(handshake_packet) == CMD_HEAD_SIZE, (
        "Property 14 violated: handshake packet length is %d bytes, "
        "expected %d (CMD_HEAD_SIZE). A length of "
        "%d (BLOCK_SIZE_BYTES) would indicate the encryption "
        "transform was applied to the handshake; Requirement 9.6 "
        "forbids that."
        % (
            len(handshake_packet),
            CMD_HEAD_SIZE,
            PacketEncryptor.BLOCK_SIZE_BYTES,
        )
    )

    # ---- Core invariant 4: the bytes decode against the plaintext
    # ``cmd_head_t`` layout exactly. We unpack as ``<IIII`` so each
    # 32-bit field is read little-endian per the upstream wire
    # format (``cmd_head_t`` in ``c++_demo/NetConfig/kmboxNet.h``).
    mac, rand, indexpts, cmd = struct.unpack(
        CMD_HEAD_FORMAT, handshake_packet[:CMD_HEAD_SIZE]
    )

    # ``head.cmd`` must be the ``cmd_connect`` identifier per the
    # upstream ``kmNet_init`` body.
    assert cmd == CMD_CONNECT, (
        "Property 14 violated: handshake head.cmd=0x%08X, expected "
        "CMD_CONNECT=0x%08X." % (cmd, CMD_CONNECT)
    )

    # ``head.mac`` must equal ``StrToHex(uuid, 4)`` — the test
    # computes this value from the input ``uuid`` independently of
    # the driver to avoid silent agreement on a regressed parser.
    expected_mac = _str_to_hex(uuid)
    assert mac == expected_mac, (
        "Property 14 violated: handshake head.mac=0x%08X, expected "
        "StrToHex(%r, 4)=0x%08X."
        % (mac, uuid[:8], expected_mac)
    )

    # ``head.rand == 0`` per :meth:`PacketBuilder.build_connect`. The
    # upstream BSS-initialized ``client_tx`` global has ``head.rand``
    # zero before the first send; the driver mirrors that.
    assert rand == 0, (
        "Property 14 follow-on: handshake head.rand=%d, expected 0 "
        "(the upstream BSS-initialized ``client_tx`` global has "
        "head.rand zero before the first send)." % rand
    )

    # ``head.indexpts == 1`` — ``next_indexpts()`` increments from
    # zero to one before the handshake is built; the handshake is
    # the very first packet emitted after construction.
    assert indexpts == 1, (
        "Property 14 follow-on: handshake head.indexpts=%d, "
        "expected 1 (next_indexpts increments from 0 to 1 before "
        "the handshake is built; the handshake is the very first "
        "packet emitted after construction)." % indexpts
    )

    # Final belt-and-braces: a freshly constructed plaintext header
    # built by an independent reference path must equal the bytes on
    # the wire byte-for-byte. Re-encoding via ``struct.pack`` here
    # serves as the most explicit encoding of "decodes byte-for-byte
    # against the plaintext ``cmd_head_t`` layout" from Property 14.
    expected_plaintext = struct.pack(
        CMD_HEAD_FORMAT,
        expected_mac & 0xFFFFFFFF,
        0,
        1,
        CMD_CONNECT,
    )
    assert handshake_packet == expected_plaintext, (
        "Property 14 violated: handshake bytes do not match the "
        "plaintext ``cmd_head_t`` layout byte-for-byte. Got %r; "
        "expected %r." % (handshake_packet, expected_plaintext)
    )
