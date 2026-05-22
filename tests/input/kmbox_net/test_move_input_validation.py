"""
Property test — Task 8.2 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 3: ``move`` input validation
# and remainder accumulation.

**Property 3: ``move`` input validation and remainder accumulation**

    *For any* Hypothesis-generated ``(rem_x, rem_y, x, y)`` tuple, the
    public-API method :meth:`KmBoxNetDriver.move` SHALL satisfy:

      * **Valid path** — when ``x`` and ``y`` are finite floats in the
        inclusive range ``[-32768.0, 32768.0]``, the post-call
        ``remainder_x`` / ``remainder_y`` equal what
        :meth:`BaseMouse.calculate_move_amount` would produce when
        applied to the pre-call remainders, and exactly one
        ``_move(int_x, int_y)`` packet reaches the wire iff
        ``(int_x, int_y) != (0, 0)``; otherwise zero packets are
        emitted and the remainders still match the
        ``calculate_move_amount`` reference (which may have updated
        them even when the integer truncation is zero).
      * **Invalid path** — when *either* ``x`` *or* ``y`` is NaN,
        ±inf, or outside ``[-32768.0, 32768.0]``, the call is dropped
        without modifying ``remainder_x`` or ``remainder_y`` and
        without emitting a UDP packet (Requirement 3.4).

**Validates: Requirements 3.3, 3.4**

Implementation notes
--------------------

The test instantiates a real :class:`KmBoxNetDriver` so the
constructor exercises the full Init_Handshake send + recv path against
a :class:`FakeUdpSocket` and a :class:`FakeDevice` configured for a
successful reply. Encryption is disabled (``use_encryption=False``) so
each post-handshake packet on the wire is exactly
``CMD_HEAD_SIZE + SOFT_MOUSE_SIZE = 72`` bytes; this lets the test
length-check and decode the move packets without modelling the
encryptor's keystream.

The reference computation that mirrors
:meth:`BaseMouse.calculate_move_amount` is implemented inline (rather
than imported and re-invoked on a separate dummy mouse instance) so
the test verifies the *contract* of the algorithm, not a particular
implementation: given pre-call remainders ``(rx, ry)`` and a finite
in-range ``(x, y)``, the post-call remainders are
``(rx + x - int(rx + x), ry + y - int(ry + y))`` and the truncated
deltas are ``(int(rx + x), int(ry + y))``. Re-deriving the formula
from the requirement text rather than the implementation means the
test would still flag a regression if ``calculate_move_amount`` were
later refactored in a way that deviated from the documented behaviour.

The socket / device setup is done inside the test body (rather than
through pytest fixtures) because Hypothesis runs the test body many
times per pytest invocation: function-scoped fixtures retain state
across examples and the :class:`FakeDevice` only publishes its
handshake reply once. Constructing fresh fakes per example keeps each
``KmBoxNetDriver()`` call deterministic. This mirrors the
``_build_connected_driver`` pattern already used in
``test_dispatch_encrypt_isolation.py``,
``test_dispatch_oserror_isolation.py``, and
``test_send_click_ordering.py``.
"""

from __future__ import annotations

import math
import socket as _stdlib_socket
import struct
import sys
from pathlib import Path
from typing import Tuple

