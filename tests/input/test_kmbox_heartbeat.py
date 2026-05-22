"""
Example tests — Task 7.9 of spec ``kmbox-net-integration``.

Tests for the heartbeat thread cadence, ``release()``-driven thread
termination timing, the lifecycle-state transitions performed by
``_connect()``, and the membership of the ``ConnectionStatus`` enum.

The four scenarios exercised here are the four observable contracts of
the heartbeat / lifecycle subsystem documented in design.md §
``Heartbeat thread + reconnect FSM`` and acceptance criteria
``Requirement 6: Connection Lifecycle``:

  1. ``test_heartbeat_cadence_3_5s_window``
     → Req 6.5: while ``connection_status is CONNECTED``, the driver
       MUST issue one heartbeat probe every 1000 ms (±50 ms). Counted
       over a 3.5 s wall-clock window, this yields 3 ± 1 invocations.

  2. ``test_release_stops_heartbeat_in_1s``
     → Req 6.10: ``release()`` MUST stop the heartbeat thread within
       1.0 s. Asserted by measuring ``release()``'s wall-clock
       duration AND verifying ``_heartbeat_thread.is_alive()`` is
       ``False`` on return.

  3. ``test_state_transitions``
     → Req 6.2 / 6.3 / 6.4: the success path traverses
       ``DISCONNECTED → CONNECTING → CONNECTED`` in order, and each
       failure mode (import error, init exception, non-zero init
       result, init timeout) terminates in ``FAILED``.

  4. ``test_enum_membership``
     → Req 6.1: the ``ConnectionStatus`` enum has exactly the five
       values ``disconnected``, ``connecting``, ``connected``,
       ``reconnecting``, ``failed``.

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.10**

Implementation notes
--------------------
The module-level ``kmNet`` binding inside ``input.kmbox_net_driver`` is
the single chokepoint the driver reaches for vendor calls. The fixture
``kmnet_mock`` replaces that binding with a ``MagicMock`` whose ``init``
returns ``0`` (so ``__init__`` admits the driver to ``CONNECTED``) and
whose ``monitor`` returns ``0`` (so heartbeat probes succeed without
triggering the reconnect FSM). Because ``MagicMock`` auto-creates any
attribute access, ``hasattr(kmNet, "monitor")`` is ``True`` and the
heartbeat takes its preferred ``kmNet.monitor(0)`` branch.

Wall-clock timing is used for the cadence and release-timing tests.
The heartbeat loop's cadence sleep uses ``threading.Event.wait(1.0)``,
which is backed by an OS-level condition variable — it cannot be
intercepted by patching ``time.sleep`` or ``time.monotonic``, so the
only reliable measurement is real wall time. The 3.5 s window plus the
``3 ± 1`` tolerance accommodates scheduler jitter on Windows.

Every test that constructs a successfully-connected driver MUST call
``driver.release()`` before returning so the daemon heartbeat thread
does not leak across the test session.
"""

from __future__ import annotations

import time
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from input import kmbox_net_driver
from input.kmbox_net_driver import ConnectionStatus, KmBoxNetDriver


# ---------------------------------------------------------------------------
# Constants and fixtures
# ---------------------------------------------------------------------------

_TEST_IP = "192.168.2.188"
_TEST_PORT = "6234"
_TEST_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def kmnet_mock() -> Iterator[MagicMock]:
    """
    Replace ``input.kmbox_net_driver.kmNet`` with a fresh ``MagicMock``.

    Pre-configures the two vendor entry points exercised by these
    tests:

      - ``init.return_value = 0`` so ``_connect()`` admits the driver
        to ``CONNECTED`` on the success path.
      - ``monitor.return_value = 0`` so each heartbeat probe returns
        ``True`` and the reconnect FSM is NOT entered. Without this,
        the heartbeat would observe a non-zero return value (the
        ``MagicMock`` default), tear down the link, and the cadence
        test would observe a totally different code path.

    The original binding (typically ``None`` when ``kmNet.pyd`` is
    absent) is captured at setup and restored on teardown so tests can
    run in any order without leaking module state.
    """
    original = kmbox_net_driver.kmNet
    mock = MagicMock(name="kmNet")
    mock.init.return_value = 0
    mock.monitor.return_value = 0
    kmbox_net_driver.kmNet = mock
    try:
        yield mock
    finally:
        kmbox_net_driver.kmNet = original


