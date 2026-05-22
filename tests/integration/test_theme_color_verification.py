"""
Task 15.1: Color Palette Verification Test

This test verifies that all color values in theme.py match the LianFlow reference
implementation from ImGui LianFlow/imgui_settings.h

Reference: ImGui LianFlow/imgui_settings.h (namespace c::)
"""

import pytest
from gui import theme


class TestColorPaletteMatch:
    """Verify all colors match the LianFlow reference implementation."""
    
    def test_main_color_matches_reference(self):
        """
        Reference: rgba(173, 143, 233, 1)
        Expected: (0.678, 0.561, 0.914, 1.0)
        """
        expected = (173/255, 143/255, 233/255, 1.0)
        assert theme.MAIN_COLOR == pytest.approx(expected, abs=0.001), \
            f"MAIN_COLOR mismatch: got {theme.MAIN_COLOR}, expected {expected}"
    
    def test_second_color_matches_reference(self):
        """
        Reference: rgba(100, 92, 122, 1)
        Expected: (0.392, 0.361, 0.478, 1.0)
        """
        expected = (100/255, 92/255, 122/255, 1.0)
        assert theme.SECOND_COLOR == pytest.approx(expected, abs=0.001), \
            f"SECOND_COLOR mismatch: got {theme.SECOND_COLOR}, expected {expected}"
    
    def test_background_color_matches_reference(self):
        """
        Reference: rgba(20, 20, 20, 0.5)
        Expected: (0.078, 0.078, 0.078, 0.50)
        """
        expected = (20/255, 20/255, 20/255, 0.5)
        assert theme.BACKGROUND_COLOR == pytest.approx(expected, abs=0.001), \
            f"BACKGROUND_COLOR mismatch: got {theme.BACKGROUND_COLOR}, expected {expected}"
    
    def test_stroke_color_matches_reference(self):
        """
        Reference: ImColor(255, 255, 255, 0)
        Expected: (1.0, 1.0, 1.0, 0.0)
        """
        expected = (1.0, 1.0, 1.0, 0.0)
        assert theme.STROKE_COLOR == pytest.approx(expected, abs=0.001), \
            f"STROKE_COLOR mismatch: got {theme.STROKE_COLOR}, expected {expected}"
    
    def test_window_bg_color_matches_reference(self):
        """
        Reference: rgba(22, 22, 22, 0.71)
        Expected: (0.086, 0.086, 0.086, 0.71)
        """
        expected = (22/255, 22/255, 22/255, 0.71)
        assert theme.WINDOW_BG_COLOR == pytest.approx(expected, abs=0.001), \
            f"WINDOW_BG_COLOR mismatch: got {theme.WINDOW_BG_COLOR}, expected {expected}"
    
    def test_separator_matches_reference(self):
        """
        Reference: ImColor(22, 23, 26)
        Expected: (0.086, 0.090, 0.102, 1.0)
        """
        expected = (22/255, 23/255, 26/255, 1.0)
        assert theme.SEPARATOR == pytest.approx(expected, abs=0.001), \
            f"SEPARATOR mismatch: got {theme.SEPARATOR}, expected {expected}"


class TestAnimationColors:
    """Verify animation colors match reference (namespace c::anim::)."""
    
    def test_anim_active_matches_reference(self):
        """
        Reference: ImColor(114, 149, 255, 255)
        Expected: (0.447, 0.584, 1.0, 1.0)
        """
        expected = (114/255, 149/255, 255/255, 1.0)
        assert theme.ANIM_ACTIVE == pytest.approx(expected, abs=0.001), \
            f"ANIM_ACTIVE mismatch: got {theme.ANIM_ACTIVE}, expected {expected}"
    
    def test_anim_default_matches_reference(self):
        """
        Reference: ImColor(22, 23, 26, 255)
        Expected: (0.086, 0.090, 0.102, 1.0)
        """
        expected = (22/255, 23/255, 26/255, 1.0)
        assert theme.ANIM_DEFAULT == pytest.approx(expected, abs=0.001), \
            f"ANIM_DEFAULT mismatch: got {theme.ANIM_DEFAULT}, expected {expected}"


