
import dataclasses                                                      
import enum
import hashlib                                                        
import inspect                                                                  
import ipaddress                                                         
import logging
import os                                          
import queue                                                         
import random                                     
import socket                                                        
import struct                                          
import threading                                                        
import time                                                       

from .base_mouse import BaseMouse

logger = logging.getLogger(__name__)

CMD_CONNECT = 0xAF3C2828

CMD_MOUSE_MOVE = 0xAEDE7345

CMD_MOUSE_LEFT = 0x9823AE8D

CMD_MOUSE_MIDDLE = 0x97A3AE8D

CMD_MOUSE_RIGHT = 0x238D8212

CMD_MOUSE_WHEEL = 0xFFEEAD38

CMD_MOUSE_AUTOMOVE = 0xAEDE7346

CMD_BAZERMOVE = 0xA238455A

CMD_KEYBOARD_ALL = 0x123C2C2F

CMD_REBOOT = 0xAA8855AA

CMD_MONITOR = 0x27388020

CMD_MASK_MOUSE = 0x23234343

CMD_UNMASK_ALL = 0x23344343

CMD_SETCONFIG = 0x1D3D3323

CMD_HEAD_FORMAT = "<IIII"

CMD_HEAD_SIZE = struct.calcsize(CMD_HEAD_FORMAT)

def pack_header(mac: int, rand: int, indexpts: int, cmd: int) -> bytes:

    return struct.pack(
        CMD_HEAD_FORMAT,
        mac & 0xFFFFFFFF,
        rand & 0xFFFFFFFF,
        indexpts & 0xFFFFFFFF,
        cmd & 0xFFFFFFFF,
    )

SOFT_MOUSE_FORMAT = "<iiii10i"

SOFT_MOUSE_SIZE = struct.calcsize(SOFT_MOUSE_FORMAT)

MOUSE_BUTTON_LEFT_BIT: int = 0x01
MOUSE_BUTTON_RIGHT_BIT: int = 0x02
MOUSE_BUTTON_MIDDLE_BIT: int = 0x04

SOFT_KEYBOARD_FORMAT = "<BB10B"

SOFT_KEYBOARD_SIZE = struct.calcsize(SOFT_KEYBOARD_FORMAT)

SOFT_KEYBOARD_KEY_SLOTS: int = 10

HID_MODIFIER_BASE: int = 0xE0
HID_MODIFIER_TOP: int = 0xE7

_VK_TO_HID_TABLE: dict = {

    0x30: 39,                                   
    0x31: 30,                                   
    0x32: 31,                      
    0x33: 32,                      
    0x34: 33,                      
    0x35: 34,                      
    0x36: 35,                      
    0x37: 36,                      
    0x38: 37,                      
    0x39: 38,                      

    0x0D: 40,                                                   
    0x1B: 41,                           
    0x08: 42,                                       
    0x09: 43,                           
    0x20: 44,                           

    0x25: 0x50,                       
    0x26: 0x52,                       
    0x27: 0x4F,                       
    0x28: 0x51,                       

    0x2D: 0x49,                        
    0x2E: 0x4C,                        
    0x24: 0x4A,                        
    0x23: 0x4D,                        
    0x21: 0x4B,                                  
    0x22: 0x4E,                                    

    0x70: 0x3A,         
    0x71: 0x3B,         
    0x72: 0x3C,         
    0x73: 0x3D,         
    0x74: 0x3E,         
    0x75: 0x3F,         
    0x76: 0x40,         
    0x77: 0x41,         
    0x78: 0x42,         
    0x79: 0x43,          
    0x7A: 0x44,          
    0x7B: 0x45,          

    0xA0: 0xE1,                                               
    0xA1: 0xE5,                                                
    0xA2: 0xE0,                                                 
    0xA3: 0xE4,                                                  
    0xA4: 0xE2,                                             
    0xA5: 0xE6,                                              
    0x5B: 0xE3,                                              
    0x5C: 0xE7,                                               
    0x10: 0xE1,                                                 
    0x11: 0xE0,                                                   
    0x12: 0xE2,                                               

    0x14: 0x39,                                     
    0x90: 0x53,                         
    0x91: 0x47,                                       
}

for _vk_letter in range(0x41, 0x5B):
    _VK_TO_HID_TABLE[_vk_letter] = 0x04 + (_vk_letter - 0x41)
del _vk_letter                                  

@dataclasses.dataclass
class KeyboardState:

    ctrl: int = 0
    keys: list = dataclasses.field(
        default_factory=lambda: [0] * SOFT_KEYBOARD_KEY_SLOTS
    )

def keyboard_apply_down(state: KeyboardState, hid: int) -> None:

    if HID_MODIFIER_BASE <= hid <= HID_MODIFIER_TOP:

        state.ctrl = (state.ctrl | (1 << (hid - HID_MODIFIER_BASE))) & 0xFF
        return

    if hid in state.keys:
        return

    for i in range(SOFT_KEYBOARD_KEY_SLOTS):
        if state.keys[i] == 0:
            state.keys[i] = hid
            return

    state.keys[:] = state.keys[1:] + [hid]

def keyboard_apply_up(state: KeyboardState, hid: int) -> None:

    if HID_MODIFIER_BASE <= hid <= HID_MODIFIER_TOP:

        state.ctrl = state.ctrl & (~(1 << (hid - HID_MODIFIER_BASE)) & 0xFF)
        return
    for i in range(SOFT_KEYBOARD_KEY_SLOTS):
        if state.keys[i] == hid:
            state.keys[i] = 0
            return

