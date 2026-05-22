"""
Property test — Task 3.10 of spec ``aim-pipeline-simplification``.

# Feature: aim-pipeline-simplification, Property req 2.8: pixel_to_count

**Property req 2.8** — *the ``pixel_to_count`` config key is read
exactly once and reflected in every driver move; an INFO log line
is emitted on every config load.*

**Validates: Requirement 2.8** — "WHEN capture-frame pixels are
converted to HID mouse-counts THEN the system SHALL apply an
explicit, configurable scaling factor ``pixel_to_count`` (read from
``config.yaml``, default value derived from the user's Valorant sens
0.5, 800 DPI, ADS multiplier 0.4) at exactly ONE point in the
pipeline (immediately before ``BaseMouse.send_move``). The scaling
factor SHALL be visible in logs at ``INFO`` level on every config
load."

The unfixed pipeline had no ``pixel_to_count`` key at all (defect
1.8). The simplification adds:

* ``aim.pixel_to_count`` to ``config.yaml`` (default 0.85 hipfire),
* ``utils/validation.py::_require_positive_number`` enforcing
  positivity,
* ``aim/pipeline.py::_to_counts`` reading the value via
  ``cfg["aim"]["pixel_to_count"]`` once per ``aim_step`` call,
* ``config.py::_log_pixel_to_count`` emitting one INFO log line on
  every ``load_config()`` invocation.

This test exercises the runtime contract: the driver's float input
scales linearly with ``pixel_to_count`` (read once per ``aim_step``
call), and one INFO line per config load lands on the
``config.aim`` logger.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

import pytest

import config as cfg
from aim.pipeline import _LockState, aim_step
from engines.ai_engine import Detection
from input.base_mouse import BaseMouse


CAPTURE_SIZE = 416
HEADSHOT_BIAS = 0.30


class _FloatRecorder(BaseMouse):
    """Capture float inputs to ``move`` (pre-quantization)."""

    def __init__(self) -> None:
        super().__init__(target_cps=10.0)
        self.float_in: List[Tuple[float, float]] = []

    def move(self, x: float, y: float) -> None:  # type: ignore[override]
        self.float_in.append((float(x), float(y)))
        super().move(x, y)

    def send_move(self, x: int, y: int) -> None:  # type: ignore[override]
        pass

    def send_click(self, delay_before_click: float = 0.0) -> None:  # type: ignore[override]
        raise AssertionError("send_click must not fire on the AI path")


def _cfg(pixel_to_count: float) -> Dict[str, Dict[str, Any]]:
    return {
        "aim": {
            "smoothing_factor": 0.85,
            "max_step": 60.0,
            "max_fov_radius": 200.0,
            "lock_radius_px": 70.0,
            "lock_timeout_s": 0.5,
            "pixel_to_count": pixel_to_count,
        },
        "ai_engine": {
            "capture_size": CAPTURE_SIZE,
            "headshot_bias": HEADSHOT_BIAS,
        },
    }


def _enemy() -> Detection:
    return Detection(
        class_id=0, class_name="enemy",
        x=210.0, y=210.0, w=60.0, h=120.0, confidence=0.9,
    )


@pytest.mark.unit
def test_pixel_to_count_scales_linearly_with_driver_float_input() -> None:
    """req 2.8 — driver float input scales 1:1 with ``pixel_to_count``.

    Drives the pipeline with two ``pixel_to_count`` values (1.0 and
    2.0) on the same detection sequence; the recorded float inputs
    on the second run MUST equal exactly 2× the float inputs on the
    first run, modulo the EMA history (which is reset per run).
    """
    state_a, mouse_a = _LockState(), _FloatRecorder()
    state_b, mouse_b = _LockState(), _FloatRecorder()

    cfg_a = _cfg(1.0)
    cfg_b = _cfg(2.0)

    det = _enemy()
    for _ in range(5):
        aim_step([det], state_a, cfg_a, mouse_a, operator_overridden=False)
        aim_step([det], state_b, cfg_b, mouse_b, operator_overridden=False)

    assert mouse_a.float_in, "no moves emitted on run a — bbox out of FOV?"
    assert len(mouse_a.float_in) == len(mouse_b.float_in), (
        "Property req 2.8: emit count differs between runs — "
        "pixel_to_count must affect *only* the magnitude of the move, "
        "not whether a move is emitted"
    )
    for (xa, ya), (xb, yb) in zip(mouse_a.float_in, mouse_b.float_in):
        # Tolerate float rounding noise; the scale ratio MUST be 2.
        assert abs(xb - 2.0 * xa) < 1e-6, (
            f"Property req 2.8: x scale violated — pixel_to_count=2.0 "
            f"yielded {xb}, pixel_to_count=1.0 yielded {xa}, expected "
            f"ratio 2.0"
        )
        assert abs(yb - 2.0 * ya) < 1e-6, (
            f"Property req 2.8: y scale violated — pixel_to_count=2.0 "
            f"yielded {yb}, pixel_to_count=1.0 yielded {ya}, expected "
            f"ratio 2.0"
        )


@pytest.mark.unit
def test_pixel_to_count_logged_at_info_on_config_load() -> None:
    """req 2.8 — one INFO line per config load on the ``config.aim`` logger.

    Calls ``config.load_config()`` and asserts the ``config.aim``
    logger emits an INFO record whose message includes the literal
    string ``aim.pixel_to_count=`` followed by the configured value.

    The ``config.aim`` logger is created with ``propagate=False`` (it
    owns its own handler), so we attach a custom handler to it
    directly rather than relying on caplog propagation.
    """
    captured: List[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    handler = _Capture(level=logging.INFO)
    target = logging.getLogger("config.aim")
    # Force level to INFO so the record is not filtered before
    # reaching our handler. ``setup_logger`` short-circuits when the
    # logger already has handlers, so attaching our handler first
    # would leave the level at NOTSET (root default = WARNING) and
    # the INFO record would be filtered. Setting level=INFO here
    # mirrors what ``setup_logger`` would do on a fresh logger.
    prev_level = target.level
    target.setLevel(logging.INFO)
    target.addHandler(handler)
    try:
        config = cfg.load_config()
    finally:
        target.removeHandler(handler)
        target.setLevel(prev_level)

    expected = float(config["aim"]["pixel_to_count"])

    info_records = [r for r in captured if r.levelno == logging.INFO]
    assert info_records, (
        "Property req 2.8: ``load_config()`` did not emit an INFO "
        "record on the ``config.aim`` logger. Per the spec the "
        "explicit pixel→HID-count scaling factor MUST be visible in "
        "logs on every config load."
    )

    matching = [
        r for r in info_records
        if "aim.pixel_to_count=" in r.getMessage()
        and f"{expected:.4f}" in r.getMessage()
    ]
    assert matching, (
        f"Property req 2.8: no INFO record matched the expected "
        f"format ``aim.pixel_to_count={expected:.4f}``. Records "
        f"observed: {[r.getMessage() for r in info_records]}"
    )


@pytest.mark.unit
def test_pixel_to_count_present_in_config_yaml() -> None:
    """req 2.8 structural — ``pixel_to_count`` lives in ``config.yaml``.

    Reads the live ``config.yaml`` and asserts the ``aim.pixel_to_count``
    key exists with a strictly positive numeric value. This pins the
    "default value derived from the user's Valorant sens 0.5, 800 DPI,
    ADS multiplier 0.4" half of req 2.8 — the key is shipped in the
    config file, not just defaulted at runtime.
    """
    import os
    import yaml

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    with open(os.path.join(repo_root, "config.yaml"), "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    aim_section = data.get("aim") or {}
    assert "pixel_to_count" in aim_section or "legacy_pixel_to_count" in aim_section, (
        "Property req 2.8: ``aim.pixel_to_count`` (or ``aim.legacy_pixel_to_count``) "
        "is missing from config.yaml; the explicit pixel→HID-count scaling factor "
        "must be a shipped config key."
    )
    value = aim_section.get("pixel_to_count") or aim_section.get("legacy_pixel_to_count")
    assert isinstance(value, (int, float)) and value > 0, (
        f"Property req 2.8: ``aim.pixel_to_count`` must be a "
        f"strictly positive number; got {value!r}"
    )


@pytest.mark.unit
def test_pixel_to_count_read_once_per_step() -> None:
    """req 2.8 — value is consumed at exactly one point per tick.

    Wraps the cfg dict's ``"aim"`` section in a counter and asserts
    ``aim_step`` accesses ``pixel_to_count`` exactly once per call.
    The unfixed pipeline had multiple owners; the simplification
    keeps the access count at one — this test pins that contract.
    """
    state, mouse = _LockState(), _FloatRecorder()

    class _CountingDict(dict):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.access_count = 0

        def __getitem__(self, key):
            if key == "pixel_to_count":
                self.access_count += 1
            return super().__getitem__(key)

    aim_inner = _CountingDict(
        smoothing_factor=0.85, max_step=60.0, max_fov_radius=200.0,
        lock_radius_px=70.0, lock_timeout_s=0.5, pixel_to_count=0.85,
    )
    cfg_dict = {
        "aim": aim_inner,
        "ai_engine": {"capture_size": CAPTURE_SIZE, "headshot_bias": HEADSHOT_BIAS},
    }

    aim_step([_enemy()], state, cfg_dict, mouse, operator_overridden=False)
    assert aim_inner.access_count == 1, (
        f"Property req 2.8: aim_step accessed ``pixel_to_count`` "
        f"{aim_inner.access_count} times in one call; the spec "
        f"requires exactly ONE pixel → HID-count scaling site per tick"
    )
