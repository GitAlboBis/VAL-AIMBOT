"""Unit tests for ``DetectionFramework._publish_kmbox_state``.

Implements task 10.6 of the ``kmbox-net-integration`` spec. Validates
Requirements 7.1, 7.2, 7.3:

- Req 7.1 — the GUI reads ``connection_status`` from ``SharedState``
  on every render frame (this test confirms the producer side writes
  the canonical string value).
- Req 7.2 — the GUI reads device IP/port from ``SharedState``.
- Req 7.3 — the GUI reads ``use_encryption`` from ``SharedState``.
- Req 7.10 — when no driver is present, the GUI renders ``"no data"``;
  this test confirms the producer publishes that literal so the GUI
  fallback resolves correctly.

The integration test suite (task 10.7,
``tests/main/test_detection_framework_kmbox.py``) covers end-to-end
wiring with a real ``KmBoxNetDriver`` mock; this file validates the
``_publish_kmbox_state`` method in isolation against a stubbed driver.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _build_framework():
    """Construct a side-effect-free ``DetectionFramework`` for unit tests.

    Mirrors the helper in ``test_post_refactor_regressions.py``:
    construction reads ``config.yaml`` (no I/O beyond that) then we
    short-circuit attributes the publish path does NOT touch.
    """
    # Lazy import so module-level errors elsewhere in ``main`` do not
    # poison this file (matches ``test_post_refactor_regressions``).
    from main import DetectionFramework

    framework = DetectionFramework()
    return framework


@pytest.mark.unit
def test_publish_kmbox_state_with_no_driver_writes_no_data() -> None:
    """Req 7.10 — when ``input_driver is None``, publish ``"no data"``.

    All four ``kmbox_*`` keys must contain the literal ``"no data"``
    string so the GUI's no-data fallback (Req 7.10) renders correctly.
    """
    framework = _build_framework()
    framework.input_driver = None

    framework._publish_kmbox_state()

    assert framework.shared_state.get_state("kmbox_status") == "no data"
    assert framework.shared_state.get_state("kmbox_ip") == "no data"
    assert framework.shared_state.get_state("kmbox_port") == "no data"
    assert framework.shared_state.get_state("kmbox_use_encryption") == "no data"


@pytest.mark.unit
def test_publish_kmbox_state_with_connected_driver_writes_canonical_strings() -> None:
    """Req 7.1, 7.2, 7.3 — publish driver state into the four ``kmbox_*`` keys.

    ``connection_status`` is published as ``.value`` (the canonical
    string the GUI matches against per Req 7.4–7.6). IP, port, and
    encryption flag are forwarded byte-for-byte from the driver.
    """
    from input.kmbox_net_driver import ConnectionStatus

    framework = _build_framework()
    # SimpleNamespace gives us a minimal driver shim — _publish_kmbox_state
    # only reads ``connection_status`` / ``ip`` / ``port`` /
    # ``use_encryption``, so we need not stand up a full driver.
    framework.input_driver = SimpleNamespace(
        connection_status=ConnectionStatus.CONNECTED,
        ip="192.168.2.188",
        port="6234",
        use_encryption=True,
    )

    framework._publish_kmbox_state()

    assert framework.shared_state.get_state("kmbox_status") == "connected"
    assert framework.shared_state.get_state("kmbox_ip") == "192.168.2.188"
    assert framework.shared_state.get_state("kmbox_port") == "6234"
    assert framework.shared_state.get_state("kmbox_use_encryption") is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "status_member, expected_value",
    [
        ("DISCONNECTED", "disconnected"),
        ("CONNECTING", "connecting"),
        ("CONNECTED", "connected"),
        ("RECONNECTING", "reconnecting"),
        ("FAILED", "failed"),
    ],
)
def test_publish_kmbox_state_publishes_status_value_for_every_state(
    status_member: str, expected_value: str
) -> None:
    """Req 7.1 — every ``ConnectionStatus`` member maps to its ``.value``.

    The GUI compares ``kmbox_status`` against the literal strings
    ``"connected"`` / ``"reconnecting"`` / ``"failed"`` (Req 7.4–7.6)
    and falls back to ``"no data"`` for any other value (Req 7.10).
    Publishing ``.value`` (a plain ``str``) instead of the enum object
    keeps the comparison in the GUI hot path cheap and explicit.
    """
    from input.kmbox_net_driver import ConnectionStatus

    framework = _build_framework()
    framework.input_driver = SimpleNamespace(
        connection_status=getattr(ConnectionStatus, status_member),
        ip="10.0.0.1",
        port="6234",
        use_encryption=False,
    )

    framework._publish_kmbox_state()

    assert framework.shared_state.get_state("kmbox_status") == expected_value


@pytest.mark.unit
def test_publish_kmbox_state_does_not_call_driver_methods() -> None:
    """The publish path is a pure read — no method invocations on the driver.

    Req 7.9 says the GUI MUST NOT call ``kmNet.*`` on the render thread.
    The producer side mirrors that contract: ``_publish_kmbox_state``
    only reads attributes; it never calls ``driver._connect()``,
    ``driver.move()``, or any other side-effecting method.
    """
    from input.kmbox_net_driver import ConnectionStatus

    framework = _build_framework()
    driver = MagicMock()
    driver.connection_status = ConnectionStatus.CONNECTED
    driver.ip = "192.168.2.188"
    driver.port = "6234"
    driver.use_encryption = True
    framework.input_driver = driver

    framework._publish_kmbox_state()

    # MagicMock records every call/attribute access. Filter to only
    # attribute *invocations* (e.g. ``driver._connect()``); plain
    # attribute reads do not appear in ``method_calls``.
    assert driver.method_calls == [], (
        f"_publish_kmbox_state must not invoke any driver methods; "
        f"got {driver.method_calls!r}"
    )
