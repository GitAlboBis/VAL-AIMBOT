"""
Property test — Task 5.2 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 19: ``__init__`` argument validation.

**Property 19: ``__init__`` argument validation**

    *For any* tuple ``(ip, port, uuid)`` where at least one of:

      * ``ip`` is not a 4-octet dotted-decimal string with each octet
        in the inclusive range ``[0, 255]``,
      * ``port`` does not parse to an int in ``[1, 65535]``,
      * ``uuid`` is not a non-empty string of length ``[1, 64]``,

    the driver SHALL satisfy:

      * ``initialized == False``,
      * ``connection_status == ConnectionStatus.FAILED`` (compare-equal
        to the literal ``"failed"`` per the ``str``-enum contract),
      * exactly one error-level log entry is emitted on the
        ``input.kmbox_net_driver`` logger naming the offending
        parameter and its value,
      * zero UDP packets are emitted on any ``FakeUdpSocket``.

**Validates: Requirements 8.8**

Implementation notes
--------------------

The driver checks ``ip`` → ``port`` → ``uuid`` in that order and
short-circuits on the first failed check, so the offending parameter
named in the log entry is the *first* invalid parameter in that
order. The test reproduces the same classification by calling the
driver's validation helpers directly (``_is_valid_ip``,
``_parse_port``, ``_is_valid_uuid``) — this keeps the property check
in lockstep with the implementation's classification of "invalid"
without re-deriving the rule set.

The socket / handler setup mirrors the inline pattern used in
``test_dispatch_encrypt_isolation.py``: ``socket.socket`` is
monkey-patched for the duration of the constructor call so any UDP
socket the driver attempts to create is captured and inspectable, and
a bespoke :class:`_ListHandler` collects ``ERROR``-level records to
avoid the cross-example state-leak hazard of ``caplog`` under
Hypothesis. Per Requirement 8.8 the driver must not even *construct*
a socket on the validation-failure path; the captured-sockets list is
typically empty. The "zero packets emitted" assertion is performed by
summing ``sent`` across every captured socket so a regression that
constructs a socket without sending is still permitted, while a
regression that sends a packet on a validation-failure path fails the
test.

The argument strategies cover both the *valid* and *invalid* arms of
each parameter — ``assume(not (ip_valid and port_valid and
uuid_valid))`` then filters out the all-valid tuples that would
exercise the handshake send path Property 19 deliberately does not
cover. Constraining the *valid uuid* arm to hexadecimal characters
ensures that the assertions never inadvertently exercise the
``StrToHex(uuid[:8], 4)`` failure path inside ``__init__`` (a
separate code path, not covered by Property 19).
"""

from __future__ import annotations

import logging
import socket as _stdlib_socket
import sys
from pathlib import Path

