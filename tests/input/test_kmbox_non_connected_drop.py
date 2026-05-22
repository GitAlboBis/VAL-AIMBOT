"""
Property test — Task 7.8 of spec ``kmbox-net-integration``.

# Feature: kmbox-net-integration, Property 5: Non-CONNECTED state rejects
#   all sends without raising.

**Property 5: Non-CONNECTED state rejects all sends without raising**

    *For any* sequence of public-method calls on :class:`KmBoxNetDriver`
    (``move`` / ``click`` / ``click_button`` / ``mouse_down`` /
    ``mouse_up`` / ``key_press`` / ``scroll``) issued while either

      - ``connection_status`` is one of
        ``DISCONNECTED`` / ``CONNECTING`` / ``RECONNECTING`` / ``FAILED``
        (i.e. anything other than ``CONNECTED``), or
      - ``_released`` has been latched to ``True`` (post-``release()``),

    the test SHALL observe **zero** invocations of any ``kmNet.*``
    attribute the driver may reach (``move``/``left``/``right``/
    ``middle``/``wheel``/``keydown``/``keyup`` and their ``enc_*``
    twins) and **no exception SHALL propagate out of the driver call**.

**Validates: Requirements 1.7, 2.7, 6.9**

Implementation notes
--------------------
The driver enforces this property structurally inside
``KmBoxNetDriver._dispatch_call`` (see ``input/kmbox_net_driver.py``):

  1. ``if self._released: return None`` — Req 1.7 / Req 6.10 terminal
     gate that fires before any other check.
  2. ``if self.connection_status is not ConnectionStatus.CONNECTED:
     return None`` — Req 6.9 / Req 2.7 gate (``initialized`` is False in
     every non-CONNECTED state, so this single identity check subsumes
     both requirement clauses).

Both gates are silent: they return ``None`` without logging at the
``_dispatch_call`` level and without raising. The driver-level public-API
methods (``click_button`` / ``mouse_down`` / ``mouse_up`` / ``key_press``
/ ``scroll``) catch their own exception path with
``try/except Exception: log + return False``, but because the dispatcher
returns ``None`` rather than raising, the property is satisfied without
those handlers ever firing.

Two parameterizations
~~~~~~~~~~~~~~~~~~~~~
Per the task plan, the property is exercised in two arms with disjoint
generators so each gate in ``_dispatch_call`` is structurally verified
in isolation:

  A. ``connection_status`` in {DISCONNECTED, CONNECTING, RECONNECTING,
     FAILED}: the driver is constructed in CONNECTED state via the
     ``kmNet.init=0`` mock, then ``connection_status`` is force-set to
     the non-CONNECTED value before the call list is replayed. The
     ``_released`` flag is left at ``False`` so the dispatcher's first
     gate is *not* the one tripping; the property must hold via the
     second gate alone.
  B. ``_released = True``: the driver is constructed in CONNECTED state,
     ``connection_status`` is left at CONNECTED so the second gate is
     *not* the one tripping, and ``_released`` is force-latched. The
     property must hold via the first gate alone.

Threading and timing patches
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The test reuses the synchronous ``threading.Thread`` substitution and
``time.sleep`` no-op patch documented in
``tests/input/test_kmbox_encryption_routing.py``. With ``kmNet.init``
mocked to return ``0`` immediately the connect worker resolves on the
first ``queue.get`` poll and the driver lands in CONNECTED inline; with
``time.sleep`` neutralized neither the click hold nor the keyboard hold
wastes wall-clock time. The driver's rate-limit reads ``time.monotonic``
(left untouched) and may legitimately drop clicks within the
``1.0 / target_cps`` window — which is fine, because a dropped click
trivially satisfies the "zero kmNet calls" assertion.

Why the heartbeat thread is replaced too
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``KmBoxNetDriver.__init__`` starts a ``KmBoxHeartbeat`` daemon thread
after a successful connect. With ``threading.Thread`` swapped out for
``_SyncFakeThread`` the heartbeat "thread" is constructed but its
``start()`` runs the loop body inline — and the loop body's first action
is to sit in an ``Event.wait(1.0)`` cadence sleep which would block the
test indefinitely. The fake's ``start()`` runs the target *to
completion*, which for the heartbeat loop is "until ``_heartbeat_stop``
is set". To avoid the deadlock we pre-set ``_heartbeat_stop`` on the
target instance before construction would finish — but that requires
post-construction surgery. Simpler: we patch ``Event.wait`` to return
``True`` immediately (which the heartbeat loop interprets as "release()
was called, terminate"), so the inline heartbeat target returns on its
first iteration with no probe issued.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Tuple
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from input import kmbox_net_driver
from input.kmbox_net_driver import ConnectionStatus, KmBoxNetDriver


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Sentinel constructor args reused across every driver instance built in
# this module. Values mirror the live ``config.yaml`` entries.
_TEST_IP = "192.168.2.188"
_TEST_PORT = "6234"
_TEST_UUID = "00000000-0000-0000-0000-000000000000"

# The seven plaintext ``kmNet.*`` attributes the driver may reach via
# ``_dispatch_call``. Their values are the values of
# ``KmBoxNetDriver._PLAINTEXT_FN``; encoding them locally (rather than
# introspecting the class) keeps the assertion auditable against the
# requirement text.
_PLAINTEXT_ATTRS: Tuple[str, ...] = (
    "move", "left", "right", "middle", "wheel", "keydown", "keyup",
)

# The matching encrypted attributes.
_ENCRYPTED_ATTRS: Tuple[str, ...] = tuple(f"enc_{a}" for a in _PLAINTEXT_ATTRS)

# Every ``kmNet.*`` attribute the driver could reach through
# ``_dispatch_call``. Property 5 asserts that the SUM of call counts
# across every one of these is zero while in a non-CONNECTED state or
# after release() — there is no permitted "stray" send-site.
_ALL_DISPATCH_ATTRS: Tuple[str, ...] = _PLAINTEXT_ATTRS + _ENCRYPTED_ATTRS

# The four non-CONNECTED states the driver may legitimately occupy.
# ``CONNECTED`` is intentionally absent: this property is exclusively
# about the silent-drop gate, so admitting CONNECTED would make the
# assertion vacuously false on any real send.
_NON_CONNECTED_STATES: Tuple[ConnectionStatus, ...] = (
    ConnectionStatus.DISCONNECTED,
    ConnectionStatus.CONNECTING,
    ConnectionStatus.RECONNECTING,
    ConnectionStatus.FAILED,
)

# Identifier sets accepted by the click-edge and hold-edge button
# resolvers respectively (see ``KmBoxNetDriver._BUTTON_EDGE`` /
# ``_BUTTON_HOLD``). Drawn from with ``sampled_from`` so Hypothesis
# explores both the string and integer branches.
_CLICK_BUTTON_IDS: Tuple[Any, ...] = (
    "left", "right", "middle", 1, 2, 4, 8, 16, 32,
)
_HOLD_BUTTON_IDS: Tuple[Any, ...] = (
    "left", "right", "middle", 1, 2, 3,
)


# ---------------------------------------------------------------------------
# Synchronous thread fake
# ---------------------------------------------------------------------------


class _SyncFakeThread:
    """
    Drop-in for :class:`threading.Thread` whose ``start()`` runs the target
    inline.

    Three driver paths spawn ``threading.Thread`` instances:

      * :meth:`KmBoxNetDriver._connect` — bounds ``kmNet.init`` against
        the 5-second cap by harvesting the worker result through a
        ``queue.Queue``. With a mock that returns ``0`` immediately the
        worker completes inline and the bounded ``queue.get`` succeeds
        on the first poll.
      * :meth:`KmBoxNetDriver.__init__` — starts a ``KmBoxHeartbeat``
        daemon thread after a successful connect. The ``Event.wait``
        patch (see below) makes the inline heartbeat target return on
        its first iteration with no probe issued.
      * :meth:`KmBoxNetDriver.click` — admits a click and spawns a worker
        thread that calls :meth:`send_click`. Running the worker inline
        lets the property observe (the absence of) dispatch attempts in
        the same call frame as the ``click()`` invocation.

    ``is_alive()`` returns ``False`` permanently so the
    ``BaseMouse.click_thread.is_alive()`` short-circuit in
    :meth:`KmBoxNetDriver.click` never blocks subsequent admissions on a
    phantom in-flight worker. ``join()`` is a no-op so any future caller
    that joins on the thread does not deadlock.
    """

    __slots__ = ("_target", "_args", "_kwargs")

    def __init__(
        self,
        *args: Any,
        target: Any = None,
        args_kw: Any = None,
        kwargs: Any = None,
        name: Any = None,
        daemon: Any = None,
        **_extra: Any,
    ) -> None:
        self._target = target
        self._args: Tuple[Any, ...] = tuple(args_kw) if args_kw else ()
        self._kwargs = dict(kwargs) if kwargs else {}

    def start(self) -> None:
        if self._target is not None:
            self._target(*self._args, **self._kwargs)

    def is_alive(self) -> bool:
        return False

    def join(self, timeout: Any = None) -> None:  # pragma: no cover - defensive
        return None


def _make_thread_factory():
    """
    Return a callable usable as a ``threading.Thread`` replacement.

    ``threading.Thread`` is most often constructed by keyword
    (``Thread(target=..., args=..., daemon=True, name=...)``). The driver
    code uses exactly that shape. We forward the conventional ``args``
    keyword into ``_SyncFakeThread`` under the alias ``args_kw`` to avoid
    colliding with the ``*args`` capture in :class:`_SyncFakeThread`'s
    constructor.
    """

    def _factory(*args: Any, **kwargs: Any) -> _SyncFakeThread:
        target = kwargs.pop("target", None)
        thread_args = kwargs.pop("args", ())
        thread_kwargs = kwargs.pop("kwargs", None)
        # Discard ``name`` / ``daemon`` / any other Thread-only kwargs.
        kwargs.pop("name", None)
        kwargs.pop("daemon", None)
        return _SyncFakeThread(
            target=target,
            args_kw=thread_args,
            kwargs=thread_kwargs,
        )

    return _factory


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Move components in [-100, 100]: well inside the Req 1.4 valid-input
# window so the Property 3 no-op gate does not pre-empt the dispatch
# path under test. (We are testing the Req 6.9 / 1.7 dispatch gates,
# not the Req 1.4 input-validation gate.)
_MOVE_FLOATS = st.floats(
    min_value=-100.0,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
)


def _method_call(
    name: str,
    args_strategy: "st.SearchStrategy[Tuple[Any, ...]]",
) -> "st.SearchStrategy[Tuple[str, Tuple[Any, ...]]]":
    """Build a tagged-tuple strategy ``(name, args)`` for a single call."""
    return st.tuples(st.just(name), args_strategy)


# Each method-call shape is generated as a tagged tuple so the test body
# can ``match`` on the first element. Argument tuples are wrapped with
# ``st.tuples`` so the args entry is always a tuple (uniform shape across
# methods).
_METHOD_CALL_STRATEGY = st.one_of(
    # ``move(x, y)`` — exercises the ``"move"`` key in both dispatch
    # tables. Inputs are inside the Req 1.4 valid window so the
    # invalid-input no-op branch (Property 3) does not mask the gate
    # under test.
    _method_call("move", st.tuples(_MOVE_FLOATS, _MOVE_FLOATS)),
    # ``click()`` — exercises the ``send_click`` path which would issue
    # ``_dispatch_call("left", 1)`` / ``_dispatch_call("left", 0)`` if
    # the gate did not trip. Note: ``click()`` itself short-circuits
    # before spawning the worker when ``_released`` or non-CONNECTED
    # (see ``KmBoxNetDriver.click``); this is a redundant gate on top
    # of the dispatcher's, and the property holds either way.
    _method_call("click", st.just(())),
    # ``click_button(button)`` — full identifier set covers both
    # ``press_release`` (string) and edge (integer) branches of
    # ``_BUTTON_EDGE``. The driver's ``initialized`` short-circuit
    # also fires here in non-CONNECTED states (since ``_connect()``
    # leaves ``initialized = False`` in every non-CONNECTED branch),
    # but the property is tested at the dispatcher boundary so a
    # zero-call observation is the same regardless of which gate
    # tripped first.
    _method_call(
        "click_button", st.tuples(st.sampled_from(_CLICK_BUTTON_IDS))
    ),
    # ``mouse_down(button)`` / ``mouse_up(button)`` — full identifier
    # set per Req 4.3a.
    _method_call(
        "mouse_down", st.tuples(st.sampled_from(_HOLD_BUTTON_IDS))
    ),
    _method_call(
        "mouse_up", st.tuples(st.sampled_from(_HOLD_BUTTON_IDS))
    ),
    # ``key_press(vk_code, hold_ms)`` — VK 0x41 (``A``) is in the
    # ``_vk_to_hid`` table; ``hold_ms=0`` keeps the deterministic
    # Req 4.8 hold collapsed to a no-op ``time.sleep(0)``.
    _method_call("key_press", st.tuples(st.just(0x41), st.just(0))),
    # ``scroll(amount)`` — small integer wheel deltas.
    _method_call("scroll", st.tuples(st.integers(min_value=-10, max_value=10))),
)

_METHOD_CALL_LIST_STRATEGY = st.lists(
    _METHOD_CALL_STRATEGY, min_size=0, max_size=30
)


# ``max_examples=100`` matches the task plan's ``@settings(max_examples=100)``
# directive. ``deadline=None`` disables the per-example time budget — the
# property body builds a fresh driver per example, which is fast in
# absolute terms but Windows scheduler jitter can flag spurious deadline
# failures.
_PROPERTY_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sum_call_counts(mock: MagicMock, attrs: Iterable[str]) -> int:
    """Total invocation count across the given ``mock.*`` attributes."""
    return sum(getattr(mock, a).call_count for a in attrs)


def _per_attr_counts(mock: MagicMock, attrs: Iterable[str]) -> str:
    """Render per-attribute counts for assertion failure messages."""
    return ", ".join(
        f"{a}={getattr(mock, a).call_count}" for a in attrs
    )


def _reset_dispatch_call_history(mock: MagicMock) -> None:
    """
    Clear ``call_count`` / ``call_args_list`` on every dispatch attribute.

    ``mock.reset_mock()`` (without ``side_effect=True``) preserves any
    configured return values / side_effects, which is exactly what we
    want here: the default success ``return_value=0`` survives the reset
    so any post-reset call (which the property forbids) would still
    behave non-trivially if it slipped through.
    """
    for attr_name in _ALL_DISPATCH_ATTRS:
        getattr(mock, attr_name).reset_mock()


def _invoke_driver_method(
    driver: KmBoxNetDriver,
    method_name: str,
    args: Tuple[Any, ...],
) -> None:
    """
    Dispatch a single tagged method call against the driver.

    Property 5 forbids the driver from raising out of any of these calls
    while in a non-CONNECTED state or after release(). The call sites
    are wrapped with their own try/except in the driver
    (``click_button`` / ``mouse_down`` / ``mouse_up`` / ``key_press`` /
    ``scroll`` log-and-swallow; ``send_click`` log-and-swallows;
    ``send_move`` re-raises per Req 1.8). For Property 5, however, the
    dispatcher's silent-drop gate fires *before* any ``kmNet.*`` call
    is attempted — there is nothing to raise — so the property holds
    structurally, and an unexpected exception here is a bug.
    """
    if method_name == "move":
        driver.move(*args)
    elif method_name == "click":
        driver.click(*args)
    elif method_name == "click_button":
        driver.click_button(*args)
    elif method_name == "mouse_down":
        driver.mouse_down(*args)
    elif method_name == "mouse_up":
        driver.mouse_up(*args)
    elif method_name == "key_press":
        driver.key_press(*args)
    elif method_name == "scroll":
        driver.scroll(*args)
    else:  # pragma: no cover - guarded by the strategy enumeration
        raise AssertionError(f"unknown method: {method_name!r}")


def _build_connected_driver(
    mock_kmnet: MagicMock,
    use_encryption: bool,
) -> KmBoxNetDriver:
    """
    Construct a ``KmBoxNetDriver`` that lands in CONNECTED state.

    The property body needs a driver instance that has successfully
    completed ``_connect()`` so we can subsequently force it into a
    non-CONNECTED state (or latch ``_released``) and replay the
    method-call list. Using a CONNECTED-then-mutated driver — rather
    than constructing a driver that fails to connect outright — keeps
    the dispatcher's other state (``_send_lock``, ``_PLAINTEXT_FN``,
    button tables) in the same shape as a real driver hitting the gate
    in production.

    Parameters
    ----------
    mock_kmnet:
        The ``MagicMock`` standing in for ``input.kmbox_net_driver.kmNet``.
        Its ``init`` MUST be configured to return ``0`` BEFORE this
        function is called.
    use_encryption:
        Forwarded to the constructor so the property exercises both
        dispatch tables across hypothesis examples.
    """
    driver = KmBoxNetDriver(
        ip=_TEST_IP,
        port=_TEST_PORT,
        uuid=_TEST_UUID,
        use_encryption=use_encryption,
        # Large ``target_cps`` keeps the click rate-limit window at
        # 1 ms so most generated ``click()`` calls pass the limiter and
        # actually reach the dispatcher (where the property's gate is
        # enforced). Even with the limiter dropping calls, a dropped
        # click contributes nothing to the "zero kmNet calls"
        # assertion — the property holds either way.
        target_cps=1000.0,
    )
    # Sanity: with ``kmNet.init`` returning 0 the driver MUST land in
    # CONNECTED, otherwise the rest of the test body is testing the
    # gate against a driver that already tripped it during construction
    # — which would make the assertion vacuously true and hide a real
    # routing regression.
    assert driver.connection_status is ConnectionStatus.CONNECTED, (
        "fixture precondition failed: driver did not reach CONNECTED "
        "state with mocked kmNet.init returning 0"
    )
    return driver


# ---------------------------------------------------------------------------
# Property test — Arm A: non-CONNECTED ``connection_status``
# ---------------------------------------------------------------------------


@pytest.mark.unit
@_PROPERTY_SETTINGS
@given(
    use_encryption=st.booleans(),
    non_connected_state=st.sampled_from(_NON_CONNECTED_STATES),
    method_calls=_METHOD_CALL_LIST_STRATEGY,
)
def test_non_connected_state_drops_all_sends(
    use_encryption: bool,
    non_connected_state: ConnectionStatus,
    method_calls: List[Tuple[str, Tuple[Any, ...]]],
) -> None:
    """
    Validates Req 6.9 / Req 2.7 (and the no-raise half of Req 1.7).

    For any sequence of public driver-method invocations issued while
    ``connection_status`` is one of
    ``DISCONNECTED`` / ``CONNECTING`` / ``RECONNECTING`` / ``FAILED``,
    Property 5 asserts:

      * Zero invocations of any ``kmNet.*`` attribute the driver may
        reach through ``_dispatch_call`` (the seven plaintext attrs and
        their seven ``enc_*`` twins).
      * No exception propagates out of any driver method call.

    Construction is performed in CONNECTED state via the
    ``kmNet.init=0`` mock; ``connection_status`` is then force-set to
    the non-CONNECTED value before the call list is replayed. The
    ``_released`` flag is left at ``False`` so the dispatcher's first
    gate is *not* the one tripping — the property must hold via the
    second gate (``connection_status is not CONNECTED``) alone.
    """
    original_kmnet = kmbox_net_driver.kmNet
    mock_kmnet = MagicMock(name="kmNet")
    mock_kmnet.init.return_value = 0
    kmbox_net_driver.kmNet = mock_kmnet
    try:
        with patch(
            "input.kmbox_net_driver.threading.Thread",
            new=_make_thread_factory(),
        ), patch(
            "input.kmbox_net_driver.time.sleep",
            new=lambda *_a, **_kw: None,
        ), patch(
            # The inline heartbeat thread (started by __init__ after a
            # successful connect under the sync-thread patch) would
            # otherwise sit in ``Event.wait(1.0)`` forever. Returning
            # True from ``wait`` mimics the post-release() signal so
            # the loop body returns on its first iteration without
            # issuing any probe.
            "input.kmbox_net_driver.threading.Event.wait",
            new=lambda self, timeout=None: True,
        ):
            driver = _build_connected_driver(mock_kmnet, use_encryption)

            # Force the driver into the target non-CONNECTED state.
            # ``initialized`` is left True/False per the driver's own
            # invariant: ``_dispatch_call`` consults ``connection_status``,
            # not ``initialized``, so the gate trips regardless. We
            # explicitly set ``initialized = False`` to keep the
            # internal state self-consistent (every non-CONNECTED state
            # has ``initialized = False`` by construction in the driver).
            driver.connection_status = non_connected_state
            driver.initialized = False

            # Discard any ``kmNet.*`` calls made during construction
            # (none expected today, but the reset is cheap insurance
            # against future ``__init__`` evolution). The ``init`` call
            # itself is on a different attribute and is not in
            # ``_ALL_DISPATCH_ATTRS``.
            _reset_dispatch_call_history(mock_kmnet)

            # ----- Drive the method-call sequence ----------------------
            # Property 5 asserts no exception propagates; we do NOT
            # wrap this loop in try/except because catching here would
            # mask a Property 5 violation. The driver's silent-drop
            # gate fires before any ``kmNet.*`` call attempt, so there
            # is nothing for the dispatcher to raise.
            for method_name, args in method_calls:
                _invoke_driver_method(driver, method_name, args)

        # ----- Property assertion ------------------------------------
        total_calls = _sum_call_counts(mock_kmnet, _ALL_DISPATCH_ATTRS)
        assert total_calls == 0, (
            "Property 5 violated: connection_status="
            f"{non_connected_state.value!r} emitted {total_calls} "
            f"kmNet call(s) across {len(method_calls)} method "
            f"invocation(s); per-attribute counts: "
            + _per_attr_counts(mock_kmnet, _ALL_DISPATCH_ATTRS)
            + f"; method_calls={method_calls!r}"
        )
    finally:
        # Restore the module-level ``kmNet`` binding regardless of
        # outcome so subsequent tests in the same session are not
        # contaminated by this test's mock.
        kmbox_net_driver.kmNet = original_kmnet


# ---------------------------------------------------------------------------
# Property test — Arm B: ``_released = True``
# ---------------------------------------------------------------------------


@pytest.mark.unit
@_PROPERTY_SETTINGS
@given(
    use_encryption=st.booleans(),
    method_calls=_METHOD_CALL_LIST_STRATEGY,
)
def test_released_drops_all_sends(
    use_encryption: bool,
    method_calls: List[Tuple[str, Tuple[Any, ...]]],
) -> None:
    """
    Validates Req 1.7 (terminal ``_released`` gate, no-raise half).

    For any sequence of public driver-method invocations issued after
    ``_released`` has been latched to ``True``, Property 5 asserts:

      * Zero invocations of any ``kmNet.*`` attribute the driver may
        reach through ``_dispatch_call``.
      * No exception propagates out of any driver method call.

    Construction is performed in CONNECTED state via the
    ``kmNet.init=0`` mock; ``_released`` is then force-latched while
    ``connection_status`` is left at CONNECTED so the dispatcher's
    second gate is *not* the one tripping — the property must hold via
    the first gate (``if self._released: return None``) alone.

    Note we set ``_released`` directly rather than calling
    ``release()``: that keeps the test focused on the dispatcher
    contract and avoids exercising the ``release()`` heartbeat-join
    path (covered separately by Task 7.9's example tests).
    """
    original_kmnet = kmbox_net_driver.kmNet
    mock_kmnet = MagicMock(name="kmNet")
    mock_kmnet.init.return_value = 0
    kmbox_net_driver.kmNet = mock_kmnet
    try:
        with patch(
            "input.kmbox_net_driver.threading.Thread",
            new=_make_thread_factory(),
        ), patch(
            "input.kmbox_net_driver.time.sleep",
            new=lambda *_a, **_kw: None,
        ), patch(
            "input.kmbox_net_driver.threading.Event.wait",
            new=lambda self, timeout=None: True,
        ):
            driver = _build_connected_driver(mock_kmnet, use_encryption)

            # Force-latch the terminal release flag while leaving
            # ``connection_status`` at CONNECTED so the property
            # exercises the first gate in ``_dispatch_call``
            # (Req 1.7) in isolation. ``initialized`` is left at True
            # for the same reason: the dispatcher does not consult it,
            # and leaving it True ensures the public-API methods'
            # ``if not self.initialized`` short-circuits do NOT fire —
            # the property must hold via the dispatcher's first gate
            # alone.
            driver._released = True

            # Discard any incidental ``kmNet.*`` calls made during
            # construction.
            _reset_dispatch_call_history(mock_kmnet)

            # ----- Drive the method-call sequence ----------------------
            for method_name, args in method_calls:
                _invoke_driver_method(driver, method_name, args)

        # ----- Property assertion ------------------------------------
        total_calls = _sum_call_counts(mock_kmnet, _ALL_DISPATCH_ATTRS)
        assert total_calls == 0, (
            "Property 5 violated: _released=True emitted "
            f"{total_calls} kmNet call(s) across {len(method_calls)} "
            "method invocation(s); per-attribute counts: "
            + _per_attr_counts(mock_kmnet, _ALL_DISPATCH_ATTRS)
            + f"; method_calls={method_calls!r}"
        )
    finally:
        kmbox_net_driver.kmNet = original_kmnet
