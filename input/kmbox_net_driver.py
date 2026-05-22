"""KmBox Net driver -- production build for Surface Pro 11 (ARM64).

Pure-Python replacement for the vendor KmNet.pyd (AMD64-only).
Stripped to only the methods used by main_simple.py:
  move, isdown_right/side1/side2, trace, monitor, mask_side1/2,
  unmask_all, release, connection_status.
"""

import enum
import random
import socket
import struct
import threading
import time

from .base_mouse import BaseMouse

# ──────────────────────────────────────────────────────────────────────
# Protocol constants
# ──────────────────────────────────────────────────────────────────────
CMD_CONNECT      = 0xAF3C2828
CMD_MOUSE_MOVE   = 0xAEDE7345
CMD_BAZERMOVE    = 0xA238455A
CMD_MONITOR      = 0x27388020
CMD_MASK_MOUSE   = 0x23234343
CMD_UNMASK_ALL   = 0x23344343

_HEAD_FMT  = "<IIII"
_HEAD_SIZE = struct.calcsize(_HEAD_FMT)

# soft_mouse_t: button(i), x(i), y(i), wheel(i), point[10](10i)
_MOUSE_FMT  = "<iiii10i"
_MOUSE_SIZE = struct.calcsize(_MOUSE_FMT)

# Monitor snapshot
_MON_MOUSE_FMT   = "<BBhhh"
_MON_MOUSE_SIZE  = struct.calcsize(_MON_MOUSE_FMT)
_MON_KB_FMT      = "<BB10B"
_MON_KB_SIZE     = struct.calcsize(_MON_KB_FMT)
_MON_SNAP_SIZE   = _MON_MOUSE_SIZE + _MON_KB_SIZE
_MON_RECV_TIMEOUT = 0.25


# ──────────────────────────────────────────────────────────────────────
# Packet building (inlined, no class overhead)
# ──────────────────────────────────────────────────────────────────────
def _pack_header(mac: int, rand: int, idx: int, cmd: int) -> bytes:
    return struct.pack(_HEAD_FMT,
                       mac & 0xFFFFFFFF, rand & 0xFFFFFFFF,
                       idx & 0xFFFFFFFF, cmd & 0xFFFFFFFF)


def _pack_mouse(btn: int, x: int, y: int, wheel: int,
                points: tuple = (0,0,0,0,0,0,0,0,0,0)) -> bytes:
    return struct.pack(_MOUSE_FMT, btn & 0xFFFFFFFF, x, y, wheel, *points)


# ──────────────────────────────────────────────────────────────────────
# XXTEA encryption (Python fallback + native C accelerator)
# ──────────────────────────────────────────────────────────────────────
def _xxtea_mx(z, y, s, k, p, e):
    a = ((z >> 5) ^ ((y << 2) & 0xFFFFFFFF)) & 0xFFFFFFFF
    b = ((y >> 3) ^ ((z << 4) & 0xFFFFFFFF)) & 0xFFFFFFFF
    c = (s ^ y) & 0xFFFFFFFF
    d = (k[(p & 3) ^ e] ^ z) & 0xFFFFFFFF
    return (((a + b) & 0xFFFFFFFF) ^ ((c + d) & 0xFFFFFFFF)) & 0xFFFFFFFF


