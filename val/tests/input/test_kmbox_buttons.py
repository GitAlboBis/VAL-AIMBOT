"""
Parameterized tests — Task 5.6 of spec ``kmbox-net-integration``.

Tests for the centralized button-identifier dispatch in
``KmBoxNetDriver.click_button``, ``KmBoxNetDriver.mouse_down``, and
``KmBoxNetDriver.mouse_up``.

Three concerns are exercised:

  1. **Accepted identifiers route to the correct ``kmNet`` function and
     emit the correct edge state.** Each public API has its own table of
     accepted identifiers (9 for ``click_button``, 6 each for
     ``mouse_down``/``mouse_up``); every entry is enumerated.

  2. **Rejected identifiers (``None``, ``"x1"``, ``7``, ``99``) are
     dropped without invoking ``kmNet``** — Req 4.7 mandates a single
     point of truth for the rejection path: an identifier that is not a
     key in ``_BUTTON_EDGE`` / ``_BUTTON_HOLD`` MUST be rejected without
     any underlying ``kmNet.*`` call AND a log entry MUST name the
     offending identifier.

  3. **The encryption-routing chokepoint is exercised in plaintext mode**
     (``use_encryption=False``) so the ``kmNet`` mock attributes match
     the ``_PLAINTEXT_FN`` table (``left``/``right``/``middle``) and can
     be inspected directly. The encrypted-routing property is covered by
     Property 1 (Task 4.5); this file's focus is identifier dispatch.

**Validates: Requirements 4.3, 4.3a, 4.7**

Implementation notes
--------------------
The ``kmnet_mock`` fixture replaces the module-level ``kmNet`` binding
inside ``input.kmbox_net_driver`` with a fresh ``MagicMock`` whose
``init`` returns ``0`` (so ``__init__`` admits the driver to
``CONNECTED``). Each accepted-identifier test then resets the relevant
button-method mocks (``left``/``right``/``middle``) before the call so
``call_args_list`` reflects only the call under test, not the
``kmNet.init(...)`` invocation issued by the constructor.

For the press-then-release path (string identifiers in ``click_button``)
the driver calls ``time.sleep(hold_time)`` between the down and up
edges; ``time.sleep`` is patched to a no-op so the parameterized sweep
is fast.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

from input import kmbox_net_driver
from input.kmbox_net_driver import KmBoxNetDriver


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

    The mock pre-configures ``init`` to return ``0`` so the constructor
    admits the driver to ``CONNECTED`` on the success path. Tests that
    inspect call counts on ``left`` / ``right`` / ``middle`` reset those
    specific attribute mocks AFTER construction so the constructor's
    ``kmNet.init(...)`` call does not pollute the assertions.
    """
    original = kmbox_net_driver.kmNet
    mock = MagicMock(name="kmNet")
    mock.init.return_value = 0
    kmbox_net_driver.kmNet = mock
    try:
        yield mock
    finally:
        kmbox_net_driver.kmNet = original


@pytest.fixture
def driver(kmnet_mock: MagicMock) -> Iterator[KmBoxNetDriver]:
    """
    Construct a ``KmBoxNetDriver`` in plaintext mode
    (``use_encryption=False``) so the ``_PLAINTEXT_FN`` table is selected
    by ``_dispatch_call``. This is what makes the parameterized
    assertions readable: ``mock.left``/``right``/``middle`` are the
    attributes the driver actually reaches for, no ``enc_*`` indirection.

    ``time.sleep`` is patched to a no-op for the lifetime of the driver
    so the press-then-release path completes instantly under the
    parameterized sweep.
    """
    with patch.object(kmbox_net_driver.time, "sleep", lambda _s: None):
        d = KmBoxNetDriver(
            ip=_TEST_IP,
            port=_TEST_PORT,
            uuid=_TEST_UUID,
            use_encryption=False,
            target_cps=10.0,
        )
        # Reset the button-method mocks AFTER construction so the
        # constructor's ``kmNet.init(...)`` call is not visible in the
        # assertions on ``call_args_list``. ``init`` itself is left
        # untouched in case a future test wants to verify it.
        kmnet_mock.left.reset_mock()
        kmnet_mock.right.reset_mock()
        kmnet_mock.middle.reset_mock()
        yield d


