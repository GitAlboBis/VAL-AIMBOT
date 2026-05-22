"""
Property test — Task 8.3 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 4: ``click`` rate limiting.

**Property 4: ``click`` rate limiting**

    *For any* sequence of ``click(delay)`` calls at monotonic
    timestamps ``t_1 ≤ t_2 ≤ … ≤ t_n`` with a fixed
    ``target_cps ∈ (0, 1000]``, the driver SHALL satisfy:

      1. **Window invariant.** The number of admitted clicks (those
         that spawn a ``send_click`` worker) over any window
         ``[a, b]`` is at most ``⌊(b - a) · target_cps⌋ + 1``.
         Equivalently, every pair of consecutive admitted clicks
         has gap ``≥ 1.0 / target_cps``.
      2. **No-overlap invariant.** No admitted click overlaps a
         still-running click worker — i.e. while
         ``click_thread.is_alive()`` is ``True`` the gate at the
         entry of ``BaseMouse.click`` SHALL drop subsequent calls
         without spawning a new worker.

**Validates: Requirements 3.5**

Implementation notes
--------------------

The driver inherits ``click(delay_before_click)`` from
:class:`input.base_mouse.BaseMouse` (Task 8.1 explicitly preserves
this behaviour: "Inherit ``click(delay_before_click)`` from
``BaseMouse`` (rate limiting via ``target_cps`` is provided by the
base class)."). The base implementation reads ``time.time()`` and
gates admission on:

  * ``not self.click_thread.is_alive()`` — the no-overlap clause; and
  * ``time.time() - self.last_click_time >= 1.0 / self.target_cps``
    — the rate-limit-window clause.

Admitted calls spawn a daemon ``threading.Thread`` whose target is
``self.send_click(delay_before_click)``.

To exercise both invariants deterministically the test:

  1. Builds a connected :class:`KmBoxNetDriver` against the standard
     :class:`FakeUdpSocket` + :class:`FakeDevice` harness, so
     ``send_click`` (which delegates to ``_dispatch_call``) does not
     short-circuit on a non-CONNECTED status. ``use_encryption=False``
     keeps the wire path one ``sendto`` per dispatch, irrelevant to
     this property but cheaper.
  2. Replaces ``time.time`` *inside* ``input.base_mouse`` with a
     test-controlled clock so the gate's elapsed-time arithmetic is
     deterministic. We patch the dotted path
     ``input.base_mouse.time.time`` (rather than ``time.time``
     globally) so other modules running concurrently are unaffected.
  3. Replaces ``threading.Thread`` *inside* ``input.base_mouse`` with
     a :class:`_FakeThread` whose ``start()`` is a no-op and whose
     ``is_alive()`` is controllable. This (a) prevents the click
     worker from running on the real wall clock and racing the
     deterministic test time, and (b) lets the test choose whether
     the previously spawned worker is still "alive" when the next
     ``click()`` is called — exactly the signal the no-overlap
     gate checks.
  4. Detects admission by counting :class:`_FakeThread` instances
     created during each ``click()`` call. The base class
     constructs and ``start()``-s a fresh ``Thread`` *only* on the
     admit path, so a post-call instance count delta of ``1`` means
     "admitted" and ``0`` means "dropped".

The Hypothesis strategies match the task plan verbatim:

  * Sorted monotonic timestamps in seconds — generated as a list of
    non-negative gaps then accumulated.
  * ``target_cps`` in ``(0, 1000]``. ``BaseMouse.__init__`` clamps to
    ``max(target_cps, 1.0)``, so values ``≥ 1.0`` pass through
    bit-exactly and the test's ``1.0 / target_cps`` window equals
    the driver's window.

Two property tests are exposed:

  * :func:`test_click_rate_limit_window_invariant` — Property 4
    clause 1 (window invariant).
  * :func:`test_click_drops_while_worker_alive` — Property 4
    clause 2 (no-overlap invariant).
"""

from __future__ import annotations

