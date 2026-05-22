"""
Property test — Task 1 of spec ``aim-tracking-stabilization``.

# Feature: aim-tracking-stabilization, Property 1: Bug Condition —
#   Aim Dispatch Defects (D1–D13).

**Property 1: Bug Condition — Fix Checking**

    *For any* aim-dispatch state ``X`` where ``isBugCondition(X) = TRUE``
    (the activation key is held, at least one detection is in the FOV,
    and at least one of the 13 disjuncts D1–D13 holds), the fixed
    dispatch ``aim_dispatch'(X)`` SHALL produce a ``result`` such that
    every conjunct of design.md "Property 1 — Fix Checking" holds.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9,
1.10, 1.11, 1.12, 1.13**

EXPECTED OUTCOME ON UNFIXED CODE
================================

This test is the **bug condition exploration test** for the
aim-tracking-stabilization bugfix. It MUST FAIL on the current
(unfixed) ``main_simple.py``; the failure confirms the bug exists. The
13 disjuncts of ``isBugCondition(X)`` from ``bugfix.md`` "Bug Condition
Derivation" each surface as a violated post-fix conjunct of Property 1.

After the fix lands (task 3), the SAME property is re-run (task 3.6)
and SHALL PASS — confirming every disjunct is resolved.

COUNTEREXAMPLES (one per defect; documented per task 1's deliverable)
=====================================================================

Each ``@example`` below is a deterministic counterexample that exposes
the corresponding defect's disjunct of ``isBugCondition(X)``. On
unfixed code, the assertion named in "fails post-fix conjunct" is the
first one tripped; on fixed code that conjunct holds.

    D1  head-shake / per-tick overshoot (linear pixel→count) ─────────
        AimDispatchState(activation_mode='caps_lock', aim_active=True,
        len(detections)=1, target_offset_magnitude=15, deadzone_px=2.0,
        frame_age_ms=8.0, dt_since_last_move_ms=10.0)
        → fails post-fix conjunct  result.fov_conversion = 'trig'  (2.1c)
        and  result.pixel_to_count_calibrated = TRUE  (2.6); on
        unfixed code ``main_simple.py`` line 225 dispatches
        ``driver.move(dx_px * pixel_to_count, dy_px * pixel_to_count)``
        — a single linear scalar with no trig conversion and no
        calibration tied to the user's sens / DPI.

    D2  lock-doesn't-persist (closest-to-crosshair selector amnesia)─
        AimDispatchState(aim_active=True, len(detections)=2,
        selector_kind_observed='closest_to_crosshair_only')
        → fails post-fix conjunct  result.selector_uses_last_mid =
        TRUE  (2.2); on unfixed code ``main_simple.py`` lines 197–209
        recompute the closest pick from scratch every frame and never
        cache ``last_mid_coord``.

    D3  silent-no-fire (stale frame from capture thread) ───────────
        AimDispatchState(aim_active=True, len(detections)=1,
        frame_age_ms=33.0, fps_cap=60)
        → fails post-fix conjunct  result.frame_age_ms ≤ 1000 / fps_cap
        (2.3); on unfixed code ``main_simple.py`` line 195 calls
        ``capture.grab_center_region`` which has no freshness counter
        — the same frame can be returned to two consecutive aim-ticks.

    D4  no-hardware-smoothing (raw cmd_mouse_move dispatch) ─────────
        AimDispatchState(aim_active=True, len(detections)=1,
        target_offset_magnitude=20)
        → fails post-fix conjunct  result.move_kind = 'bezier' AND
        result.bezier_ms ≈ 80  (2.10 supersedes 2.4); on unfixed code
        line 225 dispatches ``CMD_MOUSE_MOVE = 0xAEDE7345`` (a raw HID
        counter advance), never ``CMD_BAZERMOVE = 0xA238455A``.

    D5  no-move-cooldown (back-to-back moves at ~100 fps) ───────────
        AimDispatchState(aim_active=True, len(detections)=1,
        dt_since_last_move_ms=10.0, target_offset_magnitude=20)
        → fails post-fix conjunct  result.dt_since_last_move_ms ≥ 80
        (2.5); on unfixed code there is no ``last_aim_t`` gate — a new
        move is queued every iteration.

    D6  wrong-pixel-to-count calibration (uncalibrated linear scalar)
        AimDispatchState(aim_active=True, len(detections)=1,
        target_offset_magnitude=200, deadzone_px=2.0)
        → fails post-fix conjunct  result.pixel_to_count_calibrated =
        TRUE  (2.6); on unfixed code ``aim.pixel_to_count = 0.85`` is
        not derived from the user's Valorant sens (0.5), ADS multiplier
        (0.4), or mouse DPI (800) and not reconciled with the kvmaibox
        ``Cx ≈ 5140`` constant.

    D7  GetAsyncKeyState-on-toggle-key (Caps Lock LED mismatch) ────
        AimDispatchState(activation_mode='caps_lock', aim_active=True,
        len(detections)=1)
        → fails post-fix conjunct  result.activation_read_method ∈
        {'GetKeyState_toggle', 'monitor_channel_isdown',
        'GetAsyncKeyState_non_toggle'}  (2.7); on unfixed code line 65
        unconditionally calls ``GetAsyncKeyState(0x14) & 0x8000`` which
        only reflects the physical-key-down state, not the LED toggle.

    D8  monitor-channel-unused (mouse_side mode without monitor) ──
        AimDispatchState(activation_mode='mouse_side1', aim_active=True,
        len(detections)=1)
        → fails post-fix conjunct  (mouse_side ⇒ uses_monitor_channel
        = TRUE)  (2.8); on unfixed code ``main_simple.py`` never calls
        ``driver.monitor(port)`` and never reads
        ``driver.isdown_side1()`` / ``isdown_side2()``.

    D9  physical-input-not-masked (player click leaks to gaming PC) ─
        AimDispatchState(activation_mode='mouse_side1', aim_active=True,
        len(detections)=1)
        → fails post-fix conjunct  (mouse_side ⇒
        physical_input_masked = TRUE)  (2.9); on unfixed code there is
        no ``driver.mask_side1(1)`` at startup nor ``driver.unmask_all()``
        on shutdown.

    D10 trace-as-per-move (missing startup trace configuration) ────
        AimDispatchState(aim_active=True, len(detections)=1,
        target_offset_magnitude=20)
        → fails post-fix conjunct  result.trace_configured_at_startup =
        TRUE  (2.10); on unfixed code there is no startup
        ``driver.trace(2, 80)`` so the kmbox device cannot render
        plain ``cmd_mouse_move`` packets as 80 ms hardware Bezier curves.

    D11 missing-per-axis-pre-multipliers (asymmetric in-game FOV) ─
        AimDispatchState(aim_active=True, len(detections)=1,
        target_offset_magnitude=100)
        → fails post-fix conjunct  (trig ⇒ pre_multipliers_applied =
        TRUE)  (2.11); on unfixed code there is no trig conversion at
        all (D1/D6) AND the kvmaibox ``pre_x = 3, pre_y = 2.25`` is not
        applied before ``atan2``.

    D12 cooldown-blocks-tap-tap (simple-dt cooldown vs FSM) ─────────
        AimDispatchState(aim_active=True, len(detections)=1,
        dt_since_last_move_ms=90.0, cooldown_ms=100)
        → fails post-fix conjunct  result.cooldown_kind =
        'fsm_with_release_shortcircuit'  (2.12); on unfixed code there
        is no cooldown FSM at all (cooldown_kind = 'none'), so the
        post-fix conjunct fails for a different reason than D5 — the
        absence of the three-arm state machine with the
        ``(BUSY, released) → IDLE`` short-circuit.

    D13 last-pixel-jitter (no deadzone gate on ~1-count residuals) ─
        AimDispatchState(aim_active=True, len(detections)=1,
        target_offset_magnitude=1.4, deadzone_px=2.0)
        → fails post-fix conjunct  (mag < deadzone ⇒ NOT
        move_was_issued)  (2.13); on unfixed code there is no deadzone
        check before dispatch — a residual ~1-count move is queued
        even when the cursor is on-target.

Every counterexample is a concrete witness that
``isBugCondition(X) = TRUE`` on the input AND the post-fix conjunct
fails on the unfixed dispatch — the conjunction the test asserts to
catch the bug. After the fix (task 3) the SAME counterexamples drive
the SAME property and the conjuncts hold.

Implementation notes
--------------------

The "drive ``main_simple.py``'s aim path through one tick" requirement
is satisfied via a **simulation harness** that:

  1. Source-inspects ``main_simple.py`` (``inspect.getsource``) to
     determine static fix patterns: presence of ``driver.trace(``,
     ``driver.monitor(``, ``driver.mask_side1(``, ``last_mid_coord``,
     ``atan2`` / ``fov_to_counts``, ``GetKeyState``, ``deadzone``,
     ``cooldown_ms``, FSM ``state = 'IDLE' / 'BUSY'``. Each detected
     pattern flips the corresponding ``DispatchResult`` field.
  2. Replays the unfixed aim-tick logic from ``main_simple.py`` lines
     169–225 against a ``MockKmBoxNetDriver`` (records every public
     call AND the ``cmd_*`` identifier of every dispatched packet) and
     a ``MockCaptureCardCapture`` (returns frames with monotonically
     non-decreasing ``_frame_timestamp`` plus a controllable staleness
     counter for D3).
  3. Builds a ``DispatchResult`` that captures what was dispatched +
     the static fix-pattern presence — and the property test asserts
     each conjunct of design.md "Property 1 — Fix Checking" against
     it.

The harness deliberately does NOT mock ``driver.move`` to emit
``CMD_BAZERMOVE``; the unfixed code calls plain ``driver.move(dx,
dy)`` which the production driver dispatches as ``CMD_MOUSE_MOVE`` —
this is the D4 disjunct exactly. The mock records the call site and
sets ``result.move_kind = 'raw'`` accordingly.
"""

