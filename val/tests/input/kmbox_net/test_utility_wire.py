"""
Property test — Task 2.7 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 7 (utility subset): Per-command
#   round-trip encoding.

**Property 7 (utility subset): Per-command round-trip encoding**

    *For each* command in
    ``{monitor, reboot, setconfig, mask_mouse_left, unmask_all,
    keydown, keyup}``, with valid arguments generated via Hypothesis,
    the packet built by :class:`PacketBuilder` SHALL satisfy:

      * ``head.cmd`` matches the documented identifier
        (``CMD_MONITOR``, ``CMD_REBOOT``, ``CMD_SETCONFIG``,
        ``CMD_MASK_MOUSE``, ``CMD_UNMASK_ALL`` or ``CMD_KEYBOARD_ALL``
        for keydown/keyup) — Requirements 6.1, 7.2, 7.4, 7.5.
      * ``head.rand`` follows the per-command encoding table from
        ``design.md`` — ``port | (0xaa55 << 16)`` for ``monitor`` with
        non-zero port, ``0`` for ``monitor(0)``, ``inet_aton(ip)`` as
        a little-endian ``uint32`` for ``setconfig``, ``state & 0x01``
        for ``mask_mouse_left``, ``0`` for ``unmask_all``.
      * The trailing payload bytes for ``setconfig`` are exactly
        ``[port >> 8, port & 0xff]`` (big-endian, two bytes).

**Validates: Requirements 6.1, 7.2, 7.4, 7.5**

Implementation notes
--------------------

The ``keydown`` / ``keyup`` commands are *not* separate packet types —
they reuse ``cmd_keyboard_all`` (``CMD_KEYBOARD_ALL``). The test
verifies that pressing/releasing a HID code via
``keyboard_apply_down`` / ``keyboard_apply_up`` against a
:class:`KeyboardState` and then calling
:meth:`PacketBuilder.build_keyboard` produces a 28-byte
``cmd_keyboard_all`` packet whose ``ctrl`` and ``button[10]`` bytes
exactly match the post-state expected from the press / release
operation.

Strategies follow design.md "Property tests" generator names:

  * ``valid_port = st.integers(1024, 49151)``
  * ``valid_ip = st.from_regex(r'^...$', fullmatch=True).filter(_octets_in_range)``
  * ``valid_hid = st.integers(0, 255)``
  * ``state ∈ {0, 1}``  (boolean equivalent for ``mask_mouse_left``)

The test does not import the driver class, the UDP socket, or any
other layer — :class:`PacketBuilder` is a pure-functional component
that only depends on stdlib ``struct`` / ``socket.inet_aton`` /
``random`` for header pack and rand generation, so the test stays
focused on the wire-encoding identity.
"""

from __future__ import annotations

import socket
import struct
import sys
from pathlib import Path

# Make the ``input`` package importable when pytest is launched from the
# repository root or any sub-directory. The driver ships as
# ``input/kmbox_net_driver.py`` at the project root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hypothesis import given, settings
from hypothesis import strategies as st

