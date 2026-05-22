"""
Property test — Task 7.7 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 8: Invalid-parameter rejection.

**Property 8: Invalid-parameter rejection**

    *For each* command in ``{_move, _left, _right, _middle, _wheel,
    _mouse, _move_auto, _move_beizer, _keydown, _keyup, monitor,
    setconfig, mask_mouse_left}`` and *for each* argument tuple that
    contains at least one out-of-range or wrong-type value, invoking
    the command SHALL satisfy:

      * the call raises an exception (``TypeError`` for a wrong-type
        value, ``ValueError`` for an out-of-range value) whose
        message names at least one offending parameter and at least
        one offending value;
      * zero UDP packets are emitted on the underlying
        :class:`FakeUdpSocket` beyond the post-handshake baseline.

**Validates: Requirements 4.5, 4.9, 4.10, 4.11, 5.5, 5.7, 6.3, 7.3, 7.6**

Each requirement enumerated above prescribes argument-validation
contracts on a specific public-API entry point of the driver:

    * ``4.5``  — ``_mouse(btn, x, y, wheel)`` rejects out-of-range
      tuples;
    * ``4.9``  — ``_move(x, y)`` rejects non-strict-int / out-of-range
      arguments;
    * ``4.10`` — ``_left`` / ``_right`` / ``_middle`` reject any
      ``isdown`` outside ``{0, 1}`` and ``_wheel`` rejects zero,
      out-of-range, or non-integer arguments;
    * ``4.11`` — ``_move_auto`` and ``_move_beizer`` reject any
      argument outside the per-parameter ranges defined by
      Requirements 4.6 / 4.7;
    * ``5.5``  — ``key_press`` rejects out-of-range ``hold_ms``
      (covered by ``test_keypress_stuck_key_safety.py`` / Task 8.7;
      this property's coverage of ``5.5`` is via ``_keydown`` /
      ``_keyup`` rejecting out-of-range ``hid_code``, since
      ``key_press`` ultimately dispatches through them);
    * ``5.7``  — ``_keydown`` / ``_keyup`` reject out-of-range
      ``hid_code``;
    * ``6.3``  — ``monitor(port)`` rejects ``port`` not in
      ``{0} ∪ [1024, 49151]``;
    * ``7.3``  — ``setconfig(ip, port)`` rejects malformed ``ip`` or
      out-of-range ``port``;
    * ``7.6``  — ``mask_mouse_left(state)`` rejects ``state`` not in
      ``{0, 1}``.

Property 8 collapses every one of those rejection contracts into a
single behavioural claim — *any* invalid argument tuple raises and
emits no UDP packet — so the test exercises every named command on
several deliberately-corrupted argument tuples per example.

Implementation notes
--------------------

The test instantiates a real :class:`KmBoxNetDriver` against a
:class:`FakeUdpSocket` + :class:`FakeDevice` configured for a
successful handshake. Constructing a *connected* driver matters
because the rejection contract is a *pre-dispatch* check (validation
runs before any ``Send_Lock`` acquisition or ``_dispatch_call``
invocation, per the design's "Error Handling" section). A connected
driver makes the "zero packets emitted" assertion meaningful: if
validation accidentally let a tuple through, the dispatch chain
would build, encrypt, and ``sendto`` the packet, growing
``fake_sock.sent`` past the handshake baseline.

The handshake itself emits exactly one packet during construction;
the test snapshots that count and asserts it remains constant after
every rejected call. Per-step the snapshot is compared to the
immediately-prior count (so a regression that leaks one packet
through on step 3 of 5 is caught even if subsequent steps re-stabilize
the count via lucky validation on the unrelated args).

The socket / handshake setup is done inline (rather than through
pytest fixtures) because Hypothesis runs the test body many times per
pytest invocation: function-scoped fixtures retain state across
examples and the :class:`FakeDevice` only publishes its handshake
reply once. Constructing fresh fakes per example keeps each
``KmBoxNetDriver()`` call deterministic. This mirrors the
``_build_connected_driver`` pattern already used in
``test_dispatch_encrypt_isolation.py`` /
``test_dispatch_oserror_isolation.py`` /
``test_status_gated_send.py``.

Strategy design
---------------

For each named command the test defines a composite Hypothesis
strategy that:

    1. draws a *valid* value for every parameter from the same range
       used by the existing valid-path property tests (Property 7,
       Property 9, Property 13, Property 19);
    2. picks exactly *one* parameter to corrupt, drawn from a
       per-command invalid strategy that covers wrong-type cases
       (``bool``, ``str``, ``None``, ``float``, ``list``) and
       out-of-range numeric cases;
    3. emits a 4-tuple ``(method_name, args, offending_name,
       offending_value)`` recording exactly which parameter and
       value the validator is expected to flag.

Corrupting exactly one parameter (rather than multiple) makes the
``offending_name`` deterministic: each command's validator walks its
parameters in declaration order and short-circuits on the first
failure (see ``_move`` / ``_move_beizer`` / ``setconfig`` in
``input/kmbox_net_driver.py``), so the parameter the test corrupted
is the one named in the resulting exception message. A test that
corrupts multiple parameters would still detect a violation, but
would lose the precise correspondence between corruption site and
diagnostic message that makes the property useful.

The match against the message uses two complementary substrings:

    * ``f"'{offending_name}'"`` — the implementation always renders
      the parameter name in single quotes (either via ``%r`` /
      ``!r`` formatting on a literal name, or via ``f"{name!r}"``
      inside the ``_move_beizer`` / ``_move_auto`` validation
      loops). Quoting it makes the assertion robust to common
      substrings (e.g. the letter ``x`` appearing inside
      ``_move_auto`` would otherwise spuriously satisfy a bare
      ``"x" in msg`` check).
    * ``f"got {offending_value!r}"`` *or* ``f"={offending_value!r}"``
      — the implementation embeds the offending value via either
      the ``ValueError`` style ``"... (got VALUE)"`` or the
      ``TypeError`` style ``"... (got TYPE=VALUE)"``. Allowing
      either substring covers both code paths without coupling the
      assertion to which of the two raised. ``repr(value)`` rather
      than ``str(value)`` matches the implementation's ``%r`` /
      ``!r`` formatting verbatim.
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

import pytest  # noqa: E402  — sys.path manipulation above
from hypothesis import HealthCheck, given, settings  # noqa: E402
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
# Wrong-type generators (rejected by ``_is_strict_int`` / ``isinstance``)
# ---------------------------------------------------------------------------


# Strict-int validation in the driver uses
# ``isinstance(value, int) and not isinstance(value, bool)``; bool is
# explicitly rejected even though ``True``/``False`` are int subclasses
# in Python (so ``True`` would otherwise sneak past as ``1`` and
# silently encode a button-state on every move). This strategy
# enumerates the categories of values that ``_is_strict_int`` rejects:
# bool, float (any), str (any), None, and list (a stand-in for
# arbitrary non-numeric containers).
_st_wrong_type_for_int: st.SearchStrategy = st.one_of(
    st.booleans(),
    st.floats(
        allow_nan=False,
        allow_infinity=False,
        min_value=-1000.0,
        max_value=1000.0,
    ),
    st.text(
        min_size=0,
        max_size=6,
        # Restrict to printable ASCII so the ``repr(value)`` substring
        # check is unambiguous on every console encoding.
        alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    ),
    st.none(),
    st.lists(st.integers(min_value=-10, max_value=10), max_size=3),
)


def _out_of_range_int(low: int, high: int) -> st.SearchStrategy:
    """Strategy for ints strictly outside the inclusive range ``[low, high]``.

    Generates either a value above ``high`` (up to ``high + 100_000``)
    or below ``low`` (down to ``low - 100_000``). The 100_000 bound
    keeps the values readable in counter-examples and well below
    ``sys.maxsize``.
    """
    return st.one_of(
        st.integers(min_value=high + 1, max_value=high + 100_000),
        st.integers(min_value=low - 100_000, max_value=low - 1),
    )


# ---------------------------------------------------------------------------
# Valid-value strategies (used to fill the *non*-corrupted slots so the
# command would otherwise reach ``_dispatch_call`` cleanly)
# ---------------------------------------------------------------------------


# ``valid_xy`` — signed mouse delta in ``[-32768, 32768]`` (Req 4.1).
_v_xy = st.integers(min_value=-32768, max_value=32768)
# ``valid_isdown`` — strict ``{0, 1}`` per Req 4.10 / 7.6.
_v_isdown = st.integers(min_value=0, max_value=1)
# ``valid_wheel`` — non-zero in ``[-128, 128]`` per Req 4.3 / 4.10. The
# ``_wheel`` validator rejects zero (the upstream wiki documents the
# method as taking a non-zero amount), so a "valid" wheel must omit 0.
_v_wheel_nonzero = st.integers(min_value=-128, max_value=128).filter(
    lambda v: v != 0
)
# ``valid_wheel_for_mouse`` — full ``[-128, 128]`` (zero allowed for
# the combined ``_mouse`` packet per Req 4.4).
_v_wheel_for_mouse = st.integers(min_value=-128, max_value=128)
# ``valid_button_mask`` — full 8-bit bitmask per Req 4.4.
_v_btn_mask = st.integers(min_value=0, max_value=255)
# ``valid_ms`` — ``[1, 65535]`` per Req 4.6 / 4.7.
_v_ms = st.integers(min_value=1, max_value=65535)
# ``valid_hid`` — ``[0, 255]`` per Req 5.7.
_v_hid = st.integers(min_value=0, max_value=255)
# ``valid_monitor_port`` — ``0`` (disable) or ``[1024, 49151]`` per
# Req 6.1 / 6.2.
_v_monitor_port = st.one_of(
    st.just(0),
    st.integers(min_value=1024, max_value=49151),
)
# ``valid_setconfig_port`` — ``[1, 65535]`` per Req 7.2.
_v_setconfig_port = st.integers(min_value=1, max_value=65535)
# ``valid_ip`` — well-formed 4-octet dotted-decimal. A handful of
# canonical samples is sufficient: this property exercises *invalid*
# values, so the *valid* sentinel only needs to satisfy
# ``_is_valid_ip`` cleanly when paired with an invalid port.
_v_ip = st.sampled_from(
    [
        "0.0.0.0",
        "127.0.0.1",
        "192.168.2.188",
        "255.255.255.255",
    ]
)


# ---------------------------------------------------------------------------
# Invalid-value strategies (per-parameter)
# ---------------------------------------------------------------------------


# Generic "invalid strict-int in [low, high]" — wrong type *or*
# out-of-range integer. Used for ``x``, ``y``, ``btn``, ``ms``,
# ``hid_code``, ``port`` (setconfig).
def _invalid_strict_int_in(low: int, high: int) -> st.SearchStrategy:
    return st.one_of(
        _st_wrong_type_for_int,
        _out_of_range_int(low, high),
    )


_inv_xy = _invalid_strict_int_in(-32768, 32768)
_inv_btn = _invalid_strict_int_in(0, 255)
_inv_ms = _invalid_strict_int_in(1, 65535)
_inv_hid = _invalid_strict_int_in(0, 255)
_inv_setconfig_port = _invalid_strict_int_in(1, 65535)

# ``_inv_isdown`` — ``isdown`` must be exactly ``0`` or ``1`` per Req
# 4.10. Out-of-range ints in ``[2, 200]`` and negatives in ``[-200,
# -1]`` cover the "any other int" arm; ``_st_wrong_type_for_int``
# covers the wrong-type arm.
_inv_isdown = st.one_of(
    _st_wrong_type_for_int,
    st.integers(min_value=2, max_value=200),
    st.integers(min_value=-200, max_value=-1),
)
# ``_inv_state`` — same shape as ``_inv_isdown`` (Req 7.6).
_inv_state = _inv_isdown

# ``_inv_wheel`` — three failure modes for ``_wheel(amount)`` per
# Req 4.10: wrong type, zero, or out-of-range int. Note ``st.just(0)``
# is the *only* in-range invalid integer for ``_wheel``; the upstream
# wiki documents the method as taking a non-zero ``amount`` and the
# implementation rejects it explicitly.
_inv_wheel = st.one_of(
    _st_wrong_type_for_int,
    st.just(0),
    _out_of_range_int(-128, 128),
)
# ``_inv_wheel_for_mouse`` — for the combined ``_mouse(btn, x, y,
# wheel)`` packet, ``wheel == 0`` is *valid* (Req 4.4 makes no
# zero-exclusion); only wrong type or out-of-range range is invalid.
_inv_wheel_for_mouse = st.one_of(
    _st_wrong_type_for_int,
    _out_of_range_int(-128, 128),
)

# ``_inv_monitor_port`` — Req 6.3 rejects any int outside
# ``{0} ∪ [1024, 49151]``. Wrong-type values also fail.
_inv_monitor_port = st.one_of(
    _st_wrong_type_for_int,
    st.integers(min_value=1, max_value=1023),
    st.integers(min_value=49152, max_value=200_000),
    st.integers(min_value=-200_000, max_value=-1),
)

# ``_inv_ip`` — Req 7.3 rejects any non-string or any string that is
# not a 4-octet dotted-decimal with each octet in ``[0, 255]``.
_inv_ip = st.one_of(
    st.none(),
    st.integers(),
    st.lists(st.integers(min_value=0, max_value=255), max_size=6),
    st.just(""),
    st.just("not.an.ip"),
    st.just("1.2.3"),
    st.just("256.1.2.3"),
    st.just("1.2.3.4.5"),
    st.just(" 192.168.1.1"),
    st.just("a.b.c.d"),
)


# ---------------------------------------------------------------------------
# Per-command corruption strategies
# ---------------------------------------------------------------------------
#
# Each composite below draws a *valid* tuple of arguments for the
# named command and then corrupts exactly one parameter, returning
# ``(method_name, args, offending_name, offending_value)``.
#
# The validator in each command short-circuits on the first invalid
# parameter (in declaration order), so corrupting exactly one
# parameter pins down which name is expected in the diagnostic
# message.


@st.composite
def _gen_move_invalid(draw) -> tuple:
    which = draw(st.sampled_from(["x", "y"]))
    if which == "x":
        bad = draw(_inv_xy)
        return ("_move", (bad, draw(_v_xy)), "x", bad)
    bad = draw(_inv_xy)
    return ("_move", (draw(_v_xy), bad), "y", bad)


@st.composite
def _gen_left_invalid(draw) -> tuple:
    bad = draw(_inv_isdown)
    return ("_left", (bad,), "isdown", bad)


@st.composite
def _gen_right_invalid(draw) -> tuple:
    bad = draw(_inv_isdown)
    return ("_right", (bad,), "isdown", bad)


@st.composite
def _gen_middle_invalid(draw) -> tuple:
    bad = draw(_inv_isdown)
    return ("_middle", (bad,), "isdown", bad)


@st.composite
def _gen_wheel_invalid(draw) -> tuple:
    bad = draw(_inv_wheel)
    return ("_wheel", (bad,), "amount", bad)


@st.composite
def _gen_mouse_invalid(draw) -> tuple:
    # Validation order in ``_mouse``: btn → x → y → wheel (type
    # checks first, then range checks in the same order). Corrupt
    # exactly one slot and label it as the offending parameter.
    which = draw(st.sampled_from(["btn", "x", "y", "wheel"]))
    btn = draw(_v_btn_mask)
    x = draw(_v_xy)
    y = draw(_v_xy)
    wheel = draw(_v_wheel_for_mouse)
    if which == "btn":
        bad = draw(_inv_btn)
        return ("_mouse", (bad, x, y, wheel), "btn", bad)
    if which == "x":
        bad = draw(_inv_xy)
        return ("_mouse", (btn, bad, y, wheel), "x", bad)
    if which == "y":
        bad = draw(_inv_xy)
        return ("_mouse", (btn, x, bad, wheel), "y", bad)
    bad = draw(_inv_wheel_for_mouse)
    return ("_mouse", (btn, x, y, bad), "wheel", bad)


@st.composite
def _gen_move_auto_invalid(draw) -> tuple:
    # Validation order: x → y → ms (type then range).
    which = draw(st.sampled_from(["x", "y", "ms"]))
    x = draw(_v_xy)
    y = draw(_v_xy)
    ms = draw(_v_ms)
    if which == "x":
        bad = draw(_inv_xy)
        return ("_move_auto", (bad, y, ms), "x", bad)
    if which == "y":
        bad = draw(_inv_xy)
        return ("_move_auto", (x, bad, ms), "y", bad)
    bad = draw(_inv_ms)
    return ("_move_auto", (x, y, bad), "ms", bad)


@st.composite
def _gen_move_beizer_invalid(draw) -> tuple:
    # Validation order in ``_move_beizer`` (declaration order): x, y,
    # ms, x1, y1, x2, y2 for type checks; then x, y, x1, y1, x2, y2
    # for range checks (ms range checked last). Corrupt exactly one
    # slot — the validator's first detected violation matches it.
    which = draw(st.sampled_from(["x", "y", "ms", "x1", "y1", "x2", "y2"]))
    x = draw(_v_xy)
    y = draw(_v_xy)
    ms = draw(_v_ms)
    x1 = draw(_v_xy)
    y1 = draw(_v_xy)
    x2 = draw(_v_xy)
    y2 = draw(_v_xy)
    if which == "x":
        bad = draw(_inv_xy)
        return ("_move_beizer", (bad, y, ms, x1, y1, x2, y2), "x", bad)
    if which == "y":
        bad = draw(_inv_xy)
        return ("_move_beizer", (x, bad, ms, x1, y1, x2, y2), "y", bad)
    if which == "ms":
        bad = draw(_inv_ms)
        return ("_move_beizer", (x, y, bad, x1, y1, x2, y2), "ms", bad)
    if which == "x1":
        bad = draw(_inv_xy)
        return ("_move_beizer", (x, y, ms, bad, y1, x2, y2), "x1", bad)
    if which == "y1":
        bad = draw(_inv_xy)
        return ("_move_beizer", (x, y, ms, x1, bad, x2, y2), "y1", bad)
    if which == "x2":
        bad = draw(_inv_xy)
        return ("_move_beizer", (x, y, ms, x1, y1, bad, y2), "x2", bad)
    bad = draw(_inv_xy)
    return ("_move_beizer", (x, y, ms, x1, y1, x2, bad), "y2", bad)


@st.composite
def _gen_keydown_invalid(draw) -> tuple:
    bad = draw(_inv_hid)
    return ("_keydown", (bad,), "hid_code", bad)


@st.composite
def _gen_keyup_invalid(draw) -> tuple:
    bad = draw(_inv_hid)
    return ("_keyup", (bad,), "hid_code", bad)


@st.composite
def _gen_monitor_invalid(draw) -> tuple:
    bad = draw(_inv_monitor_port)
    return ("monitor", (bad,), "port", bad)


@st.composite
def _gen_setconfig_invalid(draw) -> tuple:
    # Validation order: ip first (TypeError if not str, then
    # ValueError if not 4-octet), then port (TypeError if not strict
    # int, then ValueError if out of range). Corrupting only ip
    # leaves port valid; corrupting only port leaves ip valid.
    which = draw(st.sampled_from(["ip", "port"]))
    if which == "ip":
        bad = draw(_inv_ip)
        return ("setconfig", (bad, draw(_v_setconfig_port)), "ip", bad)
    bad = draw(_inv_setconfig_port)
    return ("setconfig", (draw(_v_ip), bad), "port", bad)


@st.composite
def _gen_mask_mouse_left_invalid(draw) -> tuple:
    bad = draw(_inv_state)
    return ("mask_mouse_left", (bad,), "state", bad)


# Union strategy — picks one of the 13 commands uniformly per step.
_st_invalid_call: st.SearchStrategy = st.one_of(
    _gen_move_invalid(),
    _gen_left_invalid(),
    _gen_right_invalid(),
    _gen_middle_invalid(),
    _gen_wheel_invalid(),
    _gen_mouse_invalid(),
    _gen_move_auto_invalid(),
    _gen_move_beizer_invalid(),
    _gen_keydown_invalid(),
    _gen_keyup_invalid(),
    _gen_monitor_invalid(),
    _gen_setconfig_invalid(),
    _gen_mask_mouse_left_invalid(),
)

# Sequence of corrupted calls. Bounded to keep examples quick — five
# steps is enough to interleave commands and prove the property holds
# uniformly across the full named set within a single example.
_st_scenario = st.lists(_st_invalid_call, min_size=1, max_size=5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_connected_driver() -> tuple[KmBoxNetDriver, FakeUdpSocket]:
    """Construct a :class:`KmBoxNetDriver` whose handshake succeeds.

    Patches ``socket.socket`` for the duration of the constructor so
    the driver creates a :class:`FakeUdpSocket` instead of a real
    one, and attaches a :class:`FakeDevice` so the handshake
    ``recvfrom`` resolves to a zero-result-code reply. The patch is
    reverted before the function returns.

    The returned driver is in :data:`ConnectionStatus.CONNECTED`
    with ``initialized == True``; ``fake_sock.sent`` already holds
    exactly one entry (the handshake packet emitted from inside
    ``__init__``). Subsequent rejected calls in the test body must
    NOT grow that count.

    Returns:
        Tuple ``(driver, fake_sock)``. The fake socket is the
        underlying transport bound by the driver during
        construction; ``fake_sock.sent`` records every UDP packet
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
        # Disable encryption so a counter-factual "validation passed"
        # bug emits the readable plaintext mouse-class layout instead
        # of the 128-byte encrypted form, making any escape easier to
        # diagnose. Property 8 is independent of ``use_encryption``
        # (validation runs *before* the dispatch chain reads the
        # flag), so either setting would work.
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
# Property 8
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(scenario=_st_scenario)
def test_invalid_parameter_rejection(scenario: list) -> None:
    """Each of the 13 named commands rejects an invalid argument tuple.

    For every step ``(method_name, args, offending_name,
    offending_value)`` in the generated scenario, the call must:

      * raise either :class:`TypeError` (wrong-type argument) or
        :class:`ValueError` (out-of-range argument) — the two
        exception classes the driver's validators are documented to
        throw across Requirements 4.5 / 4.9 / 4.10 / 4.11 / 5.7 /
        6.3 / 7.3 / 7.6;
      * include the offending parameter name in the exception
        message (matched as the quoted form ``f"'{name}'"`` so the
        check is robust to common substrings appearing elsewhere in
        the diagnostic);
      * include the offending value in the exception message,
        matched as either the ``ValueError`` style ``"got VALUE"`` or
        the ``TypeError`` style ``"=VALUE"`` (where ``VALUE`` is
        ``repr(offending_value)``, since the implementation embeds
        the value via ``%r`` / ``!r`` formatting in both code
        paths);
      * not grow the underlying :class:`FakeUdpSocket` ``.sent``
        list — Property 8's "zero UDP packets" clause, evaluated
        relative to the post-handshake baseline.

    The cross-step invariant — total emitted packets stay equal to
    the post-handshake baseline across every rejected call — is
    re-asserted at the end of the scenario as a regression guard
    against a per-step count that briefly grows and then shrinks
    again (e.g. via a partial dispatch that sends and then somehow
    removes the entry from ``.sent``).

    Validates: Requirements 4.5, 4.9, 4.10, 4.11, 5.5, 5.7, 6.3,
    7.3, 7.6.
    """
    driver, fake_sock = _build_connected_driver()
    assert driver.connection_status == ConnectionStatus.CONNECTED, (
        "test pre-condition: handshake must succeed so the driver "
        "starts in CONNECTED before exercising the validators; got "
        "%r" % (driver.connection_status,)
    )
    assert driver.initialized is True
    assert fake_sock.closed is False

    # Post-handshake baseline. Every rejected call below must leave
    # this count untouched.
    handshake_packet_count = len(fake_sock.sent)
    assert handshake_packet_count == 1, (
        "test pre-condition: exactly one handshake packet should "
        "have been emitted before any command-layer call; got %d"
        % handshake_packet_count
    )

    for step_index, (method_name, args, offending_name, offending_value) in enumerate(
        scenario
    ):
        method = getattr(driver, method_name)
        sent_before = len(fake_sock.sent)

        # 1. Invocation MUST raise (TypeError | ValueError).
        with pytest.raises((TypeError, ValueError)) as excinfo:
            method(*args)

        msg = str(excinfo.value)

        # 2. The exception message names the offending parameter.
        #
        # The driver's validators consistently quote the parameter
        # name in the diagnostic — either as a literal ``'name'``
        # baked into the f-string template (e.g. ``_move``,
        # ``_left``, ``setconfig``, ``monitor``) or as ``{name!r}``
        # inside a per-parameter loop (e.g. ``_move_beizer``). Both
        # yield the same single-quoted form, so matching
        # ``f"'{name}'"`` covers every command without a per-command
        # special case.
        expected_name_substring = f"'{offending_name}'"
        assert expected_name_substring in msg, (
            "step %d (method=%s, args=%r): exception message must "
            "name the offending parameter %s; got %r."
            % (
                step_index,
                method_name,
                args,
                expected_name_substring,
                msg,
            )
        )

        # 3. The exception message names the offending value.
        #
        # Allow either the ``ValueError`` ``"got VALUE"`` form or the
        # ``TypeError`` ``"=VALUE"`` form (where the implementation
        # prefixes the value with ``"got TYPE=VALUE"``). Using
        # ``repr`` rather than ``str`` matches the ``%r`` / ``!r``
        # formatting the validators use.
        expected_value_substring_a = f"got {offending_value!r}"
        expected_value_substring_b = f"={offending_value!r}"
        assert (
            expected_value_substring_a in msg
            or expected_value_substring_b in msg
        ), (
            "step %d (method=%s, args=%r): exception message must "
            "name the offending value via either %r or %r; got %r."
            % (
                step_index,
                method_name,
                args,
                expected_value_substring_a,
                expected_value_substring_b,
                msg,
            )
        )

        # 4. Zero new UDP packets emitted by the rejected call.
        sent_after = len(fake_sock.sent)
        assert sent_after == sent_before, (
            "step %d (method=%s, args=%r): FakeUdpSocket.sent grew "
            "from %d to %d entries — Property 8 forbids invoking "
            "sendto on the rejection path."
            % (
                step_index,
                method_name,
                args,
                sent_before,
                sent_after,
            )
        )

        # 5. Socket lifecycle is untouched. A rejected call is a
        # *pre-dispatch* validation failure; the transport layer
        # never sees the request, so the underlying fake socket
        # must remain open and the connection state must remain
        # CONNECTED.
        assert fake_sock.closed is False, (
            "step %d (method=%s): underlying fake socket was closed "
            "by a rejection path — Property 8 requires the rejection "
            "to leave the socket open." % (step_index, method_name)
        )
        assert driver.connection_status == ConnectionStatus.CONNECTED, (
            "step %d (method=%s): connection_status changed to %r on "
            "the rejection path — Property 8 requires validation "
            "failures to leave connection_status untouched."
            % (step_index, method_name, driver.connection_status)
        )
        assert driver.initialized is True, (
            "step %d (method=%s): initialized changed to %r on the "
            "rejection path — Property 8 requires validation "
            "failures to leave initialized untouched."
            % (step_index, method_name, driver.initialized)
        )

    # Cross-step invariant — across the entire scenario, the total
    # emitted packet count never moved off the post-handshake
    # baseline. Catches a regression where an individual step
    # increments and decrements ``.sent`` symmetrically (e.g. via a
    # mock ``send`` that records and then ``pop()``-s the entry).
    assert len(fake_sock.sent) == handshake_packet_count, (
        "post-scenario invariant: total emitted packets must stay "
        "at the handshake baseline (%d) across %d rejected "
        "dispatches; got %d."
        % (handshake_packet_count, len(scenario), len(fake_sock.sent))
    )
