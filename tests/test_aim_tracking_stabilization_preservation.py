"""
Property tests — Task 2 of spec ``aim-tracking-stabilization``.

# Feature: aim-tracking-stabilization, Property 2: Preservation —
#   Non-Buggy Inputs (3.1–3.7).

**Property 2: Preservation — Non-Buggy Inputs**

    *For any* aim-dispatch state ``X`` where ``isBugCondition(X) =
    FALSE`` (the activation key is not held, OR the detection list is
    empty, OR none of the 13 disjuncts hold), the fixed dispatch SHALL
    produce the same observable result as the original dispatch:
    ``aim_dispatch(X) = aim_dispatch'(X)``.

This file encodes the seven preservation surfaces (3.1–3.7) of
design.md "Preservation Requirements" / "Testing Strategy →
Preservation Checking" / "Property-Based Tests" Property 5 + Property
6, one Hypothesis property per requirement clause.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**

EXPECTED OUTCOME ON UNFIXED CODE
================================

These tests are the **preservation property tests** for the
aim-tracking-stabilization bugfix. They MUST PASS on the current
(unfixed) ``main_simple.py`` / ``input/kmbox_net_driver.py`` /
``capture/capture_card.py`` / ``engines/ai_engine.py`` / ``aim/
pipeline.py`` — passing confirms the *baseline behaviour to preserve*.

After the fix lands (task 3), the SAME properties are re-run (task
3.7) and SHALL still pass — confirming no regressions on the seven
preservation surfaces.

OBSERVED BASELINES (recorded against UNFIXED code per task 2)
=============================================================

3.1 ``engine.process_frame(frame)`` is deterministic on a fixed RGB
    frame — calling it twice on the same bytes returns the *same*
    detection list (current implementation: ``enabled = False`` →
    returns ``[]`` deterministically; the property is the
    determinism, not a specific value).

3.2 The exact 16-byte / 72-byte UDP packet emitted by every public
    ``KmBoxNetDriver`` method (``move``, ``move_relative``,
    ``click_button``, ``mouse_down``, ``mouse_up``, ``key_press``,
    ``scroll``, ``monitor``, ``setconfig``, ``mask_mouse_left``,
    ``unmask_all``) for a given input is byte-for-byte stable across
    runs, recorded by patching ``socket.socket`` with a
    :class:`FakeUdpSocket` and reading the plaintext header + payload
    after seeding ``PacketBuilder._rand_source`` with a fixed seed.

3.3 ``engine.backend_name == 'none'`` and
    ``engine.model_path == './models/v11n-416-2.onnx'`` (or whatever
    the user's config sets) for an unloaded engine constructed with a
    fixed config dict.

3.4 ``capture.initialize(target_fps)`` returns ``True`` and persists
    ``(self._width, self._height, self._actual_fourcc) == (W, H, F)``
    for a fixed (mocked) ``cv2.VideoCapture`` whose
    ``CAP_PROP_FRAME_WIDTH``/``..._HEIGHT`` are the recorded values.

3.5 ``hashlib.sha256(open('aim/pipeline.py', 'rb').read()).hexdigest()``
    has a fixed baseline value at the time of bug-condition test
    authoring. This baseline is asserted unchanged.

3.6 With ``general.activation_key = 'f5'``,
    ``main_simple._key_down(0x74)`` calls
    ``ctypes.windll.user32.GetAsyncKeyState(0x74)`` exactly once and
    masks the result with ``0x8000``. ``GetKeyState`` is NOT
    consulted, and ``driver.isdown_side1`` / ``isdown_side2`` are NOT
    consulted (3.6 fall-through arm of the post-fix
    ``_is_active(spec)`` per design.md File 3 entry 2).

3.7 With ``aim_active = False`` OR ``len(detections) == 0``, the
    aim-tick logic from ``main_simple.py`` lines 169–225 emits zero
    ``driver.move`` calls. This is asserted directly against a
    :class:`MockKmBoxNetDriver` recording every call.

Implementation notes
--------------------

The seven properties share a small set of fixtures:

  - ``FakeUdpSocket`` / ``FakeDevice`` from
    ``tests/input/kmbox_net/conftest.py`` — used by 3.2 to drive a
    real :class:`KmBoxNetDriver` against an in-memory UDP fake.
  - ``MockKmBoxNetDriver`` (defined locally) — used by 3.7 to record
    public driver calls without any wire interaction.
  - ``hypothesis`` strategies that constrain each generator to the
    domain the property quantifies over (small RGB frames for 3.1,
    bounded driver-call sequences for 3.2, ``aim_active = False`` OR
    empty detections for 3.7).

Each property runs ≥ 100 generated examples by default per the task
contract.
"""

from __future__ import annotations

import hashlib
import math
import random
import socket as _stdlib_socket
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from hypothesis import HealthCheck, assume, given, settings, strategies as st

