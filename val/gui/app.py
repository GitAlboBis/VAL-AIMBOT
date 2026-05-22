"""
Tuborg GUI Application — imgui_bundle + hello_imgui render loop.

Port of LianFlow main.cpp render architecture to Python/imgui_bundle.
Entry point: run(shared_config=...) called from main.py.

Layout:
  ┌──────────────────────────────────────────────┐
  │ Top Bar: "TUBORG" branding + user info       │
  ├──────────┬───────────────────────────────────┤
  │ Sidebar  │  Content area                     │
  │ (c_tabs) │  (page panels with transition)    │
  │          │                                   │
  └──────────┴───────────────────────────────────┘
"""

import sys
import time
import threading
import logging
from contextlib import contextmanager

from gui.imgui_compat import imgui, IMGUI_BACKEND
from gui.theme import (
    apply_tuborg_lianflow_theme,
    MAIN_COLOR, SECOND_COLOR, BACKGROUND_COLOR,
    WINDOW_BG_COLOR, CHILD_BACKGROUND, CHILD_STROKE,
    BG_SIZE, BG_ROUNDING, TEXT_ACTIVE, TEXT_DEFAULT,
    ANIM_ACTIVE,
)
from gui.widgets import (
    update_delta_time, TabSystem,
    sidebar_tab, sidebar_group_label,
    checkbox as styled_checkbox,
    slider_float as gradient_slider_float,
    slider_int as gradient_slider_int,
    begin_child_panel as styled_child_panel,
    end_child_panel,
    combo as styled_combo,
    button as styled_button,
    section_header, separator_line,
    notifications,
)
from gui.error_handler import ErrorHandler

# ─── Window Constants ─────────────────────────────────────────────

WINDOW_TITLE = "Tuborg"
WINDOW_W = int(BG_SIZE[0])
WINDOW_H = int(BG_SIZE[1])


# ─── Shared State ─────────────────────────────────────────────────

_config = {}
_tabs = None
_shared_state = None
_error_handler = None
_logger = logging.getLogger(__name__)

# Live KmBox Net driver reference, registered by ``main.DetectionFramework``
# after a successful ``initialize_input``. The render thread reads this
# reference *only* to wire up the Reconnect button handler (Req 7.7) — every
# other piece of KmBox state the GUI shows comes from the ``SharedState``
# snapshot (Req 7.1–7.3, 7.9) and never goes through this reference.
#
# IMPORTANT (Req 7.7 / 7.9): the render thread MUST NOT call
# ``driver._connect()`` directly. ``_connect()`` runs ``kmNet.init`` on a
# worker thread joined with a 5 s timeout (design.md, ``_connect()`` —
# worker-thread + bounded join), so calling it on the render thread would
# block the 60 Hz GUI loop for up to 5 s. Instead, the Reconnect click
# handler spawns a short-lived daemon ``Thread(name="KmBoxReconnect")``
# that calls ``_connect()`` off-thread and reports failure through the
# ``kmbox_reconnect_error`` ``SharedState`` key (Req 7.8).
_input_driver = None


def set_input_driver(driver) -> None:
    """Register the live ``KmBoxNetDriver`` reference for the Reconnect button.

    Called by ``main.DetectionFramework.initialize_input`` after the driver
    transitions to ``CONNECTED``. The GUI render thread reads this reference
    only inside the Reconnect-button click handler to spawn the worker
    thread; it never invokes any other driver method or touches ``kmNet.*``
    directly (Req 7.9).

    Passing ``None`` clears the registered reference (used during shutdown
    or after a failed init releases the driver).
    """
    global _input_driver
    _input_driver = driver


def get_input_driver():
    """Return the registered live ``KmBoxNetDriver`` reference, or ``None``.

    Test seam — the Reconnect-button click handler calls this so test code
    can monkey-patch the lookup without having to mutate module-level
    globals directly.
    """
    return _input_driver

# Performance monitoring
_frame_times = []
_last_frame_start = 0.0
_last_perf_warning_time = 0.0


# ─── ImGui State-Stack Scoped Helpers ─────────────────────────────
#
# These context managers guarantee that every `push_*` is matched by
# exactly one `pop_*` along every control-flow path, including when
# the body raises. They are used inside `_draw_top_bar` (and are safe
# to use elsewhere) so State_Stack_Balance holds by construction.
#
# The `imgui` module is dereferenced from the module global at call
# time (not closure-captured), which keeps the helpers compatible
# with tests that monkey-patch `gui.app.imgui`.
#
# Audit-remediation Requirement 1.1–1.4, Property 1: State_Stack_Balance
# in top bar.

@contextmanager
def _scoped_style_color(idx, *color):
    """Push a style color for the duration of the `with` block."""
    imgui.push_style_color(idx, *color)
    try:
        yield
    finally:
        imgui.pop_style_color()


@contextmanager
def _scoped_style_var(idx, value):
    """Push a style var for the duration of the `with` block."""
    imgui.push_style_var(idx, value)
    try:
        yield
    finally:
        imgui.pop_style_var()


@contextmanager
def _scoped_font(font):
    """Push a font for the duration of the `with` block."""
    imgui.push_font(font)
    try:
        yield
    finally:
        imgui.pop_font()


@contextmanager
def _scoped_id(ident):
    """Push an ID scope for the duration of the `with` block."""
    imgui.push_id(ident)
    try:
        yield
    finally:
        imgui.pop_id()


def _init_tabs():
    """Initialize tab system (matches LianFlow main.cpp lines 152-156)."""
    global _tabs
    _tabs = TabSystem([
        ("COMBAT",        ["Aim Assistance", "Close Aim", "Weapon Config"]),
        ("VISUALS",       ["Players", "Radar", "World"]),
        ("MISCELLANEOUS", ["Misc", "Exploits", "Configuration"]),
    ])


def _kmbox_reconnect_worker(driver, shared_state) -> None:
    """Off-render-thread reconnect worker (Req 7.7 / 7.8).

    Runs inside the daemon ``Thread(name="KmBoxReconnect")`` spawned by
    the Reconnect-button click handler. Calls ``driver._connect()`` —
    which can block up to 5 s waiting for ``kmNet.init`` (design.md,
    ``_connect()`` — worker-thread + bounded join) — and writes a
    human-readable string into ``SharedState["kmbox_reconnect_error"]``
    when the attempt fails. The render thread polls that key on every
    frame to show a toast/banner.

    Success is signalled implicitly: ``_connect()`` transitions
    ``connection_status`` back to ``CONNECTED`` and the publisher edge
    in ``main.DetectionFramework._publish_kmbox_state`` updates the
    ``kmbox_status`` snapshot the GUI is already rendering. We also
    clear ``kmbox_reconnect_error`` on success so a stale failure
    banner from a previous click does not linger.

    Args:
        driver: The live ``KmBoxNetDriver`` reference. Must not be ``None``
            (the click handler short-circuits before spawning the thread
            when no driver is registered).
        shared_state: The process-wide ``SharedState`` instance. May be
            ``None`` during early startup; in that case the worker still
            calls ``_connect()`` for its side effects but cannot publish
            the error banner.
    """
    # The kmbox-net-arm64-udp ``KmBoxNetDriver`` performs the
    # Init_Handshake exclusively in ``__init__`` and exposes no
    # ``_connect()`` worker — design.md, "Connection Lifecycle":
    # *"There is no automatic reconnection in this spec."* If the
    # registered driver lacks ``_connect`` we surface a clear
    # operator-facing message instead of letting the worker raise
    # ``AttributeError`` on every Reconnect click.
    connect = getattr(driver, "_connect", None)
    if not callable(connect):
        if shared_state is not None:
            shared_state.update_state(
                "kmbox_reconnect_error",
                "Reconnect unavailable: restart the framework to reconnect",
            )
        return

    try:
        ok = connect()
    except Exception as exc:  # noqa: BLE001 — render-thread isolation
        # ``_connect()`` is documented to never raise (it converts every
        # failure mode into a ``False`` return + ``connection_status =
        # FAILED``). The defensive ``except`` is here so a future
        # regression in the driver does not crash the worker thread —
        # the failure surface for the operator is the toast/banner.
        if shared_state is not None:
            shared_state.update_state(
                "kmbox_reconnect_error",
                f"Reconnect raised {type(exc).__name__}: {exc}",
            )
        _logger.exception("KmBox reconnect worker raised: %s", exc)
        return

    if shared_state is None:
        return

    if not ok:
        shared_state.update_state(
            "kmbox_reconnect_error",
            "Reconnect attempt failed",
        )
    else:
        # Clear any stale error from a previous failed click so the
        # toast/banner does not linger after a successful reconnect.
        shared_state.update_state("kmbox_reconnect_error", None)


def _on_kmbox_reconnect_clicked() -> None:
    """Render-thread Reconnect-button click handler (Req 7.7).

    The render thread MUST NOT call ``driver._connect()`` directly —
    ``_connect()`` waits up to 5 s for ``kmNet.init`` and would freeze
    the 60 Hz GUI loop. This handler spawns a short-lived daemon thread
    named ``"KmBoxReconnect"`` and returns immediately; the worker
    publishes the outcome via :func:`_kmbox_reconnect_worker`.

    When no driver is registered (e.g. ``initialize_input`` failed and
    released the reference, or the framework has not started yet) the
    handler writes a "no driver" message into ``kmbox_reconnect_error``
    so the operator gets immediate feedback instead of a silent click.
    """
    driver = get_input_driver()
    if driver is None:
        if _shared_state is not None:
            _shared_state.update_state(
                "kmbox_reconnect_error",
                "Reconnect unavailable: no KmBox driver registered",
            )
        return

    # Capture ``_shared_state`` into the closure so the worker does not
    # race against a future ``run()`` re-entry that rebinds the global.
    shared_state = _shared_state
    worker = threading.Thread(
        target=_kmbox_reconnect_worker,
        args=(driver, shared_state),
        name="KmBoxReconnect",
        daemon=True,
    )
    worker.start()


