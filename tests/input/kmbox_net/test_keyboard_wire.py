"""
Property test — Task 2.5 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 9: Keyboard wire is HID-only.

**Property 9: Keyboard wire is HID-only**

    *For any* sequence of ``_keydown`` / ``_keyup`` invocations producing
    emitted keyboard UDP packets, every byte in the
    ``soft_keyboard_t.button[0..9]`` field of every emitted packet is in
    ``[0, 255]``; pressing then releasing the same HID code returns the
    buffer to its prior state; modifier keys (HID ``0xE0..0xE7``) toggle
    the correct ``ctrl`` bit and never appear in ``keys[0..9]``.

**Validates: Requirements 5.3, 5.4**

Implementation notes
--------------------

The test exercises the wire-layer triple
``(KeyboardState, keyboard_apply_down/up, PacketBuilder.build_keyboard)``
in isolation — no UDP socket, no driver lifecycle, no encryption. Each
generated sequence of ``(action, hid)`` events is applied to a fresh
:class:`KeyboardState` *and* to a freshly-built packet, so the test
verifies (a) the in-memory buffer transitions defined in
``c++_demo/NetConfig/kmboxNet.cpp:kmNet_keydown``/``kmNet_keyup`` and
(b) that those transitions serialize to a 12-byte ``soft_keyboard_t``
payload whose every byte fits the unsigned-byte HID range.

The three sub-properties below correspond directly to the three
clauses of Property 9 in design.md and are all checked on the same
generated sequence — splitting them keeps Hypothesis shrinkage focused
on the failing clause.
"""

from __future__ import annotations

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

from input.kmbox_net_driver import (
    CMD_KEYBOARD_ALL,
    HID_MODIFIER_BASE,
    HID_MODIFIER_TOP,
    KeyboardState,
    PacketBuilder,
    SOFT_KEYBOARD_FORMAT,
    keyboard_apply_down,
    keyboard_apply_up,
)


# ---------------------------------------------------------------------------
# Wire-format constants
# ---------------------------------------------------------------------------

# 16-byte ``cmd_head_t`` precedes the 12-byte ``soft_keyboard_t`` payload
# (see design.md "Per-command payload encoding" — keyboard plaintext
# packet length = 28 bytes).
_CMD_HEAD_SIZE = 16
_SOFT_KEYBOARD_SIZE = struct.calcsize(SOFT_KEYBOARD_FORMAT)
_KEYBOARD_PACKET_SIZE = _CMD_HEAD_SIZE + _SOFT_KEYBOARD_SIZE
_KEY_SLOTS = 10


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# 32-bit unsigned MAC value — the full input space of
# ``StrToHex(uuid[:8], 4)`` (see ``kmboxNet.cpp:kmNet_init``).
_st_mac = st.integers(min_value=0, max_value=2**32 - 1)

# Full HID code range per Requirement 5.7 — ``_keydown(hid)`` / ``_keyup(hid)``
# accept any integer in ``[0, 255]``. The strategy intentionally covers both
# modifier (``0xE0..0xE7``) and non-modifier codes so a single sequence can
# exercise both branches of ``keyboard_apply_down`` / ``keyboard_apply_up``.
_st_hid = st.integers(min_value=0, max_value=255)

# Strategy emitting an ``("down" | "up", hid)`` event. ``up`` of a key never
# previously pressed is a legal no-op in the upstream code, so we do not
# constrain the generator to "only press what was pressed" — the wire-layer
# property must hold regardless.
_st_event = st.tuples(st.sampled_from(("down", "up")), _st_hid)

# A bounded sequence of events. The 32-event cap keeps each Hypothesis
# example small enough to run quickly while still letting the buffer fill
# (10 slots) and overflow (>10 unique non-modifier presses) so the
# shift-on-overflow path is exercised.
_st_event_seq = st.lists(_st_event, min_size=0, max_size=32)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply(state: KeyboardState, action: str, hid: int) -> None:
    """Dispatch ``action`` to the matching keyboard-state helper."""
    if action == "down":
        keyboard_apply_down(state, hid)
    else:
        keyboard_apply_up(state, hid)


def _emit_packet(builder: PacketBuilder, state: KeyboardState) -> bytes:
    """Build the 28-byte plaintext keyboard packet for ``state``."""
    return builder.build_keyboard(
        builder.next_indexpts(), state.ctrl, list(state.keys)
    )


