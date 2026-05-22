"""
Example tests — Task 5.7 of spec ``kmbox-net-integration``.

Tests for ``KmBoxNetDriver.key_press`` ``hold_ms`` validation and the
keydown/keyup dispatch pair on the success path.

Three observable contracts are exercised here, drawn straight from the
acceptance criteria for Req 4.5 and Req 4.8:

  1. **Out-of-range ``hold_ms`` raises and emits no edges.** When
     ``hold_ms`` is outside the inclusive range ``[0, 5000]``, the driver
     MUST raise ``ValueError`` whose message names the rejected
     ``hold_ms`` value (Req 4.8) and MUST NOT invoke any of
     ``kmNet.keydown`` / ``kmNet.keyup`` / ``kmNet.enc_keydown`` /
     ``kmNet.enc_keyup``. Every flavour of out-of-range rejection
     (``-1`` just below the lower bound, ``5001`` just above the upper
     bound, ``1_000_000`` far above the upper bound) takes the same
     branch and is parameterized over a single test.

  2. **Valid ``hold_ms`` issues exactly one keydown + keyup pair.** When
     ``hold_ms`` is in range, the driver MUST emit exactly one keydown
     edge followed by exactly one keyup edge, both routed through the
     plaintext ``kmNet`` functions when ``use_encryption=False``, and
     both carrying the HID code resolved from the supplied VK code
     (Req 4.5). The boundary values ``0`` and ``5000`` are exercised
     alongside the canonical ``100`` so the validator's inclusive bounds
     are locked in.

  3. **Unmapped VK code is a soft reject.** When the VK code has no
     entry in ``_vk_to_hid``, the driver returns ``False`` without
     invoking any ``kmNet`` keydown/keyup function (consistent with the
     prior driver contract). This is the orthogonal failure mode to
     ``hold_ms`` validation and is asserted in a dedicated test so a
     regression in either path surfaces independently.

**Validates: Requirements 4.5, 4.8**

Implementation notes
--------------------
* The fixture pattern mirrors ``tests/input/test_kmbox_connect.py``: the
  module-level ``kmNet`` binding inside ``input.kmbox_net_driver`` is
  swapped for a fresh ``MagicMock`` so every keydown/keyup invocation is
  captured, and the original binding is restored on teardown.

* ``time.sleep`` is patched to a no-op for the duration of every test so
  the ``hold_ms = 5000`` boundary case does not stall the suite for five
  seconds. The patch targets the bound ``time`` reference inside
  ``input.kmbox_net_driver`` so the rest of the process clock is
  unaffected.

* The driver is constructed with ``use_encryption=False`` so the tests
  can assert directly against the plaintext ``kmnet_mock.keydown`` /
  ``kmnet_mock.keyup`` attributes. The "no plaintext call" guarantee
  under encryption is covered by Property 1 (Task 4.5) and is not
  re-asserted here.

* VK ``0x41`` ('A') is the canonical key under test because its HID
  mapping (``4``) is the first entry in ``_vk_to_hid`` and is the
  cheapest to verify.
"""

from __future__ import annotations

from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from input import kmbox_net_driver
from input.kmbox_net_driver import KmBoxNetDriver


# ---------------------------------------------------------------------------
# Constants and fixtures
# ---------------------------------------------------------------------------

# Canonical constructor args reused across tests.
_TEST_IP = "192.168.2.188"
_TEST_PORT = "6234"
_TEST_UUID = "00000000-0000-0000-0000-000000000000"

# VK 0x41 ('A') → HID 4 per the ``_vk_to_hid`` table (letters A–Z map to
# HID 4–29). Picking the first entry keeps the assertion concrete.
_VK_A = 0x41
_HID_A = 4