import socket as _stdlib_socket
import sys
import threading as _stdlib_threading
from pathlib import Path
from typing import Any, List, Tuple
from unittest.mock import patch

# Make the ``input`` package importable when pytest is launched from
# the repository root or any sub-directory. The driver ships as
# ``input/kmbox_net_driver.py`` at the project root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from input import base_mouse as _base_mouse_module  # noqa: E402
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

# A list of non-negative inter-click gaps in seconds. Accumulating
# these gives the sorted monotonic timestamps t_1 ≤ … ≤ t_n required
# by Property 4. Bounding each gap to ``[0.0, 2.0]`` keeps each
# example small while still spanning windows wide enough to fit
# multiple admissions at moderate ``target_cps``.
_st_gap = st.floats(
    min_value=0.0,
    max_value=2.0,
    allow_nan=False,
    allow_infinity=False,
)
_st_gaps = st.lists(_st_gap, min_size=0, max_size=40)

# ``target_cps`` in (0, 1000]. ``BaseMouse.__init__`` clamps to
# ``max(target_cps, 1.0)``, so the lower bound is 1.0 here so that
# the test's ``1.0 / target_cps`` window equals the driver's window
# bit-exactly. The upper bound matches Requirement 3.5's
# "less than or equal to 1000".
_st_target_cps = st.floats(
    min_value=1.0,
    max_value=1000.0,
    allow_nan=False,
    allow_infinity=False,
)


_PROPERTY_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
        HealthCheck.differing_executors,
    ],
)


# ---------------------------------------------------------------------------
# FakeThread — observable, controllable replacement for ``threading.Thread``
# ---------------------------------------------------------------------------


class _FakeThread:
    """Drop-in for ``threading.Thread`` that records creation only.

    ``BaseMouse.click`` constructs and ``start()``-s a fresh
    ``threading.Thread`` *only* on the admit path. Substituting this
    fake into ``input.base_mouse`` allows the test to:

      * Detect admission unambiguously by tracking
        :attr:`instances` length deltas across each ``click()`` call.
      * Suppress the worker so ``send_click`` does not run on the
        real wall clock and race the deterministic test clock.
      * Control ``is_alive()`` per-instance to exercise the
        no-overlap clause: the test can mark a previously created
        thread as "still running" before issuing the next click and
        verify that the gate drops it.

    The signature accepts ``*args, **kwargs`` so it tolerates any
    Thread constructor shape (positional ``target``, keyword ``args``,
    ``name``, ``daemon``, …).
    """

    instances: List["_FakeThread"] = []

    __slots__ = ("_alive", "_target", "_args")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Capture target/args for diagnostic clarity but never run
        # them — the property under test is purely about the gate
        # decision in the calling thread, not the worker side
        # effects.
        self._target = kwargs.get("target")
        self._args = kwargs.get("args", ())
        self._alive = False
        type(self).instances.append(self)

    def start(self) -> None:  # pragma: no cover — pure no-op
        # Suppress the worker so ``send_click`` never runs against
        # the real wall clock. The rate-limit gate has already
        # executed in the calling thread by the time we reach this
        # method.
        pass

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:  # pragma: no cover
        # ``release()`` may try to join background threads; tolerate
        # it cleanly.
        return None

    @classmethod
    def reset(cls) -> None:
        cls.instances = []


# ---------------------------------------------------------------------------
# Fake-clock helper
# ---------------------------------------------------------------------------


class _FakeClock:
    """Mutable scalar exposing a ``__call__`` that returns the current time.

    The base class reads ``time.time()`` (not ``time.monotonic()``).
    This fake substitutes for ``input.base_mouse.time.time`` so the
    rate-limit gate's elapsed-time arithmetic becomes deterministic.
    """

    __slots__ = ("now",)

    def __init__(self, start: float = 1_000_000.0) -> None:
        # Start far from zero so a regression that compared against
        # ``last_click_time == 0.0`` and treated ``time.time()`` as
        # epoch-relative still produces a meaningful elapsed value
        # for the test's purposes (the property is invariant under
        # any constant offset of the time source).
        self.now: float = float(start)

    def __call__(self) -> float:
        return self.now


