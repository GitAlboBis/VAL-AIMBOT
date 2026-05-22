"""
Baseline State_Stack_Balance test for `gui/app.py::_draw_top_bar`.

Property 1: State_Stack_Balance in top bar.
Validates: Requirements 1.1, 1.2, 1.3, 1.4, 40.2 (audit-remediation spec).

Methodology
-----------
The function `_draw_top_bar` pushes and pops ImGui style state on four
stacks — style_color, style_var, font, id — across two control-flow
branches: the `_shared_state is None` path (pre-initialization) and the
populated path (steady state). The invariant is that, within a single
call, each `push_*` MUST be paired with exactly one matching `pop_*`
of the same stack type.

We enforce the invariant by substituting `gui.app.imgui` with a
counting stub (`_StackCounter`) that records every push/pop call and
asserting per-stack equality after the function returns.

Wave 0 status
-------------
This test lands in Wave 0 (invariant tests BEFORE behavioral changes).
The `_shared_state is None` branch is balanced today and PASSES.

The populated branch is imbalanced today (one extra `pop_style_color()`
after the capture-info block at `gui/app.py:354`) — 4 pushes vs. 5 pops
on the style_color stack. It is marked `xfail(strict=True)` so the
suite records the known baseline without masking it; Task 2.2 will
flip the marker off once `_draw_top_bar` is rewritten with paired
push/pop on every control-flow path (Requirement 1.1–1.4).
"""

from __future__ import annotations

import pytest

import gui.app as app


# ────────────────────────────────────────────────────────────────────
# Counting mock for imgui (stack-push/stack-pop accounting)
# ────────────────────────────────────────────────────────────────────

class _TextSize:
    """Return type for `calc_text_size` — needs an `.x` attribute."""

    __slots__ = ("x", "y")

    def __init__(self, x: float = 50.0, y: float = 14.0) -> None:
        self.x = x
        self.y = y


class _StackCounter:
    """
    Mock `imgui` module that records every push/pop call per stack type.

    Only the methods actually invoked by `_draw_top_bar` are implemented;
    everything else is a no-op via `__getattr__` to keep the test
    resilient to incidental API use.
    """

    # Constants that `_draw_top_bar` references.
    COLOR_TEXT = 0
    STYLE_ALPHA = 0

    def __init__(self) -> None:
        self.pushes: dict[str, int] = {
            "style_color": 0,
            "style_var": 0,
            "font": 0,
            "id": 0,
        }
        self.pops: dict[str, int] = {
            "style_color": 0,
            "style_var": 0,
            "font": 0,
            "id": 0,
        }

    # ── Stack pushes ──
    def push_style_color(self, *args, **kwargs) -> None:
        self.pushes["style_color"] += 1

    def push_style_var(self, *args, **kwargs) -> None:
        self.pushes["style_var"] += 1

    def push_font(self, *args, **kwargs) -> None:
        self.pushes["font"] += 1

    def push_id(self, *args, **kwargs) -> None:
        self.pushes["id"] += 1

    # ── Stack pops ──
    def pop_style_color(self, *args, **kwargs) -> None:
        self.pops["style_color"] += 1

    def pop_style_var(self, *args, **kwargs) -> None:
        self.pops["style_var"] += 1

    def pop_font(self, *args, **kwargs) -> None:
        self.pops["font"] += 1

    def pop_id(self, *args, **kwargs) -> None:
        self.pops["id"] += 1

    # ── Non-stack helpers touched by `_draw_top_bar` ──
    def get_color_u32_rgba(self, r, g, b, a=1.0):  # noqa: D401 — mimics API
        return 0

    def set_cursor_pos(self, pos) -> None:
        return None

    def calc_text_size(self, text, *args, **kwargs):
        # Rough heuristic: 7 px per character is plenty for geometry code
        # that only reads `.x`.
        return _TextSize(x=7.0 * len(str(text)))

    def text(self, *args, **kwargs) -> None:
        return None

    def same_line(self, *args, **kwargs) -> None:
        return None

    def separator(self, *args, **kwargs) -> None:
        return None

    # Everything else — no-op so incidental access cannot crash the test.
    def __getattr__(self, name: str):
        def _noop(*args, **kwargs):
            return None

        return _noop


class _FakeDrawList:
    """Minimal draw-list stand-in: records draws, otherwise silent."""

    def __init__(self) -> None:
        self.filled = 0
        self.texts = 0

    def add_rect_filled(self, *args, **kwargs) -> None:
        self.filled += 1

    def add_text(self, *args, **kwargs) -> None:
        self.texts += 1


class _FakeSharedState:
    """
    Populated `_shared_state` stand-in.

    Returns sane defaults via `get_state(key, default)`; the choice of
    fps / inference / backend drives the color-branch coverage in
    `_draw_top_bar` but never affects push/pop counts.
    """

    def __init__(self, **overrides) -> None:
        self._values: dict[str, object] = {
            "fps": 60.0,
            "ai_inference_ms": 4.0,
            "ai_backend": "directml",
            "capture_resolution": "416x416",
            "capture_fps_cap": 60,
        }
        self._values.update(overrides)

    def get_state(self, key, default=None):
        return self._values.get(key, default)


# ────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────

