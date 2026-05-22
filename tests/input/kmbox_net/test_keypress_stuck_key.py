"""
Property test — Task 8.7 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 10: ``key_press`` stuck-key safety.

**Property 10: ``key_press`` stuck-key safety**

    *For any* ``(vk_code, hold_ms)`` such that ``_vk_to_hid(vk_code)`` is
    defined and ``hold_ms ∈ [0, 5000]``, *for any* fault injected at the
    wait step (``time.sleep`` raising) or at the keyup transmission step
    (``FakeUdpSocket.sendto`` raising on the keyup call), exactly one
    keyup UDP packet for ``_vk_to_hid(vk_code)`` is emitted before the
    injected exception propagates (or — when the fault is absorbed by
    the dispatch chain per Requirement 1.8 — before ``key_press``
    returns to its caller).

**Validates: Requirements 5.8**

Implementation notes
--------------------

The property has two distinct fault-injection points:

1. **Wait-step fault** — ``time.sleep(hold_ms / 1000)`` inside
   :meth:`KmBoxNetDriver.key_press` raises a custom exception. The
   keydown packet has already been emitted at this point; the
   ``try/finally`` block in ``key_press`` MUST still emit the matching
   keyup packet (so the device's HID buffer returns to empty, satisfying
   the "stuck-key safety" name) and then re-raise the original
   ``time.sleep`` exception.

2. **Keyup-transmission fault** — ``FakeUdpSocket.sendto`` raises
   ``OSError`` on the third call (handshake = 1, keydown = 2,
   keyup = 3). ``_dispatch_call`` catches the ``OSError`` per
   Requirement 1.8 and returns ``None`` to ``key_press`` — so no
   exception propagates *out* of ``key_press``. The property in this
   branch reduces to: the keyup transmission attempt was made
   (exactly one ``sendto`` call carrying the matching HID code in the
   keyup-released wire shape), and ``key_press`` did not crash.

Both branches share the same observable: exactly one *keyup* attempt
on the wire for the HID code translated from ``vk_code``. A
:class:`_CountingFakeUdpSocket` records every ``sendto`` invocation —
including the one that raised — so the wait-step branch and the
keyup-transmission branch can be asserted with one shared decoder.

Encryption is disabled (``use_encryption=False``) so packets are the
plaintext keyboard wire layout (28 B = 16 B ``cmd_head_t`` + 12 B
``soft_keyboard_t``); this lets the test decode each packet directly
without round-tripping through ``PacketEncryptor``.

The driver imports ``time`` at module scope (``import time``) and
calls ``time.sleep(hold_ms / 1000)`` inside ``key_press``. The wait-
step fault is injected by replacing the ``time`` attribute on the
:mod:`input.kmbox_net_driver` module with a small proxy that raises a
deterministic exception from its ``sleep`` method. The original
attribute is restored in a ``finally`` block so a failing example
cannot leak the proxy into a sibling test.
"""

from __future__ import annotations

import logging
import socket as _stdlib_socket
import struct
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# Make the ``input`` package importable when pytest is launched from any
# sub-directory. The driver ships as ``input/kmbox_net_driver.py`` at
# the project root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from input import kmbox_net_driver  # noqa: E402  — for ``.time`` patch
from input.kmbox_net_driver import (  # noqa: E402
    CMD_KEYBOARD_ALL,
    HID_MODIFIER_BASE,
    HID_MODIFIER_TOP,
    ConnectionStatus,
    KmBoxNetDriver,
    SOFT_KEYBOARD_FORMAT,
    _VK_TO_HID_TABLE,
)
from tests.input.kmbox_net.conftest import (  # noqa: E402
    FakeDevice,
    FakeUdpSocket,
)


# ---------------------------------------------------------------------------
# Wire-format constants
# ---------------------------------------------------------------------------

_CMD_HEAD_SIZE = 16
_SOFT_KEYBOARD_SIZE = struct.calcsize(SOFT_KEYBOARD_FORMAT)
_KEYBOARD_PACKET_SIZE = _CMD_HEAD_SIZE + _SOFT_KEYBOARD_SIZE  # 28
_KEY_SLOTS = 10


