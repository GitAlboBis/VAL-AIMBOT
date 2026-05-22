"""
Direct kmbox UDP smoke test — bypasses the framework entirely.

Sends a small move command to the kmbox over UDP. If the mouse on the gaming
PC moves, the wire (Surface -> dongle -> kmbox -> gaming PC) is healthy
and the issue is upstream (hotkeys, AI detection, aim toggle, etc).

Run with:  python tools\\kmbox_smoke_move.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml

from input.kmbox_net_driver import KmBoxNetDriver

cfg_path = REPO_ROOT / "config.yaml"
with cfg_path.open(encoding="utf-8") as fp:
    cfg = yaml.safe_load(fp)

km = cfg["input"]["kmbox_net"]
print(f"Connecting to kmbox at {km['ip']}:{km['port']} (uuid={km['uuid']})...")

driver = KmBoxNetDriver(
    ip=km["ip"],
    port=km["port"],
    uuid=km["uuid"],
    use_encryption=km["use_encryption"],
    target_cps=10,
)

if str(driver.connection_status) != "ConnectionStatus.CONNECTED":
    print(f"[FAIL] Driver not connected: {driver.connection_status}")
    sys.exit(1)

print(f"[OK]  Driver connected: {driver.get_driver_info()}")
print()
print("Sending 10 move commands (50px right, 50px left, alternating)...")
print("Watch the gaming PC's mouse cursor. Each move is 200ms apart.")
print()

try:
    for i in range(10):
        dx = 50 if i % 2 == 0 else -50
        dy = 0
        print(f"  [{i+1}/10] move dx={dx:+4d} dy={dy:+4d}")
        driver.move_relative(dx, dy)
        time.sleep(0.2)
    print()
    print("[OK] 10 moves dispatched. Did the mouse jiggle on the gaming PC?")
finally:
    driver.release()
    print("Driver released.")
