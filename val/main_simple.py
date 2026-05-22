"""Minimal aim assist — RootKit / kvmaibox style (post-fix).

Implements design.md File 3: hardware-Bezier via startup ``driver.trace``
(2.10), ``last_mid_coord`` selector (2.2), trig FOV with per-axis
pre-multipliers (2.6, 2.11), IDLE/BUSY FSM with release short-circuit
(2.5, 2.12), deadzone gate (2.13), mode-dispatched activation —
caps_lock toggle / mouse-side monitor / GetAsyncKeyState fall-through
(2.7), monitor + mask_side*/unmask_all (2.8, 2.9), alt activation key
(2.15), and ``grab_latest`` (2.3). Preserves: ``aim/pipeline.py`` not
called (3.5); ``GetAsyncKeyState`` for non-toggle VKs (3.6); zero moves
when inactive (3.7).
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Silence the QNN backend's ETW-state-mismatch error spam BEFORE any
# import that may construct an InferenceSession. ONNX Runtime emits
# `[E:onnxruntime: ...] ETW enabled previously, but disabled now ...`
# at ERROR severity once per inference on Windows when the global ETW
# tracing state changed between sessions; the message is purely
# cosmetic (profiling is unaffected) but at 60 fps it floods stdout.
# Severity 3 silences ERROR but keeps FATAL; bump to 4 to silence
# everything ONNX Runtime emits.
try:
    import onnxruntime as _ort
    _ort.set_default_logger_severity(3)
except Exception:  # noqa: BLE001
    pass

import config as cfg
from capture import CaptureCardCapture
from capture.capture_card import CAPTURE_PRESETS
from engines.ai_engine import AIVisionEngine, Detection
from input.kmbox_net_driver import KmBoxNetDriver, ConnectionStatus

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.WARNING,
)
logger = logging.getLogger("aim")


# ─── Activation read primitives ───────────────────────────────────────
# ``_key_down`` is preserved for Requirement 3.6: non-toggle VKs (e.g.
# f5) SHALL still go through ``GetAsyncKeyState(VK) & 0x8000``. The
# ``vk`` arm of ``_is_active`` delegates to it.
def _key_down(vk_code: int) -> bool:
    """Return True if the given Windows VK is currently held down."""
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk_code) & 0x8000)
    except Exception:  # noqa: BLE001
        return False


def _caps_lock_on() -> bool:
    """Return True iff Caps Lock TOGGLE (LED) is currently on.

    Per Microsoft docs, ``GetKeyState`` returns a SHORT where:
      - bit 15 (sign bit) = key currently held DOWN
      - bit 0 (low bit)   = toggle state (LED on for Caps Lock / Num Lock /
                            Scroll Lock)

    The aim-tracking-stabilization spec 2.7(a) requires the *toggle/LED*
    semantic (RootKit style: press once → LED on → aim active until
    pressed again), so we test bit 0 — NOT the sign bit. The earlier
    ``< 0`` check tested the sign bit, which is "currently held",
    producing HOLD-on-press semantics instead of TOGGLE.
    """
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetKeyState(0x14) & 0x0001)
    except Exception:  # noqa: BLE001
        return False


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


from contextlib import contextmanager

@contextmanager
def silence_native_output():
    """Completely silence standard output and standard error at the OS file descriptor level."""
    import os
    import sys
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
    except Exception:
        yield
        return
    try:
        saved_stdout_fd = os.dup(1)
        saved_stderr_fd = os.dup(2)
    except Exception:
        os.close(devnull)
        yield
        return
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')
        yield
    finally:
        try:
            sys.stdout.close()
            sys.stderr.close()
        except Exception:
            pass
        sys.stdout = orig_stdout
        sys.stderr = orig_stderr
        os.dup2(saved_stdout_fd, 1)
        os.dup2(saved_stderr_fd, 2)
        os.close(saved_stdout_fd)
        os.close(saved_stderr_fd)
        os.close(devnull)


# ─── Module-level selector cache (Requirement 2.2 / §4.1 (b)) ─────────
last_mid_coord: Optional[Tuple[float, float]] = None
last_target_time: float = 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal aim — RootKit style")
    # --toggle preserved as a no-op for non-toggle VKs (3.6); for
    # caps_lock it is superseded by mode (a) GetKeyState_toggle.
    parser.add_argument("--toggle", action="store_true",
                        help="Legacy no-op (superseded by mode (a) for caps_lock).")
    parser.add_argument("--debug-frame", action="store_true",
                        help="Save one captured frame per second to "
                             "debug_frame.jpg (for verifying the AI is "
                             "receiving real pixels). Off by default.")
    parser.add_argument("--confidence", type=float, default=None,
                        help="Override ai_engine.confidence at runtime "
                             "(e.g. 0.15 to verify the model sees anything; "
                             "raises detection count when the configured "
                             "threshold is too high). Off by default.")
    parser.add_argument("--debug-classes", action="store_true",
                        help="Print, once per second, the raw class_id "
                             "histogram BEFORE the target_classes filter. "
                             "Useful when dets=0 but the bot is visible in "
                             "debug_frame.jpg (the model may be predicting "
                             "the wrong class_id).")
    parser.add_argument("--silent", action="store_true",
                        help="Disable all runtime console logging and status bar updates (default behavior).")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable runtime console logging, connection banners, and status bar updates.")
    args = parser.parse_args()
    _ = args.toggle  # toggle is a no-op now

    # Default to silent mode unless --verbose is explicitly requested.
    if not args.verbose:
        args.silent = True

    if args.silent:
        logging.getLogger().setLevel(logging.ERROR)
        logging.getLogger("aim").setLevel(logging.ERROR)
        config_logger = logging.getLogger("config.aim")
        config_logger.setLevel(logging.ERROR)
        config_logger.addHandler(logging.NullHandler())
        try:
            import onnxruntime as _ort
            _ort.set_default_logger_severity(4)
        except Exception:
            pass
    else:
        logging.getLogger().setLevel(logging.WARNING)
        logging.getLogger("aim").setLevel(logging.WARNING)
        try:
            import onnxruntime as _ort
            _ort.set_default_logger_severity(3)
        except Exception:
            pass

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
    if not capture.initialize(target_fps=int(cap_cfg.get("fps_cap", 60)), silent=args.silent):
        logger.error("Capture card init failed; check device/cable/EDID")
        return 1
    cap_w, cap_h = capture.get_resolution()
    if not args.silent:
        print(f"[OK] Capture: {cap_w}x{cap_h}")

    # ─── AI engine (preserved QNN cascade) ────────────────────────
    # Optional --confidence override for debugging "dets=0" stalls.
    if args.confidence is not None:
        ai_cfg = dict(ai_cfg)  # copy so we don't mutate the loaded config
        ai_cfg["confidence"] = float(args.confidence)
        if not args.silent:
            print(f"[DBG] confidence override → {ai_cfg['confidence']}")
    engine = AIVisionEngine(ai_cfg, shared_state=None)
    if args.silent:
        with silence_native_output():
            model_loaded = engine.load_model()
    else:
        model_loaded = engine.load_model()

    if not model_loaded:
        logger.error("AI engine load_model failed")
        capture.cleanup()
        return 1
    if not args.silent:
        print(f"[OK] AI engine: backend={engine.backend_name}")

    # ─── Kmbox driver ─────────────────────────────────────────────
    km_cfg = inp_cfg["kmbox_net"]
    driver = KmBoxNetDriver(
        ip=km_cfg["ip"], port=km_cfg["port"], uuid=km_cfg["uuid"],
        use_encryption=km_cfg.get("use_encryption", True),
        target_cps=config.get("rapid_fire", {}).get("target_cps", 10),
    )
    if driver.connection_status is not ConnectionStatus.CONNECTED:
        logger.error("Kmbox not connected: %s", driver.connection_status)
        capture.cleanup(); engine.release()
        return 1
    if not args.silent:
        print(f"[OK] Kmbox: {driver.ip}:{driver.port}")

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
    cooldown_ms = int(aim_cfg.get("cooldown_ms", 100))
    deadzone_px = float(aim_cfg.get("deadzone_px", 2.0))
    mask_xy     = bool(aim_cfg.get("mask_xy_during_aim", False))
    lock_radius_px = float(aim_cfg.get("lock_radius_px", 70.0))
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

    if not args.silent:
        print("─" * 50)
        print(f"  ACTIVATION : {gen_cfg.get('activation_key','caps_lock')} ({activation_spec.mode})")
        if activation_spec_alt.mode != 'none':
            print(f"  ALT KEY    : {gen_cfg.get('activation_key_alt')} ({activation_spec_alt.mode})")
        print(f"  PANIC      : {gen_cfg.get('panic_key','f10')}")
        print(f"  FOV/Cx/pre : {fov_radius_px}px / "
              f"{Cx if Cx is not None else f'legacy={legacy_p2c}'} / ({pre_x},{pre_y})")
        print(f"  trace      : algorithm={trace_algo}, delay={trace_delay}ms, "
              f"cooldown={cooldown_ms}ms, deadzone={deadzone_px}px")
        print(f"  EMA alpha  : {ema_alpha}  prediction={'OFF' if disable_prediction else f'ON (interval={prediction_interval})'}")
        print(f"  speed mult : [{min_speed_mult}, {max_speed_mult}]")
        print(f"  lock/time  : radius={lock_radius_px}px, timeout={lock_timeout_s}s")
        print("─" * 50)

    # ─── Startup sequence (design.md File 3 entry 6 / §4.6, §4.7) ─
    # 1) Trace once at startup → every subsequent driver.move(dx, dy)
    #    is rendered as a hardware Bezier (Requirement 2.10).
    try:
        driver.trace(algorithm=trace_algo, delay_ms=trace_delay)
        if not args.silent:
            print(f"[OK] driver.trace({trace_algo}, {trace_delay})")
    except Exception as e:  # noqa: BLE001
        logger.warning("driver.trace(%d, %d): %s", trace_algo, trace_delay, e)

    # 2) Monitor channel + side-button mask when mode (b) is selected
    #    (Requirements 2.8, 2.9).
    monitor_modes = {'mouse_side1', 'mouse_side2'}
    if (activation_spec.mode in monitor_modes
            or activation_spec_alt.mode in monitor_modes):
        monitor_port = int(km_cfg.get("monitor_port", 16800))
        try:
            driver.monitor(port=monitor_port)
            if not args.silent:
                print(f"[OK] driver.monitor({monitor_port})")
        except Exception as e:  # noqa: BLE001
            logger.warning("driver.monitor(%d): %s", monitor_port, e)
        for spec in (activation_spec, activation_spec_alt):
            try:
                if spec.mode == 'mouse_side1':
                    driver.mask_side1(1)
                    if not args.silent:
                        print("[OK] driver.mask_side1(1)")
                elif spec.mode == 'mouse_side2':
                    driver.mask_side2(1)
                    if not args.silent:
                        print("[OK] driver.mask_side2(1)")
            except Exception as e:  # noqa: BLE001
                logger.warning("driver.mask_side*(1): %s", e)

    # ─── Cooldown FSM (Requirements 2.5 + 2.12) ───────────────────
    # IDLE/BUSY two-state machine, three transitions:
    #   (IDLE, held + detected + mag ≥ deadzone) → fire and BUSY
    #   (BUSY, held + (now - last_aim_t)*1000 ≥ cooldown_ms) → IDLE
    #   (BUSY, released) → IDLE   (release short-circuit, D12 fix)
    state: Literal['IDLE', 'BUSY'] = 'IDLE'
    last_aim_t: float = 0.0

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
        print("Running. Hold/toggle activation key to aim. Press F10 to quit.")
    fps_count, fps_t0 = 0, time.time()
    # --debug-classes: histogram of raw class_ids returned by the QNN
    # provider BEFORE the target_classes filter. Lets the operator see
    # whether the model is predicting class 1 (ally) when it should
    # predict class 0 (enemy) — a common cause of dets=0 with a visible
    # bot in debug_frame.jpg.
    raw_class_hist: dict = {}
    try:
        while True:
            if _key_down(panic_vk):
                if not args.silent:
                    print("\n[PANIC] F10 pressed; shutting down")
                break

            # --- Activation gate (Requirements 2.7, 2.15)
            aim_active = _is_active(activation_spec, driver)
            if activation_spec_alt.mode != 'none':
                aim_active = aim_active or _is_active(activation_spec_alt, driver)

            # FSM release short-circuit: (BUSY, released) → IDLE.
            if state == 'BUSY' and not aim_active:
                state = 'IDLE'
                if mask_xy:
                    try: driver.mask_x(0); driver.mask_y(0)
                    except Exception: pass  # noqa: BLE001, E701

            # --- Fresh frame (Requirement 2.3 / §4.3)
            frame = capture.grab_latest(size=cap_size)
            if frame is None:
                time.sleep(0.001)
                continue

            detections: List[Detection] = engine.process_frame(frame) or []

            # --debug-classes: peek at the raw output
            # (BEFORE the target_classes filter).
            # Cheap because we only build the histogram from the cached inference.
            if args.debug_classes:
                try:
                    for d in getattr(engine, "last_raw_detections", []):
                        cid = int(d.get("class_id", -1))
                        raw_class_hist[cid] = raw_class_hist.get(cid, 0) + 1
                except Exception:  # noqa: BLE001
                    pass

            # --- Selector with last_mid_coord bias (Req 2.2 / §4.1 (b))
            best: Optional[Detection] = None
            cx = cy = cap_size / 2.0
            now_t = time.time()
            
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
                    best_lock_d = float("inf")
                    for det in detections:
                        hx = det.x
                        hy = det.y - det.h * headshot_bias
                        dist_last = math.hypot(hx - last_mid_coord[0], hy - last_mid_coord[1])
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
                    best_crosshair_d = float("inf")
                    for det in detections:
                        hx = det.x
                        hy = det.y - det.h * headshot_bias
                        dist = math.hypot(hx - cx, hy - cy)
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
                    current_pred_t = time.time()
                    if pred_prev_time is None:
                        # First target — no prediction yet
                        pred_prev_x, pred_prev_y = hx, hy
                        pred_prev_time = current_pred_t
                        pred_prev_vx = pred_prev_vy = 0.0
                    else:
                        # Detect target switch (jump > 30% of screen)
                        max_jump = cap_size * 0.3
                        if abs(hx - pred_prev_x) > max_jump or abs(hy - pred_prev_y) > max_jump:
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
                            cur_dist = math.hypot(hx - pred_prev_x, hy - pred_prev_y)
                            proximity = max(0.1, min(1.0, 1.0 / (cur_dist + 1.0)))

                            speed_corr = 1.0
                            if pred_prev_distance is not None and max_pred_distance > 0:
                                speed_corr = 1.0 + (abs(cur_dist - pred_prev_distance) / max_pred_distance) * 0.1

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

                mx, my = fov_to_counts(
                    dx_px, dy_px,
                    pre_x=pre_x, pre_y=pre_y, Cx=Cx,
                    legacy_pixel_to_count=legacy_p2c,
                )

                if math.hypot(mx, my) < deadzone_px:
                    pass  # Req 2.13: sub-deadzone → no move, no cooldown
                else:
                    # ─── Division smoothing (stateless, no overshoot) ──
                    if ema_alpha < 1.0 and ema_alpha > 0.0:
                        mx *= ema_alpha
                        my *= ema_alpha

                    # ─── Adaptive speed multiplier ─────
                    distance = math.hypot(dx_px, dy_px)
                    norm_dist = min(distance / (cap_size / 2.0), 1.0)
                    if norm_dist < 0.05:
                        speed_mult = 1.0  # Near center: precise
                    elif norm_dist < 0.20:
                        speed_mult = max_speed_mult  # Mid range: fast snap
                    else:
                        taper = min((norm_dist - 0.20) / 0.80, 1.0)
                        speed_mult = max_speed_mult * (1.0 - taper * 0.3)
                    speed_mult = max(min_speed_mult, min(max_speed_mult, speed_mult))
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

                    if state == 'IDLE':
                        driver.move(mx, my)
                        last_aim_t = time.time()
                        state = 'BUSY'
                        if mask_xy:
                            try: driver.mask_x(1); driver.mask_y(1)
                            except Exception: pass  # noqa: BLE001, E701

            if state == 'BUSY':
                if (time.time() - last_aim_t) * 1000.0 >= cooldown_ms:
                    state = 'IDLE'
                    if mask_xy:
                        try: driver.mask_x(0); driver.mask_y(0)
                        except Exception: pass  # noqa: BLE001, E701

            best_d = (math.hypot(best.x - cx, (best.y - best.h * headshot_bias) - cy)
                      if best is not None else 0.0)

            fps_count += 1
            if time.time() - fps_t0 >= 1.0:
                if not args.silent:
                    aim_label = "\033[92mON\033[0m" if aim_active else "\033[91mOFF\033[0m"
                    print(f"\r[fps={fps_count:3d}  AIM={aim_label}  "
                          f"dets={len(detections):2d}  state={state}  "
                          f"best_d={best_d:6.1f}]    ", end="", flush=True)
                    if args.debug_classes:
                        # Print on its own line so the carriage-return status
                        # bar above does not overwrite it. Histogram resets
                        # each second so spikes are visible in real time.
                        print(f"  raw_classes={raw_class_hist}", flush=True)
                raw_class_hist = {}
                # --debug-frame: dump the most recent capture once per
                # second so the operator can verify the AI is receiving
                # real pixels (and not, e.g., a black frame from a
                # detached HDMI cable). Cheap because cv2.imwrite is
                # called at 1 Hz, not at 60 fps. With --debug-classes
                # also active, draw the raw detections (regardless of
                # target_classes filter) on top so the operator can see
                # WHAT the model actually predicted vs WHERE the bot is.
                if args.debug_frame and frame is not None:
                    try:
                        import cv2 as _cv2
                        out = frame.copy()
                        if args.debug_classes:
                            try:
                                for d in getattr(engine, "last_raw_detections", []):
                                    cid = int(d.get("class_id", -1))
                                    conf = float(d.get("confidence", 0.0))
                                    bx = float(d.get("x", 0.0))
                                    by = float(d.get("y", 0.0))
                                    bw = float(d.get("w", 0.0))
                                    bh = float(d.get("h", 0.0))
                                    x1 = int(bx - bw / 2)
                                    y1 = int(by - bh / 2)
                                    x2 = int(bx + bw / 2)
                                    y2 = int(by + bh / 2)
                                    color = (0, 255, 0) if cid == 0 else (0, 0, 255)
                                    _cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
                                    _cv2.putText(
                                        out, f"c={cid} {conf:.2f}",
                                        (x1, max(15, y1 - 4)),
                                        _cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
                                    )
                            except Exception:  # noqa: BLE001
                                pass
                        # Crosshair marker at the centre of the crop —
                        # this is where the in-game crosshair lives,
                        # so any detection's distance from this point
                        # is the dx_px/dy_px the dispatch consumes.
                        ccx = out.shape[1] // 2
                        ccy = out.shape[0] // 2
                        _cv2.drawMarker(
                            out, (ccx, ccy), (255, 255, 255),
                            markerType=_cv2.MARKER_CROSS, markerSize=20, thickness=1,
                        )
                        _cv2.imwrite(str(REPO_ROOT / "debug_frame.jpg"), out)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("debug-frame imwrite: %s", e)
                fps_count, fps_t0 = 0, time.time()

    except KeyboardInterrupt:
        if not args.silent:
            print("\n[KeyboardInterrupt]")
    finally:
        try: capture.cleanup()
        except Exception as e: logger.warning("capture.cleanup(): %s", e)  # noqa: BLE001, E701
        try: engine.release()
        except Exception as e: logger.warning("engine.release(): %s", e)  # noqa: BLE001, E701
        # Restore the player's mouse BEFORE releasing the driver (2.9 / §4.6).
        try: driver.unmask_all()
        except Exception as e: logger.warning("driver.unmask_all(): %s", e)  # noqa: BLE001, E701
        try: driver.release()
        except Exception as e: logger.warning("driver.release(): %s", e)  # noqa: BLE001, E701
        if not args.silent:
            print("[OK] shutdown complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