# Make the ``input`` package importable when pytest is launched from
# the repository root or any sub-directory (the driver ships as
# ``input/kmbox_net_driver.py`` at the project root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hypothesis import HealthCheck, assume, example, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from input.kmbox_net_driver import (  # noqa: E402  — sys.path manipulation above
    ConnectionStatus,
    KmBoxNetDriver,
    _is_valid_ip,
    _is_valid_uuid,
    _parse_port,
)
from tests.input.kmbox_net.conftest import FakeUdpSocket  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ListHandler(logging.Handler):
    """Captures every ``LogRecord`` emitted at or above ``ERROR``.

    A bespoke handler avoids the cross-example state-leak hazard of
    pytest's ``caplog`` fixture under Hypothesis (records from a
    previous example would otherwise pollute the next example's
    assertions). One handler is constructed and torn down per
    example.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        self.records.append(record)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


# ``valid_ip`` — well-formed 4-octet dotted-decimal IPv4 string. Each
# octet drawn from ``[0, 255]`` independently.
_valid_ip_st = st.builds(
    lambda a, b, c, d: f"{a}.{b}.{c}.{d}",
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
)

# ``invalid_ip`` — diverse non-string and malformed string forms. The
# strategy intentionally over-generates; ``_is_valid_ip`` is the final
# arbiter and the test's ``assume`` filters tuples where every
# parameter happens to land on the valid side.
_invalid_ip_st = st.one_of(
    st.none(),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.lists(st.integers(min_value=0, max_value=255), max_size=6),
    st.text(max_size=20),
    # Octet out of range in the first slot.
    st.builds(
        lambda a, b, c, d: f"{a}.{b}.{c}.{d}",
        st.integers(min_value=256, max_value=999),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
    ),
    # 3-octet form (too few).
    st.builds(
        lambda a, b, c: f"{a}.{b}.{c}",
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
    ),
    # 5-octet form (too many).
    st.builds(
        lambda a, b, c, d, e: f"{a}.{b}.{c}.{d}.{e}",
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
    ),
    st.just(""),
    st.just(" 192.168.1.1"),
    st.just("192.168.1.1 "),
    st.just("192. 168.1.1"),
    st.just("192.168.1.-1"),
    st.just("a.b.c.d"),
)

_ip_st = st.one_of(_valid_ip_st, _invalid_ip_st)


# ``valid_port`` — ``int`` or ASCII-decimal ``str`` form in ``[1, 65535]``.
_valid_port_st = st.one_of(
    st.integers(min_value=1, max_value=65535),
    st.integers(min_value=1, max_value=65535).map(str),
)
# ``invalid_port`` — out-of-range ints, ``bool``, ``None``, floats,
# malformed strings (whitespace, signs, hex, empty).
_invalid_port_st = st.one_of(
    st.integers(min_value=-1000, max_value=0),
    st.integers(min_value=65536, max_value=200000),
    st.booleans(),
    st.none(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=8),
    st.just(""),
    st.just(" 41990"),
    st.just("41990 "),
    st.just("+41990"),
    st.just("0x10"),
    st.just("-1"),
    st.lists(st.integers()),
)
_port_st = st.one_of(_valid_port_st, _invalid_port_st)


# ``valid_uuid`` — hexadecimal-only string of length ``[1, 64]``. The
# hex constraint ensures the *valid* arm never trips the
# ``StrToHex(uuid[:8], 4)`` failure path inside ``__init__`` (a code
# path that is NOT part of Property 19's contract).
_valid_uuid_st = st.text(
    alphabet="0123456789abcdefABCDEF", min_size=1, max_size=64
)
# ``invalid_uuid`` — empty string, oversize string, and non-string
# types. The length-failure path inside ``_is_valid_uuid`` is what we
# want to exercise; the empty-string and oversize cases trigger it
# directly.
_invalid_uuid_st = st.one_of(
    st.just(""),
    st.text(min_size=65, max_size=200),
    st.none(),
    st.integers(),
    st.lists(st.integers()),
    st.floats(allow_nan=True, allow_infinity=True),
)
_uuid_st = st.one_of(_valid_uuid_st, _invalid_uuid_st)


# ---------------------------------------------------------------------------
# Property 19
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.filter_too_much,
        HealthCheck.too_slow,
    ],
)
@given(ip=_ip_st, port=_port_st, uuid=_uuid_st)
# Hand-picked examples covering each offending-parameter case so the
# property is exercised on at least one tuple per category even if
# Hypothesis's random sampling skips them.
@example(ip="not.an.ip", port=41990, uuid="01FBC068")          # ip invalid (form)
@example(ip="256.0.0.0", port="41990", uuid="01FBC068")        # ip invalid (octet)
@example(ip="1.2.3", port="41990", uuid="01FBC068")            # ip invalid (3 octets)
@example(ip=None, port="41990", uuid="01FBC068")               # ip invalid (type)
@example(ip="192.168.2.188", port=0, uuid="01FBC068")          # port invalid (zero)
@example(ip="192.168.2.188", port=70000, uuid="01FBC068")      # port invalid (range)
@example(ip="192.168.2.188", port=True, uuid="01FBC068")       # port invalid (bool)
@example(ip="192.168.2.188", port="0x10", uuid="01FBC068")     # port invalid (string form)
@example(ip="192.168.2.188", port=None, uuid="01FBC068")       # port invalid (type)
@example(ip="192.168.2.188", port="41990", uuid="")            # uuid invalid (empty)
@example(ip="192.168.2.188", port="41990", uuid="x" * 65)      # uuid invalid (oversize)
@example(ip="192.168.2.188", port="41990", uuid=None)          # uuid invalid (type)
def test_init_argument_validation(ip, port, uuid) -> None:
    """``KmBoxNetDriver.__init__`` rejects invalid args per Requirement 8.8.

    For each generated ``(ip, port, uuid)`` tuple where at least one
    component fails the Requirement 8.8 rule set (classified via
    ``_is_valid_ip`` / ``_parse_port`` / ``_is_valid_uuid`` so the
    test agrees with the implementation about the boundary), the
    constructor must:

      * leave ``initialized`` set to ``False``;
      * leave ``connection_status`` set to ``ConnectionStatus.FAILED``
        (which compares equal to the literal ``"failed"`` thanks to
        the ``str``-enum subclassing);
      * emit exactly one ``ERROR``-level log record on the
        ``input.kmbox_net_driver`` logger whose formatted message
        contains both the offending parameter name (``ip`` / ``port``
        / ``uuid``) and the ``repr()`` of the offending value
        (matched precisely as the ``f"got {value!r}"`` substring the
        implementation produces via ``%r`` formatting);
      * emit zero UDP packets on any socket constructed during
        ``__init__``.

    Validates: Requirement 8.8.
    """
    # Classify each parameter. The driver checks ``ip`` first, then
    # ``port``, then ``uuid``, short-circuiting on the first failure
    # — so the test reproduces that order to compute the *expected*
    # offending parameter name and value.
    ip_valid = _is_valid_ip(ip)
    port_valid = _parse_port(port) is not None
    uuid_valid = _is_valid_uuid(uuid)

    # Property 19 only covers tuples where at least one parameter
    # fails Requirement 8.8. Tuples where every parameter passes
    # would exercise the handshake send path (a different property,
    # see Property 14 ``test_init_handshake_plaintext.py``); skip
    # them via ``assume``.
    assume(not (ip_valid and port_valid and uuid_valid))

    if not ip_valid:
        offending_name = "ip"
        offending_value = ip
    elif not port_valid:
        offending_name = "port"
        offending_value = port
    else:
        offending_name = "uuid"
        offending_value = uuid

    # ── Log-handler installation ──────────────────────────────────
    #
    # A bespoke ``ERROR``-level handler avoids the cross-example
    # state-leak hazard of ``caplog`` under Hypothesis. The handler
    # is detached in the ``finally`` block so a failed example does
    # not stick around to pollute the next one.
    driver_logger = logging.getLogger("input.kmbox_net_driver")
    handler = _ListHandler()
    driver_logger.addHandler(handler)
    prior_level = driver_logger.level
    driver_logger.setLevel(logging.ERROR)

    # ── Socket monkey-patch ───────────────────────────────────────
    #
    # Per Requirement 8.8 the validation-failure path must emit zero
    # UDP packets. The driver also typically does not *construct* a
    # socket on this path (the socket object is built only after
    # validation passes), so the captured ``sockets`` list is
    # ordinarily empty. Wrapping ``socket.socket`` is still useful as
    # a guard rail: a regression that creates a socket *and* sends
    # on it is caught by the ``total_sent == 0`` check below; a
    # regression that creates a socket but never sends is permitted
    # (it does not violate the property).
    sockets: list[FakeUdpSocket] = []

    def _factory(family: int = _stdlib_socket.AF_INET,
                 type_: int = _stdlib_socket.SOCK_DGRAM,
                 proto: int = 0,
                 fileno: int | None = None,
                 **_kwargs) -> FakeUdpSocket:
        sock = FakeUdpSocket(family=family, type_=type_)
        sock.proto = proto
        sockets.append(sock)
        return sock

    original = _stdlib_socket.socket
    _stdlib_socket.socket = _factory  # type: ignore[assignment]
    try:
        driver = KmBoxNetDriver(
            ip=ip,
            port=port,
            uuid=uuid,
            use_encryption=True,
        )
    finally:
        _stdlib_socket.socket = original  # type: ignore[assignment]
        driver_logger.removeHandler(handler)
        driver_logger.setLevel(prior_level)

    # ── Post-condition 1: terminal FAILED state ───────────────────
    assert driver.initialized is False, (
        "Requirement 8.8: driver.initialized must be False after a "
        "validation-failure constructor; got %r"
        % (driver.initialized,)
    )
    assert driver.connection_status == ConnectionStatus.FAILED, (
        "Requirement 8.8: connection_status must equal "
        "ConnectionStatus.FAILED on the validation-failure path; "
        "got %r" % (driver.connection_status,)
    )
    # ``ConnectionStatus`` subclasses ``str`` so the GUI Configuration
    # page can compare against the bare literal ``"failed"`` from
    # Requirement 10's vocabulary without an explicit ``.value``.
    assert driver.connection_status == "failed", (
        "ConnectionStatus.FAILED must compare equal to the literal "
        "string 'failed' (str-enum contract per design.md "
        "'Threading model'); got %r" % (driver.connection_status,)
    )

    # ── Post-condition 2: exactly one ERROR record naming the
    # offending parameter and its value ────────────────────────────
    error_records = [
        r for r in handler.records if r.levelno == logging.ERROR
    ]
    assert len(error_records) == 1, (
        "Requirement 8.8: expected exactly one ERROR-level log "
        "record on the validation-failure path; got %d (%r)."
        % (
            len(error_records),
            [r.getMessage() for r in error_records],
        )
    )
    message = error_records[0].getMessage()

    # The implementation's three validation-failure log calls each
    # name the parameter in single quotes (``"'ip'"`` /  ``"'port'"``
    # / ``"'uuid'"``); the bare ``offending_name`` substring check
    # is sufficient and accommodates either spelling.
    assert offending_name in message, (
        "Requirement 8.8: error log entry must name the offending "
        "parameter %r; got %r." % (offending_name, message)
    )

    # The implementation logs the offending value via ``%r``
    # formatting after the literal ``"got "`` — match that exact
    # substring so a generic ``repr(value) in message`` does not
    # spuriously pass when the same digits happen to appear in
    # surrounding boilerplate (e.g. ``"[1, 65535]"`` for the port
    # range diagnostic, or ``"[0, 255]"`` for the IP-octet
    # diagnostic).
    expected_value_substring = f"got {offending_value!r}"
    assert expected_value_substring in message, (
        "Requirement 8.8: error log entry must name the offending "
        "value via the implementation's ``got %%r`` format "
        "(expected substring %r); got %r."
        % (expected_value_substring, message)
    )

    # ── Post-condition 3: zero UDP packets emitted ────────────────
    total_sent = sum(len(s.sent) for s in sockets)
    assert total_sent == 0, (
        "Requirement 8.8: zero UDP packets must be emitted on the "
        "validation-failure path; got %d packet(s) across %d "
        "captured socket(s)."
        % (total_sent, len(sockets))
    )