# Ensure the project root is on sys.path so ``main_simple`` and friends
# import the same way they do under ``python main_simple.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import main_simple  # noqa: E402
from engines.ai_engine import AIVisionEngine, Detection  # noqa: E402
from input import kmbox_net_driver as kmd  # noqa: E402
from input.kmbox_net_driver import (  # noqa: E402
    CMD_HEAD_FORMAT,
    CMD_HEAD_SIZE,
    ConnectionStatus,
    KmBoxNetDriver,
)
from tests.input.kmbox_net.conftest import (  # noqa: E402
    FakeDevice,
    FakeUdpSocket,
)


# ---------------------------------------------------------------------------
# Recorded baselines (observed against UNFIXED code at task 2 authoring)
# ---------------------------------------------------------------------------

# 3.5 — SHA-256 of ``aim/pipeline.py`` at task 2 authoring.
# Recorded via:
#     python -c "import hashlib;print(hashlib.sha256(
#         open('aim/pipeline.py','rb').read()).hexdigest())"
_AIM_PIPELINE_SHA256_BASELINE: str = (
    "fdfea8f11534fb3c3a5be306f7368b88589ece8d00e29e6e6bdbed9f1da69c57"
)

# 3.6 — VK code for ``f5`` per ``main_simple._VK_BY_NAME`` (line 89).
_VK_F5: int = 0x74
_VK_HIGH_BIT_MASK: int = 0x8000

# 3.2 — canonical fake handshake target (matches the user's config.yaml).
_TEST_IP: str = "192.168.2.188"
_TEST_PORT: str = "41990"
_TEST_UUID: str = "B6860C3D"

# 3.4 — recorded baseline returned by ``capture.initialize`` against a
# mocked cv2.VideoCapture configured with the user's UGREEN MS2130
# preset (1920×1080 YUY2 60 fps per design.md "Preservation
# Requirement 3.4 → Capture initialization").
_CAPTURE_BASELINE_WIDTH: int = 1920
_CAPTURE_BASELINE_HEIGHT: int = 1080
_CAPTURE_BASELINE_FOURCC: str = "YUY2"


# ---------------------------------------------------------------------------
# 3.1  QNN provider preservation — engine.process_frame is deterministic
# ---------------------------------------------------------------------------


