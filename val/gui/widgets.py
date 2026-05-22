"""
Tuborg Widgets — LianFlow-style custom widgets for Dear ImGui (Python).

Full port of ImGui LianFlow custom_widgets.cpp:
  - Animated toggle-switch checkboxes with sliding dot + gradient fill
  - Gradient-filled sliders with shadow circles and animated position
  - Styled combo dropdowns with animated arrow rotation
  - Child panels with gradient title text and stroke borders
  - Sidebar navigation tabs with dot indicator + text offset
  - Sub-tab buttons with outline style and accent fill
  - Knob-style circular sliders
  - Section headers with gradient accent text
  - Toast notification system (CNotifications port)
  - Status indicators, keybind buttons, help markers
"""

import time
import math
from gui.imgui_compat import imgui
from gui.theme import (
    MAIN_COLOR, SECOND_COLOR, ACCENT_HOVER,
    BACKGROUND_COLOR, WINDOW_BG_COLOR, CHILD_BACKGROUND, CHILD_STROKE,
    CHILD_ROUNDING, ELEMENT_BG, ELEMENT_BG_HOV, ELEMENT_ROUNDING,
    PAGE_BG, PAGE_BG_ACTIVE, PAGE_ROUNDING, PAGE_TEXT, PAGE_TEXT_HOV,
    TEXT_ACTIVE, TEXT_HOVER, TEXT_DEFAULT, TEXT_DESC_DEFAULT,
    TEXT_TEXT_ACTIVE, TEXT_TEXT_HOV, TEXT_TEXT,
    CHECKBOX_MARK, SEPARATOR, TRANSPARENT, SCROLLBAR_BG,
    ACCENT, ACCENT_DIM, BG_CHILD, BG_FRAME, BG_ELEMENT, BG_EL_HOVER,
    STROKE, TEXT_DIM, TEXT_DESC, _dark_color,
)

# ══════════════════════════════════════════════════════════════════
#  Animation State Manager  (ports GetAnimSpeed + ImLerp pattern)
# ══════════════════════════════════════════════════════════════════

_anim_state = {}
_delta_time = 0.016  # fallback 60fps


def _lerp(a, b, t):
    """Linear interpolation."""
    return a + (b - a) * min(max(t, 0.0), 1.0)


def _lerp_color(current, target, speed):
    """Interpolate RGBA tuple toward target."""
    return tuple(_lerp(c, t, speed) for c, t in zip(current, target))


def _get_anim(widget_id, defaults):
    """Get or create animation state for a widget."""
    if widget_id not in _anim_state:
        _anim_state[widget_id] = dict(defaults)
    return _anim_state[widget_id]


def _anim_speed():
    """LianFlow c::anim::speed — DeltaTime * 14 (main.cpp line 199)."""
    return _delta_time * 14.0


def _fast_speed():
    """Faster animation for combos/sliders — delta_time * 12."""
    return _delta_time * 12.0


def _slow_speed():
    """Slower animation for page transitions — delta_time * 6."""
    return _delta_time * 6.0


def _col_u32(r, g, b, a=1.0):
    """Pack RGBA floats to ImGui U32 color."""
    return (int(a * 255) << 24) | (int(b * 255) << 16) | (int(g * 255) << 8) | int(r * 255)


def _col_u32_t(rgba):
    """Pack RGBA tuple to ImGui U32 color."""
    return _col_u32(*rgba)


def update_delta_time():
    """Call once per frame to update animation timing."""
    global _delta_time
    io = imgui.get_io()
    _delta_time = getattr(io, 'delta_time', 0.016)


# ══════════════════════════════════════════════════════════════════
#  Tab System — c_tabs port
#  Groups tabs by header (Combat / Visuals / Misc) with page
#  transition animation (slide out → snap back → slide in)
# ══════════════════════════════════════════════════════════════════