def _make_driver(**overrides) -> KmBoxNetDriver:
    """Construct a ``KmBoxNetDriver`` with the canonical test args."""
    kwargs = {
        "ip": _TEST_IP,
        "port": _TEST_PORT,
        "uuid": _TEST_UUID,
        "use_encryption": True,
        "target_cps": 10.0,
    }
    kwargs.update(overrides)
    return KmBoxNetDriver(**kwargs)


class _StateRecordingDriver(KmBoxNetDriver):
    """
    Subclass that records every assignment to ``connection_status``.

    The recording is performed via ``__setattr__`` so all transitions
    are captured in order — including the initial ``DISCONNECTED``
    write performed by ``__init__`` before ``_connect()`` is called and
    the ``CONNECTING`` write performed inside ``_connect()`` before
    ``kmNet.init`` is invoked.

    The history list is initialized via ``object.__setattr__`` so the
    very first ``__setattr__`` call (from ``BaseMouse.__init__``) does
    not crash on a missing attribute lookup.
    """

    def __init__(self, *args, **kwargs):
        object.__setattr__(self, "_state_history", [])
        super().__init__(*args, **kwargs)

    def __setattr__(self, name: str, value) -> None:
        if name == "connection_status":
            self._state_history.append(value)
        super().__setattr__(name, value)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_enum_membership() -> None:
    """
    Validates Req 6.1.

    The ``ConnectionStatus`` enum MUST have exactly the five values
    enumerated in the requirement text — no more, no less. The string
    values MUST match verbatim (lowercase, single word) so the GUI
    Configuration page can compare against the literal strings without
    an explicit ``.value`` access.
    """
    expected = {
        "disconnected",
        "connecting",
        "connected",
        "reconnecting",
        "failed",
    }

    actual_values = {member.value for member in ConnectionStatus}
    assert actual_values == expected, (
        f"ConnectionStatus values mismatch (Req 6.1): "
        f"expected {expected}, got {actual_values}"
    )

    # Exact count — guards against future additions slipping past the
    # set-equality check above (which would fire on a subset, but a
    # superset is also forbidden by Req 6.1's "exactly five" wording).
    assert len(ConnectionStatus) == 5, (
        f"ConnectionStatus must have exactly 5 members (Req 6.1); "
        f"got {len(ConnectionStatus)}"
    )

    # Each named member is reachable by attribute access — this is the
    # surface the rest of the codebase consumes (e.g.
    # ``ConnectionStatus.CONNECTED``), so an enum that satisfied the
    # value-set assertion but renamed a member would still break
    # callers. Asserting attribute access pins the public contract.
    assert ConnectionStatus.DISCONNECTED.value == "disconnected"
    assert ConnectionStatus.CONNECTING.value == "connecting"
    assert ConnectionStatus.CONNECTED.value == "connected"
    assert ConnectionStatus.RECONNECTING.value == "reconnecting"
    assert ConnectionStatus.FAILED.value == "failed"