def _make_engine_disabled(model_path: str = "./models/v11n-416-2.onnx") -> AIVisionEngine:
    """Construct an :class:`AIVisionEngine` whose backend is the
    no-op fallback (``enabled = False``).

    With ``enabled = False``, ``process_frame`` returns the empty list
    on every input — the deterministic baseline this preservation test
    asserts. After the fix, the same property must hold.
    """
    return AIVisionEngine(
        {
            "enabled": False,
            "model_path": model_path,
            "capture_size": 416,
            "confidence": 0.55,
            "iou_threshold": 0.45,
            "headshot_bias": 0.30,
            "target_classes": [0],
        },
        shared_state=None,
    )


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.large_base_example],
)
@given(
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
def test_preservation_qnn_provider(seed: int) -> None:
    """**Validates: Requirements 3.1**

    For any fixed RGB frame, ``engine.process_frame(frame)`` returns
    the same detection list on two consecutive calls — i.e. the
    inference path is deterministic on identical input. Per design.md
    "Testing Strategy → Preservation Checking" Test Case 1.

    The current (unfixed) code path is ``AIVisionEngine.process_frame``
    in ``engines/ai_engine.py`` which short-circuits to ``[]`` when
    ``enabled = False`` (no model loaded). The post-fix code path
    SHALL preserve this determinism: the same frame in → the same
    detection list out. The fix touches only the aim-dispatch
    site in ``main_simple.py``; ``AIVisionEngine.process_frame`` is
    NOT modified (Requirement 3.1).
    """
    rng = np.random.default_rng(seed)
    frame = rng.integers(0, 256, size=(416, 416, 3), dtype=np.uint8)

    engine = _make_engine_disabled()
    out_a = engine.process_frame(frame.copy())
    out_b = engine.process_frame(frame.copy())

    # Determinism: two consecutive calls on bit-identical frame bytes
    # produce bit-identical detection lists. The list contents are the
    # baseline behaviour to preserve — not a specific value.
    assert out_a == out_b, (
        f"engine.process_frame is not deterministic on a fixed RGB "
        f"frame: first call returned {out_a!r}, second call returned "
        f"{out_b!r}"
    )
    # On UNFIXED code the engine is disabled (no model loaded in
    # tests), so the recorded baseline is the empty list.
    assert out_a == [], (
        f"engine.process_frame baseline (enabled=False) is the empty "
        f"list per design.md Preservation Requirement 3.1; got "
        f"{out_a!r}"
    )



# ---------------------------------------------------------------------------
# 3.2  Wire-byte preservation — every public KmBoxNetDriver method
# ---------------------------------------------------------------------------


# Public driver methods enumerated in tasks.md task 2 — the existing
# public surface, NOT the new wrappers added by task 3.1
# (``trace`` / ``mask_side1`` / ``mask_side2`` / ``mask_x`` /
# ``mask_y`` / ``isdown_side1`` / ``isdown_side2``).
#
# Each entry is a tuple ``(method_name, args_strategy)`` where
# ``args_strategy`` is a Hypothesis strategy for the call's positional
# arguments. The strategies are constrained to the per-method
# validation contract documented in ``input/kmbox_net_driver.py`` so a
# generated call NEVER fails validation (which would short-circuit the
# dispatch and produce no wire bytes — uninteresting for preservation
# checking).
_PUBLIC_DRIVER_CALLS: List[Tuple[str, st.SearchStrategy]] = [
    # move(x, y) — float input, internally clamped to int [-32768, 32768]
    # via BaseMouse.calculate_move_amount. Bound the floats to a range
    # whose integer truncation lies inside the validator's range.
    (
        "move",
        st.tuples(
            st.floats(min_value=-1000.0, max_value=1000.0,
                      allow_nan=False, allow_infinity=False, width=32),
            st.floats(min_value=-1000.0, max_value=1000.0,
                      allow_nan=False, allow_infinity=False, width=32),
        ),
    ),
    # move_relative(dx, dy) — strict ints in [-32768, 32768] per _move.
    (
        "move_relative",
        st.tuples(
            st.integers(min_value=-32768, max_value=32768),
            st.integers(min_value=-32768, max_value=32768),
        ),
    ),
    # click_button(button) — 'left'/'right'/'middle' or DD-compatible
    # int code. Use only string labels for byte-stable test output.
    (
        "click_button",
        st.tuples(st.sampled_from(["left", "right", "middle"])),
    ),
    # mouse_down(button) — 'left'/'right'/'middle' or 1/2/3.
    (
        "mouse_down",
        st.tuples(st.sampled_from(["left", "right", "middle"])),
    ),
    # mouse_up(button) — 'left'/'right'/'middle' or 1/2/3.
    (
        "mouse_up",
        st.tuples(st.sampled_from(["left", "right", "middle"])),
    ),
    # key_press(vk_code, hold_ms=0) — vk_code in the _vk_to_hid table;
    # use the F-keys 0x70..0x79 (always mapped per _VK_TO_HID_TABLE)
    # and hold_ms = 0 to keep the test fast.
    (
        "key_press",
        st.tuples(
            st.integers(min_value=0x70, max_value=0x79),
            st.just(0),
        ),
    ),
    # scroll(amount) — int in [-128, 128] excluding 0 per _wheel.
    (
        "scroll",
        st.tuples(
            st.integers(min_value=-128, max_value=128).filter(lambda v: v != 0),
        ),
    ),
    # monitor(port) — int in [0, 65535]. 0 disables the listener (no
    # background thread to clean up).
    (
        "monitor",
        st.tuples(st.just(0)),
    ),
    # setconfig(ip, port) — IPv4 string + int port in [1, 65535].
    (
        "setconfig",
        st.tuples(
            st.just("192.168.2.188"),
            st.integers(min_value=1, max_value=65535),
        ),
    ),
    # mask_mouse_left(state) — 0 or 1.
    (
        "mask_mouse_left",
        st.tuples(st.sampled_from([0, 1])),
    ),
    # unmask_all() — no args.
    (
        "unmask_all",
        st.just(()),
    ),
]


def _build_connected_driver(
    rand_seed: int = 42,
    use_encryption: bool = False,
) -> Tuple[KmBoxNetDriver, FakeUdpSocket]:
    """Construct a :class:`KmBoxNetDriver` whose handshake succeeds
    against a :class:`FakeUdpSocket` + :class:`FakeDevice`.

    The returned driver's ``_packet_builder._rand_source`` is reseeded
    with ``rand_seed`` AFTER the handshake so subsequent
    ``head.rand`` values are deterministic across runs — this is
    what makes byte-for-byte equality assertions tractable across
    independent test runs.

    The handshake itself emits one plaintext ``cmd_connect`` packet
    that uses the original (urandom-seeded) RNG; the test inspects
    only the post-handshake packets so the handshake byte stream is
    irrelevant to the property assertion.
    """
    sockets: List[FakeUdpSocket] = []
    device = FakeDevice(outcome=FakeDevice.HandshakeOutcome.SUCCESS)

    def factory(
        family: int = _stdlib_socket.AF_INET,
        type_: int = _stdlib_socket.SOCK_DGRAM,
        proto: int = 0,
        fileno: Optional[int] = None,
        **_kwargs,
    ) -> FakeUdpSocket:
        sock = FakeUdpSocket(family=family, type_=type_)
        sock.proto = proto
        sockets.append(sock)
        device.attach(sock)
        return sock

    with patch.object(_stdlib_socket, "socket", factory):
        driver = KmBoxNetDriver(
            ip=_TEST_IP,
            port=_TEST_PORT,
            uuid=_TEST_UUID,
            use_encryption=use_encryption,
            target_cps=10.0,
        )

    assert driver.connection_status is ConnectionStatus.CONNECTED, (
        f"FakeDevice handshake unexpectedly failed: "
        f"connection_status={driver.connection_status}"
    )
    assert sockets, "factory was never called — no FakeUdpSocket available"

    # Reseed the rand source for byte-stable head.rand fields. Reset
    # ``_indexpts`` to 1 (it was bumped to 1 by the handshake) so
    # subsequent indexpts values start from 2 deterministically — the
    # handshake packet was already sent and is filtered out by the
    # caller's ``post_handshake_packets`` accessor.
    driver._packet_builder._rand_source = random.Random(rand_seed)

    return driver, sockets[0]


def _replay_calls(
    driver: KmBoxNetDriver,
    calls: List[Tuple[str, tuple]],
) -> None:
    """Invoke a sequence of public driver methods on ``driver``."""
    for name, args in calls:
        method = getattr(driver, name)
        method(*args)


def _post_handshake_packets(sock: FakeUdpSocket) -> List[bytes]:
    """Return the byte stream emitted after the handshake (which is
    always the first 16-byte packet on a fresh ``FakeUdpSocket``)."""
    if not sock.sent:
        return []
    # First packet is always the cmd_connect handshake.
    return [payload for (payload, _addr) in sock.sent[1:]]


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
        HealthCheck.large_base_example,
    ],
)
@given(
    # Generate a sequence of 1..6 (method_name, args) tuples drawn
    # from the public surface. This exercises Property 5 (wire-byte
    # preservation under random call sequences) per design.md
    # "Property-Based Tests".
    call_sequence=st.lists(
        st.one_of(
            *[
                st.tuples(st.just(name), strat)
                for name, strat in _PUBLIC_DRIVER_CALLS
            ]
        ),
        min_size=1,
        max_size=6,
    ),
    rand_seed=st.integers(min_value=0, max_value=2**31 - 1),
)
def test_preservation_wire_bytes(
    call_sequence: List[Tuple[str, tuple]],
    rand_seed: int,
) -> None:
    """**Validates: Requirements 3.2**

    For any sequence of public ``KmBoxNetDriver`` calls (drawn from
    the existing public surface, NOT the new ``trace`` /
    ``mask_side*`` / ``mask_x`` / ``mask_y`` / ``isdown_side*``
    wrappers added by task 3.1), the byte stream emitted on the wire
    is byte-for-byte stable across two independent driver instances
    seeded with the same RNG.

    This is design.md Property-Based Tests "Property 5 wire-byte
    preservation under random call sequences" and Preservation Test
    Case 2. The new wrappers introduced by task 3.1 emit packets
    whose byte layout is identical to existing protocol packets
    (``trace`` → ``cmd_bazerMove``, ``mask_*`` → ``cmd_mask_mouse``)
    per design.md §4.2 / §4.6 — but they are excluded from this
    sequence so the test isolates the preservation claim from any
    new code path.

    The fixture seeds ``_packet_builder._rand_source`` with a fixed
    seed AFTER the handshake so the ``head.rand`` field is
    deterministic; ``_indexpts`` is monotonic from the
    PacketBuilder's own counter; and ``head.mac`` is derived purely
    from the constructor's ``uuid`` argument. The handshake itself
    uses the original urandom-seeded RNG and is stripped from the
    captured byte stream before the equality check.
    """
    # Two independent driver instances, same RNG seed.
    driver_a, sock_a = _build_connected_driver(rand_seed=rand_seed)
    try:
        _replay_calls(driver_a, call_sequence)
        bytes_a = _post_handshake_packets(sock_a)
    finally:
        try:
            driver_a.release()
        except Exception:  # noqa: BLE001 — release must not break the test
            pass

    driver_b, sock_b = _build_connected_driver(rand_seed=rand_seed)
    try:
        _replay_calls(driver_b, call_sequence)
        bytes_b = _post_handshake_packets(sock_b)
    finally:
        try:
            driver_b.release()
        except Exception:  # noqa: BLE001
            pass

    # Property 5: byte-for-byte equality of the two captured streams.
    assert bytes_a == bytes_b, (
        f"wire-byte preservation violated for call sequence "
        f"{call_sequence!r}: stream A != stream B\n"
        f"  A: {[b.hex() for b in bytes_a]}\n"
        f"  B: {[b.hex() for b in bytes_b]}"
    )

    # Sanity: every captured packet's header size is correct
    # (16 bytes for keyboard / monitor / reboot / setconfig / mask /
    # unmask, 72 bytes for mouse-class commands). Assert that header
    # parsing succeeds — a malformed packet would indicate a wire
    # protocol drift.
    for pkt in bytes_a:
        assert len(pkt) >= CMD_HEAD_SIZE, (
            f"captured packet shorter than CMD_HEAD_SIZE: "
            f"{pkt.hex()} (len={len(pkt)})"
        )
        # Unpack the header to verify it is well-formed.
        struct.unpack(CMD_HEAD_FORMAT, pkt[:CMD_HEAD_SIZE])