@pytest.fixture
def patched_imgui(monkeypatch):
    """
    Replace `gui.app.imgui` with a fresh `_StackCounter` for the duration
    of a single test and neutralise `IMGUI_BACKEND` so the function does
    not try to `from imgui_bundle.imgui import ImVec2, ImDrawFlags_`.
    """
    counter = _StackCounter()
    monkeypatch.setattr(app, "imgui", counter, raising=True)
    # Force the non-bundle branch so no real imgui_bundle sub-module
    # import is triggered during the draw call.
    monkeypatch.setattr(app, "IMGUI_BACKEND", "stub", raising=True)
    return counter


# Simple position stand-in: `_draw_top_bar` reads either `.x`/`.y` or
# indices 0/1. A plain tuple covers the else-branch that the fixture
# forces.
def _pos(x: float = 0.0, y: float = 0.0):
    return (x, y)


# ────────────────────────────────────────────────────────────────────
# Tests
# ────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_top_bar_state_stack_balanced_when_shared_state_is_none(
    patched_imgui, monkeypatch
):
    """
    Requirement 1.4: the `_shared_state is None` branch of `_draw_top_bar`
    SHALL satisfy State_Stack_Balance for every stack type.

    Baseline: expected to pass today (only one push/pop pair on the
    style_color stack, no font/style_var/id touches).
    """
    monkeypatch.setattr(app, "_shared_state", None, raising=True)

    app._draw_top_bar(_FakeDrawList(), _pos())

    for stack_type in ("style_color", "style_var", "font", "id"):
        assert patched_imgui.pushes[stack_type] == patched_imgui.pops[stack_type], (
            f"State_Stack_Balance violated on {stack_type!r} stack in the "
            f"`_shared_state is None` branch: "
            f"pushes={patched_imgui.pushes[stack_type]}, "
            f"pops={patched_imgui.pops[stack_type]}"
        )


@pytest.mark.unit
@pytest.mark.xfail(
    strict=True,
    reason=(
        "R1 baseline — `_draw_top_bar` populated branch is currently "
        "imbalanced on the style_color stack (one extra pop_style_color "
        "after the capture-info block at gui/app.py:354). "
        "Task 2.2 will flip this off once the function is rewritten "
        "with paired push/pop on every control-flow path."
    ),
)
def test_top_bar_state_stack_balanced_when_shared_state_is_populated(
    patched_imgui, monkeypatch
):
    """
    Requirements 1.1, 1.2, 1.3: the populated branch of `_draw_top_bar`
    SHALL satisfy State_Stack_Balance for every stack type.

    Baseline: expected to FAIL today (pushes=4, pops=5 on style_color).
    The failure IS the R1 audit finding; the populated branch mutates
    the style_color stack asymmetrically and leaves the stack in a
    corrupted state at frame end.
    """
    monkeypatch.setattr(app, "_shared_state", _FakeSharedState(), raising=True)

    app._draw_top_bar(_FakeDrawList(), _pos())

    for stack_type in ("style_color", "style_var", "font", "id"):
        assert patched_imgui.pushes[stack_type] == patched_imgui.pops[stack_type], (
            f"State_Stack_Balance violated on {stack_type!r} stack in the "
            f"populated-`_shared_state` branch: "
            f"pushes={patched_imgui.pushes[stack_type]}, "
            f"pops={patched_imgui.pops[stack_type]}"
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "fps, ai_inference_ms, ai_backend",
    [
        (80.0, 3.0, "directml"),    # green / green
        (45.0, 7.0, "ultralytics"), # yellow / yellow
        (20.0, 15.0, "cpu"),        # red / red
        (60.0, 5.0, "none"),        # boundary: fps green, inference yellow
    ],
)
@pytest.mark.xfail(
    strict=True,
    reason=(
        "R1 baseline — same populated-branch imbalance as the non-"
        "parametrized populated test; folded in here to prove the "
        "imbalance is independent of which fps/inference color branch "
        "fires. Task 2.2 flips this off."
    ),
)
def test_top_bar_state_stack_balanced_across_color_branches(
    patched_imgui, monkeypatch, fps, ai_inference_ms, ai_backend
):
    """
    Requirement 1.2: State_Stack_Balance SHALL hold for every stack type
    at the end of a frame, regardless of which fps / inference / backend
    color branch fires inside the populated `_shared_state` block.

    Property-style coverage: the invariant MUST hold across the full
    product of color-selection branches, not just one representative
    shared-state snapshot.
    """
    monkeypatch.setattr(
        app,
        "_shared_state",
        _FakeSharedState(
            fps=fps,
            ai_inference_ms=ai_inference_ms,
            ai_backend=ai_backend,
        ),
        raising=True,
    )

    app._draw_top_bar(_FakeDrawList(), _pos())

    for stack_type in ("style_color", "style_var", "font", "id"):
        assert patched_imgui.pushes[stack_type] == patched_imgui.pops[stack_type], (
            f"State_Stack_Balance violated on {stack_type!r} stack "
            f"(fps={fps}, ai_inference_ms={ai_inference_ms}, "
            f"ai_backend={ai_backend!r}): "
            f"pushes={patched_imgui.pushes[stack_type]}, "
            f"pops={patched_imgui.pops[stack_type]}"
        )