# ---------------------------------------------------------------------------
# CountingFakeUdpSocket — records every sendto invocation, including those
# that raise. ``FakeUdpSocket.sent`` only records *successful* sends; for
# the keyup-transmission-fault branch we need to observe the *attempt* so
# the wait-step and keyup-transmission branches share a uniform observable.
# ---------------------------------------------------------------------------


class _CountingFakeUdpSocket(FakeUdpSocket):
    """A :class:`FakeUdpSocket` that records every ``sendto`` invocation.

    ``self.attempts`` stores ``(payload, addr)`` tuples for *every* call
    to ``sendto`` — both successful sends (which also append to
    ``self.sent``) and calls that raised because ``raise_on_send`` was
    set. The keyup-transmission fault path needs this distinction
    because :meth:`KmBoxNetDriver._dispatch_call` catches the
    ``OSError`` from ``sendto`` per Requirement 1.8 and the keyup
    packet never reaches ``self.sent``.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # All ``sendto`` invocations, recorded *before* the raise check.
        self.attempts: List[Tuple[bytes, Tuple[str, int]]] = []

    def sendto(self, payload: bytes, addr: Tuple[str, int]) -> int:  # type: ignore[override]
        # Record the attempt before any raise so the test can observe a
        # keyup attempt that ``_dispatch_call`` then absorbed.
        self.attempts.append((bytes(payload), addr))
        return super().sendto(payload, addr)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


# Only VK codes that have a mapping — Property 10 explicitly conditions on
# ``_vk_to_hid(vk_code)`` being defined, so we sample directly from the
# table's keys. This keeps every example exercising the success path of
# vk-validation, leaving the fault injection as the sole stress vector.
_st_mapped_vk = st.sampled_from(sorted(_VK_TO_HID_TABLE.keys()))

# Hold duration — strict ``int`` in ``[0, 5000]`` per Requirement 5.5.
# The clock is replaced with a no-op ``sleep`` for the wait-step branch
# (so the wall-clock wait collapses to instantaneous regardless of value)
# and is left untouched on the keyup-transmission branch (where the
# ``hold_ms`` value still exercises the success path of ``time.sleep``).
# We use a small bound on the upper end of the strategy ONLY to keep
# CI runtime predictable for the keyup-transmission branch (which calls
# the real ``time.sleep`` for very brief intervals); the wait-step
# branch uses the full 0..5000 range via ``draw``.
_st_hold_ms_full = st.integers(min_value=0, max_value=5000)
# Bounded hold so the keyup-transmission branch's real ``time.sleep``
# call stays under 5 ms per example. ``time.sleep(0.005)`` × 100 examples
# ≈ 0.5 s, comfortably below Hypothesis' default deadline.
_st_hold_ms_short = st.integers(min_value=0, max_value=5)

# Realistic UDP errnos — same selection as Property 2's test, kept here
# so a counter-example points at a recognisable transmission failure
# rather than a stray integer.
_st_errno = st.sampled_from([11, 90, 101, 105, 113])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decode_keyboard_packet(packet: bytes) -> Tuple[int, int, int, Tuple[int, ...]]:
    """Return ``(cmd, ctrl, resvel, keys)`` from a 28-byte plaintext packet.

    The header ``cmd`` field is at offset 12 (last uint32 of the
    little-endian ``<IIII`` ``cmd_head_t``). The 12-byte
    ``soft_keyboard_t`` payload follows: ``<BB10B`` = ``ctrl``,
    ``resvel``, ``keys[10]``.
    """
    if len(packet) != _KEYBOARD_PACKET_SIZE:
        raise AssertionError(
            f"expected {_KEYBOARD_PACKET_SIZE}-byte plaintext keyboard packet, "
            f"got {len(packet)} bytes"
        )
    cmd = struct.unpack("<IIII", packet[:_CMD_HEAD_SIZE])[3]
    ctrl, resvel, *keys = struct.unpack(
        SOFT_KEYBOARD_FORMAT, packet[_CMD_HEAD_SIZE:]
    )
    if len(keys) != _KEY_SLOTS:
        raise AssertionError(
            f"expected {_KEY_SLOTS}-slot key buffer, got {len(keys)} slots"
        )
    return cmd, ctrl, resvel, tuple(keys)


def _is_keyboard_packet(packet: bytes) -> bool:
    """``True`` iff ``packet`` is a 28-byte plaintext keyboard datagram."""
    if len(packet) != _KEYBOARD_PACKET_SIZE:
        return False
    cmd = struct.unpack("<IIII", packet[:_CMD_HEAD_SIZE])[3]
    return cmd == CMD_KEYBOARD_ALL


def _is_pressed_for_hid(ctrl: int, keys: Tuple[int, ...], hid: int) -> bool:
    """``True`` iff the keyboard state encodes ``hid`` as currently held."""
    if HID_MODIFIER_BASE <= hid <= HID_MODIFIER_TOP:
        return bool(ctrl & (1 << (hid - HID_MODIFIER_BASE)))
    return hid in keys


def _is_released(ctrl: int, keys: Tuple[int, ...]) -> bool:
    """``True`` iff the keyboard state is fully empty (no key/modifier held)."""
    return ctrl == 0 and all(k == 0 for k in keys)


def _build_connected_driver() -> Tuple[KmBoxNetDriver, _CountingFakeUdpSocket]:
    """Construct a connected ``KmBoxNetDriver`` against a counting fake socket.

    Mirrors the harness in ``test_dispatch_oserror_isolation.py`` but
    substitutes :class:`_CountingFakeUdpSocket` so the test can observe
    every ``sendto`` invocation, including those whose ``sendto`` raised.
    Encryption is disabled so the wire bytes are the plaintext layout
    decodable by :func:`_decode_keyboard_packet`.
    """
    sockets: list[_CountingFakeUdpSocket] = []
    device = FakeDevice(outcome=FakeDevice.HandshakeOutcome.SUCCESS)

    def _factory(family: int = _stdlib_socket.AF_INET,
                 type_: int = _stdlib_socket.SOCK_DGRAM,
                 proto: int = 0,
                 fileno: Optional[int] = None,
                 **_kwargs) -> _CountingFakeUdpSocket:
        sock = _CountingFakeUdpSocket(family=family, type_=type_)
        sock.proto = proto
        sockets.append(sock)
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


class _SleepInjectingTime:
    """Module proxy that raises from ``sleep`` and otherwise delegates to ``time``.

    The driver calls ``time.sleep(hold_ms / 1000)`` inside ``key_press``;
    the wait-step fault branch needs that single call to raise a
    deterministic exception. Replacing the entire ``time`` attribute on
    :mod:`input.kmbox_net_driver` (rather than mutating the global
    ``time.sleep`` itself) keeps the patch local — sibling tests that
    import the real ``time`` module are unaffected.

    Every other attribute access (``time.monotonic``, ``time.time``,
    ``time.perf_counter``, …) flows through to the original module so
    code paths that read the wall clock during the test (e.g. log
    timestamps) still see real time.
    """

    def __init__(self, original_time, exception: BaseException) -> None:
        self._orig = original_time
        self._exception = exception
        self.sleep_calls: List[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(float(seconds))
        # Re-raise the same instance — Python promotes
        # ``__traceback__`` correctly; the test only inspects the type.
        raise self._exception

    def __getattr__(self, name: str):
        return getattr(self._orig, name)


class _ListHandler(logging.Handler):
    """Captures ERROR-level log records emitted on the driver logger."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def clear(self) -> None:
        self.records.clear()