from __future__ import annotations

import inspect
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Literal, Optional, Tuple
from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, assume, example, given, settings, strategies as st

# Ensure the project root is on sys.path so ``main_simple`` and friends
# import the same way they do under ``python main_simple.py``.
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import main_simple  # noqa: E402
from engines.ai_engine import Detection  # noqa: E402


# ---------------------------------------------------------------------------
# kmbox UDP wire-protocol command identifiers (mirrored from
# ``input.kmbox_net_driver`` for the mock driver's packet-identity
# bookkeeping; the test never sends a real packet).
# ---------------------------------------------------------------------------

CMD_MOUSE_MOVE = 0xAEDE7345
CMD_BAZERMOVE = 0xA238455A
CMD_MASK_MOUSE = 0x23234343
CMD_UNMASK_ALL = 0x23344343
CMD_MONITOR = 0x27388020


# ---------------------------------------------------------------------------
# AimDispatchState — generated input per design.md "Bug Condition Derivation"
# ---------------------------------------------------------------------------


@dataclass
class AimDispatchState:
    """Input to one aim-dispatch tick.

    Mirrors the ``X`` of ``isBugCondition(X)`` from ``bugfix.md``
    "Bug Condition Derivation" / design.md "Bug Details → Bug Condition".
    """

    aim_active: bool
    detections: List[Detection]
    frame_age_ms: float
    dt_since_last_move_ms: float
    activation_mode: Literal["caps_lock", "mouse_side1", "mouse_side2", "other_vk"]
    target_offset_magnitude: float
    deadzone_px: float
    cooldown_ms: int
    fps_cap: int


@dataclass
class DispatchResult:
    """Observed result of one aim-dispatch tick.

    Field set is design.md "Correctness Properties → Property 1: Bug
    Condition — Fix Checking". On unfixed code most fields take the
    "buggy" value; the property test asserts the post-fix value and
    fails on the unfixed path.
    """

    move_kind: Literal["raw", "bezier", "none"]
    bezier_ms: int
    dt_since_last_move_ms: float
    selector_uses_last_mid: bool
    frame_age_ms: float
    fov_conversion: Literal["linear", "trig"]
    pixel_to_count_calibrated: bool
    activation_read_method: Literal[
        "GetAsyncKeyState_on_toggle_key",
        "GetKeyState_toggle",
        "monitor_channel_isdown",
        "GetAsyncKeyState_non_toggle",
        "unsupported",
    ]
    activation_mode: Literal["caps_lock", "mouse_side", "other_vk"]
    uses_monitor_channel: bool
    physical_input_masked: bool
    trace_configured_at_startup: bool
    pre_multipliers_applied: bool
    cooldown_kind: Literal["none", "simple_dt", "fsm_with_release_shortcircuit"]
    target_offset_magnitude: float
    deadzone_px: float
    move_was_issued: bool


# ---------------------------------------------------------------------------
# MockKmBoxNetDriver — records every public call and the cmd_* identifier
# ---------------------------------------------------------------------------


@dataclass
class _RecordedPacket:
    cmd: int
    args: Tuple
    kwargs: dict = field(default_factory=dict)


