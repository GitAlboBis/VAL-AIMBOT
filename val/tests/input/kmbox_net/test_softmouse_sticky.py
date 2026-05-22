"""
Property test — Sticky ``softmouse.button`` parity with upstream.

# Feature: kmbox-net-arm64-udp, Property 7-bis: Multi-button sticky state.

**Property 7-bis: ``softmouse.button`` is sticky across builds**

    The :class:`PacketBuilder` mirrors the upstream ``softmouse``
    global state machine in ``c++_demo/NetConfig/kmboxNet.cpp``:
    every ``kmNet_mouse_*`` function updates ``softmouse.button``
    in place and copies the *whole* ``softmouse`` struct (button +
    deltas) into the outgoing packet.

    Concretely, for any sequence of left/right/middle press and
    release events ``e_1, e_2, ..., e_n``, the
    ``soft_mouse_t.button`` field of the *n-th* emitted packet
    equals the bitwise composition that an independent reference
    model — initialized to ``0`` and applying ``OR mask`` on press
    / ``AND ~mask`` on release per the upstream
    ``softmouse.button = (isdown ? (softmouse.button | mask) :
    (softmouse.button & ~mask))`` rule — would yield after the
    same sequence.

    Furthermore, intervening ``build_move`` / ``build_wheel`` /
    ``build_move_auto`` / ``build_move_beizer`` packets carry the
    *same* current ``softmouse.button`` value (they preserve, not
    reset, the sticky state). ``build_mouse_all(btn, ...)``
    overwrites ``softmouse.button`` with ``btn``, matching the
    upstream ``softmouse.button = button`` assignment.

**Validates: Upstream parity for multi-button HID reports.**

This property is *not* in the original spec's correctness list
because the spec mandated a stricter "fresh button per packet"
shape. Cross-checking against the upstream ``kmboxNet.cpp`` (see
github.com/kvmaibox/kmboxnet) revealed that real devices expect
the sticky behaviour for multi-button-hold scenarios (e.g. ADS
right-button held while clicking left to fire). This file
documents and verifies the corrected behaviour.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path
from typing import List, Tuple

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
# Per-event description
# ---------------------------------------------------------------------------
#
# Every event in the generated sequence is a ``(kind, *args)`` tuple. The
# reference model below interprets each tuple identically to the way
# ``_dispatch_call`` would route it through ``PacketBuilder``.

# Mouse button events.
_BUTTON_DEFS = (
    ("left", CMD_MOUSE_LEFT, MOUSE_BUTTON_LEFT_BIT),
    ("right", CMD_MOUSE_RIGHT, MOUSE_BUTTON_RIGHT_BIT),
    ("middle", CMD_MOUSE_MIDDLE, MOUSE_BUTTON_MIDDLE_BIT),
)


@st.composite
def _gen_event(draw) -> tuple:
    """Generate one event in the sequence.

    Possible shapes:
      ``("button", cmd, bit, isdown)`` — ``build_button(cmd, bit, isdown)``
      ``("move", x, y)`` — ``build_move(x, y)``
      ``("wheel", w)`` — ``build_wheel(w)``
      ``("move_auto", x, y, ms)`` — ``build_move_auto(x, y, ms)``
      ``("move_beizer", x, y, ms, x1, y1, x2, y2)``
      ``("mouse_all", btn, x, y, wheel)`` — ``build_mouse_all(...)``
    """
    kind = draw(
        st.sampled_from(
            ["button", "move", "wheel", "move_auto", "move_beizer", "mouse_all"]
        )
    )
    if kind == "button":
        _name, cmd, bit = draw(st.sampled_from(_BUTTON_DEFS))
        isdown = draw(st.integers(min_value=0, max_value=1))
        return ("button", cmd, bit, isdown)
    if kind == "move":
        return ("move", draw(_st_xy), draw(_st_xy))
    if kind == "wheel":
        return ("wheel", draw(_st_wheel_nonzero))
    if kind == "move_auto":
        return ("move_auto", draw(_st_xy), draw(_st_xy), draw(_st_ms))
    if kind == "move_beizer":
        return (
            "move_beizer",
            draw(_st_xy),
            draw(_st_xy),
            draw(_st_ms),
            draw(_st_xy),
            draw(_st_xy),
            draw(_st_xy),
            draw(_st_xy),
        )
    # mouse_all
    return (
        "mouse_all",
        draw(st.integers(min_value=0, max_value=255)),
        draw(_st_xy),
        draw(_st_xy),
        draw(_st_wheel_for_mouse_all),
    )


_st_xy = st.integers(min_value=-32768, max_value=32768)
_st_wheel_nonzero = st.integers(min_value=-128, max_value=128).filter(lambda v: v != 0)
_st_wheel_for_mouse_all = st.integers(min_value=-128, max_value=128)
_st_ms = st.integers(min_value=1, max_value=65535)
_st_mac = st.integers(min_value=0, max_value=2**32 - 1)


# ---------------------------------------------------------------------------
# Reference model — replicates the upstream ``softmouse.button`` semantics
# ---------------------------------------------------------------------------


def _apply_event_reference(state: dict, event: tuple) -> int:
    """Apply ``event`` to the reference state and return expected button byte.

    ``state["button"]`` mirrors ``softmouse.button`` from
    ``c++_demo/NetConfig/kmboxNet.cpp``. Updates follow the
    upstream rules:

      * ``button`` event → ``button = (isdown ? button | bit : button & ~bit)``
        then emit a packet whose ``soft_mouse_t.button`` equals the
        new ``button`` value.
      * ``move`` / ``wheel`` / ``move_auto`` / ``move_beizer`` → leave
        ``button`` unchanged; the emitted packet carries the current
        ``button`` value plus the move/wheel deltas.
      * ``mouse_all(btn, ...)`` → overwrites ``button = btn`` (the
        upstream ``softmouse.button = button`` assignment) and emits
        a packet whose ``soft_mouse_t.button`` equals ``btn``.
    """
    kind = event[0]
    if kind == "button":
        _, _cmd, bit, isdown = event
        if isdown:
            state["button"] = (state["button"] | bit) & 0xFF
        else:
            state["button"] = state["button"] & (~bit & 0xFF)
        return state["button"]
    if kind == "mouse_all":
        _, btn, *_ = event
        state["button"] = btn & 0xFF
        return state["button"]
    # move / wheel / move_auto / move_beizer — preserve sticky state.
    return state["button"]


def _expected_cmd(event: tuple) -> int:
    """Return the ``head.cmd`` the matching builder method emits."""
    kind = event[0]
    if kind == "button":
        return event[1]  # the upstream cmd id
    if kind == "move":
        return CMD_MOUSE_MOVE
    if kind == "wheel":
        return CMD_MOUSE_WHEEL
    if kind == "mouse_all":
        return CMD_MOUSE_WHEEL  # upstream re-uses cmd_mouse_wheel
    if kind == "move_auto":
        return CMD_MOUSE_AUTOMOVE
    return CMD_BAZERMOVE  # move_beizer


def _build_packet(builder: PacketBuilder, event: tuple) -> bytes:
    """Route ``event`` through the matching ``PacketBuilder.build_*`` method."""
    indexpts = builder.next_indexpts()
    kind = event[0]
    if kind == "button":
        _, cmd, bit, isdown = event
        return builder.build_button(indexpts, cmd, bit, isdown)
    if kind == "move":
        _, x, y = event
        return builder.build_move(indexpts, x, y)
    if kind == "wheel":
        _, w = event
        return builder.build_wheel(indexpts, w)
    if kind == "move_auto":
        _, x, y, ms = event
        return builder.build_move_auto(indexpts, x, y, ms)
    if kind == "move_beizer":
        _, x, y, ms, x1, y1, x2, y2 = event
        return builder.build_move_beizer(indexpts, x, y, ms, x1, y1, x2, y2)
    # mouse_all
    _, btn, x, y, w = event
    return builder.build_mouse_all(indexpts, btn, x, y, w)


def _decode_button_field(packet: bytes) -> int:
    """Return ``soft_mouse_t.button`` from a 72-byte mouse-class packet."""
    fields = struct.unpack(SOFT_MOUSE_FORMAT, packet[CMD_HEAD_SIZE:])
    return fields[0]


def _decode_cmd(packet: bytes) -> int:
    """Return ``head.cmd`` from any packet."""
    return struct.unpack(CMD_HEAD_FORMAT, packet[:CMD_HEAD_SIZE])[3]


# ---------------------------------------------------------------------------
# Property 7-bis
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(mac=_st_mac, events=st.lists(_gen_event(), min_size=1, max_size=20))
def test_softmouse_button_is_sticky_against_upstream_reference(
    mac: int, events: List[tuple]
) -> None:
    """``soft_mouse_t.button`` matches the upstream sticky reference model.

    For every event in the generated sequence the test:

      * routes the event through :class:`PacketBuilder` (incrementing
        ``indexpts`` and possibly mutating the sticky button state);
      * applies the same event to an independent reference state
        (a plain ``dict`` initialized to ``button = 0``) using the
        upstream rules;
      * decodes the emitted packet and asserts:

        - ``head.cmd`` matches the expected command identifier; and
        - ``soft_mouse_t.button`` equals the reference's button byte.

    A failure of the second assertion would indicate
    :class:`PacketBuilder` is *not* in lockstep with the upstream
    sticky semantics — exactly the regression we're guarding
    against.
    """
    builder = PacketBuilder(mac)
    state: dict = {"button": 0}

    for index, event in enumerate(events):
        expected_button = _apply_event_reference(state, event)
        packet = _build_packet(builder, event)

        assert len(packet) == CMD_HEAD_SIZE + SOFT_MOUSE_SIZE, (
            f"event {index} ({event}): expected 72-byte packet, "
            f"got {len(packet)}"
        )

        assert _decode_cmd(packet) == _expected_cmd(event), (
            f"event {index} ({event}): head.cmd mismatch "
            f"(got 0x{_decode_cmd(packet):08x}, "
            f"expected 0x{_expected_cmd(event):08x})"
        )

        emitted_button = _decode_button_field(packet)
        assert emitted_button == expected_button, (
            f"event {index} ({event}): sticky button state mismatch. "
            f"Reference state predicts button = 0x{expected_button:02x}, "
            f"but emitted packet has button = 0x{emitted_button:02x}. "
            f"Full event history: {events[:index + 1]}"
        )


def test_multi_button_hold_scenario() -> None:
    """Concrete multi-button scenario from the upstream cross-check.

    Press right (held for ADS in many FPS), then press left (fire).
    The upstream behaviour produces ``button = 0x03`` on the
    left-press packet (both bits set). A regression that resets the
    button field per command would emit ``button = 0x01``, dropping
    the held right-button state.
    """
    builder = PacketBuilder(mac=0x12345678)

    # Press right.
    pkt = builder.build_button(
        builder.next_indexpts(),
        CMD_MOUSE_RIGHT,
        MOUSE_BUTTON_RIGHT_BIT,
        1,
    )
    assert _decode_button_field(pkt) == 0x02

    # Press left while holding right — must produce 0x03.
    pkt = builder.build_button(
        builder.next_indexpts(),
        CMD_MOUSE_LEFT,
        MOUSE_BUTTON_LEFT_BIT,
        1,
    )
    assert _decode_button_field(pkt) == 0x03, (
        "multi-button hold: pressing left while right is held must "
        f"produce button=0x03; got 0x{_decode_button_field(pkt):02x}"
    )

    # Move while both held — packet must still carry button=0x03.
    pkt = builder.build_move(builder.next_indexpts(), 10, -5)
    assert _decode_button_field(pkt) == 0x03, (
        "move during multi-button hold must preserve sticky button "
        f"state; got 0x{_decode_button_field(pkt):02x}"
    )

    # Release left — right still held.
    pkt = builder.build_button(
        builder.next_indexpts(),
        CMD_MOUSE_LEFT,
        MOUSE_BUTTON_LEFT_BIT,
        0,
    )
    assert _decode_button_field(pkt) == 0x02, (
        "releasing left while right is held must yield button=0x02; "
        f"got 0x{_decode_button_field(pkt):02x}"
    )

    # Release right — fully clear.
    pkt = builder.build_button(
        builder.next_indexpts(),
        CMD_MOUSE_RIGHT,
        MOUSE_BUTTON_RIGHT_BIT,
        0,
    )
    assert _decode_button_field(pkt) == 0x00