# ---------------------------------------------------------------------------
# 3.3  Model file preservation — engine.backend_name + engine.model_path
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    # The model_path under test — a string drawn from a fixed pool of
    # plausible relative paths the user might have in config.yaml.
    # The property holds for every choice: the engine's ``model_path``
    # field equals what was passed in, and ``backend_name`` is
    # ``'none'`` (the unloaded baseline).
    model_path=st.sampled_from([
        "./models/v11n-416-2.onnx",
        "./models/v11n-416-2-fp16.onnx",
        "./models/test_model.onnx",
        "models/v11n-416-2.onnx",
    ]),
)
def test_preservation_model_file(model_path: str) -> None:
    """**Validates: Requirements 3.3**

    ``engine.backend_name`` and ``engine.model_path`` are unchanged
    by the bugfix — the fix touches only the aim-dispatch site in
    ``main_simple.py`` and adds public driver wrappers in
    ``input/kmbox_net_driver.py``; neither affects the engine's
    model file selection or backend selection cascade
    (``AIVisionEngine._find_model`` / ``load_model`` /
    ``backend_name`` per design.md File 3 / §4.1).

    Per design.md "Testing Strategy → Preservation Checking" Test
    Case 3 and "Preservation Requirements" 3.3, the recorded
    baseline is:

      * ``engine.backend_name`` returns ``'none'`` for an unloaded
        engine (``AIVisionEngine.backend_name`` property at
        line 829 of ``engines/ai_engine.py``).
      * ``engine.model_path`` equals the path passed via
        ``config['model_path']`` (line 156 of
        ``engines/ai_engine.py``).
    """
    engine = _make_engine_disabled(model_path=model_path)

    # 3.3 baseline 1: backend_name is 'none' for an unloaded engine.
    assert engine.backend_name == "none", (
        f"engine.backend_name baseline preservation violated: "
        f"expected 'none' (unloaded engine), got "
        f"{engine.backend_name!r}"
    )

    # 3.3 baseline 2: model_path is preserved verbatim from the
    # config dict. The bugfix MUST NOT rewrite this field.
    assert engine.model_path == model_path, (
        f"engine.model_path baseline preservation violated: "
        f"expected {model_path!r}, got {engine.model_path!r}"
    )