class PacketBuilder:

    def __init__(self, mac: int) -> None:

        self._mac: int = mac & 0xFFFFFFFF

        self._indexpts: int = 0

        self._rand_source: random.Random = random.Random(os.urandom(8))

        self._softmouse_button: int = 0

        self.mask_flag: int = 0

    def next_indexpts(self) -> int:

        self._indexpts = (self._indexpts + 1) & 0xFFFFFFFF
        return self._indexpts

    def _random_rand(self) -> int:

        return self._rand_source.randrange(0, 1 << 32)

    @staticmethod
    def _pack_soft_mouse(
        button: int,
        x: int,
        y: int,
        wheel: int,
        points: tuple = (),
    ) -> bytes:

        if len(points) > 10:
            raise ValueError(
                "soft_mouse_t.point[10] holds at most 10 entries; "
                f"got {len(points)}"
            )
        padded = list(points) + [0] * (10 - len(points))
        return struct.pack(
            SOFT_MOUSE_FORMAT,
            button,
            x,
            y,
            wheel,
            *padded,
        )

    def build_move(self, indexpts: int, x: int, y: int) -> bytes:

        header = pack_header(
            self._mac, self._random_rand(), indexpts, CMD_MOUSE_MOVE
        )
        payload = self._pack_soft_mouse(self._softmouse_button, x, y, 0)
        return header + payload

    def build_button(
        self, indexpts: int, cmd: int, bit: int, isdown: int
    ) -> bytes:

        if isdown:
            self._softmouse_button = (self._softmouse_button | bit) & 0xFF
        else:
            self._softmouse_button = self._softmouse_button & (~bit & 0xFF)
        header = pack_header(self._mac, self._random_rand(), indexpts, cmd)
        payload = self._pack_soft_mouse(self._softmouse_button, 0, 0, 0)
        return header + payload

    def build_wheel(self, indexpts: int, wheel: int) -> bytes:

        header = pack_header(
            self._mac, self._random_rand(), indexpts, CMD_MOUSE_WHEEL
        )
        payload = self._pack_soft_mouse(
            self._softmouse_button, 0, 0, wheel
        )
        return header + payload

    def build_mouse_all(
        self,
        indexpts: int,
        btn: int,
        x: int,
        y: int,
        wheel: int,
    ) -> bytes:

        self._softmouse_button = btn & 0xFF
        header = pack_header(
            self._mac, self._random_rand(), indexpts, CMD_MOUSE_WHEEL
        )
        payload = self._pack_soft_mouse(
            self._softmouse_button, x, y, wheel
        )
        return header + payload

    def build_move_auto(
        self, indexpts: int, x: int, y: int, ms: int
    ) -> bytes:

        header = pack_header(self._mac, ms, indexpts, CMD_MOUSE_AUTOMOVE)
        payload = self._pack_soft_mouse(self._softmouse_button, x, y, 0)
        return header + payload

    def build_move_beizer(
        self,
        indexpts: int,
        x: int,
        y: int,
        ms: int,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
    ) -> bytes:

        header = pack_header(self._mac, ms, indexpts, CMD_BAZERMOVE)
        payload = self._pack_soft_mouse(
            self._softmouse_button, x, y, 0,
            points=(x1, y1, x2, y2),
        )
        return header + payload

    def build_keyboard(
        self,
        indexpts: int,
        ctrl: int,
        keys,
    ) -> bytes:

        keys_list = list(keys)
        if len(keys_list) != SOFT_KEYBOARD_KEY_SLOTS:
            raise ValueError(
                "soft_keyboard_t.button[10] requires exactly "
                f"{SOFT_KEYBOARD_KEY_SLOTS} HID codes; got {len(keys_list)}"
            )
        header = pack_header(
            self._mac, self._random_rand(), indexpts, CMD_KEYBOARD_ALL
        )

        payload = struct.pack(
            SOFT_KEYBOARD_FORMAT,
            ctrl & 0xFF,
            0,
            *(k & 0xFF for k in keys_list),
        )
        return header + payload

    def build_connect(self, indexpts: int) -> bytes:

        return pack_header(self._mac, 0, indexpts, CMD_CONNECT)

    def build_monitor(self, indexpts: int, port: int) -> bytes:

        if port != 0:
            rand = (port | (0xAA55 << 16)) & 0xFFFFFFFF
        else:
            rand = 0
        return pack_header(self._mac, rand, indexpts, CMD_MONITOR)

    def build_reboot(self, indexpts: int) -> bytes:

        return pack_header(
            self._mac, self._random_rand(), indexpts, CMD_REBOOT
        )

    def build_setconfig(
        self, indexpts: int, ip: str, port: int
    ) -> bytes:

        rand = struct.unpack("<I", socket.inet_aton(ip))[0]
        header = pack_header(self._mac, rand, indexpts, CMD_SETCONFIG)

        payload = bytes(((port >> 8) & 0xFF, port & 0xFF))
        return header + payload

    def build_mask_mouse_left(
        self, indexpts: int, state: int
    ) -> bytes:

        self.mask_flag = (self.mask_flag & ~0x01) | (state & 0x01)
        return pack_header(
            self._mac, self.mask_flag & 0xFFFFFFFF, indexpts, CMD_MASK_MOUSE
        )

    def _build_mask_bit(
        self, indexpts: int, bit_index: int, state: int
    ) -> bytes:

        bit_mask = 1 << bit_index
        if state & 0x01:
            self.mask_flag = self.mask_flag | bit_mask
        else:
            self.mask_flag = self.mask_flag & ~bit_mask
        return pack_header(
            self._mac, self.mask_flag & 0xFFFFFFFF, indexpts, CMD_MASK_MOUSE
        )

    def build_mask_side1(self, indexpts: int, state: int) -> bytes:

        return self._build_mask_bit(indexpts, 3, state)

    def build_mask_side2(self, indexpts: int, state: int) -> bytes:

        return self._build_mask_bit(indexpts, 4, state)

    def build_mask_x(self, indexpts: int, state: int) -> bytes:

        return self._build_mask_bit(indexpts, 5, state)

    def build_mask_y(self, indexpts: int, state: int) -> bytes:

        return self._build_mask_bit(indexpts, 6, state)

    def build_unmask_all(self, indexpts: int) -> bytes:

        self.mask_flag = 0
        return pack_header(self._mac, 0, indexpts, CMD_UNMASK_ALL)

def _xxtea_mx(z: int, y: int, sum_: int, k: list, p: int, e: int) -> int:

    a = ((z >> 5) ^ ((y << 2) & 0xFFFFFFFF)) & 0xFFFFFFFF
    b = ((y >> 3) ^ ((z << 4) & 0xFFFFFFFF)) & 0xFFFFFFFF
    c = (sum_ ^ y) & 0xFFFFFFFF
    d = (k[(p & 3) ^ e] ^ z) & 0xFFFFFFFF
    return (((a + b) & 0xFFFFFFFF) ^ ((c + d) & 0xFFFFFFFF)) & 0xFFFFFFFF

