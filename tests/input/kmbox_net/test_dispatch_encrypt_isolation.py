"""
Property test — Task 4.5 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 17: Encrypted-call fault isolation.

**Property 17: Encrypted-call fault isolation**

    *For any* sequence of public-API calls executed against a connected
    driver with ``use_encryption=True``, with an arbitrary subset of
    those calls configured to raise an exception inside
    :meth:`PacketEncryptor.encrypt`, the driver SHALL satisfy:

      * ``use_encryption`` remains ``True`` throughout — the encryption
        flag is never silently flipped to ``False`` as a recovery
        measure.
      * Each failing call emits *exactly one* error-level log record
        whose message names both the originating logical command and
        the exception type raised by ``encrypt``.
      * A subsequent successful encrypted-mode call still routes
        through ``PacketEncryptor.encrypt`` — there is no fallback to
        plaintext after a fault. The packet that reaches the wire is
        the encrypted form (128 bytes per the upstream ``sendto``
        length contract), not the shorter plaintext layout.
      * No UDP packet is emitted for the failing call (the fault
        prevents the ``sendto`` from running, which is the *intent*
        of fault isolation: the device never sees a malformed
        plaintext packet because the encryptor was supposed to wrap
        it).

**Validates: Requirements 9.5**

Implementation notes
--------------------

The test instantiates a real :class:`KmBoxNetDriver` so the
constructor exercises the full Init_Handshake send + recv path against
a :class:`FakeUdpSocket` and a :class:`FakeDevice` configured for a
successful reply. Because the command-layer wrappers (``_move``,
``_left``, …) still raise ``NotImplementedError`` at the point this
task lands, the test calls ``driver._dispatch_call("move", …)``
directly; ``_dispatch_call`` is the *single* chokepoint where
``self.use_encryption`` is read (Requirement 9.4) and where the
encrypted-call fault isolation is implemented, so exercising it
directly is sufficient to prove the property.

The socket / device setup is done inside the test body (rather than
through pytest fixtures) because Hypothesis runs the test body many
times per pytest invocation: function-scoped fixtures retain state
across examples and the :class:`FakeDevice` only publishes its
handshake reply once. Constructing fresh fakes per example keeps each
``KmBoxNetDriver()`` call deterministic.

The encryptor monkey-patch wraps the real ``PacketEncryptor.encrypt``
so it can be toggled per call: when the next call is configured to
fail, the wrapper raises a known ``InjectedEncryptError``; when not,
the wrapper delegates to the real transform so the wire bytes that
reach ``sendto`` are byte-for-byte identical to what the unmodified
driver would produce. This lets the test assert *both* that
``encrypt`` was invoked on the recovery path (Requirement 9.5 second
clause) *and* that the recovery packet matches the canonical
encrypted layout (no plaintext fallback).
"""

from __future__ import annotations

import logging
import socket as _stdlib_socket
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
    the same encryption path. Sampling across several increases the
    chance that the cmd-name substring assertion exercises distinct
    spellings rather than always seeing ``"move"``.
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