# ---------------------------------------------------------------------------
# click_button — accepted identifiers
# ---------------------------------------------------------------------------
#
# Press-then-release path: string identifiers issue (1) THEN (0) on the
# matching logical button. The expected ``call_args_list`` is the full
# two-call sequence so order is asserted, not just count.

_CLICK_PRESS_RELEASE_CASES = [
    pytest.param("left",   "left",   id="click_button-left"),
    pytest.param("right",  "right",  id="click_button-right"),
    pytest.param("middle", "middle", id="click_button-middle"),
]

# Single-edge path: DD-compatible integer codes resolve to one logical
# button + one edge state. The expected ``call_args_list`` is the
# single-call sequence.
_CLICK_SINGLE_EDGE_CASES = [
    pytest.param(1,  "left",   1, id="click_button-1-Ldown"),
    pytest.param(2,  "left",   0, id="click_button-2-Lup"),
    pytest.param(4,  "right",  1, id="click_button-4-Rdown"),
    pytest.param(8,  "right",  0, id="click_button-8-Rup"),
    pytest.param(16, "middle", 1, id="click_button-16-Mdown"),
    pytest.param(32, "middle", 0, id="click_button-32-Mup"),
]


@pytest.mark.unit
@pytest.mark.parametrize("button,logical", _CLICK_PRESS_RELEASE_CASES)
def test_click_button_press_release(
    driver: KmBoxNetDriver,
    kmnet_mock: MagicMock,
    button: Any,
    logical: str,
) -> None:
    """
    Validates Req 4.3 — string identifiers route to the matching logical
    button and emit a press-then-release sequence: ``(1)`` followed by
    ``(0)`` on the SAME ``kmNet`` function.

    The non-target button mocks (e.g. ``right`` and ``middle`` for a
    ``"left"`` call) MUST remain untouched — Req 4.3 mandates that ONLY
    the matching function is invoked.
    """
    result = driver.click_button(button)

    assert result is True, f"click_button({button!r}) must return True on success"

    target_fn = getattr(kmnet_mock, logical)
    # Two calls in order: down edge then up edge on the same logical fn.
    assert target_fn.call_args_list == [(((1,)), {}), (((0,)), {})], (
        f"click_button({button!r}) must issue {logical}(1) then {logical}(0); "
        f"got {target_fn.call_args_list!r}"
    )

    # Non-target buttons are untouched (Req 4.3 — ONLY the matching fn).
    for other in ("left", "right", "middle"):
        if other == logical:
            continue
        other_fn = getattr(kmnet_mock, other)
        assert other_fn.call_count == 0, (
            f"click_button({button!r}) must NOT invoke kmNet.{other}; "
            f"got call_args_list={other_fn.call_args_list!r}"
        )


@pytest.mark.unit
@pytest.mark.parametrize("button,logical,state", _CLICK_SINGLE_EDGE_CASES)
def test_click_button_single_edge(
    driver: KmBoxNetDriver,
    kmnet_mock: MagicMock,
    button: Any,
    logical: str,
    state: int,
) -> None:
    """
    Validates Req 4.3 — DD-compatible integer codes resolve to a single
    edge on the matching logical button:

      1  → left(1)    2  → left(0)
      4  → right(1)   8  → right(0)
      16 → middle(1)  32 → middle(0)

    Exactly one ``kmNet.<logical>(state)`` call is emitted; non-target
    buttons remain untouched.
    """
    result = driver.click_button(button)

    assert result is True, f"click_button({button!r}) must return True on success"

    target_fn = getattr(kmnet_mock, logical)
    assert target_fn.call_args_list == [(((state,)), {})], (
        f"click_button({button!r}) must issue exactly one "
        f"{logical}({state}); got {target_fn.call_args_list!r}"
    )

    # Non-target buttons are untouched.
    for other in ("left", "right", "middle"):
        if other == logical:
            continue
        other_fn = getattr(kmnet_mock, other)
        assert other_fn.call_count == 0, (
            f"click_button({button!r}) must NOT invoke kmNet.{other}; "
            f"got call_args_list={other_fn.call_args_list!r}"
        )