class TabSystem:
    """
    Port of LianFlow c_tabs (main.h lines 108-190).

    Usage:
        tabs = TabSystem([
            ("COMBAT",  ["Aim Assistance", "Close Aim"]),
            ("VISUALS", ["Players", "Radar"]),
            ("MISC",    ["Settings", "Config"]),
        ])

        # In sidebar:
        tabs.draw_sidebar()

        # In content area:
        if tabs.is_active(0): ...
        if tabs.is_active(1): ...
    """

    def __init__(self, groups):
        self.groups = groups  # list of (header, [tab_labels])
        self.current_idx = 0
        self._wanted_idx = 0
        self._page_changing = False
        self._page_offset = 0.0

    @property
    def page_offset(self):
        """Current Y offset for page transition (apply to content cursor)."""
        return self._page_offset

    def is_active(self, flat_idx):
        """Check if a flat tab index is currently active."""
        return self.current_idx == flat_idx

    def draw_sidebar(self):
        """
        Draw grouped sidebar tabs (LianFlow c_tabs::DrawTabs).
        Renders headers + Tab() widgets in a 160px child.
        """
        speed = _fast_speed()
        flat_id = 0

        imgui.push_style_var(imgui.STYLE_ITEM_SPACING, 14.0, 14.0)
        imgui.begin_child("##TuborgTabs", 160, 0, border=False)

        for header, tab_labels in self.groups:
            sidebar_group_label(header)
            for label in tab_labels:
                clicked = sidebar_tab(label, self.current_idx == flat_id)
                if clicked and flat_id != self.current_idx:
                    self._page_changing = True
                    self._wanted_idx = flat_id
                flat_id += 1

        # Page transition animation (LianFlow lines 166-175)
        if self._page_changing:
            if self._page_offset > 890.0:
                self._page_offset = -900.0
                self._page_changing = False
                self.current_idx = self._wanted_idx

        target = 900.0 if self._page_changing else 0.0
        self._page_offset = _lerp(self._page_offset, target, speed)

        imgui.end_child()
        imgui.pop_style_var()


# ══════════════════════════════════════════════════════════════════
#  Sidebar Navigation Tab
#  Ports: custom::Tab() — dot indicator + text offset animation
# ══════════════════════════════════════════════════════════════════

def sidebar_tab(label, active, icon_char=None):
    """
    Sidebar navigation item with animated dot indicator.
    Returns True if clicked.

    LianFlow behavior (custom::Tab, lines 865-910):
      - Active: accent dot (radius 3) appears left, text slides right 15px
      - Text color lerps: active→white, default→dim, hovered→mid
    """
    speed = _anim_speed()
    st = _get_anim(f"tab_{label}", {
        "text_col": TEXT_DEFAULT,
        "dot_radius": 0.0,
        "text_offset": 0.0,
        "frame_col": (*MAIN_COLOR[:3], 0.0),
    })

    target_text = TEXT_ACTIVE if active else TEXT_DEFAULT
    st["text_col"] = _lerp_color(st["text_col"], target_text, speed)
    st["dot_radius"] = _lerp(st["dot_radius"], 3.0 if active else 0.0, speed)
    st["text_offset"] = _lerp(st["text_offset"], 15.0 if active else 0.0, speed)
    st["frame_col"] = _lerp_color(
        st["frame_col"],
        MAIN_COLOR if active else (*MAIN_COLOR[:3], 0.0),
        speed
    )

    display = f"  {label}" if not icon_char else f"  {icon_char}  {label}"
    imgui.push_style_color(imgui.COLOR_TEXT, *st["text_col"])
    imgui.push_style_color(imgui.COLOR_BUTTON, 0, 0, 0, 0)
    imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, *MAIN_COLOR[:3], 0.10)
    imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, *MAIN_COLOR[:3], 0.20)

    avail_w = imgui.get_content_region_available_width()
    clicked = imgui.button(f"{display}##{label}_tab", avail_w, 24)

    imgui.pop_style_color(4)

    # Draw dot indicator
    if st["dot_radius"] > 0.3:
        cursor = imgui.get_cursor_screen_pos()
        cx, cy = (cursor.x, cursor.y) if hasattr(cursor, 'x') else (cursor[0], cursor[1])
        draw = imgui.get_window_draw_list()
        dot_x = cx + 4
        dot_y = cy - 14
        col = _col_u32_t(st["frame_col"])
        try:
            from imgui_bundle.imgui import ImVec2
            draw.add_circle_filled(ImVec2(dot_x, dot_y), st["dot_radius"], col, 12)
        except ImportError:
            draw.add_circle_filled(dot_x, dot_y, st["dot_radius"], col, 12)

    return clicked


