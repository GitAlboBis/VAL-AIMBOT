"""
Property test — Task 4.4 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 2: Transmission-failure isolation.

**Property 2: Transmission-failure isolation**

    *For any* sequence of public-API calls executed against a connected
    driver where an arbitrary subset of the underlying
    ``UDP_Socket.sendto`` invocations are configured to raise
    ``OSError``, the driver SHALL satisfy after every failing call:

      * ``driver.remainder_x`` and ``driver.remainder_y`` are unchanged
        from their values immediately before the failing call. A
        transmission fault MUST NOT corrupt the BaseMouse sub-pixel
        accumulator (which is updated by ``move()``, never by
        ``_dispatch_call``).
      * Exactly one ERROR-level log record is emitted on the
        ``input.kmbox_net_driver`` logger and its message names both
        the originating logical command and the OSError ``errno``
        value (the driver's ``_dispatch_call`` error log includes
        ``errno=<n>``).
      * The underlying UDP socket is still open
        (``fake_sock.closed == False``) — Requirement 1.8 forbids
        closing the socket on a transient transmission error so
        recovery is possible without re-running the handshake.
      * ``driver.initialized`` and ``driver.connection_status`` are
        unchanged from their values immediately before the failing
        call. The status field stays at ``CONNECTED`` so subsequent
        sends are not gated out by ``_dispatch_call``'s status check.
      * The next ``_dispatch_call`` invoked with ``raise_on_send``
        cleared completes successfully without raising — the driver
        recovers transparently and the wire receives the new packet.

**Validates: Requirements 1.8**

Implementation notes
--------------------

The test instantiates a real :class:`KmBoxNetDriver` so the
constructor exercises the full Init_Handshake send + recv path against
a :class:`FakeUdpSocket` and a :class:`FakeDevice` configured for a
successful reply. Because the command-layer wrappers (``_move``,
``_left``, …) still raise ``NotImplementedError`` at the point this
task lands, the test calls ``driver._dispatch_call("move", …)``
(and other ``cmd_name`` strings) directly. ``_dispatch_call`` is the
single chokepoint that catches ``OSError`` and emits the diagnostic
log entry per Requirement 1.8, so exercising it directly is
sufficient to prove the property.

The socket setup is done inline (rather than through pytest fixtures)
because Hypothesis runs the test body many times per pytest
invocation: function-scoped fixtures retain state across examples and
the :class:`FakeDevice` only publishes its handshake reply once.
Constructing fresh fakes per example keeps each ``KmBoxNetDriver()``
call deterministic. This mirrors the ``_build_connected_driver``
pattern already used in ``test_dispatch_encrypt_isolation.py``.

Fault injection uses ``FakeUdpSocket.raise_on_send`` with
``raise_once=True`` so every failing step injects exactly one
``OSError`` and the next ``sendto`` succeeds — enabling the
"recovers transparently" clause of Property 2 to be validated on the
same socket, on the same step.

The driver's ``BaseMouse.remainder_x``/``remainder_y`` accumulator is
never touched by ``_dispatch_call`` (it is updated only by
``move()``), so this test sets the remainders to *known, non-zero
sentinels* before each failing dispatch. Asserting that those
sentinels are unchanged after the failure is a strict test: if a
future refactor accidentally routes ``_dispatch_call`` through
``move()`` or otherwise touches the remainders on a fault path, the
mismatch is detected.
"""

from __future__ import annotations

import logging
import socket as _stdlib_socket
import sys
from pathlib import Path

# Make the ``input`` package importable when pytest is launched from
# the repository root or any sub-directory. The driver ships as
# ``input/kmbox_net_driver.py`` at the project root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hypothesis import given, settings
from hypothesis import strategies as st

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


