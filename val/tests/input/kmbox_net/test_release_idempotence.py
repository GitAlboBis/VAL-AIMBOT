"""
Property test — Task 5.5 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 5: ``release`` idempotence and
# terminal silence.

**Property 5: ``release`` idempotence and terminal silence**

    *For any* :class:`KmBoxNetDriver` instance and *for any* sequence of
    public-API calls invoked after one or more calls to :meth:`release`,
    the driver SHALL satisfy:

      1. zero ``UDP_Socket.sendto`` calls are issued by the post-release
         calls (the in-flight handshake packet emitted *before* release
         is allowed; it is the only sendto recorded between
         construction and release);
      2. no public-API call invoked after release raises an exception;
      3. the UDP socket is closed exactly once across the entire
         lifetime of the driver, regardless of how many times
         :meth:`release` is invoked;
      4. each background thread spawned by the driver is joined
         exactly once (vacuously satisfied at this point in the
         implementation: task 7.3 wires the Monitor listener; until
         then ``_monitor_listener`` is ``None`` and no thread is
         spawned, so the "exactly once" clause holds for the empty
         set of spawned threads);
      5. ``initialized`` is ``False`` and ``connection_status`` is
         :data:`ConnectionStatus.DISCONNECTED` (== the literal string
         ``"disconnected"``, since :class:`ConnectionStatus` mixes
         :class:`str`).

**Validates: Requirements 3.8, 10.5**

Implementation notes
--------------------

The test instantiates a real :class:`KmBoxNetDriver` against a
:class:`FakeUdpSocket` + :class:`FakeDevice` configured for a
successful handshake, exactly mirroring the inline ``socket.socket``
monkey-patching pattern used by ``test_dispatch_encrypt_isolation.py``.
The driver's command-layer wrappers (``_move``, ``_left``, …) are still
``NotImplementedError`` at this point in the implementation, so the
test invokes ``driver._dispatch_call(cmd_name, *args)`` directly —
``_dispatch_call`` is the single chokepoint where the
``_released`` flag and ``connection_status`` are inspected before any
``sendto`` (Requirements 7.8, 8.7, 10.4 in the design's "Components and
Interfaces" section), so it is the right entry point to prove the
post-release silence property.

The fake UDP socket's :meth:`close` method is instrumented with a
counter (``close_count``) so the test can verify the "closed exactly
once" clause regardless of how many times :meth:`release` is invoked.
The driver's :class:`UdpSocket` wrapper is itself idempotent (it sets a
``_closed`` flag and short-circuits subsequent calls), so the
underlying fake's ``close`` should be invoked exactly once even when
``release()`` is called many times — this test asserts that contract
end-to-end.
"""

from __future__ import annotations

import socket as _stdlib_socket
import sys
from pathlib import Path

# Make the ``input`` package importable when pytest is launched from
# the repository root or any sub-directory.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from input.kmbox_net_driver import (  # noqa: E402
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


# Per-argument bounds match the design's "Per-command payload encoding"
# table. The values are not actually used by the wire layer on the
# post-release path (``_dispatch_call`` returns ``None`` before any
# build step runs once ``_released`` is set), but generating valid
# arguments keeps the property generic to the entire public command
# surface and avoids accidentally exercising input-validation paths
# that are themselves unrelated to Property 5.
_st_xy = st.integers(min_value=-32768, max_value=32768)
_st_isdown = st.integers(min_value=0, max_value=1)
_st_wheel = st.integers(min_value=-128, max_value=128)
_st_btn_mask = st.integers(min_value=0, max_value=255)
_st_ms = st.integers(min_value=1, max_value=65535)
_st_hid = st.integers(min_value=0, max_value=255)
_st_monitor_port = st.integers(min_value=1024, max_value=49151)


