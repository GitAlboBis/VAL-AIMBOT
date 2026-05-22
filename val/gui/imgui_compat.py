"""
Tuborg ImGui Compatibility Shim — auto-detect imgui_bundle vs pyimgui.

Provides a unified `imgui` namespace with pyimgui-style API so widgets.py
and theme.py work unchanged with either backend.

Key translations for imgui_bundle:
  - push_style_color(idx, r, g, b, a) -> push_style_color(idx, ImVec4)
  - text_colored(text, r, g, b, a)    -> text_colored(ImVec4, text)
  - begin_child(label, w, h, border)  -> begin_child(str_id, ImVec2, flags)
  - COLOR_TEXT, STYLE_*, WINDOW_*     -> Col_, StyleVar_, WindowFlags_ .value
"""

import sys
import types

# ── Backend detection ─────────────────────────────────────────────

_USE_BUNDLE = False
_USE_PYIMGUI = False

try:
    import imgui_bundle  # noqa: F401
    _USE_BUNDLE = True
except ImportError:
    pass

if not _USE_BUNDLE:
    try:
        import imgui as _raw_imgui  # noqa: F401
        _USE_PYIMGUI = True
    except ImportError:
        pass

if _USE_BUNDLE:
    IMGUI_BACKEND = "imgui_bundle"
    BACKEND = "imgui_bundle"
elif _USE_PYIMGUI:
    IMGUI_BACKEND = "pyimgui"
    BACKEND = "pyimgui"
else:
    IMGUI_BACKEND = "none"
    BACKEND = "none"


# ── imgui_bundle wrapper ─────────────────────────────────────────