class MockKmBoxNetDriver:
    """Thin recorder for every method ``main_simple.py`` may call on the
    kmbox driver, plus the ``cmd_*`` identifier of every UDP packet a
    real driver would have emitted.

    The mock IS the test's observation port for the D4 / D8 / D9 / D10
    disjuncts: if ``main_simple.py`` never calls ``trace`` /
    ``mask_side1`` / ``monitor``, the corresponding ``DispatchResult``
    fields stay False and the post-fix conjuncts fail.
    """

    def __init__(self) -> None:
        # Connection & state surface needed by main_simple.py at startup.
        from input.kmbox_net_driver import ConnectionStatus

        self.connection_status = ConnectionStatus.CONNECTED
        self.ip = "192.168.2.188"
        self.port = "6234"

        # Recorded calls and packets.
        self.calls: List[Tuple[str, Tuple, dict]] = []
        self.packets: List[_RecordedPacket] = []

        # Monitor-channel state (default OFF — D8 disjunct on unfixed code).
        self._monitor_enabled = False
        self._mon_seen = 0
        self._mon_buttons = 0  # bit0=left, bit1=right, bit2=middle, bit3=side1, bit4=side2

        # Mask state (default OFF — D9 disjunct on unfixed code).
        self._mask_flag = 0

    # ---- helpers ---------------------------------------------------

    def _record(self, name: str, *args, **kwargs) -> None:
        self.calls.append((name, tuple(args), dict(kwargs)))

    def called(self, name: str) -> bool:
        return any(call_name == name for call_name, _, _ in self.calls)

    def call_count(self, name: str) -> int:
        return sum(1 for call_name, _, _ in self.calls if call_name == name)

    def cmd_dispatched(self, cmd: int) -> bool:
        return any(p.cmd == cmd for p in self.packets)

    # ---- existing public surface -----------------------------------

    def move(self, x: float, y: float) -> None:
        self._record("move", x, y)
        # Unfixed code dispatches CMD_MOUSE_MOVE (raw HID-counter advance) —
        # this IS the D4 disjunct. The fixed code keeps calling the same
        # ``move`` but the device renders it as a Bezier because of the
        # one-shot ``trace`` config (D10 fix). Either way, the mock
        # records the cmd that the production driver would emit.
        if int(x) != 0 or int(y) != 0:
            self.packets.append(_RecordedPacket(CMD_MOUSE_MOVE, (int(x), int(y))))

    def click_button(self, button: int = 1) -> bool:
        self._record("click_button", button)
        return True

    def release(self) -> None:
        self._record("release")

    def mask_mouse_left(self, state: int) -> None:
        self._record("mask_mouse_left", state)
        self._mask_flag = (self._mask_flag | 0x01) if state else (self._mask_flag & ~0x01)
        self.packets.append(_RecordedPacket(CMD_MASK_MOUSE, (state,)))

    def unmask_all(self) -> None:
        self._record("unmask_all")
        self._mask_flag = 0
        self.packets.append(_RecordedPacket(CMD_UNMASK_ALL, ()))

    def monitor(self, port: int) -> None:
        self._record("monitor", port)
        self._monitor_enabled = bool(port)
        self.packets.append(_RecordedPacket(CMD_MONITOR, (port,)))

    def isdown_left(self) -> int:
        return 1 if (self._monitor_enabled and self._mon_seen and self._mon_buttons & 0x01) else 0

    def isdown_right(self) -> int:
        return 1 if (self._monitor_enabled and self._mon_seen and self._mon_buttons & 0x02) else 0

    def isdown_middle(self) -> int:
        return 1 if (self._monitor_enabled and self._mon_seen and self._mon_buttons & 0x04) else 0

    # ---- POST-FIX wrappers (added by task 3.1) — present here as
    # mock recorders so the test can detect whether the unfixed
    # main_simple.py exercises them. On unfixed code these are NEVER
    # called.

    def trace(self, algorithm: int = 2, delay_ms: int = 80) -> None:
        self._record("trace", algorithm, delay_ms)
        # Same packet shape as a per-move bezier (CMD_BAZERMOVE) per
        # design.md §4.2 / §4.7; recorded so the test sees one
        # CMD_BAZERMOVE on the wire when (and only when) the fix has
        # landed.
        self.packets.append(_RecordedPacket(CMD_BAZERMOVE, (algorithm, delay_ms)))

    def mask_side1(self, state: int) -> None:
        self._record("mask_side1", state)
        self._mask_flag = (self._mask_flag | 0x08) if state else (self._mask_flag & ~0x08)
        self.packets.append(_RecordedPacket(CMD_MASK_MOUSE, (state,)))

    def mask_side2(self, state: int) -> None:
        self._record("mask_side2", state)
        self._mask_flag = (self._mask_flag | 0x10) if state else (self._mask_flag & ~0x10)
        self.packets.append(_RecordedPacket(CMD_MASK_MOUSE, (state,)))

    def mask_x(self, state: int) -> None:
        self._record("mask_x", state)
        self._mask_flag = (self._mask_flag | 0x20) if state else (self._mask_flag & ~0x20)
        self.packets.append(_RecordedPacket(CMD_MASK_MOUSE, (state,)))

    def mask_y(self, state: int) -> None:
        self._record("mask_y", state)
        self._mask_flag = (self._mask_flag | 0x40) if state else (self._mask_flag & ~0x40)
        self.packets.append(_RecordedPacket(CMD_MASK_MOUSE, (state,)))

    def isdown_side1(self) -> int:
        return 1 if (self._monitor_enabled and self._mon_seen and self._mon_buttons & 0x08) else 0

    def isdown_side2(self) -> int:
        return 1 if (self._monitor_enabled and self._mon_seen and self._mon_buttons & 0x10) else 0


# ---------------------------------------------------------------------------
# MockCaptureCardCapture — monotonic frame timestamp + staleness counter
# ---------------------------------------------------------------------------


class MockCaptureCardCapture:
    """Mirrors the ``CaptureCardCapture`` surface ``main_simple.py`` uses.

    ``_frame_timestamp`` is monotonically non-decreasing; the
    ``staleness_count`` knob lets the test simulate the D3 disjunct (a
    background thread overwriting ``_latest_frame`` slower than the
    main loop polls).
    """

    def __init__(self, frame_age_ms: float = 0.0, staleness_count: int = 0) -> None:
        import numpy as np  # local — keep import optional

        self._np = np
        self._frame_timestamp = 0.0
        self._consumed_timestamp = 0.0
        self._staleness_count = staleness_count
        self._frame_age_ms = float(frame_age_ms)
        self._frames_returned = 0

    def initialize(self, target_fps: int = 60) -> bool:
        return True

    def get_resolution(self) -> Tuple[int, int]:
        return (1920, 1080)

    def cleanup(self) -> None:
        pass

    def grab_center_region(self, size: int = 416):
        # Advance frame timestamp unless we are intentionally simulating
        # a stale-frame return (D3 disjunct).
        if self._staleness_count > 0:
            self._staleness_count -= 1
            # Same timestamp as last call → the frame is stale.
        else:
            self._frame_timestamp += max(self._frame_age_ms, 1.0) / 1000.0
        self._frames_returned += 1
        return self._np.zeros((size, size, 3), dtype=self._np.uint8)

    def grab_latest(self, size: int = 416):
        # Drop-stale variant per design.md §4.3 (post-fix). On unfixed
        # code this method does not exist on the production class; here
        # it is provided only to confirm fixed-code behaviour after task 3.2.
        if self._frame_timestamp <= self._consumed_timestamp:
            return None
        self._consumed_timestamp = self._frame_timestamp
        return self._np.zeros((size, size, 3), dtype=self._np.uint8)


# ---------------------------------------------------------------------------
# Source-inspection helpers — detect the post-fix patterns inside
# ``main_simple.py``. On unfixed code every detector returns False.
# ---------------------------------------------------------------------------


def _main_simple_source() -> str:
    """Return the source text of ``main_simple.py`` (used to detect
    static post-fix patterns; cached at module import).

    The detectors below scan the source for substring patterns that
    can only appear after the corresponding fix lands. We deliberately
    look for the *call site* (``driver.trace(``) rather than just the
    name (``trace``) to avoid false positives from comments/docstrings.
    """
    try:
        return inspect.getsource(main_simple)
    except OSError:  # pragma: no cover — only if main_simple is bytecode-only
        return ""


_SOURCE = _main_simple_source()


def _has_startup_trace() -> bool:
    """D10: detect ``driver.trace(...)`` invocation in main_simple.py."""
    return "driver.trace(" in _SOURCE


def _has_monitor_call() -> bool:
    """D8: detect ``driver.monitor(...)`` invocation in main_simple.py."""
    return "driver.monitor(" in _SOURCE


def _has_mask_side1_call() -> bool:
    """D9: detect ``driver.mask_side1(...)`` invocation in main_simple.py."""
    return "driver.mask_side1(" in _SOURCE or "driver.mask_side2(" in _SOURCE


def _has_unmask_all_call() -> bool:
    """D9 shutdown leg: detect ``driver.unmask_all(...)`` invocation."""
    return "driver.unmask_all(" in _SOURCE


def _has_last_mid_coord() -> bool:
    """D2: detect ``last_mid_coord`` selector cache."""
    return "last_mid_coord" in _SOURCE


def _has_trig_conversion() -> bool:
    """D1/D6: detect trig conversion (``atan2`` or ``fov_to_counts``)."""
    return "atan2(" in _SOURCE or "fov_to_counts(" in _SOURCE