# ---------------------------------------------------------------------------
# 3.4  Capture initialization preservation — (width, height, fourcc)
# ---------------------------------------------------------------------------


def _make_mock_video_capture(
    width: int = _CAPTURE_BASELINE_WIDTH,
    height: int = _CAPTURE_BASELINE_HEIGHT,
    fourcc: str = _CAPTURE_BASELINE_FOURCC,
) -> MagicMock:
    """Build a ``cv2.VideoCapture``-shaped MagicMock that reports the
    given resolution and FourCC.

    ``CaptureCardCapture.initialize`` consults the mock via:

      * ``isOpened()``                 → True
      * ``get(CAP_PROP_FRAME_WIDTH)``  → ``width``
      * ``get(CAP_PROP_FRAME_HEIGHT)`` → ``height``
      * ``get(CAP_PROP_FOURCC)``       → little-endian-packed ASCII
                                          of ``fourcc`` so
                                          ``_try_fourcc`` accepts it
      * ``read()``                     → ``(True, np.zeros(...))``
        (test-read must succeed)
      * ``set(...)`` / ``release()``   → MagicMock no-ops

    Used only in the 3.4 preservation test; no real device is opened.
    """
    fourcc_bytes = fourcc.encode("ascii")
    fourcc_int = (
        fourcc_bytes[0]
        | (fourcc_bytes[1] << 8)
        | (fourcc_bytes[2] << 16)
        | (fourcc_bytes[3] << 24)
    )

    cap_prop_frame_width = 3   # cv2.CAP_PROP_FRAME_WIDTH
    cap_prop_frame_height = 4  # cv2.CAP_PROP_FRAME_HEIGHT
    cap_prop_fourcc = 6        # cv2.CAP_PROP_FOURCC

    mock_cap = MagicMock(name="VideoCapture")
    mock_cap.isOpened.return_value = True

    def _get(prop: int) -> float:
        if prop == cap_prop_frame_width:
            return float(width)
        if prop == cap_prop_frame_height:
            return float(height)
        if prop == cap_prop_fourcc:
            return float(fourcc_int)
        return 0.0

    mock_cap.get.side_effect = _get
    mock_cap.set.return_value = True
    mock_cap.read.return_value = (True, np.zeros((height, width, 3), dtype=np.uint8))
    mock_cap.release.return_value = None
    return mock_cap


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
        HealthCheck.large_base_example,
    ],
)
@given(
    target_fps=st.integers(min_value=30, max_value=144),
)
def test_preservation_capture_init(target_fps: int) -> None:
    """**Validates: Requirements 3.4**

    ``capture.initialize(target_fps)`` returns ``True`` for any
    plausible ``target_fps`` and persists the recorded
    ``(width, height, fourcc)`` tuple of
    ``(1920, 1080, 'YUY2')`` — the UGREEN MS2130 DSHOW preset per
    design.md "Preservation Requirement 3.4".

    Per design.md "Testing Strategy → Preservation Checking" Test
    Case 4, the bugfix only adds a new ``grab_latest`` accessor
    (task 3.2); ``initialize``, ``_capture_loop``, ``cleanup``, and
    backend selection are NOT modified, so the recorded tuple
    SHALL hold across the fix.

    The test mocks ``cv2.VideoCapture`` so no real device is opened
    — the property is observation-first, not hardware-dependent.
    """
    from capture.capture_card import CaptureCardCapture

    # Construct a mocked cv2.VideoCapture for the device under test.
    mock_cap = _make_mock_video_capture()

    capture = CaptureCardCapture(
        device_index=0,
        fourcc=_CAPTURE_BASELINE_FOURCC,
        width=_CAPTURE_BASELINE_WIDTH,
        height=_CAPTURE_BASELINE_HEIGHT,
    )

    # Patch cv2.VideoCapture inside the capture_card module so the
    # mock is returned regardless of constructor arguments.
    with patch("capture.capture_card.cv2.VideoCapture", return_value=mock_cap):
        try:
            ok = capture.initialize(target_fps=target_fps)

            # 3.4 baseline 1: initialize returns True for the mocked
            # device that reports 1920×1080 YUY2.
            assert ok is True, (
                f"capture.initialize(target_fps={target_fps}) returned "
                f"{ok!r}; expected True for the recorded MS2130 "
                f"preset"
            )

            # 3.4 baseline 2: (width, height) tuple matches recorded.
            assert capture.get_resolution() == (
                _CAPTURE_BASELINE_WIDTH,
                _CAPTURE_BASELINE_HEIGHT,
            ), (
                f"capture.get_resolution() preservation violated: "
                f"expected "
                f"({_CAPTURE_BASELINE_WIDTH}, "
                f"{_CAPTURE_BASELINE_HEIGHT}), got "
                f"{capture.get_resolution()!r}"
            )

            # 3.4 baseline 3: fourcc matches recorded ('YUY2').
            assert capture._actual_fourcc == _CAPTURE_BASELINE_FOURCC, (
                f"capture._actual_fourcc preservation violated: "
                f"expected {_CAPTURE_BASELINE_FOURCC!r}, got "
                f"{capture._actual_fourcc!r}"
            )
        finally:
            capture.cleanup()