def _cmd_strategy() -> st.SearchStrategy:
    """Strategy emitting ``(cmd_name, args)`` tuples for ``_dispatch_call``.

    Sampled across the full set of logical command names recognised by
    :meth:`KmBoxNetDriver._dispatch_call` (see the dispatch chain in
    that method's body). Property 5 asserts post-release silence
    *for any* sequence of public-API calls, so the strategy spans every
    routable command — not just the mouse subset — to maximise the
    chance that the property is exercised against every dispatch arm.
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
            st.tuples(
                st.integers(min_value=0, max_value=255),
                st.lists(_st_hid, min_size=10, max_size=10),
            ),
        ),
        st.tuples(st.just("monitor"), st.tuples(_st_monitor_port)),
        st.tuples(st.just("monitor"), st.tuples(st.just(0))),
        st.tuples(st.just("reboot"), st.tuples()),
        st.tuples(
            st.just("setconfig"),
            st.tuples(
                st.just("192.168.2.188"),
                st.integers(min_value=1, max_value=65535),
            ),
        ),
        st.tuples(
            st.just("mask_mouse_left"),
            st.tuples(_st_isdown),
        ),
        st.tuples(st.just("unmask_all"), st.tuples()),
    )


# Sequence of post-release dispatch calls. Bounded so each Hypothesis
# example completes quickly; five steps are enough to interleave
# multiple command kinds and prove the silence invariant across the
# dispatch table.
_st_post_release_calls = st.lists(
    _cmd_strategy(),
    min_size=0,
    max_size=8,
)


# Number of consecutive ``release()`` calls. Property 5 requires
# idempotence for "one or more" calls; sampling ``[1, 5]`` exercises
# both the single-release case (the common path) and several
# repeated-release cases (the idempotence stress).
_st_release_count = st.integers(min_value=1, max_value=5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_connected_driver() -> tuple[KmBoxNetDriver, FakeUdpSocket]:
    """Construct a ``KmBoxNetDriver`` whose handshake succeeds against a fake.

    Patches ``socket.socket`` for the duration of the constructor so
    the driver creates a :class:`FakeUdpSocket` instead of a real one,
    and attaches a successful :class:`FakeDevice` so the handshake
    ``recvfrom`` resolves to a zero-result-code reply. The patch is
    reverted before the function returns so any later socket use by
    the test body would (correctly) reach the real ``socket.socket`` —
    but the test only inspects ``driver.udp_socket`` (which already
    wraps a ``FakeUdpSocket``), so no real socket is ever opened.

    The fake socket's ``close`` method is wrapped with a counter so
    the test can verify the "closed exactly once" clause of Property 5
    independently of the underlying ``UdpSocket`` wrapper's
    idempotence (which is itself the implementation under test).

    Returns:
        Tuple of ``(driver, fake_udp_socket)``. ``fake_udp_socket.sent``
        records every packet the driver has emitted (the sole entry
        immediately after a successful handshake is the connect packet
        from ``__init__``); ``fake_udp_socket.close_count`` records the
        number of times ``close`` has been invoked.
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
        # Instrument ``close`` with a counter. We wrap rather than
        # replace so the original ``FakeUdpSocket`` semantics
        # (set ``closed = True``, drain the recv queue) are preserved.
        sock.close_count = 0
        original_close = sock.close

        def counting_close() -> None:
            sock.close_count += 1
            original_close()

        sock.close = counting_close  # type: ignore[method-assign]
        sockets.append(sock)
        # Attach the device on the *first* socket only so the
        # handshake reply is queued before the driver's ``recvfrom``.
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
# Property 5
# ---------------------------------------------------------------------------


