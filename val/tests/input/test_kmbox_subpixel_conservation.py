"""
Property test — Task 4.6 of spec ``kmbox-net-integration``.

# Feature: kmbox-net-integration, Property 2: Sub-pixel conservation
#   across move sequences.

**Property 2: Sub-pixel conservation across move sequences**

    *For any* finite sequence of ``move(x, y)`` calls where each ``x`` and
    ``y`` is a finite float in the inclusive range ``[-32767.0, 32767.0]``,
    the sum of the integer arguments passed to all resulting
    ``send_move(int_x, int_y)`` invocations PLUS the driver's final
    ``(remainder_x, remainder_y)`` values SHALL exactly equal the sum of
    the input ``(x, y)`` values (within float tolerance ``1e-9`` to absorb
    the ordering noise of computing the reference sum independently).

**Validates: Requirements 1.3**

Implementation notes
--------------------
The conservation property is the formal statement of the Unibot-style
sub-pixel remainder pattern that ``BaseMouse.calculate_move_amount`` (and
therefore ``KmBoxNetDriver.move`` → ``send_move`` → ``_dispatch_call``)
implements:

    For each move(x, y):
        move_x_internal = x + remainder_x_old
        int_emitted     = trunc(move_x_internal)        # int(...) truncates
        remainder_x_new = move_x_internal - int_emitted

    Telescoping over a sequence:
        sum(int_emitted) + remainder_x_final == sum(x) + remainder_x_initial
        (with remainder_x_initial == 0 immediately after construction)

The driver is configured with ``use_encryption=False`` so emitted moves
land on the plaintext ``kmNet.move`` (not ``kmNet.enc_move``), which lets
the test inspect ``mock.move.call_args_list`` directly without needing a
second branch for the encrypted path.

The mocking pattern mirrors ``tests/input/test_kmbox_connect.py``:
``input.kmbox_net_driver.kmNet`` is replaced with a fresh ``MagicMock``
whose ``init`` returns ``0`` so the driver lands in ``CONNECTED`` and
``_dispatch_call`` actually invokes the resolved attribute. The mock is
constructed inside the test body (not via a function-scoped fixture) to
avoid Hypothesis's ``function_scoped_fixture`` health-check warning while
still giving every Hypothesis example a fresh mock.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, strategies as st

from input import kmbox_net_driver
from input.kmbox_net_driver import ConnectionStatus, KmBoxNetDriver


# ---------------------------------------------------------------------------
# Constants and strategies
# ---------------------------------------------------------------------------

_TEST_IP = "192.168.2.188"
_TEST_PORT = "6234"
_TEST_UUID = "00000000-0000-0000-0000-000000000000"

# Req 1.3 input domain: finite floats in [-32767.0, 32767.0]. NaN and ±inf
# are excluded by ``allow_nan=False`` / ``allow_infinity=False`` because
# they are covered by Property 3 (``test_kmbox_invalid_move``); mixing
# their counterexamples into this property would trigger the Req 1.4
# no-op gate and hide conservation failures behind a guard branch.
_MOVE_FLOATS = st.floats(
    min_value=-32767.0,
    max_value=32767.0,
    allow_nan=False,
    allow_infinity=False,
)

# A sequence of (x, y) move pairs. ``min_size=0`` exercises the trivial
# empty-sequence case (final remainders == 0, sum of emitted == 0).
# ``max_size=200`` keeps each example bounded but still long enough for
# remainder accumulation patterns to emerge.
_MOVE_SEQUENCES = st.lists(
    st.tuples(_MOVE_FLOATS, _MOVE_FLOATS),
    min_size=0,
    max_size=200,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_kmnet_mock() -> tuple[MagicMock, object]:
    """Patch ``input.kmbox_net_driver.kmNet`` with a fresh ``MagicMock``.

    Returns the mock and the original binding so the caller can restore
    it on teardown. ``mock.init`` is configured to return ``0`` so the
    driver transitions to ``CONNECTED`` and ``_dispatch_call`` will
    actually route ``send_move`` through to ``mock.move``.
    """
    original = kmbox_net_driver.kmNet
    mock = MagicMock(name="kmNet")
    mock.init.return_value = 0
    kmbox_net_driver.kmNet = mock
    return mock, original


def _make_driver() -> KmBoxNetDriver:
    """Construct a ``CONNECTED`` driver with plaintext routing.

    ``use_encryption=False`` so emitted moves land on ``kmNet.move``
    (not ``kmNet.enc_move``), matching the property's inspection target.
    """
    return KmBoxNetDriver(
        ip=_TEST_IP,
        port=_TEST_PORT,
        uuid=_TEST_UUID,
        use_encryption=False,
        target_cps=10.0,
    )


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@pytest.mark.unit
@given(inputs=_MOVE_SEQUENCES)
@settings(max_examples=100)
def test_subpixel_conservation_across_move_sequences(
    inputs: list[tuple[float, float]],
) -> None:
    """
    Property 2: sub-pixel conservation across move sequences.

    For every finite sequence of valid ``(x, y)`` move inputs, after the
    full sequence has been issued through ``driver.move``:

        sum(int_x emitted to kmNet.move) + driver.remainder_x  ==  sum(input x)
        sum(int_y emitted to kmNet.move) + driver.remainder_y  ==  sum(input y)

    within absolute tolerance ``1e-9`` (covers the ordering noise of
    computing the reference sum independently with Python's left-to-right
    floating-point addition).

    Validates: Requirements 1.3.
    """
    mock, original = _install_kmnet_mock()
    try:
        driver = _make_driver()
        # Sanity: with mock.init.return_value = 0 the driver MUST land in
        # CONNECTED, otherwise `_dispatch_call` short-circuits and `mock.move`
        # never sees the calls (which would silently make the property
        # vacuously true).
        assert driver.connection_status == ConnectionStatus.CONNECTED

        for x, y in inputs:
            driver.move(x, y)

        # ``send_move`` skips emit when both int components are zero, so
        # ``mock.move.call_args_list`` only contains the *non-skipped*
        # calls. That is fine for conservation: a skipped call contributes
        # ``0 + 0`` to either side of the equation.
        emitted_x = sum(c.args[0] for c in mock.move.call_args_list)
        emitted_y = sum(c.args[1] for c in mock.move.call_args_list)

        # Reference sums computed independently. Hypothesis-generated
        # sequences may include very-small floats whose summation order
        # differs from the driver's accumulator path, so the comparison
        # tolerates ``1e-9`` of float-arithmetic drift.
        expected_x = math.fsum(x for x, _ in inputs)
        expected_y = math.fsum(y for _, y in inputs)

        actual_x = emitted_x + driver.remainder_x
        actual_y = emitted_y + driver.remainder_y

        assert math.isclose(actual_x, expected_x, abs_tol=1e-9), (
            f"x conservation violated: emitted={emitted_x!r} + "
            f"remainder_x={driver.remainder_x!r} = {actual_x!r} "
            f"!= sum(input x) = {expected_x!r} "
            f"(diff={actual_x - expected_x!r}, inputs={inputs!r})"
        )
        assert math.isclose(actual_y, expected_y, abs_tol=1e-9), (
            f"y conservation violated: emitted={emitted_y!r} + "
            f"remainder_y={driver.remainder_y!r} = {actual_y!r} "
            f"!= sum(input y) = {expected_y!r} "
            f"(diff={actual_y - expected_y!r}, inputs={inputs!r})"
        )
    finally:
        kmbox_net_driver.kmNet = original