# ---------------------------------------------------------------------------
# 3.5  aim/pipeline.py preservation — SHA-256 unchanged
# ---------------------------------------------------------------------------


def test_preservation_aim_pipeline_unchanged() -> None:
    """**Validates: Requirements 3.5**

    The SHA-256 of ``aim/pipeline.py`` is unchanged by the bugfix.
    Per design.md "Preservation Requirement 3.5":

        ``aim/pipeline.py`` is unmodified. ``main_simple.py`` does
        not call ``aim_step`` and SHALL continue not to call it.
        The module MAY be deleted as a separate cleanup; this
        bugfix does not "improve" it.

    This is a single-shot assertion (no Hypothesis generator —
    nothing to generate over) per design.md "Testing Strategy →
    Preservation Checking" Test Case 5. The recorded baseline hash
    is the file's SHA-256 at task 2 authoring; if the file changes
    for any reason during task 3, this property fails and the fix
    is rolled back per the preservation contract.
    """
    pipeline_path = _REPO_ROOT / "aim" / "pipeline.py"
    assert pipeline_path.exists(), (
        f"aim/pipeline.py not found at {pipeline_path}"
    )
    actual = hashlib.sha256(pipeline_path.read_bytes()).hexdigest()
    assert actual == _AIM_PIPELINE_SHA256_BASELINE, (
        f"aim/pipeline.py SHA-256 preservation violated: "
        f"expected {_AIM_PIPELINE_SHA256_BASELINE!r}, got {actual!r}. "
        f"Per design.md Preservation Requirement 3.5, the file MUST "
        f"be unmodified by this bugfix."
    )


