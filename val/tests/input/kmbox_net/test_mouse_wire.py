"""
Property test — Task 2.3 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 7 (mouse subset):
#   Per-command round-trip encoding.

**Property 7 (mouse subset): Per-command round-trip encoding**

    *For each* mouse command in
    ``{move, left, right, middle, wheel, mouse, move_auto, move_beizer}``,
    given valid arguments produced by the design's ``valid_xy``,
    ``valid_wheel``, ``valid_btn``, ``valid_ms`` Hypothesis strategies,
    the bytes produced by ``PacketBuilder.build_*`` SHALL satisfy:

    1. ``struct.unpack('<IIII', b[:16])[3]`` equals the documented
       ``cmd`` identifier for that command (cf. design.md "Command
       Identifier Table").
    2. The decoded ``soft_mouse_t`` fields equal the inputs (cf.
       design.md "Per-command payload encoding").
    3. The ``head.rand`` encoding matches the table — *random* for the
       click / move / wheel / mouse commands, ``ms`` for
       ``_move_auto``, ``ms`` for ``_move_beizer``.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.6, 4.7**

Implementation notes
--------------------

The 14 ``CMD_*`` identifiers, the ``cmd_head_t`` and ``soft_mouse_t``
layouts, and the per-command payload encoding are all documented in
``c++_demo/NetConfig/kmboxNet.h`` and ``c++_demo/NetConfig/kmboxNet.cpp``
of https://github.com/kvmaibox/kmboxnet (Protocol Sources entries 1
and 2 in design.md). Each ``build_*`` method on
:class:`~input.kmbox_net_driver.PacketBuilder` mirrors a single
``kmNet_*`` function in the upstream source and writes the same
little-endian byte layout the firmware expects.

This test is purely on the wire layer — no socket, no encryption, no
driver instance. It exercises the round-trip
``args → bytes → struct.unpack → args`` so any future regression in
either the field order or the rand encoding fails fast.

Note on ``build_mouse_all``: per design.md Conflict Log entry 3 the
upstream ``kmNet_mouse_all`` re-uses ``cmd_mouse_wheel`` as its command
identifier rather than declaring a dedicated one. The test asserts that
exact behaviour (``head.cmd == CMD_MOUSE_WHEEL`` for the combined send).
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path
from typing import Tuple

# Make the ``input`` package importable when pytest is launched from the
# repository root or any sub-directory. The driver ships as
# ``input/kmbox_net_driver.py`` at the project root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hypothesis import given, settings
from hypothesis import strategies as st

from input.kmbox_net_driver import (
    CMD_BAZERMOVE,
    CMD_HEAD_FORMAT,
    CMD_HEAD_SIZE,
    CMD_MOUSE_AUTOMOVE,
    CMD_MOUSE_LEFT,
    CMD_MOUSE_MIDDLE,
    CMD_MOUSE_MOVE,
    CMD_MOUSE_RIGHT,
    CMD_MOUSE_WHEEL,
    MOUSE_BUTTON_LEFT_BIT,
    MOUSE_BUTTON_MIDDLE_BIT,
    MOUSE_BUTTON_RIGHT_BIT,
    SOFT_MOUSE_FORMAT,
    SOFT_MOUSE_SIZE,
    PacketBuilder,
)


# ---------------------------------------------------------------------------
# Strategies — match the ones declared in design.md "Testing Strategy"
# ---------------------------------------------------------------------------

#: ``valid_xy`` per design.md — tuples of signed mouse deltas in
#: ``[-32768, 32768]``.
valid_xy = st.tuples(
    st.integers(min_value=-32768, max_value=32768),
    st.integers(min_value=-32768, max_value=32768),
)

#: ``valid_wheel`` per design.md — non-zero signed wheel ticks in
#: ``[-128, 128]``. (``_wheel`` rejects ``0`` per Requirement 4.10, so
#: the strategy mirrors that.)
valid_wheel = st.integers(min_value=-128, max_value=128).filter(lambda v: v != 0)

#: ``valid_btn`` per design.md — button bitmask in ``[0, 255]``.
valid_btn = st.integers(min_value=0, max_value=255)

#: ``valid_ms`` per design.md — duration in milliseconds in ``[1, 65535]``.
valid_ms = st.integers(min_value=1, max_value=65535)

#: 32-bit ``head.indexpts`` counter — the builder accepts any
#: ``uint32`` for this field, so the property exercises the full range.
valid_indexpts = st.integers(min_value=0, max_value=2**32 - 1)

#: 32-bit MAC value passed to :class:`PacketBuilder` — produced by
#: ``StrToHex(uuid[:8], 4)`` in ``kmboxNet.cpp:kmNet_init``.
valid_mac = st.integers(min_value=0, max_value=2**32 - 1)

#: ``isdown`` flag for ``_left/_right/_middle`` — exactly the integer
#: ``0`` (release) or ``1`` (press) per Requirement 4.2.
valid_isdown = st.sampled_from((0, 1))


# ---------------------------------------------------------------------------
# Helpers — header / payload decoders
# ---------------------------------------------------------------------------


def _decode_header(packet: bytes) -> Tuple[int, int, int, int]:
    """Decode the 16-byte ``cmd_head_t`` prefix into ``(mac, rand, indexpts, cmd)``."""
    assert len(packet) >= CMD_HEAD_SIZE, (
        f"packet too short to contain cmd_head_t: {len(packet)} bytes"
    )
    return struct.unpack(CMD_HEAD_FORMAT, packet[:CMD_HEAD_SIZE])


def _decode_soft_mouse(
    packet: bytes,
) -> Tuple[int, int, int, int, Tuple[int, ...]]:
    """Decode the 56-byte ``soft_mouse_t`` payload after the header.

    Returns ``(button, x, y, wheel, point[10])``.
    """
    expected = CMD_HEAD_SIZE + SOFT_MOUSE_SIZE
    assert len(packet) == expected, (
        f"mouse-class packet must be exactly {expected} bytes "
        f"(header + soft_mouse_t); got {len(packet)}"
    )
    fields = struct.unpack(
        SOFT_MOUSE_FORMAT, packet[CMD_HEAD_SIZE:expected]
    )
    button, x, y, wheel = fields[:4]
    points = tuple(fields[4:])
    return button, x, y, wheel, points


# ---------------------------------------------------------------------------
# Property 7 (mouse subset): round-trip encoding per command
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(mac=valid_mac, indexpts=valid_indexpts, xy=valid_xy)
def test_round_trip_move(mac: int, indexpts: int, xy: Tuple[int, int]) -> None:
    """``build_move`` round-trip — Property 7, ``move`` slice.

    Validates: Requirements 4.1.
    """
    x, y = xy
    builder = PacketBuilder(mac)
    packet = builder.build_move(indexpts, x, y)

    head_mac, head_rand, head_indexpts, head_cmd = _decode_header(packet)
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)
    assert head_cmd == CMD_MOUSE_MOVE
    # ``rand`` is the obfuscation field — any 32-bit unsigned value is
    # admissible per the per-command table ("random()" for ``_move``).
    assert 0 <= head_rand <= 0xFFFFFFFF

    button, dx, dy, wheel, points = _decode_soft_mouse(packet)
    assert button == 0
    assert dx == x
    assert dy == y
    assert wheel == 0
    assert points == (0,) * 10


@settings(max_examples=200, deadline=None)
@given(mac=valid_mac, indexpts=valid_indexpts, isdown=valid_isdown)
def test_round_trip_left(mac: int, indexpts: int, isdown: int) -> None:
    """``build_button`` round-trip for the left button — Property 7,
    ``left`` slice.

    Validates: Requirements 4.2.
    """
    builder = PacketBuilder(mac)
    button_mask = MOUSE_BUTTON_LEFT_BIT if isdown == 1 else 0
    packet = builder.build_button(indexpts, CMD_MOUSE_LEFT, MOUSE_BUTTON_LEFT_BIT, isdown)

    head_mac, head_rand, head_indexpts, head_cmd = _decode_header(packet)
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)
    assert head_cmd == CMD_MOUSE_LEFT
    assert 0 <= head_rand <= 0xFFFFFFFF

    button, x, y, wheel, points = _decode_soft_mouse(packet)
    assert button == button_mask
    # ``button & 0x01`` reflects the ``isdown`` flag per Requirement 4.2
    # ("isdown == 1 denotes press, isdown == 0 denotes release").
    assert (button & MOUSE_BUTTON_LEFT_BIT) == (isdown & 0x01)
    assert x == 0
    assert y == 0
    assert wheel == 0
    assert points == (0,) * 10


@settings(max_examples=200, deadline=None)
@given(mac=valid_mac, indexpts=valid_indexpts, isdown=valid_isdown)
def test_round_trip_right(mac: int, indexpts: int, isdown: int) -> None:
    """``build_button`` round-trip for the right button — Property 7,
    ``right`` slice.

    Validates: Requirements 4.2.
    """
    builder = PacketBuilder(mac)
    button_mask = MOUSE_BUTTON_RIGHT_BIT if isdown == 1 else 0
    packet = builder.build_button(indexpts, CMD_MOUSE_RIGHT, MOUSE_BUTTON_RIGHT_BIT, isdown)

    head_mac, head_rand, head_indexpts, head_cmd = _decode_header(packet)
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)
    assert head_cmd == CMD_MOUSE_RIGHT
    assert 0 <= head_rand <= 0xFFFFFFFF

    button, x, y, wheel, points = _decode_soft_mouse(packet)
    assert button == button_mask
    assert (button & MOUSE_BUTTON_RIGHT_BIT) == (
        (isdown & 0x01) * MOUSE_BUTTON_RIGHT_BIT
    )
    assert x == 0
    assert y == 0
    assert wheel == 0
    assert points == (0,) * 10


@settings(max_examples=200, deadline=None)
@given(mac=valid_mac, indexpts=valid_indexpts, isdown=valid_isdown)
def test_round_trip_middle(mac: int, indexpts: int, isdown: int) -> None:
    """``build_button`` round-trip for the middle button — Property 7,
    ``middle`` slice.

    Validates: Requirements 4.2.
    """
    builder = PacketBuilder(mac)
    button_mask = MOUSE_BUTTON_MIDDLE_BIT if isdown == 1 else 0
    packet = builder.build_button(indexpts, CMD_MOUSE_MIDDLE, MOUSE_BUTTON_MIDDLE_BIT, isdown)

    head_mac, head_rand, head_indexpts, head_cmd = _decode_header(packet)
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)
    assert head_cmd == CMD_MOUSE_MIDDLE
    assert 0 <= head_rand <= 0xFFFFFFFF

    button, x, y, wheel, points = _decode_soft_mouse(packet)
    assert button == button_mask
    assert (button & MOUSE_BUTTON_MIDDLE_BIT) == (
        (isdown & 0x01) * MOUSE_BUTTON_MIDDLE_BIT
    )
    assert x == 0
    assert y == 0
    assert wheel == 0
    assert points == (0,) * 10


@settings(max_examples=200, deadline=None)
@given(mac=valid_mac, indexpts=valid_indexpts, wheel=valid_wheel)
def test_round_trip_wheel(mac: int, indexpts: int, wheel: int) -> None:
    """``build_wheel`` round-trip — Property 7, ``wheel`` slice.

    Validates: Requirements 4.3.
    """
    builder = PacketBuilder(mac)
    packet = builder.build_wheel(indexpts, wheel)

    head_mac, head_rand, head_indexpts, head_cmd = _decode_header(packet)
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)
    assert head_cmd == CMD_MOUSE_WHEEL
    assert 0 <= head_rand <= 0xFFFFFFFF

    button, x, y, w, points = _decode_soft_mouse(packet)
    assert button == 0
    assert x == 0
    assert y == 0
    assert w == wheel
    assert points == (0,) * 10


@settings(max_examples=200, deadline=None)
@given(
    mac=valid_mac,
    indexpts=valid_indexpts,
    btn=valid_btn,
    xy=valid_xy,
    wheel=valid_wheel,
)
def test_round_trip_mouse(
    mac: int,
    indexpts: int,
    btn: int,
    xy: Tuple[int, int],
    wheel: int,
) -> None:
    """``build_mouse_all`` round-trip — Property 7, ``mouse`` slice.

    Per design.md Conflict Log entry 3 the upstream ``kmNet_mouse_all``
    re-uses ``cmd_mouse_wheel`` as its command identifier, so the
    expected ``head.cmd`` is :data:`CMD_MOUSE_WHEEL` even though the
    builder method is named ``build_mouse_all``.

    Validates: Requirements 4.4.
    """
    x, y = xy
    builder = PacketBuilder(mac)
    packet = builder.build_mouse_all(indexpts, btn, x, y, wheel)

    head_mac, head_rand, head_indexpts, head_cmd = _decode_header(packet)
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)
    # Upstream re-uses cmd_mouse_wheel for kmNet_mouse_all (design
    # Conflict Log entry 3) — the test asserts that exact behaviour.
    assert head_cmd == CMD_MOUSE_WHEEL
    assert 0 <= head_rand <= 0xFFFFFFFF

    button, dx, dy, w, points = _decode_soft_mouse(packet)
    assert button == btn
    assert dx == x
    assert dy == y
    assert w == wheel
    assert points == (0,) * 10


@settings(max_examples=200, deadline=None)
@given(
    mac=valid_mac,
    indexpts=valid_indexpts,
    xy=valid_xy,
    ms=valid_ms,
)
def test_round_trip_move_auto(
    mac: int, indexpts: int, xy: Tuple[int, int], ms: int
) -> None:
    """``build_move_auto`` round-trip — Property 7, ``move_auto`` slice.

    Unlike the click / move / wheel / mouse commands, ``head.rand``
    encodes the duration ``ms`` (per ``kmboxNet.cpp:kmNet_mouse_move_auto``
    sets ``tx.head.rand = ms``).

    Validates: Requirements 4.6.
    """
    x, y = xy
    builder = PacketBuilder(mac)
    packet = builder.build_move_auto(indexpts, x, y, ms)

    head_mac, head_rand, head_indexpts, head_cmd = _decode_header(packet)
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)
    assert head_cmd == CMD_MOUSE_AUTOMOVE
    # Per the per-command table: ``head.rand == ms`` for ``_move_auto``.
    assert head_rand == (ms & 0xFFFFFFFF)

    button, dx, dy, wheel, points = _decode_soft_mouse(packet)
    assert button == 0
    assert dx == x
    assert dy == y
    assert wheel == 0
    assert points == (0,) * 10


@settings(max_examples=200, deadline=None)
@given(
    mac=valid_mac,
    indexpts=valid_indexpts,
    xy=valid_xy,
    ms=valid_ms,
    p1=valid_xy,
    p2=valid_xy,
)
def test_round_trip_move_beizer(
    mac: int,
    indexpts: int,
    xy: Tuple[int, int],
    ms: int,
    p1: Tuple[int, int],
    p2: Tuple[int, int],
) -> None:
    """``build_move_beizer`` round-trip — Property 7, ``move_beizer`` slice.

    Like ``move_auto``, ``head.rand`` carries the duration ``ms``. The
    two control points populate ``soft_mouse_t.point[0..3]`` as
    ``(x1, y1, x2, y2)`` describing a second-order Bézier curve. The
    upstream typo ``cmd_bazerMove`` is preserved per Requirement 4.8.

    Validates: Requirements 4.7.
    """
    x, y = xy
    x1, y1 = p1
    x2, y2 = p2
    builder = PacketBuilder(mac)
    packet = builder.build_move_beizer(indexpts, x, y, ms, x1, y1, x2, y2)

    head_mac, head_rand, head_indexpts, head_cmd = _decode_header(packet)
    assert head_mac == (mac & 0xFFFFFFFF)
    assert head_indexpts == (indexpts & 0xFFFFFFFF)
    assert head_cmd == CMD_BAZERMOVE
    # Per the per-command table: ``head.rand == ms`` for ``_move_beizer``.
    assert head_rand == (ms & 0xFFFFFFFF)

    button, dx, dy, wheel, points = _decode_soft_mouse(packet)
    assert button == 0
    assert dx == x
    assert dy == y
    assert wheel == 0
    # Only point[0..3] carry the two control coordinates; remaining
    # slots stay zeroed.
    assert points[0] == x1
    assert points[1] == y1
    assert points[2] == x2
    assert points[3] == y2
    assert points[4:] == (0,) * 6