class PacketEncryptor:

    DELTA: int = 0x9E3779B9

    BLOCK_SIZE_BYTES: int = 128
    BLOCK_COUNT: int = 32

    ROUNDS: int = 6

    KEY_SIZE_BYTES: int = 16

    def __init__(self, mac: int) -> None:

        mac &= 0xFFFFFFFF

        self._key = (
            bytes(
                (
                    (mac >> 24) & 0xFF,
                    (mac >> 16) & 0xFF,
                    (mac >> 8) & 0xFF,
                    mac & 0xFF,
                )
            )
            + bytes(self.KEY_SIZE_BYTES - 4)
        )

        self._key_words: list = list(struct.unpack("<4I", self._key))

    @classmethod
    def _normalize(cls, data: bytes) -> bytes:

        if len(data) >= cls.BLOCK_SIZE_BYTES:
            return data[: cls.BLOCK_SIZE_BYTES]
        return data + bytes(cls.BLOCK_SIZE_BYTES - len(data))

    def encrypt(self, plaintext: bytes) -> bytes:

        block = self._normalize(plaintext)

        v = list(struct.unpack("<32I", block))
        k = self._key_words
        n = self.BLOCK_COUNT

        z = v[n - 1]
        sum_ = 0

        for _round in range(self.ROUNDS):
            sum_ = (sum_ + self.DELTA) & 0xFFFFFFFF
            e = (sum_ >> 2) & 3

            for p in range(n - 1):
                y = v[p + 1]
                mx = _xxtea_mx(z, y, sum_, k, p, e)
                v[p] = (v[p] + mx) & 0xFFFFFFFF
                z = v[p]

            y = v[0]
            p = n - 1
            mx = _xxtea_mx(z, y, sum_, k, p, e)
            v[n - 1] = (v[n - 1] + mx) & 0xFFFFFFFF
            z = v[n - 1]
        return struct.pack("<32I", *v)

    def decrypt(self, ciphertext: bytes) -> bytes:

        block = self._normalize(ciphertext)
        v = list(struct.unpack("<32I", block))
        k = self._key_words
        n = self.BLOCK_COUNT

        sum_ = (self.ROUNDS * self.DELTA) & 0xFFFFFFFF
        y = v[0]
        for _round in range(self.ROUNDS):
            e = (sum_ >> 2) & 3

            for p in range(n - 1, 0, -1):
                z = v[p - 1]
                mx = _xxtea_mx(z, y, sum_, k, p, e)
                v[p] = (v[p] - mx) & 0xFFFFFFFF
                y = v[p]

            z = v[n - 1]
            p = 0
            mx = _xxtea_mx(z, y, sum_, k, p, e)
            v[0] = (v[0] - mx) & 0xFFFFFFFF
            y = v[0]
            sum_ = (sum_ - self.DELTA) & 0xFFFFFFFF
        return struct.pack("<32I", *v)

class ConnectionStatus(str, enum.Enum):

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"

class UdpSocket:

    def __init__(self, recv_timeout_s: float = 3.0) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self._sock.settimeout(float(recv_timeout_s))
        self._lock = threading.Lock()
        self._closed = False

    @property
    def lock(self) -> threading.Lock:

        return self._lock

    def sendto(self, payload: bytes, addr: tuple) -> int:

        return self._sock.sendto(payload, addr)

    def recvfrom(self, bufsize: int = 1024) -> tuple:

        return self._sock.recvfrom(bufsize)

    def close(self) -> None:

        if self._closed:
            return
        self._closed = True
        try:
            self._sock.close()
        except OSError:

            pass

    @property
    def closed(self) -> bool:

        return self._closed

def _is_valid_ip(ip: object) -> bool:

    if not isinstance(ip, str):
        return False

    if any(ch.isspace() for ch in ip):
        return False
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    for octet in parts:

        if not octet or not octet.isascii() or not octet.isdigit():
            return False
        try:
            value = int(octet)
        except ValueError:
            return False
        if not 0 <= value <= 255:
            return False
    return True

def _parse_port(port: object) -> int | None:

    if isinstance(port, bool):
        return None
    if isinstance(port, int):
        if 1 <= port <= 65535:
            return port
        return None
    if isinstance(port, str):

        if not port or not port.isascii() or not port.isdigit():
            return None
        try:
            value = int(port)
        except ValueError:
            return None
        if 1 <= value <= 65535:
            return value
        return None
    return None

def _is_valid_uuid(uuid: object) -> bool:

    if not isinstance(uuid, str):
        return False
    return 1 <= len(uuid) <= 64

_MONITOR_MOUSE_FORMAT = "<BBhhh"
_MONITOR_MOUSE_SIZE = struct.calcsize(_MONITOR_MOUSE_FORMAT)

_MONITOR_KEYBOARD_FORMAT = "<BB10B"
_MONITOR_KEYBOARD_SIZE = struct.calcsize(_MONITOR_KEYBOARD_FORMAT)

_MONITOR_SNAPSHOT_SIZE = _MONITOR_MOUSE_SIZE + _MONITOR_KEYBOARD_SIZE

_MONITOR_RECV_TIMEOUT_S: float = 0.25

class _MonitorListener(threading.Thread):

    def __init__(self, port: int, parent_driver: "KmBoxNetDriver") -> None:

        super().__init__(
            name=f"KmBoxNet-MonitorListener-{port}", daemon=True
        )
        self._port: int = int(port)
        self._driver = parent_driver

        self._stop = threading.Event()

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._sock.bind(("0.0.0.0", self._port))
        except OSError:

            try:
                self._sock.close()
            except OSError:
                pass
            raise

        self._sock.settimeout(_MONITOR_RECV_TIMEOUT_S)

    def run(self) -> None:

        while not self._stop.is_set():
            try:
                data, _addr = self._sock.recvfrom(64)
            except socket.timeout:

                continue
            except OSError:

                return
            except Exception as exc:                

                logger.error(
                    "kmbox_net: _MonitorListener.run unexpected "
                    "%s on recvfrom (%s); listener exiting.",
                    type(exc).__name__,
                    exc,
                )
                return

            if len(data) < _MONITOR_SNAPSHOT_SIZE:
                continue

            try:
                _report_id, buttons, _x, _y, _wheel = struct.unpack(
                    _MONITOR_MOUSE_FORMAT,
                    data[:_MONITOR_MOUSE_SIZE],
                )
            except struct.error as exc:

                logger.error(
                    "kmbox_net: _MonitorListener.run failed to "
                    "unpack mouse report (%s); skipping snapshot.",
                    exc,
                )
                continue

            self._driver._mon_left = 1 if buttons & 0x01 else 0
            self._driver._mon_right = 1 if buttons & 0x02 else 0
            self._driver._mon_middle = 1 if buttons & 0x04 else 0

            self._driver._mon_side1 = 1 if buttons & 0x08 else 0
            self._driver._mon_side2 = 1 if buttons & 0x10 else 0

            self._driver._mon_seen = 1

            cb = self._driver._monitor_callback
            if cb is not None:
                now = time.monotonic()
                last_t = self._driver._monitor_last_event_t
                dt_s = 0.0 if last_t is None else max(0.0, now - last_t)
                self._driver._monitor_last_event_t = now
                try:
                    cb(int(buttons), int(_x), int(_y), float(dt_s))
                except Exception as exc:                

                    logger.error(
                        "kmbox_net: _MonitorListener.run "
                        "monitor callback raised %s (%s); "
                        "continuing listen loop.",
                        type(exc).__name__,
                        exc,
                    )

    def stop(self) -> None:

        self._stop.set()
        try:
            self._sock.close()
        except OSError:

            pass