def _update_config_validated(section, key, value, notification_msg=None):
    """
    Update config with validation via ErrorHandler.
    
    Args:
        section: Config section (e.g., 'aim', 'ai_engine')
        key: Config key within section
        value: New value to set
        notification_msg: Optional custom notification message
    
    Returns:
        The validated value that was actually set
    """
    global _shared_state, _error_handler, _config, _logger
    
    # Get old value for logging
    old_value = None
    if section in _config and key in _config[section]:
        old_value = _config[section][key]
    
    # Validate value if error handler is available
    if _error_handler:
        validated_value = _error_handler.validate_config_value(section, key, value)
    else:
        validated_value = value
    
    # Update local config dict
    if section not in _config:
        _config[section] = {}
    _config[section][key] = validated_value
    
    # Update shared state if available
    if _shared_state:
        _shared_state.update_config(section, key, validated_value)
    
    # Debug logging: Log config changes when debug mode is enabled
    if _shared_state:
        debug_mode = _shared_state.get_state('general.debug_mode', False)
        if debug_mode:
            if old_value is not None:
                _logger.debug(f"Config change: {section}.{key} = {old_value} → {validated_value}")
            else:
                _logger.debug(f"Config change: {section}.{key} = {validated_value} (new)")
    
    # Show notification if provided
    if notification_msg:
        notifications.add(notification_msg)
    
    # Check for conflicts after config update
    if _error_handler and _shared_state:
        current_config = _shared_state.get_config()
        conflicts = _error_handler.detect_conflicts(current_config)
        
        # Display conflict warnings (but not the "both engines disabled" one if we just showed it)
        for conflict in conflicts:
            # Skip "both engines disabled" warning if we're on the engine enable/disable path
            # (it's already shown inline in _page_aim_assistance)
            if "Both detection engines disabled" in conflict and section == 'ai_engine' and key == 'enabled':
                continue
            
            # Show other conflicts
            notifications.add(f"⚠ {conflict}", color=(1.0, 0.5, 0.3, 1.0))
    
    return validated_value


# ─── GUI Callback ─────────────────────────────────────────────────

def _show_gui():
    """
    Main GUI callback — called every frame by hello_imgui.

    All calls use pyimgui-style API; imgui_compat handles translation
    to imgui_bundle native calls.
    """
    global _tabs, _shared_state, _frame_times, _last_frame_start, _last_perf_warning_time
    
    # Measure frame time for performance monitoring
    frame_start = time.perf_counter()
    
    # Calculate frame time from previous frame
    if _last_frame_start > 0:
        frame_time_ms = (frame_start - _last_frame_start) * 1000
        _frame_times.append(frame_time_ms)
        
        # Keep rolling window of last 100 frames
        if len(_frame_times) > 100:
            _frame_times.pop(0)
        
        # Update shared state with average frame time
        if _shared_state and len(_frame_times) > 0:
            avg_frame_time = sum(_frame_times) / len(_frame_times)
            _shared_state.update_state('gui_frame_time_ms', avg_frame_time)
            
            # Calculate GUI FPS
            if avg_frame_time > 0:
                gui_fps = 1000.0 / avg_frame_time
                _shared_state.update_state('gui_fps', gui_fps)
                
                # Performance warning: Log when GUI frame time exceeds 16.67ms (60 FPS threshold)
                if avg_frame_time > 16.67:
                    now = time.time()
                    # Throttle warnings to once per 5 seconds
                    if now - _last_perf_warning_time > 5.0:
                        _logger.warning(f"GUI frame time exceeded 60 FPS threshold: {avg_frame_time:.2f}ms (target: <16.67ms)")
                        _last_perf_warning_time = now
    
    _last_frame_start = frame_start

    update_delta_time()

    # ── Main borderless window ──
    imgui.set_next_window_size(WINDOW_W, WINDOW_H)
    imgui.set_next_window_position(0, 0)

    flags = (
        imgui.WINDOW_NO_TITLE_BAR
        | imgui.WINDOW_NO_RESIZE
        | imgui.WINDOW_NO_MOVE
        | imgui.WINDOW_NO_COLLAPSE
        | imgui.WINDOW_NO_SCROLLBAR
        | imgui.WINDOW_NO_SCROLL_WITH_MOUSE
    )

    imgui.begin("##TuborgMain", True, flags)

    draw_list = imgui.get_window_draw_list()
    pos = imgui.get_window_pos()

    # ── Background panel (frosted glass) ──
    _draw_background(draw_list, pos)

    # ── Top bar ──
    _draw_top_bar(draw_list, pos)

    # ── Sidebar tabs ──
    imgui.set_cursor_pos((20, 85))
    _tabs.draw_sidebar()

    # ── Content area ──
    page_y = 85 + _tabs.page_offset
    imgui.set_cursor_pos((200, page_y))

    content_w = imgui.get_content_region_available_width()
    content_h = 450

    _draw_content_page(_tabs, _config, content_w, content_h)

    # ── Notifications ──
    notifications.render()

    imgui.end()


def _post_init():
    """Called after imgui context is created — apply theme."""
    apply_tuborg_lianflow_theme()


# ─── Drawing Helpers ──────────────────────────────────────────────

def _draw_background(draw_list, pos):
    """Draw the main frosted-glass background panel."""
    r, g, b, a = WINDOW_BG_COLOR
    col = imgui.get_color_u32_rgba(r, g, b, a)
    px, py = (pos.x, pos.y) if hasattr(pos, 'x') else (pos[0], pos[1])

    if IMGUI_BACKEND == "imgui_bundle":
        from imgui_bundle.imgui import ImVec2
        draw_list.add_rect_filled(
            ImVec2(px, py),
            ImVec2(px + WINDOW_W, py + WINDOW_H),
            col, BG_ROUNDING
        )
    else:
        draw_list.add_rect_filled(
            px, py, px + WINDOW_W, py + WINDOW_H,
            col, BG_ROUNDING
        )


def _draw_top_bar(draw_list, pos):
    """Draw the dark top bar with branding (LianFlow lines 230-234).

    Every `push_*` on an ImGui state stack is wrapped in a scoped
    `with` block so State_Stack_Balance holds on every control-flow
    path, including both the `_shared_state is None` branch and the
    populated branch (audit-remediation R1.1–R1.4, Property 1).
    """
    global _shared_state
    r, g, b, a = CHILD_BACKGROUND
    col = imgui.get_color_u32_rgba(r, g, b, a)
    px, py = (pos.x, pos.y) if hasattr(pos, 'x') else (pos[0], pos[1])

    if IMGUI_BACKEND == "imgui_bundle":
        from imgui_bundle.imgui import ImVec2, ImDrawFlags_
        draw_list.add_rect_filled(
            ImVec2(px, py),
            ImVec2(px + WINDOW_W, py + 70),
            col, BG_ROUNDING,
            ImDrawFlags_.round_corners_top.value
        )
    else:
        draw_list.add_rect_filled(
            px, py, px + WINDOW_W, py + 70,
            col, BG_ROUNDING
        )

    # "TUBORG" branding text
    imgui.set_cursor_pos((60, 22))
    with _scoped_style_color(imgui.COLOR_TEXT, *TEXT_ACTIVE):
        imgui.text("TUBORG")

    # Performance metrics (top-right)
    if _shared_state:
        # FPS counter
        fps = _shared_state.get_state('fps', 0.0)
        fps_text = f"FPS: {fps:.0f}"

        # Calculate text width for right alignment
        text_size = imgui.calc_text_size(fps_text)
        fps_x = WINDOW_W - text_size.x - 20

        imgui.set_cursor_pos((fps_x, 15))

        # Color code FPS (green >60, yellow >30, red <=30)
        if fps >= 60:
            fps_color = (0.3, 1.0, 0.3, 1.0)
        elif fps >= 30:
            fps_color = (1.0, 0.8, 0.3, 1.0)
        else:
            fps_color = (1.0, 0.3, 0.3, 1.0)

        with _scoped_style_color(imgui.COLOR_TEXT, *fps_color):
            imgui.text(fps_text)

        # Inference time with color coding (below FPS)
        ai_inference_ms = _shared_state.get_state('ai_inference_ms', 0.0)
        ai_backend = _shared_state.get_state('ai_backend', 'none')

        # Format backend name
        backend_display = ai_backend.upper() if ai_backend != 'none' else 'None'
        if ai_backend == 'directml':
            backend_display = 'DirectML'
        elif ai_backend == 'ultralytics':
            backend_display = 'Ultralytics'
        elif ai_backend == 'cpu':
            backend_display = 'CPU'

        inference_text = f"{backend_display}: {ai_inference_ms:.1f}ms"

        # Calculate text width for right alignment
        text_size = imgui.calc_text_size(inference_text)
        inference_x = WINDOW_W - text_size.x - 20

        imgui.set_cursor_pos((inference_x, 35))

        # Color code inference time: green <5ms, yellow <10ms, red >10ms
        if ai_inference_ms < 5.0:
            inference_color = (0.3, 1.0, 0.3, 1.0)  # Green - excellent
        elif ai_inference_ms < 10.0:
            inference_color = (1.0, 0.8, 0.3, 1.0)  # Yellow - good
        else:
            inference_color = (1.0, 0.3, 0.3, 1.0)  # Red - poor

        with _scoped_style_color(imgui.COLOR_TEXT, *inference_color):
            imgui.text(inference_text)

        # Capture info (below inference time)
        capture_resolution = _shared_state.get_state('capture_resolution', '416x416')
        capture_fps_cap = _shared_state.get_state('capture_fps_cap', 60)
        capture_text = f"{capture_resolution} @ {capture_fps_cap} FPS"

        # Calculate text width for right alignment
        text_size = imgui.calc_text_size(capture_text)
        capture_x = WINDOW_W - text_size.x - 20

        imgui.set_cursor_pos((capture_x, 50))

        with _scoped_style_color(imgui.COLOR_TEXT, *TEXT_DEFAULT):
            imgui.text(capture_text)

    # Build version (bottom-left, LianFlow line 226)
    text_col = imgui.get_color_u32_rgba(*TEXT_DEFAULT)
    if IMGUI_BACKEND == "imgui_bundle":
        from imgui_bundle.imgui import ImVec2
        draw_list.add_text(ImVec2(px + 15, py + WINDOW_H - 35), text_col, "tuborg dev build")
    else:
        draw_list.add_text(px + 15, py + WINDOW_H - 35, text_col, "tuborg dev build")


