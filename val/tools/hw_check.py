"""
Hardware-discovery smoke test — kmbox-net + capture card + ONNX model.

Run with: ``python tools\\hw_check.py``

Reports four sections:

  1. ONNX model file presence + ONNX Runtime availability + model load.
  2. Capture-card enumeration (Media Foundation + DirectShow).
  3. KmBox Net Init_Handshake against the configured IP/port/UUID.
  4. Summary with go / no-go.

Each section is independent so a failure in one (e.g. ONNX runtime missing)
does not prevent the others from running. The KmBox handshake is the only
test that actually opens a real UDP socket — see the section header for
the wire-protocol details.
"""

from __future__ import annotations

import os
import socket
import struct
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _section(name: str) -> None:
    print()
    print("=" * 60)
    print(name)
    print("=" * 60)


# ---------------------------------------------------------------------------
# 1. ONNX model + runtime
# ---------------------------------------------------------------------------

_section("1. ONNX MODEL + RUNTIME")

model_path = REPO_ROOT / "models" / "v11n-416-2.onnx"
if not model_path.exists():
    # Fall back to the FP16 variant if the FP32 baseline is absent.
    model_path = REPO_ROOT / "models" / "v11n-416-2-fp16.onnx"
if model_path.exists():
    size_mb = model_path.stat().st_size / (1024 * 1024)
    print(f"[OK]  Model file: {model_path}")
    print(f"      Size:       {size_mb:.2f} MB")
    model_ok = True
else:
    print(f"[FAIL] Model file NOT FOUND: {model_path}")
    model_ok = False

try:
    import onnxruntime as ort
    print(f"[OK]  onnxruntime: {ort.__version__}")
    # Trigger the QNN plugin-EP registration (no-op if onnxruntime-qnn is not
    # installed). Snapdragon X Elite ships QNN out-of-tree so it has to be
    # registered before it appears in get_available_providers().
    qnn_registered = False
    try:
        from engines.qnn_provider import has_qnn  # noqa: WPS433
        qnn_registered = has_qnn()
    except Exception:
        pass
    providers = ort.get_available_providers()
    print(f"      Providers:   {providers}")
    if qnn_registered and "QNNExecutionProvider" in providers:
        print(f"[OK]  QNNExecutionProvider registered (Snapdragon NPU available)")
    elif qnn_registered:
        print(f"[WARN] has_qnn()=True but QNNExecutionProvider missing from providers")
    else:
        print(f"      (QNNExecutionProvider not registered — NPU acceleration off)")
    ort_ok = True
except ImportError:
    print("[FAIL] onnxruntime NOT INSTALLED")
    print("       Install:    pip install onnxruntime")
    print("       Or DirectML: pip install onnxruntime-directml")
    print("       Or QNN:      pip install onnxruntime-qnn")
    ort_ok = False
    providers = []

if model_ok and ort_ok:
    try:
        # Try CPU first to confirm the model is well-formed; provider
        # selection happens inside the framework.
        sess = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        inputs = sess.get_inputs()
        outputs = sess.get_outputs()
        print(f"[OK]  Model loads under CPUExecutionProvider")
        print(f"      Inputs:     {[(i.name, i.shape, i.type) for i in inputs]}")
        print(f"      Outputs:    {[(o.name, o.shape, o.type) for o in outputs]}")
        model_load_ok = True
    except Exception as exc:
        print(f"[FAIL] Model load failed: {type(exc).__name__}: {exc}")
        model_load_ok = False
else:
    model_load_ok = False
    print("[SKIP] Model load (file or runtime missing)")


# ---------------------------------------------------------------------------
# 1b. NPU smoke (only when QNNExecutionProvider is registered)
# ---------------------------------------------------------------------------