class KmBoxNetDriver(BaseMouse):

    def __init__(
        self,
        ip: str = "192.168.2.188",
        port: str | int = "41990",
        uuid: str = "",
        use_encryption: bool = True,
        target_cps: float = 10.0,
    ) -> None:

        super().__init__(target_cps=target_cps)

        self.ip: str = ip if isinstance(ip, str) else ""

        self.port = port
        self.uuid: str = uuid if isinstance(uuid, str) else ""
        self.use_encryption: bool = bool(use_encryption)
        self.initialized: bool = False
        self.connection_status: ConnectionStatus = ConnectionStatus.DISCONNECTED
        self._released: bool = False

        self._packet_builder: PacketBuilder | None = None
        self._packet_encryptor: PacketEncryptor | None = None
        self.udp_socket: UdpSocket | None = None
        self._send_lock: threading.Lock | None = None

        self._keyboard_state: KeyboardState = KeyboardState()

        self._monitor_listener: "_MonitorListener | None" = None
        self._monitor_enabled: bool = False
        self._mon_left: int = 0
        self._mon_right: int = 0
        self._mon_middle: int = 0

        self._mon_side1: int = 0
        self._mon_side2: int = 0
        self._mon_seen: int = 0

        self._monitor_callback: "Optional[Callable[[int, int, int, float], None]]" = None

        self._monitor_last_event_t: "Optional[float]" = None

        if not _is_valid_ip(ip):
            self.connection_status = ConnectionStatus.FAILED
            logger.error(
                "kmbox_net: KmBoxNetDriver.__init__ rejected invalid "
                "'ip' parameter (expected 4-octet dotted-decimal "
                "string with each octet in [0, 255]); got %r",
                ip,
            )
            return

        parsed_port = _parse_port(port)
        if parsed_port is None:
            self.connection_status = ConnectionStatus.FAILED
            logger.error(
                "kmbox_net: KmBoxNetDriver.__init__ rejected invalid "
                "'port' parameter (expected int or ASCII-decimal "
                "string parsing to int in [1, 65535]); got %r",
                port,
            )
            return

        if not _is_valid_uuid(uuid):
            self.connection_status = ConnectionStatus.FAILED
            logger.error(
                "kmbox_net: KmBoxNetDriver.__init__ rejected invalid "
                "'uuid' parameter (expected non-empty string of "
                "length [1, 64]); got %r",
                uuid,
            )
            return

        self.port = parsed_port

        try:
            mac = int(uuid[:8].ljust(8, "0"), 16)
        except ValueError:
            self.connection_status = ConnectionStatus.FAILED
            logger.error(
                "kmbox_net: KmBoxNetDriver.__init__ rejected 'uuid' "
                "parameter — first 8 characters are not valid "
                "hexadecimal (StrToHex(%r, 4) failed)",
                uuid[:8],
            )
            return

        self.connection_status = ConnectionStatus.CONNECTING

        self._packet_builder = PacketBuilder(mac)
        self._packet_encryptor = PacketEncryptor(mac)

        self.udp_socket = UdpSocket(recv_timeout_s=5.0)
        self._send_lock = self.udp_socket.lock

        indexpts = self._packet_builder.next_indexpts()
        connect_packet = self._packet_builder.build_connect(indexpts)

        try:
            with self._send_lock:
                self.udp_socket.sendto(connect_packet, (self.ip, self.port))
        except OSError as exc:
            self.connection_status = ConnectionStatus.FAILED
            self.initialized = False
            logger.error(
                "kmbox_net: Init_Handshake sendto failed for "
                "%s:%d (errno=%s, %s); driver entering 'failed' state "
                "without retransmission.",
                self.ip,
                self.port,
                getattr(exc, "errno", None),
                exc,
            )
            return

        try:
            reply, _reply_addr = self.udp_socket.recvfrom(1024)
        except socket.timeout:
            self.connection_status = ConnectionStatus.FAILED
            self.initialized = False
            logger.error(
                "kmbox_net: Init_Handshake timeout for %s:%d "
                "(no reply within 5 seconds); driver entering "
                "'failed' state.",
                self.ip,
                self.port,
            )
            return
        except OSError as exc:

            self.connection_status = ConnectionStatus.FAILED
            self.initialized = False
            logger.error(
                "kmbox_net: Init_Handshake recvfrom failed for "
                "%s:%d (errno=%s, %s); driver entering 'failed' "
                "state.",
                self.ip,
                self.port,
                getattr(exc, "errno", None),
                exc,
            )
            return

        if len(reply) < CMD_HEAD_SIZE:
            self.connection_status = ConnectionStatus.FAILED
            self.initialized = False
            logger.error(
                "kmbox_net: Init_Handshake reply too short for "
                "%s:%d (got %d bytes, expected >= %d); driver "
                "entering 'failed' state.",
                self.ip,
                self.port,
                len(reply),
                CMD_HEAD_SIZE,
            )
            return
        r_mac, r_rand, r_idx, r_cmd = struct.unpack(
            CMD_HEAD_FORMAT, reply[:CMD_HEAD_SIZE]
        )

        if r_cmd != CMD_CONNECT:
            logger.warning(
                "kmbox_net: Init_Handshake reply head.cmd echo "
                "mismatch (got 0x%08X, expected 0x%08X); accepting "
                "anyway per upstream NetRxReturnHandle semantics.",
                r_cmd,
                CMD_CONNECT,
            )
        if r_idx != indexpts:
            logger.warning(
                "kmbox_net: Init_Handshake reply head.indexpts echo "
                "mismatch (got %d, expected %d); accepting anyway "
                "per upstream NetRxReturnHandle semantics.",
                r_idx,
                indexpts,
            )

        self.initialized = True
        self.connection_status = ConnectionStatus.CONNECTED

    def release(self) -> None:

        self._released = True

        listener = getattr(self, "_monitor_listener", None)
        if listener is not None:
            try:
                listener.stop()
            except Exception as exc:

                logger.error(
                    "kmbox_net: release() failed to stop monitor "
                    "listener (%s: %s); continuing teardown.",
                    type(exc).__name__,
                    exc,
                )
            try:
                listener.join(1.0)
            except Exception as exc:
                logger.error(
                    "kmbox_net: release() failed to join monitor "
                    "listener (%s: %s); continuing teardown.",
                    type(exc).__name__,
                    exc,
                )

            self._monitor_listener = None

        self._mon_side1 = 0
        self._mon_side2 = 0

        if self.udp_socket is not None:
            self.udp_socket.close()

        self.initialized = False
        self.connection_status = ConnectionStatus.DISCONNECTED

    def send_move(self, x: int, y: int) -> None:

        if not self._is_strict_int(x) or not self._is_strict_int(y):
            return
        if not -32768 <= x <= 32768:
            return
        if not -32768 <= y <= 32768:
            return
        self._move(x, y)

    def send_click(self, delay_before_click: float = 0.0) -> None:

        if isinstance(delay_before_click, bool):
            return
        if not isinstance(delay_before_click, (int, float)):
            return

        if not (0.0 <= float(delay_before_click) <= 5.0):
            return

        try:
            time.sleep(float(delay_before_click))
            self._left(1)
        finally:

            self._left(0)

    def move(self, x: float, y: float) -> None:

        if isinstance(x, bool) or isinstance(y, bool):
            return
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return

        try:
            xf = float(x)
            yf = float(y)
        except (TypeError, ValueError):
            return
        if not (-32768.0 <= xf <= 32768.0):
            return
        if not (-32768.0 <= yf <= 32768.0):
            return

        int_x, int_y = self.calculate_move_amount(xf, yf)
        if int_x != 0 or int_y != 0:
            self.send_move(int_x, int_y)

    _BUTTON_EDGE = {

        "left":   ("left",   "press_release"),
        "right":  ("right",  "press_release"),
        "middle": ("middle", "press_release"),

        1:        ("left",   "down"),
        2:        ("left",   "up"),
        4:        ("right",  "down"),
        8:        ("right",  "up"),
        16:       ("middle", "down"),
        32:       ("middle", "up"),
    }

    _BUTTON_HOLD = {
        "left":   "left",   1: "left",
        "right":  "right",  2: "right",
        "middle": "middle", 3: "middle",
    }

    def move_relative(self, dx: int, dy: int) -> bool:

        try:
            self._move(dx, dy)
        except (ValueError, TypeError) as exc:
            logger.error(
                "kmbox_net: move_relative(%r, %r) rejected: %s",
                dx, dy, exc,
            )
            return False
        return True

    def click_button(self, button: int | str = 1) -> bool:

        resolved = self._BUTTON_EDGE.get(button)
        if resolved is None:
            logger.error(
                "kmbox_net: click_button(%r) rejected: identifier "
                "not in _BUTTON_EDGE",
                button,
            )
            return False
        logical, edge = resolved
        method = getattr(self, "_" + logical)
        try:
            if edge == "press_release":
                method(1)
                method(0)
            elif edge == "down":
                method(1)
            else:

                method(0)
        except (ValueError, TypeError) as exc:
            logger.error(
                "kmbox_net: click_button(%r) rejected: %s",
                button, exc,
            )
            return False
        return True

    def mouse_down(self, button: int | str = 1) -> bool:

        logical = self._BUTTON_HOLD.get(button)
        if logical is None:
            logger.error(
                "kmbox_net: mouse_down(%r) rejected: identifier "
                "not in _BUTTON_HOLD",
                button,
            )
            return False
        method = getattr(self, "_" + logical)
        try:
            method(1)
        except (ValueError, TypeError) as exc:
            logger.error(
                "kmbox_net: mouse_down(%r) rejected: %s",
                button, exc,
            )
            return False
        return True

    def mouse_up(self, button: int | str = 1) -> bool:

        logical = self._BUTTON_HOLD.get(button)
        if logical is None:
            logger.error(
                "kmbox_net: mouse_up(%r) rejected: identifier "
                "not in _BUTTON_HOLD",
                button,
            )
            return False
        method = getattr(self, "_" + logical)
        try:
            method(0)
        except (ValueError, TypeError) as exc:
            logger.error(
                "kmbox_net: mouse_up(%r) rejected: %s",
                button, exc,
            )
            return False
        return True

    def key_press(self, vk_code: int, hold_ms: int = 50) -> bool:

        if not self._is_strict_int(hold_ms) or not 0 <= hold_ms <= 5000:
            logger.error(
                "kmbox_net: key_press rejected: hold_ms out of range: %r",
                hold_ms,
            )
            raise ValueError(f"hold_ms out of range: {hold_ms}")

        if not self._is_strict_int(vk_code):
            logger.error(
                "kmbox_net: key_press rejected: vk_code is not an "
                "int (got %s=%r)",
                type(vk_code).__name__, vk_code,
            )
            return False
        hid_code = self._vk_to_hid(vk_code)
        if hid_code is None:
            logger.error(
                "kmbox_net: key_press rejected: vk_code %r has no "
                "entry in _vk_to_hid table",
                vk_code,
            )
            return False

        self._keydown(hid_code)
        try:
            time.sleep(hold_ms / 1000)
        finally:

            self._keyup(hid_code)
        return True

    def scroll(self, amount: int) -> bool:

        try:
            self._wheel(amount)
        except (ValueError, TypeError) as exc:
            logger.error(
                "kmbox_net: scroll(%r) rejected: %s",
                amount, exc,
            )
            return False
        return True

    def get_driver_info(self) -> dict:

        return {
            "backend": "kmbox-net-udp",
            "ip": self.ip,
            "port": self.port,
            "uuid": self.uuid,
            "use_encryption": self.use_encryption,
            "connection_status": str(self.connection_status),
            "initialized": self.initialized,
        }

    @staticmethod
    def _is_strict_int(value: object) -> bool:

        return isinstance(value, int) and not isinstance(value, bool)

    def _move(self, x: int, y: int) -> None:

        if not self._is_strict_int(x):
            raise TypeError(
                f"_move: 'x' must be int (got {type(x).__name__}={x!r})"
            )
        if not self._is_strict_int(y):
            raise TypeError(
                f"_move: 'y' must be int (got {type(y).__name__}={y!r})"
            )
        if not -32768 <= x <= 32768:
            raise ValueError(
                f"_move: 'x' out of range [-32768, 32768] (got {x!r})"
            )
        if not -32768 <= y <= 32768:
            raise ValueError(
                f"_move: 'y' out of range [-32768, 32768] (got {y!r})"
            )
        self._dispatch_call("move", x, y)

    def _left(self, isdown: int) -> None:

        if not self._is_strict_int(isdown):
            raise TypeError(
                f"_left: 'isdown' must be int (got "
                f"{type(isdown).__name__}={isdown!r})"
            )
        if isdown not in (0, 1):
            raise ValueError(
                f"_left: 'isdown' must be 0 or 1 (got {isdown!r})"
            )
        self._dispatch_call("left", isdown)

    def _right(self, isdown: int) -> None:

        if not self._is_strict_int(isdown):
            raise TypeError(
                f"_right: 'isdown' must be int (got "
                f"{type(isdown).__name__}={isdown!r})"
            )
        if isdown not in (0, 1):
            raise ValueError(
                f"_right: 'isdown' must be 0 or 1 (got {isdown!r})"
            )
        self._dispatch_call("right", isdown)

    def _middle(self, isdown: int) -> None:

        if not self._is_strict_int(isdown):
            raise TypeError(
                f"_middle: 'isdown' must be int (got "
                f"{type(isdown).__name__}={isdown!r})"
            )
        if isdown not in (0, 1):
            raise ValueError(
                f"_middle: 'isdown' must be 0 or 1 (got {isdown!r})"
            )
        self._dispatch_call("middle", isdown)

    def _wheel(self, amount: int) -> None:

        if not self._is_strict_int(amount):
            raise TypeError(
                f"_wheel: 'amount' must be int (got "
                f"{type(amount).__name__}={amount!r})"
            )
        if amount == 0:
            raise ValueError(
                f"_wheel: 'amount' must be non-zero (got {amount!r})"
            )
        if not -128 <= amount <= 128:
            raise ValueError(
                f"_wheel: 'amount' out of range [-128, 128] "
                f"(got {amount!r})"
            )
        self._dispatch_call("wheel", amount)

    def _mouse(self, btn: int, x: int, y: int, wheel: int) -> None:

        if not self._is_strict_int(btn):
            raise TypeError(
                f"_mouse: 'btn' must be int (got "
                f"{type(btn).__name__}={btn!r})"
            )
        if not self._is_strict_int(x):
            raise TypeError(
                f"_mouse: 'x' must be int (got {type(x).__name__}={x!r})"
            )
        if not self._is_strict_int(y):
            raise TypeError(
                f"_mouse: 'y' must be int (got {type(y).__name__}={y!r})"
            )
        if not self._is_strict_int(wheel):
            raise TypeError(
                f"_mouse: 'wheel' must be int (got "
                f"{type(wheel).__name__}={wheel!r})"
            )
        if not 0 <= btn <= 255:
            raise ValueError(
                f"_mouse: 'btn' out of range [0, 255] (got {btn!r})"
            )
        if not -32768 <= x <= 32768:
            raise ValueError(
                f"_mouse: 'x' out of range [-32768, 32768] (got {x!r})"
            )
        if not -32768 <= y <= 32768:
            raise ValueError(
                f"_mouse: 'y' out of range [-32768, 32768] (got {y!r})"
            )
        if not -128 <= wheel <= 128:
            raise ValueError(
                f"_mouse: 'wheel' out of range [-128, 128] "
                f"(got {wheel!r})"
            )
        self._dispatch_call("mouse", btn, x, y, wheel)

    def _move_auto(self, x: int, y: int, ms: int) -> None:

        if not self._is_strict_int(x):
            raise TypeError(
                f"_move_auto: 'x' must be int (got "
                f"{type(x).__name__}={x!r})"
            )
        if not self._is_strict_int(y):
            raise TypeError(
                f"_move_auto: 'y' must be int (got "
                f"{type(y).__name__}={y!r})"
            )
        if not self._is_strict_int(ms):
            raise TypeError(
                f"_move_auto: 'ms' must be int (got "
                f"{type(ms).__name__}={ms!r})"
            )
        if not -32768 <= x <= 32768:
            raise ValueError(
                f"_move_auto: 'x' out of range [-32768, 32768] "
                f"(got {x!r})"
            )
        if not -32768 <= y <= 32768:
            raise ValueError(
                f"_move_auto: 'y' out of range [-32768, 32768] "
                f"(got {y!r})"
            )
        if not 1 <= ms <= 65535:
            raise ValueError(
                f"_move_auto: 'ms' out of range [1, 65535] "
                f"(got {ms!r})"
            )
        self._dispatch_call("move_auto", x, y, ms)

    def _move_beizer(
        self,
        x: int,
        y: int,
        ms: int,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
    ) -> None:

        for name, value in (
            ("x", x),
            ("y", y),
            ("ms", ms),
            ("x1", x1),
            ("y1", y1),
            ("x2", x2),
            ("y2", y2),
        ):
            if not self._is_strict_int(value):
                raise TypeError(
                    f"_move_beizer: {name!r} must be int (got "
                    f"{type(value).__name__}={value!r})"
                )

        for name, value in (
            ("x", x),
            ("y", y),
            ("x1", x1),
            ("y1", y1),
            ("x2", x2),
            ("y2", y2),
        ):
            if not -32768 <= value <= 32768:
                raise ValueError(
                    f"_move_beizer: {name!r} out of range "
                    f"[-32768, 32768] (got {value!r})"
                )
        if not 1 <= ms <= 65535:
            raise ValueError(
                f"_move_beizer: 'ms' out of range [1, 65535] "
                f"(got {ms!r})"
            )
        self._dispatch_call("move_beizer", x, y, ms, x1, y1, x2, y2)

    def _keydown(self, hid_code: int) -> None:

        if not self._is_strict_int(hid_code):
            raise TypeError(
                f"_keydown: 'hid_code' must be int (got "
                f"{type(hid_code).__name__}={hid_code!r})"
            )
        if not 0 <= hid_code <= 255:
            raise ValueError(
                f"_keydown: 'hid_code' out of range [0, 255] "
                f"(got {hid_code!r})"
            )
        keyboard_apply_down(self._keyboard_state, hid_code)

        self._dispatch_call(
            "keyboard",
            self._keyboard_state.ctrl,
            list(self._keyboard_state.keys),
        )

    def _keyup(self, hid_code: int) -> None:

        if not self._is_strict_int(hid_code):
            raise TypeError(
                f"_keyup: 'hid_code' must be int (got "
                f"{type(hid_code).__name__}={hid_code!r})"
            )
        if not 0 <= hid_code <= 255:
            raise ValueError(
                f"_keyup: 'hid_code' out of range [0, 255] "
                f"(got {hid_code!r})"
            )
        keyboard_apply_up(self._keyboard_state, hid_code)
        self._dispatch_call(
            "keyboard",
            self._keyboard_state.ctrl,
            list(self._keyboard_state.keys),
        )

    def monitor(self, port: int) -> None:

        if not self._is_strict_int(port):
            raise TypeError(
                f"monitor: 'port' must be int (got "
                f"{type(port).__name__}={port!r})"
            )

        if port != 0 and not (1024 <= port <= 49151):
            raise ValueError(
                f"monitor: 'port' must be 0 or in [1024, 49151] "
                f"(got {port!r})"
            )

        self._dispatch_call("monitor", port)

        previous = self._monitor_listener
        if previous is not None:
            try:
                previous.stop()
            except Exception as exc:                
                logger.error(
                    "kmbox_net: monitor() failed to stop previous "
                    "listener (%s: %s); continuing.",
                    type(exc).__name__,
                    exc,
                )
            try:

                previous.join(1.0)
            except Exception as exc:                
                logger.error(
                    "kmbox_net: monitor() failed to join previous "
                    "listener (%s: %s); continuing.",
                    type(exc).__name__,
                    exc,
                )
            self._monitor_listener = None

        if port == 0:

            self._monitor_enabled = False
            self._mon_seen = 0
            self._mon_left = 0
            self._mon_right = 0
            self._mon_middle = 0

            self._mon_side1 = 0
            self._mon_side2 = 0
            return

        if (
            getattr(self, "_released", False)
            or self.connection_status != ConnectionStatus.CONNECTED
        ):
            return

        self._mon_seen = 0
        self._mon_left = 0
        self._mon_right = 0
        self._mon_middle = 0

        self._mon_side1 = 0
        self._mon_side2 = 0

        try:
            listener = _MonitorListener(port=port, parent_driver=self)
        except OSError as exc:
            logger.error(
                "kmbox_net: monitor() failed to bind listener on "
                "port %d (errno=%s, %s); Monitor_Channel left "
                "disabled.",
                port,
                getattr(exc, "errno", None),
                exc,
            )
            self._monitor_enabled = False
            return
        self._monitor_listener = listener

        self._monitor_enabled = True
        listener.start()

    def isdown_left(self) -> int:

        if not self._monitor_enabled or self._mon_seen == 0:
            return 0
        return self._mon_left

    def isdown_middle(self) -> int:

        if not self._monitor_enabled or self._mon_seen == 0:
            return 0
        return self._mon_middle

    def isdown_right(self) -> int:

        if not self._monitor_enabled or self._mon_seen == 0:
            return 0
        return self._mon_right

    def isdown_side1(self) -> int:

        if not self._monitor_enabled or self._mon_seen == 0:
            return 0
        return self._mon_side1

    def isdown_side2(self) -> int:

        if not self._monitor_enabled or self._mon_seen == 0:
            return 0
        return self._mon_side2

    def set_monitor_callback(self, fn) -> None:

        if fn is None:
            self._monitor_callback = None
            self._monitor_last_event_t = None
        else:
            self._monitor_last_event_t = None
            self._monitor_callback = fn

    def reboot(self) -> None:

        was_connected = self.connection_status == ConnectionStatus.CONNECTED
        self._dispatch_call("reboot")
        if was_connected:

            self.connection_status = ConnectionStatus.DISCONNECTED
            self.initialized = False

    def setconfig(self, ip: str, port: int) -> None:

        if not isinstance(ip, str):
            raise TypeError(
                f"setconfig: 'ip' must be str (got "
                f"{type(ip).__name__}={ip!r})"
            )
        if not _is_valid_ip(ip):
            raise ValueError(
                f"setconfig: 'ip' must be a 4-octet dotted-decimal "
                f"string with each octet in [0, 255] (got {ip!r})"
            )

        if not self._is_strict_int(port):
            raise TypeError(
                f"setconfig: 'port' must be int (got "
                f"{type(port).__name__}={port!r})"
            )
        if not 1 <= port <= 65535:
            raise ValueError(
                f"setconfig: 'port' out of range [1, 65535] "
                f"(got {port!r})"
            )
        self._dispatch_call("setconfig", ip, port)

    def trace(self, algorithm: int = 2, delay_ms: int = 80) -> None:

        if not self._is_strict_int(algorithm):
            raise TypeError(
                f"trace: 'algorithm' must be int (got "
                f"{type(algorithm).__name__}={algorithm!r})"
            )
        if algorithm not in (0, 1, 2, 3):
            raise ValueError(
                f"trace: 'algorithm' must be in { 0, 1, 2, 3}  "
                f"(got {algorithm!r})"
            )

        self._move_beizer(0, 0, delay_ms, algorithm, 0, 0, 0)

    def mask_mouse_left(self, state: int) -> None:

        if not self._is_strict_int(state):
            raise TypeError(
                f"mask_mouse_left: 'state' must be int (got "
                f"{type(state).__name__}={state!r})"
            )
        if state not in (0, 1):
            raise ValueError(
                f"mask_mouse_left: 'state' must be 0 or 1 "
                f"(got {state!r})"
            )
        self._dispatch_call("mask_mouse_left", state)

    def mask_side1(self, state: int) -> None:

        if not self._is_strict_int(state):
            raise TypeError(
                f"mask_side1: 'state' must be int (got "
                f"{type(state).__name__}={state!r})"
            )
        if state not in (0, 1):
            raise ValueError(
                f"mask_side1: 'state' must be 0 or 1 (got {state!r})"
            )
        self._dispatch_call("mask_side1", state)

    def mask_side2(self, state: int) -> None:

        if not self._is_strict_int(state):
            raise TypeError(
                f"mask_side2: 'state' must be int (got "
                f"{type(state).__name__}={state!r})"
            )
        if state not in (0, 1):
            raise ValueError(
                f"mask_side2: 'state' must be 0 or 1 (got {state!r})"
            )
        self._dispatch_call("mask_side2", state)

    def mask_x(self, state: int) -> None:

        if not self._is_strict_int(state):
            raise TypeError(
                f"mask_x: 'state' must be int (got "
                f"{type(state).__name__}={state!r})"
            )
        if state not in (0, 1):
            raise ValueError(
                f"mask_x: 'state' must be 0 or 1 (got {state!r})"
            )
        self._dispatch_call("mask_x", state)

    def mask_y(self, state: int) -> None:

        if not self._is_strict_int(state):
            raise TypeError(
                f"mask_y: 'state' must be int (got "
                f"{type(state).__name__}={state!r})"
            )
        if state not in (0, 1):
            raise ValueError(
                f"mask_y: 'state' must be 0 or 1 (got {state!r})"
            )
        self._dispatch_call("mask_y", state)

    def unmask_all(self) -> None:

        self._dispatch_call("unmask_all")

    def _dispatch_call(self, cmd_name: str, *args) -> None:

        if getattr(self, "_released", False):
            return None
        if self.connection_status != ConnectionStatus.CONNECTED:
            return None

        builder = self._packet_builder
        indexpts = builder.next_indexpts()

        if cmd_name == "move":
            x, y = args
            payload = builder.build_move(indexpts, x, y)
        elif cmd_name == "left":
            (isdown,) = args

            payload = builder.build_button(
                indexpts, CMD_MOUSE_LEFT, MOUSE_BUTTON_LEFT_BIT, isdown
            )
        elif cmd_name == "right":
            (isdown,) = args

            payload = builder.build_button(
                indexpts, CMD_MOUSE_RIGHT, MOUSE_BUTTON_RIGHT_BIT, isdown
            )
        elif cmd_name == "middle":
            (isdown,) = args

            payload = builder.build_button(
                indexpts, CMD_MOUSE_MIDDLE, MOUSE_BUTTON_MIDDLE_BIT, isdown
            )
        elif cmd_name == "wheel":
            (amount,) = args
            payload = builder.build_wheel(indexpts, amount)
        elif cmd_name == "mouse":
            btn, x, y, wheel = args
            payload = builder.build_mouse_all(indexpts, btn, x, y, wheel)
        elif cmd_name == "move_auto":
            x, y, ms = args
            payload = builder.build_move_auto(indexpts, x, y, ms)
        elif cmd_name == "move_beizer":
            x, y, ms, x1, y1, x2, y2 = args

            payload = builder.build_move_beizer(
                indexpts, x, y, ms, x1, y1, x2, y2
            )
        elif cmd_name == "keyboard":
            ctrl, keys = args
            payload = builder.build_keyboard(indexpts, ctrl, keys)
        elif cmd_name == "monitor":
            (port,) = args
            payload = builder.build_monitor(indexpts, port)
        elif cmd_name == "reboot":
            payload = builder.build_reboot(indexpts)
        elif cmd_name == "setconfig":
            ip, port = args
            payload = builder.build_setconfig(indexpts, ip, port)
        elif cmd_name == "mask_mouse_left":
            (state,) = args
            payload = builder.build_mask_mouse_left(indexpts, state)
        elif cmd_name == "mask_side1":
            (state,) = args
            payload = builder.build_mask_side1(indexpts, state)
        elif cmd_name == "mask_side2":
            (state,) = args
            payload = builder.build_mask_side2(indexpts, state)
        elif cmd_name == "mask_x":
            (state,) = args
            payload = builder.build_mask_x(indexpts, state)
        elif cmd_name == "mask_y":
            (state,) = args
            payload = builder.build_mask_y(indexpts, state)
        elif cmd_name == "unmask_all":
            payload = builder.build_unmask_all(indexpts)
        else:

            raise ValueError(f"unknown command name: {cmd_name!r}")

        if self.use_encryption:
            try:
                payload = self._packet_encryptor.encrypt(payload)
            except Exception as exc:

                logger.error(
                    "kmbox_net: PacketEncryptor.encrypt failed for "
                    "command %r (%s: %s); use_encryption left unchanged, "
                    "no plaintext fallback applied.",
                    cmd_name,
                    type(exc).__name__,
                    exc,
                )
                return None

        try:
            with self._send_lock:
                self.udp_socket.sendto(payload, (self.ip, self.port))
        except OSError as exc:

            logger.error(
                "kmbox_net: UDP sendto failed for command %r "
                "(errno=%s, %s); socket left open, "
                "initialized and connection_status unchanged.",
                cmd_name,
                getattr(exc, "errno", None),
                exc,
            )
            return None

        return None

    @staticmethod
    def _vk_to_hid(vk: int) -> int | None:

        return _VK_TO_HID_TABLE.get(vk)