def _cmd_strategy() -> st.SearchStrategy:
    """Strategy emitting a ``(cmd_name, args)`` tuple for ``_dispatch_call``.

    Sampled across the mouse-class commands whose builders are stable
    at this point in the implementation (``move``, ``left``, ``right``,
    ``middle``, ``wheel``, ``mouse``). All five route through the
    single ``_dispatch_call`` chokepoint, so any one of them exercises
    the same OSError-isolation path. Sampling across several increases
    the chance that the ``cmd_name`` substring assertion exercises
    distinct spellings rather than always seeing ``"move"``.
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
    )


# ``errno_strategy`` — pick from a small set of distinct, realistic
# UDP errnos. The driver's log message includes ``errno=<value>`` so
# any positive integer would do; sampling a few well-known values
# (EAGAIN, ENETUNREACH, EHOSTUNREACH, EMSGSIZE, ENOBUFS) makes the
# generated counter-examples easier to read when something fails.
_st_errno = st.sampled_from([11, 90, 101, 105, 113])

# ``remainder_strategy`` — finite floats far from zero so the
# "unchanged after fault" assertion is non-trivial. The remainders
# live on ``BaseMouse`` and are never touched by ``_dispatch_call``,
# so any value should round-trip; using non-zero sentinels makes a
# regression detectable (a stray ``self.remainder_x = 0.0`` would not
# pass).
_st_remainder = st.floats(
    min_value=-100.0,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
)

# Sequence of ``((cmd_name, args), should_fail, errno, rem_x, rem_y)``
# tuples. Bounded so Hypothesis examples stay quick — five steps is
# enough to interleave failing and succeeding calls and prove the
# fault-isolation invariants on each failing step plus the "recovery"
# clause via the next succeeding step.
_st_scenario = st.lists(
    st.tuples(
        _cmd_strategy(),
        st.booleans(),
        _st_errno,
        _st_remainder,
        _st_remainder,
    ),
    min_size=1,
    max_size=5,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ListHandler(logging.Handler):
    """Captures every ``LogRecord`` emitted at or above ``ERROR``.

    A bespoke handler avoids the cross-example state-leak hazard of
    pytest's ``caplog`` fixture under Hypothesis (records from a
    previous example would otherwise pollute the next example's
    assertions). The handler is reset between dispatch calls inside
    the test body via :meth:`clear`.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def clear(self) -> None:
        self.records.clear()