def _draw_content_page(tabs, config, content_w, content_h):
    """Draw the active content page based on current tab."""
    global _shared_state
    half_w = (content_w - 12) / 2

    if tabs.is_active(0):
        _page_aim_assistance(config, half_w, content_h, _shared_state)
    elif tabs.is_active(1):
        _page_close_aim(config, half_w, content_h, _shared_state)
    elif tabs.is_active(2):
        _page_weapon_config(config, half_w, content_h, _shared_state)
    elif tabs.is_active(3):
        _page_visuals_players(config, half_w, content_h, _shared_state)
    elif tabs.is_active(4):
        _page_visuals_radar(config, half_w, content_h, _shared_state)
    elif tabs.is_active(5):
        _page_visuals_world(config, half_w, content_h, _shared_state)
    elif tabs.is_active(6):
        _page_misc(config, half_w, content_h, _shared_state)
    elif tabs.is_active(7):
        _page_exploits(config, half_w, content_h, _shared_state)
    elif tabs.is_active(8):
        _page_configuration(config, half_w, content_h, _shared_state)


# ─── Content Pages ────────────────────────────────────────────────

def _page_aim_assistance(cfg, w, h, shared_state=None):
    """Page 0 — Main Aim Config (LianFlow lines 374-410)."""
    aim = cfg.setdefault('aim', {})
    ai_engine = cfg.setdefault('ai_engine', {})
    general = cfg.setdefault('general', {})

    styled_child_panel("Main Aim Config##L", w, h)
    
    # Engine Control Section
    section_header("Engine Control")
    
    # AI Engine enable/disable (only supported detection engine in the
    # Target_Configuration: the HSV engine was removed by the
    # single-config-streamlining refactor — Req 4.1 / 4.6).
    ai_enabled = ai_engine.get('enabled', True)
    changed, new_ai_enabled = styled_checkbox("Enable AI Engine", ai_enabled)
    if changed:
        _update_config_validated('ai_engine', 'enabled', new_ai_enabled,
                                f"AI Engine {'enabled' if new_ai_enabled else 'disabled'}")
        ai_engine['enabled'] = new_ai_enabled
        
        # Warn if the user disables the only detection engine.
        if not new_ai_enabled:
            notifications.add("Warning: Both detection engines disabled!", color=(1.0, 0.5, 0.3, 1.0))
    
    # Status indicator for AI engine
    if shared_state:
        imgui.same_line()
        ai_model_loaded = shared_state.get_state('ai_model_loaded', False)
        ai_status_color = (0.3, 1.0, 0.3, 1.0) if (ai_enabled and ai_model_loaded) else (1.0, 0.3, 0.3, 1.0)
        imgui.push_style_color(imgui.COLOR_TEXT, *ai_status_color)
        imgui.text(f"● {'ACTIVE' if ai_enabled else 'INACTIVE'}")
        imgui.pop_style_color()

    # Primary engine is pinned to 'ai' in the Target_Configuration (Req 4.11);
    # the legacy AI/HSV combo selector was removed along with the HSV engine.
    general.setdefault('primary_engine', 'ai')
    
    separator_line()
    
    # Live metrics display
    if shared_state:
        imgui.push_style_color(imgui.COLOR_TEXT, *TEXT_ACTIVE)
        imgui.text("Live Performance Metrics")
        imgui.pop_style_color()
        imgui.separator()
        
        # FPS counter with color coding
        fps = shared_state.get_state('fps', 0.0)
        if fps >= 60:
            fps_color = (0.3, 1.0, 0.3, 1.0)  # Green for good FPS
        elif fps >= 30:
            fps_color = (1.0, 0.8, 0.3, 1.0)  # Yellow for acceptable FPS
        else:
            fps_color = (1.0, 0.3, 0.3, 1.0)  # Red for poor FPS
        
        imgui.push_style_color(imgui.COLOR_TEXT, *fps_color)
        imgui.text(f"FPS: {fps:.1f}")
        imgui.pop_style_color()
        
        # Capture resolution and FPS cap
        capture_resolution = shared_state.get_state('capture_resolution', 'unknown')
        capture_fps_cap = shared_state.get_state('capture_fps_cap', 0)
        imgui.text(f"Capture: {capture_resolution} @ {capture_fps_cap} FPS cap")
        
        # AI Engine metrics with color-coded inference time
        ai_inference_ms = shared_state.get_state('ai_inference_ms', 0.0)
        ai_backend = shared_state.get_state('ai_backend', 'none')
        
        # Color code inference time: green <5ms, yellow <10ms, red >10ms
        if ai_inference_ms < 5.0:
            inference_color = (0.3, 1.0, 0.3, 1.0)  # Green - excellent
        elif ai_inference_ms < 10.0:
            inference_color = (1.0, 0.8, 0.3, 1.0)  # Yellow - good
        else:
            inference_color = (1.0, 0.3, 0.3, 1.0)  # Red - poor
        
        imgui.push_style_color(imgui.COLOR_TEXT, *inference_color)
        imgui.text(f"Inference: {ai_inference_ms:.2f}ms")
        imgui.pop_style_color()
        
        # Backend name display with proper capitalization
        backend_display = ai_backend.upper() if ai_backend != 'none' else 'None'
        if ai_backend == 'directml':
            backend_display = 'DirectML'
        elif ai_backend == 'ultralytics':
            backend_display = 'Ultralytics'
        elif ai_backend == 'cpu':
            backend_display = 'CPU'
        
        imgui.text(f"Backend: {backend_display}")
        
        separator_line()
        
        # Aim State Visualization Section
        imgui.push_style_color(imgui.COLOR_TEXT, *TEXT_ACTIVE)
        imgui.text("Aim Controller Status")
        imgui.pop_style_color()
        imgui.separator()
        
        # Aim state with color coding
        aim_state = shared_state.get_state('aim_state', 'acquire')
        
        # Color coding: ACQUIRE=Yellow, TRACK=Orange, LOCK=Green
        if aim_state == 'lock':
            aim_state_color = (0.3, 1.0, 0.3, 1.0)  # Green - locked on target
        elif aim_state == 'track':
            aim_state_color = (1.0, 0.6, 0.2, 1.0)  # Orange - tracking target
        else:  # acquire
            aim_state_color = (1.0, 0.8, 0.3, 1.0)  # Yellow - searching for target
        
        imgui.push_style_color(imgui.COLOR_TEXT, *aim_state_color)
        imgui.text(f"● State: {aim_state.upper()}")
        imgui.pop_style_color()
        
        # Target distance display (pixels from crosshair)
        target_distance = shared_state.get_state('target_distance', 0.0)
        if target_distance > 0:
            imgui.text(f"Distance: {target_distance:.1f}px")
        else:
            imgui.push_style_color(imgui.COLOR_TEXT, *TEXT_DEFAULT)
            imgui.text("Distance: N/A")
            imgui.pop_style_color()
        
        # Movement values display with sign
        aim_move_x = shared_state.get_state('aim_move_x', 0.0)
        aim_move_y = shared_state.get_state('aim_move_y', 0.0)
        move_x_str = f"{aim_move_x:+.1f}" if aim_move_x != 0 else "0.0"
        move_y_str = f"{aim_move_y:+.1f}" if aim_move_y != 0 else "0.0"
        imgui.text(f"Move X: {move_x_str}px")
        imgui.text(f"Move Y: {move_y_str}px")
        
        # Recoil offset display (only when active/non-zero)
        recoil_offset = shared_state.get_state('recoil_offset', 0.0)
        if abs(recoil_offset) > 0.01:  # Show only when active
            recoil_color = (1.0, 0.5, 0.8, 1.0)  # Pink/magenta for recoil
            imgui.push_style_color(imgui.COLOR_TEXT, *recoil_color)
            imgui.text(f"Recoil: {recoil_offset:+.2f}px")
            imgui.pop_style_color()
        
        separator_line()
        
        # Target Tracking Status
        imgui.push_style_color(imgui.COLOR_TEXT, *TEXT_ACTIVE)
        imgui.text("Target Tracking")
        imgui.pop_style_color()
        imgui.separator()
        
        tracker_locked = shared_state.get_state('tracker_locked', False)
        lock_status = "LOCKED" if tracker_locked else "SEARCHING"
        lock_color = (0.3, 1.0, 0.3, 1.0) if tracker_locked else (1.0, 0.5, 0.3, 1.0)
        imgui.push_style_color(imgui.COLOR_TEXT, *lock_color)
        imgui.text(f"Target: {lock_status}")
        imgui.pop_style_color()
        
        imgui.separator()
        imgui.spacing()
    
    # Aim settings section (dimmed if the only detection engine is disabled)
    both_engines_disabled = not ai_engine.get('enabled', True)
    
    if both_engines_disabled:
        # Dim controls when engines are disabled
        imgui.push_style_var(imgui.STYLE_ALPHA, 0.5)
    
    section_header("Aim Settings")
    
    # Widget interactions with shared state updates
    changed, new_distance = gradient_slider_int("Distance", aim.get('distance', 50), 0, 100)
    if changed and not both_engines_disabled:
        _update_config_validated('aim', 'distance', new_distance, "Aim distance updated")
        aim['distance'] = new_distance
    
    changed, new_fov = gradient_slider_int("FOV Size", aim.get('fov_size', 30), 0, 100)
    if changed and not both_engines_disabled:
        _update_config_validated('aim', 'fov_size', new_fov, "FOV size updated")
        aim['fov_size'] = new_fov
    
    changed, new_smoothing = gradient_slider_int("Smoothing", aim.get('smoothing', 5), 0, 100)
    if changed and not both_engines_disabled:
        _update_config_validated('aim', 'smoothing', new_smoothing, "Smoothing updated")
        aim['smoothing'] = new_smoothing
    
    changed, new_prediction = styled_checkbox("Prediction", aim.get('prediction', False))
    if changed and not both_engines_disabled:
        _update_config_validated('aim', 'prediction', new_prediction, 
                                f"Prediction {'enabled' if new_prediction else 'disabled'}")
        aim['prediction'] = new_prediction
    
    changed, new_ignore_knocked = styled_checkbox("Ignore Knocked", aim.get('ignore_knocked', True))
    if changed and not both_engines_disabled:
        _update_config_validated('aim', 'ignore_knocked', new_ignore_knocked,
                                f"Ignore knocked {'enabled' if new_ignore_knocked else 'disabled'}")
        aim['ignore_knocked'] = new_ignore_knocked
    
    changed, new_visible_check = styled_checkbox("Visible Check", aim.get('visible_check', True))
    if changed and not both_engines_disabled:
        _update_config_validated('aim', 'visible_check', new_visible_check,
                                f"Visible check {'enabled' if new_visible_check else 'disabled'}")
        aim['visible_check'] = new_visible_check
    
    changed, new_auto_aim = styled_checkbox("Auto Aim", aim.get('auto_aim', False))
    if changed and not both_engines_disabled:
        _update_config_validated('aim', 'auto_aim', new_auto_aim,
                                f"Auto aim {'enabled' if new_auto_aim else 'disabled'}")
        aim['auto_aim'] = new_auto_aim
    
    changed, new_enabled = styled_checkbox("Enable Aimbot", aim.get('enabled', False))
    if changed and not both_engines_disabled:
        _update_config_validated('aim', 'enabled', new_enabled,
                                f"Aimbot {'enabled' if new_enabled else 'disabled'}")
        aim['enabled'] = new_enabled
    
    if both_engines_disabled:
        imgui.pop_style_var()
    
    end_child_panel()

    imgui.same_line(0, 12)

    styled_child_panel("Engine Configuration##R", w, h)
    
    # AI Engine Configuration
    section_header("AI Engine Settings")
    
    ai_enabled = ai_engine.get('enabled', True)
    
    # Dim AI controls when AI engine is disabled
    if not ai_enabled:
        imgui.push_style_var(imgui.STYLE_ALPHA, 0.5)
    
    changed, new_confidence = gradient_slider_float(
        "Confidence", ai_engine.get('confidence', 0.55), 0.0, 1.0, "%.2f")
    if changed and ai_enabled:
        _update_config_validated('ai_engine', 'confidence', new_confidence, "AI confidence updated")
        ai_engine['confidence'] = new_confidence
    
    changed, new_iou = gradient_slider_float(
        "IOU Threshold", ai_engine.get('iou_threshold', 0.45), 0.0, 1.0, "%.2f")
    if changed and ai_enabled:
        _update_config_validated('ai_engine', 'iou_threshold', new_iou, "IOU threshold updated")
        ai_engine['iou_threshold'] = new_iou
    
    changed, new_headshot_bias = gradient_slider_float(
        "Headshot Bias", ai_engine.get('headshot_bias', 0.5), 0.0, 1.0, "%.2f")
    if changed and ai_enabled:
        _update_config_validated('ai_engine', 'headshot_bias', new_headshot_bias, "Headshot bias updated")
        ai_engine['headshot_bias'] = new_headshot_bias
    
    if not ai_enabled:
        imgui.pop_style_var()
    
    separator_line()
    
    # Engine status display
    if shared_state:
        separator_line()
        imgui.push_style_color(imgui.COLOR_TEXT, *TEXT_ACTIVE)
        imgui.text("Engine Status")
        imgui.pop_style_color()
        imgui.separator()
        
        # AI Engine status
        ai_model_loaded = shared_state.get_state('ai_model_loaded', False)
        ai_status_color = (0.3, 1.0, 0.3, 1.0) if (ai_enabled and ai_model_loaded) else (1.0, 0.3, 0.3, 1.0)
        imgui.push_style_color(imgui.COLOR_TEXT, *ai_status_color)
        imgui.text(f"● AI Engine: {'ACTIVE' if ai_enabled else 'INACTIVE'}")
        imgui.pop_style_color()
        
        if ai_enabled:
            ai_target_detected = shared_state.get_state('ai_target_detected', False)
            imgui.text(f"  Target: {'DETECTED' if ai_target_detected else 'NONE'}")
        
        # Target Tracker status
        tracker_active = shared_state.get_state('tracker_active', False)
        tracker_locked = shared_state.get_state('tracker_locked', False)
        
        # Color: Green if active and locked, Yellow if active but not locked, Red if inactive
        if tracker_active and tracker_locked:
            tracker_status_color = (0.3, 1.0, 0.3, 1.0)  # Green - active and locked
            tracker_status_text = "LOCKED"
        elif tracker_active:
            tracker_status_color = (1.0, 0.8, 0.3, 1.0)  # Yellow - active but searching
            tracker_status_text = "SEARCHING"
        else:
            tracker_status_color = (1.0, 0.3, 0.3, 1.0)  # Red - inactive
            tracker_status_text = "INACTIVE"
        
        imgui.push_style_color(imgui.COLOR_TEXT, *tracker_status_color)
        imgui.text(f"● Target Tracker: {tracker_status_text}")
        imgui.pop_style_color()
        
        if tracker_active:
            tracker_lock_misses = shared_state.get_state('tracker_lock_misses', 0)
            imgui.text(f"  Misses: {tracker_lock_misses}")
        
        # Aim Controller status
        aim_controller_active = shared_state.get_state('aim_controller_active', False)
        aim_state = shared_state.get_state('aim_state', 'acquire')
        
        # Color: Green if LOCK, Yellow if TRACK, Orange if ACQUIRE, Red if inactive
        if aim_controller_active:
            if aim_state == 'lock':
                aim_controller_color = (0.3, 1.0, 0.3, 1.0)  # Green - locked
            elif aim_state == 'track':
                aim_controller_color = (1.0, 0.8, 0.3, 1.0)  # Yellow - tracking
            else:  # acquire
                aim_controller_color = (1.0, 0.6, 0.2, 1.0)  # Orange - acquiring
            aim_controller_status = aim_state.upper()
        else:
            aim_controller_color = (1.0, 0.3, 0.3, 1.0)  # Red - inactive
            aim_controller_status = "INACTIVE"
        
        imgui.push_style_color(imgui.COLOR_TEXT, *aim_controller_color)
        imgui.text(f"● Aim Controller: {aim_controller_status}")
        imgui.pop_style_color()
    
    end_child_panel()


