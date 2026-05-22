"""
Property test — Task 4.7 of spec ``kmbox-net-integration``.

# Feature: kmbox-net-integration, Property 3: Invalid move input is a no-op.

**Property 3: Invalid move input is a no-op**

    *For any* ``(x, y)`` input to :meth:`KmBoxNetDriver.move` where either
    component is non-finite (``NaN``, ``+inf``, ``-inf``) or strictly outside
    the inclusive range ``[-32767.0, 32767.0]``, no ``kmNet.move`` or
    ``kmNet.enc_move`` invocation SHALL occur and the values of
    ``remainder_x`` and ``remainder_y`` immediately after the call SHALL be
    exactly equal to their values immediately before the call.

**Validates: Requirements 1.4**

Implementation notes
--------------------
The driver routes every move through ``_dispatch_call("move", ...)`` which
maps to ``kmNet.move`` when ``use_encryption=False`` and ``kmNet.enc_move``
when ``use_encryption=True``. Req 1.4 mandates that invalid input never
reaches that dispatch site AND never perturbs the sub-pixel accumulator —
the validation gate inside :meth:`KmBoxNetDriver.move` must short-circuit
*before* :meth:`BaseMouse.calculate_move_amount` runs, because that
function unconditionally mutates ``remainder_x`` / ``remainder_y``.

The property is parameterized over ``use_encryption`` so the no-op contract
is verified for both routing tables (``_PLAINTEXT_FN`` and ``_ENCRYPTED_FN``)
in the same run; both ``kmNet.move`` and ``kmNet.enc_move`` are asserted
non-called regardless of which table would have been selected on a valid
input.

The invalid-input generator partitions the failure modes:

  - non-finite floats: ``NaN``, ``+inf``, ``-inf``;
  - magnitudes strictly greater than ``32767.0`` (just past the inclusive
    boundary, captured via :func:`math.nextafter`).

The composite ``(x, y)`` strategy guarantees *at least one* component is
invalid; the other component is drawn from the unrestricted float space
(including valid values) so the property exercises the documented
"either component invalid → drop" contract from the requirement text.
"""

from __future__ import annotations

import math
from typing import Iterator
from unittest.mock import MagicMock

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

# Inclusive boundary of the valid move-input range (Req 1.4). Mirrors the
# ``_MOVE_INPUT_MIN`` / ``_MOVE_INPUT_MAX`` constants on the driver class.
_MOVE_BOUND = 32767.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kmnet_mock() -> Iterator[MagicMock]:
    """
    Replace ``input.kmbox_net_driver.kmNet`` with a fresh ``MagicMock``.

    The mock's ``init`` returns ``0`` so the driver constructed under this
    fixture transitions cleanly to ``CONNECTED``; both ``move`` and
    ``enc_move`` (the two attributes whose call counts the property
    asserts) default to ``MagicMock`` no-ops that record every invocation.

    The original module-level binding (typically ``None`` on systems
    without the vendor ``kmNet.pyd``) is restored on teardown so test
    ordering does not matter.
    """
    original = kmbox_net_driver.kmNet
    mock = MagicMock(name="kmNet")
    mock.init.return_value = 0
    kmbox_net_driver.kmNet = mock
    try:
        yield mock
    finally:
        kmbox_net_driver.kmNet = original


def _make_connected_driver(use_encryption: bool) -> KmBoxNetDriver:
    """
    Construct a ``KmBoxNetDriver`` and assert it reached ``CONNECTED``.

    The fixture's mocked ``kmNet.init`` returns ``0``, so ``__init__`` is
    expected to drop straight into the CONNECTED state. Asserting it here
    makes the property's preconditions locally readable and turns a
    fixture regression into a precondition error rather than a confusing
    property failure.
    """
    driver = KmBoxNetDriver(
        ip=_TEST_IP,
        port=_TEST_PORT,
        uuid=_TEST_UUID,
        use_encryption=use_encryption,
        target_cps=10.0,
    )
    assert driver.connection_status is ConnectionStatus.CONNECTED, (
        "fixture precondition failed: driver did not reach CONNECTED"
    )
    return driver


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Smallest float strictly greater / less than the inclusive boundary. Using
# ``math.nextafter`` rather than a chosen literal (e.g. ``32767.5``) makes
# the generator cover the tightest representable failure case — a value
# the validator's strict ``<= _MOVE_INPUT_MAX`` comparison would still
# reject.
_JUST_ABOVE_BOUND = math.nextafter(_MOVE_BOUND, math.inf)
_JUST_BELOW_NEG_BOUND = math.nextafter(-_MOVE_BOUND, -math.inf)


# Out-of-range finite floats. Splits into the positive-overflow and
# negative-overflow branches so Hypothesis explores both tails. The upper
# bound is large but representable; ``allow_nan`` / ``allow_infinity`` are
# disabled to keep this strategy disjoint from ``_nan_inf_strategy``.
_out_of_range_strategy = st.one_of(
    st.floats(
        min_value=_JUST_ABOVE_BOUND,
        max_value=1e15,
        allow_nan=False,
        allow_infinity=False,
    ),
    st.floats(
        min_value=-1e15,
        max_value=_JUST_BELOW_NEG_BOUND,
        allow_nan=False,
        allow_infinity=False,
    ),
)