# ---------------------------------------------------------------------------
# mouse_down / mouse_up — accepted identifiers
# ---------------------------------------------------------------------------
#
# ``_BUTTON_HOLD`` accepts the three string identifiers AND the
# DD-compatible integer codes ``1=left``, ``2=right``, ``3=middle``.
# ``mouse_down`` MUST emit state ``1``; ``mouse_up`` MUST emit state ``0``.

_HOLD_CASES = [
    pytest.param("left",   "left",   id="hold-left-str"),
    pytest.param("right",  "right",  id="hold-right-str"),
    pytest.param("middle", "middle", id="hold-middle-str"),
    pytest.param(1,        "left",   id="hold-1-left"),
    pytest.param(2,        "right",  id="hold-2-right"),
    pytest.param(3,        "middle", id="hold-3-middle"),
]


@pytest.mark.unit
@pytest.mark.parametrize("button,logical", _HOLD_CASES)
def test_mouse_down_dispatch(
    driver: KmBoxNetDriver,
    kmnet_mock: MagicMock,
    button: Any,
    logical: str,
) -> None:
    """
    Validates Req 4.3a — ``mouse_down`` resolves the identifier through
    ``_BUTTON_HOLD`` and issues exactly one ``kmNet.<logical>(1)`` call.
    """
    result = driver.mouse_down(button)

    assert result is True, f"mouse_down({button!r}) must return True on success"

    target_fn = getattr(kmnet_mock, logical)
    assert target_fn.call_args_list == [(((1,)), {})], (
        f"mouse_down({button!r}) must issue exactly one "
        f"{logical}(1); got {target_fn.call_args_list!r}"
    )

    for other in ("left", "right", "middle"):
        if other == logical:
            continue
        other_fn = getattr(kmnet_mock, other)
        assert other_fn.call_count == 0, (
            f"mouse_down({button!r}) must NOT invoke kmNet.{other}"
        )


@pytest.mark.unit
@pytest.mark.parametrize("button,logical", _HOLD_CASES)
def test_mouse_up_dispatch(
    driver: KmBoxNetDriver,
    kmnet_mock: MagicMock,
    button: Any,
    logical: str,
) -> None:
    """
    Validates Req 4.3a — ``mouse_up`` resolves the identifier through
    ``_BUTTON_HOLD`` and issues exactly one ``kmNet.<logical>(0)`` call.
    """
    result = driver.mouse_up(button)

    assert result is True, f"mouse_up({button!r}) must return True on success"

    target_fn = getattr(kmnet_mock, logical)
    assert target_fn.call_args_list == [(((0,)), {})], (
        f"mouse_up({button!r}) must issue exactly one "
        f"{logical}(0); got {target_fn.call_args_list!r}"
    )

    for other in ("left", "right", "middle"):
        if other == logical:
            continue
        other_fn = getattr(kmnet_mock, other)
        assert other_fn.call_count == 0, (
            f"mouse_up({button!r}) must NOT invoke kmNet.{other}"
        )


# ---------------------------------------------------------------------------
# Rejection path — Req 4.7
# ---------------------------------------------------------------------------
#
# Identifiers that are not keys in the relevant table MUST be rejected:
#
#   - return ``False``,
#   - emit a warning that names the offending identifier (so an operator
#     reading the log can see what was passed), and
#   - issue NO ``kmNet.*`` call at all (no left/right/middle, no
#     enc_left/enc_right/enc_middle).
#
# The four sentinels exercise the four shapes of a non-key argument:
# ``None`` (the absence sentinel), a non-matching string (``"x1"``), an
# integer that falls between accepted edge codes (``7``), and an
# integer well outside the accepted set (``99``).

_REJECTED_IDENTIFIERS = [
    pytest.param(None,  id="rejected-None"),
    pytest.param("x1",  id="rejected-x1"),
    pytest.param(7,     id="rejected-7"),
    pytest.param(99,    id="rejected-99"),
]