def _decode_payload(packet: bytes) -> tuple[int, int, tuple[int, ...]]:
    """Return ``(ctrl, resvel, keys)`` from the keyboard payload.

    ``packet`` is the full 28-byte plaintext datagram emitted by
    :meth:`PacketBuilder.build_keyboard`. The first 16 bytes are the
    ``cmd_head_t`` header; the trailing 12 bytes are the
    ``soft_keyboard_t`` payload.
    """
    assert len(packet) == _KEYBOARD_PACKET_SIZE
    fields = struct.unpack(SOFT_KEYBOARD_FORMAT, packet[_CMD_HEAD_SIZE:])
    ctrl = fields[0]
    resvel = fields[1]
    keys = tuple(fields[2:])
    assert len(keys) == _KEY_SLOTS
    return ctrl, resvel, keys


def _decode_cmd(packet: bytes) -> int:
    """Return ``head.cmd`` (offset 12, little-endian uint32)."""
    return struct.unpack("<IIII", packet[:_CMD_HEAD_SIZE])[3]


def _snapshot(state: KeyboardState) -> tuple[int, tuple[int, ...]]:
    """Capture an immutable view of ``state`` for equality comparisons."""
    return state.ctrl, tuple(state.keys)


# ---------------------------------------------------------------------------
# Property 9 — clause A: keyboard wire bytes are unsigned in [0, 255]
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(mac=_st_mac, events=_st_event_seq)
def test_keyboard_wire_bytes_are_in_unsigned_byte_range(
    mac: int, events: list[tuple[str, int]]
) -> None:
    """Every emitted ``soft_keyboard_t`` byte is in ``[0, 255]``.

    The packet uses ``<BB10B`` so this is a structural invariant of
    ``struct.pack`` — but the property must still hold across every
    intermediate state produced by arbitrary down/up sequences,
    including overflow into the 11th key (which shifts the buffer).

    Validates: Requirements 5.3, 5.4.
    """
    builder = PacketBuilder(mac)
    state = KeyboardState()

    # Verify the initial all-zero state encodes correctly.
    packet = _emit_packet(builder, state)
    assert _decode_cmd(packet) == CMD_KEYBOARD_ALL
    ctrl, resvel, keys = _decode_payload(packet)
    assert 0 <= ctrl <= 255
    assert resvel == 0
    assert all(0 <= b <= 255 for b in keys)

    for action, hid in events:
        _apply(state, action, hid)
        packet = _emit_packet(builder, state)

        # Header still identifies the keyboard command.
        assert _decode_cmd(packet) == CMD_KEYBOARD_ALL

        ctrl, resvel, keys = _decode_payload(packet)
        # Unsigned-byte range — the core wire invariant.
        assert 0 <= ctrl <= 255, ctrl
        assert resvel == 0, resvel
        for slot_index, byte_value in enumerate(keys):
            assert 0 <= byte_value <= 255, (slot_index, byte_value)


# ---------------------------------------------------------------------------
# Property 9 — clause B: down(hid) then up(hid) restores prior state
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(prefix=_st_event_seq, hid=_st_hid)
def test_keyboard_press_then_release_restores_state(
    prefix: list[tuple[str, int]], hid: int
) -> None:
    """``keyup(hid)`` after ``keydown(hid)`` returns the buffer to its prior state.

    The invariant holds for every reachable state, including states with
    ``hid`` already held (idempotent press → idempotent release leaves
    the buffer unchanged) and states where the buffer is full
    (overflow-shift on press → release matches the post-shift slot,
    yielding the post-shift buffer rather than the original — see the
    asymmetric branch below).

    Validates: Requirements 5.3, 5.4.
    """
    state = KeyboardState()
    for action, h in prefix:
        _apply(state, action, h)

    is_modifier = HID_MODIFIER_BASE <= hid <= HID_MODIFIER_TOP
    already_held = (
        is_modifier
        and bool(state.ctrl & (1 << (hid - HID_MODIFIER_BASE)))
        or (not is_modifier and hid != 0 and hid in state.keys)
    )
    buffer_full_no_room = (
        not is_modifier
        and hid != 0
        and hid not in state.keys
        and 0 not in state.keys
    )

    before = _snapshot(state)

    keyboard_apply_down(state, hid)
    keyboard_apply_up(state, hid)

    after = _snapshot(state)

    if already_held:
        # ``keydown`` is idempotent for modifiers and held non-modifiers;
        # the matching ``keyup`` then clears them, so the prior state is
        # NOT restored — the key/mod is now released. Verify only the
        # specific clearing.
        if is_modifier:
            mask = 1 << (hid - HID_MODIFIER_BASE)
            assert before[0] & mask, "precondition: modifier was held"
            assert not (after[0] & mask), (
                "release of held modifier should clear its ctrl bit"
            )
            # Non-targeted ctrl bits and the entire key buffer must be
            # untouched.
            assert (before[0] & ~mask) == (after[0] & ~mask)
            assert before[1] == after[1]
        else:
            assert hid in before[1], "precondition: non-modifier was held"
            assert hid not in after[1], (
                "release of held non-modifier should remove it from the buffer"
            )
            # ``ctrl`` is untouched.
            assert before[0] == after[0]
    elif buffer_full_no_room and hid != 0:
        # Overflow-shift on press: the oldest slot is dropped and ``hid``
        # is appended at slot 9. The matching release zeros slot 9, but
        # the dropped slot is gone for good — the original buffer is not
        # restored. Verify the post-shift invariant instead: after the
        # press+release pair the last slot is 0 and slots 0..8 equal
        # ``before[1][1:]``.
        assert after[0] == before[0]
        assert after[1][:-1] == before[1][1:]
        assert after[1][-1] == 0
    else:
        # Press inserted into a free slot (or hid == 0, a no-op for
        # both branches) — release zeros that slot, restoring the prior
        # state byte-for-byte.
        assert after == before, (before, after, hid, is_modifier)