# ---------------------------------------------------------------------------
# Driver harness — fresh fakes per Hypothesis example
# ---------------------------------------------------------------------------


def _build_connected_driver(target_cps: float) -> Tuple[KmBoxNetDriver, FakeUdpSocket]:
    """Construct a CONNECTED :class:`KmBoxNetDriver` against fresh fakes.

    Returns ``(driver, fake_socket)``. The fake socket is the first
    UDP socket the driver constructed (the handshake/transport
    socket); subsequent sockets (e.g. a Monitor listener) are not
    relevant to this property.
    """
    sockets: List[FakeUdpSocket] = []
    device = FakeDevice(outcome=FakeDevice.HandshakeOutcome.SUCCESS)

    def _factory(
        family: int = _stdlib_socket.AF_INET,
        type_: int = _stdlib_socket.SOCK_DGRAM,
        proto: int = 0,
        fileno: int | None = None,
        **_kwargs: Any,
    ) -> FakeUdpSocket:
        sock = FakeUdpSocket(family=family, type_=type_)
        sock.proto = proto
        sockets.append(sock)
        if len(sockets) == 1:
            device.attach(sock)
        return sock

    original_socket = _stdlib_socket.socket
    _stdlib_socket.socket = _factory  # type: ignore[assignment]
    try:
        driver = KmBoxNetDriver(
            ip="192.168.2.188",
            port="41990",
            uuid="01FBC068",
            use_encryption=False,
            target_cps=target_cps,
        )
    finally:
        _stdlib_socket.socket = original_socket  # type: ignore[assignment]

    if not sockets:
        raise RuntimeError(
            "test harness invariant violated: KmBoxNetDriver did "
            "not construct any UDP socket"
        )
    if driver.connection_status is not ConnectionStatus.CONNECTED:
        raise RuntimeError(
            "test pre-condition: handshake should have driven the "
            f"driver to CONNECTED; got connection_status="
            f"{driver.connection_status!r}"
        )
    return driver, sockets[0]


# ---------------------------------------------------------------------------
# Property 4 clause 1 — window invariant
# ---------------------------------------------------------------------------