# ---------------------------------------------------------------------------
# Property 10 — branch A: fault at the wait step
# ---------------------------------------------------------------------------


@settings(max_examples=80, deadline=None)
@given(vk_code=_st_mapped_vk, hold_ms=_st_hold_ms_full)
def test_keypress_emits_keyup_when_sleep_raises(
    vk_code: int, hold_ms: int
) -> None:
    """Wait-step fault: ``time.sleep`` raises → keyup still emitted, then re-raise.

    Sequence under test:

        1. ``key_press(vk_code, hold_ms)`` validates inputs (both pass —
           ``vk_code`` is sampled from ``_VK_TO_HID_TABLE`` and
           ``hold_ms`` is in ``[0, 5000]``).
        2. ``_keydown(hid)`` emits the first keyboard packet (the
           "press" — non-zero state in ``ctrl`` or ``keys[0]``).
        3. ``time.sleep(hold_ms / 1000)`` — this is the injected fault
           point. The proxy installed by the test raises a
           ``RuntimeError`` instance; the ``try`` block in ``key_press``
           propagates the exception to its ``finally`` clause.
        4. ``finally:`` ``_keyup(hid)`` emits the second keyboard packet
           (the "release" — fully-zero state).
        5. The original ``RuntimeError`` from step 3 propagates out of
           ``key_press`` to the test.

    Validates: Requirements 5.8.
    """
    driver, fake_sock = _build_connected_driver()
    assert driver.connection_status == ConnectionStatus.CONNECTED, (
        "test pre-condition: handshake must succeed so key_press is "
        "not gated out by the status check; got %r"
        % (driver.connection_status,)
    )
    # Snapshot post-handshake counters so the test asserts on what
    # ``key_press`` adds, not on the handshake itself.
    handshake_attempts = len(fake_sock.attempts)
    handshake_sent = len(fake_sock.sent)
    assert handshake_attempts == 1 and handshake_sent == 1, (
        "test pre-condition: exactly one handshake packet expected; "
        "got attempts=%d sent=%d"
        % (handshake_attempts, handshake_sent)
    )

    hid = _VK_TO_HID_TABLE[vk_code]
    sentinel_exception = RuntimeError(
        f"injected wait-step fault for vk=0x{vk_code:02x} hid=0x{hid:02x}"
    )
    proxy = _SleepInjectingTime(kmbox_net_driver.time, sentinel_exception)

    # Replace the ``time`` attribute on the driver module so
    # ``time.sleep(...)`` inside ``key_press`` resolves to the proxy.
    # Restoration in ``finally`` is mandatory — a leak would crash every
    # subsequent test in this process by raising from every ``time.sleep``.
    original_time = kmbox_net_driver.time
    kmbox_net_driver.time = proxy
    try:
        try:
            driver.key_press(vk_code, hold_ms)
        except RuntimeError as exc:
            propagated = exc
        else:
            raise AssertionError(
                "key_press did NOT propagate the injected wait-step "
                "exception — Requirement 5.8 says the original exception "
                "MUST propagate after the keyup is emitted "
                f"(vk_code=0x{vk_code:02x}, hold_ms={hold_ms})"
            )
    finally:
        kmbox_net_driver.time = original_time

    # The propagated exception is the *same* instance the proxy raised —
    # Python preserves identity on re-raise.
    assert propagated is sentinel_exception, (
        "key_press propagated a different exception than the one "
        f"injected at the wait step: got {propagated!r}"
    )

    # The proxy's ``sleep`` was invoked exactly once with the requested
    # duration (in seconds), and the requested duration matches the
    # ``hold_ms / 1000`` formula in the driver.
    assert len(proxy.sleep_calls) == 1, (
        "expected exactly one time.sleep call from key_press; got "
        f"{len(proxy.sleep_calls)} ({proxy.sleep_calls!r})"
    )
    expected_sleep_seconds = hold_ms / 1000
    assert proxy.sleep_calls[0] == expected_sleep_seconds, (
        "key_press passed an unexpected duration to time.sleep: "
        f"got {proxy.sleep_calls[0]!r}, expected {expected_sleep_seconds!r}"
    )

    # Exactly two keyboard packets reached the wire: keydown then keyup.
    new_attempts = fake_sock.attempts[handshake_attempts:]
    new_sent = fake_sock.sent[handshake_sent:]
    assert len(new_attempts) == 2, (
        "expected exactly two sendto attempts from key_press "
        f"(keydown + keyup); got {len(new_attempts)}"
    )
    assert len(new_sent) == 2, (
        "expected exactly two packets recorded on the wire from "
        f"key_press (keydown + keyup); got {len(new_sent)} — "
        "the wait-step fault must NOT prevent the keyup from being "
        "emitted (Requirement 5.8 stuck-key safety)"
    )

    keydown_packet, _ = new_sent[0]
    keyup_packet, _ = new_sent[1]
    assert _is_keyboard_packet(keydown_packet), (
        "first emitted packet is not a keyboard datagram: "
        f"len={len(keydown_packet)}, head_cmd=0x{struct.unpack('<IIII', keydown_packet[:16])[3]:08x}"
    )
    assert _is_keyboard_packet(keyup_packet), (
        "second emitted packet is not a keyboard datagram: "
        f"len={len(keyup_packet)}, head_cmd=0x{struct.unpack('<IIII', keyup_packet[:16])[3]:08x}"
    )

    # The keydown packet encodes the HID as held; the keyup packet
    # encodes the empty state (matching Property 9 clause B —
    # ``keydown(hid)`` followed by ``keyup(hid)`` from a clean state
    # restores the empty buffer).
    _, keydown_ctrl, _, keydown_keys = _decode_keyboard_packet(keydown_packet)
    _, keyup_ctrl, _, keyup_keys = _decode_keyboard_packet(keyup_packet)

    assert _is_pressed_for_hid(keydown_ctrl, keydown_keys, hid), (
        f"keydown packet does not encode hid=0x{hid:02x} as held: "
        f"ctrl=0x{keydown_ctrl:02x}, keys={keydown_keys}"
    )
    assert _is_released(keyup_ctrl, keyup_keys), (
        "keyup packet must encode the fully-released state (ctrl=0, "
        f"keys=all zero); got ctrl=0x{keyup_ctrl:02x}, keys={keyup_keys}"
    )

    # Driver is left in a recoverable state — the wait-step fault is
    # caller-visible (it propagated) but the transport invariants from
    # Requirement 1.8 still hold: socket open, status unchanged.
    assert driver.connection_status == ConnectionStatus.CONNECTED
    assert driver.initialized is True
    assert fake_sock.closed is False