# All ``kmNet`` button/edge-attribute names that MUST remain untouched
# on the rejection path. Both plaintext and encrypted variants are
# checked so a future regression that switches dispatch to the encrypted
# table cannot mask a missed rejection.
_BUTTON_KMNET_ATTRS = (
    "left", "right", "middle",
    "enc_left", "enc_right", "enc_middle",
)


def _assert_no_button_calls(kmnet_mock: MagicMock) -> None:
    """Helper — assert no plaintext or encrypted button fn was invoked."""
    for attr in _BUTTON_KMNET_ATTRS:
        fn = getattr(kmnet_mock, attr)
        assert fn.call_count == 0, (
            f"rejection path MUST NOT invoke kmNet.{attr}; "
            f"got call_args_list={fn.call_args_list!r}"
        )


@pytest.mark.unit
@pytest.mark.parametrize("button", _REJECTED_IDENTIFIERS)
def test_click_button_rejects_unknown_identifier(
    driver: KmBoxNetDriver,
    kmnet_mock: MagicMock,
    caplog: pytest.LogCaptureFixture,
    button: Any,
) -> None:
    """
    Validates Req 4.7 — ``click_button`` with an identifier outside
    ``_BUTTON_EDGE`` MUST return ``False``, log the offending identifier,
    and issue no ``kmNet.*`` call.
    """
    with caplog.at_level(logging.WARNING, logger=kmbox_net_driver.__name__):
        result = driver.click_button(button)

    assert result is False, (
        f"click_button({button!r}) must return False on rejection (Req 4.7)"
    )
    _assert_no_button_calls(kmnet_mock)

    # The log message must name the offending identifier per Req 4.7.
    # ``%r`` formatting in the driver gives us ``repr(button)`` so e.g.
    # ``"x1"`` appears as ``'x1'``; we check for ``repr(button)`` to
    # match that contract regardless of the exact format string.
    combined = " ".join(record.getMessage() for record in caplog.records)
    assert repr(button) in combined, (
        f"expected log to name rejected identifier {button!r}; "
        f"got records: {combined!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("button", _REJECTED_IDENTIFIERS)
def test_mouse_down_rejects_unknown_identifier(
    driver: KmBoxNetDriver,
    kmnet_mock: MagicMock,
    caplog: pytest.LogCaptureFixture,
    button: Any,
) -> None:
    """
    Validates Req 4.7 — ``mouse_down`` with an identifier outside
    ``_BUTTON_HOLD`` MUST return ``False``, log the offending identifier,
    and issue no ``kmNet.*`` call.
    """
    with caplog.at_level(logging.WARNING, logger=kmbox_net_driver.__name__):
        result = driver.mouse_down(button)

    assert result is False, (
        f"mouse_down({button!r}) must return False on rejection (Req 4.7)"
    )
    _assert_no_button_calls(kmnet_mock)

    combined = " ".join(record.getMessage() for record in caplog.records)
    assert repr(button) in combined, (
        f"expected log to name rejected identifier {button!r}; "
        f"got records: {combined!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("button", _REJECTED_IDENTIFIERS)
def test_mouse_up_rejects_unknown_identifier(
    driver: KmBoxNetDriver,
    kmnet_mock: MagicMock,
    caplog: pytest.LogCaptureFixture,
    button: Any,
) -> None:
    """
    Validates Req 4.7 — ``mouse_up`` with an identifier outside
    ``_BUTTON_HOLD`` MUST return ``False``, log the offending identifier,
    and issue no ``kmNet.*`` call.
    """
    with caplog.at_level(logging.WARNING, logger=kmbox_net_driver.__name__):
        result = driver.mouse_up(button)

    assert result is False, (
        f"mouse_up({button!r}) must return False on rejection (Req 4.7)"
    )
    _assert_no_button_calls(kmnet_mock)

    combined = " ".join(record.getMessage() for record in caplog.records)
    assert repr(button) in combined, (
        f"expected log to name rejected identifier {button!r}; "
        f"got records: {combined!r}"
    )