@pytest.fixture
def kmnet_mock() -> Iterator[MagicMock]:
    """
    Replace ``input.kmbox_net_driver.kmNet`` with a fresh ``MagicMock``.

    The mock's ``init`` is pre-configured to return ``0`` so the driver
    construction always succeeds (status transitions to ``CONNECTED``,
    ``initialized`` becomes ``True``); ``keydown`` / ``keyup`` /
    ``enc_keydown`` / ``enc_keyup`` are auto-attributes on the mock and
    record every invocation through ``call_args_list``.

    The original module-level binding (typically ``None`` when
    ``kmNet.pyd`` is absent) is captured at setup and restored on
    teardown so test order does not matter.
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
def no_sleep() -> Iterator[None]:
    """
    Patch ``time.sleep`` inside ``input.kmbox_net_driver`` to a no-op.

    Without this patch, ``key_press(..., hold_ms=5000)`` would block the
    test for five seconds. Patching the bound ``time`` reference inside
    the driver module leaves the global ``time.sleep`` (and therefore
    pytest's own timing) untouched.
    """
    with patch.object(kmbox_net_driver.time, "sleep", lambda *_a, **_kw: None):
        yield


def _make_driver(use_encryption: bool = False) -> KmBoxNetDriver:
    """
    Construct a ``KmBoxNetDriver`` with the canonical test args.

    Defaults to ``use_encryption=False`` so the plaintext
    ``kmNet.keydown`` / ``kmNet.keyup`` attributes on the mock can be
    inspected directly.
    """
    return KmBoxNetDriver(
        ip=_TEST_IP,
        port=_TEST_PORT,
        uuid=_TEST_UUID,
        use_encryption=use_encryption,
        target_cps=10.0,
    )


def _assert_no_keydown_keyup_calls(mock: MagicMock) -> None:
    """
    Assert no keydown/keyup edge was emitted on either the plaintext or
    the encrypted path.

    Used by the out-of-range and unmapped-VK tests where the driver MUST
    reject the call before ``_dispatch_call`` is reached. The four
    attributes are auto-created lazily by ``MagicMock``; checking
    ``call_count == 0`` is equivalent to asserting the attribute was
    never accessed as a callable, which is what Req 4.8 demands.
    """
    for fn_name in ("keydown", "keyup", "enc_keydown", "enc_keyup"):
        fn = getattr(mock, fn_name)
        assert fn.call_count == 0, (
            f"expected no kmNet.{fn_name} calls; got {fn.call_args_list!r}"
        )


# ---------------------------------------------------------------------------
# Tests — out-of-range hold_ms
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_hold_ms",
    [
        pytest.param(-1, id="just-below-lower-bound"),
        pytest.param(5001, id="just-above-upper-bound"),
        pytest.param(1_000_000, id="far-above-upper-bound"),
    ],
)
def test_key_press_out_of_range_hold_ms_raises_and_emits_no_edges(
    kmnet_mock: MagicMock,
    no_sleep: None,
    bad_hold_ms: int,
) -> None:
    """
    Validates Req 4.8.

    For every ``hold_ms`` value outside the inclusive range ``[0, 5000]``,
    ``key_press`` MUST:

      - raise ``ValueError`` whose message contains the literal phrase
        ``"hold_ms out of range"`` (the implementation formats the
        message as ``f"hold_ms out of range: {hold_ms}"``), and
      - emit zero ``kmNet.keydown`` / ``kmNet.keyup`` /
        ``kmNet.enc_keydown`` / ``kmNet.enc_keyup`` calls.

    The validation gate runs BEFORE the VK→HID resolution and BEFORE any
    ``_dispatch_call`` invocation, so a malformed ``hold_ms`` cannot
    leak a stuck-down key onto the device — the keydown is rejected
    before the keyup would ever need to fire.
    """
    driver = _make_driver()

    with pytest.raises(ValueError, match="hold_ms out of range"):
        driver.key_press(_VK_A, hold_ms=bad_hold_ms)

    _assert_no_keydown_keyup_calls(kmnet_mock)


# ---------------------------------------------------------------------------
# Tests — valid hold_ms
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "hold_ms",
    [
        pytest.param(0, id="lower-bound-zero"),
        pytest.param(100, id="canonical-100ms"),
        pytest.param(5000, id="upper-bound-5000"),
    ],
)
def test_key_press_valid_hold_ms_issues_one_keydown_keyup_pair(
    kmnet_mock: MagicMock,
    no_sleep: None,
    hold_ms: int,
) -> None:
    """
    Validates Req 4.5.

    For every ``hold_ms`` value inside the inclusive range ``[0, 5000]``,
    ``key_press`` MUST:

      - return ``True`` (both edges dispatched without raising),
      - invoke ``kmNet.keydown`` exactly once with the HID code resolved
        from the supplied VK code (here ``HID 4`` for VK ``0x41``),
      - invoke ``kmNet.keyup`` exactly once with the same HID code,
      - emit zero calls on the encrypted path (the driver is constructed
        with ``use_encryption=False`` so the plaintext route is the only
        legal path through ``_dispatch_call``).

    Boundary values ``0`` and ``5000`` lock in the inclusive nature of
    the validator's range check; the canonical ``100`` is the
    representative interior value called out by the task.
    """
    driver = _make_driver(use_encryption=False)

    result = driver.key_press(_VK_A, hold_ms=hold_ms)

    assert result is True, "key_press must return True on the success path"

    kmnet_mock.keydown.assert_called_once_with(_HID_A)
    kmnet_mock.keyup.assert_called_once_with(_HID_A)

    # Encrypted variants must remain untouched when use_encryption=False
    # — this mirrors the Property 1 contract at the unit-test scale.
    assert kmnet_mock.enc_keydown.call_count == 0
    assert kmnet_mock.enc_keyup.call_count == 0


# ---------------------------------------------------------------------------
# Tests — unmapped VK code (orthogonal soft-reject path)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_key_press_unmapped_vk_returns_false_without_kmnet_calls(
    kmnet_mock: MagicMock,
    no_sleep: None,
) -> None:
    """
    Validates the design's "VK→HID miss → soft reject" contract.

    A VK code with no entry in ``_vk_to_hid`` (here ``0xFF``) MUST cause
    ``key_press`` to return ``False`` without invoking any
    keydown/keyup function on either the plaintext or encrypted path.

    This is the orthogonal failure mode to Req 4.8 and is asserted in
    its own test so a regression in either rejection path surfaces
    independently. ``hold_ms = 100`` is an explicitly-valid value, so a
    regression that conflates the two rejection paths (e.g. raising
    ``ValueError`` here instead of returning ``False``) is caught by
    the absence of a ``pytest.raises`` block.
    """
    driver = _make_driver()

    result = driver.key_press(0xFF, hold_ms=100)

    assert result is False, (
        "key_press must return False (not raise) when the VK code has "
        "no HID mapping"
    )
    _assert_no_keydown_keyup_calls(kmnet_mock)