from input.kmbox_net_driver import (  # noqa: E402  — sys.path manipulation above
    CMD_HEAD_FORMAT,
    CMD_HEAD_SIZE,
    CMD_KEYBOARD_ALL,
    CMD_MASK_MOUSE,
    CMD_MONITOR,
    CMD_REBOOT,
    CMD_SETCONFIG,
    CMD_UNMASK_ALL,
    KeyboardState,
    PacketBuilder,
    SOFT_KEYBOARD_FORMAT,
    SOFT_KEYBOARD_KEY_SLOTS,
    keyboard_apply_down,
    keyboard_apply_up,
    pack_header,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _octets_in_range(ip: str) -> bool:
    """Return ``True`` iff every dotted-decimal octet is in ``[0, 255]``.

    Leading zeros are rejected so the generated IPs are accepted by
    ``socket.inet_aton`` on every supported platform (Python 3.13+ on
    some platforms refuses ``"0.0.0.08"``-style octets because the
    leading zero is interpreted as the prefix of an octal literal). The
    command-layer wrapper enforces stricter validation per Requirement
    7.3 anyway; the builder only needs IPs that ``inet_aton`` parses.
    """
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        # Reject empty octets and any octet with a leading zero unless
        # the octet is exactly ``"0"``.
        if not p or (len(p) > 1 and p[0] == "0"):
            return False
        try:
            value = int(p)
        except ValueError:
            return False
        if not (0 <= value <= 255):
            return False
    return True


# 32-bit unsigned MAC value — the full input space of
# ``StrToHex(uuid[:8], 4)`` (see ``kmboxNet.cpp:kmNet_init``).
_st_mac = st.integers(min_value=0, max_value=2**32 - 1)

# Pre-allocated monotonic counter — the caller-supplied ``indexpts``
# field of every per-command builder method. The wire field is a 32-bit
# unsigned int; sample the entire space.
_st_indexpts = st.integers(min_value=0, max_value=2**32 - 1)

# ``valid_port = st.integers(1024, 49151)`` per design.md generators.
_st_valid_port = st.integers(min_value=1024, max_value=49151)

# ``setconfig`` accepts the full ``[1, 65535]`` service-port range
# (Requirement 7.3); broaden the strategy here so the big-endian
# payload encoding is exercised across the whole 16-bit space.
_st_setconfig_port = st.integers(min_value=1, max_value=65535)

# ``valid_ip`` — dotted-decimal with octets in ``[0, 255]``.
_st_valid_ip = st.from_regex(
    r"^[0-9]{1,3}(\.[0-9]{1,3}){3}$", fullmatch=True
).filter(_octets_in_range)

# ``valid_hid = st.integers(0, 255)`` per design.md generators.
_st_valid_hid = st.integers(min_value=0, max_value=255)

# ``state ∈ {0, 1}`` for ``mask_mouse_left`` (Requirement 7.6).
_st_state = st.integers(min_value=0, max_value=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unpack_head(packet: bytes) -> tuple:
    """Return the four ``cmd_head_t`` fields ``(mac, rand, indexpts, cmd)``.

    The header is the first 16 bytes of every packet; ``struct.unpack``
    with ``CMD_HEAD_FORMAT`` (``<IIII``) decodes them as
    little-endian uint32s.
    """
    return struct.unpack(CMD_HEAD_FORMAT, packet[:CMD_HEAD_SIZE])


# ---------------------------------------------------------------------------
# Property 7 — monitor (port != 0)
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(mac=_st_mac, indexpts=_st_indexpts, port=_st_valid_port)
def test_monitor_packet_round_trip_nonzero(
    mac: int, indexpts: int, port: int
) -> None:
    """``build_monitor(port)`` for ``port != 0`` encodes per the table.

    Validates: Requirements 6.1.
    """
    builder = PacketBuilder(mac)
    packet = builder.build_monitor(indexpts, port)

    # ``cmd_monitor`` packets carry no payload beyond the header.
    assert len(packet) == CMD_HEAD_SIZE

    head_mac, head_rand, head_indexpts, head_cmd = _unpack_head(packet)
    assert head_cmd == CMD_MONITOR
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)
    # ``head.rand = port | (0xaa55 << 16)`` per
    # ``c++_demo/NetConfig/kmboxNet.cpp:kmNet_monitor`` and design.md.
    expected_rand = (port | (0xAA55 << 16)) & 0xFFFFFFFF
    assert head_rand == expected_rand


# ---------------------------------------------------------------------------
# Property 7 — monitor (port == 0)
# ---------------------------------------------------------------------------


@settings(max_examples=50, deadline=None)
@given(mac=_st_mac, indexpts=_st_indexpts)
def test_monitor_packet_round_trip_zero(mac: int, indexpts: int) -> None:
    """``build_monitor(0)`` encodes ``head.rand = 0``.

    Validates: Requirements 6.1.
    """
    builder = PacketBuilder(mac)
    packet = builder.build_monitor(indexpts, 0)

    assert len(packet) == CMD_HEAD_SIZE
    head_mac, head_rand, head_indexpts, head_cmd = _unpack_head(packet)
    assert head_cmd == CMD_MONITOR
    assert head_rand == 0
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)