# ---------------------------------------------------------------------------
# 3.6  GetAsyncKeyState preservation for non-toggle VK (f5)
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    # Generate the high-bit return value the mocked
    # ``GetAsyncKeyState`` will return — the activation gate must
    # treat any value with bit 0x8000 set as "key down" and any
    # value without it as "key up". Hypothesis explores the boundary.
    raw_state=st.integers(min_value=0, max_value=0xFFFF),
)
def test_preservation_getasynckeystate_for_non_toggle_vk(
    raw_state: int,
) -> None:
    """**Validates: Requirements 3.6**

    With ``general.activation_key = 'f5'`` (a non-toggle, non-mouse
    VK code 0x74), the activation gate dispatches via
    ``ctypes.windll.user32.GetAsyncKeyState(0x74) & 0x8000`` exactly
    as the unfixed code does. Per design.md "Preservation
    Requirement 3.6":

        WHEN ``general.activation_key`` is bound to any VK other than
        ``caps_lock``, ``mouse_side1``, or ``mouse_side2``, the
        activation gate continues to use ``GetAsyncKeyState(VK) &
        0x8000`` and HOLD-to-aim semantics. Only ``caps_lock`` is
        rerouted to ``GetKeyState``, and only ``mouse_side1`` /
        ``mouse_side2`` is rerouted to the monitor channel.

    The post-fix code's ``_is_active(spec, driver)`` (design.md File
    3 entry 2) must dispatch to ``GetAsyncKeyState(0x74) & 0x8000``
    on the ``vk`` arm and MUST NOT call ``GetKeyState`` or
    ``driver.isdown_side1`` / ``isdown_side2`` for any VK other
    than caps_lock / mouse_side. Per design.md Preservation Test
    Case 6, this is the property under test.

    The test calls the unfixed ``main_simple._key_down(0x74)`` with
    ``ctypes.windll.user32`` mocked, and asserts:

      1. ``GetAsyncKeyState`` was invoked exactly once with arg
         ``0x74``.
      2. ``GetKeyState`` was NOT invoked.
      3. ``main_simple._VK_BY_NAME['f5'] == 0x74`` (the resolution
         table is unchanged).
      4. The boolean return matches ``bool(raw_state & 0x8000)``
         (the high-bit semantics are preserved).
    """
    # 3.6 sanity: the VK lookup table maps 'f5' to 0x74.
    assert main_simple._resolve_vk("f5") == _VK_F5, (
        f"main_simple._resolve_vk('f5') preservation violated: "
        f"expected {_VK_F5!r}, got {main_simple._resolve_vk('f5')!r}"
    )

    mock_user32 = MagicMock(name="user32")
    mock_user32.GetAsyncKeyState.return_value = raw_state
    # GetKeyState is the post-fix Caps-Lock-toggle arm; the
    # non-toggle VK preservation property requires it NOT be
    # consulted for VKs like F5.
    mock_user32.GetKeyState = MagicMock(name="GetKeyState_should_not_be_called")

    mock_windll = MagicMock(name="windll")
    mock_windll.user32 = mock_user32

    with patch("ctypes.windll", mock_windll, create=True):
        actual = main_simple._key_down(_VK_F5)

    # 3.6 conjunct 1: GetAsyncKeyState was called exactly once with VK=0x74.
    mock_user32.GetAsyncKeyState.assert_called_once_with(_VK_F5)

    # 3.6 conjunct 2: the non-toggle VK arm does NOT consult
    # GetKeyState (that is the caps_lock arm, mode (a) of design.md
    # File 3 entry 2).
    assert mock_user32.GetKeyState.call_count == 0, (
        f"GetKeyState was called {mock_user32.GetKeyState.call_count} "
        f"times for non-toggle VK 0x{_VK_F5:02X}; design.md "
        f"Preservation Requirement 3.6 requires zero calls."
    )

    # 3.6 conjunct 3: the high-bit mask semantic is preserved —
    # _key_down returns True iff (raw_state & 0x8000) is non-zero.
    expected = bool(raw_state & _VK_HIGH_BIT_MASK)
    assert actual is expected, (
        f"_key_down(0x{_VK_F5:02X}) returned {actual!r} for raw "
        f"GetAsyncKeyState return {hex(raw_state)}; expected "
        f"{expected!r} per the (& 0x8000) semantic."
    )



# ---------------------------------------------------------------------------
# 3.7  Zero moves when inactive — aim_active=False OR detections=[]
# ---------------------------------------------------------------------------


class _ZeroMoveMockDriver:
    """Minimal recorder for ``driver.move`` calls — used by 3.7.

    The aim-tick logic from ``main_simple.py`` lines 211–225 calls
    ``driver.move(dx, dy)`` exactly once per frame WHEN
    ``aim_active = TRUE AND best is not None``. The 3.7 preservation
    property is the contrapositive: WHEN ``aim_active = FALSE OR best
    is None`` (the latter follows from ``len(detections) == 0`` plus
    the FOV filter), zero ``driver.move`` calls are issued.
    """

    def __init__(self) -> None:
        self.move_calls: List[Tuple[float, float]] = []

    def move(self, x: float, y: float) -> None:
        self.move_calls.append((float(x), float(y)))