if _USE_BUNDLE:
    from imgui_bundle import imgui as _ib

    class _ImguiCompat:
        """
        Wraps imgui_bundle to provide pyimgui-compatible API.

        - Constants: COLOR_TEXT, STYLE_FRAME_ROUNDING, WINDOW_NO_TITLE_BAR, etc.
        - Functions: push_style_color(idx, r,g,b,a), text_colored(text, r,g,b,a), etc.
        - Passthrough: any attribute not explicitly wrapped is delegated to imgui_bundle.
        """

        # ── Color constants (pyimgui-style) ──
        COLOR_TEXT = _ib.Col_.text.value
        COLOR_TEXT_DISABLED = _ib.Col_.text_disabled.value
        COLOR_WINDOW_BACKGROUND = _ib.Col_.window_bg.value
        COLOR_CHILD_BACKGROUND = _ib.Col_.child_bg.value
        COLOR_POPUP_BACKGROUND = _ib.Col_.popup_bg.value
        COLOR_BORDER = _ib.Col_.border.value
        COLOR_BORDER_SHADOW = _ib.Col_.border_shadow.value
        COLOR_FRAME_BACKGROUND = _ib.Col_.frame_bg.value
        COLOR_FRAME_BACKGROUND_HOVERED = _ib.Col_.frame_bg_hovered.value
        COLOR_FRAME_BACKGROUND_ACTIVE = _ib.Col_.frame_bg_active.value
        COLOR_TITLE_BACKGROUND = _ib.Col_.title_bg.value
        COLOR_TITLE_BACKGROUND_ACTIVE = _ib.Col_.title_bg_active.value
        COLOR_TITLE_BACKGROUND_COLLAPSED = _ib.Col_.title_bg_collapsed.value
        COLOR_MENUBAR_BACKGROUND = _ib.Col_.menu_bar_bg.value
        COLOR_SCROLLBAR_BACKGROUND = _ib.Col_.scrollbar_bg.value
        COLOR_SCROLLBAR_GRAB = _ib.Col_.scrollbar_grab.value
        COLOR_SCROLLBAR_GRAB_HOVERED = _ib.Col_.scrollbar_grab_hovered.value
        COLOR_SCROLLBAR_GRAB_ACTIVE = _ib.Col_.scrollbar_grab_active.value
        COLOR_CHECK_MARK = _ib.Col_.check_mark.value
        COLOR_SLIDER_GRAB = _ib.Col_.slider_grab.value
        COLOR_SLIDER_GRAB_ACTIVE = _ib.Col_.slider_grab_active.value
        COLOR_BUTTON = _ib.Col_.button.value
        COLOR_BUTTON_HOVERED = _ib.Col_.button_hovered.value
        COLOR_BUTTON_ACTIVE = _ib.Col_.button_active.value
        COLOR_HEADER = _ib.Col_.header.value
        COLOR_HEADER_HOVERED = _ib.Col_.header_hovered.value
        COLOR_HEADER_ACTIVE = _ib.Col_.header_active.value
        COLOR_SEPARATOR = _ib.Col_.separator.value
        COLOR_SEPARATOR_HOVERED = _ib.Col_.separator_hovered.value
        COLOR_SEPARATOR_ACTIVE = _ib.Col_.separator_active.value
        COLOR_RESIZE_GRIP = _ib.Col_.resize_grip.value
        COLOR_RESIZE_GRIP_HOVERED = _ib.Col_.resize_grip_hovered.value
        COLOR_RESIZE_GRIP_ACTIVE = _ib.Col_.resize_grip_active.value
        COLOR_TAB = _ib.Col_.tab.value
        COLOR_TAB_HOVERED = _ib.Col_.tab_hovered.value
        COLOR_TAB_ACTIVE = _ib.Col_.tab_selected.value
        COLOR_TAB_UNFOCUSED = _ib.Col_.tab_dimmed.value
        COLOR_TAB_UNFOCUSED_ACTIVE = _ib.Col_.tab_dimmed_selected.value
        COLOR_NAV_HIGHLIGHT = _ib.Col_.nav_cursor.value

        # ── Style variable constants ──
        STYLE_ALPHA = _ib.StyleVar_.alpha.value
        STYLE_WINDOW_PADDING = _ib.StyleVar_.window_padding.value
        STYLE_WINDOW_ROUNDING = _ib.StyleVar_.window_rounding.value
        STYLE_WINDOW_BORDER_SIZE = _ib.StyleVar_.window_border_size.value
        STYLE_WINDOW_MIN_SIZE = _ib.StyleVar_.window_min_size.value
        STYLE_CHILD_ROUNDING = _ib.StyleVar_.child_rounding.value
        STYLE_CHILD_BORDER_SIZE = _ib.StyleVar_.child_border_size.value
        STYLE_POPUP_ROUNDING = _ib.StyleVar_.popup_rounding.value
        STYLE_POPUP_BORDER_SIZE = _ib.StyleVar_.popup_border_size.value
        STYLE_FRAME_PADDING = _ib.StyleVar_.frame_padding.value
        STYLE_FRAME_ROUNDING = _ib.StyleVar_.frame_rounding.value
        STYLE_FRAME_BORDER_SIZE = _ib.StyleVar_.frame_border_size.value
        STYLE_ITEM_SPACING = _ib.StyleVar_.item_spacing.value
        STYLE_ITEM_INNER_SPACING = _ib.StyleVar_.item_inner_spacing.value
        STYLE_INDENT_SPACING = _ib.StyleVar_.indent_spacing.value
        STYLE_SCROLLBAR_SIZE = _ib.StyleVar_.scrollbar_size.value
        STYLE_SCROLLBAR_ROUNDING = _ib.StyleVar_.scrollbar_rounding.value
        STYLE_GRAB_MIN_SIZE = _ib.StyleVar_.grab_min_size.value
        STYLE_GRAB_ROUNDING = _ib.StyleVar_.grab_rounding.value
        STYLE_TAB_ROUNDING = _ib.StyleVar_.tab_rounding.value

        # ── Window flags ──
        WINDOW_NO_TITLE_BAR = _ib.WindowFlags_.no_title_bar.value
        WINDOW_NO_RESIZE = _ib.WindowFlags_.no_resize.value
        WINDOW_NO_MOVE = _ib.WindowFlags_.no_move.value
        WINDOW_NO_SCROLLBAR = _ib.WindowFlags_.no_scrollbar.value
        WINDOW_NO_SCROLL_WITH_MOUSE = _ib.WindowFlags_.no_scroll_with_mouse.value
        WINDOW_NO_COLLAPSE = _ib.WindowFlags_.no_collapse.value
        WINDOW_NO_BACKGROUND = _ib.WindowFlags_.no_background.value
        WINDOW_NO_SAVED_SETTINGS = _ib.WindowFlags_.no_saved_settings.value
        WINDOW_NO_FOCUS_ON_APPEARING = _ib.WindowFlags_.no_focus_on_appearing.value
        WINDOW_ALWAYS_AUTO_RESIZE = _ib.WindowFlags_.always_auto_resize.value

        # ── Key constants ──
        try:
            KEY_INSERT = _ib.Key.insert.value
        except Exception:
            KEY_INSERT = 0x2D

        # ── API wrappers ──

        @staticmethod
        def push_style_color(idx, *args):
            """push_style_color(idx, r, g, b, a) or push_style_color(idx, ImVec4)."""
            if len(args) == 4:
                _ib.push_style_color(idx, _ib.ImVec4(*args))
            elif len(args) == 1 and isinstance(args[0], _ib.ImVec4):
                _ib.push_style_color(idx, args[0])
            else:
                _ib.push_style_color(idx, *args)

        @staticmethod
        def text_colored(text_or_color, *args):
            """
            Supports both calling conventions:
              text_colored(text, r, g, b, a)   — pyimgui style
              text_colored(ImVec4, text)        — imgui_bundle style
            """
            if isinstance(text_or_color, str) and len(args) >= 3:
                # pyimgui: text_colored("hello", r, g, b, a)
                r, g, b = args[0], args[1], args[2]
                a = args[3] if len(args) > 3 else 1.0
                _ib.text_colored(_ib.ImVec4(r, g, b, a), text_or_color)
            elif isinstance(text_or_color, _ib.ImVec4) and len(args) >= 1:
                # imgui_bundle native: text_colored(ImVec4, text)
                _ib.text_colored(text_or_color, args[0])
            else:
                _ib.text_colored(text_or_color, *args)

        @staticmethod
        def begin_child(label, width=0.0, height=0.0, border=False, flags=0):
            """begin_child(label, w, h, border, flags) — pyimgui-compatible."""
            child_flags = 0
            if border:
                child_flags |= _ib.ChildFlags_.borders.value
            return _ib.begin_child(label, _ib.ImVec2(width, height), child_flags, flags)

        @staticmethod
        def set_next_window_position(x, y, cond=0, pivot_x=0, pivot_y=0):
            """pyimgui-compatible set_next_window_position."""
            _ib.set_next_window_pos(_ib.ImVec2(x, y), cond)

        @staticmethod
        def set_next_window_size(w, h, cond=0):
            """pyimgui-compatible set_next_window_size."""
            _ib.set_next_window_size(_ib.ImVec2(w, h), cond)

        @staticmethod
        def set_cursor_pos(pos):
            """Accept tuple (x,y) or ImVec2."""
            if isinstance(pos, (tuple, list)):
                _ib.set_cursor_pos(_ib.ImVec2(pos[0], pos[1]))
            else:
                _ib.set_cursor_pos(pos)

        @staticmethod
        def get_content_region_available_width():
            """pyimgui-compatible — returns just the x component."""
            return _ib.get_content_region_avail().x

        @staticmethod
        def push_style_var(idx, *args):
            """push_style_var(idx, val) or push_style_var(idx, x, y)."""
            if len(args) == 2:
                _ib.push_style_var(idx, _ib.ImVec2(args[0], args[1]))
            else:
                _ib.push_style_var(idx, args[0])

        @staticmethod
        def get_color_u32_rgba(r, g, b, a=1.0):
            """Helper to convert RGBA floats to u32."""
            return _ib.get_color_u32(_ib.ImVec4(r, g, b, a))

        @staticmethod
        def color_edit3(label, r, g, b, flags=0):
            """pyimgui-compatible color_edit3."""
            changed, color = _ib.color_edit3(label, [r, g, b], flags)
            return changed, tuple(color)

        @staticmethod
        def color_edit4(label, r, g, b, a, flags=0):
            """pyimgui-compatible color_edit4."""
            changed, color = _ib.color_edit4(label, [r, g, b, a], flags)
            return changed, tuple(color)

        @staticmethod
        def slider_float(label, value, min_val, max_val, fmt="%.3f", flags=0):
            """pyimgui-compatible slider_float — returns (changed, value)."""
            changed, new_val = _ib.slider_float(label, value, min_val, max_val, fmt, flags)
            return changed, new_val

        @staticmethod
        def slider_int(label, value, min_val, max_val, fmt="%d", flags=0):
            """pyimgui-compatible slider_int — returns (changed, value)."""
            changed, new_val = _ib.slider_int(label, value, min_val, max_val, fmt, flags)
            return changed, new_val

        @staticmethod
        def checkbox(label, state):
            """pyimgui-compatible checkbox — returns (changed, value)."""
            changed, new_val = _ib.checkbox(label, state)
            return changed, new_val

        @staticmethod
        def combo(label, current_item, items, height_in_items=-1):
            """pyimgui-compatible combo — returns (changed, current)."""
            # imgui_bundle wants items as a list
            if isinstance(items, (list, tuple)):
                items_list = list(items)
            else:
                items_list = items
            items_str = "\0".join(str(i) for i in items_list) + "\0"
            changed, new_idx = _ib.combo(label, current_item, items_list, height_in_items)
            return changed, new_idx

        @staticmethod
        def input_text(label, value, buffer_size=256, flags=0):
            """pyimgui-compatible input_text — returns (changed, value)."""
            changed, new_val = _ib.input_text(label, value, flags)
            return changed, new_val

        @staticmethod
        def button(label, width=0, height=0):
            """pyimgui-compatible button."""
            return _ib.button(label, _ib.ImVec2(width, height))

        @staticmethod
        def is_key_pressed(key, repeat=True):
            """pyimgui-compatible is_key_pressed."""
            return _ib.is_key_pressed(_ib.Key(key), repeat)

        def __getattr__(self, name):
            """Delegate anything not explicitly wrapped to imgui_bundle.imgui."""
            return getattr(_ib, name)

    imgui = _ImguiCompat()
    GlfwRenderer = None  # imgui_bundle uses hello_imgui, not raw GLFW