@_PROPERTY_SETTINGS
@given(gaps=_st_gaps, target_cps=_st_target_cps)
def test_click_rate_limit_window_invariant(
    gaps: List[float], target_cps: float
) -> None:
    """Property 4 clause 1: window invariant.

    For sorted timestamps ``t_1 ≤ … ≤ t_n`` (the cumulative sum of
    ``gaps``) and any ``target_cps ∈ [1.0, 1000.0]``, the number of
    admitted clicks over any window ``[a, b]`` is at most
    ``⌊(b - a) · target_cps⌋ + 1``. Equivalently, every pair of
    consecutive admitted timestamps satisfies ``gap ≥ 1.0 / target_cps``.
    """
    # ---- build a connected driver -------------------------------------
    driver, _fake_sock = _build_connected_driver(target_cps=target_cps)

    # Sanity: BaseMouse should not have re-clamped target_cps because
    # the strategy starts at 1.0 — the test's window must equal the
    # driver's window bit-exactly.
    assert driver.target_cps == target_cps, (
        "BaseMouse target_cps clamp altered the test's window: "
        f"strategy gave {target_cps!r}, driver has {driver.target_cps!r}"
    )

    # ---- accumulate strict timestamps from the gaps -------------------
    # Cumulative sum yields a sorted sequence t_1 ≤ t_2 ≤ … ≤ t_n.
    # Adding a constant offset keeps elapsed-time arithmetic the same.
    timestamps: List[float] = []
    acc = 0.0
    for g in gaps:
        acc += float(g)
        timestamps.append(acc)

    # ---- install fake clock + fake thread on the base module ---------
    fake_clock = _FakeClock(start=0.0)
    _FakeThread.reset()

    admit_timestamps: List[float] = []

    # Patch ``time.time`` and ``threading.Thread`` *inside* the
    # ``input.base_mouse`` module only, so the rest of the process
    # (including the ``FakeDevice`` listener thread infrastructure)
    # remains untouched.
    with patch.object(
        _base_mouse_module.time, "time", fake_clock
    ), patch.object(
        _base_mouse_module, "threading", _FakeThreadingProxy()
    ):
        try:
            for t in timestamps:
                # Set the virtual clock to ``t`` before the call. The
                # base class's gate evaluates
                # ``time.time() - last_click_time``; the post-call
                # value of ``self.click_thread`` is a fresh
                # :class:`_FakeThread` iff this call was admitted.
                fake_clock.now = float(t)

                # Snapshot the fake-thread instance count BEFORE the
                # call. The base class assigns
                # ``self.click_thread = threading.Thread(...)`` only
                # on the admit path, which appends one new instance
                # to ``_FakeThread.instances``.
                pre_count = len(_FakeThread.instances)

                driver.click()

                post_count = len(_FakeThread.instances)
                admitted = post_count > pre_count
                if admitted:
                    # On admission, exactly one new fake-thread was
                    # created (the click worker that was suppressed).
                    assert post_count == pre_count + 1, (
                        f"_FakeThread instance count jumped by "
                        f"{post_count - pre_count} on a single click; "
                        "the base class should construct exactly one "
                        "Thread per admitted click."
                    )
                    admit_timestamps.append(float(t))
        finally:
            # Always release the driver so the underlying fake
            # socket's ``close_count`` invariant is preserved across
            # Hypothesis examples.
            driver.release()

    # ---- assertion: window invariant ----------------------------------
    # The exact form Property 4 mandates: for every pair (i, j) with
    # i ≤ j among admit_timestamps, the window ``[t_i, t_j]`` must
    # contain at most ``⌊(t_j - t_i) · target_cps⌋ + 1`` admissions.
    # Since admit_timestamps is sorted, the pair (i, j) bracketing
    # the j - i + 1 entries [i..j] is the tightest window for that
    # admission count. Iterating O(n^2) is acceptable for n ≤ 40.
    n = len(admit_timestamps)
    for i in range(n):
        for j in range(i, n):
            a = admit_timestamps[i]
            b = admit_timestamps[j]
            count = j - i + 1
            # Use the property formulation verbatim: ``floor`` is
            # ``int`` for non-negative values; ``b - a`` is non-negative
            # because the admit_timestamps list is sorted.
            max_allowed = int((b - a) * target_cps) + 1
            assert count <= max_allowed, (
                "Property 4 clause 1 violated: window "
                f"[{a!r}, {b!r}] (length {b - a!r}s) admitted "
                f"{count} clicks; max allowed at "
                f"target_cps={target_cps!r} is "
                f"floor((b-a)*target_cps) + 1 = {max_allowed}. "
                f"admit_timestamps={admit_timestamps!r}, "
                f"timestamps={timestamps!r}, gaps={gaps!r}."
            )


# ---------------------------------------------------------------------------
# Property 4 clause 2 — no admitted click overlaps a still-running worker
# ---------------------------------------------------------------------------