@settings(max_examples=50, deadline=None)
@given(
    release_count=_st_release_count,
    post_release_calls=_st_post_release_calls,
)
def test_release_idempotence_and_terminal_silence(
    release_count: int,
    post_release_calls: list,
) -> None:
    """``release()`` is idempotent and silences every subsequent send.

    Per Property 5 (design.md) and Requirements 3.8 / 10.5:

      1. After ``release()`` returns, every public-API call routed
         through ``_dispatch_call`` (the only chokepoint that talks to
         the socket) returns ``None`` without emitting a UDP packet.
      2. ``release()`` is idempotent: invoking it ``N >= 1`` times
         produces exactly the same observable end state as invoking
         it once. In particular the underlying UDP socket's ``close``
         method is invoked exactly once across all ``N`` ``release()``
         calls (the ``UdpSocket`` wrapper short-circuits subsequent
         calls via its internal ``_closed`` flag).
      3. After the last ``release()`` returns,
         ``driver.initialized == False`` and
         ``driver.connection_status == ConnectionStatus.DISCONNECTED``
         (which compares equal to the literal string
         ``"disconnected"`` thanks to the ``str`` mixin on the enum,
         per the design "Components and Interfaces" section).

    Validates: Requirements 3.8, 10.5.
    """
    # 1. Build a connected driver. The handshake itself emits exactly
    # one UDP packet (the ``cmd_connect`` request); ``fake_sock.sent``
    # therefore has length 1 immediately after construction. We
    # snapshot this length so the post-release-silence assertion can
    # check that *no further* packets are emitted, regardless of the
    # handshake.
    driver, fake_sock = _build_connected_driver()
    assert driver.connection_status == ConnectionStatus.CONNECTED, (
        "test pre-condition: handshake must succeed; got %r"
        % (driver.connection_status,)
    )
    assert driver.initialized is True, (
        "test pre-condition: handshake success must set "
        "initialized=True; got %r" % (driver.initialized,)
    )

    sent_count_before_release = len(fake_sock.sent)
    assert sent_count_before_release == 1, (
        "test pre-condition: exactly one handshake packet should "
        "have been emitted before any post-release call; got %d"
        % sent_count_before_release
    )
    assert fake_sock.close_count == 0, (
        "test pre-condition: close() must not have been invoked "
        "before release(); got close_count=%d"
        % fake_sock.close_count
    )
    assert fake_sock.closed is False, (
        "test pre-condition: socket must be open before release(); "
        "got closed=%r" % (fake_sock.closed,)
    )

    # 2. Capture spawned threads. Property 5 clause 4 requires that
    # each spawned thread be joined exactly once across all
    # ``release()`` calls. At this point in the implementation
    # (task 5.5; task 7.3 has not yet wired ``_MonitorListener``)
    # the driver does not spawn any background threads, so the
    # "exactly once" clause is vacuously satisfied for the empty
    # set. We still capture ``_monitor_listener`` defensively so a
    # later refactor that spawns threads in ``__init__`` would be
    # caught by the post-release assertion below.
    listener_before_release = getattr(driver, "_monitor_listener", None)

    # 3. Invoke ``release()`` ``release_count`` times. The first call
    # performs the actual teardown; subsequent calls must be no-ops
    # per Requirement 3.8 ("SHALL return without raising an
    # exception when invoked a second or subsequent time on a driver
    # instance whose UDP_Socket is already closed").
    for i in range(release_count):
        driver.release()
        # After the *first* ``release()`` the post-conditions of
        # clause 5 must already hold; the remaining ``release()``
        # calls must preserve them.
        assert driver.initialized is False, (
            "release() iteration %d: initialized must be False after "
            "release(); got %r" % (i, driver.initialized)
        )
        assert driver.connection_status == ConnectionStatus.DISCONNECTED, (
            "release() iteration %d: connection_status must be "
            "DISCONNECTED after release(); got %r"
            % (i, driver.connection_status)
        )
        # ``ConnectionStatus`` mixes ``str`` so equality with the
        # literal ``"disconnected"`` is part of the public contract
        # observed by the GUI shared_state per the design
        # "Components and Interfaces" section.
        assert driver.connection_status == "disconnected", (
            "release() iteration %d: connection_status must compare "
            "equal to the literal string 'disconnected' (str mixin "
            "on ConnectionStatus); got %r"
            % (i, driver.connection_status)
        )

    # 4. Property 5 clause 3 — closed exactly once. ``UdpSocket``'s
    # ``_closed`` flag prevents the underlying ``socket.close`` from
    # being invoked more than once even when ``release()`` is called
    # ``release_count`` times.
    assert fake_sock.close_count == 1, (
        "Property 5 clause 3: UDP socket must be closed exactly "
        "once across %d release() calls; got close_count=%d"
        % (release_count, fake_sock.close_count)
    )
    assert fake_sock.closed is True, (
        "Property 5 clause 3: fake socket must reflect a closed "
        "state after release(); got closed=%r" % (fake_sock.closed,)
    )

    # 5. Property 5 clause 4 — listener thread invariant. At this
    # point in the implementation no listener thread is spawned, so
    # the listener attribute should remain ``None`` after release().
    listener_after_release = getattr(driver, "_monitor_listener", None)
    assert listener_after_release is None, (
        "Property 5 clause 4: _monitor_listener must be None after "
        "release() (task 5.5 implementation has no spawned threads "
        "to join); got %r" % (listener_after_release,)
    )
    # If a future change spawns a listener in ``__init__``, the
    # captured ``listener_before_release`` would be non-None and the
    # post-release listener must have been joined and cleared. The
    # ``is None`` assertion above already enforces the cleared part.
    assert listener_before_release is None or listener_after_release is None

    # 6. Property 5 clauses 1 & 2 — terminal silence and no-raise.
    # Replay the generated post-release call sequence against
    # ``_dispatch_call``. Each call MUST return ``None`` (the
    # ``_released`` short-circuit at the top of ``_dispatch_call``),
    # MUST NOT raise an exception, and MUST NOT invoke
    # ``sendto`` on the fake socket.
    for step_index, (cmd_name, args) in enumerate(post_release_calls):
        try:
            result = driver._dispatch_call(cmd_name, *args)
        except Exception as exc:  # pragma: no cover - failure path
            raise AssertionError(
                "Property 5 clause 2 violated: post-release "
                "_dispatch_call(%r, *%r) raised %s: %s"
                % (cmd_name, args, type(exc).__name__, exc)
            ) from exc

        # ``_dispatch_call`` is documented to return ``None`` on
        # every code path (see its docstring "Returns: None in every
        # case"). The post-release path returns ``None`` via the
        # ``_released`` short-circuit; this assertion catches a
        # regression where the gate is removed and the call falls
        # through into the build/encrypt/sendto chain.
        assert result is None, (
            "Property 5 clause 2: post-release _dispatch_call must "
            "return None (got %r) for step %d (%r, %r)"
            % (result, step_index, cmd_name, args)
        )

        # Property 5 clause 1 — zero ``sendto`` calls after release.
        # ``sent_count_before_release`` is the handshake-only baseline
        # captured before the ``release()`` loop; after release no
        # additional packets must appear regardless of how many
        # post-release dispatch calls are made.
        assert len(fake_sock.sent) == sent_count_before_release, (
            "Property 5 clause 1 violated: post-release "
            "_dispatch_call(%r, *%r) at step %d caused a sendto — "
            "fake_sock.sent grew from %d to %d"
            % (
                cmd_name,
                args,
                step_index,
                sent_count_before_release,
                len(fake_sock.sent),
            )
        )

    # 7. Final state re-confirmation. Even after ``release_count``
    # release calls *and* ``len(post_release_calls)`` dispatch calls
    # post-release, the driver state must still reflect a fully
    # released driver — ``initialized=False``, ``connection_status``
    # equal to ``DISCONNECTED``, and the underlying socket closed
    # exactly once.
    assert driver.initialized is False
    assert driver.connection_status == ConnectionStatus.DISCONNECTED
    assert driver.connection_status == "disconnected"
    assert fake_sock.close_count == 1
    assert fake_sock.closed is True
    assert len(fake_sock.sent) == sent_count_before_release