# ---------------------------------------------------------------------------
# Property 7 — reboot
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(mac=_st_mac, indexpts=_st_indexpts)
def test_reboot_packet_round_trip(mac: int, indexpts: int) -> None:
    """``build_reboot`` produces a header-only ``cmd_reboot`` packet.

    Validates: Requirements 7.4 (``head.cmd == cmd_reboot`` is the only
    documented requirement; ``head.rand`` is randomized per
    ``kmboxNet.cpp:kmNet_reboot`` and is therefore not asserted).
    """
    builder = PacketBuilder(mac)
    packet = builder.build_reboot(indexpts)

    assert len(packet) == CMD_HEAD_SIZE
    head_mac, _head_rand, head_indexpts, head_cmd = _unpack_head(packet)
    assert head_cmd == CMD_REBOOT
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)


# ---------------------------------------------------------------------------
# Property 7 — setconfig
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(mac=_st_mac, indexpts=_st_indexpts, ip=_st_valid_ip, port=_st_setconfig_port)
def test_setconfig_packet_round_trip(
    mac: int, indexpts: int, ip: str, port: int
) -> None:
    """``build_setconfig`` encodes ``head.rand = inet_aton(ip)`` and a
    big-endian 2-byte port payload.

    Validates: Requirements 7.5.
    """
    builder = PacketBuilder(mac)
    packet = builder.build_setconfig(indexpts, ip, port)

    # Total packet length: 16-byte header + 2-byte payload.
    assert len(packet) == CMD_HEAD_SIZE + 2

    head_mac, head_rand, head_indexpts, head_cmd = _unpack_head(packet)
    assert head_cmd == CMD_SETCONFIG
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)
    # ``head.rand = inet_aton(ip)`` decoded as little-endian uint32 —
    # see design.md "Per-command payload encoding" for ``setconfig``.
    expected_rand = struct.unpack("<I", socket.inet_aton(ip))[0]
    assert head_rand == expected_rand

    # Trailing payload: exactly two bytes — high then low byte of port.
    payload = packet[CMD_HEAD_SIZE:]
    assert payload == bytes(((port >> 8) & 0xFF, port & 0xFF))


# ---------------------------------------------------------------------------
# Property 7 — mask_mouse_left
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(mac=_st_mac, indexpts=_st_indexpts, state=_st_state)
def test_mask_mouse_left_packet_round_trip(
    mac: int, indexpts: int, state: int
) -> None:
    """``build_mask_mouse_left(state)`` encodes ``head.rand = state & 1``.

    Validates: Requirements 7.2.
    """
    builder = PacketBuilder(mac)
    # Builder starts with ``mask_flag = 0``; bit0 of head.rand should
    # therefore equal ``state & 0x01`` after a single call.
    packet = builder.build_mask_mouse_left(indexpts, state)

    assert len(packet) == CMD_HEAD_SIZE
    head_mac, head_rand, head_indexpts, head_cmd = _unpack_head(packet)
    assert head_cmd == CMD_MASK_MOUSE
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)
    # bit0 carries ``state``; higher bits remain untouched (start at 0).
    assert (head_rand & 0x01) == (state & 0x01)
    assert (head_rand & ~0x01) == 0
    # The builder updates its internal bookkeeping in step.
    assert builder.mask_flag == (state & 0x01)


# ---------------------------------------------------------------------------
# Property 7 — unmask_all
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(mac=_st_mac, indexpts=_st_indexpts, prev_state=_st_state)
def test_unmask_all_packet_round_trip(
    mac: int, indexpts: int, prev_state: int
) -> None:
    """``build_unmask_all`` encodes ``head.rand = 0`` and resets the flag.

    Validates: Requirements 7.2 (``cmd_unmask_all`` always carries
    ``head.rand == 0`` per the design table; the builder also resets
    its internal ``mask_flag`` to zero).
    """
    builder = PacketBuilder(mac)
    # Pre-condition: builder may have been used to set bit0 first; the
    # subsequent ``unmask_all`` call MUST clear ``head.rand`` regardless.
    builder.build_mask_mouse_left(indexpts, prev_state)

    packet = builder.build_unmask_all(indexpts)

    assert len(packet) == CMD_HEAD_SIZE
    head_mac, head_rand, head_indexpts, head_cmd = _unpack_head(packet)
    assert head_cmd == CMD_UNMASK_ALL
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)
    assert head_rand == 0
    # Internal ``mask_flag`` reset to 0 per design.md.
    assert builder.mask_flag == 0