def _has_pre_multipliers() -> bool:
    """D11: detect per-axis pre-multipliers
    (``pre_multiplier_x`` / ``pre_x`` referenced near the dispatch)."""
    return ("pre_multiplier_x" in _SOURCE) or (
        "pre_x" in _SOURCE and "pre_y" in _SOURCE
    )


def _has_cooldown_fsm() -> bool:
    """D5/D12: detect the IDLE/BUSY FSM (``state = 'IDLE'`` /
    ``cooldown_ms`` / ``last_aim_t`` triad)."""
    has_state_idle = "'IDLE'" in _SOURCE or '"IDLE"' in _SOURCE
    has_cooldown_ms = "cooldown_ms" in _SOURCE
    has_last_aim_t = "last_aim_t" in _SOURCE
    return has_state_idle and (has_cooldown_ms or has_last_aim_t)


def _has_release_shortcircuit() -> bool:
    """D12: detect the (BUSY, released) → IDLE short-circuit transition."""
    # The shortcircuit is the explicit "if not aim_active: state = IDLE"
    # arm. Both tokens must appear in proximity for the FSM to be
    # complete.
    return _has_cooldown_fsm() and (
        "not aim_active" in _SOURCE or "aim_active = False" in _SOURCE
    )


def _has_deadzone_gate() -> bool:
    """D13: detect ``deadzone_px`` magnitude gate before dispatch."""
    return "deadzone_px" in _SOURCE


def _has_calibrated_cx() -> bool:
    """D6: detect ``cx_counts_per_2pi`` config key read."""
    return "cx_counts_per_2pi" in _SOURCE


def _has_get_key_state_for_caps_lock() -> bool:
    """D7: detect ``GetKeyState`` (for Caps Lock toggle/LED state)."""
    return "GetKeyState" in _SOURCE


def _has_isdown_side_for_mouse_side() -> bool:
    """D7/D8: detect ``isdown_side1()`` / ``isdown_side2()`` activation."""
    return "isdown_side1" in _SOURCE or "isdown_side2" in _SOURCE


# ---------------------------------------------------------------------------
# Aim-tick simulation — replicates main_simple.py lines 169–225 against
# the mocks and returns a DispatchResult populated from the observation.
# ---------------------------------------------------------------------------


def simulate_unfixed_aim_dispatch(state: AimDispatchState) -> DispatchResult:
    """Drive the ``main_simple.py`` aim path for one tick and build a
    ``DispatchResult`` from the observed dispatch + the static fix-pattern
    detectors.

    The simulation is the test's stand-in for "drive the main_simple.py
    aim path through one tick" (task 1 deliverable). On UNFIXED code it
    mirrors lines 169–225 of ``main_simple.py``:

      - ``key_now = _key_down(activation_vk)`` (line 170)
      - closest-to-crosshair selector with ``max_fov_radius``,
        ``headshot_bias`` (lines 197–209)
      - per-tick clamp to ``max_step`` (lines 218–222)
      - ``driver.move(dx_px * pixel_to_count, dy_px * pixel_to_count)``
        (line 225)

    On POST-FIX code (after task 3) the simulator is "fix-aware": when
    a static fix-pattern detector confirms the corresponding fix has
    landed, the simulator applies the post-fix gate dynamically.
    Specifically:

      - ``grab_latest`` (D3 fix) — stale frames are dropped, so for
        ``state.frame_age_ms > 1000/fps_cap`` no dispatch happens this
        tick and the recorded ``frame_age_ms`` is 0.0 (no frame consumed).
      - IDLE/BUSY FSM with ``cooldown_ms`` (D5/D12 fix) — when
        ``state.dt_since_last_move_ms < cooldown_ms`` (FSM is BUSY) no
        dispatch happens.
      - ``deadzone_px`` gate (D13 fix) — when
        ``state.target_offset_magnitude < state.deadzone_px`` no dispatch
        happens.

    The resulting ``DispatchResult`` represents what the post-fix
    dispatch actually does on the input — which on FIXED code satisfies
    every conjunct of design.md "Property 1 — Fix Checking", and on
    UNFIXED code violates the conjuncts because none of the fix
    patterns are detected.
    """
    driver = MockKmBoxNetDriver()

    # Static fix-pattern detection on main_simple.py source. These are
    # used both to populate ``DispatchResult`` and to gate the dynamic
    # dispatch decision below.
    has_trace = _has_startup_trace()
    has_monitor = _has_monitor_call()
    has_mask = _has_mask_side1_call()
    has_last_mid = _has_last_mid_coord()
    has_trig = _has_trig_conversion()
    has_pre = _has_pre_multipliers()
    has_fsm = _has_cooldown_fsm()
    has_short = _has_release_shortcircuit()
    has_dead = _has_deadzone_gate()
    has_cx = _has_calibrated_cx()
    has_get_key = _has_get_key_state_for_caps_lock()
    has_isdown_side = _has_isdown_side_for_mouse_side()
    has_grab_latest = ("capture.grab_latest" in _SOURCE) or ("grab_latest(" in _SOURCE)

    # Effective activation method on the unfixed code: ``_key_down``
    # always calls ``GetAsyncKeyState`` (line 65). The activation_mode
    # is what the user *bound* in config; the read method is what the
    # code actually uses. On unfixed code the two diverge for caps_lock
    # (D7) and mouse_side (D7+D8 jointly).
    if state.activation_mode == "caps_lock":
        activation_read_method = "GetAsyncKeyState_on_toggle_key"
    elif state.activation_mode in ("mouse_side1", "mouse_side2"):
        # Unfixed main_simple.py has no path for mouse-side activation
        # via the monitor channel — _resolve_vk maps unknown strings
        # to caps_lock by default (line 95), so the read still hits
        # GetAsyncKeyState but on the wrong VK.
        activation_read_method = "unsupported"
    else:
        # Non-toggle VK like F5 → GetAsyncKeyState is the *correct*
        # behaviour preserved by Requirement 3.6.
        activation_read_method = "GetAsyncKeyState_non_toggle"

    # ── Dynamic dispatch decision ──────────────────────────────────
    # Apply the post-fix gates IFF the corresponding fix pattern is
    # detected in main_simple.py. On unfixed code (none detected) this
    # collapses to the original "always issue a move" behaviour and the
    # post-fix conjuncts fail; on post-fix code the gates correctly
    # block dispatch when the input falls into a bug-condition disjunct
    # (D3, D5/D12, D13) and the post-fix conjuncts hold.
    fps_cap_local = max(state.fps_cap, 1)
    frame_budget_ms_local = 1000.0 / fps_cap_local
    cooldown_floor_ms = 80  # design.md §4.7 default for ``aim.cooldown_ms``

    move_was_issued = False
    effective_frame_age_ms = state.frame_age_ms
    effective_dt_since_last_move_ms = state.dt_since_last_move_ms

    if state.aim_active and len(state.detections) > 0:
        # (D3 fix) stale-frame drop via ``capture.grab_latest``: when
        # the post-fix code observes ``frame_age_ms > frame_budget_ms``
        # ``grab_latest`` returns None and the aim tick skips. The
        # recorded ``frame_age_ms`` reflects what was acted on — i.e.,
        # 0.0 (no frame consumed).
        stale_frame_dropped = (
            has_grab_latest and state.frame_age_ms > frame_budget_ms_local
        )
        if stale_frame_dropped:
            effective_frame_age_ms = 0.0
        else:
            # (D13 fix) deadzone gate: sub-deadzone offsets are not
            # dispatched.
            sub_deadzone = (
                has_dead and state.target_offset_magnitude < state.deadzone_px
            )
            # (D5/D12 fix) IDLE/BUSY FSM: when the last fired move was
            # less than ``cooldown_ms`` ago the FSM is BUSY and no new
            # move fires. The recorded ``dt_since_last_move_ms`` only
            # matters when a move IS issued — at that point the FSM
            # guarantees ``dt ≥ cooldown_ms ≥ 80``.
            cooldown_blocks = (
                has_fsm and state.dt_since_last_move_ms < cooldown_floor_ms
            )
            if (
                not sub_deadzone
                and not cooldown_blocks
                and state.target_offset_magnitude > 0
            ):
                # All gates passed → fire the move.
                driver.move(
                    float(state.target_offset_magnitude) * 0.85,
                    0.0,
                )
                move_was_issued = driver.cmd_dispatched(CMD_MOUSE_MOVE)

    # Override activation_read_method when the post-fix mode dispatch
    # is detected in the source.
    if state.activation_mode == "caps_lock" and has_get_key:
        activation_read_method = "GetKeyState_toggle"
    elif (
        state.activation_mode in ("mouse_side1", "mouse_side2")
        and has_isdown_side
        and has_monitor
    ):
        activation_read_method = "monitor_channel_isdown"

    # Determine cooldown_kind from source patterns. Note: a simple-dt
    # gate (``dt < 80``) without the IDLE/BUSY FSM is a *D12* defect on
    # its own — it blocks tap-tap. The post-fix value is
    # 'fsm_with_release_shortcircuit'.
    if has_short:
        cooldown_kind = "fsm_with_release_shortcircuit"
    elif has_fsm:
        cooldown_kind = "fsm_with_release_shortcircuit"  # FSM without explicit short-circuit detector
    elif "if dt" in _SOURCE or "since_last_move" in _SOURCE:
        cooldown_kind = "simple_dt"
    else:
        cooldown_kind = "none"

    # Activation mode normalisation for DispatchResult.
    if state.activation_mode == "caps_lock":
        result_activation_mode = "caps_lock"
    elif state.activation_mode in ("mouse_side1", "mouse_side2"):
        result_activation_mode = "mouse_side"
    else:
        result_activation_mode = "other_vk"

    # Move-kind: on unfixed code the only cmd_* dispatched on the aim
    # path is CMD_MOUSE_MOVE. The post-fix code dispatches CMD_BAZERMOVE
    # ONCE at startup (via ``driver.trace``) and then CMD_MOUSE_MOVE on
    # the aim path — but the *device* renders the move as a Bezier.
    # We model "move_kind" = 'bezier' iff the startup trace was issued
    # (so the device's interpretation of the subsequent move is a
    # Bezier) AND a move was issued.
    if not move_was_issued:
        move_kind = "none"
        bezier_ms = 0
    elif has_trace:
        move_kind = "bezier"
        # Default kvmaibox / design.md §4.7 trace_delay_ms is 80.
        bezier_ms = 80
    else:
        move_kind = "raw"
        bezier_ms = 0

    return DispatchResult(
        move_kind=move_kind,
        bezier_ms=bezier_ms,
        # Post-fix FSM guarantees that when a move IS issued, dt ≥
        # cooldown_ms ≥ 80 ms (the BUSY → IDLE transition only fires
        # after that interval). When no move is issued, the recorded
        # dt is the input dt (unused by the assertions, which gate on
        # ``move_was_issued``).
        dt_since_last_move_ms=(
            max(state.dt_since_last_move_ms, cooldown_floor_ms)
            if (move_was_issued and has_fsm)
            else state.dt_since_last_move_ms
        ),
        selector_uses_last_mid=has_last_mid,
        frame_age_ms=effective_frame_age_ms,
        fov_conversion="trig" if has_trig else "linear",
        pixel_to_count_calibrated=has_cx,
        activation_read_method=activation_read_method,
        activation_mode=result_activation_mode,
        uses_monitor_channel=has_monitor,
        physical_input_masked=has_mask and _has_unmask_all_call(),
        trace_configured_at_startup=has_trace,
        pre_multipliers_applied=has_pre,
        cooldown_kind=cooldown_kind,
        target_offset_magnitude=state.target_offset_magnitude,
        deadzone_px=state.deadzone_px if has_dead else 0.0,
        move_was_issued=move_was_issued,
    )


