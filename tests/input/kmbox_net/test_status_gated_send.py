"""
Property test — Task 5.7 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 13: Status-gated send suppression.

**Property 13: Status-gated send suppression**

    *For each* ``connection_status ∈ {disconnected, connecting,
    reconnecting, failed}`` and *for each* public-API send method
    routed through the driver's single dispatch chokepoint, the
    driver SHALL satisfy:

      * The call returns ``None``.
      * The call raises no exception.
      * ``FakeUdpSocket.sendto`` is invoked zero times by the call.
      * ``driver.remainder_x`` and ``driver.remainder_y`` are
        unchanged across the call.

**Validates: Requirements 7.8, 8.7, 10.4**

Requirement 7.8 covers utility commands (``reboot``, ``setconfig``,
``mask_mouse_left``, ``unmask_all``) — they "drop the call by
returning ``None``" while ``connection_status`` is not ``connected``.
Requirement 8.7 covers the ``send_move``/``send_click``/``move``/
``click``/``move_relative``/``click_button``/``mouse_down``/
``mouse_up``/``key_press``/``scroll`` family — same drop semantics
when the post-handshake ``initialized`` is ``False`` (which happens
on every non-``CONNECTED`` status). Requirement 10.4 generalizes the
gate over the entire mouse/keyboard public surface for the four
non-``CONNECTED`` states.

All three requirements collapse to a single behavioural claim at the
``_dispatch_call`` chokepoint: any send-path entry observed while
``connection_status != CONNECTED`` returns ``None`` without touching
the socket and without mutating ``BaseMouse`` accumulators. The
driver's per-command public wrappers (``_move``, ``_left``,
``send_move``, …) all funnel through ``_dispatch_call`` (Requirement
9.4 / design "Components and Interfaces"), so verifying the
chokepoint is sufficient — and necessary, because the public
wrappers themselves still raise ``NotImplementedError`` at the point
this task lands (per Tasks 7.x / 8.x). Future tasks that implement
the wrappers add validation/build code *before* the dispatch call;
they do not alter the gate.

Implementation notes
--------------------

The test instantiates a real :class:`KmBoxNetDriver` so the
constructor exercises the full Init_Handshake send + recv path
against a :class:`FakeUdpSocket` and a :class:`FakeDevice` configured
for a successful reply, leaving the driver in CONNECTED state. The
test body then mutates ``driver.connection_status`` to each of
{DISCONNECTED, CONNECTING, RECONNECTING, FAILED} and asserts the
dispatch chokepoint observes the gate.

The socket setup is done inline (rather than through pytest fixtures)
because Hypothesis runs the test body many times per pytest
invocation: function-scoped fixtures retain state across examples
and the :class:`FakeDevice` only publishes its handshake reply once.
Constructing fresh fakes per example keeps each ``KmBoxNetDriver()``
call deterministic. This mirrors the ``_build_connected_driver``
pattern already used in ``test_dispatch_encrypt_isolation.py`` and
``test_dispatch_oserror_isolation.py``.

The handshake itself emits one packet to ``FakeUdpSocket.sent`` — the
test snapshots that count after construction so the "zero new
packets" assertion compares to the post-handshake baseline rather
than to zero. Likewise the test seeds non-zero sentinels into
``remainder_x``/``remainder_y`` *after* construction so the
"unchanged across the call" assertion is strict (a regression that
zeroed the remainders on the gated path would not pass an
``rem == 0.0`` check, but it would fail a sentinel check).

Why ``CONNECTED`` is excluded from the status set
-------------------------------------------------

Property 13 is the *complement* of the "connected" path: the gate
takes effect for the four non-``CONNECTED`` states. A separate
property (Requirement 10.3, exercised by other tasks) covers the
``CONNECTED`` path, which MUST emit a packet rather than drop the
call. Asserting both halves in the same test would conflate two
distinct properties.
"""

from __future__ import annotations

import socket as _stdlib_socket
import sys
from pathlib import Path

# Make the ``input`` package importable when pytest is launched from
# the repository root or any sub-directory. The driver ships as
# ``input/kmbox_net_driver.py`` at the project root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hypothesis import given, settings  # noqa: E402  — sys.path manipulation above
from hypothesis import strategies as st  # noqa: E402

