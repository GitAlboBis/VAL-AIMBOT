"""
Pytest fixtures for ``kmbox-net-arm64-udp`` tests.

Implements the "Fakes and harness" section of design.md:

- ``FakeUdpSocket``    — in-memory UDP send-side fake. Records ``(payload, addr)``
                         tuples and exposes a toggleable ``raise_on_send`` for
                         Property 2 / Property 17 fault injection. Supports
                         ``bind``, ``setsockopt``, ``settimeout``, ``setblocking``,
                         and ``close``.
- ``FakeMonitorSocket`` — paired with ``FakeUdpSocket`` to deliver Monitor_Channel
                         snapshots into the listener thread under deterministic
                         test control.
- ``FakeClock``        — substitutes ``time.monotonic`` and ``time.sleep``.
- ``FakeDevice``       — orchestrates the handshake reply (success / failure /
                         timeout) for lifecycle tests.

The ``socket_factory`` fixture monkey-patches ``socket.socket`` so any
``KmBoxNetDriver()`` constructed inside a test always operates on the fakes
without ever opening a real UDP socket.

These fixtures are deliberately framework-agnostic: they do not import the
driver module under test, so they remain usable even before the rewrite of
``input/kmbox_net_driver.py`` has landed.
"""

from __future__ import annotations

import collections
import queue
import socket as _stdlib_socket
import threading
import time as _stdlib_time
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, List, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Address = Tuple[str, int]
Packet = Tuple[bytes, Address]


# ---------------------------------------------------------------------------
# FakeUdpSocket
# ---------------------------------------------------------------------------