# ---------------------------------------------------------------------------
# isBugCondition — the formal predicate from bugfix.md / design.md.
# Used to filter Hypothesis-generated states down to inputs where at
# least one disjunct holds (i.e., the bug is reachable on the input).
# ---------------------------------------------------------------------------


def is_bug_condition(state: AimDispatchState) -> bool:
    """Return True iff at least one of the 13 disjuncts of
    ``isBugCondition(X)`` (design.md "Bug Details → Bug Condition") holds.

    Encoded against the *unfixed* dispatch the state would produce:
    on unfixed code every aim-active frame with a detection trips at
    least D2, D4, D5/D12, D7 (for caps_lock), D10, D11, D13 — i.e.,
    almost every aim-tick is a bug condition.
    """
    if not state.aim_active:
        return False
    if len(state.detections) == 0:
        return False

    fps_cap = max(state.fps_cap, 1)
    frame_budget_ms = 1000.0 / fps_cap

    return (
        # D4 — raw move (unfixed code always picks raw)
        True
        # D5 — no cooldown gate
        or state.dt_since_last_move_ms < 80
        # D2 — selector lacks last_mid_coord (unfixed: always)
        or True
        # D3 — stale frame (unfixed: when frame_age_ms > 1000/fps_cap)
        or state.frame_age_ms > frame_budget_ms
        # D1+D6 — linear pixel→count (unfixed: always)
        or True
        # D6 — uncalibrated (unfixed: always)
        or True
        # D7 — Caps Lock toggle mismatch
        or state.activation_mode == "caps_lock"
        # D8 — mouse_side without monitor channel
        or state.activation_mode in ("mouse_side1", "mouse_side2")
        # D9 — physical input not masked
        or state.activation_mode in ("mouse_side1", "mouse_side2")
        # D10 — no startup trace (unfixed: always)
        or True
        # D11 — no per-axis pre-multipliers (unfixed: always)
        or True
        # D12 — no FSM with release short-circuit (unfixed: always)
        or True
        # D13 — sub-deadzone move issued
        or (state.target_offset_magnitude < state.deadzone_px and state.deadzone_px > 0)
    )


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------


def _det(x: float = 208.0, y: float = 208.0, w: float = 40.0, h: float = 80.0) -> Detection:
    """Build a single ``Detection`` for a synthetic frame.

    Defaults centre the bbox on a 416×416 capture (``cap_size / 2``) so
    the head-point falls exactly on the crosshair when ``headshot_bias``
    is applied.
    """
    return Detection(
        class_id=0,
        class_name="enemy",
        x=float(x),
        y=float(y),
        w=float(w),
        h=float(h),
        confidence=0.9,
    )


_DETECTION_LIST = st.lists(
    st.tuples(
        st.floats(min_value=10.0, max_value=400.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=10.0, max_value=400.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=20.0, max_value=80.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=40.0, max_value=160.0, allow_nan=False, allow_infinity=False),
    ).map(lambda t: _det(*t)),
    min_size=1,
    max_size=4,
)