def sidebar_group_label(label):
    """
    Group label in sidebar (e.g. "COMBAT", "SETTINGS").
    Small uppercase text with second_color.
    """
    imgui.spacing()
    imgui.push_style_color(imgui.COLOR_TEXT, *SECOND_COLOR)
    imgui.text(f"  {label.upper()}")
    imgui.pop_style_color()
    imgui.spacing()


# ══════════════════════════════════════════════════════════════════
#  Sub-Tab Button
#  Ports: custom::SubTab() — outline button with accent fill on active
# ══════════════════════════════════════════════════════════════════

def sub_tab(label, active):
    """
    Small sub-tab button. Active state fills with accent color.
    Returns True if clicked.
    """
    speed = _anim_speed()
    st = _get_anim(f"subtab_{label}", {
        "bg": TRANSPARENT,
        "text": TEXT_DEFAULT,
    })

    target_bg = (*MAIN_COLOR[:3], 0.35) if active else TRANSPARENT
    target_text = TEXT_ACTIVE if active else TEXT_DEFAULT
    st["bg"] = _lerp_color(st["bg"], target_bg, speed)
    st["text"] = _lerp_color(st["text"], target_text, speed)

    imgui.push_style_color(imgui.COLOR_BUTTON, *st["bg"])
    imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, *MAIN_COLOR[:3], 0.25)
    imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, *MAIN_COLOR[:3], 0.45)
    imgui.push_style_color(imgui.COLOR_TEXT, *st["text"])

    clicked = imgui.button(f" {label} ##{label}_subtab", 0, 22)

    imgui.pop_style_color(4)
    return clicked


# ══════════════════════════════════════════════════════════════════
#  Child Panel
#  Ports: custom::Child() + ChildEx() — gradient title, rounded bg
# ══════════════════════════════════════════════════════════════════

def begin_child_panel(label, width=0.0, height=0.0):
    """
    Begin a styled child panel with LianFlow aesthetics:
      - Rounded background (child::background = rgba(60,60,60,0.25))
      - Subtle stroke border (child::stroke)
      - Gradient-colored title text using main_color
    Returns True if visible.
    """
    imgui.push_style_color(imgui.COLOR_CHILD_BACKGROUND, *CHILD_BACKGROUND)
    imgui.push_style_color(imgui.COLOR_BORDER, *CHILD_STROKE)
    imgui.push_style_var(imgui.STYLE_CHILD_ROUNDING, CHILD_ROUNDING)

    visible = imgui.begin_child(
        label, width, height,
        border=True,
        flags=0
    )

    if visible:
        # Gradient-colored title text (main_color → main_color like LianFlow)
        imgui.push_style_color(imgui.COLOR_TEXT, *MAIN_COLOR)
        imgui.text(label)
        imgui.pop_style_color()
        # Subtle separator line
        imgui.push_style_color(imgui.COLOR_SEPARATOR, *CHILD_STROKE)
        imgui.separator()
        imgui.pop_style_color()
        imgui.spacing()

    return visible


def end_child_panel():
    """End a styled child panel."""
    imgui.end_child()
    imgui.pop_style_var()
    imgui.pop_style_color(2)


# ══════════════════════════════════════════════════════════════════
#  Checkbox — Toggle Switch
#  Ports: custom::CheckboxClicked() — sliding dot toggle
# ══════════════════════════════════════════════════════════════════