@pytest.mark.unit
def test_state_transitions(kmnet_mock: MagicMock) -> None:
    """
    Validates Req 6.2 / 6.3 / 6.4.

    On the success path, the driver MUST traverse
    ``DISCONNECTED → CONNECTING → CONNECTED`` in order during
    construction (Req 6.2 / 6.3). The intermediate ``CONNECTING`` write
    is the one that distinguishes a correctly-implemented lifecycle
    from one that simply jumps to the terminal state — observers
    (heartbeat thread, GUI publisher) rely on it to render the
    in-flight indicator.

    On each of the four failure modes, the driver MUST terminate in
    ``FAILED`` (Req 6.4):

      - import error (vendor ``.pyd`` absent)
      - exception raised from ``kmNet.init``
      - non-zero result code from ``kmNet.init``
      - timeout: ``kmNet.init`` exceeds the 5-second bound (Req 2.4)

    The success path is recorded via the ``_StateRecordingDriver``
    subclass so the in-order transition can be asserted; failure-mode
    assertions only need the terminal state, since that is what
    ``_dispatch_call``'s send-gate (Req 6.9) consults.
    """
    # ---- Success path: DISCONNECTED → CONNECTING → CONNECTED ----
    driver = _StateRecordingDriver(
        ip=_TEST_IP,
        port=_TEST_PORT,
        uuid=_TEST_UUID,
        use_encryption=True,
        target_cps=10.0,
    )
    try:
        # The recorded sequence must contain — in order — the three
        # canonical transitions. Equality (rather than ``in``) pins the
        # exact transition list so a regression that introduced a
        # spurious extra write would fail this test.
        assert driver._state_history == [
            ConnectionStatus.DISCONNECTED,
            ConnectionStatus.CONNECTING,
            ConnectionStatus.CONNECTED,
        ], (
            "expected DISCONNECTED → CONNECTING → CONNECTED transition "
            f"(Req 6.2 / 6.3); got {driver._state_history!r}"
        )
        # Final state — what an external observer sees after __init__
        # returns. ``initialized`` MUST also be True per Req 6.3.
        assert driver.connection_status is ConnectionStatus.CONNECTED
        assert driver.initialized is True
    finally:
        driver.release()

    # ---- Failure mode 1: import error ----
    # ``_ensure_kmnet`` raising is the realistic shape of the
    # vendor-binary-absent failure (``ImportError: No module named
    # 'kmNet'``). The driver MUST catch it and transition to FAILED.
    with patch.object(
        kmbox_net_driver,
        "_ensure_kmnet",
        side_effect=ImportError("No module named 'kmNet'"),
    ):
        driver = _make_driver()
    assert driver.connection_status is ConnectionStatus.FAILED, (
        "import error must terminate in FAILED (Req 6.4)"
    )
    assert driver.initialized is False
    # No heartbeat thread is created on a failed connect — release()
    # is still safe to call (idempotent guard inside release()), but
    # there is no thread to join here.

    # ---- Failure mode 2: kmNet.init raises ----
    kmnet_mock.init.side_effect = RuntimeError("vendor exploded")
    try:
        driver = _make_driver()
        assert driver.connection_status is ConnectionStatus.FAILED, (
            "init exception must terminate in FAILED (Req 6.4)"
        )
        assert driver.initialized is False
    finally:
        kmnet_mock.init.side_effect = None

    # ---- Failure mode 3: kmNet.init returns non-zero ----
    kmnet_mock.init.return_value = 7  # any non-zero
    try:
        driver = _make_driver()
        assert driver.connection_status is ConnectionStatus.FAILED, (
            "non-zero init result must terminate in FAILED (Req 6.4)"
        )
        assert driver.initialized is False
    finally:
        kmnet_mock.init.return_value = 0

    # ---- Failure mode 4: kmNet.init exceeds the 5 s bound ----
    # The vendor function has no timeout parameter; we simulate a hung
    # call with a 10 s sleep. The driver's worker is daemonized so the
    # sleep continues in the orphaned thread and does not block the
    # test process. The terminal state MUST still be FAILED.
    kmnet_mock.init.side_effect = lambda *args, **kwargs: time.sleep(10.0)
    try:
        start = time.monotonic()
        driver = _make_driver()
        elapsed = time.monotonic() - start
        # Sanity: the construction call must complete within ~5.5 s
        # (Req 2.4). If it returned faster than ~4.5 s the timeout
        # branch did not fire and the assertion below would be
        # vacuous.
        assert 4.5 <= elapsed < 5.6, (
            f"timeout-branch construction took {elapsed:.2f} s; "
            "expected ~5 s (Req 2.4)"
        )
        assert driver.connection_status is ConnectionStatus.FAILED, (
            "init timeout must terminate in FAILED (Req 6.4)"
        )
        assert driver.initialized is False
    finally:
        kmnet_mock.init.side_effect = None