from input.kmbox_net_driver import (  # noqa: E402  — sys.path manipulation above
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


# ``valid_xy`` — signed mouse delta in ``[-32768, 32768]`` (Requirement 4.1).
_st_xy = st.integers(min_value=-32768, max_value=32768)
# ``valid_isdown`` — strict ``{0, 1}`` per Requirements 4.2 / 4.10.
_st_isdown = st.integers(min_value=0, max_value=1)
# ``valid_wheel`` — ``[-128, 128]`` per Requirement 4.3.
_st_wheel = st.integers(min_value=-128, max_value=128)
# ``valid_button_mask`` — full 8-bit bitmask per Requirement 4.4.
_st_btn_mask = st.integers(min_value=0, max_value=255)
# ``valid_ms`` — ``[1, 65535]`` per Requirements 4.6 / 4.7.
_st_ms = st.integers(min_value=1, max_value=65535)
# ``valid_hid`` — ``[0, 255]`` per Requirements 5.1 / 5.2 / 5.7.
_st_hid_byte = st.integers(min_value=0, max_value=255)
# ``valid_keyboard_keys`` — list of exactly 10 HID slots per ``soft_keyboard_t``.
_st_keyboard_keys = st.lists(_st_hid_byte, min_size=10, max_size=10)
# ``valid_port`` — Monitor_Channel port per Requirement 6.1, plus 0 (disable)
# per Requirement 6.2.
_st_monitor_port = st.one_of(
    st.just(0),
    st.integers(min_value=1024, max_value=49151),
)
# ``valid_setconfig_port`` — service port per Requirement 7.2.
_st_setconfig_port = st.integers(min_value=1, max_value=65535)
# ``valid_ip`` — four-octet dotted-decimal per Requirement 7.2. A single
# canonical sample suffices: this test exercises the *gate*, not the
# wire encoding (covered by Property 7 / Tasks 2.3 + 2.7).
_st_ip = st.sampled_from(
    [
        "0.0.0.0",
        "127.0.0.1",
        "192.168.2.188",
        "255.255.255.255",
    ]
)
# ``valid_mask_state`` — ``{0, 1}`` per Requirement 7.6.
_st_mask_state = st.integers(min_value=0, max_value=1)


def _cmd_strategy() -> st.SearchStrategy:
    """Strategy emitting a ``(cmd_name, args)`` tuple for ``_dispatch_call``.

    Sampled across *every* logical command name recognized by the
    dispatch table in ``KmBoxNetDriver._dispatch_call`` — mouse
    (``move``, ``left``, ``right``, ``middle``, ``wheel``, ``mouse``,
    ``move_auto``, ``move_beizer``), keyboard (``keyboard``),
    monitor (``monitor``), and utility (``reboot``, ``setconfig``,
    ``mask_mouse_left``, ``unmask_all``).

    The full surface is covered because Property 13 spans every
    public-API send method per Requirements 7.8, 8.7, 10.4 — the
    gate is at the chokepoint, but the *requirement* names each
    method individually, so sampling every one demonstrates the
    gate applies uniformly.
    """
    return st.one_of(
        st.tuples(st.just("move"), st.tuples(_st_xy, _st_xy)),
        st.tuples(st.just("left"), st.tuples(_st_isdown)),
        st.tuples(st.just("right"), st.tuples(_st_isdown)),
        st.tuples(st.just("middle"), st.tuples(_st_isdown)),
        st.tuples(st.just("wheel"), st.tuples(_st_wheel)),
        st.tuples(
            st.just("mouse"),
            st.tuples(_st_btn_mask, _st_xy, _st_xy, _st_wheel),
        ),
        st.tuples(
            st.just("move_auto"),
            st.tuples(_st_xy, _st_xy, _st_ms),
        ),
        st.tuples(
            st.just("move_beizer"),
            st.tuples(_st_xy, _st_xy, _st_ms, _st_xy, _st_xy, _st_xy, _st_xy),
        ),
        st.tuples(
            st.just("keyboard"),
            st.tuples(_st_hid_byte, _st_keyboard_keys),
        ),
        st.tuples(st.just("monitor"), st.tuples(_st_monitor_port)),
        st.tuples(st.just("reboot"), st.tuples()),
        st.tuples(
            st.just("setconfig"),
            st.tuples(_st_ip, _st_setconfig_port),
        ),
        st.tuples(
            st.just("mask_mouse_left"),
            st.tuples(_st_mask_state),
        ),
        st.tuples(st.just("unmask_all"), st.tuples()),
    )


# ``status_strategy`` — every non-``CONNECTED`` member of
# :class:`ConnectionStatus`. The four members named by Requirement
# 10.4 (DISCONNECTED, CONNECTING, RECONNECTING, FAILED) are exactly
# the set for which the gate must drop the call.
_st_non_connected_status = st.sampled_from(
    [
        ConnectionStatus.DISCONNECTED,
        ConnectionStatus.CONNECTING,
        ConnectionStatus.RECONNECTING,
        ConnectionStatus.FAILED,
    ]
)

# ``remainder_strategy`` — finite floats far from zero so the
# "unchanged across gated call" assertion is non-trivial. The
# remainders live on ``BaseMouse`` and are never touched by
# ``_dispatch_call``; using non-zero sentinels makes a regression
# detectable (a stray ``self.remainder_x = 0.0`` would not pass an
# ``rem != 0.0`` check, but it would pass an unconditional
# ``rem == 0.0`` check).
_st_remainder = st.floats(
    min_value=-100.0,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
)

# Sequence of ``((cmd_name, args), status, rem_x, rem_y)`` tuples.
# Bounded so Hypothesis examples stay quick — five steps is enough to
# interleave all four non-``CONNECTED`` statuses across multiple
# command names and prove the gate holds uniformly. Using a sequence
# (rather than a single tuple) lets one example exercise the gate
# under several distinct status transitions in series, which catches
# any regression where the gate latches "off" after the first call.
_st_scenario = st.lists(
    st.tuples(
        _cmd_strategy(),
        _st_non_connected_status,
        _st_remainder,
        _st_remainder,
    ),
    min_size=1,
    max_size=5,
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
    ``initialized == True``; the test body mutates
    ``driver.connection_status`` *after* construction to put the
    driver into each of the four non-``CONNECTED`` states under
    test, without re-running the handshake.

    Returns:
        Tuple of (driver, fake_udp_socket). The ``fake_udp_socket``
        is the underlying transport the driver bound during
        construction; ``fake_udp_socket.sent`` records every packet
        the driver has emitted, including the handshake.
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
        # Disable encryption for this test so the wire packets emitted
        # in the (counterfactual) "gate fails" branch would be the
        # plaintext mouse-class layout (72 bytes) rather than the
        # encrypted 128-byte form. Property 13 is independent of the
        # ``use_encryption`` flag (the gate runs *before* the
        # encryption decision in ``_dispatch_call``), so either
        # setting would work; plaintext keeps the failure mode
        # easier to read in any counter-example.
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


# ---------------------------------------------------------------------------
# Property 13
# ---------------------------------------------------------------------------


@settings(max_examples=75, deadline=None)
@given(scenario=_st_scenario)
def test_status_gated_send_suppression(scenario: list) -> None:
    """``_dispatch_call`` drops the call when ``connection_status != CONNECTED``.

    For each step in the generated scenario the driver's
    ``connection_status`` is mutated to one of the four non-``CONNECTED``
    members of :class:`ConnectionStatus`, then ``_dispatch_call`` is
    invoked with one of the 14 logical command names recognized by
    the dispatch table. After the call the test asserts:

      * The dispatch helper returned ``None`` — Requirements 7.8,
        8.7, 10.4 explicitly require ``None`` return on the gated
        path.
      * No exception was raised — the gate is a *silent* drop, not
        a fault. The driver's public surface is consumed by a
        240 Hz aim-output thread which would otherwise crash on a
        single transient gate hit.
      * No new packet reached the wire — ``len(fake_sock.sent)``
        equals the post-handshake baseline. The handshake itself
        emitted one packet during construction; subsequent gated
        dispatches MUST NOT emit any.
      * ``driver.remainder_x`` and ``driver.remainder_y`` equal the
        sentinels seeded immediately before the call. The
        ``BaseMouse`` accumulator is owned by ``move()``, never by
        ``_dispatch_call``, so the gated path MUST NOT touch it.

    Validates: Requirements 7.8, 8.7, 10.4.
    """
    # 1. Build a connected driver against the fakes. The handshake
    # itself runs on the same FakeUdpSocket; once we return from
    # ``_build_connected_driver`` the driver is in CONNECTED state
    # and the socket has exactly one entry in ``.sent`` (the
    # handshake).
    driver, fake_sock = _build_connected_driver()
    assert driver.connection_status == ConnectionStatus.CONNECTED, (
        "test pre-condition: handshake must succeed so the driver "
        "starts in CONNECTED before the test body mutates the status; "
        "got %r" % (driver.connection_status,)
    )
    assert driver.initialized is True
    assert fake_sock.closed is False

    handshake_packet_count = len(fake_sock.sent)
    assert handshake_packet_count == 1, (
        "test pre-condition: exactly one handshake packet should "
        "have been emitted before any dispatch calls; got %d"
        % handshake_packet_count
    )

    # 2. Replay the generated scenario step by step. Each step picks
    # one of the four gated statuses and one of the 14 command
    # names; every step asserts the four-clause invariant.
    for step_index, ((cmd_name, args), gated_status, rem_x, rem_y) in enumerate(
        scenario
    ):
        # Snapshot the wire-packet count *before* mutating the
        # status so the post-call assertion compares to the
        # immediate-prior count, not to the original handshake
        # baseline. Across multiple gated steps the count must
        # remain equal to the baseline because no step is allowed
        # to emit a packet.
        sent_before = len(fake_sock.sent)

        # Seed BaseMouse remainders with known sentinels so the
        # "unchanged across gated call" assertion is strict.
        # ``remainder_x`` / ``remainder_y`` are ordinary ``float``
        # attributes on ``BaseMouse``; assigning them directly is
        # the same operation ``BaseMouse.calculate_move_amount``
        # performs internally and matches the ``_st_remainder``
        # range.
        driver.remainder_x = rem_x
        driver.remainder_y = rem_y

        # 3. Mutate the connection status. The assignment is a
        # single attribute write of an immutable ``str`` enum
        # value (``ConnectionStatus.DISCONNECTED`` etc. are
        # interned at module load); under CPython's GIL this is
        # atomic per the design "Threading model" section, so no
        # lock is required even if the test ran under
        # ``ThreadPoolExecutor`` (it does not — the test is
        # single-threaded).
        driver.connection_status = gated_status

        # 4. Invoke the chokepoint with one of the 14 logical
        # command names. The call must return ``None`` and must
        # not raise. ``_dispatch_call`` does its own argument
        # unpacking based on ``cmd_name``, so the per-command
        # ``args`` tuple is forwarded via ``*args``.
        try:
            result = driver._dispatch_call(cmd_name, *args)
        except Exception as exc:
            raise AssertionError(
                "step %d (status=%r, cmd_name=%r, args=%r): "
                "_dispatch_call raised %s: %s — Requirement "
                "10.4 requires the gated path to drop the call "
                "silently without raising."
                % (
                    step_index,
                    gated_status,
                    cmd_name,
                    args,
                    type(exc).__name__,
                    exc,
                )
            )

        # Clause 1 — return value.
        assert result is None, (
            "step %d (status=%r, cmd_name=%r): _dispatch_call "
            "returned %r; Requirement 10.4 requires ``None``."
            % (step_index, gated_status, cmd_name, result)
        )

        # Clause 2 — wire silence. The gated path MUST NOT emit a
        # packet; ``len(fake_sock.sent)`` is unchanged from the
        # pre-call snapshot. Across all five scenario steps the
        # count therefore stays at the post-handshake baseline.
        sent_after = len(fake_sock.sent)
        assert sent_after == sent_before, (
            "step %d (status=%r, cmd_name=%r): FakeUdpSocket.sent "
            "grew from %d to %d entries — Requirements 7.8, 8.7, "
            "10.4 forbid invoking sendto on the gated path."
            % (
                step_index,
                gated_status,
                cmd_name,
                sent_before,
                sent_after,
            )
        )

        # Clause 3 — remainder preservation. The gated path MUST
        # NOT mutate ``BaseMouse`` accumulators; assert byte-equal
        # equality of the sentinels.
        assert driver.remainder_x == rem_x, (
            "step %d (status=%r, cmd_name=%r): remainder_x changed "
            "from %r to %r across a gated call — Requirements 7.8, "
            "8.7, 10.4 require the dispatch helper to leave "
            "remainder_x unchanged."
            % (
                step_index,
                gated_status,
                cmd_name,
                rem_x,
                driver.remainder_x,
            )
        )
        assert driver.remainder_y == rem_y, (
            "step %d (status=%r, cmd_name=%r): remainder_y changed "
            "from %r to %r across a gated call — Requirements 7.8, "
            "8.7, 10.4 require the dispatch helper to leave "
            "remainder_y unchanged."
            % (
                step_index,
                gated_status,
                cmd_name,
                rem_y,
                driver.remainder_y,
            )
        )

        # Clause 4 — socket lifecycle. The gate is a *drop*, not a
        # teardown: the underlying fake socket must remain open so
        # the next CONNECTED-state dispatch (after a successful
        # reconnect, in production) can use the same transport
        # without re-running the handshake. Closure would be a
        # release()-equivalent action and is out of scope for the
        # gate.
        assert fake_sock.closed is False, (
            "step %d (status=%r, cmd_name=%r): underlying fake "
            "socket was closed by a gated dispatch — Requirements "
            "7.8, 8.7, 10.4 require the dispatch helper to leave "
            "the socket open on the gated path."
            % (step_index, gated_status, cmd_name)
        )

    # Cross-step invariant — across every gated step in the scenario
    # the wire-packet count never moved off the post-handshake
    # baseline. This catches a regression where the gate held for
    # the *first* gated call (e.g. by testing a stale ``initialized``
    # flag) but released for subsequent calls in the same status.
    assert len(fake_sock.sent) == handshake_packet_count, (
        "post-scenario invariant: total emitted packets stayed at "
        "the handshake baseline (%d) across %d gated dispatches; "
        "got %d." % (handshake_packet_count, len(scenario), len(fake_sock.sent))
    )
