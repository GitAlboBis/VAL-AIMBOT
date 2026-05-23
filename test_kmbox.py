import sys
sys.path.insert(0, '.')
import config as cfg
from input.kmbox_net_driver import KmBoxNetDriver

config = cfg.load_config()
km_cfg = config.get("input", {})["kmbox_net"]
print(f"Connecting to {km_cfg['ip']}:{km_cfg['port']} UUID: {km_cfg['uuid']}")
driver = KmBoxNetDriver(ip=km_cfg["ip"], port=km_cfg["port"], uuid=km_cfg["uuid"])
print(f"Status: {driver.connection_status}")