def _build_connected_driver() -> tuple[KmBoxNetDriver, FakeUdpSocket]:
    """Construct a ``KmBoxNetDriver`` whose handshake succeeds against a fake.

    Patches ``socket.socket`` for the duration of the constructor so
    the driver creates a :class:`FakeUdpSocket` instead of a real one,
    and attaches a successful :class:`FakeDevice` so the handshake
    ``recvfrom`` resolves to a zero-result-code reply. The patch is
    reverted before the function returns so any later socket use by
    the test body would (correctly) reach the real ``socket.socket`` —
    but the test only inspects ``driver.udp_socket._sock`` (already a
    ``FakeUdpSocket``) so no real socket is ever opened.

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
        # Disable encryption for this test so the wire packets are the
        # plaintext mouse-class layout (72 bytes), which keeps the
        # ``_dispatch_call`` execution path focused on the OSError
        # branch under test. Encryption-fault isolation is covered
        # separately by Property 17 / Task 4.5 in
        # ``test_dispatch_encrypt_isolation.py``.
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
    # The driver's ``UdpSocket`` wrapper holds the FakeUdpSocket as
    # ``_sock``; expose that fake so the test can poke
    # ``raise_on_send`` per step.
    return driver, sockets[0]


# ---------------------------------------------------------------------------
# Property 2
# ---------------------------------------------------------------------------


@settings(max_examples=50, deadline=None)
@given(scenario=_st_scenario)
def test_transmission_failure_isolation(scenario: list) -> None:
    """``OSError`` from ``sendto`` is isolated per Requirement 1.8.

    For each step in the generated scenario the driver is asked to
    dispatch a command with the underlying ``FakeUdpSocket.sendto``
    either healthy or configured to raise a single ``OSError(errno,
    "msg")``. ``BaseMouse.remainder_x`` / ``remainder_y`` are seeded
    to known sentinels before the call. After each step the test
    verifies, when the call was configured to fail:

      * ``driver.remainder_x`` and ``driver.remainder_y`` equal the
        pre-call sentinels.
      * Exactly one ERROR-level log record was emitted whose message
        names both the logical command name and ``errno=<n>``.
      * The underlying socket is still open
        (``fake_sock.closed == False``).
      * ``driver.initialized`` and ``driver.connection_status``
        equal the pre-call values (``True`` / ``CONNECTED``).
      * The failing-call path itself does not raise — the driver
        swallows the ``OSError`` per Requirement 1.8.
      * No new packet reached the wire (``len(fake_sock.sent)``
        unchanged) because ``sendto`` was the call that raised.
      * A *second* ``_dispatch_call`` immediately following, with
        ``raise_on_send`` cleared, completes without raising and
        delivers exactly one new packet to the wire — proving the
        recovery clause of the property.

    On non-failing steps the test verifies the call delivers exactly
    one packet to the wire and emits no ERROR-level log records.

    Validates: Requirements 1.8.
    """
    # 1. Build a connected driver against the fakes. The handshake
    # itself runs on the same FakeUdpSocket; once we return from
    # ``_build_connected_driver`` the driver is in CONNECTED state and
    # the socket has exactly one entry in ``.sent`` (the handshake).
    driver, fake_sock = _build_connected_driver()
    assert driver.connection_status == ConnectionStatus.CONNECTED, (
        "test pre-condition: handshake must succeed so _dispatch_call "
        "is not gated out by the status check; got %r"
        % (driver.connection_status,)
    )
    assert driver.initialized is True
    assert fake_sock.closed is False

    handshake_packet_count = len(fake_sock.sent)
    assert handshake_packet_count == 1, (
        "test pre-condition: exactly one handshake packet should have "
        "been emitted before any dispatch calls; got %d"
        % handshake_packet_count
    )

    # 2. Install a logging handler so we can count ERROR-level records
    # per dispatch call without pytest's ``caplog`` cross-example state
    # hazards under Hypothesis.
    driver_logger = logging.getLogger("input.kmbox_net_driver")
    handler = _ListHandler()
    driver_logger.addHandler(handler)
    # Make sure the logger itself does not filter ERROR records. The
    # default level for a custom-named logger is WARNING, which already
    # passes ERROR; setting it explicitly is defensive against test
    # ordering that might have lowered it.
    prior_level = driver_logger.level
    driver_logger.setLevel(logging.ERROR)

    try:
        # 3. Replay the generated scenario step by step.
        for step_index, ((cmd_name, args), should_fail, errno_value,
                         rem_x, rem_y) in enumerate(scenario):
            # Seed BaseMouse remainders with known sentinels so the
            # "unchanged after fault" assertion is a strict check
            # rather than a vacuous ``0.0 == 0.0``.
            driver.remainder_x = rem_x
            driver.remainder_y = rem_y

            # Snapshot every quantity we expect ``_dispatch_call`` to
            # leave untouched on the OSError path.
            sent_before = len(fake_sock.sent)
            initialized_before = driver.initialized
            status_before = driver.connection_status
            handler.clear()

            if should_fail:
                # Inject a single-shot OSError on the next sendto. The
                # ``raise_once=True`` flag means subsequent sendto
                # calls (the recovery dispatch below) succeed.
                fake_sock.raise_on_send = OSError(
                    errno_value, "test-injected transmission failure"
                )
                fake_sock.raise_once = True

                # ``_dispatch_call`` must NOT propagate the OSError —
                # Requirement 1.8 says it returns ``None`` after
                # logging.
                result = driver._dispatch_call(cmd_name, *args)
                assert result is None, (
                    "step %d (%r, should_fail=True): _dispatch_call "
                    "must return None on the OSError path; got %r."
                    % (step_index, cmd_name, result)
                )

                # Post-condition 1 — Requirement 1.8 first clause:
                # remainders unchanged. ``_dispatch_call`` does not
                # touch BaseMouse remainders even on the success
                # path, so the sentinels MUST round-trip exactly.
                assert driver.remainder_x == rem_x, (
                    "step %d (%r, should_fail=True): remainder_x "
                    "modified by failed dispatch (%r → %r) — "
                    "Requirement 1.8 requires remainders unchanged."
                    % (
                        step_index,
                        cmd_name,
                        rem_x,
                        driver.remainder_x,
                    )
                )
                assert driver.remainder_y == rem_y, (
                    "step %d (%r, should_fail=True): remainder_y "
                    "modified by failed dispatch (%r → %r) — "
                    "Requirement 1.8 requires remainders unchanged."
                    % (
                        step_index,
                        cmd_name,
                        rem_y,
                        driver.remainder_y,
                    )
                )

                # Post-condition 2 — Requirement 1.8 second clause:
                # exactly one ERROR-level log record naming the
                # command and the errno value.
                error_records = [
                    r for r in handler.records if r.levelno == logging.ERROR
                ]
                assert len(error_records) == 1, (
                    "step %d (%r, should_fail=True): expected exactly "
                    "one ERROR-level log record on the OSError path; "
                    "got %d (%r)."
                    % (
                        step_index,
                        cmd_name,
                        len(error_records),
                        [r.getMessage() for r in error_records],
                    )
                )
                message = error_records[0].getMessage()
                assert cmd_name in message, (
                    "step %d (%r, should_fail=True): error log entry "
                    "must name the originating logical command; got "
                    "%r." % (step_index, cmd_name, message)
                )
                # The driver's _dispatch_call OSError log includes
                # ``errno=<n>``; assert the literal errno value (as a
                # decimal) appears in the message. Using ``str(value)``
                # rather than ``"errno=%d" % value`` keeps the test
                # tolerant of minor formatting changes — but the
                # explicit "errno" substring assertion below confirms
                # the field is present, not just a stray digit
                # collision with another integer in the message.
                assert "errno" in message, (
                    "step %d (%r, should_fail=True): error log entry "
                    "must include an ``errno=`` field per Requirement "
                    "1.8; got %r." % (step_index, cmd_name, message)
                )
                assert str(errno_value) in message, (
                    "step %d (%r, should_fail=True): error log entry "
                    "must name the OSError errno value (%d); got %r."
                    % (step_index, cmd_name, errno_value, message)
                )

                # Post-condition 3 — Requirement 1.8 third clause:
                # socket still open. A transient transmission error
                # MUST NOT trigger a close, otherwise the driver
                # would have to re-run the handshake to recover.
                assert fake_sock.closed is False, (
                    "step %d (%r, should_fail=True): underlying UDP "
                    "socket was closed after an OSError — "
                    "Requirement 1.8 requires the socket left open "
                    "for recovery." % (step_index, cmd_name)
                )

                # Post-condition 4 — Requirement 1.8 fourth clause:
                # initialized and connection_status unchanged.
                assert driver.initialized is initialized_before, (
                    "step %d (%r, should_fail=True): initialized flag "
                    "changed (%r → %r) after a transmission fault — "
                    "Requirement 1.8 requires it unchanged."
                    % (
                        step_index,
                        cmd_name,
                        initialized_before,
                        driver.initialized,
                    )
                )
                assert driver.connection_status == status_before, (
                    "step %d (%r, should_fail=True): connection_status "
                    "changed (%r → %r) after a transmission fault — "
                    "Requirement 1.8 requires it unchanged."
                    % (
                        step_index,
                        cmd_name,
                        status_before,
                        driver.connection_status,
                    )
                )

                # Post-condition 5: no packet reached the wire — the
                # FakeUdpSocket.sendto raised before recording. (The
                # recovery dispatch below is what proves "the next
                # public-API send call does not raise".)
                assert len(fake_sock.sent) == sent_before, (
                    "step %d (%r, should_fail=True): a packet was "
                    "recorded on the wire despite OSError — the fake "
                    "socket should have raised before appending."
                    % (step_index, cmd_name)
                )

                # Post-condition 6 — Requirement 1.8 fifth clause:
                # the next public-API send call does not raise. Use a
                # known-good ``move`` dispatch so this part of the
                # property is exercised on every failing step
                # regardless of which command was generated. The
                # ``raise_once`` flag set above has cleared
                # ``raise_on_send``, so the second sendto succeeds.
                handler.clear()
                recovery_sent_before = len(fake_sock.sent)
                # Re-snapshot remainders so the recovery call's
                # remainder-untouched assertion is independent of the
                # failing-step assertions above (and to confirm
                # ``_dispatch_call`` itself never touches them on
                # the success path).
                rem_x_pre_recovery = driver.remainder_x
                rem_y_pre_recovery = driver.remainder_y
                driver._dispatch_call("move", 1, -1)

                assert driver.remainder_x == rem_x_pre_recovery, (
                    "step %d recovery (%r): remainder_x modified by "
                    "post-failure dispatch (%r → %r)."
                    % (
                        step_index,
                        cmd_name,
                        rem_x_pre_recovery,
                        driver.remainder_x,
                    )
                )
                assert driver.remainder_y == rem_y_pre_recovery, (
                    "step %d recovery (%r): remainder_y modified by "
                    "post-failure dispatch (%r → %r)."
                    % (
                        step_index,
                        cmd_name,
                        rem_y_pre_recovery,
                        driver.remainder_y,
                    )
                )
                assert len(fake_sock.sent) == recovery_sent_before + 1, (
                    "step %d recovery (%r): expected exactly one new "
                    "packet on the wire after the OSError-failed "
                    "dispatch; got %d → %d."
                    % (
                        step_index,
                        cmd_name,
                        recovery_sent_before,
                        len(fake_sock.sent),
                    )
                )
                recovery_errors = [
                    r for r in handler.records if r.levelno == logging.ERROR
                ]
                assert recovery_errors == [], (
                    "step %d recovery (%r): no ERROR-level log record "
                    "should be emitted on the recovery dispatch; got "
                    "%r."
                    % (
                        step_index,
                        cmd_name,
                        [r.getMessage() for r in recovery_errors],
                    )
                )
                # Driver invariants hold across the recovery dispatch
                # too — the success path of ``_dispatch_call`` MUST
                # NOT mutate any of them.
                assert driver.initialized is initialized_before
                assert driver.connection_status == status_before
                assert fake_sock.closed is False
                assert driver.use_encryption is False
            else:
                # Non-failing step: a healthy dispatch delivers
                # exactly one new packet and emits no ERROR records.
                assert fake_sock.raise_on_send is None, (
                    "step %d (%r, should_fail=False): test harness "
                    "invariant violated — raise_on_send should be "
                    "clear before a healthy dispatch; got %r."
                    % (step_index, cmd_name, fake_sock.raise_on_send)
                )

                driver._dispatch_call(cmd_name, *args)

                # Remainders left alone on the success path too.
                assert driver.remainder_x == rem_x
                assert driver.remainder_y == rem_y
                assert len(fake_sock.sent) == sent_before + 1, (
                    "step %d (%r, should_fail=False): expected one "
                    "new packet on the wire after a healthy dispatch; "
                    "got %d → %d."
                    % (
                        step_index,
                        cmd_name,
                        sent_before,
                        len(fake_sock.sent),
                    )
                )
                error_records = [
                    r for r in handler.records if r.levelno == logging.ERROR
                ]
                assert error_records == [], (
                    "step %d (%r, should_fail=False): no ERROR-level "
                    "log record should be emitted on the success "
                    "path; got %r."
                    % (
                        step_index,
                        cmd_name,
                        [r.getMessage() for r in error_records],
                    )
                )
                assert driver.initialized is initialized_before
                assert driver.connection_status == status_before
                assert fake_sock.closed is False
    finally:
        driver_logger.removeHandler(handler)
        driver_logger.setLevel(prior_level)