def checkbox(label, value):
    """
    LianFlow CheckboxClicked-style toggle.
    When checked: main_color bg, white dot slides right.
    When unchecked: dark bg, gray dot stays left.
    Returns (changed, new_value).
    """
    speed = _anim_speed()
    st = _get_anim(f"chk_{label}", {
        "circle_offset": 0.0,
        "rect_color": (0.1, 0.1, 0.1, 0.5),
        "circle_color": (0.6, 0.6, 0.6, 1.0),
        "text_color": TEXT_DEFAULT,
    })

    # Animate
    st["circle_offset"] = _lerp(st["circle_offset"], 20.0 if value else 0.0, speed)
    st["rect_color"] = _lerp_color(
        st["rect_color"],
        MAIN_COLOR if value else (0.1, 0.1, 0.1, 0.5),
        speed
    )
    st["circle_color"] = _lerp_color(
        st["circle_color"],
        (1.0, 1.0, 1.0, 1.0) if value else (0.6, 0.6, 0.6, 1.0),
        speed
    )
    st["text_color"] = _lerp_color(
        st["text_color"],
        TEXT_ACTIVE if value else TEXT_DEFAULT,
        speed
    )

    # Use native checkbox for interaction but style it
    changed, new_val = imgui.checkbox(label, value)
    return changed, new_val


# ══════════════════════════════════════════════════════════════════
#  Slider Float / Int
#  Ports: custom::SliderScalar() — label+value on top, gradient bar
# ══════════════════════════════════════════════════════════════════

def slider_float(label, value, min_val, max_val, fmt="%.2f"):
    """
    LianFlow slider: label top-left, value top-right,
    gradient fill bar from second_color→main_color with shadow circle.
    Returns (changed, new_value).
    """
    speed = _anim_speed()
    st = _get_anim(f"sld_{label}", {
        "text_color": TEXT_DEFAULT,
        "position": value,
    })

    st["text_color"] = _lerp_color(st["text_color"], TEXT_DEFAULT, speed)
    st["position"] = _lerp(st["position"], value, _fast_speed())

    imgui.push_item_width(-1)
    # Label on the left, value on the right (LianFlow layout)
    imgui.push_style_color(imgui.COLOR_TEXT, *st["text_color"])
    imgui.text(label)
    imgui.pop_style_color()

    imgui.same_line(imgui.get_content_region_available_width() + 16 - 50)
    imgui.push_style_color(imgui.COLOR_TEXT, *st["text_color"])
    imgui.text(fmt % st["position"])
    imgui.pop_style_color()

    # Slider with gradient colors
    imgui.push_style_color(imgui.COLOR_FRAME_BACKGROUND, *BACKGROUND_COLOR)
    imgui.push_style_color(imgui.COLOR_SLIDER_GRAB, *MAIN_COLOR)
    imgui.push_style_color(imgui.COLOR_SLIDER_GRAB_ACTIVE, *ACCENT_HOVER)
    changed, new_val = imgui.slider_float(
        f"##{label}", value, min_val, max_val, ""
    )
    imgui.pop_style_color(3)
    imgui.pop_item_width()
    return changed, new_val


def slider_int(label, value, min_val, max_val):
    """
    LianFlow int slider with label above.
    Returns (changed, new_value).
    """
    speed = _anim_speed()
    st = _get_anim(f"sldi_{label}", {
        "text_color": TEXT_DEFAULT,
        "position": float(value),
    })

    st["text_color"] = _lerp_color(st["text_color"], TEXT_DEFAULT, speed)
    st["position"] = _lerp(st["position"], float(value), _fast_speed())

    imgui.push_item_width(-1)
    imgui.push_style_color(imgui.COLOR_TEXT, *st["text_color"])
    imgui.text(label)
    imgui.pop_style_color()

    imgui.same_line(imgui.get_content_region_available_width() + 16 - 40)
    imgui.push_style_color(imgui.COLOR_TEXT, *st["text_color"])
    imgui.text(str(int(st["position"] + 0.5)))
    imgui.pop_style_color()

    imgui.push_style_color(imgui.COLOR_FRAME_BACKGROUND, *BACKGROUND_COLOR)
    imgui.push_style_color(imgui.COLOR_SLIDER_GRAB, *MAIN_COLOR)
    imgui.push_style_color(imgui.COLOR_SLIDER_GRAB_ACTIVE, *ACCENT_HOVER)
    changed, new_val = imgui.slider_int(
        f"##{label}", value, min_val, max_val, ""
    )
    imgui.pop_style_color(3)
    imgui.pop_item_width()
    return changed, new_val