# Make the ``input`` package importable when pytest is launched from
# the repository root or any sub-directory. The driver ships as
# ``input/kmbox_net_driver.py`` at the project root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from input.kmbox_net_driver import (  # noqa: E402  — sys.path manipulation above
    CMD_HEAD_FORMAT,
    CMD_HEAD_SIZE,
    CMD_MOUSE_MOVE,
    ConnectionStatus,
    KmBoxNetDriver,
    SOFT_MOUSE_FORMAT,
    SOFT_MOUSE_SIZE,
)
from tests.input.kmbox_net.conftest import (  # noqa: E402
    FakeDevice,
    FakeUdpSocket,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


# ``valid_float_xy`` — finite floats in the inclusive range
# ``[-32768.0, 32768.0]`` (Requirement 3.3 / 3.4 valid path). The
# Hypothesis ``floats`` strategy with ``allow_nan=False`` and
# ``allow_infinity=False`` plus the explicit bounds covers the entire
# valid input domain for ``move``.
_st_valid_float_xy = st.floats(
    min_value=-32768.0,
    max_value=32768.0,
    allow_nan=False,
    allow_infinity=False,
)

# ``invalid_float`` — NaN, ±inf, or out-of-range floats. The driver
# MUST reject every value here (Requirement 3.4). The strategy is the
# union of three independent generators so Hypothesis explores each
# rejection branch (NaN, +inf, -inf, out-of-range positive,
# out-of-range negative) without any one branch dominating.
_st_invalid_float = st.one_of(
    # NaN — comparisons with the bounded range always return False, so
    # any range check that uses ``-32768.0 <= xf <= 32768.0`` rejects
    # NaN trivially.
    st.just(float("nan")),
    # ±inf.
    st.just(float("inf")),
    st.just(float("-inf")),
    # Out-of-range finite floats. The bounds are 32768.0 + 1e-3 to
    # ensure a finite distance above the cutoff (so a strict-inequality
    # bug in the driver's range check would still accept these).
    st.floats(
        min_value=32768.0 + 1e-3,
        max_value=1e30,
        allow_nan=False,
        allow_infinity=False,
    ),
    st.floats(
        min_value=-1e30,
        max_value=-32768.0 - 1e-3,
        allow_nan=False,
        allow_infinity=False,
    ),
)

# ``valid_remainder`` — sentinels for the pre-call remainder state.
# The driver does not constrain remainder magnitudes (the BaseMouse
# accumulator can in principle hold any float), but real-world values
# stay in single-pixel territory. ``[-100.0, 100.0]`` covers the
# realistic operating range plus generous margin and avoids floating-
# point precision artifacts that would arise at very large magnitudes
# where ``int(huge_float + small_float) != int(huge_float) +
# int(small_float)``.
_st_valid_remainder = st.floats(
    min_value=-100.0,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
)


# Top-level scenario: pre-call remainders plus an ``(x, y)`` pair that
# is either fully valid, fully invalid, or mixed (one valid + one
# invalid). The mixed branch is important because Requirement 3.4
# rejects when *either* coordinate is invalid, not only when both are.
_st_xy_pair = st.one_of(
    # Both valid.
    st.tuples(_st_valid_float_xy, _st_valid_float_xy),
    # Both invalid.
    st.tuples(_st_invalid_float, _st_invalid_float),
    # x invalid, y valid.
    st.tuples(_st_invalid_float, _st_valid_float_xy),
    # x valid, y invalid.
    st.tuples(_st_valid_float_xy, _st_invalid_float),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_connected_driver() -> Tuple[KmBoxNetDriver, FakeUdpSocket]:
    """Construct a ``KmBoxNetDriver`` whose handshake succeeds against a fake.

    Patches ``socket.socket`` for the duration of the constructor so
    the driver creates a :class:`FakeUdpSocket` instead of a real one,
    and attaches a successful :class:`FakeDevice` so the handshake
    ``recvfrom`` resolves to a zero-result-code reply. The patch is
    reverted before the function returns.

    The returned driver is in ``ConnectionStatus.CONNECTED`` with
    ``initialized == True`` and ``use_encryption == False`` so each
    post-handshake mouse packet is the canonical 72-byte plaintext
    ``cmd_head_t + soft_mouse_t`` record. This lets the test decode
    the wire bytes directly to confirm the emitted packet is in fact
    the ``cmd_mouse_move`` form (Requirement 3.3 second clause:
    "emit an integer-pixel UDP move command"), not — say — a
    ``cmd_mouse_left`` triggered by a stray click thread.

    Returns:
        Tuple of (driver, fake_udp_socket). ``fake_udp_socket.sent``
        records every packet the driver has emitted, including the
        single handshake packet emitted during ``__init__``.
    """
    sockets: list = []
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


def _reference_calculate_move_amount(
    rem_x: float,
    rem_y: float,
    x: float,
    y: float,
) -> Tuple[int, int, float, float]:
    """Reference computation mirroring :meth:`BaseMouse.calculate_move_amount`.

    Re-derived from the requirement text (Requirement 3.3) rather
    than imported from :class:`BaseMouse` so the test verifies the
    *contract* of the algorithm. The contract is:

      * Add the incoming ``(x, y)`` to the prior ``(rem_x, rem_y)``.
      * Truncate the resulting accumulators to integers (``int()``
        truncates toward zero).
      * The new remainders are the post-truncation fractional parts
        (``acc - int(acc)``).

    Returns:
        ``(int_x, int_y, new_rem_x, new_rem_y)`` — the four-tuple a
        compliant ``calculate_move_amount`` MUST produce for the
        given inputs.
    """
    acc_x = rem_x + x
    acc_y = rem_y + y
    int_x = int(acc_x)
    int_y = int(acc_y)
    new_rem_x = acc_x - int_x
    new_rem_y = acc_y - int_y
    return int_x, int_y, new_rem_x, new_rem_y


def _decode_move_packet(packet: bytes) -> Tuple[int, int, int]:
    """Decode ``head.cmd`` and ``soft_mouse_t.(x, y)`` from a 72-byte packet.

    Mouse-class plaintext packets are exactly
    ``CMD_HEAD_SIZE + SOFT_MOUSE_SIZE`` (16 + 56 = 72) bytes per the
    design's "Per-command payload encoding" table. The header layout
    ``(mac, rand, indexpts, cmd)`` is little-endian, and the payload
    starts at offset ``CMD_HEAD_SIZE`` with the ``soft_mouse_t``
    fields in order ``(button, x, y, wheel, point[10])`` per
    :data:`SOFT_MOUSE_FORMAT`.

    Returns:
        ``(head.cmd, soft_mouse_t.x, soft_mouse_t.y)``.
    """
    expected = CMD_HEAD_SIZE + SOFT_MOUSE_SIZE
    assert len(packet) == expected, (
        f"mouse-class plaintext packet must be exactly {expected} "
        f"bytes (header + soft_mouse_t); got {len(packet)}"
    )
    _mac, _rand, _indexpts, head_cmd = struct.unpack(
        CMD_HEAD_FORMAT, packet[:CMD_HEAD_SIZE]
    )
    fields = struct.unpack(
        SOFT_MOUSE_FORMAT, packet[CMD_HEAD_SIZE:expected]
    )
    # ``fields`` = (button, x, y, wheel, point[0..9]).
    return head_cmd, fields[1], fields[2]


def _is_finite_in_range(v: float) -> bool:
    """Return True iff ``v`` is finite and in ``[-32768.0, 32768.0]``.

    Re-implements the Requirement 3.4 acceptance condition without
    relying on the driver's internal range-check spelling. NaN and
    ±inf return False because :func:`math.isfinite` rejects both.
    """
    if not isinstance(v, (int, float)):
        return False
    if isinstance(v, bool):
        return False
    if not math.isfinite(float(v)):
        return False
    return -32768.0 <= float(v) <= 32768.0


# ---------------------------------------------------------------------------
# Property 3
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    rem_x=_st_valid_remainder,
    rem_y=_st_valid_remainder,
    xy=_st_xy_pair,
)
def test_move_input_validation_and_remainder_accumulation(
    rem_x: float,
    rem_y: float,
    xy: Tuple[float, float],
) -> None:
    """``move`` validates inputs and accumulates remainders per Requirements 3.3, 3.4.

    For each generated ``(rem_x, rem_y, x, y)`` example the test:

      1. Builds a connected driver against fresh fakes (handshake
         succeeds, encryption disabled).
      2. Sets the pre-call ``remainder_x`` / ``remainder_y`` to the
         generated sentinel values.
      3. Snapshots ``len(fake_sock.sent)`` so the post-call delta
         counts only packets emitted by the ``move`` call (excluding
         the single handshake packet).
      4. Calls ``driver.move(x, y)``.
      5. Branches on the validity of ``(x, y)``:

         * **Valid** (both ``x`` and ``y`` finite and in range): the
           post-call remainders MUST match the reference computation
           (Requirement 3.3); exactly one new packet was emitted iff
           the truncated ``(int_x, int_y) != (0, 0)``; the emitted
           packet MUST be a ``cmd_mouse_move`` packet whose
           ``soft_mouse_t.(x, y)`` fields equal the reference
           ``(int_x, int_y)``.
         * **Invalid** (either ``x`` or ``y`` NaN, ±inf, or
           out-of-range): zero new packets MUST have been emitted
           and the remainders MUST be byte-equal to their pre-call
           values (Requirement 3.4 "without modifying remainder_x
           or remainder_y").

    Validates: Requirements 3.3, 3.4.
    """
    x, y = xy

    # 1. Build a connected driver against fresh fakes.
    driver, fake_sock = _build_connected_driver()
    assert driver.connection_status == ConnectionStatus.CONNECTED, (
        "test pre-condition: handshake must succeed so move() is not "
        "gated out by the connection-status check; got %r"
        % (driver.connection_status,)
    )
    assert driver.use_encryption is False, (
        "test pre-condition: encryption must be disabled so the "
        "emitted move packet is the canonical 72-byte plaintext "
        "form decodable by _decode_move_packet"
    )

    # 2. Seed the remainder state.
    driver.remainder_x = float(rem_x)
    driver.remainder_y = float(rem_y)

    # 3. Snapshot the wire-packet count *after* the handshake. Any
    # delta from this baseline is attributable to the move() call
    # under test.
    sent_before = len(fake_sock.sent)
    assert sent_before == 1, (
        "test pre-condition: exactly one handshake packet should "
        "have been emitted before move() is called; got %d"
        % sent_before
    )

    # 4. Invoke move(). Per Requirement 3.4 the call must not raise
    # for invalid inputs — it must drop them silently.
    driver.move(x, y)

    sent_after = len(fake_sock.sent)
    new_packets = fake_sock.sent[sent_before:sent_after]

    # 5. Branch on the validity of (x, y).
    valid = _is_finite_in_range(x) and _is_finite_in_range(y)

    if valid:
        # ── Valid path — Requirement 3.3 ──────────────────────────
        ref_int_x, ref_int_y, ref_rem_x, ref_rem_y = (
            _reference_calculate_move_amount(rem_x, rem_y, x, y)
        )

        # Post-call remainders match the reference computation. We
        # use exact equality because BaseMouse.calculate_move_amount
        # uses the same float arithmetic the reference does, so the
        # results must be bit-identical (no rounding tolerance is
        # required and a tolerance would mask a genuine drift bug).
        assert driver.remainder_x == ref_rem_x, (
            "post-call remainder_x must match BaseMouse."
            "calculate_move_amount reference; pre=(%r, %r), in=(%r, %r), "
            "expected_rem_x=%r, got_rem_x=%r"
            % (rem_x, rem_y, x, y, ref_rem_x, driver.remainder_x)
        )
        assert driver.remainder_y == ref_rem_y, (
            "post-call remainder_y must match BaseMouse."
            "calculate_move_amount reference; pre=(%r, %r), in=(%r, %r), "
            "expected_rem_y=%r, got_rem_y=%r"
            % (rem_x, rem_y, x, y, ref_rem_y, driver.remainder_y)
        )

        # Exactly one new packet iff the truncated deltas are
        # non-zero. ``move()`` calls ``send_move`` — which
        # ultimately reaches ``_dispatch_call("move", ...)`` — only
        # when ``(int_x, int_y) != (0, 0)``; otherwise it is a no-op
        # at the public API surface.
        if (ref_int_x, ref_int_y) != (0, 0):
            # Reference truncated deltas may still be outside the
            # ``[-32768, 32768]`` range that ``send_move`` enforces
            # (Requirement 3.10): the accumulator can drift one
            # past the bound when ``(rem + x)`` is just over the
            # cutoff after rounding. ``send_move`` drops in that
            # case, so we tolerate the no-packet outcome.
            send_move_in_range = (
                -32768 <= ref_int_x <= 32768
                and -32768 <= ref_int_y <= 32768
            )
            if send_move_in_range:
                assert len(new_packets) == 1, (
                    "Requirement 3.3: exactly one move packet must be "
                    "emitted when truncated deltas are non-zero and "
                    "in send_move's range; pre=(%r, %r), in=(%r, %r), "
                    "expected (int_x, int_y)=(%d, %d); got %d packets"
                    % (
                        rem_x, rem_y, x, y,
                        ref_int_x, ref_int_y, len(new_packets),
                    )
                )
                packet, _addr = new_packets[0]
                head_cmd, packet_x, packet_y = _decode_move_packet(packet)
                assert head_cmd == CMD_MOUSE_MOVE, (
                    "Requirement 3.3: emitted packet must be a "
                    "cmd_mouse_move packet (head.cmd == 0x%08x); "
                    "got head.cmd == 0x%08x"
                    % (CMD_MOUSE_MOVE, head_cmd & 0xFFFFFFFF)
                )
                assert packet_x == ref_int_x, (
                    "Requirement 3.3: emitted soft_mouse_t.x must "
                    "equal the truncated accumulator; pre=(%r, %r), "
                    "in=(%r, %r), expected_x=%d, got_x=%d"
                    % (
                        rem_x, rem_y, x, y,
                        ref_int_x, packet_x,
                    )
                )
                assert packet_y == ref_int_y, (
                    "Requirement 3.3: emitted soft_mouse_t.y must "
                    "equal the truncated accumulator; pre=(%r, %r), "
                    "in=(%r, %r), expected_y=%d, got_y=%d"
                    % (
                        rem_x, rem_y, x, y,
                        ref_int_y, packet_y,
                    )
                )
            else:
                # send_move drops the out-of-range case silently
                # per Requirement 3.10. No packets expected.
                assert len(new_packets) == 0, (
                    "Requirement 3.10: send_move must drop "
                    "out-of-range truncated deltas without emitting; "
                    "pre=(%r, %r), in=(%r, %r), "
                    "(int_x, int_y)=(%d, %d), got %d packets"
                    % (
                        rem_x, rem_y, x, y,
                        ref_int_x, ref_int_y, len(new_packets),
                    )
                )
        else:
            # ``(int_x, int_y) == (0, 0)`` — accumulator did not
            # cross an integer boundary; the BaseMouse contract
            # explicitly skips ``send_move`` in this case.
            assert len(new_packets) == 0, (
                "Requirement 3.3: zero packets must be emitted when "
                "truncated deltas are (0, 0); pre=(%r, %r), in=(%r, %r), "
                "got %d packets"
                % (rem_x, rem_y, x, y, len(new_packets))
            )
    else:
        # ── Invalid path — Requirement 3.4 ────────────────────────
        # Remainders must be byte-equal to their pre-call values.
        # Float equality is exact here because the driver must not
        # touch the remainders at all on the invalid path.
        assert driver.remainder_x == rem_x, (
            "Requirement 3.4: remainder_x must be unchanged on the "
            "invalid path; pre_rem_x=%r, in=(%r, %r), got_rem_x=%r"
            % (rem_x, x, y, driver.remainder_x)
        )
        assert driver.remainder_y == rem_y, (
            "Requirement 3.4: remainder_y must be unchanged on the "
            "invalid path; pre_rem_y=%r, in=(%r, %r), got_rem_y=%r"
            % (rem_y, x, y, driver.remainder_y)
        )
        # Zero new packets emitted.
        assert len(new_packets) == 0, (
            "Requirement 3.4: zero UDP packets must be emitted on "
            "the invalid path; in=(%r, %r), got %d packets"
            % (x, y, len(new_packets))
        )