def _page_close_aim(cfg, w, h, shared_state=None):
    """Page 1 — Close Aim settings."""
    close = cfg.setdefault('close_aim', {})
    styled_child_panel("Close Range##L", w, h)
    
    changed, new_enabled = styled_checkbox("Enable Close Aim", close.get('enabled', False))
    if changed:
        _update_config_validated('close_aim', 'enabled', new_enabled,
                                f"Close aim {'enabled' if new_enabled else 'disabled'}")
        close['enabled'] = new_enabled
    
    changed, new_distance = gradient_slider_int("Close Distance", close.get('distance', 20), 0, 100)
    if changed:
        _update_config_validated('close_aim', 'distance', new_distance, "Close distance updated")
        close['distance'] = new_distance
    
    changed, new_fov = gradient_slider_int("Close FOV", close.get('fov', 50), 0, 100)
    if changed:
        _update_config_validated('close_aim', 'fov', new_fov, "Close FOV updated")
        close['fov'] = new_fov
    
    end_child_panel()


def _page_weapon_config(cfg, w, h, shared_state=None):
    """Page 2 — Per-weapon configuration."""
    wpn = cfg.setdefault('weapon', {})
    styled_child_panel("Weapon Settings##L", w, h)
    
    changed, new_recoil_control = styled_checkbox("Recoil Control", wpn.get('recoil_control', False))
    if changed:
        _update_config_validated('weapon', 'recoil_control', new_recoil_control,
                                f"Recoil control {'enabled' if new_recoil_control else 'disabled'}")
        wpn['recoil_control'] = new_recoil_control
    
    changed, new_recoil_strength = gradient_slider_float(
        "Recoil Strength", wpn.get('recoil_strength', 0.5), 0.0, 1.0)
    if changed:
        _update_config_validated('weapon', 'recoil_strength', new_recoil_strength, "Recoil strength updated")
        wpn['recoil_strength'] = new_recoil_strength
    
    end_child_panel()