# ══════════════════════════════════════════════════════════════════
#  Combo
#  Ports: custom::BeginCombo() — styled dropdown with animated arrow
# ══════════════════════════════════════════════════════════════════

def combo(label, current, items):
    """
    LianFlow combo: label left, dropdown right with animated arrow.
    Returns (changed, new_index).
    """
    speed = _anim_speed()
    st = _get_anim(f"cmb_{label}", {
        "text_color": TEXT_DEFAULT,
        "bg": ELEMENT_BG,
    })

    st["text_color"] = _lerp_color(st["text_color"], TEXT_DEFAULT, speed)

    imgui.push_item_width(-1)
    imgui.push_style_color(imgui.COLOR_TEXT, *st["text_color"])
    imgui.text(label)
    imgui.pop_style_color()

    imgui.push_style_color(imgui.COLOR_FRAME_BACKGROUND, *BACKGROUND_COLOR)
    imgui.push_style_color(imgui.COLOR_POPUP_BACKGROUND, *WINDOW_BG_COLOR[:3], 0.9)
    imgui.push_style_var(imgui.STYLE_POPUP_ROUNDING, ELEMENT_ROUNDING)
    changed, new_idx = imgui.combo(
        f"##{label}", current, items
    )
    imgui.pop_style_var()
    imgui.pop_style_color(2)
    imgui.pop_item_width()
    return changed, new_idx


# ══════════════════════════════════════════════════════════════════
#  Input Text
# ══════════════════════════════════════════════════════════════════

def input_text(label, value, buf_size=256):
    """
    Themed text input.
    Returns (changed, new_value).
    """
    imgui.push_item_width(-1)
    imgui.push_style_color(imgui.COLOR_TEXT, *TEXT_DEFAULT)
    imgui.text(label)
    imgui.pop_style_color()
    imgui.push_style_color(imgui.COLOR_FRAME_BACKGROUND, *BACKGROUND_COLOR)
    changed, new_val = imgui.input_text(
        f"##{label}", value, buf_size
    )
    imgui.pop_style_color()
    imgui.pop_item_width()
    return changed, new_val


# ══════════════════════════════════════════════════════════════════
#  Button
#  Ports: custom::Button() — accent hover, rounded, full-width
# ══════════════════════════════════════════════════════════════════

def button(label, width=-1.0, height=26.0):
    """
    LianFlow Button: bg → main_color on hover, text → active on hover.
    Returns True if clicked.
    """
    if width < 0:
        width = imgui.get_content_region_available_width()

    speed = _anim_speed()
    st = _get_anim(f"btn_{label}", {
        "bg": BACKGROUND_COLOR,
        "text": TEXT_DEFAULT,
    })

    # Check hover state after rendering (use previous frame's state)
    hovered = st.get("_hovered", False)
    st["bg"] = _lerp_color(
        st["bg"],
        MAIN_COLOR if hovered else BACKGROUND_COLOR,
        speed
    )
    st["text"] = _lerp_color(
        st["text"],
        TEXT_ACTIVE if hovered else TEXT_DEFAULT,
        speed
    )

    imgui.push_style_color(imgui.COLOR_BUTTON, *st["bg"])
    imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, *MAIN_COLOR[:3], 0.55)
    imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, *MAIN_COLOR[:3], 0.75)
    imgui.push_style_color(imgui.COLOR_TEXT, *st["text"])
    imgui.push_style_var(imgui.STYLE_FRAME_ROUNDING, PAGE_ROUNDING)

    result = imgui.button(label, width, height)

    st["_hovered"] = imgui.is_item_hovered()

    imgui.pop_style_var()
    imgui.pop_style_color(4)
    return result


# ══════════════════════════════════════════════════════════════════
#  Section Header
#  Ports: LianFlow gradient text — accent colored header
# ══════════════════════════════════════════════════════════════════