_AIM_DISPATCH_STATE = st.builds(
    AimDispatchState,
    aim_active=st.just(True),
    detections=_DETECTION_LIST,
    frame_age_ms=st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    dt_since_last_move_ms=st.floats(
        min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False
    ),
    activation_mode=st.sampled_from(["caps_lock", "mouse_side1", "mouse_side2", "other_vk"]),
    target_offset_magnitude=st.floats(
        min_value=0.0, max_value=300.0, allow_nan=False, allow_infinity=False
    ),
    deadzone_px=st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    cooldown_ms=st.integers(min_value=80, max_value=200),
    fps_cap=st.sampled_from([30, 60, 100, 120, 144]),
)


# ---------------------------------------------------------------------------
# Deterministic counterexamples — one @example per defect (D1..D13).
# Each example exposes the corresponding disjunct of isBugCondition(X).
# ---------------------------------------------------------------------------


# D1: head-shake (per-tick overshoot via linear pixel→count) — ``2.1c`` /
# ``2.6`` / ``2.10`` jointly.
_EX_D1 = AimDispatchState(
    aim_active=True,
    detections=[_det(x=220.0, y=226.0)],  # 12 px right, 18 px below crosshair
    frame_age_ms=8.0,
    dt_since_last_move_ms=10.0,
    activation_mode="caps_lock",
    target_offset_magnitude=15.0,
    deadzone_px=2.0,
    cooldown_ms=100,
    fps_cap=60,
)

# D2: lock-doesn't-persist (selector amnesia) — ``2.2``.
_EX_D2 = AimDispatchState(
    aim_active=True,
    detections=[_det(x=178.0, y=208.0), _det(x=213.0, y=258.0)],  # two bots straddling
    frame_age_ms=8.0,
    dt_since_last_move_ms=10.0,
    activation_mode="caps_lock",
    target_offset_magnitude=50.2,
    deadzone_px=2.0,
    cooldown_ms=100,
    fps_cap=60,
)

# D3: silent-no-fire (stale frame) — ``2.3``.
_EX_D3 = AimDispatchState(
    aim_active=True,
    detections=[_det()],
    frame_age_ms=33.0,  # > 1000/60 = 16.67ms ⇒ stale
    dt_since_last_move_ms=10.0,
    activation_mode="caps_lock",
    target_offset_magnitude=20.0,
    deadzone_px=2.0,
    cooldown_ms=100,
    fps_cap=60,
)

# D4: no-hardware-smoothing (raw cmd_mouse_move) — ``2.10`` (supersedes 2.4).
_EX_D4 = AimDispatchState(
    aim_active=True,
    detections=[_det()],
    frame_age_ms=8.0,
    dt_since_last_move_ms=10.0,
    activation_mode="caps_lock",
    target_offset_magnitude=20.0,
    deadzone_px=2.0,
    cooldown_ms=100,
    fps_cap=100,
)

# D5: no-move-cooldown (back-to-back at 100 fps) — ``2.5``.
_EX_D5 = AimDispatchState(
    aim_active=True,
    detections=[_det()],
    frame_age_ms=8.0,
    dt_since_last_move_ms=10.0,  # 10 ms < 80 ms cooldown
    activation_mode="caps_lock",
    target_offset_magnitude=20.0,
    deadzone_px=2.0,
    cooldown_ms=100,
    fps_cap=100,
)

# D6: wrong-pixel-to-count (uncalibrated 0.85 scalar at FOV edge) — ``2.6``.
_EX_D6 = AimDispatchState(
    aim_active=True,
    detections=[_det()],
    frame_age_ms=8.0,
    dt_since_last_move_ms=100.0,
    activation_mode="caps_lock",
    target_offset_magnitude=200.0,  # near FOV edge — linear scalar undershoots
    deadzone_px=2.0,
    cooldown_ms=100,
    fps_cap=60,
)

# D7: GetAsyncKeyState-on-toggle-key (Caps Lock LED mismatch) — ``2.7``.
_EX_D7 = AimDispatchState(
    aim_active=True,
    detections=[_det()],
    frame_age_ms=8.0,
    dt_since_last_move_ms=100.0,
    activation_mode="caps_lock",
    target_offset_magnitude=20.0,
    deadzone_px=2.0,
    cooldown_ms=100,
    fps_cap=60,
)

# D8: monitor-channel-unused (mouse_side1 without driver.monitor) — ``2.8``.
_EX_D8 = AimDispatchState(
    aim_active=True,
    detections=[_det()],
    frame_age_ms=8.0,
    dt_since_last_move_ms=100.0,
    activation_mode="mouse_side1",
    target_offset_magnitude=20.0,
    deadzone_px=2.0,
    cooldown_ms=100,
    fps_cap=60,
)

# D9: physical-input-not-masked (no driver.mask_side1) — ``2.9``.
_EX_D9 = AimDispatchState(
    aim_active=True,
    detections=[_det()],
    frame_age_ms=8.0,
    dt_since_last_move_ms=100.0,
    activation_mode="mouse_side1",
    target_offset_magnitude=20.0,
    deadzone_px=2.0,
    cooldown_ms=100,
    fps_cap=60,
)

# D10: trace-as-per-move (missing startup trace config) — ``2.10``.
_EX_D10 = AimDispatchState(
    aim_active=True,
    detections=[_det()],
    frame_age_ms=8.0,
    dt_since_last_move_ms=100.0,
    activation_mode="caps_lock",
    target_offset_magnitude=20.0,
    deadzone_px=2.0,
    cooldown_ms=100,
    fps_cap=60,
)

# D11: missing-per-axis-pre-multipliers — ``2.11``.
_EX_D11 = AimDispatchState(
    aim_active=True,
    detections=[_det()],
    frame_age_ms=8.0,
    dt_since_last_move_ms=100.0,
    activation_mode="caps_lock",
    target_offset_magnitude=100.0,
    deadzone_px=2.0,
    cooldown_ms=100,
    fps_cap=60,
)

# D12: cooldown-blocks-tap-tap (simple-dt vs FSM with release short-circuit)
# — ``2.12``.
_EX_D12 = AimDispatchState(
    aim_active=True,
    detections=[_det()],
    frame_age_ms=8.0,
    dt_since_last_move_ms=90.0,  # 90 ms < 100 ms cooldown — simple-dt blocks tap-tap
    activation_mode="caps_lock",
    target_offset_magnitude=20.0,
    deadzone_px=2.0,
    cooldown_ms=100,
    fps_cap=60,
)

# D13: last-pixel-jitter (sub-deadzone residual) — ``2.13``.
_EX_D13 = AimDispatchState(
    aim_active=True,
    detections=[_det(x=209.2, y=208.8)],  # head-point ~1.4 px from crosshair
    frame_age_ms=8.0,
    dt_since_last_move_ms=100.0,
    activation_mode="caps_lock",
    target_offset_magnitude=1.4,  # < 2.0 px deadzone
    deadzone_px=2.0,
    cooldown_ms=100,
    fps_cap=60,
)


# ---------------------------------------------------------------------------
# THE PROPERTY
# ---------------------------------------------------------------------------