class _Encryptor:
    """XXTEA block encryptor for kmbox protocol packets."""

    _DELTA = 0x9E3779B9
    _BLOCK = 128   # bytes
    _N     = 32    # uint32 words
    _ROUNDS = 6

    # Native C accelerator (lazy-loaded once per process)
    _native_encrypt = None
    _native_probed  = False

    def __init__(self, mac: int):
        mac &= 0xFFFFFFFF
        key_bytes = bytes(((mac >> 24) & 0xFF, (mac >> 16) & 0xFF,
                           (mac >>  8) & 0xFF,  mac        & 0xFF)) + b'\x00' * 12
        self._kw = list(struct.unpack("<4I", key_bytes))

        if not _Encryptor._native_probed:
            _Encryptor._native_probed = True
            try:
                from .xxtea_accel import native_xxtea_encrypt
                if native_xxtea_encrypt is not None:
                    _Encryptor._native_encrypt = native_xxtea_encrypt
            except Exception:
                pass

    def encrypt(self, data: bytes) -> bytes:
        # Pad/truncate to 128 bytes
        if len(data) < self._BLOCK:
            data = data + b'\x00' * (self._BLOCK - len(data))
        elif len(data) > self._BLOCK:
            data = data[:self._BLOCK]

        # Fast path: native C
        if _Encryptor._native_encrypt is not None:
            return _Encryptor._native_encrypt(data, self._kw)

        # Fallback: pure Python
        v = list(struct.unpack("<32I", data))
        k = self._kw
        z = v[31]
        s = 0
        for _ in range(self._ROUNDS):
            s = (s + self._DELTA) & 0xFFFFFFFF
            e = (s >> 2) & 3
            for p in range(31):
                y = v[p + 1]
                mx = _xxtea_mx(z, y, s, k, p, e)
                v[p] = (v[p] + mx) & 0xFFFFFFFF
                z = v[p]
            y = v[0]
            mx = _xxtea_mx(z, y, s, k, 31, e)
            v[31] = (v[31] + mx) & 0xFFFFFFFF
            z = v[31]
        return struct.pack("<32I", *v)


# ──────────────────────────────────────────────────────────────────────
# Connection status enum
# ──────────────────────────────────────────────────────────────────────
class ConnectionStatus(str, enum.Enum):
    DISCONNECTED = "disconnected"
    CONNECTING   = "connecting"
    CONNECTED    = "connected"
    FAILED       = "failed"


# ──────────────────────────────────────────────────────────────────────
# Monitor listener thread
# ──────────────────────────────────────────────────────────────────────
class _MonitorListener(threading.Thread):

    def __init__(self, port: int, driver):
        super().__init__(name=f"KmBox-Mon-{port}", daemon=True)
        self._driver = driver
        self._stop_evt = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._sock.bind(("0.0.0.0", port))
        except OSError:
            try: self._sock.close()
            except OSError: pass
            raise
        self._sock.settimeout(_MON_RECV_TIMEOUT)

    def run(self):
        drv = self._driver
        while not self._stop_evt.is_set():
            try:
                data, _ = self._sock.recvfrom(64)
            except socket.timeout:
                continue
            except OSError:
                return

            if len(data) < _MON_SNAP_SIZE:
                continue

            try:
                _, buttons, _, _, _ = struct.unpack(
                    _MON_MOUSE_FMT, data[:_MON_MOUSE_SIZE])
            except struct.error:
                continue

            drv._mon_left   = 1 if buttons & 0x01 else 0
            drv._mon_right  = 1 if buttons & 0x02 else 0
            drv._mon_middle = 1 if buttons & 0x04 else 0
            drv._mon_side1  = 1 if buttons & 0x08 else 0
            drv._mon_side2  = 1 if buttons & 0x10 else 0
            drv._mon_seen   = 1

    def stop(self):
        self._stop_evt.set()
        try: self._sock.close()
        except OSError: pass


# ──────────────────────────────────────────────────────────────────────
# Input validation helpers (startup only)
# ──────────────────────────────────────────────────────────────────────
def _valid_ip(ip):
    if not isinstance(ip, str): return False
    parts = ip.split(".")
    if len(parts) != 4: return False
    for p in parts:
        if not p or not p.isdigit(): return False
        if not 0 <= int(p) <= 255: return False
    return True


def _parse_port(port):
    if isinstance(port, bool): return None
    if isinstance(port, int):  return port if 1 <= port <= 65535 else None
    if isinstance(port, str):
        if not port or not port.isdigit(): return None
        v = int(port)
        return v if 1 <= v <= 65535 else None
    return None