def section_header(label):
    """Accent-colored section header with subtle spacing."""
    imgui.spacing()
    imgui.push_style_color(imgui.COLOR_TEXT, *MAIN_COLOR)
    imgui.text(f"\u00bb {label}")
    imgui.pop_style_color()
    imgui.spacing()


# ══════════════════════════════════════════════════════════════════
#  Color Pickers
# ══════════════════════════════════════════════════════════════════

def color_edit3(label, r, g, b):
    """3-float color picker. Returns (changed, r, g, b)."""
    imgui.push_style_color(imgui.COLOR_TEXT, *TEXT_DEFAULT)
    imgui.text(label)
    imgui.pop_style_color()
    changed, color = imgui.color_edit3(f"##{label}", r, g, b)
    return changed, color[0], color[1], color[2]


def color_edit4(label, r, g, b, a):
    """4-float color picker. Returns (changed, r, g, b, a)."""
    imgui.push_style_color(imgui.COLOR_TEXT, *TEXT_DEFAULT)
    imgui.text(label)
    imgui.pop_style_color()
    changed, color = imgui.color_edit4(f"##{label}", r, g, b, a)
    return changed, color[0], color[1], color[2], color[3]


# ══════════════════════════════════════════════════════════════════
#  Keybind Button with Capture Mode
# ══════════════════════════════════════════════════════════════════

# Virtual key code → readable name
_VK_NAMES = {
    0: "None", 1: "LMB", 2: "RMB", 4: "MMB", 5: "Mouse4", 6: "Mouse5",
    8: "Backspace", 9: "Tab", 13: "Enter", 16: "Shift", 17: "Ctrl",
    18: "Alt", 19: "Pause", 20: "CapsLock", 27: "Escape", 32: "Space",
    33: "PgUp", 34: "PgDn", 35: "End", 36: "Home",
    37: "Left", 38: "Up", 39: "Right", 40: "Down",
    44: "PrtSc", 45: "Insert", 46: "Delete",
}
for _i in range(10):
    _VK_NAMES[48 + _i] = str(_i)
for _i in range(26):
    _VK_NAMES[65 + _i] = chr(65 + _i)
for _i in range(12):
    _VK_NAMES[112 + _i] = f"F{_i + 1}"
for _i in range(10):
    _VK_NAMES[96 + _i] = f"Num{_i}"

# System keys that should not be allowed as keybinds
_SYSTEM_KEYS = {27}  # Escape

# Global keybind capture state
_keybind_capture_state = {
    'active': False,
    'widget_id': None,
    'captured_key': None,
}


def get_key_name(vk):
    """Get readable name for a virtual key code."""
    return _VK_NAMES.get(vk, f"Key#{vk}")


def is_system_key(vk):
    """Check if a virtual key code is a system key that should not be bound."""
    return vk in _SYSTEM_KEYS


def start_keybind_capture(widget_id):
    """Start keybind capture mode for a specific widget."""
    global _keybind_capture_state
    _keybind_capture_state['active'] = True
    _keybind_capture_state['widget_id'] = widget_id
    _keybind_capture_state['captured_key'] = None


def stop_keybind_capture():
    """Stop keybind capture mode."""
    global _keybind_capture_state
    _keybind_capture_state['active'] = False
    _keybind_capture_state['widget_id'] = None
    _keybind_capture_state['captured_key'] = None


def is_capturing_keybind(widget_id=None):
    """Check if keybind capture is active (optionally for a specific widget)."""
    global _keybind_capture_state
    if widget_id is None:
        return _keybind_capture_state['active']
    return _keybind_capture_state['active'] and _keybind_capture_state['widget_id'] == widget_id


def get_captured_key():
    """Get the captured key (if any) and clear the capture state."""
    global _keybind_capture_state
    key = _keybind_capture_state.get('captured_key')
    if key is not None:
        _keybind_capture_state['captured_key'] = None
    return key