def _page_visuals_players(cfg, w, h, shared_state=None):
    """Page 3 — Player ESP.

    The legacy memory-based ESP backend was removed by the
    single-config-streamlining refactor (Req 4.2 / 4.10). The page now
    shows only the visual toggles for rendering player overlays; its
    former config section is no longer referenced.
    """
    vis = cfg.setdefault('visuals', {})

    styled_child_panel("Player ESP##L", w, h)

    section_header("ESP Settings")
    
    # Widget interactions with shared state updates
    changed, new_box_esp = styled_checkbox("Box ESP", vis.get('box_esp', True))
    if changed:
        _update_config_validated('visuals', 'box_esp', new_box_esp,
                                f"Box ESP {'enabled' if new_box_esp else 'disabled'}")
        vis['box_esp'] = new_box_esp
    
    changed, new_skeleton = styled_checkbox("Skeleton", vis.get('skeleton', False))
    if changed:
        _update_config_validated('visuals', 'skeleton', new_skeleton,
                                f"Skeleton {'enabled' if new_skeleton else 'disabled'}")
        vis['skeleton'] = new_skeleton
    
    changed, new_health_bar = styled_checkbox("Health Bar", vis.get('health_bar', True))
    if changed:
        _update_config_validated('visuals', 'health_bar', new_health_bar,
                                f"Health bar {'enabled' if new_health_bar else 'disabled'}")
        vis['health_bar'] = new_health_bar
    
    changed, new_name_tag = styled_checkbox("Name Tag", vis.get('name_tag', True))
    if changed:
        _update_config_validated('visuals', 'name_tag', new_name_tag,
                                f"Name tag {'enabled' if new_name_tag else 'disabled'}")
        vis['name_tag'] = new_name_tag
    
    changed, new_distance_tag = styled_checkbox("Distance", vis.get('distance_tag', False))
    if changed:
        _update_config_validated('visuals', 'distance_tag', new_distance_tag,
                                f"Distance tag {'enabled' if new_distance_tag else 'disabled'}")
        vis['distance_tag'] = new_distance_tag

    end_child_panel()


def _page_visuals_radar(cfg, w, h, shared_state=None):
    """Page 4 — Radar settings."""
    radar = cfg.setdefault('radar', {})
    styled_child_panel("Radar##L", w, h)
    
    changed, new_enabled = styled_checkbox("Enable Radar", radar.get('enabled', False))
    if changed:
        _update_config_validated('radar', 'enabled', new_enabled,
                                f"Radar {'enabled' if new_enabled else 'disabled'}")
        radar['enabled'] = new_enabled
    
    changed, new_zoom = gradient_slider_float("Radar Zoom", radar.get('zoom', 1.0), 0.5, 5.0)
    if changed:
        _update_config_validated('radar', 'zoom', new_zoom, "Radar zoom updated")
        radar['zoom'] = new_zoom
    
    end_child_panel()


def _page_visuals_world(cfg, w, h, shared_state=None):
    """Page 5 — World ESP."""
    world = cfg.setdefault('world', {})
    styled_child_panel("World ESP##L", w, h)
    
    changed, new_loot_esp = styled_checkbox("Loot ESP", world.get('loot_esp', False))
    if changed:
        _update_config_validated('world', 'loot_esp', new_loot_esp,
                                f"Loot ESP {'enabled' if new_loot_esp else 'disabled'}")
        world['loot_esp'] = new_loot_esp
    
    changed, new_vehicle_esp = styled_checkbox("Vehicle ESP", world.get('vehicle_esp', False))
    if changed:
        _update_config_validated('world', 'vehicle_esp', new_vehicle_esp,
                                f"Vehicle ESP {'enabled' if new_vehicle_esp else 'disabled'}")
        world['vehicle_esp'] = new_vehicle_esp
    
    end_child_panel()