# ---------------------------------------------------------------------------
# Property 7 — keydown / keyup (re-using cmd_keyboard_all)
# ---------------------------------------------------------------------------
#
# Per the task brief, ``keydown`` / ``keyup`` are not standalone packet
# types: both reuse ``cmd_keyboard_all`` (``CMD_KEYBOARD_ALL``). The
# expected wire behavior is that pressing a HID via
# ``keyboard_apply_down`` and then ``build_keyboard``-ing the resulting
# ``KeyboardState`` produces a 28-byte packet whose 12-byte
# ``soft_keyboard_t`` payload exactly matches the post-state.


@settings(max_examples=200, deadline=None)
@given(mac=_st_mac, indexpts=_st_indexpts, hid=_st_valid_hid)
def test_keydown_packet_round_trip(
    mac: int, indexpts: int, hid: int
) -> None:
    """``keydown(hid)`` then ``build_keyboard`` emits a ``cmd_keyboard_all``
    packet whose payload reflects the press.

    Validates: Requirements 6.1, 7.2, 7.4, 7.5 (utility subset — keydown
    is grouped with monitor/utility commands per the task brief).
    """
    builder = PacketBuilder(mac)
    state = KeyboardState()
    keyboard_apply_down(state, hid)

    packet = builder.build_keyboard(indexpts, state.ctrl, state.keys)

    # Total packet length: 16-byte header + 12-byte payload.
    assert len(packet) == CMD_HEAD_SIZE + struct.calcsize(SOFT_KEYBOARD_FORMAT)

    head_mac, _head_rand, head_indexpts, head_cmd = _unpack_head(packet)
    # Note that "keydown"/"keyup" commands reuse cmd_keyboard_all.
    assert head_cmd == CMD_KEYBOARD_ALL
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)

    # Payload must match the post-state byte-for-byte.
    payload = packet[CMD_HEAD_SIZE:]
    expected_payload = struct.pack(
        SOFT_KEYBOARD_FORMAT,
        state.ctrl & 0xFF,
        0,
        *(k & 0xFF for k in state.keys),
    )
    assert payload == expected_payload

    # Sanity: the keyboard buffer always carries exactly 10 key slots.
    assert len(state.keys) == SOFT_KEYBOARD_KEY_SLOTS


@settings(max_examples=200, deadline=None)
@given(mac=_st_mac, indexpts=_st_indexpts, hid=_st_valid_hid)
def test_keyup_packet_round_trip(
    mac: int, indexpts: int, hid: int
) -> None:
    """``keydown(hid)`` followed by ``keyup(hid)`` then ``build_keyboard``
    emits a ``cmd_keyboard_all`` packet whose payload reflects the
    release (state returns to all-zero for any single press / release
    cycle).

    Validates: Requirements 6.1, 7.2, 7.4, 7.5 (utility subset — keyup
    is grouped with monitor/utility commands per the task brief).
    """
    builder = PacketBuilder(mac)
    state = KeyboardState()

    # Press then release the same HID — the buffer should return to its
    # pristine zeroed state for any HID in [0, 255].
    keyboard_apply_down(state, hid)
    keyboard_apply_up(state, hid)

    packet = builder.build_keyboard(indexpts, state.ctrl, state.keys)

    assert len(packet) == CMD_HEAD_SIZE + struct.calcsize(SOFT_KEYBOARD_FORMAT)

    head_mac, _head_rand, head_indexpts, head_cmd = _unpack_head(packet)
    assert head_cmd == CMD_KEYBOARD_ALL
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)

    # After a complete press/release cycle the post-state is all zeros.
    payload = packet[CMD_HEAD_SIZE:]
    expected_payload = struct.pack(
        SOFT_KEYBOARD_FORMAT,
        0,
        0,
        *([0] * SOFT_KEYBOARD_KEY_SLOTS),
    )
    assert payload == expected_payload
    assert state.ctrl == 0
    assert state.keys == [0] * SOFT_KEYBOARD_KEY_SLOTS