elif _USE_PYIMGUI:
    import imgui as imgui  # noqa: F811

    try:
        from imgui.integrations.glfw import GlfwRenderer
    except ImportError:
        try:
            from imgui.integrations.opengl import ProgrammablePipelineRenderer as GlfwRenderer
        except ImportError:
            GlfwRenderer = None

    # pyimgui attribute aliases
    _pyimgui_aliases = {
        'COLOR_WINDOW_BACKGROUND': 'WINDOW_BG',
        'STYLE_ITEM_SPACING': 'ITEM_SPACING',
    }
    for standard, pyimgui_name in _pyimgui_aliases.items():
        if not hasattr(imgui, standard) and hasattr(imgui, pyimgui_name):
            setattr(imgui, standard, getattr(imgui, pyimgui_name))

else:
    # ── Stub module — allows import but no rendering ──
    imgui = types.ModuleType("imgui_stub")
    imgui.__doc__ = "Stub: no ImGui backend available"
    GlfwRenderer = None

    _CONSTS = {
        'COLOR_TEXT': 0, 'COLOR_TEXT_DISABLED': 1,
        'COLOR_WINDOW_BACKGROUND': 2, 'COLOR_CHILD_BACKGROUND': 3,
        'COLOR_POPUP_BACKGROUND': 4, 'COLOR_BORDER': 5,
        'COLOR_BORDER_SHADOW': 6, 'COLOR_FRAME_BACKGROUND': 7,
        'COLOR_FRAME_BACKGROUND_HOVERED': 8, 'COLOR_FRAME_BACKGROUND_ACTIVE': 9,
        'COLOR_TITLE_BACKGROUND': 10, 'COLOR_TITLE_BACKGROUND_ACTIVE': 11,
        'COLOR_TITLE_BACKGROUND_COLLAPSED': 12, 'COLOR_MENUBAR_BACKGROUND': 13,
        'COLOR_SCROLLBAR_BACKGROUND': 14, 'COLOR_SCROLLBAR_GRAB': 15,
        'COLOR_SCROLLBAR_GRAB_HOVERED': 16, 'COLOR_SCROLLBAR_GRAB_ACTIVE': 17,
        'COLOR_CHECK_MARK': 18, 'COLOR_SLIDER_GRAB': 19,
        'COLOR_SLIDER_GRAB_ACTIVE': 20, 'COLOR_BUTTON': 21,
        'COLOR_BUTTON_HOVERED': 22, 'COLOR_BUTTON_ACTIVE': 23,
        'COLOR_HEADER': 24, 'COLOR_HEADER_HOVERED': 25,
        'COLOR_HEADER_ACTIVE': 26, 'COLOR_SEPARATOR': 27,
        'COLOR_SEPARATOR_HOVERED': 28, 'COLOR_SEPARATOR_ACTIVE': 29,
        'COLOR_RESIZE_GRIP': 30, 'COLOR_RESIZE_GRIP_HOVERED': 31,
        'COLOR_RESIZE_GRIP_ACTIVE': 32,
        'COLOR_TAB': 33, 'COLOR_TAB_HOVERED': 34, 'COLOR_TAB_ACTIVE': 35,
        'COLOR_TAB_UNFOCUSED': 36, 'COLOR_TAB_UNFOCUSED_ACTIVE': 37,
        'COLOR_NAV_HIGHLIGHT': 42,
        'STYLE_WINDOW_ROUNDING': 3, 'STYLE_FRAME_ROUNDING': 12,
        'STYLE_FRAME_PADDING': 11, 'STYLE_ITEM_SPACING': 14,
        'STYLE_POPUP_ROUNDING': 9, 'STYLE_WINDOW_PADDING': 2,
        'STYLE_CHILD_ROUNDING': 7, 'STYLE_SCROLLBAR_SIZE': 18,
        'WINDOW_NO_TITLE_BAR': 1, 'WINDOW_NO_RESIZE': 2,
        'WINDOW_NO_MOVE': 4, 'WINDOW_NO_SCROLLBAR': 8,
        'WINDOW_NO_COLLAPSE': 32, 'WINDOW_NO_SAVED_SETTINGS': 256,
        'WINDOW_NO_FOCUS_ON_APPEARING': 4096,
    }

    for name, val in _CONSTS.items():
        setattr(imgui, name, val)

    def _noop(*a, **kw):
        pass

    def _stub_io():
        io = types.SimpleNamespace()
        io.delta_time = 0.016
        io.display_size = types.SimpleNamespace(x=800, y=600)
        return io

    def _stub_style():
        return types.SimpleNamespace(
            window_padding=(0, 0), frame_padding=(0, 0),
            item_spacing=(0, 0), window_rounding=0, frame_rounding=0,
            popup_rounding=0, scrollbar_size=0,
            window_border_size=0, child_border_size=0, popup_border_size=0,
            colors=[(0, 0, 0, 1)] * 55,
        )

    imgui.get_io = _stub_io
    imgui.get_style = _stub_style

    _STUBS = [
        'create_context', 'new_frame', 'render', 'end_frame',
        'begin', 'end', 'begin_child', 'end_child',
        'text', 'text_colored', 'button', 'checkbox',
        'slider_float', 'slider_int', 'combo', 'input_text',
        'same_line', 'separator', 'spacing', 'dummy',
        'push_style_color', 'pop_style_color',
        'push_style_var', 'pop_style_var',
        'push_item_width', 'pop_item_width',
        'set_cursor_pos', 'get_cursor_pos',
        'get_content_region_available_width',
        'get_window_draw_list', 'is_item_hovered',
        'set_next_window_position', 'set_next_window_size',
        'begin_tooltip', 'end_tooltip',
        'push_text_wrap_pos', 'pop_text_wrap_pos',
        'color_edit3', 'color_edit4',
        'begin_group', 'end_group',
        'push_font', 'pop_font',
        'get_draw_data',
    ]
    for fn in _STUBS:
        if not hasattr(imgui, fn):
            setattr(imgui, fn, _noop)
