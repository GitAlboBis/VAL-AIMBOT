"""
Tuborg Theme — 1:1 LianFlow imgui_settings.h color palette.

All colors are exact values from the LianFlow C++ preset (namespace c::).
This file is the SINGLE SOURCE OF TRUTH for all Tuborg GUI colors.

main_color:        rgba(173, 143, 233, 1.0)   — purple accent
second_color:      rgba(100,  92, 122, 1.0)   — muted lavender
background_color:  rgba( 20,  20,  20, 0.50)  — semi-transparent dark
window_bg_color:   rgba( 22,  22,  22, 0.71)  — frosted window
stroke_color:      rgba(255, 255, 255, 0.00)  — invisible by default
separator:         ImColor(22, 23, 26)
"""

from gui.imgui_compat import imgui

# ═══════════════════════════════════════════════════════════════════
#  PRIMARY PALETTE  (namespace c::)
# ═══════════════════════════════════════════════════════════════════

MAIN_COLOR       = (0.678, 0.561, 0.914, 1.0)      # rgba(173,143,233,1)
SECOND_COLOR     = (0.392, 0.361, 0.478, 1.0)      # rgba(100,92,122,1)
BACKGROUND_COLOR = (0.078, 0.078, 0.078, 0.50)     # rgba(20,20,20,0.5)
STROKE_COLOR     = (1.0,   1.0,   1.0,   0.0)      # rgba(255,255,255,0) — invisible
WINDOW_BG_COLOR  = (0.086, 0.086, 0.086, 0.71)     # rgba(22,22,22,0.71)
SEPARATOR        = (0.086, 0.090, 0.102, 1.0)      # ImColor(22,23,26)

# ═══════════════════════════════════════════════════════════════════
#  ANIMATION COLORS  (namespace c::anim::)
# ═══════════════════════════════════════════════════════════════════

ANIM_ACTIVE      = (0.447, 0.584, 1.0,   1.0)      # ImColor(114,149,255,255)
ANIM_DEFAULT     = (0.086, 0.090, 0.102, 1.0)      # ImColor(22,23,26,255)

# ═══════════════════════════════════════════════════════════════════
#  BACKGROUND PANEL  (namespace c::bg::)
# ═══════════════════════════════════════════════════════════════════

BG_BACKGROUND    = (0.086, 0.086, 0.086, 0.71)     # rgba(22,22,22,0.71)
BG_SIZE          = (850.0, 596.0)
BG_ROUNDING      = 15.0

# ═══════════════════════════════════════════════════════════════════
#  CHILD PANEL  (namespace c::child::)
# ═══════════════════════════════════════════════════════════════════

CHILD_BACKGROUND = (0.235, 0.235, 0.235, 0.25)     # rgba(60,60,60,0.25)
CHILD_STROKE     = (0.071, 0.071, 0.094, 0.0)      # ImColor(18,18,24,0)
CHILD_ROUNDING   = 8.0

# ═══════════════════════════════════════════════════════════════════
#  PAGE / TAB  (namespace c::page::)
# ═══════════════════════════════════════════════════════════════════

PAGE_BG_ACTIVE   = (0.082, 0.086, 0.098, 1.0)      # ImColor(21,22,25)
PAGE_BG          = (0.063, 0.067, 0.071, 1.0)      # ImColor(16,17,18)
PAGE_TEXT_HOV    = (0.588, 0.635, 0.804, 1.0)      # ImColor(150,162,205)
PAGE_TEXT        = (0.588, 0.635, 0.804, 1.0)      # ImColor(150,162,205)
PAGE_ROUNDING    = 4.0

# ═══════════════════════════════════════════════════════════════════
#  ELEMENTS  (namespace c::elements::)
# ═══════════════════════════════════════════════════════════════════

ELEMENT_BG_HOV   = (0.082, 0.086, 0.098, 1.0)      # ImColor(21,22,25)
ELEMENT_BG       = (0.063, 0.067, 0.071, 1.0)      # ImColor(16,17,18)
ELEMENT_ROUNDING = 2.5

# ═══════════════════════════════════════════════════════════════════
#  TEXT  (namespace c::text::)
# ═══════════════════════════════════════════════════════════════════

TEXT_ACTIVE       = (1.0,   1.0,   1.0,   1.0)     # ImColor(255,255,255,255)
TEXT_HOVER        = (0.804, 0.804, 0.804, 1.0)     # ImColor(205,205,205,255)
TEXT_DEFAULT      = (0.588, 0.588, 0.588, 0.863)   # ImColor(150,150,150,220)