class FakeUdpSocket:
    """In-memory stand-in for ``socket.socket(AF_INET, SOCK_DGRAM)``.

    Behavior:
      * ``sendto(payload, addr)`` appends a ``(bytes(payload), addr)`` tuple to
        ``self.sent`` and returns the payload length, mirroring the real
        ``socket.sendto`` contract.
      * If ``raise_on_send`` is set to a non-``None`` ``OSError``, the next
        ``sendto`` call raises it. By default the error persists across calls
        (matching a hard failure mode); set ``raise_once=True`` to clear the
        error after one raise.
      * ``recvfrom(bufsize)`` returns the next pre-queued reply, or blocks (up
        to the configured ``timeout``) waiting for one. If the queue is empty
        when the timeout elapses, ``socket.timeout`` is raised, mirroring the
        real socket behavior.
      * ``bind`` records the bound address. ``setsockopt`` records the option
        triple. ``settimeout`` / ``setblocking`` record the value.
      * ``close`` flips ``self.closed`` to ``True``; subsequent ``sendto`` /
        ``recvfrom`` calls raise ``OSError`` with errno ``EBADF`` to mirror the
        real-socket behavior. ``close`` is idempotent.

    The fake is thread-safe for the patterns used by the driver: a single
    sender thread (``_dispatch_call``) and (for monitor sockets) a single
    receiver thread.
    """

    # Constants matching ``socket.AF_INET`` / ``socket.SOCK_DGRAM`` so the
    # driver's diagnostic logs (which sometimes print these) match real values.
    AF_INET = _stdlib_socket.AF_INET
    SOCK_DGRAM = _stdlib_socket.SOCK_DGRAM

    def __init__(
        self,
        family: int = _stdlib_socket.AF_INET,
        type_: int = _stdlib_socket.SOCK_DGRAM,
        *,
        raise_on_send: Optional[OSError] = None,
        raise_once: bool = False,
    ) -> None:
        self.family = family
        self.type = type_
        self.proto = 0

        # Record of every emitted packet — tests inspect this to verify wire
        # bytes (Property 7, Property 14, Property 15, etc.).
        self.sent: List[Packet] = []

        # Toggleable fault injection for OSError path tests
        # (Property 2 / Property 17).
        self.raise_on_send: Optional[OSError] = raise_on_send
        self.raise_once: bool = raise_once

        # Pre-queued recvfrom replies. ``put_recv`` enqueues a reply tuple.
        # ``recvfrom`` consumes from the head and respects ``self.timeout``.
        self._recv_queue: "queue.Queue[Packet]" = queue.Queue()

        # Bookkeeping for socket-lifecycle assertions.
        self.bound_address: Optional[Address] = None
        self.sockopts: List[Tuple[int, int, Any]] = []
        self.timeout: Optional[float] = None
        self.blocking: Optional[bool] = None
        self.closed: bool = False

        # Internal lock — protects ``sent`` and ``raise_on_send`` so concurrent
        # ``sendto`` callers (e.g. Property 1 lock-discipline tests) do not
        # corrupt the log.
        self._lock = threading.Lock()

    # ---- send-side ------------------------------------------------------

    def sendto(self, payload: bytes, addr: Address) -> int:
        """Record the packet and return its length, or raise the queued OSError."""
        if self.closed:
            raise OSError(9, "Bad file descriptor")  # EBADF
        with self._lock:
            err = self.raise_on_send
            if err is not None:
                if self.raise_once:
                    self.raise_on_send = None
                raise err
            data = bytes(payload)
            self.sent.append((data, addr))
            return len(data)

    # ---- recv-side ------------------------------------------------------

    def put_recv(self, payload: bytes, addr: Address = ("0.0.0.0", 0)) -> None:
        """Enqueue a reply that the next ``recvfrom`` will return."""
        self._recv_queue.put((bytes(payload), addr))

    def recvfrom(self, bufsize: int = 1024) -> Packet:
        """Return the next pre-queued reply, honoring the configured timeout."""
        if self.closed:
            raise OSError(9, "Bad file descriptor")
        try:
            payload, addr = self._recv_queue.get(
                block=True if self.timeout is None or self.timeout > 0 else False,
                timeout=self.timeout,
            )
        except queue.Empty:
            raise _stdlib_socket.timeout("timed out")
        # Truncate to ``bufsize`` to mirror UDP datagram semantics.
        return payload[:bufsize], addr

    # ---- option-setting -------------------------------------------------

    def bind(self, addr: Address) -> None:
        if self.closed:
            raise OSError(9, "Bad file descriptor")
        self.bound_address = addr

    def setsockopt(self, level: int, optname: int, value: Any) -> None:
        self.sockopts.append((level, optname, value))

    def settimeout(self, value: Optional[float]) -> None:
        self.timeout = value

    def setblocking(self, flag: bool) -> None:
        self.blocking = bool(flag)

    def getsockname(self) -> Address:
        return self.bound_address or ("0.0.0.0", 0)

    # ---- lifecycle ------------------------------------------------------

    def close(self) -> None:
        # Idempotent — a second close on an already-closed socket is a no-op.
        self.closed = True
        # Drain pending recvs so any blocked listener wakes up promptly.
        try:
            while True:
                self._recv_queue.get_nowait()
        except queue.Empty:
            pass

    # ---- context-manager support (matches stdlib socket) ---------------

    def __enter__(self) -> "FakeUdpSocket":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


# ---------------------------------------------------------------------------
# FakeMonitorSocket
# ---------------------------------------------------------------------------


class FakeMonitorSocket(FakeUdpSocket):
    """A ``FakeUdpSocket`` specialized for the Monitor_Channel listener.

    Identical behavior to ``FakeUdpSocket`` but with a convenience
    ``push_snapshot`` method that frames a ``standard_mouse_report_t`` (8 B)
    + ``standard_keyboard_report_t`` (12 B) datagram from high-level
    parameters, so tests can inject monitor frames without having to
    re-implement the wire layout.

    Layout (per design.md):
        offset  0  : u8  report_id
        offset  1  : u8  buttons (bit0=L, bit1=R, bit2=M, bit3=Side1, bit4=Side2)
        offset  2  : i16 x  (little-endian)
        offset  4  : i16 y  (little-endian)
        offset  6  : i16 wheel (little-endian)
        offset  8  : u8  report_id (keyboard)
        offset  9  : u8  modifier mask
        offset 10  : 10B HID keycodes
    """

    def push_snapshot(
        self,
        *,
        buttons: int = 0,
        x: int = 0,
        y: int = 0,
        wheel: int = 0,
        modifiers: int = 0,
        keys: Optional[List[int]] = None,
        report_id_mouse: int = 1,
        report_id_keyboard: int = 1,
        addr: Address = ("0.0.0.0", 0),
    ) -> None:
        """Frame and enqueue a 20-byte monitor datagram."""
        import struct

        keys = list(keys or [])
        if len(keys) > 10:
            raise ValueError("monitor snapshot supports at most 10 HID keys")
        keys_padded = keys + [0] * (10 - len(keys))

        mouse = struct.pack(
            "<BBhhh",
            report_id_mouse & 0xFF,
            buttons & 0xFF,
            x,
            y,
            wheel,
        )
        keyboard = struct.pack(
            "<BB10B",
            report_id_keyboard & 0xFF,
            modifiers & 0xFF,
            *(b & 0xFF for b in keys_padded),
        )
        self.put_recv(mouse + keyboard, addr)