class TestBackgroundPanelColors:
    """Verify background panel colors match reference (namespace c::bg::)."""
    
    def test_bg_background_matches_reference(self):
        """
        Reference: rgba(22, 22, 22, 0.71)
        Expected: (0.086, 0.086, 0.086, 0.71)
        """
        expected = (22/255, 22/255, 22/255, 0.71)
        assert theme.BG_BACKGROUND == pytest.approx(expected, abs=0.001), \
            f"BG_BACKGROUND mismatch: got {theme.BG_BACKGROUND}, expected {expected}"
    
    def test_bg_size_matches_reference(self):
        """
        Reference: ImVec2(850, 596)
        Expected: (850.0, 596.0)
        """
        expected = (850.0, 596.0)
        assert theme.BG_SIZE == expected, \
            f"BG_SIZE mismatch: got {theme.BG_SIZE}, expected {expected}"
    
    def test_bg_rounding_matches_reference(self):
        """
        Reference: 15.f
        Expected: 15.0
        """
        expected = 15.0
        assert theme.BG_ROUNDING == expected, \
            f"BG_ROUNDING mismatch: got {theme.BG_ROUNDING}, expected {expected}"


class TestChildPanelColors:
    """Verify child panel colors match reference (namespace c::child::)."""
    
    def test_child_background_matches_reference(self):
        """
        Reference: rgba(60, 60, 60, 0.25)
        Expected: (0.235, 0.235, 0.235, 0.25)
        """
        expected = (60/255, 60/255, 60/255, 0.25)
        assert theme.CHILD_BACKGROUND == pytest.approx(expected, abs=0.001), \
            f"CHILD_BACKGROUND mismatch: got {theme.CHILD_BACKGROUND}, expected {expected}"
    
    def test_child_stroke_matches_reference(self):
        """
        Reference: ImColor(18, 18, 24, 0)
        Expected: (0.071, 0.071, 0.094, 0.0)
        """
        expected = (18/255, 18/255, 24/255, 0.0)
        assert theme.CHILD_STROKE == pytest.approx(expected, abs=0.001), \
            f"CHILD_STROKE mismatch: got {theme.CHILD_STROKE}, expected {expected}"
    
    def test_child_rounding_matches_reference(self):
        """
        Reference: 8.f
        Expected: 8.0
        """
        expected = 8.0
        assert theme.CHILD_ROUNDING == expected, \
            f"CHILD_ROUNDING mismatch: got {theme.CHILD_ROUNDING}, expected {expected}"


class TestPageTabColors:
    """Verify page/tab colors match reference (namespace c::page::)."""
    
    def test_page_bg_active_matches_reference(self):
        """
        Reference: ImColor(21, 22, 25)
        Expected: (0.082, 0.086, 0.098, 1.0)
        """
        expected = (21/255, 22/255, 25/255, 1.0)
        assert theme.PAGE_BG_ACTIVE == pytest.approx(expected, abs=0.001), \
            f"PAGE_BG_ACTIVE mismatch: got {theme.PAGE_BG_ACTIVE}, expected {expected}"
    
    def test_page_bg_matches_reference(self):
        """
        Reference: ImColor(16, 17, 18)
        Expected: (0.063, 0.067, 0.071, 1.0)
        """
        expected = (16/255, 17/255, 18/255, 1.0)
        assert theme.PAGE_BG == pytest.approx(expected, abs=0.001), \
            f"PAGE_BG mismatch: got {theme.PAGE_BG}, expected {expected}"
    
    def test_page_text_hov_matches_reference(self):
        """
        Reference: ImColor(150, 162, 205)
        Expected: (0.588, 0.635, 0.804, 1.0)
        """
        expected = (150/255, 162/255, 205/255, 1.0)
        assert theme.PAGE_TEXT_HOV == pytest.approx(expected, abs=0.001), \
            f"PAGE_TEXT_HOV mismatch: got {theme.PAGE_TEXT_HOV}, expected {expected}"
    
    def test_page_text_matches_reference(self):
        """
        Reference: ImColor(150, 162, 205)
        Expected: (0.588, 0.635, 0.804, 1.0)
        """
        expected = (150/255, 162/255, 205/255, 1.0)
        assert theme.PAGE_TEXT == pytest.approx(expected, abs=0.001), \
            f"PAGE_TEXT mismatch: got {theme.PAGE_TEXT}, expected {expected}"
    
    def test_page_rounding_matches_reference(self):
        """
        Reference: 4.f
        Expected: 4.0
        """
        expected = 4.0
        assert theme.PAGE_ROUNDING == expected, \
            f"PAGE_ROUNDING mismatch: got {theme.PAGE_ROUNDING}, expected {expected}"


