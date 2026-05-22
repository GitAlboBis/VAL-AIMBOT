"""
Example tests — Task 3.4 of spec ``kmbox-net-integration``.

Tests for ``KmBoxNetDriver._connect()`` failure modes invoked from
``__init__``.

The four scenarios exercised here are the four observable outcomes of the
worker-thread + bounded-join pattern documented in design.md §
``_connect() — worker-thread + bounded join``:

  1. ``_ensure_kmnet`` raises (kmNet.pyd absent / import-time error)
     → Req 2.3 / Req 6.4: status FAILED, initialized False, log names "kmNet".
  2. ``kmNet.init(ip, port, uuid)`` returns 0 within 5 s
     → Req 2.6 / Req 6.3: status CONNECTED, initialized True, called once
       with the constructor args byte-equal.
  3. ``kmNet.init`` blocks past the 5 s bound
     → Req 2.4 / Req 2.5 / Req 6.4: status FAILED within ~5.5 s wall time.
  4. (Implicit in #2) the call is bounded by the daemon-worker + queue
     pattern so the failure path never leaks the calling thread.

**Validates: Requirements 2.3, 2.4, 2.5, 2.6, 6.2, 6.3, 6.4**

Implementation notes
--------------------
The module-level ``kmNet`` binding inside ``input.kmbox_net_driver`` is the
single chokepoint the driver reaches for vendor calls. The fixture
``kmnet_mock`` replaces that binding with a ``MagicMock`` whose ``init`` is
configured per test, then restores the original binding on teardown so
tests can run in any order without leaking module state.

Because ``_ensure_kmnet()`` is a no-op when the global is already non-None
(see its source), installing a non-None mock is sufficient to bypass the
real import.
"""

from __future__ import annotations

import logging
import time
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from input import kmbox_net_driver
from input.kmbox_net_driver import ConnectionStatus, KmBoxNetDriver


# ---------------------------------------------------------------------------
# Constants and fixtures
# ---------------------------------------------------------------------------

# Sentinel constructor args reused by every test so the
# ``test_init_called_once_with_args`` assertion can match by value.
_TEST_IP = "192.168.2.188"
_TEST_PORT = "6234"
_TEST_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def kmnet_mock() -> Iterator[MagicMock]:
    """
    Replace ``input.kmbox_net_driver.kmNet`` with a fresh ``MagicMock``.

    The mock's ``init`` is pre-configured to return ``0`` so the default
    scenario for any test consuming the fixture is the success path; tests
    that need a different scenario override ``mock.init.return_value`` or
    ``mock.init.side_effect`` after fixture setup.

    The original binding (typically ``None`` when ``kmNet.pyd`` is absent)
    is captured at setup and restored on teardown so test order does not
    matter.
    """
    original = kmbox_net_driver.kmNet
    mock = MagicMock(name="kmNet")
    mock.init.return_value = 0
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_kmnet_import_failure_logs_module_name(caplog: pytest.LogCaptureFixture) -> None:
    """
    Validates Req 2.3 / Req 6.4.

    When ``_ensure_kmnet`` raises (e.g. the vendor ``kmNet.pyd`` is absent),
    the driver MUST:

      - leave ``initialized`` set to ``False``,
      - set ``connection_status`` to ``FAILED``,
      - emit a log entry whose message names the module that failed
        to import (the literal ``"kmNet"``).
    """
    # Patch the module-level lazy-importer to raise the same exception
    # ``importlib.import_module('kmNet')`` would raise on a system without
    # the vendor binary. ``_connect`` catches ``Exception`` so any subclass
    # works; ``ImportError`` is the realistic shape.
    with patch.object(
        kmbox_net_driver,
        "_ensure_kmnet",
        side_effect=ImportError("No module named 'kmNet'"),
    ):
        with caplog.at_level(logging.ERROR, logger=kmbox_net_driver.__name__):
            driver = _make_driver()

    assert driver.initialized is False, (
        "initialized must be False after import failure (Req 2.3)"
    )
    assert driver.connection_status == ConnectionStatus.FAILED, (
        "connection_status must be FAILED after import failure (Req 6.4)"
    )

    # The error log entry must name the failing module so an operator
    # reading the log can identify ``kmNet`` as the missing dependency.
    combined = " ".join(record.getMessage() for record in caplog.records)
    assert "kmNet" in combined, (
        f"expected log message to name 'kmNet'; got records: {combined!r}"
    )


@pytest.mark.unit
def test_init_called_once_with_args(kmnet_mock: MagicMock) -> None:
    """
    Validates Req 2.4 / Req 6.3.

    ``KmBoxNetDriver.__init__`` MUST invoke ``kmNet.init`` exactly once and
    forward the constructor's ``(ip, port, uuid)`` byte-equal — no
    transformation, no defaulting, no retry. On the success path the driver
    transitions to ``CONNECTED`` with ``initialized`` set to ``True``.
    """
    driver = _make_driver()

    kmnet_mock.init.assert_called_once_with(_TEST_IP, _TEST_PORT, _TEST_UUID)
    assert driver.connection_status == ConnectionStatus.CONNECTED
    assert driver.initialized is True


@pytest.mark.unit
def test_init_5s_timeout(kmnet_mock: MagicMock) -> None:
    """
    Validates Req 2.4 / Req 2.5 / Req 6.4.

    When ``kmNet.init`` blocks past the 5-second bound, the driver MUST
    abandon the call (the worker thread is daemon and orphaned) and
    transition to ``FAILED`` within roughly 5.5 s of construction. The
    test wall-clock-measures the construction call and asserts an upper
    bound of 5.5 s; the lower bound of 4.5 s confirms the failure path
    actually fired the timeout branch and not, say, a synchronous error.
    """
    # The vendor function has no timeout parameter, so we simulate a
    # hung call with a 10 s sleep — well past the 5 s join bound. The
    # driver's worker is daemonized; the sleep continues in the orphaned
    # thread but does not block the test process or pytest's teardown.
    kmnet_mock.init.side_effect = lambda *args, **kwargs: time.sleep(10.0)

    start = time.monotonic()
    driver = _make_driver()
    elapsed = time.monotonic() - start

    assert elapsed < 5.5, (
        f"_connect() took {elapsed:.2f}s, expected < 5.5s "
        "(Req 2.4: 5-second bound on kmNet.init)"
    )
    assert elapsed >= 4.5, (
        f"_connect() took {elapsed:.2f}s, expected >= ~5s; "
        "the timeout branch should not return early"
    )
    assert driver.connection_status == ConnectionStatus.FAILED, (
        "connection_status must be FAILED after init timeout (Req 6.4)"
    )
    assert driver.initialized is False, (
        "initialized must be False after init timeout (Req 2.5)"
    )


@pytest.mark.unit
def test_init_zero_returns_connected(kmnet_mock: MagicMock) -> None:
    """
    Validates Req 2.6 / Req 6.2 / Req 6.3.

    When ``kmNet.init`` returns ``0`` within the 5-second bound, the driver
    MUST set ``connection_status`` to ``CONNECTED`` and ``initialized`` to
    ``True``. The fixture default already returns ``0``; this test makes
    that explicit so the contract is locally readable.
    """
    kmnet_mock.init.return_value = 0  # explicit; default already 0

    driver = _make_driver()

    assert driver.connection_status == ConnectionStatus.CONNECTED, (
        "connection_status must be CONNECTED on init==0 (Req 6.3)"
    )
    assert driver.initialized is True, (
        "initialized must be True on init==0 (Req 2.6)"
    )