# ---------------------------------------------------------------------------
# FakeClock
# ---------------------------------------------------------------------------


@dataclass
class FakeClock:
    """Deterministic substitute for ``time.monotonic`` and ``time.sleep``.

    ``now`` returns the current virtual time. ``sleep(seconds)`` advances the
    clock by the requested duration without actually blocking — the wait is
    recorded in ``sleeps`` so tests can verify Property 4 (rate limiting) and
    Property 6 (send_click delay) without real wall-clock waits.

    A ``sleep_hook`` may be installed to inject side-effects (e.g. raise an
    exception to simulate Property 10 stuck-key safety). The hook is invoked
    with the requested duration *before* the clock advances.
    """

    start: float = 0.0
    sleeps: List[float] = field(default_factory=list)
    sleep_hook: Optional[Callable[[float], None]] = None

    def __post_init__(self) -> None:
        self._now = float(self.start)
        self._lock = threading.Lock()

    # ---- public API -----------------------------------------------------

    def monotonic(self) -> float:
        with self._lock:
            return self._now

    def time(self) -> float:
        # Some code paths (logging timestamps) use ``time.time``; serve the
        # same monotonic value so tests stay deterministic.
        return self.monotonic()

    def sleep(self, seconds: float) -> None:
        if self.sleep_hook is not None:
            self.sleep_hook(seconds)
        with self._lock:
            self.sleeps.append(float(seconds))
            self._now += max(0.0, float(seconds))

    def advance(self, seconds: float) -> None:
        """Manually advance the clock without recording a sleep."""
        with self._lock:
            self._now += float(seconds)

    # ---- pytest convenience --------------------------------------------

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Install this clock as ``time.monotonic`` / ``time.sleep`` / ``time.time``."""
        monkeypatch.setattr("time.monotonic", self.monotonic)
        monkeypatch.setattr("time.sleep", self.sleep)
        monkeypatch.setattr("time.time", self.time)


# ---------------------------------------------------------------------------
# FakeDevice
# ---------------------------------------------------------------------------


class FakeDevice:
    """Orchestrates the Init_Handshake reply and subsequent device responses.

    Three handshake outcomes are supported per the design's lifecycle tests:

      * ``HandshakeOutcome.SUCCESS``  — enqueue a ``cmd_head_t`` echo
        reply per upstream ``kmboxNet.cpp:NetRxReturnHandle``: the
        device echoes the request's ``head.mac``, ``head.rand``,
        ``head.indexpts``, and ``head.cmd`` (== ``CMD_CONNECT``)
        verbatim. The driver treats any reply ≥ 16 bytes as success
        per the upstream "ret = 0" semantics.
      * ``HandshakeOutcome.FAILURE``  — enqueue a malformed reply
        (shorter than 16 bytes). Per the driver's reply-length check,
        a reply of length < ``CMD_HEAD_SIZE`` triggers the FAILED
        terminal state. (The upstream protocol has no
        device-side "fail" reply — failures are timeouts in
        practice.)
      * ``HandshakeOutcome.TIMEOUT``  — enqueue nothing, so the
        driver's ``recvfrom`` raises ``socket.timeout``.

    A ``FakeDevice`` is bound to a ``FakeUdpSocket`` via ``attach``. After
    attachment, every ``sendto`` performed by the driver is observed and the
    configured response is published into the same socket's recv queue.

    Beyond the handshake, ``FakeDevice`` does not normally reply (the real
    KmBox Net device acks command packets implicitly via UDP delivery).
    Tests can call ``enqueue_reply(payload)`` to inject ad-hoc replies for
    commands that require them.
    """

    class HandshakeOutcome:
        SUCCESS = "success"
        FAILURE = "failure"
        TIMEOUT = "timeout"

    def __init__(
        self,
        *,
        outcome: str = "success",
        failure_code: int = 1,
        ip: str = "192.168.2.188",
        port: int = 41990,
    ) -> None:
        if outcome not in {
            self.HandshakeOutcome.SUCCESS,
            self.HandshakeOutcome.FAILURE,
            self.HandshakeOutcome.TIMEOUT,
        }:
            raise ValueError(
                "outcome must be one of "
                "{'success', 'failure', 'timeout'}, got %r" % (outcome,)
            )
        self.outcome = outcome
        self.failure_code = int(failure_code)
        self.ip = ip
        self.port = int(port)
        # Set when ``attach`` is called.
        self._socket: Optional[FakeUdpSocket] = None
        # Tracks how many handshake replies have been published so the
        # device only answers the first ``cmd_connect`` packet.
        self._handshake_published = False
        # Replies queued by tests via ``enqueue_reply``.
        self._extra_replies: Deque[bytes] = collections.deque()

    # ---- attachment -----------------------------------------------------

    def attach(self, sock: FakeUdpSocket) -> None:
        """Bind this device to ``sock`` and publish the handshake reply.

        The reply is enqueued *before* the driver issues its handshake
        ``recvfrom`` so the driver always observes a deterministic outcome.
        For ``HandshakeOutcome.TIMEOUT`` no reply is enqueued and the
        driver's ``recvfrom`` will raise ``socket.timeout`` after the
        socket's configured timeout elapses.
        """
        self._socket = sock
        self._publish_handshake_reply()

    def _publish_handshake_reply(self) -> None:
        if self._socket is None or self._handshake_published:
            return
        if self.outcome == self.HandshakeOutcome.TIMEOUT:
            # No reply — driver will see ``socket.timeout``.
            self._handshake_published = True
            return
        import struct

        if self.outcome == self.HandshakeOutcome.SUCCESS:
            # Upstream ``cmd_head_t`` echo per
            # ``kmboxNet.cpp:NetRxReturnHandle``: device echoes the
            # request's mac/rand/indexpts/cmd. The driver accepts any
            # reply ≥ 16 bytes as success (matching the upstream
            # ``ret = 0`` convention). We frame an echo with
            # ``cmd == CMD_CONNECT`` (0xAF3C2828) and ``indexpts == 1``
            # to match what a freshly-constructed driver actually
            # sends on the wire (PacketBuilder.next_indexpts()
            # increments from 0 to 1 before the handshake).
            CMD_CONNECT = 0xAF3C2828
            reply = struct.pack(
                "<IIII", 0, 0, 1, CMD_CONNECT
            )
        else:
            # HandshakeOutcome.FAILURE — emit a too-short (< 16-byte)
            # reply so the driver's length check trips and transitions
            # to FAILED. The upstream protocol does not define a
            # "device-side failure code"; in practice failures are
            # timeouts. The shorter-than-header reply is the closest
            # protocol-realistic stand-in for "device sent something
            # malformed".
            reply = b"\x00" * 8
        self._socket.put_recv(reply, (self.ip, self.port))
        self._handshake_published = True

    # ---- ad-hoc replies -------------------------------------------------

    def enqueue_reply(self, payload: bytes, addr: Optional[Address] = None) -> None:
        """Enqueue an arbitrary reply on the attached socket."""
        if self._socket is None:
            raise RuntimeError("FakeDevice not attached to a socket")
        self._socket.put_recv(payload, addr or (self.ip, self.port))

    # ---- inspection -----------------------------------------------------

    @property
    def packets(self) -> List[Packet]:
        """All packets the driver has sent to this device."""
        if self._socket is None:
            return []
        return list(self._socket.sent)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_udp_socket() -> FakeUdpSocket:
    """A bare ``FakeUdpSocket`` with no fault injection configured."""
    return FakeUdpSocket()


@pytest.fixture
def fake_monitor_socket() -> FakeMonitorSocket:
    """A bare ``FakeMonitorSocket`` for Monitor_Channel tests."""
    return FakeMonitorSocket()


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """Install a ``FakeClock`` over ``time.monotonic`` / ``time.sleep`` / ``time.time``."""
    clock = FakeClock()
    clock.install(monkeypatch)
    return clock


@pytest.fixture
def fake_device() -> FakeDevice:
    """A ``FakeDevice`` configured for a successful handshake."""
    return FakeDevice(outcome=FakeDevice.HandshakeOutcome.SUCCESS)


@dataclass
class SocketFactoryHandle:
    """Handle returned by the ``socket_factory`` fixture.

    Exposes:

      * ``sockets``    — list of every ``FakeUdpSocket`` created via the
                         monkey-patched ``socket.socket`` constructor, in
                         creation order. Tests typically inspect
                         ``handle.sockets[0]`` for the driver's main UDP
                         socket and ``handle.sockets[1]`` for any subsequent
                         monitor socket.
      * ``factory``    — the callable installed in place of ``socket.socket``.
                         Useful when a test wants to invoke it directly.
      * ``device``     — the attached ``FakeDevice`` (if any). Set by
                         ``attach_device`` so tests can publish handshake
                         replies on the *next* socket created by the driver.
      * ``configure``  — a callback ``configure(sock)`` invoked on every newly
                         minted socket. Tests assign it to install fault
                         injection or pre-queue replies on each socket.
    """

    sockets: List[FakeUdpSocket]
    factory: Callable[..., FakeUdpSocket]
    device: Optional[FakeDevice] = None
    configure: Optional[Callable[[FakeUdpSocket], None]] = None

    def attach_device(self, device: FakeDevice) -> None:
        """Have ``device`` answer the handshake on the next socket created."""
        self.device = device
        # If the driver has already created a socket before ``attach_device``
        # is called, attach the device to it immediately so its handshake
        # reply is queued before the driver's ``recvfrom``.
        if self.sockets:
            device.attach(self.sockets[0])


@pytest.fixture
def socket_factory(monkeypatch: pytest.MonkeyPatch) -> SocketFactoryHandle:
    """Monkey-patch ``socket.socket`` so the driver only sees ``FakeUdpSocket``.

    The returned ``SocketFactoryHandle`` lets a test:

      * inspect every fake socket the driver created (``handle.sockets``);
      * attach a ``FakeDevice`` so the next-created socket receives a
        deterministic handshake reply (``handle.attach_device(...)``);
      * install a per-socket ``configure(sock)`` callback to inject faults
        or preload recv replies (``handle.configure = lambda s: ...``).

    The patch covers both ``socket.socket(...)`` constructor calls and
    direct attribute access on the ``socket`` module so the driver cannot
    accidentally bind a real OS socket inside a test.
    """
    handle = SocketFactoryHandle(sockets=[], factory=None)  # type: ignore[arg-type]

    def factory(family: int = _stdlib_socket.AF_INET,
                type_: int = _stdlib_socket.SOCK_DGRAM,
                proto: int = 0,
                fileno: Optional[int] = None,
                **_kwargs: Any) -> FakeUdpSocket:
        sock = FakeUdpSocket(family=family, type_=type_)
        sock.proto = proto
        handle.sockets.append(sock)
        # Tests may want to react to every new socket (e.g. attach a device
        # to the first socket, install fault injection on the second).
        if handle.configure is not None:
            handle.configure(sock)
        # If a device is already registered, attach it to the *first* socket
        # created (the handshake socket); subsequent sockets (e.g. the
        # monitor listener) are left alone.
        if handle.device is not None and len(handle.sockets) == 1:
            handle.device.attach(sock)
        return sock

    handle.factory = factory  # type: ignore[assignment]
    monkeypatch.setattr("socket.socket", factory)
    return handle