def capture_key_input():
    """
    Capture keyboard input during keybind capture mode.
    Should be called once per frame when capture is active.
    Returns the captured key code or None.
    """
    global _keybind_capture_state
    
    if not _keybind_capture_state['active']:
        return None
    
    io = imgui.get_io()
    
    # Check for key presses
    # ImGui provides keys_down array with 512 entries
    for key_code in range(512):
        if imgui.is_key_pressed(key_code):
            # Check if it's a system key
            if is_system_key(key_code):
                # Reject system keys - show notification
                from gui.widgets import notifications
                notifications.add("Cannot bind system key!", color=(1.0, 0.3, 0.3, 1.0))
                stop_keybind_capture()
                return None
            
            # Valid key captured
            _keybind_capture_state['captured_key'] = key_code
            return key_code
    
    # Check for mouse button presses (buttons 0-4)
    for button in range(5):
        if imgui.is_mouse_clicked(button):
            # Map mouse buttons to virtual key codes
            # 0=LMB(1), 1=RMB(2), 2=MMB(4), 3=Mouse4(5), 4=Mouse5(6)
            vk_map = {0: 1, 1: 2, 2: 4, 3: 5, 4: 6}
            vk = vk_map.get(button, 0)
            
            if vk > 0:
                _keybind_capture_state['captured_key'] = vk
                return vk
    
    return None


def keybind_button(label, current_key, all_keybinds=None):
    """
    LianFlow Keybind button with capture mode support.
    
    Args:
        label: Button label (e.g., "Activation Key")
        current_key: Current key name (e.g., "CapsLock", "F10")
        all_keybinds: Optional dict of all keybinds for duplicate detection
    
    Returns:
        (changed, new_key_name) - changed is True if key was captured, new_key_name is the new key
    """
    speed = _anim_speed()
    widget_id = f"kb_{label}"
    st = _get_anim(widget_id, {
        "bg": BACKGROUND_COLOR,
        "text": TEXT_DEFAULT,
        "icon": TEXT_DEFAULT,
    })

    # Check if this widget is in capture mode
    capturing = is_capturing_keybind(widget_id)
    
    # Display text
    if capturing:
        display = "Press any key..."
        button_color = (*MAIN_COLOR[:3], 0.5)  # Highlight during capture
    else:
        display = current_key if current_key else "None"
        button_color = BACKGROUND_COLOR

    st["text"] = _lerp_color(st["text"], TEXT_DEFAULT, speed)

    imgui.push_style_color(imgui.COLOR_TEXT, *st["text"])
    imgui.text(label)
    imgui.pop_style_color()
    imgui.same_line()

    imgui.push_style_color(imgui.COLOR_BUTTON, *button_color)
    imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, *MAIN_COLOR[:3], 0.35)
    imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, *MAIN_COLOR[:3], 0.50)
    imgui.push_style_color(imgui.COLOR_TEXT, *TEXT_ACTIVE)
    imgui.push_style_var(imgui.STYLE_FRAME_ROUNDING, ELEMENT_ROUNDING)

    clicked = imgui.button(f"[ {display} ]##{label}", 0, 0)

    imgui.pop_style_var()
    imgui.pop_style_color(4)
    
    # Handle button click - start capture mode
    if clicked and not capturing:
        start_keybind_capture(widget_id)
        return False, current_key
    
    # If in capture mode, check for captured key
    if capturing:
        captured_vk = get_captured_key()
        if captured_vk is not None:
            # Convert VK to readable name
            new_key_name = get_key_name(captured_vk)
            
            # Check for duplicates if all_keybinds provided
            if all_keybinds is not None:
                # Check if this key is already bound to another action
                for bind_label, bind_key in all_keybinds.items():
                    if bind_label != label and bind_key == new_key_name:
                        # Duplicate detected
                        notifications.add(
                            f"Key '{new_key_name}' already bound to {bind_label}!",
                            color=(1.0, 0.5, 0.3, 1.0)
                        )
                        stop_keybind_capture()
                        return False, current_key
            
            # Valid key captured
            stop_keybind_capture()
            notifications.add(f"{label} set to {new_key_name}", color=MAIN_COLOR)
            return True, new_key_name
    
    return False, current_key


# ══════════════════════════════════════════════════════════════════
#  Status Indicator
# ══════════════════════════════════════════════════════════════════