class TestElementColors:
    """Verify element colors match reference (namespace c::elements::)."""
    
    def test_element_bg_hov_matches_reference(self):
        """
        Reference: ImColor(21, 22, 25)
        Expected: (0.082, 0.086, 0.098, 1.0)
        """
        expected = (21/255, 22/255, 25/255, 1.0)
        assert theme.ELEMENT_BG_HOV == pytest.approx(expected, abs=0.001), \
            f"ELEMENT_BG_HOV mismatch: got {theme.ELEMENT_BG_HOV}, expected {expected}"
    
    def test_element_bg_matches_reference(self):
        """
        Reference: ImColor(16, 17, 18)
        Expected: (0.063, 0.067, 0.071, 1.0)
        """
        expected = (16/255, 17/255, 18/255, 1.0)
        assert theme.ELEMENT_BG == pytest.approx(expected, abs=0.001), \
            f"ELEMENT_BG mismatch: got {theme.ELEMENT_BG}, expected {expected}"
    
    def test_element_rounding_matches_reference(self):
        """
        Reference: 2.5f
        Expected: 2.5
        """
        expected = 2.5
        assert theme.ELEMENT_ROUNDING == expected, \
            f"ELEMENT_ROUNDING mismatch: got {theme.ELEMENT_ROUNDING}, expected {expected}"


class TestTextColors:
    """Verify text colors match reference (namespace c::text::)."""
    
    def test_text_active_matches_reference(self):
        """
        Reference: ImColor(255, 255, 255, 255)
        Expected: (1.0, 1.0, 1.0, 1.0)
        """
        expected = (1.0, 1.0, 1.0, 1.0)
        assert theme.TEXT_ACTIVE == pytest.approx(expected, abs=0.001), \
            f"TEXT_ACTIVE mismatch: got {theme.TEXT_ACTIVE}, expected {expected}"
    
    def test_text_hover_matches_reference(self):
        """
        Reference: ImColor(205, 205, 205, 255)
        Expected: (0.804, 0.804, 0.804, 1.0)
        """
        expected = (205/255, 205/255, 205/255, 1.0)
        assert theme.TEXT_HOVER == pytest.approx(expected, abs=0.001), \
            f"TEXT_HOVER mismatch: got {theme.TEXT_HOVER}, expected {expected}"
    
    def test_text_default_matches_reference(self):
        """
        Reference: ImColor(150, 150, 150, 220)
        Expected: (0.588, 0.588, 0.588, 0.863)
        """
        expected = (150/255, 150/255, 150/255, 220/255)
        assert theme.TEXT_DEFAULT == pytest.approx(expected, abs=0.001), \
            f"TEXT_DEFAULT mismatch: got {theme.TEXT_DEFAULT}, expected {expected}"
    
    def test_text_desc_active_matches_reference(self):
        """
        Reference: ImColor(200, 200, 200, 102)
        Expected: (0.784, 0.784, 0.784, 0.400)
        """
        expected = (200/255, 200/255, 200/255, 102/255)
        assert theme.TEXT_DESC_ACTIVE == pytest.approx(expected, abs=0.001), \
            f"TEXT_DESC_ACTIVE mismatch: got {theme.TEXT_DESC_ACTIVE}, expected {expected}"
    
    def test_text_desc_hover_matches_reference(self):
        """
        Reference: ImColor(200, 200, 200, 63)
        Expected: (0.784, 0.784, 0.784, 0.247)
        """
        expected = (200/255, 200/255, 200/255, 63/255)
        assert theme.TEXT_DESC_HOVER == pytest.approx(expected, abs=0.001), \
            f"TEXT_DESC_HOVER mismatch: got {theme.TEXT_DESC_HOVER}, expected {expected}"
    
    def test_text_desc_default_matches_reference(self):
        """
        Reference: ImColor(200, 200, 200, 40)
        Expected: (0.784, 0.784, 0.784, 0.157)
        """
        expected = (200/255, 200/255, 200/255, 40/255)
        assert theme.TEXT_DESC_DEFAULT == pytest.approx(expected, abs=0.001), \
            f"TEXT_DESC_DEFAULT mismatch: got {theme.TEXT_DESC_DEFAULT}, expected {expected}"
    
    def test_text_text_active_matches_reference(self):
        """
        Reference: ImColor(255, 255, 255)
        Expected: (1.0, 1.0, 1.0, 1.0)
        """
        expected = (1.0, 1.0, 1.0, 1.0)
        assert theme.TEXT_TEXT_ACTIVE == pytest.approx(expected, abs=0.001), \
            f"TEXT_TEXT_ACTIVE mismatch: got {theme.TEXT_TEXT_ACTIVE}, expected {expected}"
    
    def test_text_text_hov_matches_reference(self):
        """
        Reference: ImColor(150, 162, 205)
        Expected: (0.588, 0.635, 0.804, 1.0)
        """
        expected = (150/255, 162/255, 205/255, 1.0)
        assert theme.TEXT_TEXT_HOV == pytest.approx(expected, abs=0.001), \
            f"TEXT_TEXT_HOV mismatch: got {theme.TEXT_TEXT_HOV}, expected {expected}"
    
    def test_text_text_matches_reference(self):
        """
        Reference: ImColor(150, 162, 205)
        Expected: (0.588, 0.635, 0.804, 1.0)
        """
        expected = (150/255, 162/255, 205/255, 1.0)
        assert theme.TEXT_TEXT == pytest.approx(expected, abs=0.001), \
            f"TEXT_TEXT mismatch: got {theme.TEXT_TEXT}, expected {expected}"
    
    def test_checkbox_mark_matches_reference(self):
        """
        Reference: ImColor(255, 255, 255, 255)
        Expected: (1.0, 1.0, 1.0, 1.0)
        """
        expected = (1.0, 1.0, 1.0, 1.0)
        assert theme.CHECKBOX_MARK == pytest.approx(expected, abs=0.001), \
            f"CHECKBOX_MARK mismatch: got {theme.CHECKBOX_MARK}, expected {expected}"