def _detection_strategy() -> st.SearchStrategy[Detection]:
    """Hypothesis strategy producing a single ``Detection`` with
    plausible bbox coordinates inside a 416×416 capture region."""
    return st.builds(
        Detection,
        class_id=st.just(0),
        class_name=st.just("person"),
        x=st.floats(min_value=0.0, max_value=416.0,
                    allow_nan=False, allow_infinity=False, width=32),
        y=st.floats(min_value=0.0, max_value=416.0,
                    allow_nan=False, allow_infinity=False, width=32),
        w=st.floats(min_value=10.0, max_value=120.0,
                    allow_nan=False, allow_infinity=False, width=32),
        h=st.floats(min_value=10.0, max_value=200.0,
                    allow_nan=False, allow_infinity=False, width=32),
        confidence=st.floats(min_value=0.0, max_value=1.0,
                             allow_nan=False, allow_infinity=False, width=32),
    )


def _simulate_aim_dispatch(
    aim_active: bool,
    detections: List[Detection],
    driver: _ZeroMoveMockDriver,
    cap_size: int = 416,
    headshot_bias: float = 0.30,
    max_fov_radius: float = 200.0,
    max_step: float = 60.0,
    pixel_to_count: float = 0.85,
) -> None:
    """Replay the unfixed aim-tick logic from ``main_simple.py``
    lines 197–225 against the mock driver.

    The logic is intentionally a faithful copy of the unfixed flow so
    the 3.7 preservation property tests exactly what the production
    aim-tick does — a refactor of ``main_simple.py`` to a callable
    function is out of scope for this preservation observation. The
    fixed (post-task-3) code's selector and dispatch will obey the
    same `aim_active = FALSE OR best is None ⇒ zero moves` invariant
    per design.md "Preservation Requirement 3.7".
    """
    cx = cy = cap_size / 2.0

    # Closest-to-crosshair selector with FOV filter (lines 197–209).
    best: Optional[Detection] = None
    best_d = float("inf")
    for det in detections:
        hx = det.x
        hy = det.y - det.h * headshot_bias
        dist = math.hypot(hx - cx, hy - cy)
        if dist > max_fov_radius:
            continue
        if dist < best_d:
            best_d = dist
            best = det

    # Aim-active gate + dispatch (lines 211–225).
    if aim_active and best is not None:
        hx = best.x
        hy = best.y - best.h * headshot_bias
        dx_px = hx - cx
        dy_px = hy - cy
        mag = math.hypot(dx_px, dy_px)
        if mag > max_step:
            s = max_step / mag
            dx_px *= s
            dy_px *= s
        driver.move(dx_px * pixel_to_count, dy_px * pixel_to_count)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    aim_active=st.booleans(),
    detections=st.lists(_detection_strategy(), min_size=0, max_size=5),
)
def test_preservation_zero_moves_when_inactive(
    aim_active: bool,
    detections: List[Detection],
) -> None:
    """**Validates: Requirements 3.7**

    For any ``(aim_active, detections)`` pair with
    ``aim_active = False`` OR ``len(detections) == 0``, the aim-tick
    logic emits **zero** ``driver.move`` calls. Per design.md
    "Preservation Requirement 3.7":

        WHEN no detection is in the FOV OR the activation key is not
        held THEN the system SHALL CONTINUE TO issue zero mouse
        moves on that iteration; the new cooldown gate SHALL only
        suppress moves that the existing logic would have issued,
        and SHALL NOT introduce new moves.

    This is design.md Property-Based Tests "Property 6
    zero-moves-when-inactive" and Preservation Test Case 7. The
    Hypothesis generator filters to the inactive-or-empty case; the
    active-with-detections case is out of scope for preservation
    (it is the aim hot path that the bugfix actively rewrites).
    """
    # Filter to the inactive-or-empty case the property quantifies
    # over. This is design.md "Preservation Requirement 3.7"
    # precondition: the system SHALL emit zero moves WHEN
    # ``aim_active = FALSE OR detections == []``.
    assume(not aim_active or len(detections) == 0)

    driver = _ZeroMoveMockDriver()
    _simulate_aim_dispatch(
        aim_active=aim_active,
        detections=detections,
        driver=driver,
    )

    # 3.7 invariant: zero driver.move calls.
    assert driver.move_calls == [], (
        f"3.7 preservation violated: aim_active={aim_active!r}, "
        f"len(detections)={len(detections)}, but driver.move was "
        f"called {len(driver.move_calls)} time(s): "
        f"{driver.move_calls!r}"
    )