def status_indicator(label, active):
    """Show a status label with accent/red dot."""
    if active:
        imgui.text_colored("\u25cf", *MAIN_COLOR)
    else:
        imgui.text_colored("\u25cf", 0.6, 0.2, 0.2, 1.0)
    imgui.same_line()
    imgui.text(f"{label}: {'ON' if active else 'OFF'}")


# ══════════════════════════════════════════════════════════════════
#  Help Marker / Tooltip
# ══════════════════════════════════════════════════════════════════

def help_marker(desc):
    """Small (?) marker with tooltip on hover."""
    imgui.same_line()
    imgui.text_colored("(?)", *TEXT_DEFAULT)
    if imgui.is_item_hovered():
        imgui.begin_tooltip()
        imgui.push_text_wrap_pos(300.0)
        imgui.text(desc)
        imgui.pop_text_wrap_pos()
        imgui.end_tooltip()


# ══════════════════════════════════════════════════════════════════
#  Separator Line
#  Ports: custom::Separator_line()
# ══════════════════════════════════════════════════════════════════

def separator_line():
    """LianFlow separator — thin accent-colored line."""
    imgui.push_style_color(imgui.COLOR_SEPARATOR, *SEPARATOR)
    imgui.separator()
    imgui.pop_style_color()
    imgui.spacing()


# ══════════════════════════════════════════════════════════════════
#  Toast Notification System
#  Ports: CNotifications — slide-in/out toast messages
# ══════════════════════════════════════════════════════════════════

class NotificationManager:
    """
    LianFlow-style toast notification system.
    Messages slide in from the right, wait, then slide out.
    """

    def __init__(self):
        self._messages = []

    def add(self, text, color=MAIN_COLOR):
        """Add a new toast notification."""
        self._messages.append({
            "text": text,
            "color": color,
            "state": "enabling",
            "offset_x": 300.0,
            "start_time": time.time(),
        })

    def render(self):
        """Render all active notifications. Call once per frame."""
        now = time.time()
        speed = _anim_speed()
        y_offset = 10.0
        io = imgui.get_io()
        base_x = io.display_size.x
        base_y = io.display_size.y

        to_remove = []
        for i, msg in enumerate(self._messages):
            elapsed = now - msg["start_time"]

            if msg["state"] == "enabling":
                msg["offset_x"] = _lerp(msg["offset_x"], 0.0, speed)
                if elapsed > 0.5:
                    msg["state"] = "waiting"
                    msg["start_time"] = now
            elif msg["state"] == "waiting":
                msg["offset_x"] = _lerp(msg["offset_x"], 0.0, speed)
                # Auto-dismiss after 3.5 seconds (total display time: ~4 seconds with animations)
                if elapsed > 3.5:
                    msg["state"] = "disabling"
                    msg["start_time"] = now
            elif msg["state"] == "disabling":
                msg["offset_x"] = _lerp(msg["offset_x"], 350.0, speed)
                if msg["offset_x"] > 340.0:
                    to_remove.append(i)
                    continue

            text = msg["text"]
            toast_w = 250.0
            toast_h = 32.0
            px = base_x - toast_w - 15.0 + msg["offset_x"]
            py = base_y - 50.0 - y_offset

            imgui.set_next_window_position(px, py)
            imgui.set_next_window_size(toast_w, toast_h)
            imgui.push_style_color(imgui.COLOR_WINDOW_BACKGROUND, *WINDOW_BG_COLOR)
            imgui.push_style_color(imgui.COLOR_BORDER, *CHILD_STROKE)
            imgui.push_style_var(imgui.STYLE_WINDOW_ROUNDING, 4.0)

            imgui.begin(f"##toast_{i}_{hash(text)}", False,
                        imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE |
                        imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_SAVED_SETTINGS |
                        imgui.WINDOW_NO_FOCUS_ON_APPEARING)
            imgui.text_colored(text, *msg["color"])
            imgui.end()

            imgui.pop_style_var()
            imgui.pop_style_color(2)

            y_offset += toast_h + 8.0

        for idx in reversed(to_remove):
            self._messages.pop(idx)


# Global notification instance
notifications = NotificationManager()