# ---------------------------------------------------------------------------
# Property 10 — branch B: fault at the keyup transmission step
# ---------------------------------------------------------------------------


@settings(max_examples=80, deadline=None)
@given(vk_code=_st_mapped_vk, hold_ms=_st_hold_ms_short, errno_value=_st_errno)
def test_keypress_attempts_keyup_when_keyup_sendto_raises(
    vk_code: int, hold_ms: int, errno_value: int
) -> None:
    """Keyup-transmission fault: ``sendto`` raises ``OSError`` on the keyup call.

    Per Requirement 1.8 ``_dispatch_call`` absorbs the ``OSError``,
    logs once, and returns ``None`` — so no exception propagates out
    of ``key_press``. The "stuck-key safety" property in this branch
    reduces to the observable that ``key_press`` *attempted* the keyup
    transmission exactly once: we expect three ``sendto`` invocations
    in total (handshake, keydown, keyup), the last of which raised
    ``OSError`` and was therefore not recorded on the wire. The
    keydown packet is the only post-handshake packet on
    ``fake_sock.sent``; the keyup packet is observable only via
    ``fake_sock.attempts``.

    This branch also exercises the corollary that ``key_press`` does
    NOT crash when the keyup transmission fails — analogous to the
    "no exception propagates" half of Requirement 1.8.

    Validates: Requirements 5.8 (combined with the dispatch-layer
    ``OSError`` absorption from Requirement 1.8).
    """
    driver, fake_sock = _build_connected_driver()
    assert driver.connection_status == ConnectionStatus.CONNECTED
    handshake_attempts = len(fake_sock.attempts)
    handshake_sent = len(fake_sock.sent)
    assert handshake_attempts == 1 and handshake_sent == 1

    hid = _VK_TO_HID_TABLE[vk_code]

    # Install a logging handler so we can count ERROR-level records
    # emitted by ``_dispatch_call`` on the absorbed-OSError path.
    driver_logger = logging.getLogger("input.kmbox_net_driver")
    handler = _ListHandler()
    driver_logger.addHandler(handler)
    prior_level = driver_logger.level
    driver_logger.setLevel(logging.ERROR)

    # Strategy for arming the OSError on the *third* sendto (keyup):
    # let the keydown ``sendto`` succeed (handshake is already done),
    # then flip the fault on. We do this by wrapping ``key_press``'s
    # ``_keyup`` so that the fault is armed immediately before the
    # keyup dispatch — keeping the keydown call on the success path
    # regardless of which order Hypothesis explored.
    original_keyup = driver._keyup
    fault_armed_count = {"value": 0}

    def _armed_keyup(hid_code: int) -> None:
        fake_sock.raise_on_send = OSError(
            errno_value,
            f"test-injected keyup transmission failure for hid=0x{hid_code:02x}",
        )
        fake_sock.raise_once = True
        fault_armed_count["value"] += 1
        return original_keyup(hid_code)

    driver._keyup = _armed_keyup  # type: ignore[assignment]
    try:
        # ``key_press`` MUST NOT raise — ``_dispatch_call`` absorbs the
        # injected ``OSError`` per Requirement 1.8.
        result = driver.key_press(vk_code, hold_ms)
    finally:
        driver._keyup = original_keyup  # type: ignore[assignment]
        driver_logger.removeHandler(handler)
        driver_logger.setLevel(prior_level)

    # ``key_press`` returns ``True`` on the success-path-up-to-dispatch:
    # both keydown and keyup were attempted; the keyup transmission
    # error was caller-invisible because ``_dispatch_call`` absorbed it.
    assert result is True, (
        "key_press did not return True after a keyup-transmission "
        "fault that was absorbed by _dispatch_call (Requirement 1.8); "
        f"got {result!r}"
    )

    # The keyup wrapper armed the fault exactly once → exactly one
    # keyup attempt was issued.
    assert fault_armed_count["value"] == 1, (
        "_keyup was invoked an unexpected number of times: expected "
        f"1, got {fault_armed_count['value']}"
    )

    # Three sendto attempts in total: handshake + keydown + keyup.
    new_attempts = fake_sock.attempts[handshake_attempts:]
    new_sent = fake_sock.sent[handshake_sent:]
    assert len(new_attempts) == 2, (
        "expected exactly two sendto attempts from key_press "
        f"(keydown + keyup); got {len(new_attempts)}"
    )
    # Only the keydown packet was recorded on the wire — the keyup
    # ``sendto`` raised before the fake recorded it.
    assert len(new_sent) == 1, (
        "expected exactly one packet recorded on the wire from "
        f"key_press (keydown only — keyup raised); got {len(new_sent)}"
    )

    keydown_packet, _ = new_sent[0]
    keyup_attempt_packet, _ = new_attempts[1]

    assert _is_keyboard_packet(keydown_packet), (
        "first attempt is not a keyboard datagram: "
        f"len={len(keydown_packet)}"
    )
    assert _is_keyboard_packet(keyup_attempt_packet), (
        "second (raised) attempt is not a keyboard datagram: "
        f"len={len(keyup_attempt_packet)}"
    )

    _, keydown_ctrl, _, keydown_keys = _decode_keyboard_packet(keydown_packet)
    _, keyup_ctrl, _, keyup_keys = _decode_keyboard_packet(
        keyup_attempt_packet
    )

    assert _is_pressed_for_hid(keydown_ctrl, keydown_keys, hid), (
        f"keydown packet does not encode hid=0x{hid:02x} as held: "
        f"ctrl=0x{keydown_ctrl:02x}, keys={keydown_keys}"
    )
    # Property 10's central assertion for this branch: the keyup
    # *attempt* carried the released-state encoding for the same HID.
    assert _is_released(keyup_ctrl, keyup_keys), (
        "keyup attempt must encode the fully-released state "
        f"(ctrl=0, keys=all zero); got ctrl=0x{keyup_ctrl:02x}, "
        f"keys={keyup_keys}"
    )

    # Exactly one ERROR-level log record was emitted — the
    # ``_dispatch_call`` ``OSError`` path log naming the
    # ``"keyboard"`` command (the logical command name used by
    # ``_keyup`` when it routes through ``_dispatch_call``).
    error_records = [
        r for r in handler.records if r.levelno == logging.ERROR
    ]
    assert len(error_records) == 1, (
        "expected exactly one ERROR-level log record from the absorbed "
        f"keyup OSError; got {len(error_records)}: "
        f"{[r.getMessage() for r in error_records]}"
    )
    error_message = error_records[0].getMessage()
    assert "keyboard" in error_message, (
        "absorbed-OSError log entry must name the originating logical "
        f"command ('keyboard'); got {error_message!r}"
    )
    assert str(errno_value) in error_message, (
        "absorbed-OSError log entry must name the OSError errno "
        f"value ({errno_value}); got {error_message!r}"
    )

    # Driver is left in a recoverable state per Requirement 1.8 — the
    # ``OSError`` was absorbed without changing transport invariants.
    assert driver.connection_status == ConnectionStatus.CONNECTED
    assert driver.initialized is True
    assert fake_sock.closed is False