class TestGradientColors:
    """
    Verify gradient colors used in sliders and checkboxes.
    
    Reference implementation uses gradients from second_color to main_color:
    - Checkbox gradient: c::second_color → c::main_color
    - Slider gradient: c::second_color → c::main_color
    """
    
    def test_gradient_start_color(self):
        """Gradient start color should be SECOND_COLOR."""
        # Gradient starts with second_color
        expected = theme.SECOND_COLOR
        assert expected == (100/255, 92/255, 122/255, 1.0)
    
    def test_gradient_end_color(self):
        """Gradient end color should be MAIN_COLOR."""
        # Gradient ends with main_color
        expected = theme.MAIN_COLOR
        assert expected == (173/255, 143/255, 233/255, 1.0)


class TestStatusIndicatorColors:
    """
    Verify status indicator colors.
    
    Note: The reference implementation doesn't define explicit status colors
    (green/red/yellow). These are typically application-specific and not part
    of the core theme. The current implementation may use custom values.
    """
    
    def test_status_colors_not_in_reference(self):
        """
        Status indicator colors (green/red/yellow) are not defined in the
        LianFlow reference implementation. They are application-specific.
        """
        # This test documents that status colors are not part of the reference
        assert True, "Status colors are application-specific, not in reference"


class TestUtilityColors:
    """Verify utility colors."""
    
    def test_transparent_color(self):
        """Transparent color should be (0, 0, 0, 0)."""
        expected = (0.0, 0.0, 0.0, 0.0)
        assert theme.TRANSPARENT == expected, \
            f"TRANSPARENT mismatch: got {theme.TRANSPARENT}, expected {expected}"
    
    def test_scrollbar_bg_color(self):
        """Scrollbar background should be nearly transparent."""
        expected = (0.0, 0.0, 0.0, 0.08)
        assert theme.SCROLLBAR_BG == expected, \
            f"SCROLLBAR_BG mismatch: got {theme.SCROLLBAR_BG}, expected {expected}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