def _page_misc(cfg, w, h, shared_state=None):
    """Page 6 — Miscellaneous."""
    global _error_handler
    misc = cfg.setdefault('misc', {})
    general = cfg.setdefault('general', {})
    styled_child_panel("Misc##L", w, h)
    
    # Activation Key State Indicators Section
    if shared_state:
        section_header("Key State Indicators")
        
        # Get key names from config
        activation_key_name = general.get('activation_key', 'CapsLock')
        panic_key_name = general.get('panic_key', 'F10')
        
        # Get key states
        activation_key_pressed = shared_state.get_state('activation_key_pressed', False)
        panic_key_pressed = shared_state.get_state('panic_key_pressed', False)
        
        # Activation Key Indicator with visual feedback
        imgui.text(f"Activation Key ({activation_key_name}):")
        imgui.same_line()
        
        # Visual feedback: Green when pressed, gray when released
        if activation_key_pressed:
            key_color = (0.3, 1.0, 0.3, 1.0)  # Bright green
            key_status = "● PRESSED"
        else:
            key_color = (0.5, 0.5, 0.5, 1.0)  # Gray
            key_status = "○ RELEASED"
        
        imgui.push_style_color(imgui.COLOR_TEXT, *key_color)
        imgui.text(key_status)
        imgui.pop_style_color()
        
        # Panic Key Indicator with visual feedback
        imgui.text(f"Panic Key ({panic_key_name}):")
        imgui.same_line()
        
        # Visual feedback: Red when pressed, gray when released
        if panic_key_pressed:
            panic_color = (1.0, 0.3, 0.3, 1.0)  # Bright red
            panic_status = "● PRESSED"
        else:
            panic_color = (0.5, 0.5, 0.5, 1.0)  # Gray
            panic_status = "○ RELEASED"
        
        imgui.push_style_color(imgui.COLOR_TEXT, *panic_color)
        imgui.text(panic_status)
        imgui.pop_style_color()
        
        separator_line()
    
    # Live performance metrics
    if shared_state:
        imgui.push_style_color(imgui.COLOR_TEXT, *TEXT_ACTIVE)
        imgui.text("Performance Metrics")
        imgui.pop_style_color()
        imgui.separator()
        
        # GUI frame time with color coding
        gui_frame_time_ms = shared_state.get_state('gui_frame_time_ms', 0.0)
        gui_fps = shared_state.get_state('gui_fps', 0.0)
        
        # Color code: Green <16.67ms (60+ FPS), Yellow <33.33ms (30+ FPS), Red >33.33ms
        if gui_frame_time_ms < 16.67:
            gui_perf_color = (0.3, 1.0, 0.3, 1.0)  # Green - excellent
        elif gui_frame_time_ms < 33.33:
            gui_perf_color = (1.0, 0.8, 0.3, 1.0)  # Yellow - acceptable
        else:
            gui_perf_color = (1.0, 0.3, 0.3, 1.0)  # Red - poor
        
        imgui.push_style_color(imgui.COLOR_TEXT, *gui_perf_color)
        imgui.text(f"GUI Frame: {gui_frame_time_ms:.2f}ms ({gui_fps:.0f} FPS)")
        imgui.pop_style_color()
        
        # Engine loop performance with color coding
        engine_loop_ms = shared_state.get_state('engine_loop_ms', 0.0)
        engine_hz = shared_state.get_state('engine_hz', 0.0)
        
        # Color code: Green <50ms, Yellow <100ms, Red >100ms
        if engine_loop_ms < 50.0:
            engine_perf_color = (0.3, 1.0, 0.3, 1.0)  # Green - excellent
        elif engine_loop_ms < 100.0:
            engine_perf_color = (1.0, 0.8, 0.3, 1.0)  # Yellow - acceptable
        else:
            engine_perf_color = (1.0, 0.3, 0.3, 1.0)  # Red - poor
        
        imgui.push_style_color(imgui.COLOR_TEXT, *engine_perf_color)
        imgui.text(f"Engine Loop: {engine_loop_ms:.2f}ms ({engine_hz:.0f} Hz)")
        imgui.pop_style_color()
        
        # Config update latency with color coding
        config_update_latency_ms = shared_state.get_state('config_update_latency_ms', 0.0)
        
        # Color code: Green <50ms, Yellow <100ms, Red >100ms
        if config_update_latency_ms < 50.0:
            config_perf_color = (0.3, 1.0, 0.3, 1.0)  # Green - excellent
        elif config_update_latency_ms < 100.0:
            config_perf_color = (1.0, 0.8, 0.3, 1.0)  # Yellow - acceptable
        else:
            config_perf_color = (1.0, 0.3, 0.3, 1.0)  # Red - poor
        
        imgui.push_style_color(imgui.COLOR_TEXT, *config_perf_color)
        imgui.text(f"Config Update: {config_update_latency_ms:.2f}ms")
        imgui.pop_style_color()
        
        # Recoil compensation
        recoil_offset = shared_state.get_state('recoil_offset', 0.0)
        imgui.text(f"Recoil Offset: {recoil_offset:.2f}")
        
        imgui.separator()
        imgui.spacing()
    
    # Debug mode toggle
    debug_mode = general.get('debug_mode', False)
    changed, new_debug_mode = styled_checkbox("Debug Mode", debug_mode)
    if changed:
        _update_config_validated('general', 'debug_mode', new_debug_mode,
                                f"Debug mode {'enabled' if new_debug_mode else 'disabled'}")
        general['debug_mode'] = new_debug_mode
    
    # Debug information display (when debug mode is enabled)
    if new_debug_mode and shared_state:
        separator_line()
        section_header("Debug Information")
        
        # Backend type (imgui_bundle or pyimgui)
        imgui.push_style_color(imgui.COLOR_TEXT, *TEXT_DEFAULT)
        imgui.text(f"Backend: {IMGUI_BACKEND}")
        imgui.pop_style_color()
        
        # Delta time for animation calculations
        from gui.widgets import _delta_time
        imgui.text(f"Delta Time: {_delta_time * 1000:.2f}ms ({1.0 / _delta_time:.1f} FPS)")
        
        # Active animation state count
        from gui.widgets import _anim_state
        anim_count = len(_anim_state)
        imgui.text(f"Animation States: {anim_count}")
        
        # Current tab index and page offset
        global _tabs
        if _tabs:
            imgui.text(f"Tab Index: {_tabs.current_idx}")
            imgui.text(f"Page Offset: {_tabs.page_offset:.1f}px")
        
        # Engine thread state (running/stopped/error)
        engine_thread_state = shared_state.get_state('engine_thread_state', 'unknown')
        
        # Color code engine thread state
        if engine_thread_state == 'running':
            thread_state_color = (0.3, 1.0, 0.3, 1.0)  # Green
        elif engine_thread_state == 'stopped':
            thread_state_color = (0.8, 0.8, 0.8, 1.0)  # Gray
        elif engine_thread_state == 'error':
            thread_state_color = (1.0, 0.3, 0.3, 1.0)  # Red
        else:
            thread_state_color = (1.0, 0.8, 0.3, 1.0)  # Yellow for unknown
        
        imgui.push_style_color(imgui.COLOR_TEXT, *thread_state_color)
        imgui.text(f"Engine Thread: {engine_thread_state.upper()}")
        imgui.pop_style_color()
        
        separator_line()
    
    # Engine Error Recovery Section
    if shared_state:
        separator_line()
        section_header("Engine Error Recovery")
        
        # Check for any disabled engines
        engines_to_check = [
            ('ai_engine', 'AI Engine'),
            ('target_tracker', 'Target Tracker'),
            ('aim_controller', 'Aim Controller'),
        ]
        
        any_disabled = False
        for engine_key, engine_label in engines_to_check:
            error_disabled = shared_state.get_state(f'{engine_key}_error_disabled', False)
            error_count = shared_state.get_state(f'{engine_key}_error_count', 0)
            last_error = shared_state.get_state(f'{engine_key}_last_error', '')
            
            if error_disabled:
                any_disabled = True
                
                # Display disabled engine with error info
                imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 0.3, 0.3, 1.0)
                imgui.text(f"● {engine_label}: DISABLED")
                imgui.pop_style_color()
                
                imgui.text(f"  Errors: {error_count}")
                
                # Show truncated error message
                if last_error:
                    display_error = last_error if len(last_error) <= 40 else last_error[:37] + "..."
                    imgui.text(f"  Last: {display_error}")
                    
                    # Show tooltip with full error on hover
                    if imgui.is_item_hovered() and len(last_error) > 40:
                        imgui.set_tooltip(last_error)
                
                # Restart button
                if styled_button(f"Restart {engine_label}##restart_{engine_key}"):
                    # Note: This would need to call coordinator.restart_engine()
                    # For now, we'll just update the shared state to signal restart
                    shared_state.update_state(f'{engine_key}_restart_requested', True)
                    notifications.add(f"{engine_label} restart requested", color=(0.3, 1.0, 0.3, 1.0))
                
                imgui.spacing()
            elif error_count > 0:
                # Show warning for engines with errors but not yet disabled
                imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 0.8, 0.3, 1.0)
                imgui.text(f"⚠ {engine_label}: {error_count} error(s)")
                imgui.pop_style_color()
                
                if last_error:
                    display_error = last_error if len(last_error) <= 40 else last_error[:37] + "..."
                    imgui.text(f"  Last: {display_error}")
                    
                    # Show tooltip with full error on hover
                    if imgui.is_item_hovered() and len(last_error) > 40:
                        imgui.set_tooltip(last_error)
                
                imgui.spacing()
        
        if not any_disabled:
            # Show all engines healthy
            imgui.push_style_color(imgui.COLOR_TEXT, 0.3, 1.0, 0.3, 1.0)
            imgui.text("✓ All engines operational")
            imgui.pop_style_color()
        
        imgui.separator()
        imgui.spacing()
    
    # Error display panel (shown in debug mode)
    debug_mode = general.get('debug_mode', False)
    if debug_mode and _error_handler:
        separator_line()
        imgui.push_style_color(imgui.COLOR_TEXT, *TEXT_ACTIVE)
        imgui.text("Error Log (Recent 10)")
        imgui.pop_style_color()
        imgui.separator()
        
        # Get recent errors from error handler
        recent_errors = _error_handler.get_recent_errors(10)
        
        if not recent_errors:
            imgui.text("  No errors logged")
        else:
            for error in recent_errors:
                # Format timestamp
                timestamp = time.strftime('%H:%M:%S', time.localtime(error['timestamp']))
                engine = error['engine']
                error_type = error['type']
                message = error['message']
                
                # Color code by error type
                if error_type in ['ValueError', 'TypeError', 'KeyError']:
                    error_color = (1.0, 0.8, 0.3, 1.0)  # Yellow for validation errors
                else:
                    error_color = (1.0, 0.3, 0.3, 1.0)  # Red for other errors
                
                imgui.push_style_color(imgui.COLOR_TEXT, *error_color)
                imgui.text(f"[{timestamp}] {engine}")
                imgui.pop_style_color()
                
                # Show truncated message (max 50 chars)
                display_msg = message if len(message) <= 50 else message[:47] + "..."
                imgui.text(f"  {display_msg}")
                
                # Show tooltip with full message on hover
                if imgui.is_item_hovered() and len(message) > 50:
                    imgui.set_tooltip(message)
        
        # Clear error log button
        if styled_button("Clear Error Log"):
            _error_handler.clear_error_log()
            notifications.add("Error log cleared", color=(0.3, 1.0, 0.3, 1.0))
        
        # Show error log file path
        imgui.text(f"Log file: {_error_handler.get_error_log_path()}")
        
        imgui.separator()
        imgui.spacing()
    
    # Last error display (always shown if there's an error)
    if shared_state:
        last_error = shared_state.get_state('last_error', '')
        if last_error:
            separator_line()
            imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 0.3, 0.3, 1.0)
            imgui.text("Last Error:")
            imgui.text_wrapped(last_error)
            imgui.pop_style_color()
            imgui.separator()
            imgui.spacing()
    
    # Widget interactions with shared state updates
    changed, new_no_recoil = styled_checkbox("No Recoil", misc.get('no_recoil', False))
    if changed:
        _update_config_validated('misc', 'no_recoil', new_no_recoil,
                                f"No recoil {'enabled' if new_no_recoil else 'disabled'}")
        misc['no_recoil'] = new_no_recoil
    
    changed, new_rapid_fire = styled_checkbox("Rapid Fire", misc.get('rapid_fire', False))
    if changed:
        _update_config_validated('misc', 'rapid_fire', new_rapid_fire,
                                f"Rapid fire {'enabled' if new_rapid_fire else 'disabled'}")
        misc['rapid_fire'] = new_rapid_fire
    
    end_child_panel()


def _page_exploits(cfg, w, h, shared_state=None):
    """Page 7 — Exploits."""
    styled_child_panel("Exploits##L", w, h)
    imgui.text("No exploits available.")
    end_child_panel()


