"""Minimal aim assist -- production build (no debug, no logging overhead)."""

import argparse
import ctypes
import math
import queue
import sys
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Silence ONNX Runtime noise completely
try:
    import onnxruntime as _ort
    _ort.set_default_logger_severity(4)  # FATAL only
except Exception:
    pass

import logging
logging.basicConfig(level=logging.INFO)  # Enable info-level logging

import config as cfg
from capture import CaptureCardCapture
from capture.capture_card import CAPTURE_PRESETS
from engines.ai_engine import AIVisionEngine, Detection
from input.kmbox_net_driver import KmBoxNetDriver, ConnectionStatus


# ─── Activation read primitives ───────────────────────────────────────
# Cached Win32 function pointers — avoids per-frame import + attr lookup.
_GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
_GetKeyState = ctypes.windll.user32.GetKeyState

def _key_down(vk_code: int) -> bool:
    """Return True if the given Windows VK is currently held down."""
    return bool(_GetAsyncKeyState(vk_code) & 0x8000)


def _caps_lock_on() -> bool:
    """Return True iff Caps Lock TOGGLE (LED) is currently on."""
    return bool(_GetKeyState(0x14) & 0x0001)


_VK_BY_NAME = {
    "caps_lock": 0x14, "caps lock": 0x14, "capslock": 0x14,
    "shift": 0x10, "lshift": 0xA0, "rshift": 0xA1,
    "ctrl": 0x11, "alt": 0x12,
    "lmb": 0x01, "rmb": 0x02, "mmb": 0x04,
    "xbutton1": 0x05, "xbutton2": 0x06,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f10": 0x79,
}


def _resolve_vk(name: str) -> int:
    """Translate a config string to a VK (panic key + Req 3.6 preservation)."""
    return _VK_BY_NAME.get(name.strip().lower(), 0x14)


# ─── Activation specification (design.md File 3 entries 1-2 / §4.4) ───
ActivationMode = Literal['caps_lock', 'mouse_side1', 'mouse_side2', 'vk', 'none']


@dataclass(frozen=True)
class ActivationSpec:
    mode: ActivationMode
    vk_code: Optional[int]


_NONE_SPEC = ActivationSpec('none', None)


def _resolve_activation(name: Optional[str]) -> ActivationSpec:
    """Tag the config string with one of the four activation modes."""
    if not name:
        return _NONE_SPEC
    n = name.strip().lower()
    if n in ('caps_lock', 'caps lock', 'capslock'):
        return ActivationSpec('caps_lock', 0x14)
    if n in ('mouse_side1', 'side1', 'xbutton1'):
        return ActivationSpec('mouse_side1', None)
    if n in ('mouse_side2', 'side2', 'xbutton2'):
        return ActivationSpec('mouse_side2', None)
    return ActivationSpec('vk', _VK_BY_NAME.get(n, 0x14))


def _is_active(spec: ActivationSpec, driver: KmBoxNetDriver) -> bool:
    """Mode dispatch for the activation read (design.md §4.4)."""
    if spec.mode == 'caps_lock':
        return _caps_lock_on()
    if spec.mode == 'mouse_side1':
        try: return bool(driver.isdown_side1())
        except Exception: return False  # noqa: BLE001, E701
    if spec.mode == 'mouse_side2':
        try: return bool(driver.isdown_side2())
        except Exception: return False  # noqa: BLE001, E701
    if spec.mode == 'vk' and spec.vk_code is not None:
        # Requirement 3.6 preservation: GetAsyncKeyState for non-toggle VKs.
        return _key_down(spec.vk_code)
    return False


# ─── Trig FOV conversion (design.md File 3 entry 3 / §4.5) ────────────
def fov_to_counts(
    dx_px: float, dy_px: float,
    pre_x: float, pre_y: float, Cx: Optional[float],
    legacy_pixel_to_count: float = 0.85,
) -> Tuple[float, float]:
    """Pixel offset → kmbox HID counts (kvmaibox fov() formula).

    Falls back to linear ``(dx_px*legacy, dy_px*legacy)`` when ``Cx``
    is unset (design.md §4.5 legacy fallback).
    """
    if Cx is None or Cx <= 0.0:
        return (dx_px * legacy_pixel_to_count, dy_px * legacy_pixel_to_count)
    dx_pre = dx_px * pre_x
    dy_pre = dy_px * pre_y
    Rx = Cx / (2.0 * math.pi)
    Ry = Cx / (2.0 * math.pi)
    mx = math.atan2(dx_pre, Rx) * Rx
    my = math.atan2(dy_pre, math.sqrt(dx_pre * dx_pre + Rx * Rx)) * Ry
    return (mx, my)