npu_ok = None  # tri-state: None=skip, True=pass, False=fail
if model_ok and ort_ok and qnn_registered and "QNNExecutionProvider" in providers:
    print()
    print("--- NPU smoke (QNNProvider) ---")
    try:
        import numpy as np
        from engines.qnn_provider import QNNProvider

        provider = QNNProvider(str(model_path), imgsz=416, conf=0.55)
        if not provider.load():
            print("[FAIL] QNNProvider.load() returned False — see logs above")
            npu_ok = False
        else:
            # 416x416x3 random BGR frame — closest match to capture-input shape.
            frame = np.random.randint(
                0, 256, size=(416, 416, 3), dtype=np.uint8
            )
            # Warm cache + measure 5 inferences and report median + p95.
            samples = []
            for _ in range(5):
                _, ms = provider.infer(frame)
                samples.append(ms)
            samples.sort()
            median = samples[len(samples) // 2]
            p95 = samples[-1]
            print(f"[OK]  NPU inference x5: median={median:.2f} ms  p95={p95:.2f} ms")
            print(f"      samples (ms): {[f'{s:.2f}' for s in samples]}")
            provider.release()
            npu_ok = True
    except Exception as exc:
        print(f"[FAIL] NPU smoke raised {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        npu_ok = False
elif qnn_registered is False:
    pass  # silently skipped — handled in providers print above


# ---------------------------------------------------------------------------
# 2. Capture-card enumeration
# ---------------------------------------------------------------------------

_section("2. CAPTURE CARD ENUMERATION")

try:
    import cv2
    print(f"[OK]  OpenCV: {cv2.__version__}")
    cv_ok = True
except ImportError:
    print("[FAIL] OpenCV NOT installed")
    cv_ok = False

if cv_ok:
    # Try DSHOW (DirectShow) first — most reliable enumeration on Windows
    # for USB capture cards (MS2130 chipset etc.)
    print()
    print("Probing device indices 0..4 with CAP_DSHOW (DirectShow)...")
    found_dshow = []
    for idx in range(5):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            ok, frame = cap.read()
            if ok and frame is not None:
                shape = frame.shape
                print(f"  [OK]  index={idx} DSHOW  res={w}x{h} fps={fps:.0f} "
                      f"frame_shape={shape}")
                found_dshow.append((idx, w, h, fps, shape))
            else:
                print(f"  [WARN] index={idx} DSHOW  opens but cannot read frame")
            cap.release()
        else:
            print(f"  [--]  index={idx} DSHOW  (not opened)")

    print()
    print("Probing device indices 0..4 with CAP_MSMF (Media Foundation)...")
    found_msmf = []
    for idx in range(5):
        cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            ok, frame = cap.read()
            if ok and frame is not None:
                shape = frame.shape
                print(f"  [OK]  index={idx} MSMF   res={w}x{h} fps={fps:.0f} "
                      f"frame_shape={shape}")
                found_msmf.append((idx, w, h, fps, shape))
            else:
                print(f"  [WARN] index={idx} MSMF   opens but cannot read frame")
            cap.release()
        else:
            print(f"  [--]  index={idx} MSMF   (not opened)")

    capture_ok = bool(found_dshow or found_msmf)
    print()
    if capture_ok:
        backend = "DSHOW" if found_dshow else "MSMF"
        device = (found_dshow + found_msmf)[0]
        print(f"[OK]  Capture card detected via {backend}: index={device[0]} "
              f"{device[1]}x{device[2]} @ {device[3]:.0f}fps")
    else:
        print("[FAIL] No capture card detected on any index/backend")
else:
    capture_ok = False


# ---------------------------------------------------------------------------
# 3. KmBox Net Init_Handshake
# ---------------------------------------------------------------------------

_section("3. KMBOX NET HANDSHAKE")

# Read live config to get the configured IP/port/UUID — same path the
# framework will use at startup.
try:
    import yaml
    cfg_path = REPO_ROOT / "config.yaml"
    with cfg_path.open(encoding="utf-8") as fp:
        cfg = yaml.safe_load(fp)
    km = cfg["input"]["kmbox_net"]
    ip = km["ip"]
    port = int(km["port"])
    uuid = km["uuid"]
    use_encryption = km["use_encryption"]
    print(f"[OK]  Config loaded from {cfg_path}")
    print(f"      ip={ip}  port={port}  uuid={uuid}  enc={use_encryption}")
    cfg_ok = True
except Exception as exc:
    print(f"[FAIL] Cannot read config.yaml: {type(exc).__name__}: {exc}")
    cfg_ok = False
    ip = port = uuid = None
    use_encryption = None

handshake_ok = False
if cfg_ok:
    # Build a connect packet manually. The handshake is plaintext per
    # Requirement 9.6 — no encryption is applied even when the saved
    # config has use_encryption=True. Layout: cmd_head_t = 4 x uint32
    # little-endian (mac, rand, indexpts, cmd) per kmboxNet.h.
    CMD_CONNECT = 0xAF3C2828
    mac = int(uuid[:8].ljust(8, "0"), 16)
    head_rand = 0
    head_indexpts = 1
    packet = struct.pack(
        "<IIII",
        mac & 0xFFFFFFFF,
        head_rand,
        head_indexpts,
        CMD_CONNECT,
    )

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5.0)
    try:
        print(f"      Sending Init_Handshake ({len(packet)} bytes) to "
              f"{ip}:{port} ...")
        t_send = time.monotonic()
        sock.sendto(packet, (ip, port))
        reply, addr = sock.recvfrom(1024)
        rtt_ms = (time.monotonic() - t_send) * 1000
        print(f"[OK]  Reply received from {addr[0]}:{addr[1]} after "
              f"{rtt_ms:.1f} ms")
        print(f"      Reply length: {len(reply)} bytes")
        if len(reply) >= 16:
            r_mac, r_rand, r_idx, r_cmd = struct.unpack("<IIII", reply[:16])
            print(f"      head.mac=0x{r_mac:08X}  head.rand=0x{r_rand:08X}  "
                  f"head.indexpts={r_idx}  head.cmd=0x{r_cmd:08X}")
            # Per upstream kmboxNet.cpp:NetRxReturnHandle the device
            # echoes the request fields rather than returning a
            # status code. A reply of any length >= 16 bytes is a
            # successful handshake regardless of the echoed values.
            if r_cmd == CMD_CONNECT:
                print("[OK]  head.cmd echo matches CMD_CONNECT (handshake SUCCESS)")
            else:
                print(f"[OK]  Reply received (head.cmd=0x{r_cmd:08X} differs "
                      "from CMD_CONNECT but accepted per upstream "
                      "NetRxReturnHandle semantics)")
            handshake_ok = True
        else:
            print(f"[WARN] Reply too short ({len(reply)} bytes); expected >= 16")
    except socket.timeout:
        print(f"[FAIL] TIMEOUT after 5s — no reply from {ip}:{port}")
        print("       Common causes:")
        print("       - kmbox is on a different IP/port (check display LCD)")
        print("       - kmbox not reachable from this NIC (check route)")
        print("       - Windows firewall blocking outbound UDP to that port")
    except OSError as exc:
        errno_val = getattr(exc, "errno", None)
        print(f"[FAIL] Socket error errno={errno_val}: {exc}")
        if errno_val == 10049:
            print("       (WSAEADDRNOTAVAIL — IP not bindable on any local NIC)")
        elif errno_val == 10051:
            print("       (WSAENETUNREACH — no route to that subnet)")
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# 4. Summary
# ---------------------------------------------------------------------------

_section("4. SUMMARY")

results = [
    ("Model file present",      model_ok),
    ("ONNX Runtime installed",  ort_ok),
    ("Model loads under CPU",   model_load_ok),
    ("OpenCV available",        cv_ok if "cv_ok" in dir() else False),
    ("Capture card detected",   capture_ok if "capture_ok" in dir() else False),
    ("config.yaml readable",    cfg_ok),
    ("Kmbox handshake OK",      handshake_ok),
]
# NPU is informational — only included when relevant.
if npu_ok is not None:
    results.insert(3, ("NPU inference (QNN)", npu_ok))

for label, ok in results:
    mark = "[OK]  " if ok else "[FAIL]"
    print(f"  {mark} {label}")

print()
ready = all(ok for _, ok in results)
if ready:
    print(">>> ALL CHECKS PASSED — you can launch the framework")
    if npu_ok is True:
        print(">>> NPU acceleration is ACTIVE — set ai_engine.execution_provider: auto")
    elif qnn_registered is False:
        print(">>> NPU not detected — running on CPUExecutionProvider")
    print(">>> Command: python main.py")
else:
    print(">>> Some checks failed — see sections above for fix instructions")

sys.exit(0 if ready else 1)