def _render_kmbox_panel(shared_state) -> None:
    """Render the KmBox Net Status panel (Req 7.1–7.6, 7.7, 7.8, 7.10).

    Reads ``kmbox_*`` keys from ``SharedState`` every render frame — no
    caching. The publisher in ``main.DetectionFramework._publish_kmbox_state``
    writes ``ConnectionStatus.value`` strings (Req 6.1) or the literal
    ``"no data"`` when no driver is bound. The GUI renders whatever is in
    the snapshot and never calls ``kmNet.*`` directly (Req 7.9).

    Extracted into a free function so the GUI test harness can drive the
    panel directly with a captured ``imgui`` mock and a populated
    ``SharedState``, without spinning up the full hello_imgui loop.
    """
    section_header("KmBox Net Status")

    # ── Status indicator dot + label ──
    # Theme color mapping per design table:
    #   connected     → success (green)
    #   reconnecting  → warning (yellow)
    #   failed        → error   (red)
    #   anything else → literal text "no data" with no color highlight
    # (Req 7.4, 7.5, 7.6, 7.10)
    kmbox_status = shared_state.get_state('kmbox_status', 'no data')

    if kmbox_status == 'connected':
        imgui.push_style_color(imgui.COLOR_TEXT, 0.3, 1.0, 0.3, 1.0)
        imgui.text(f"● {kmbox_status}")
        imgui.pop_style_color()
    elif kmbox_status == 'reconnecting':
        imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 0.8, 0.3, 1.0)
        imgui.text(f"● {kmbox_status}")
        imgui.pop_style_color()
    elif kmbox_status == 'failed':
        imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 0.3, 0.3, 1.0)
        imgui.text(f"● {kmbox_status}")
        imgui.pop_style_color()
    else:
        # Req 7.10 — anything outside the three mapped values renders the
        # literal text "no data" with no color highlight (no driver entry,
        # disconnected/connecting transitional states, or unknown values).
        imgui.text("no data")

    # ── IP / Port / Encryption labels ──
    # Re-read every render frame (Req 7.2, 7.3). The publisher writes the
    # literal string "no data" for ip/port/use_encryption when no driver is
    # bound; we render whatever is in the snapshot. For encryption we show
    # True/False when the value is a bool, else "no data" (covers the
    # no-driver case where the publisher writes a string).
    kmbox_ip = shared_state.get_state('kmbox_ip', 'no data')
    kmbox_port = shared_state.get_state('kmbox_port', 'no data')
    kmbox_use_encryption = shared_state.get_state('kmbox_use_encryption', 'no data')

    imgui.text(f"  IP: {kmbox_ip}")
    imgui.text(f"  Port: {kmbox_port}")

    if isinstance(kmbox_use_encryption, bool):
        imgui.text(f"  Encryption: {kmbox_use_encryption}")
    else:
        imgui.text("  Encryption: no data")

    # ── Reconnect button (Req 7.7 / 7.8) ──
    # On click, spawn a short-lived daemon ``Thread(name="KmBoxReconnect")``
    # that calls ``driver._connect()`` off the render thread (``_connect()``
    # can block up to 5 s waiting for ``kmNet.init``). The worker reports
    # failure through ``SharedState["kmbox_reconnect_error"]`` (Req 7.8);
    # the render path below polls that key and renders a banner.
    #
    # The render thread NEVER calls ``_connect()`` directly and NEVER
    # invokes any ``kmNet.*`` function (Req 7.9). The only render-thread
    # work here is reading the registered driver reference and starting
    # the daemon thread.
    if styled_button("Reconnect"):
        _on_kmbox_reconnect_clicked()

    # Reconnect-error banner (Req 7.8). The worker writes a string here
    # when the attempt fails or there is no driver registered; we render it
    # inline below the button so the operator notices it without needing to
    # watch the toast queue. The banner is cleared by a successful
    # reconnect (worker writes ``None``).
    kmbox_reconnect_error = shared_state.get_state(
        'kmbox_reconnect_error', None
    )
    if kmbox_reconnect_error:
        imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 0.3, 0.3, 1.0)
        imgui.text(f"⚠ {kmbox_reconnect_error}")
        imgui.pop_style_color()

    separator_line()