# Sequence of ``((cmd_name, args), should_fail)`` pairs. Bounded so
# Hypothesis examples stay quick — five steps is enough to interleave
# failing and succeeding calls and prove the fault-isolation invariants.
_st_scenario = st.lists(
    st.tuples(_cmd_strategy(), st.booleans()),
    min_size=1,
    max_size=5,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class InjectedEncryptError(RuntimeError):
    """Sentinel exception type raised by the patched ``encrypt``.

    Using a custom subclass means the test can assert that the
    error-level log entry names the *exact* exception type the
    encryptor raised — not just any ``RuntimeError``.
    """


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

    Patches ``socket.socket`` for the duration of the constructor so the
    driver creates a :class:`FakeUdpSocket` instead of a real one, and
    attaches a successful :class:`FakeDevice` so the handshake
    ``recvfrom`` resolves to a zero-result-code reply. The patch is
    reverted before the function returns so any later socket use by the
    test body would (correctly) reach the real ``socket.socket`` — but
    the test only inspects ``driver.udp_socket._sock`` (already a
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
        driver = KmBoxNetDriver(
            ip="192.168.2.188",
            port="41990",
            uuid="01FBC068",
            use_encryption=True,
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
# Property 17
# ---------------------------------------------------------------------------


@settings(max_examples=50, deadline=None)
@given(scenario=_st_scenario)
def test_encrypted_call_fault_isolation(scenario: list) -> None:
    """``PacketEncryptor.encrypt`` faults are isolated per Requirement 9.5.

    For each step in the generated scenario the driver is asked to
    dispatch a command with the encryptor either healthy or configured
    to raise ``InjectedEncryptError``. After each step the test
    verifies:

      * ``driver.use_encryption`` is still ``True``.
      * The failing-call path emits exactly one ERROR-level log record
        whose message names both the logical command and
        ``InjectedEncryptError``.
      * The failing-call path does not invoke ``UDP_Socket.sendto``.
      * The successful-call path invokes the (patched) ``encrypt``
        wrapper exactly once and emits exactly one packet whose length
        equals :data:`PacketEncryptor.BLOCK_SIZE_BYTES` (128 bytes —
        the canonical encrypted-packet length per the upstream
        ``sendto`` contract; the plaintext mouse-class layout is only
        72 bytes, so any byte-equal-to-plaintext fallback would fail
        this length assertion).

    After replaying the generated scenario, the test forces one final
    *successful* dispatch so that — even when the Hypothesis sequence
    happens to end with a failing call — the "next encrypted call
    still routes through encrypt" clause of the property is exercised
    on every example.

    Validates: Requirements 9.5.
    """
    # 1. Build a connected driver against the fakes. The handshake
    # itself is plaintext (Requirement 9.6), so it does NOT route
    # through ``PacketEncryptor.encrypt`` and therefore is unaffected
    # by the monkey-patch installed below.
    driver, fake_sock = _build_connected_driver()
    assert driver.connection_status == ConnectionStatus.CONNECTED, (
        "test pre-condition: handshake must succeed so _dispatch_call "
        "is not gated out by the status check; got %r"
        % (driver.connection_status,)
    )
    assert driver.use_encryption is True

    handshake_packet_count = len(fake_sock.sent)
    assert handshake_packet_count == 1, (
        "test pre-condition: exactly one handshake packet should have "
        "been emitted before any dispatch calls; got %d"
        % handshake_packet_count
    )

    # 2. Monkey-patch ``PacketEncryptor.encrypt`` with a wrapper that
    # records every invocation and either raises an injected exception
    # or delegates to the real transform. Using the *real* transform on
    # the success path means the bytes that reach ``sendto`` match the
    # canonical encrypted layout exactly, so a plaintext fallback is
    # detectable purely from packet length.
    real_encrypt = driver._packet_encryptor.encrypt
    encrypt_invocations: list[bytes] = []
    fail_next_flag = {"value": False}

    def patched_encrypt(plaintext: bytes) -> bytes:
        encrypt_invocations.append(bytes(plaintext))
        if fail_next_flag["value"]:
            raise InjectedEncryptError("test-injected encryption failure")
        return real_encrypt(plaintext)

    driver._packet_encryptor.encrypt = patched_encrypt  # type: ignore[method-assign]

    # 3. Install a logging handler so we can count ERROR-level records
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
        # 4. Replay the generated scenario step by step.
        for step_index, ((cmd_name, args), should_fail) in enumerate(scenario):
            # Reset per-step counters so assertions about "this call"
            # are not contaminated by the prior step.
            sent_before = len(fake_sock.sent)
            encrypts_before = len(encrypt_invocations)
            handler.clear()

            fail_next_flag["value"] = bool(should_fail)
            driver._dispatch_call(cmd_name, *args)

            # Post-condition 1 — Requirement 9.5 first clause:
            # ``use_encryption`` is never modified by a fault.
            assert driver.use_encryption is True, (
                "step %d (%r, should_fail=%s): use_encryption was "
                "flipped to False after dispatch — Requirement 9.5 "
                "forbids modifying the flag in response to an "
                "encryption fault." % (step_index, cmd_name, should_fail)
            )

            # ``_dispatch_call`` always reads ``use_encryption=True``
            # before invoking ``encrypt``, so encrypt MUST have been
            # called regardless of whether it then raised.
            assert len(encrypt_invocations) == encrypts_before + 1, (
                "step %d (%r, should_fail=%s): expected exactly one "
                "PacketEncryptor.encrypt invocation per dispatch call "
                "(use_encryption=True); got %d → %d."
                % (
                    step_index,
                    cmd_name,
                    should_fail,
                    encrypts_before,
                    len(encrypt_invocations),
                )
            )

            if should_fail:
                # Post-condition 2 — Requirement 9.5 second clause:
                # exactly one ERROR-level log record per failing call,
                # naming the originating command and exception type.
                error_records = [
                    r for r in handler.records if r.levelno == logging.ERROR
                ]
                assert len(error_records) == 1, (
                    "step %d (%r, should_fail=True): expected exactly "
                    "one ERROR-level log record on the encrypt-fault "
                    "path; got %d (%r)."
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
                assert "InjectedEncryptError" in message, (
                    "step %d (%r, should_fail=True): error log entry "
                    "must name the exception type "
                    "(InjectedEncryptError); got %r."
                    % (step_index, cmd_name, message)
                )

                # Post-condition 3: a failing encrypt prevents the
                # ``sendto`` from running — no plaintext fallback,
                # which is the *intent* of fault isolation. The wire
                # never sees a malformed packet.
                assert len(fake_sock.sent) == sent_before, (
                    "step %d (%r, should_fail=True): ``sendto`` was "
                    "invoked despite an encryption fault — this is a "
                    "plaintext fallback, which Requirement 9.5 "
                    "explicitly forbids."
                    % (step_index, cmd_name)
                )
            else:
                # Post-condition 4 — Requirement 9.5 third clause:
                # the successful encrypted-mode call still routes
                # through ``PacketEncryptor.encrypt``, and the wire
                # bytes are the canonical 128-byte encrypted form.
                assert len(fake_sock.sent) == sent_before + 1, (
                    "step %d (%r, should_fail=False): expected exactly "
                    "one packet on the wire after a successful "
                    "dispatch call; got %d → %d."
                    % (
                        step_index,
                        cmd_name,
                        sent_before,
                        len(fake_sock.sent),
                    )
                )
                emitted_packet, _addr = fake_sock.sent[-1]
                assert (
                    len(emitted_packet) == PacketEncryptor.BLOCK_SIZE_BYTES
                ), (
                    "step %d (%r, should_fail=False): emitted packet "
                    "length must equal the canonical encrypted-packet "
                    "size (%d bytes); got %d. A shorter packet "
                    "indicates a plaintext fallback, which "
                    "Requirement 9.5 forbids."
                    % (
                        step_index,
                        cmd_name,
                        PacketEncryptor.BLOCK_SIZE_BYTES,
                        len(emitted_packet),
                    )
                )

                # No error-level log record on the success path.
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

        # 5. Force one final successful encrypted dispatch so that —
        # regardless of how the Hypothesis-generated scenario ended —
        # the "next encrypted call still routes through encrypt" clause
        # of Requirement 9.5 is exercised on every example. This is
        # the strongest single check that no plaintext fallback was
        # latched: a successful call after the *last* generated step
        # must still produce a 128-byte encrypted packet.
        sent_before = len(fake_sock.sent)
        encrypts_before = len(encrypt_invocations)
        handler.clear()
        fail_next_flag["value"] = False
        driver._dispatch_call("move", 7, -3)

        assert driver.use_encryption is True
        assert len(encrypt_invocations) == encrypts_before + 1, (
            "final recovery dispatch: expected one encrypt invocation; "
            "got %d → %d."
            % (encrypts_before, len(encrypt_invocations))
        )
        assert len(fake_sock.sent) == sent_before + 1, (
            "final recovery dispatch: expected exactly one packet on "
            "the wire; got %d → %d."
            % (sent_before, len(fake_sock.sent))
        )
        emitted_packet, _addr = fake_sock.sent[-1]
        assert len(emitted_packet) == PacketEncryptor.BLOCK_SIZE_BYTES, (
            "final recovery dispatch: emitted packet must be the "
            "canonical 128-byte encrypted form; got %d bytes "
            "(plaintext fallback would be 72 bytes for 'move')."
            % len(emitted_packet)
        )
    finally:
        driver_logger.removeHandler(handler)
        driver_logger.setLevel(prior_level)