def test_click_drops_while_worker_alive() -> None:
    """Property 4 clause 2: no admitted click overlaps a still-running worker.

    Issues two ``click()`` calls separated by an arbitrarily large
    virtual time delta (so the rate-limit window cannot be the
    blocking factor). Between the two calls the previously created
    ``click_thread`` is force-marked as ``alive``; the second call
    MUST be dropped because
    ``not self.click_thread.is_alive()`` evaluates to ``False``.

    A third call follows after marking the thread "not alive" again,
    along with a virtual-time advance large enough to clear the
    rate-limit window. That call MUST be admitted, demonstrating the
    gate is the *only* thing that suppressed the second call.
    """
    target_cps = 10.0
    driver, _fake_sock = _build_connected_driver(target_cps=target_cps)

    # Start the virtual clock far above the rate-limit window so the
    # very first click admits. ``last_click_time`` is initialised to
    # 0.0 by ``BaseMouse.__init__``; with ``target_cps=10.0`` the
    # window is ``0.1`` seconds. Starting at ``1_000.0`` yields an
    # initial elapsed value vastly exceeding the window so the rate-
    # limit clause is open for the first call.
    fake_clock = _FakeClock(start=1_000.0)
    _FakeThread.reset()

    with patch.object(
        _base_mouse_module.time, "time", fake_clock
    ), patch.object(
        _base_mouse_module, "threading", _FakeThreadingProxy()
    ):
        try:
            # ---- first click: admitted ------------------------------
            # ``last_click_time`` is 0.0 by default; clock starts at
            # 1_000.0, so elapsed is huge and the rate-limit clause
            # opens.
            fake_clock.now = 1_000.0
            pre = len(_FakeThread.instances)
            driver.click()
            post = len(_FakeThread.instances)
            assert post == pre + 1, (
                "first click should be admitted (no prior worker, "
                "rate window not engaged); got "
                f"_FakeThread.instances delta = {post - pre}"
            )
            first_thread = _FakeThread.instances[-1]

            # Mark the just-spawned worker as "still running" so the
            # gate's ``not self.click_thread.is_alive()`` clause
            # evaluates to ``False`` for the next call.
            first_thread._alive = True

            # ---- second click: dropped (worker still alive) ---------
            # Advance the clock far past 1.0 / target_cps so the
            # rate-limit-window clause cannot be the blocking factor.
            fake_clock.now = 1_100.0
            pre = len(_FakeThread.instances)
            driver.click()
            post = len(_FakeThread.instances)
            assert post == pre, (
                "Property 4 clause 2 violated: a click was admitted "
                "while the previous click_thread was still alive. "
                f"_FakeThread.instances delta = {post - pre}; "
                "expected 0."
            )

            # ---- third click: admitted again ------------------------
            # Mark the prior worker as finished and verify the gate
            # opens. This is a regression guard: it confirms the
            # second call was dropped *because* of the alive gate,
            # not for some unrelated reason.
            first_thread._alive = False
            fake_clock.now = 1_200.0
            pre = len(_FakeThread.instances)
            driver.click()
            post = len(_FakeThread.instances)
            assert post == pre + 1, (
                "third click should be admitted after marking the "
                "prior worker as not-alive; got "
                f"_FakeThread.instances delta = {post - pre}"
            )
        finally:
            driver.release()


# ---------------------------------------------------------------------------
# Threading-module proxy
# ---------------------------------------------------------------------------


class _FakeThreadingProxy:
    """Thin shim that exposes ``Thread = _FakeThread`` and forwards.

    ``BaseMouse.click`` accesses ``threading.Thread`` via the module
    binding (``import threading`` at the top of ``base_mouse.py``),
    so we substitute the entire ``threading`` reference *inside that
    module* with this proxy. The proxy:

      * exposes ``Thread`` as :class:`_FakeThread` so admitted
        clicks construct fakes; and
      * forwards every other attribute access to the real
        :mod:`threading` module so unrelated callers (locks, events)
        are unaffected.

    ``BaseMouse.__init__`` *also* invokes ``threading.Thread`` once
    on construction (``self.click_thread = threading.Thread(...)``).
    The harness patches ``threading`` only *after* the driver has
    been constructed, so the constructor's invocation goes through
    the real ``threading.Thread`` and the post-construction
    ``self.click_thread`` is a real (not-started) ``Thread`` instance
    whose ``is_alive()`` returns ``False``. That is the desired
    initial state for the rate-limit gate.
    """

    Thread = _FakeThread

    def __getattr__(self, name: str) -> Any:
        return getattr(_stdlib_threading, name)
