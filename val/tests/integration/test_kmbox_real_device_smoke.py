"""
Real-device smoke test for the KmBox Net Ethernet/UDP driver.

This test exercises the live ``kmbox-net-integration`` happy path against
an actual KmBox Net device on the local network. It is gated behind two
runtime checks so the default ``pytest`` invocation can never fail in
environments that do not have the hardware:

    1. ``pytest.importorskip("kmNet")`` — skips when the vendor ``.pyd``
       binary is not installed in the active Python environment
       (Req 2.4 — driver construction depends on ``kmNet``).
    2. A ``socket.create_connection`` probe against the configured IP
       and port with a 1.0 s timeout — skips when the device is not
       reachable on the network.

Validates: Requirements 2.4, 6.3, 6.10
"""

from __future__ import annotations

import socket
import time

import pytest

# Module-level vendor-binary gate. ``pytest.importorskip`` raises
# ``pytest.skip`` immediately when ``kmNet`` cannot be imported, so the
# rest of this module is not even compiled into a test in environments
# without the vendor ``.pyd`` (Surface Pro / CI / dev laptops).
pytest.importorskip("kmNet")  # noqa: F841 — we only care about the side effect

# Mark every test in this file with the ``integration`` marker so the
# default ``pytest`` invocation (which selects against ``-m "not
# integration"`` patterns elsewhere, or simply leaves integration tests
# out of fast lanes) excludes it. The marker is registered in
# ``pytest.ini`` under ``markers``.
pytestmark = pytest.mark.integration


def _probe_device(ip: str, port: int, timeout: float = 1.0) -> bool:
    """Best-effort reachability probe for the configured device.

    Uses ``socket.create_connection`` with the supplied timeout. Returns
    ``True`` when a TCP connection can be opened to ``(ip, port)``,
    ``False`` on any timeout / refused / network-unreachable / DNS
    error. The probe is intentionally fail-open: any failure causes the
    caller to ``pytest.skip`` rather than ``pytest.fail`` (Req 2.4 —
    "skip if unreachable").
    """
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def test_kmbox_real_device_smoke():
    """End-to-end smoke against a live KmBox Net device.

    Steps:
      1. Load the live ``config.yaml`` to obtain ``input.kmbox_net.*``.
      2. Probe the configured IP/port; skip if unreachable.
      3. Construct ``KmBoxNetDriver`` and assert
         ``connection_status == CONNECTED`` after init (Req 2.4 / 6.3).
      4. Issue a no-op ``driver.move(0, 0)``; assert no exception.
      5. ``driver.release()`` and assert the heartbeat thread terminates
         within 1.0 s (Req 6.10).
    """
    # 1. Load the live configuration. Use ``load_config`` (not a hand-
    # crafted dict) so this test exercises the same code path the rest
    # of the application uses, including ``validate_kmbox_net_config``.
    from config import load_config

    config = load_config()
    kmbox_cfg = config["input"]["kmbox_net"]
    ip: str = kmbox_cfg["ip"]
    port_str: str = kmbox_cfg["port"]
    uuid: str = kmbox_cfg["uuid"]
    use_encryption: bool = kmbox_cfg["use_encryption"]

    # 2. Reachability probe. The configured port is a string per the
    # validator; ``socket.create_connection`` requires an integer.
    if not _probe_device(ip, int(port_str), timeout=1.0):
        pytest.skip(
            f"kmbox device unreachable at {ip}:{port_str} — "
            f"socket.create_connection probe failed within 1.0 s"
        )

    # 3. Construct the driver from live config values. Construction
    # internally invokes ``_connect()`` with a 5 s bounded timeout
    # (Task 3.2 / Req 2.4); on success it transitions
    # ``connection_status`` to ``CONNECTED`` (Req 6.3) and starts the
    # heartbeat thread.
    from input.kmbox_net_driver import ConnectionStatus, KmBoxNetDriver

    driver = KmBoxNetDriver(
        ip=ip,
        port=port_str,
        uuid=uuid,
        use_encryption=use_encryption,
    )

    try:
        assert driver.connection_status is ConnectionStatus.CONNECTED, (
            f"expected CONNECTED after init, got "
            f"{driver.connection_status.value!r}"
        )
        assert driver.initialized is True

        # 4. No-op move: ``(0, 0)`` is a safe round trip — it routes
        # through ``_dispatch_call`` and reaches ``kmNet.[enc_]move``
        # without altering the host cursor in any meaningful way.
        # We only assert that no exception escapes.
        driver.move(0, 0)
    finally:
        # 5. Release and verify the heartbeat thread terminates within
        # the 1.0 s join window mandated by Req 6.10. ``release()``
        # itself performs a 1.0 s join; we add a small post-release
        # observation window to confirm the thread is no longer alive.
        heartbeat = driver._heartbeat_thread
        driver.release()

        if heartbeat is not None:
            # ``release()`` already joined with timeout=1.0; this extra
            # ``join`` is a defensive zero-cost check that the join
            # actually completed. ``is_alive()`` should be False.
            heartbeat.join(timeout=0.05)
            assert not heartbeat.is_alive(), (
                "heartbeat thread did not terminate within 1.0 s of release()"
            )

        # Terminal-state contract from ``release()``.
        assert driver.connection_status is ConnectionStatus.DISCONNECTED
        assert driver.initialized is False