@pytest.mark.unit
def test_release_stops_heartbeat_in_1s(kmnet_mock: MagicMock) -> None:
    """
    Validates Req 6.10.

    ``release()`` MUST stop the heartbeat thread within 1000 ms. The
    contract is enforced structurally by ``release()``:

      1. ``_heartbeat_stop.set()`` interrupts the loop's
         ``Event.wait(1.0)`` cadence sleep immediately.
      2. ``_heartbeat_thread.join(timeout=1.0)`` bounds the wait at
         exactly the requirement's ceiling.

    This test asserts both observable consequences:

      - The wall-clock duration of ``release()`` is strictly less than
        1.0 s (a thread that did NOT receive the stop signal would
        consume the full 1.0 s join timeout).
      - ``_heartbeat_thread.is_alive()`` is ``False`` after ``release()``
        returns. The 1.0 s timeout on ``join`` would otherwise mask a
        thread that never terminated.
    """
    driver = _make_driver()

    # Sanity: the heartbeat thread must actually be running before
    # release() — otherwise the timing assertion is vacuous.
    assert driver._heartbeat_thread is not None, (
        "heartbeat thread must be created on a CONNECTED driver"
    )
    assert driver._heartbeat_thread.is_alive(), (
        "heartbeat thread must be alive before release()"
    )

    # Capture the thread reference BEFORE release() so the post-release
    # is_alive() check observes the same Thread object even if a future
    # implementation clears ``_heartbeat_thread`` during teardown.
    heartbeat_thread = driver._heartbeat_thread

    start = time.monotonic()
    driver.release()
    elapsed = time.monotonic() - start

    assert elapsed < 1.0, (
        f"release() took {elapsed:.3f} s; Req 6.10 mandates < 1.0 s"
    )
    assert not heartbeat_thread.is_alive(), (
        "heartbeat thread must terminate within release()'s 1.0 s "
        "join window (Req 6.10)"
    )

    # Terminal state contract — release() also sets the canonical
    # post-teardown lifecycle markers per Req 6.10's status clause.
    assert driver.connection_status is ConnectionStatus.DISCONNECTED
    assert driver.initialized is False


@pytest.mark.unit
@pytest.mark.slow
def test_heartbeat_cadence_3_5s_window(kmnet_mock: MagicMock) -> None:
    """
    Validates Req 6.5.

    While ``connection_status is CONNECTED``, the driver MUST issue one
    heartbeat probe every 1000 ms (±50 ms). Counted over a 3.5 s
    wall-clock window, this yields 3 ± 1 invocations:

      - The first probe fires shortly after the heartbeat thread
        starts (no initial wait), so a perfectly-timed run produces
        probes at approximately T=0, T=1, T=2, T=3 — four probes.
      - Scheduler jitter on Windows can push a probe past the 3.5 s
        boundary, dropping the count to three.
      - A pathologically slow first iteration could yield two probes.

    The acceptable range is ``{2, 3, 4}`` — the ``3 ± 1`` tolerance
    specified by the task. Counts outside this range indicate either
    a cadence regression (> 1 Hz or < 1 Hz) or a missing wait between
    iterations.

    Wall-clock timing is used because the heartbeat loop's cadence
    sleep uses ``threading.Event.wait(1.0)``, which is backed by an
    OS-level condition variable and cannot be intercepted by patching
    ``time.sleep`` or ``time.monotonic``. The 3.5 s sleep is the
    minimum window that gives a determinable expected count.
    """
    # ``kmNet.monitor`` is the preferred liveness primitive — selected
    # by ``_heartbeat_call`` whenever ``hasattr(kmNet, "monitor")`` is
    # True, which is always the case with a MagicMock. Configure it to
    # return 0 so each probe is treated as a successful liveness check
    # and the reconnect FSM is NOT entered (which would change the
    # call pattern entirely).
    kmnet_mock.monitor.return_value = 0

    driver = _make_driver()
    try:
        # Sanity: the driver must be CONNECTED before we count probes.
        # Without this guard, a regression that left the driver in
        # FAILED would trivially produce zero probes and mask the bug.
        assert driver.connection_status is ConnectionStatus.CONNECTED
        assert driver._heartbeat_thread is not None
        assert driver._heartbeat_thread.is_alive()

        # 3.5 s observation window. A shorter window has too few
        # samples to distinguish 1 Hz from 2 Hz reliably; a longer
        # window slows the test suite without adding signal.
        time.sleep(3.5)

        call_count = kmnet_mock.monitor.call_count
        assert 2 <= call_count <= 4, (
            f"heartbeat cadence over 3.5 s window: expected 3 ± 1 "
            f"calls (Req 6.5); got {call_count}"
        )
    finally:
        # Tear down the heartbeat thread so it does not leak across
        # the test session. ``release()`` is idempotent and safe even
        # if the assertion above fired.
        driver.release()