__all__ = [

    "CMD_HEAD_FORMAT",
    "CMD_HEAD_SIZE",
    "pack_header",
    "CMD_CONNECT",
    "CMD_MOUSE_MOVE",
    "CMD_MOUSE_LEFT",
    "CMD_MOUSE_MIDDLE",
    "CMD_MOUSE_RIGHT",
    "CMD_MOUSE_WHEEL",
    "CMD_MOUSE_AUTOMOVE",
    "CMD_BAZERMOVE",
    "CMD_KEYBOARD_ALL",
    "CMD_REBOOT",
    "CMD_MONITOR",
    "CMD_MASK_MOUSE",
    "CMD_UNMASK_ALL",
    "CMD_SETCONFIG",

    "SOFT_MOUSE_FORMAT",
    "SOFT_MOUSE_SIZE",
    "MOUSE_BUTTON_LEFT_BIT",
    "MOUSE_BUTTON_RIGHT_BIT",
    "MOUSE_BUTTON_MIDDLE_BIT",

    "SOFT_KEYBOARD_FORMAT",
    "SOFT_KEYBOARD_SIZE",
    "SOFT_KEYBOARD_KEY_SLOTS",
    "HID_MODIFIER_BASE",
    "HID_MODIFIER_TOP",
    "KeyboardState",
    "keyboard_apply_down",
    "keyboard_apply_up",

    "PacketBuilder",

    "ConnectionStatus",
    "KmBoxNetDriver",
    "UdpSocket",

    "PacketEncryptor",
]