TEXT_DESC_ACTIVE  = (0.784, 0.784, 0.784, 0.400)   # ImColor(200,200,200,102)
TEXT_DESC_HOVER   = (0.784, 0.784, 0.784, 0.247)   # ImColor(200,200,200,63)
TEXT_DESC_DEFAULT = (0.784, 0.784, 0.784, 0.157)   # ImColor(200,200,200,40)

TEXT_TEXT_ACTIVE  = (1.0,   1.0,   1.0,   1.0)     # ImColor(255,255,255)
TEXT_TEXT_HOV     = (0.588, 0.635, 0.804, 1.0)     # ImColor(150,162,205)
TEXT_TEXT         = (0.588, 0.635, 0.804, 1.0)     # ImColor(150,162,205)

CHECKBOX_MARK    = (1.0,   1.0,   1.0,   1.0)     # ImColor(255,255,255,255)

# ═══════════════════════════════════════════════════════════════════
#  UTILITY
# ═══════════════════════════════════════════════════════════════════

TRANSPARENT      = (0.0, 0.0, 0.0, 0.0)
SCROLLBAR_BG     = (0.0, 0.0, 0.0, 0.08)

# ═══════════════════════════════════════════════════════════════════
#  LEGACY ALIASES — keep backward compat with any app.py references
# ═══════════════════════════════════════════════════════════════════

ACCENT       = MAIN_COLOR
ACCENT_DIM   = SECOND_COLOR
ACCENT_HOVER = (0.748, 0.631, 0.973, 1.0)          # lighter purple hover
ACCENT_DARK  = tuple(c * 0.4 for c in MAIN_COLOR[:3]) + (1.0,)
GOLD         = MAIN_COLOR
GOLD_DIM     = SECOND_COLOR
GOLD_HOVER   = ACCENT_HOVER

BG_WINDOW    = WINDOW_BG_COLOR
BG_CHILD     = CHILD_BACKGROUND
BG_POPUP     = (0.086, 0.086, 0.086, 0.95)
BG_PANEL     = PAGE_BG
BG_ELEMENT   = ELEMENT_BG
BG_EL_HOVER  = ELEMENT_BG_HOV
BG_FRAME     = BACKGROUND_COLOR
BG_SIDEBAR   = (0.055, 0.055, 0.067, 1.0)
BG_DARK_3    = BG_CHILD

STROKE       = CHILD_STROKE
BORDER       = (0.071, 0.075, 0.094, 1.0)
BORDER_NONE  = TRANSPARENT

TEXT_DIM      = TEXT_DEFAULT
TEXT_DESC     = TEXT_DESC_DEFAULT


def _dark_color(r, g, b, _a=1.0, pct=0.4):
    """LianFlow GetDarkColor — darken by percentage."""
    return (r * pct, g * pct, b * pct, 1.0)