# ──────────────────────────────────────────────────────────────────────
# KmBoxNetDriver — production slim build
# ──────────────────────────────────────────────────────────────────────
class KmBoxNetDriver(BaseMouse):

    def __init__(self, ip="192.168.2.188", port="41990", uuid="",
                 use_encryption=True, target_cps=10.0):
        super().__init__(target_cps=target_cps)

        self.ip = ip if isinstance(ip, str) else ""
        self.uuid = uuid if isinstance(uuid, str) else ""
        self.use_encryption = bool(use_encryption)
        self.initialized = False
        self.connection_status = ConnectionStatus.DISCONNECTED
        self._released = False

        # Monitor state
        self._monitor_listener = None
        self._monitor_enabled  = False
        self._mon_left = self._mon_right = self._mon_middle = 0
        self._mon_side1 = self._mon_side2 = self._mon_seen = 0

        # Validate inputs
        if not _valid_ip(ip):
            self.connection_status = ConnectionStatus.FAILED
            return
        parsed_port = _parse_port(port)
        if parsed_port is None:
            self.connection_status = ConnectionStatus.FAILED
            return
        if not isinstance(uuid, str) or not (1 <= len(uuid) <= 64):
            self.connection_status = ConnectionStatus.FAILED
            return

        self.port = parsed_port

        try:
            mac = int(uuid[:8].ljust(8, "0"), 16)
        except ValueError:
            self.connection_status = ConnectionStatus.FAILED
            return

        self.connection_status = ConnectionStatus.CONNECTING

        # Internal state
        self._mac = mac & 0xFFFFFFFF
        self._indexpts = 0
        self._btn_state = 0
        self._mask_flag = 0
        self._encryptor = _Encryptor(mac) if use_encryption else None
        self._addr = (self.ip, self.port)  # pre-computed tuple

        # UDP socket
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(5.0)
        self._lock = threading.Lock()

        # Handshake
        self._indexpts += 1
        pkt = _pack_header(self._mac, 0, self._indexpts, CMD_CONNECT)
        try:
            with self._lock:
                self._sock.sendto(pkt, self._addr)
        except OSError:
            self.connection_status = ConnectionStatus.FAILED
            return

        try:
            reply, _ = self._sock.recvfrom(1024)
        except (socket.timeout, OSError):
            self.connection_status = ConnectionStatus.FAILED
            return

        if len(reply) < _HEAD_SIZE:
            self.connection_status = ConnectionStatus.FAILED
            return

        self.initialized = True
        self.connection_status = ConnectionStatus.CONNECTED

    # ── Hot-path: move (single inlined function) ──────────────────
    def move(self, x: float, y: float) -> None:
        """Direct move: calculate_move_amount → build → encrypt → sendto."""
        int_x, int_y = self.calculate_move_amount(x, y)
        if int_x == 0 and int_y == 0:
            return
        if self._released:
            return
        self._indexpts += 1
        header = _pack_header(self._mac, random.getrandbits(32),
                              self._indexpts, CMD_MOUSE_MOVE)
        payload = header + _pack_mouse(self._btn_state, int_x, int_y, 0)
        if self._encryptor is not None:
            payload = self._encryptor.encrypt(payload)
        try:
            with self._lock:
                self._sock.sendto(payload, self._addr)
        except OSError:
            pass

    def send_move(self, x: int, y: int) -> None:
        """Compatibility shim — delegates to _send_cmd_move."""
        if self._released:
            return
        self._send_cmd_move(x, y)

    def send_click(self, delay_before_click: float = 0.0) -> None:
        """Left click with optional delay."""
        if not isinstance(delay_before_click, (int, float)):
            return
        if not (0.0 <= float(delay_before_click) <= 5.0):
            return
        try:
            time.sleep(float(delay_before_click))
            self._send_cmd_button(0x01, 1)  # left down
        finally:
            self._send_cmd_button(0x01, 0)  # left up

    # ── Internal send helpers ─────────────────────────────────────
    def _send_raw(self, payload: bytes) -> None:
        """Encrypt and send a raw packet."""
        if self._released or self.connection_status != ConnectionStatus.CONNECTED:
            return
        if self._encryptor is not None:
            payload = self._encryptor.encrypt(payload)
        try:
            with self._lock:
                self._sock.sendto(payload, self._addr)
        except OSError:
            pass

    def _send_cmd_move(self, x: int, y: int) -> None:
        self._indexpts += 1
        header = _pack_header(self._mac, random.getrandbits(32),
                              self._indexpts, CMD_MOUSE_MOVE)
        self._send_raw(header + _pack_mouse(self._btn_state, x, y, 0))

    def _send_cmd_button(self, bit: int, isdown: int) -> None:
        if isdown:
            self._btn_state = (self._btn_state | bit) & 0xFF
        else:
            self._btn_state = self._btn_state & (~bit & 0xFF)
        # Use CMD_MOUSE_LEFT for left, but the button state is in the payload
        cmd = {0x01: 0x9823AE8D, 0x02: 0x238D8212, 0x04: 0x97A3AE8D}.get(bit, 0x9823AE8D)
        self._indexpts += 1
        header = _pack_header(self._mac, random.getrandbits(32),
                              self._indexpts, cmd)
        self._send_raw(header + _pack_mouse(self._btn_state, 0, 0, 0))

    # ── Trace (bezier setup, called once at startup) ──────────────
    def trace(self, algorithm: int = 2, delay_ms: int = 80) -> None:
        """Configure hardware Bezier interpolation on the kmbox."""
        if self._released or self.connection_status != ConnectionStatus.CONNECTED:
            return
        self._indexpts += 1
        header = _pack_header(self._mac, delay_ms,
                              self._indexpts, CMD_BAZERMOVE)
        payload = _pack_mouse(self._btn_state, 0, 0, 0,
                              points=(algorithm, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        self._send_raw(header + payload)

    # ── Monitor channel ───────────────────────────────────────────
    def monitor(self, port: int) -> None:
        """Start the monitor listener for side-button state."""
        if self._released or self.connection_status != ConnectionStatus.CONNECTED:
            return

        # Send monitor command to kmbox
        self._indexpts += 1
        rand = (port | (0xAA55 << 16)) & 0xFFFFFFFF if port != 0 else 0
        self._send_raw(_pack_header(self._mac, rand, self._indexpts, CMD_MONITOR))

        # Stop previous listener
        prev = self._monitor_listener
        if prev is not None:
            try: prev.stop()
            except Exception: pass
            try: prev.join(1.0)
            except Exception: pass
            self._monitor_listener = None

        if port == 0:
            self._monitor_enabled = False
            self._mon_seen = self._mon_left = self._mon_right = 0
            self._mon_middle = self._mon_side1 = self._mon_side2 = 0
            return

        # Reset and start new listener
        self._mon_seen = self._mon_left = self._mon_right = 0
        self._mon_middle = self._mon_side1 = self._mon_side2 = 0

        try:
            listener = _MonitorListener(port=port, driver=self)
        except OSError:
            self._monitor_enabled = False
            return
        self._monitor_listener = listener
        self._monitor_enabled = True
        listener.start()

    # ── Button state reads (hot-path, called at 60fps) ────────────
    def isdown_left(self) -> int:
        if not self._monitor_enabled or not self._mon_seen: return 0
        return self._mon_left

    def isdown_right(self) -> int:
        if not self._monitor_enabled or not self._mon_seen: return 0
        return self._mon_right

    def isdown_middle(self) -> int:
        if not self._monitor_enabled or not self._mon_seen: return 0
        return self._mon_middle

    def isdown_side1(self) -> int:
        if not self._monitor_enabled or not self._mon_seen: return 0
        return self._mon_side1

    def isdown_side2(self) -> int:
        if not self._monitor_enabled or not self._mon_seen: return 0
        return self._mon_side2

    # ── Mask commands (called once at startup) ────────────────────
    def mask_side1(self, state: int) -> None:
        bit = 1 << 3
        if state & 1: self._mask_flag |= bit
        else:         self._mask_flag &= ~bit
        self._indexpts += 1
        self._send_raw(_pack_header(self._mac, self._mask_flag & 0xFFFFFFFF,
                                    self._indexpts, CMD_MASK_MOUSE))

    def mask_side2(self, state: int) -> None:
        bit = 1 << 4
        if state & 1: self._mask_flag |= bit
        else:         self._mask_flag &= ~bit
        self._indexpts += 1
        self._send_raw(_pack_header(self._mac, self._mask_flag & 0xFFFFFFFF,
                                    self._indexpts, CMD_MASK_MOUSE))

    def unmask_all(self) -> None:
        self._mask_flag = 0
        self._indexpts += 1
        self._send_raw(_pack_header(self._mac, 0, self._indexpts, CMD_UNMASK_ALL))

    # ── Lifecycle ─────────────────────────────────────────────────
    def release(self) -> None:
        self._released = True
        listener = self._monitor_listener
        if listener is not None:
            try: listener.stop()
            except Exception: pass
            try: listener.join(1.0)
            except Exception: pass
            self._monitor_listener = None
        self._mon_side1 = self._mon_side2 = 0
        try: self._sock.close()
        except Exception: pass
        self.initialized = False
        self.connection_status = ConnectionStatus.DISCONNECTED