def _page_configuration(cfg, w, h, shared_state=None):
    """Page 8 — Config management with preset support."""
    global _error_handler
    from gui.config_manager import (
        list_presets, save_live_config_auto, save_preset, 
        load_preset, delete_preset
    )
    
    # Static variables for preset name input and delete confirmation
    if not hasattr(_page_configuration, '_preset_name_buffer'):
        _page_configuration._preset_name_buffer = ""
        _page_configuration._show_save_dialog = False
        _page_configuration._delete_confirm_preset = None
        _page_configuration._show_reset_confirm = False
    
    styled_child_panel("Configuration##L", w, h)
    
    # System Status Section
    if shared_state:
        section_header("System Status")
        
        # Capture Backend status
        capture_backend = shared_state.get_state('capture_backend', 'unknown')
        capture_active = shared_state.get_state('capture_active', False)
        capture_fps = shared_state.get_state('fps', 0.0)
        
        # Color: Green if active and FPS > 30, Yellow if active but FPS < 30, Red if inactive
        if capture_active:
            if capture_fps >= 30:
                capture_status_color = (0.3, 1.0, 0.3, 1.0)  # Green - good performance
            else:
                capture_status_color = (1.0, 0.8, 0.3, 1.0)  # Yellow - poor performance
            capture_status_text = f"ACTIVE ({capture_backend.upper()})"
        else:
            capture_status_color = (1.0, 0.3, 0.3, 1.0)  # Red - inactive
            capture_status_text = "INACTIVE"
        
        imgui.push_style_color(imgui.COLOR_TEXT, *capture_status_color)
        imgui.text(f"● Capture Backend: {capture_status_text}")
        imgui.pop_style_color()
        
        if capture_active:
            imgui.text(f"  FPS: {capture_fps:.1f}")
            capture_resolution = shared_state.get_state('capture_resolution', 'unknown')
            imgui.text(f"  Resolution: {capture_resolution}")
        
        # Input Driver status
        input_driver = shared_state.get_state('input_driver', 'unknown')
        input_active = shared_state.get_state('input_active', False)
        input_error_count = shared_state.get_state('input_error_count', 0)
        
        # Color: Green if active and no errors, Yellow if active with errors, Red if inactive
        if input_active:
            if input_error_count == 0:
                input_status_color = (0.3, 1.0, 0.3, 1.0)  # Green - working well
            else:
                input_status_color = (1.0, 0.8, 0.3, 1.0)  # Yellow - has errors
            input_status_text = f"ACTIVE ({input_driver.upper()})"
        else:
            input_status_color = (1.0, 0.3, 0.3, 1.0)  # Red - inactive
            input_status_text = "INACTIVE"
        
        imgui.push_style_color(imgui.COLOR_TEXT, *input_status_color)
        imgui.text(f"● Input Driver: {input_status_text}")
        imgui.pop_style_color()
        
        if input_active and input_error_count > 0:
            imgui.text(f"  Errors: {input_error_count}")
        
        separator_line()

    # KmBox Net Status Section (Req 7.1–7.6, 7.7, 7.8, 7.10)
    if shared_state:
        _render_kmbox_panel(shared_state)

    # Conflict Detection Section
    if _error_handler and shared_state:
        section_header("Conflict Detection")
        
        # Get current config and check for conflicts
        current_config = shared_state.get_config()
        conflicts = _error_handler.detect_conflicts(current_config)
        
        if conflicts:
            # Display conflicts with warning color
            imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 0.5, 0.3, 1.0)
            imgui.text(f"⚠ {len(conflicts)} conflict(s) detected:")
            imgui.pop_style_color()
            
            for conflict in conflicts:
                imgui.text(f"  • {conflict}")
            
            imgui.spacing()
        else:
            # No conflicts - show success message
            imgui.push_style_color(imgui.COLOR_TEXT, 0.3, 1.0, 0.3, 1.0)
            imgui.text("✓ No conflicts detected")
            imgui.pop_style_color()
        
        separator_line()
    
    # Check for unsaved changes
    has_unsaved_changes = False
    if shared_state:
        has_unsaved_changes = shared_state.check_and_clear_modified()
        # Re-set the flag since we're just checking, not clearing
        if has_unsaved_changes:
            with shared_state._config_lock:
                shared_state._config_modified = True
    
    # Save Config button with unsaved changes indicator
    save_label = "Save Config"
    if has_unsaved_changes:
        save_label = "Save Config *"  # Asterisk indicates unsaved changes
    
    if styled_button(save_label):
        if shared_state:
            # Notification is now handled by save_live_config_auto()
            save_live_config_auto(shared_state)
        else:
            notifications.add("No shared state available!", color=(1.0, 0.5, 0.3, 1.0))
    
    imgui.same_line()
    
    # Save as Preset button
    if styled_button("Save as Preset"):
        _page_configuration._show_save_dialog = True
        _page_configuration._preset_name_buffer = ""
    
    imgui.same_line()
    
    # Reset to Defaults button
    if styled_button("Reset to Defaults"):
        _page_configuration._show_reset_confirm = True
    
    # Unsaved changes indicator (dot)
    if has_unsaved_changes:
        imgui.same_line()
        imgui.text_colored((1.0, 0.8, 0.3, 1.0), "●")
        if imgui.is_item_hovered():
            imgui.set_tooltip("Unsaved changes")
    
    imgui.separator()
    
    # Reset to Defaults confirmation dialog
    if _page_configuration._show_reset_confirm:
        imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 0.5, 0.3, 1.0)
        imgui.text("⚠ Reset all settings to defaults?")
        imgui.pop_style_color()
        imgui.text("This will overwrite all current settings.")
        
        if styled_button("Yes, Reset##reset_confirm"):
            if shared_state and _error_handler:
                # Get default config
                default_config = _error_handler.get_default_config()
                
                # Apply all defaults to shared state
                for section, values in default_config.items():
                    for key, value in values.items():
                        shared_state.update_config(section, key, value)
                
                # Update local config dict
                cfg.clear()
                cfg.update(default_config)
                
                notifications.add("Configuration reset to defaults!", color=(0.3, 1.0, 0.3, 1.0))
                _page_configuration._show_reset_confirm = False
            else:
                notifications.add("Cannot reset: error handler not available!", color=(1.0, 0.3, 0.3, 1.0))
        
        imgui.same_line()
        
        if styled_button("Cancel##reset_cancel"):
            _page_configuration._show_reset_confirm = False
        
        imgui.separator()
    
    # Save as Preset dialog
    if _page_configuration._show_save_dialog:
        imgui.text("Preset Name:")
        changed, new_buffer = imgui.input_text(
            "##preset_name_input", 
            _page_configuration._preset_name_buffer, 
            256
        )
        if changed:
            _page_configuration._preset_name_buffer = new_buffer
        
        if styled_button("Save##save_preset"):
            preset_name = _page_configuration._preset_name_buffer.strip()
            
            # Validate preset name
            if not preset_name:
                notifications.add("Preset name cannot be empty!", color=(1.0, 0.5, 0.3, 1.0))
            elif any(c in preset_name for c in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']):
                notifications.add("Invalid characters in preset name!", color=(1.0, 0.5, 0.3, 1.0))
            else:
                if shared_state:
                    # Notification is now handled by save_preset()
                    success = save_preset(preset_name, shared_state)
                    if success:
                        _page_configuration._show_save_dialog = False
                else:
                    notifications.add("No shared state available!", color=(1.0, 0.5, 0.3, 1.0))
        
        imgui.same_line()
        
        if styled_button("Cancel##cancel_preset"):
            _page_configuration._show_save_dialog = False
        
        imgui.separator()
    
    # Preset list
    imgui.text("Saved Presets:")
    presets = list_presets()
    
    if not presets:
        imgui.text("  (No presets saved)")
    else:
        for preset_name in presets:
            imgui.text(f"  • {preset_name}")
            imgui.same_line()
            
            # Load button
            if styled_button(f"Load##{preset_name}_load"):
                if shared_state:
                    # Notification is now handled by load_preset()
                    load_preset(preset_name, shared_state)
                else:
                    notifications.add("No shared state available!", color=(1.0, 0.5, 0.3, 1.0))
            
            imgui.same_line()
            
            # Delete button
            if styled_button(f"Delete##{preset_name}_delete"):
                _page_configuration._delete_confirm_preset = preset_name
            
            # Delete confirmation dialog
            if _page_configuration._delete_confirm_preset == preset_name:
                imgui.same_line()
                imgui.text_colored((1.0, 0.5, 0.3, 1.0), "Confirm?")
                imgui.same_line()
                
                if styled_button(f"Yes##{preset_name}_confirm"):
                    success = delete_preset(preset_name)
                    if success:
                        notifications.add(f"Preset '{preset_name}' deleted!", color=(0.3, 1.0, 0.3, 1.0))
                    else:
                        notifications.add(f"Failed to delete preset '{preset_name}'!", color=(1.0, 0.3, 0.3, 1.0))
                    _page_configuration._delete_confirm_preset = None
                
                imgui.same_line()
                
                if styled_button(f"No##{preset_name}_cancel"):
                    _page_configuration._delete_confirm_preset = None
    
    end_child_panel()
    
    imgui.same_line(0, 12)
    
    # Right panel - Keybind Configuration
    styled_child_panel("Keybind Configuration##R", w, h)
    
    section_header("Keybind Settings")
    
    # Get current keybinds from config
    general = cfg.setdefault('general', {})
    activation_key = general.get('activation_key', 'CapsLock')
    panic_key = general.get('panic_key', 'F10')
    
    # Build keybind dict for duplicate detection
    all_keybinds = {
        'Activation Key': activation_key,
        'Panic Key': panic_key,
    }
    
    # Import keybind functions from widgets
    from gui.widgets import keybind_button, capture_key_input, is_capturing_keybind
    
    # Activation Key
    changed, new_activation_key = keybind_button("Activation Key", activation_key, all_keybinds)
    if changed:
        _update_config_validated('general', 'activation_key', new_activation_key,
                                f"Activation key set to {new_activation_key}")
        general['activation_key'] = new_activation_key
    
    # Panic Key
    changed, new_panic_key = keybind_button("Panic Key", panic_key, all_keybinds)
    if changed:
        _update_config_validated('general', 'panic_key', new_panic_key,
                                f"Panic key set to {new_panic_key}")
        general['panic_key'] = new_panic_key
    
    # Process key capture input (must be called every frame when capture is active)
    if is_capturing_keybind():
        capture_key_input()
    
    separator_line()
    
    # Keybind status display
    if shared_state:
        section_header("Keybind Status")
        
        # Activation key state
        activation_pressed = shared_state.get_state('activation_key_pressed', False)
        activation_color = (0.3, 1.0, 0.3, 1.0) if activation_pressed else TEXT_DEFAULT
        imgui.push_style_color(imgui.COLOR_TEXT, *activation_color)
        imgui.text(f"● Activation Key: {'PRESSED' if activation_pressed else 'RELEASED'}")
        imgui.pop_style_color()
        
        # Panic key state
        panic_pressed = shared_state.get_state('panic_key_pressed', False)
        panic_color = (1.0, 0.3, 0.3, 1.0) if panic_pressed else TEXT_DEFAULT
        imgui.push_style_color(imgui.COLOR_TEXT, *panic_color)
        imgui.text(f"● Panic Key: {'PRESSED' if panic_pressed else 'RELEASED'}")
        imgui.pop_style_color()
    
    imgui.spacing()
    imgui.text("Keybind Help:")
    imgui.text("  • Click a keybind button to capture")
    imgui.text("  • Press any key or mouse button")
    imgui.text("  • System keys (Escape) are blocked")
    imgui.text("  • Duplicate binds are prevented")
    
    end_child_panel()


# ─── Entry Point ──────────────────────────────────────────────────

def run(shared_state=None, shared_config=None):
    """
    Main entry point — called from main.py on the main thread.

    Args:
        shared_state: SharedState instance for bidirectional data flow (new pattern).
        shared_config: Live config dict shared with engine thread (legacy pattern).
    """
    global _config, _shared_state, _error_handler
    from config import load_config

    # Store shared state reference for callback access
    _shared_state = shared_state
    
    # Initialize error handler if shared state is available
    if _shared_state:
        _error_handler = ErrorHandler(_shared_state)

    # Initialize config dict (legacy pattern support)
    _config = shared_config if shared_config is not None else {}

    # Load initial config from config.yaml into shared state
    if _shared_state is not None:
        config = load_config()
        for section, values in config.items():
            if isinstance(values, dict):
                for key, value in values.items():
                    _shared_state.update_config(section, key, value)

    _init_tabs()

    if IMGUI_BACKEND == "imgui_bundle":
        _run_imgui_bundle()
    else:
        _run_fallback_glfw()


def _run_imgui_bundle():
    """Run using imgui_bundle's hello_imgui framework."""
    from imgui_bundle import hello_imgui, immapp

    params = hello_imgui.RunnerParams()

    # Window config
    params.app_window_params.window_title = WINDOW_TITLE
    params.app_window_params.window_geometry.size = (WINDOW_W, WINDOW_H)
    params.app_window_params.restore_previous_geometry = False

    # No menu/status bar — LianFlow is fully custom-drawn
    params.imgui_window_params.show_menu_bar = False
    params.imgui_window_params.show_status_bar = False
    params.imgui_window_params.default_imgui_window_type = (
        hello_imgui.DefaultImGuiWindowType.no_default_window
    )

    # Callbacks
    params.callbacks.show_gui = _show_gui
    params.callbacks.post_init = _post_init

    # Performance — don't idle, we have animations
    params.fps_idling.enable_idling = False

    # Run
    immapp.run(params)


def _run_fallback_glfw():
    """Fallback raw GLFW loop for pyimgui or stub backend."""
    try:
        import glfw
    except ImportError:
        print("[GUI] CRITICAL: Neither imgui_bundle nor glfw available.")
        print("[GUI] Install with: pip install imgui-bundle")
        return

    if not glfw.init():
        print("[GUI] CRITICAL: GLFW init failed")
        return

    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
    glfw.window_hint(glfw.RESIZABLE, False)

    window = glfw.create_window(WINDOW_W, WINDOW_H, WINDOW_TITLE, None, None)
    if not window:
        glfw.terminate()
        print("[GUI] CRITICAL: Window creation failed")
        return

    glfw.make_context_current(window)
    glfw.swap_interval(1)

    imgui.create_context()
    apply_tuborg_lianflow_theme()
    _init_tabs()

    try:
        from imgui.integrations.glfw import GlfwRenderer
        renderer = GlfwRenderer(window)
    except Exception:
        print("[GUI] WARNING: No renderer — running headless")
        glfw.terminate()
        return

    try:
        from OpenGL import GL as gl
        while not glfw.window_should_close(window):
            glfw.poll_events()
            renderer.process_inputs()
            imgui.new_frame()
            update_delta_time()

            _show_gui()

            imgui.render()
            gl.glClearColor(0, 0, 0, 1)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
            renderer.render(imgui.get_draw_data())
            glfw.swap_buffers(window)
    except KeyboardInterrupt:
        pass
    finally:
        renderer.shutdown()
        glfw.destroy_window(window)
        glfw.terminate()