def apply_theme():
    """Apply the Tuborg LianFlow dark+purple theme to the current ImGui context."""
    from gui.imgui_compat import IMGUI_BACKEND
    style = imgui.get_style()

    # ── Helper: set ImVec2 fields ──
    if IMGUI_BACKEND == "imgui_bundle":
        from imgui_bundle.imgui import ImVec2
        def _v2(x, y):
            return ImVec2(x, y)
    else:
        def _v2(x, y):
            return (x, y)

    # ── Sizing (exact main.cpp lines 136-149) ──
    style.window_padding = _v2(20.0, 20.0)      # s.WindowPadding = ImVec2(20, 20)
    style.frame_padding = _v2(18.0, 10.0)       # s.FramePadding = ImVec2(18, 10)
    style.item_spacing = _v2(4.0, 10.0)         # s.ItemSpacing = ImVec2(4, 10)
    style.item_inner_spacing = _v2(6.0, 4.0)
    style.indent_spacing = 20.0
    style.scrollbar_size = 1.0                   # s.ScrollbarSize = 1
    style.grab_min_size = 6.0

    # ── Rounding (exact main.cpp values) ──
    style.window_rounding = 20.0                 # s.WindowRounding = 20.f
    style.child_rounding = CHILD_ROUNDING        # child::rounding = 8
    style.frame_rounding = 2.0                   # s.FrameRounding = 2.f
    style.popup_rounding = 5.0                   # s.PopupRounding = 5.f
    style.scrollbar_rounding = 6.0
    style.grab_rounding = ELEMENT_ROUNDING       # elements::rounding = 2.5
    style.tab_rounding = 6.0

    # ── Borders (exact main.cpp) ──
    style.window_border_size = 0.0               # s.WindowBorderSize = 0.f
    style.child_border_size = 1.0                # s.ChildBorderSize = 1.f
    style.frame_border_size = 0.0
    style.popup_border_size = 0.0                # s.PopupBorderSize = 0.f
    style.tab_border_size = 0.0

    # ── Colors ──
    color_map = {
        # Backgrounds
        imgui.COLOR_WINDOW_BACKGROUND: BG_WINDOW,
        imgui.COLOR_POPUP_BACKGROUND: BG_POPUP,
        imgui.COLOR_CHILD_BACKGROUND: CHILD_BACKGROUND,
        imgui.COLOR_MENUBAR_BACKGROUND: BG_SIDEBAR,

        # Borders — main.cpp line 144: ImVec4(0,0,0,0)
        imgui.COLOR_BORDER: (0.0, 0.0, 0.0, 0.0),
        imgui.COLOR_BORDER_SHADOW: (0.0, 0.0, 0.0, 0.0),

        # Frame backgrounds
        imgui.COLOR_FRAME_BACKGROUND: BACKGROUND_COLOR,
        imgui.COLOR_FRAME_BACKGROUND_HOVERED: ELEMENT_BG_HOV,
        imgui.COLOR_FRAME_BACKGROUND_ACTIVE: (*MAIN_COLOR[:3], 0.25),

        # Title (minimal use with borderless window)
        imgui.COLOR_TITLE_BACKGROUND: BG_WINDOW,
        imgui.COLOR_TITLE_BACKGROUND_ACTIVE: BG_WINDOW,
        imgui.COLOR_TITLE_BACKGROUND_COLLAPSED: BG_WINDOW,

        # Tabs
        imgui.COLOR_TAB: PAGE_BG,
        imgui.COLOR_TAB_HOVERED: (*MAIN_COLOR[:3], 0.30),
        imgui.COLOR_TAB_ACTIVE: (*MAIN_COLOR[:3], 0.55),
        imgui.COLOR_TAB_UNFOCUSED: PAGE_BG,
        imgui.COLOR_TAB_UNFOCUSED_ACTIVE: (*MAIN_COLOR[:3], 0.20),

        # Buttons
        imgui.COLOR_BUTTON: ELEMENT_BG,
        imgui.COLOR_BUTTON_HOVERED: (*MAIN_COLOR[:3], 0.35),
        imgui.COLOR_BUTTON_ACTIVE: (*MAIN_COLOR[:3], 0.60),

        # Headers (collapsing headers, selectable, etc.)
        imgui.COLOR_HEADER: (*MAIN_COLOR[:3], 0.12),
        imgui.COLOR_HEADER_HOVERED: (*MAIN_COLOR[:3], 0.25),
        imgui.COLOR_HEADER_ACTIVE: (*MAIN_COLOR[:3], 0.40),

        # Separators — main.cpp line 145: ImVec4(1,1,1,0.2)
        imgui.COLOR_SEPARATOR: (1.0, 1.0, 1.0, 0.2),
        imgui.COLOR_SEPARATOR_HOVERED: MAIN_COLOR,
        imgui.COLOR_SEPARATOR_ACTIVE: ACCENT_HOVER,

        # Sliders — gradient fill uses accent
        imgui.COLOR_SLIDER_GRAB: MAIN_COLOR,
        imgui.COLOR_SLIDER_GRAB_ACTIVE: ACCENT_HOVER,

        # Checkbox mark — white per LianFlow
        imgui.COLOR_CHECK_MARK: CHECKBOX_MARK,

        # Scrollbar — near invisible
        imgui.COLOR_SCROLLBAR_BACKGROUND: SCROLLBAR_BG,
        imgui.COLOR_SCROLLBAR_GRAB: (*TEXT_DEFAULT[:3], 0.20),
        imgui.COLOR_SCROLLBAR_GRAB_HOVERED: (*TEXT_DEFAULT[:3], 0.35),
        imgui.COLOR_SCROLLBAR_GRAB_ACTIVE: (*MAIN_COLOR[:3], 0.50),

        # Text
        imgui.COLOR_TEXT: TEXT_ACTIVE,
        imgui.COLOR_TEXT_DISABLED: TEXT_DEFAULT,

        # Resize grip
        imgui.COLOR_RESIZE_GRIP: TRANSPARENT,
        imgui.COLOR_RESIZE_GRIP_HOVERED: (*MAIN_COLOR[:3], 0.30),
        imgui.COLOR_RESIZE_GRIP_ACTIVE: MAIN_COLOR,

        # Nav
        imgui.COLOR_NAV_HIGHLIGHT: MAIN_COLOR,
    }

    if IMGUI_BACKEND == "imgui_bundle":
        from imgui_bundle.imgui import ImVec4, Col_
        for col_idx, rgba in color_map.items():
            style.set_color_(Col_(col_idx), ImVec4(*rgba))
    else:
        colors = style.colors
        for col_idx, rgba in color_map.items():
            colors[col_idx] = rgba


# ── Public alias ──────────────────────────────────────────────────
apply_tuborg_lianflow_theme = apply_theme