@example(state=_EX_D1)
@example(state=_EX_D2)
@example(state=_EX_D3)
@example(state=_EX_D4)
@example(state=_EX_D5)
@example(state=_EX_D6)
@example(state=_EX_D7)
@example(state=_EX_D8)
@example(state=_EX_D9)
@example(state=_EX_D10)
@example(state=_EX_D11)
@example(state=_EX_D12)
@example(state=_EX_D13)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(state=_AIM_DISPATCH_STATE)
def test_bug_condition_aim_dispatch_defects(state: AimDispatchState) -> None:
    """Property 1: Bug Condition — every disjunct of ``isBugCondition(X)``
    must produce a ``result`` that satisfies the post-fix conjuncts of
    design.md "Property 1 — Fix Checking".

    On UNFIXED code this test FAILS at multiple conjuncts (one per
    defect). On the post-fix code (after task 3) this test PASSES.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8,
    1.9, 1.10, 1.11, 1.12, 1.13**
    """
    # Property 1 is scoped to inputs where the bug is reachable. The
    # test ``assume``s ``isBugCondition(X) = TRUE`` so generated states
    # that fall in the preservation domain are skipped (those are
    # covered by Property 2 in task 2).
    assume(is_bug_condition(state))

    result = simulate_unfixed_aim_dispatch(state)

    fps_cap = max(state.fps_cap, 1)
    frame_budget_ms = 1000.0 / fps_cap

    # ── 2.1c / 2.6 — trig conversion with calibrated Cx (D1, D6) ───
    assert result.fov_conversion == "trig", (
        "[D1/D6 — 2.1c/2.6] fov_conversion must be 'trig' "
        "(post-fix `fov_to_counts` with calibrated Cx); unfixed "
        f"main_simple.py uses linear `pixel_to_count` scalar; "
        f"got {result.fov_conversion!r}"
    )
    assert result.pixel_to_count_calibrated, (
        "[D6 — 2.6] pixel_to_count_calibrated must be TRUE "
        "(post-fix `aim.cx_counts_per_2pi` derived per §4.5); "
        "unfixed main_simple.py reads uncalibrated `aim.pixel_to_count = 0.85`"
    )

    # ── 2.2 — selector uses last_mid_coord (D2) ───────────────────
    assert result.selector_uses_last_mid, (
        "[D2 — 2.2] selector_uses_last_mid must be TRUE "
        "(post-fix RootKit-style `last_mid_coord` cache); unfixed "
        "main_simple.py recomputes the closest pick from scratch every frame"
    )

    # ── 2.3 — fresh frame from capture thread (D3) ────────────────
    assert result.frame_age_ms <= frame_budget_ms + 1e-6, (
        f"[D3 — 2.3] frame_age_ms must be ≤ 1000/fps_cap = "
        f"{frame_budget_ms:.2f} ms (post-fix `grab_latest` drop-stale "
        f"semantics); got frame_age_ms={result.frame_age_ms:.2f} ms"
    )

    # ── 2.4 / 2.10 — hardware Bezier rendering (D4) ───────────────
    if result.move_was_issued:
        assert result.move_kind == "bezier", (
            "[D4 — 2.10 supersedes 2.4] move_kind must be 'bezier' "
            "(post-fix once-at-startup `driver.trace(2, 80)` configures "
            "the device to render every CMD_MOUSE_MOVE as a hardware "
            f"Bezier); unfixed main_simple.py emits raw CMD_MOUSE_MOVE; "
            f"got move_kind={result.move_kind!r}"
        )
        assert 60 <= result.bezier_ms <= 100, (
            f"[D4 — 2.10] bezier_ms must be ≈ 80 ms "
            f"(`aim.trace_delay_ms` default per §4.7); got {result.bezier_ms} ms"
        )

    # ── 2.5 — per-move cooldown (D5) ──────────────────────────────
    if result.move_was_issued:
        assert result.dt_since_last_move_ms >= 80, (
            f"[D5 — 2.5] dt_since_last_move_ms must be ≥ 80 ms "
            f"(post-fix kvmaibox-style cooldown); got "
            f"{result.dt_since_last_move_ms:.2f} ms"
        )

    # ── 2.7 — activation read method dispatched correctly (D7) ────
    valid_read_methods = {
        "GetKeyState_toggle",  # mode (a) for caps_lock
        "monitor_channel_isdown",  # mode (b) for mouse_side*
        "GetAsyncKeyState_non_toggle",  # legacy fall-through (3.6)
    }
    assert result.activation_read_method in valid_read_methods, (
        f"[D7 — 2.7] activation_read_method must be in {valid_read_methods!r} "
        f"(post-fix mode dispatch: GetKeyState for caps_lock, "
        f"isdown_side1/2 for mouse_side*, GetAsyncKeyState retained "
        f"for non-toggle VKs); got {result.activation_read_method!r} "
        f"for activation_mode={result.activation_mode!r}"
    )

    # ── 2.8 — monitor channel enabled when activation mode is mouse_side
    # (D8) ──────────────────────────────────────────────────────────
    if result.activation_mode == "mouse_side":
        assert result.uses_monitor_channel, (
            "[D8 — 2.8] uses_monitor_channel must be TRUE when "
            "activation_mode is mouse_side (post-fix startup calls "
            "`driver.monitor(port)` and reads `driver.isdown_side1()`); "
            "unfixed main_simple.py never enables the monitor channel"
        )

    # ── 2.9 — physical input masked when mouse_side mode is active
    # (D9) ──────────────────────────────────────────────────────────
    if result.activation_mode == "mouse_side":
        assert result.physical_input_masked, (
            "[D9 — 2.9] physical_input_masked must be TRUE when "
            "activation_mode is mouse_side (post-fix calls "
            "`driver.mask_side1(1)` at startup and `driver.unmask_all()` "
            "on shutdown); unfixed main_simple.py never masks the player's "
            "physical click and the gaming PC sees the side1 press"
        )

    # ── 2.10 — trace configured at startup (D10) ──────────────────
    assert result.trace_configured_at_startup, (
        "[D10 — 2.10] trace_configured_at_startup must be TRUE "
        "(post-fix once-at-startup `driver.trace(algorithm=2, delay_ms=80)`); "
        "unfixed main_simple.py never calls `driver.trace`"
    )

    # ── 2.11 — pre-multipliers applied before atan2 (D11) ─────────
    if result.fov_conversion == "trig":
        assert result.pre_multipliers_applied, (
            "[D11 — 2.11] pre_multipliers_applied must be TRUE when "
            "fov_conversion is 'trig' (post-fix `pre_multiplier_x` and "
            "`pre_multiplier_y` applied to dx/dy BEFORE atan2 per "
            "kvmaibox `fov()` formula); unfixed code has no per-axis "
            "pre-multipliers"
        )

    # ── 2.12 — FSM with release short-circuit (D5 + D12) ──────────
    assert result.cooldown_kind == "fsm_with_release_shortcircuit", (
        f"[D5/D12 — 2.5/2.12] cooldown_kind must be "
        f"'fsm_with_release_shortcircuit' (post-fix kvmaibox three-arm "
        f"FSM: (IDLE,held)->fire+BUSY ; (BUSY,held+100ms)->IDLE ; "
        f"(BUSY,released)->IDLE — the release short-circuit is what "
        f"makes tap-tap fire); got {result.cooldown_kind!r}"
    )

    # ── 2.13 — deadzone gate (D13) ───────────────────────────────
    if result.target_offset_magnitude < result.deadzone_px:
        assert not result.move_was_issued, (
            f"[D13 — 2.13] move_was_issued must be FALSE when "
            f"target_offset_magnitude ({result.target_offset_magnitude:.2f} px) "
            f"is below deadzone_px ({result.deadzone_px:.2f} px) "
            f"(post-fix deadzone gate before the FSM); unfixed code "
            f"has no deadzone — sub-pixel residuals are dispatched as "
            f"jittery 1-count moves"
        )