# ─── Module-level selector cache (Requirement 2.2 / §4.1 (b)) ─────────
last_mid_coord: Optional[Tuple[float, float]] = None
last_target_time: float = 0.0


# ─── Mouse Worker Thread (sunone-style non-blocking move) ──────────────
class MouseWorker:
    """Dedicated thread for mouse move dispatch (sunone-style).

    The detection loop puts ``(mx, my)`` into a size-1 queue; the worker
    thread consumes it and calls ``driver.move()`` in the background.
    If a new command arrives before the old one is sent, the old one is
    dropped — only the freshest aim position matters (same semantics as
    ``MouseThread::queueMove`` in sunone_aimbot_2 which caps at 5 and
    pops the oldest).

    This eliminates the ~3-5ms blocking cost of XXTEA encrypt + UDP
    sendto from the main loop, letting it run at full inference speed.
    """

    def __init__(self, driver) -> None:
        self._driver = driver
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="MouseWorker"
        )
        self._thread.start()

    def queue_move(self, mx: float, my: float) -> None:
        """Enqueue a move command (non-blocking, drops stale)."""
        # Drain any stale command before putting the new one.
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait((mx, my))
        except queue.Full:
            pass  # Worker is busy; this frame's command is dropped.

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                mx, my = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                self._driver.move(mx, my)
            except Exception:  # noqa: BLE001
                pass  # Driver errors are already logged internally.

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal aim")
    parser.add_argument("--toggle", action="store_true", help="Legacy no-op.")
    parser.add_argument("--confidence", type=float, default=None,
                        help="Override ai_engine.confidence at runtime.")
    args = parser.parse_args()
    args.silent = False  # Logging enabled
    _ = args.toggle

    # ─── Load config ──────────────────────────────────────────────
    config = cfg.load_config()
    cap_cfg = config.get("capture", {})
    ai_cfg  = config.get("ai_engine", {})
    aim_cfg = config.get("aim", {})
    inp_cfg = config.get("input", {})
    gen_cfg = config.get("general", {})

    # ─── Capture card ─────────────────────────────────────────────
    preset_name = cap_cfg.get("chipset_preset", "ms2130")
    preset = CAPTURE_PRESETS.get(preset_name, CAPTURE_PRESETS["auto"])
    capture = CaptureCardCapture(
        device_index=cap_cfg.get("device_index", 0),
        fourcc=cap_cfg.get("fourcc", preset["fourcc"]),
        width=cap_cfg.get("resolution_width", preset.get("width", 1920)),
        height=cap_cfg.get("resolution_height", preset.get("height", 1080)),
    )
    if not capture.initialize(target_fps=int(cap_cfg.get("fps_cap", 60)), silent=True):
        return 1
    cap_w, cap_h = capture.get_resolution()

    if args.confidence is not None:
        ai_cfg = dict(ai_cfg)
        ai_cfg["confidence"] = float(args.confidence)
    engine = AIVisionEngine(ai_cfg, shared_state=None)
    # Silence native stdout/stderr during model load
    import os as _os
    _devnull = _os.open(_os.devnull, _os.O_WRONLY)
    _saved1, _saved2 = _os.dup(1), _os.dup(2)
    _os.dup2(_devnull, 1); _os.dup2(_devnull, 2)
    try:
        model_loaded = engine.load_model()
    finally:
        _os.dup2(_saved1, 1); _os.dup2(_saved2, 2)
        _os.close(_saved1); _os.close(_saved2); _os.close(_devnull)
    if not model_loaded:
        capture.cleanup()
        return 1

    # ─── Kmbox driver ─────────────────────────────────────────────
    km_cfg = inp_cfg["kmbox_net"]
    driver = KmBoxNetDriver(
        ip=km_cfg["ip"], port=km_cfg["port"], uuid=km_cfg["uuid"],
        use_encryption=km_cfg.get("use_encryption", True),
        target_cps=config.get("rapid_fire", {}).get("target_cps", 10),
    )
    if driver.connection_status is not ConnectionStatus.CONNECTED:
        capture.cleanup(); engine.release()
        return 1

    # ─── Mouse worker thread (sunone-style non-blocking) ──────────
    mouse_worker = MouseWorker(driver)

    # ─── Aim parameters ───────────────────────────────────────────
    cap_size      = int(ai_cfg.get("capture_size", 416))
    headshot_bias = float(ai_cfg.get("headshot_bias", 0.30))
    fov_radius_px = float(aim_cfg.get("fov_radius_px", 200.0))
    cx_raw = aim_cfg.get("cx_counts_per_2pi")
    Cx = float(cx_raw) if cx_raw is not None else None
    pre_x      = float(aim_cfg.get("pre_multiplier_x", 1.0))
    pre_y      = float(aim_cfg.get("pre_multiplier_y", 1.0))
    legacy_p2c = float(aim_cfg.get("legacy_pixel_to_count",
                                   aim_cfg.get("pixel_to_count", 0.85)))
    trace_algo  = int(aim_cfg.get("trace_algorithm", 2))
    trace_delay = int(aim_cfg.get("trace_delay_ms", 80))
    deadzone_px = float(aim_cfg.get("deadzone_px", 2.0))
    lock_radius_px = float(aim_cfg.get("lock_radius_px", 100.0))
    lock_timeout_s = float(aim_cfg.get("lock_timeout_s", 0.50))

    # New tracking parameters (sunone-style)
    ema_alpha          = float(aim_cfg.get("ema_alpha", 0.85))
    disable_prediction = bool(aim_cfg.get("disable_prediction", False))
    prediction_interval = float(aim_cfg.get("prediction_interval", 1.0))
    min_speed_mult     = float(aim_cfg.get("min_speed_multiplier", 0.8))
    max_speed_mult     = float(aim_cfg.get("max_speed_multiplier", 1.5))
    ads_multiplier     = float(aim_cfg.get("ads_multiplier", 1.0))

    activation_spec     = _resolve_activation(gen_cfg.get("activation_key", "caps_lock"))
    activation_spec_alt = _resolve_activation(gen_cfg.get("activation_key_alt"))
    panic_vk            = _resolve_vk(gen_cfg.get("panic_key", "f10"))

    # ─── Startup sequence (design.md File 3 entry 6 / §4.6, §4.7) ─
    # 1) Trace once at startup → every subsequent driver.move(dx, dy)
    #    is rendered as a hardware Bezier (Requirement 2.10).
    try:
        driver.trace(algorithm=trace_algo, delay_ms=trace_delay)
    except Exception:
        pass

    # 2) Monitor channel + side-button mask when mode (b) is selected
    #    (Requirements 2.8, 2.9).
    monitor_modes = {'mouse_side1', 'mouse_side2'}
    if (activation_spec.mode in monitor_modes
            or activation_spec_alt.mode in monitor_modes):
        monitor_port = int(km_cfg.get("monitor_port", 16800))
        try:
            driver.monitor(port=monitor_port)
        except Exception:
            pass
        for spec in (activation_spec, activation_spec_alt):
            try:
                if spec.mode == 'mouse_side1':
                    driver.mask_side1(1)
                elif spec.mode == 'mouse_side2':
                    driver.mask_side2(1)
            except Exception:
                pass

    # ─── Aim state ─────────────────────────────────────────────────
    # The IDLE/BUSY FSM has been removed: with a non-blocking mouse
    # worker thread (sunone-style), every frame can fire a move
    # command without waiting for the previous one to complete.

    global last_mid_coord, last_target_time
    last_mid_coord = None
    last_target_time = 0.0

    # ─── Prediction state (sunone-style kinematic prediction) ──────
    pred_prev_x: float = 0.0
    pred_prev_y: float = 0.0
    pred_prev_time: Optional[float] = None
    pred_prev_vx: float = 0.0
    pred_prev_vy: float = 0.0
    pred_prev_distance: Optional[float] = None
    max_pred_distance = math.sqrt(cap_size**2 + cap_size**2) / 2.0

    # ─── EMA smoothing state ──────────────────────────────────────
    ema_last_mx: float = 0.0
    ema_last_my: float = 0.0

    if not args.silent:
        print("Running.")


    # ─── Hot-path local caching (avoids module/attr lookups per frame) ─
    _hypot = math.hypot
    _atan2 = math.atan2
    _sqrt = math.sqrt
    _perf_counter = time.perf_counter
    _abs = abs
    _min = min
    _max = max
    _INF = float("inf")
    cap_size_half = cap_size / 2.0
    # Pre-compute FOV conversion constants (only valid when Cx is set)
    if Cx is not None and Cx > 0.0:
        _fov_Rx = Cx / (2.0 * math.pi)
        _fov_use_trig = True
    else:
        _fov_Rx = 0.0
        _fov_use_trig = False
    # ─── Debug counters ────────────────────────────────────────────
    _dbg_fps = 0
    _dbg_dets = 0
    _dbg_moves = 0
    _dbg_aim_on = 0
    _dbg_t0 = time.time()

    try:
        while True:
            if _key_down(panic_vk):
                break

            # --- Activation gate
            aim_active = _is_active(activation_spec, driver)
            if activation_spec_alt.mode != 'none':
                aim_active = aim_active or _is_active(activation_spec_alt, driver)

            # --- Fresh frame
            frame = capture.grab_latest(size=cap_size)
            if frame is None:
                time.sleep(0.001)
                continue

            detections: List[Detection] = engine.process_frame(frame) or []
            _dbg_fps += 1
            if detections:
                _dbg_dets += len(detections)
            if aim_active:
                _dbg_aim_on += 1

            # --- Selector with last_mid_coord bias (Req 2.2 / §4.1 (b))
            best: Optional[Detection] = None
            cx = cy = cap_size_half
            now_t = _perf_counter()
            
            # Check if we have a locked target from previous frames that is still valid
            has_lock = (last_mid_coord is not None and (now_t - last_target_time) <= lock_timeout_s)
            
            if not detections:
                if now_t - last_target_time > lock_timeout_s:
                    last_mid_coord = None
                    # Reset prediction & EMA when target is fully lost
                    pred_prev_time = None
                    ema_last_mx = ema_last_my = 0.0
            else:
                if has_lock:
                    # Sticky target lock: closest to last_mid_coord within lock_radius (no FOV check — already locked)
                    best_lock_d = _INF
                    for det in detections:
                        hx = det.x
                        hy = det.y - det.h * headshot_bias
                        dist_last = _hypot(hx - last_mid_coord[0], hy - last_mid_coord[1])
                        if dist_last <= lock_radius_px and dist_last < best_lock_d:
                            best_lock_d = dist_last
                            best = det
                    
                    if best is not None:
                        last_mid_coord = (best.x, best.y - best.h * headshot_bias)
                        last_target_time = now_t
                    else:
                        has_lock = False

                if not has_lock:
                    # Fresh target acquisition: closest to crosshair (cx, cy)
                    best_crosshair_d = _INF
                    for det in detections:
                        hx = det.x
                        hy = det.y - det.h * headshot_bias
                        dist = _hypot(hx - cx, hy - cy)
                        if dist <= fov_radius_px:
                            if dist < best_crosshair_d:
                                best_crosshair_d = dist
                                best = det
                    
                    if best is not None:
                        last_mid_coord = (best.x, best.y - best.h * headshot_bias)
                        last_target_time = now_t
                    else:
                        if now_t - last_target_time > lock_timeout_s:
                            last_mid_coord = None

            # --- Aim dispatch (Requirements 2.6, 2.10–2.13 / §4.1 (c))
            if aim_active and best is not None:
                hx = best.x
                hy = best.y - best.h * headshot_bias

                # ─── Kinematic prediction (sunone-style) ──────────
                if not disable_prediction:
                    current_pred_t = _perf_counter()
                    if pred_prev_time is None:
                        # First target — no prediction yet
                        pred_prev_x, pred_prev_y = hx, hy
                        pred_prev_time = current_pred_t
                        pred_prev_vx = pred_prev_vy = 0.0
                    else:
                        # Detect target switch (jump > 30% of screen)
                        max_jump = cap_size * 0.3
                        if _abs(hx - pred_prev_x) > max_jump or _abs(hy - pred_prev_y) > max_jump:
                            pred_prev_x, pred_prev_y = hx, hy
                            pred_prev_vx = pred_prev_vy = 0.0
                            pred_prev_time = current_pred_t
                            pred_prev_distance = None
                        else:
                            dt = current_pred_t - pred_prev_time
                            if dt < 1e-6:
                                dt = 1e-6
                            vx = (hx - pred_prev_x) / dt
                            vy = (hy - pred_prev_y) / dt
                            ax = (vx - pred_prev_vx) / dt
                            ay = (vy - pred_prev_vy) / dt

                            pred_dt = dt * prediction_interval
                            cur_dist = _hypot(hx - pred_prev_x, hy - pred_prev_y)
                            proximity = _max(0.1, _min(1.0, 1.0 / (cur_dist + 1.0)))

                            speed_corr = 1.0
                            if pred_prev_distance is not None and max_pred_distance > 0:
                                speed_corr = 1.0 + (_abs(cur_dist - pred_prev_distance) / max_pred_distance) * 0.1

                            hx = hx + vx * pred_dt * proximity * speed_corr + 0.5 * ax * (pred_dt ** 2) * proximity * speed_corr
                            hy = hy + vy * pred_dt * proximity * speed_corr + 0.5 * ay * (pred_dt ** 2) * proximity * speed_corr

                            pred_prev_vx, pred_prev_vy = vx, vy
                            pred_prev_distance = cur_dist

                        pred_prev_x, pred_prev_y = best.x, best.y - best.h * headshot_bias
                        pred_prev_time = current_pred_t
                else:
                    # Reset prediction state when disabled
                    pred_prev_time = None

                dx_px = hx - cx
                dy_px = hy - cy

                # ─── Inline FOV conversion (avoid function call overhead) ──
                if _fov_use_trig:
                    dx_pre = dx_px * pre_x
                    dy_pre = dy_px * pre_y
                    mx = _atan2(dx_pre, _fov_Rx) * _fov_Rx
                    my = _atan2(dy_pre, _sqrt(dx_pre * dx_pre + _fov_Rx * _fov_Rx)) * _fov_Rx
                else:
                    mx = dx_px * legacy_p2c
                    my = dy_px * legacy_p2c
                if _hypot(mx, my) < deadzone_px:
                    pass  # Req 2.13: sub-deadzone → no move, no cooldown
                else:
                    # ─── Division smoothing (stateless, no overshoot) ──
                    if ema_alpha < 1.0 and ema_alpha > 0.0:
                        mx *= ema_alpha
                        my *= ema_alpha

                    # ─── Adaptive speed multiplier ─────
                    distance = _hypot(dx_px, dy_px)
                    norm_dist = _min(distance / cap_size_half, 1.0)
                    if norm_dist < 0.05:
                        speed_mult = 1.0  # Near center: precise
                    elif norm_dist < 0.20:
                        speed_mult = max_speed_mult  # Mid range: fast snap
                    else:
                        taper = _min((norm_dist - 0.20) / 0.80, 1.0)
                        speed_mult = max_speed_mult * (1.0 - taper * 0.3)
                    speed_mult = _max(min_speed_mult, _min(max_speed_mult, speed_mult))
                    mx *= speed_mult
                    my *= speed_mult

                    # ─── ADS multiplier (right mouse = scoped) ────
                    if ads_multiplier != 1.0:
                        try:
                            if driver.isdown_right():
                                mx *= ads_multiplier
                                my *= ads_multiplier
                        except Exception:  # noqa: BLE001
                            pass

                    # ─── DIRECT move (bypass MouseWorker for debug) ─
                    driver.move(mx, my)
                    _dbg_moves += 1

            # ─── Debug status print (1 Hz) ─────────────────────────
            if time.time() - _dbg_t0 >= 1.0:
                print(f"\r[fps={_dbg_fps:3d}  dets={_dbg_dets:3d}  aim={'ON ' if aim_active else 'OFF'}  moves={_dbg_moves:3d}  best={'YES' if best else 'NO '}]    ", end="", flush=True)
                _dbg_fps = _dbg_dets = _dbg_moves = _dbg_aim_on = 0
                _dbg_t0 = time.time()

    except KeyboardInterrupt:
        pass
    finally:
        try: mouse_worker.stop()
        except Exception: pass
        try: capture.cleanup()
        except Exception: pass
        try: engine.release()
        except Exception: pass
        try: driver.unmask_all()
        except Exception: pass
        try: driver.release()
        except Exception: pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