# The three non-finite values the validator's ``math.isfinite`` gate
# rejects. ``sampled_from`` keeps the strategy compact and avoids
# Hypothesis spending its example budget exploring float bit patterns
# that all map to the same logical case.
_nan_inf_strategy = st.sampled_from(
    [float("nan"), float("inf"), float("-inf")]
)

# Composite invalid-float strategy: any value that the Req 1.4 gate
# rejects, regardless of which branch (non-finite or out-of-range).
_invalid_float_strategy = st.one_of(_nan_inf_strategy, _out_of_range_strategy)

# Any finite value drawn from the full ``float`` space (in-range or out).
# Used as the "other component" so the property exercises the documented
# "either component invalid → drop" contract — a valid x paired with an
# invalid y must still drop, and vice versa.
_any_float_strategy = st.floats(allow_nan=True, allow_infinity=True)


def _at_least_one_invalid_xy() -> st.SearchStrategy[tuple[float, float]]:
    """
    ``(x, y)`` tuples where AT LEAST ONE component is Req-1.4-invalid.

    Three disjoint branches cover the failure modes:

      1. ``x`` invalid, ``y`` arbitrary;
      2. ``x`` arbitrary, ``y`` invalid;
      3. both invalid (subsumed by either of the above, but listed
         explicitly so Hypothesis weights the both-invalid case fairly).
    """
    return st.one_of(
        st.tuples(_invalid_float_strategy, _any_float_strategy),
        st.tuples(_any_float_strategy, _invalid_float_strategy),
        st.tuples(_invalid_float_strategy, _invalid_float_strategy),
    )


# ``max_examples=100`` matches the task plan's
# ``@settings(max_examples=100)`` directive. ``deadline=None`` disables
# the per-example time budget — the property body is fast (a single
# ``move`` call against a mocked ``kmNet`` binding) but Windows scheduler
# jitter can flag spurious deadline failures on CI.
_PROPERTY_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        # The ``kmnet_mock`` fixture is function-scoped (one instance per
        # parametrized run), but the test body resets it via
        # ``kmnet_mock.reset_mock()`` at the top of every Hypothesis
        # example. Reuse across examples is therefore safe and intentional.
        HealthCheck.function_scoped_fixture,
    ],
)


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("use_encryption", [False, True])
@_PROPERTY_SETTINGS
@given(xy=_at_least_one_invalid_xy())
def test_invalid_move_is_noop(
    kmnet_mock: MagicMock,
    use_encryption: bool,
    xy: tuple[float, float],
) -> None:
    """
    Validates Req 1.4.

    For any ``(x, y)`` where at least one component is non-finite or
    strictly outside ``[-32767.0, 32767.0]``:

      - ``kmNet.move`` MUST NOT be invoked;
      - ``kmNet.enc_move`` MUST NOT be invoked;
      - ``remainder_x`` MUST equal its pre-call value (bit-exact);
      - ``remainder_y`` MUST equal its pre-call value (bit-exact).

    Both encryption modes are exercised so the no-op contract is verified
    against both ``_PLAINTEXT_FN`` and ``_ENCRYPTED_FN`` routing tables.
    """
    x, y = xy
    driver = _make_connected_driver(use_encryption=use_encryption)

    # Reset the call ledger so any incidental ``kmNet.*`` calls made by
    # ``__init__`` (e.g. ``kmNet.init``) do not pollute the assertion. The
    # property is concerned strictly with the invocations triggered by
    # ``move`` itself.
    kmnet_mock.reset_mock()

    # Snapshot the sub-pixel accumulator BEFORE the call. The driver
    # initializes both remainders to ``0.0`` in ``BaseMouse.__init__``, but
    # snapshotting is robust against a future change that initializes
    # them to a non-zero value (e.g. a persisted aim offset).
    remainder_x_before = driver.remainder_x
    remainder_y_before = driver.remainder_y

    # Invoke under test. ``move`` MUST swallow the invalid input silently;
    # any exception raised here would itself be a Req 1.4 violation.
    driver.move(x, y)

    # No UDP packet emitted on either dispatch table.
    assert kmnet_mock.move.call_count == 0, (
        f"kmNet.move was called {kmnet_mock.move.call_count} time(s) "
        f"with input ({x!r}, {y!r}); Req 1.4 mandates no UDP packet on "
        "invalid input"
    )
    assert kmnet_mock.enc_move.call_count == 0, (
        f"kmNet.enc_move was called {kmnet_mock.enc_move.call_count} "
        f"time(s) with input ({x!r}, {y!r}); Req 1.4 mandates no UDP "
        "packet on invalid input"
    )

    # Remainders unchanged — bit-exact equality. Float equality is the
    # right comparison here (not ``math.isclose``) because Req 1.4 is a
    # strict no-op: the validator must short-circuit before
    # ``calculate_move_amount`` mutates the accumulator, so there should
    # be no rounding to tolerate.
    assert driver.remainder_x == remainder_x_before, (
        f"remainder_x changed from {remainder_x_before!r} to "
        f"{driver.remainder_x!r} after invalid move({x!r}, {y!r})"
    )
    assert driver.remainder_y == remainder_y_before, (
        f"remainder_y changed from {remainder_y_before!r} to "
        f"{driver.remainder_y!r} after invalid move({x!r}, {y!r})"
    )