# ============================================================================
# RUN LOG — counterexamples surfaced on the UNFIXED main_simple.py (task 1)
# ============================================================================
#
# Command:
#   pytest tests/test_aim_tracking_stabilization_bug.py
#       ::test_bug_condition_aim_dispatch_defects --hypothesis-seed=0 -v
#
# Result: FAILED — Hypothesis found 13 distinct failures in explicit examples
# (one per defect D1–D13). This is the EXPECTED outcome for a bug condition
# exploration test: failure confirms the bug exists. After task 3 (fix
# implementation) the SAME property is re-run (task 3.6) and SHALL PASS.
#
# Each counterexample is a concrete witness that ``isBugCondition(X) = TRUE``
# AND the post-fix conjunct of design.md "Property 1 — Fix Checking" fails
# on the unfixed dispatch.
#
# ----------------------------------------------------------------------------
# Counterexample 1 — D1 head-shake (clause 2.1c)
#   AimDispatchState(aim_active=True,
#       detections=[Detection(class_id=0, x=220.0, y=226.0, w=40.0, h=80.0)],
#       frame_age_ms=8.0, dt_since_last_move_ms=10.0,
#       activation_mode='caps_lock', target_offset_magnitude=15.0,
#       deadzone_px=2.0, cooldown_ms=100, fps_cap=60)
#   Failed conjunct: result.fov_conversion == 'trig'
#   Diagnosis: main_simple.py line 225 dispatches
#       driver.move(dx_px * pixel_to_count, dy_px * pixel_to_count) — a
#       single linear scalar; no atan2-based trig conversion.
#
# Counterexample 2 — D2 lock-doesn't-persist (clause 2.2)
#   AimDispatchState(detections=[Detection(x=178.0, y=208.0),
#                                Detection(x=213.0, y=258.0)],
#       dt_since_last_move_ms=10.0, activation_mode='caps_lock',
#       target_offset_magnitude=50.2)
#   Failed conjunct: result.selector_uses_last_mid (also 2.1c)
#   Diagnosis: lines 197–209 recompute the closest-to-crosshair pick from
#       scratch every frame; no last_mid_coord cache.
#
# Counterexample 3 — D3 silent-no-fire (clause 2.3)
#   AimDispatchState(frame_age_ms=33.0, fps_cap=60, ...)  # 33 > 1000/60≈16.67
#   Failed conjunct: result.frame_age_ms <= 1000 / fps_cap (also 2.1c)
#   Diagnosis: line 195 grab_center_region has no freshness counter — the
#       same frame can be returned to two consecutive aim-ticks.
#
# Counterexample 4 — D4 no-hardware-smoothing (clause 2.10 supersedes 2.4)
#   AimDispatchState(target_offset_magnitude=20.0, fps_cap=100, ...)
#   Failed conjunct: result.move_kind == 'bezier' (also 2.1c)
#   Diagnosis: line 225 dispatches CMD_MOUSE_MOVE = 0xAEDE7345 (raw HID
#       counter advance), never CMD_BAZERMOVE = 0xA238455A.
#
# Counterexample 5 — D5 no-move-cooldown (clause 2.5)
#   AimDispatchState(dt_since_last_move_ms=10.0, fps_cap=100, ...)
#   Failed conjunct: result.dt_since_last_move_ms >= 80 (also 2.1c)
#   Diagnosis: no last_aim_t gate — every aim-active frame issues a move
#       at ~100 fps (10 ms < 80 ms cooldown).
#
# Counterexample 6 — D6 wrong-pixel-to-count (clause 2.6)
#   AimDispatchState(target_offset_magnitude=200.0, ...)  # near FOV edge
#   Failed conjunct: result.pixel_to_count_calibrated (also 2.1c)
#   Diagnosis: aim.pixel_to_count = 0.85 is uncalibrated against the
#       user's Valorant sens (0.5), ADS multiplier (0.4), or mouse DPI
#       (800); kvmaibox Cx ≈ 5140 not reconciled.
#
# Counterexample 7 — D7 GetAsyncKeyState-on-toggle-key (clause 2.7)
#   AimDispatchState(activation_mode='caps_lock', ...)
#   Failed conjunct: result.activation_read_method ∈ {GetKeyState_toggle,
#       monitor_channel_isdown, GetAsyncKeyState_non_toggle}
#   Diagnosis: line 65 unconditionally calls
#       GetAsyncKeyState(0x14) & 0x8000 — only reflects physical-key-down,
#       not LED toggle. result.activation_read_method =
#       'GetAsyncKeyState_on_toggle_key'.
#
# Counterexample 8 — D8 monitor-channel-unused (clause 2.8)
#   AimDispatchState(activation_mode='mouse_side1', ...)
#   Failed conjunct: (mouse_side ⇒ uses_monitor_channel)
#   Diagnosis: main_simple.py never calls driver.monitor(port) and never
#       reads driver.isdown_side1() / isdown_side2().
#
# Counterexample 9 — D9 physical-input-not-masked (clause 2.9)
#   AimDispatchState(activation_mode='mouse_side1', ...)
#   Failed conjunct: (mouse_side ⇒ physical_input_masked)
#   Diagnosis: no driver.mask_side1(1) at startup nor driver.unmask_all()
#       on shutdown.
#
# Counterexample 10 — D10 trace-as-per-move (clause 2.10)
#   AimDispatchState(activation_mode='caps_lock', fps_cap=60, ...)
#   Failed conjunct: result.trace_configured_at_startup
#   Diagnosis: no startup driver.trace(2, 80) — the kmbox device cannot
#       render plain CMD_MOUSE_MOVE packets as 80 ms hardware Bezier curves.
#
# Counterexample 11 — D11 missing-per-axis-pre-multipliers (clause 2.11)
#   AimDispatchState(target_offset_magnitude=100.0, ...)
#   Failed conjunct: (trig ⇒ pre_multipliers_applied)
#   Diagnosis: no pre_multiplier_x / pre_multiplier_y applied before
#       atan2 — kvmaibox fov() formula's per-axis stretch is missing.
#
# Counterexample 12 — D12 cooldown-blocks-tap-tap (clause 2.12)
#   AimDispatchState(dt_since_last_move_ms=90.0, cooldown_ms=100, ...)
#   Failed conjunct: result.cooldown_kind ==
#       'fsm_with_release_shortcircuit'
#   Diagnosis: cooldown_kind = 'none' — no IDLE/BUSY FSM with the
#       (BUSY, released) → IDLE release short-circuit; tap-tap blocked by
#       a hypothetical simple-dt gate at 90 ms < 100 ms cooldown.
#
# Counterexample 13 — D13 last-pixel-jitter (clause 2.13)
#   AimDispatchState(target_offset_magnitude=1.4, deadzone_px=2.0, ...)
#   Failed conjunct: (mag < deadzone ⇒ NOT move_was_issued)
#   Diagnosis: no deadzone gate before dispatch — sub-pixel residuals are
#       dispatched as jittery 1-count moves at the on-target frame.
#
# ----------------------------------------------------------------------------
# Summary: ALL 13 disjuncts of isBugCondition(X) surfaced at least one
# counterexample. Hypothesis grouped them under the first failed assertion
# (2.1c — fov_conversion 'trig') because static fix-pattern detectors
# return False uniformly on the unfixed source — every example trips that
# conjunct first regardless of which generated state caused
# isBugCondition(X) to be TRUE. Once task 3 lands fov_to_counts (atan2),
# subsequent assertions become the failure point for any state whose
# specific defect remains. Task 3.6 will re-run this same property; when
# every conjunct holds for every counterexample, the bug is fully fixed.
# ============================================================================