# ---------------------------------------------------------------------------
# Property 9 — clause C: modifier keys touch ctrl only, never keys[0..9]
# ---------------------------------------------------------------------------


# Modifier-only HID strategy for the focused clause-C test.
_st_modifier_hid = st.integers(
    min_value=HID_MODIFIER_BASE, max_value=HID_MODIFIER_TOP
)
_st_modifier_event = st.tuples(
    st.sampled_from(("down", "up")), _st_modifier_hid
)
_st_modifier_seq = st.lists(_st_modifier_event, min_size=0, max_size=16)


@settings(max_examples=200, deadline=None)
@given(mac=_st_mac, events=_st_modifier_seq)
def test_modifier_keys_toggle_ctrl_bit_and_never_enter_key_buffer(
    mac: int, events: list[tuple[str, int]]
) -> None:
    """Modifier keys toggle the matching ``ctrl`` bit; ``keys[0..9]`` stays zero.

    For a sequence consisting *only* of modifier (``0xE0..0xE7``)
    presses and releases, the ``soft_keyboard_t.button[10]`` field must
    remain all-zero across every emitted packet, and ``ctrl`` must
    equal the bitmask predicted by independently tracking the
    modifier set.

    Validates: Requirements 5.3, 5.4.
    """
    builder = PacketBuilder(mac)
    state = KeyboardState()

    # Independent reference model — a plain ``int`` bitmask updated
    # alongside the ``KeyboardState``. If the two diverge, the property
    # fails with a counter-example pointing at the divergent event.
    expected_ctrl = 0

    for action, hid in events:
        _apply(state, action, hid)
        bit = 1 << (hid - HID_MODIFIER_BASE)
        if action == "down":
            expected_ctrl = (expected_ctrl | bit) & 0xFF
        else:
            expected_ctrl = expected_ctrl & (~bit & 0xFF)

        packet = _emit_packet(builder, state)
        ctrl, resvel, keys = _decode_payload(packet)

        assert ctrl == expected_ctrl, (ctrl, expected_ctrl, action, hex(hid))
        # Modifier-only sequences must never write to the key buffer.
        assert keys == tuple([0] * _KEY_SLOTS), keys
        assert resvel == 0


# ---------------------------------------------------------------------------
# Property 9 — clause C (mixed): modifier keys never appear in keys[0..9]
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(mac=_st_mac, events=_st_event_seq)
def test_modifier_codes_never_appear_in_key_buffer(
    mac: int, events: list[tuple[str, int]]
) -> None:
    """No HID code in ``[0xE0, 0xE7]`` ever lands in ``keys[0..9]``.

    Even when the event stream interleaves modifier and non-modifier
    presses (and overflows the 10-slot buffer), the modifier codes
    flow exclusively into ``ctrl`` — they MUST NOT appear in
    ``soft_keyboard_t.button[0..9]`` of any emitted packet.

    Validates: Requirements 5.3, 5.4.
    """
    builder = PacketBuilder(mac)
    state = KeyboardState()

    for action, hid in events:
        _apply(state, action, hid)
        packet = _emit_packet(builder, state)
        _ctrl, _resvel, keys = _decode_payload(packet)

        for slot_index, byte_value in enumerate(keys):
            assert not (
                HID_MODIFIER_BASE <= byte_value <= HID_MODIFIER_TOP
            ), (
                f"modifier HID 0x{byte_value:02x} leaked into keys[{slot_index}] "
                f"after {action} 0x{hid:02x}"
            )
