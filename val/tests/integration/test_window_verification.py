"""
Window Dimensions and Background Verification Tests

Tests for Task 15.6: Verify window dimensions and background effect match LianFlow reference.

Reference: ImGui LianFlow/examples/example_win32_directx11/main.cpp
"""

import pytest
from gui.theme import BG_SIZE, BG_ROUNDING, BG_BACKGROUND, WINDOW_BG_COLOR
from gui.app import WINDOW_W, WINDOW_H


class TestWindowDimensions:
    """Test window dimensions match LianFlow reference (850x596)."""
    
    def test_window_width(self):
        """Verify window width is exactly 850 pixels."""
        assert WINDOW_W == 850, f"Window width should be 850, got {WINDOW_W}"
    
    def test_window_height(self):
        """Verify window height is exactly 596 pixels."""
        assert WINDOW_H == 596, f"Window height should be 596, got {WINDOW_H}"
    
    def test_bg_size_tuple(self):
        """Verify BG_SIZE tuple matches reference (850.0, 596.0)."""
        assert BG_SIZE == (850.0, 596.0), f"BG_SIZE should be (850.0, 596.0), got {BG_SIZE}"
    
    def test_bg_size_width(self):
        """Verify BG_SIZE width component is 850.0."""
        assert BG_SIZE[0] == 850.0, f"BG_SIZE width should be 850.0, got {BG_SIZE[0]}"
    
    def test_bg_size_height(self):
        """Verify BG_SIZE height component is 596.0."""
        assert BG_SIZE[1] == 596.0, f"BG_SIZE height should be 596.0, got {BG_SIZE[1]}"


class TestWindowRounding:
    """Test window rounding matches LianFlow reference (15.0)."""
    
    def test_bg_rounding(self):
        """Verify window rounding is exactly 15.0 pixels."""
        assert BG_ROUNDING == 15.0, f"Window rounding should be 15.0, got {BG_ROUNDING}"
    
    def test_rounding_type(self):
        """Verify rounding is a float."""
        assert isinstance(BG_ROUNDING, float), f"BG_ROUNDING should be float, got {type(BG_ROUNDING)}"


class TestBackgroundColor:
    """Test background color matches LianFlow reference rgba(22,22,22,0.71)."""
    
    def test_bg_background_color(self):
        """Verify BG_BACKGROUND color matches reference."""
        expected = (0.086, 0.086, 0.086, 0.71)
        assert BG_BACKGROUND == expected, f"BG_BACKGROUND should be {expected}, got {BG_BACKGROUND}"
    
    def test_window_bg_color(self):
        """Verify WINDOW_BG_COLOR matches reference."""
        expected = (0.086, 0.086, 0.086, 0.71)
        assert WINDOW_BG_COLOR == expected, f"WINDOW_BG_COLOR should be {expected}, got {WINDOW_BG_COLOR}"
    
    def test_bg_color_red_component(self):
        """Verify red component is 0.086 (22/255)."""
        assert abs(BG_BACKGROUND[0] - 0.086) < 0.001, f"Red component should be ~0.086, got {BG_BACKGROUND[0]}"
    
    def test_bg_color_green_component(self):
        """Verify green component is 0.086 (22/255)."""
        assert abs(BG_BACKGROUND[1] - 0.086) < 0.001, f"Green component should be ~0.086, got {BG_BACKGROUND[1]}"
    
    def test_bg_color_blue_component(self):
        """Verify blue component is 0.086 (22/255)."""
        assert abs(BG_BACKGROUND[2] - 0.086) < 0.001, f"Blue component should be ~0.086, got {BG_BACKGROUND[2]}"
    
    def test_bg_color_alpha_component(self):
        """Verify alpha component is 0.71 (transparency)."""
        assert BG_BACKGROUND[3] == 0.71, f"Alpha component should be 0.71, got {BG_BACKGROUND[3]}"


class TestWindowConstants:
    """Test window constants are correctly derived from theme."""
    
    def test_window_w_from_bg_size(self):
        """Verify WINDOW_W is derived from BG_SIZE[0]."""
        assert WINDOW_W == int(BG_SIZE[0]), f"WINDOW_W should equal int(BG_SIZE[0])"
    
    def test_window_h_from_bg_size(self):
        """Verify WINDOW_H is derived from BG_SIZE[1]."""
        assert WINDOW_H == int(BG_SIZE[1]), f"WINDOW_H should equal int(BG_SIZE[1])"
    
    def test_window_dimensions_are_integers(self):
        """Verify WINDOW_W and WINDOW_H are integers."""
        assert isinstance(WINDOW_W, int), f"WINDOW_W should be int, got {type(WINDOW_W)}"
        assert isinstance(WINDOW_H, int), f"WINDOW_H should be int, got {type(WINDOW_H)}"


class TestColorConsistency:
    """Test color consistency between BG_BACKGROUND and WINDOW_BG_COLOR."""
    
    def test_bg_colors_match(self):
        """Verify BG_BACKGROUND and WINDOW_BG_COLOR are identical."""
        assert BG_BACKGROUND == WINDOW_BG_COLOR, \
            f"BG_BACKGROUND and WINDOW_BG_COLOR should match: {BG_BACKGROUND} vs {WINDOW_BG_COLOR}"
    
    def test_color_tuple_length(self):
        """Verify color tuples have 4 components (RGBA)."""
        assert len(BG_BACKGROUND) == 4, f"BG_BACKGROUND should have 4 components, got {len(BG_BACKGROUND)}"
        assert len(WINDOW_BG_COLOR) == 4, f"WINDOW_BG_COLOR should have 4 components, got {len(WINDOW_BG_COLOR)}"


class TestReferenceAlignment:
    """Test alignment with LianFlow reference values."""
    
    def test_reference_window_width(self):
        """Verify window width matches LianFlow reference (850)."""
        REFERENCE_WIDTH = 850
        assert WINDOW_W == REFERENCE_WIDTH, \
            f"Window width should match reference {REFERENCE_WIDTH}, got {WINDOW_W}"
    
    def test_reference_window_height(self):
        """Verify window height matches LianFlow reference (596)."""
        REFERENCE_HEIGHT = 596
        assert WINDOW_H == REFERENCE_HEIGHT, \
            f"Window height should match reference {REFERENCE_HEIGHT}, got {WINDOW_H}"
    
    def test_reference_rounding(self):
        """Verify rounding matches LianFlow reference (15.0)."""
        REFERENCE_ROUNDING = 15.0
        assert BG_ROUNDING == REFERENCE_ROUNDING, \
            f"Rounding should match reference {REFERENCE_ROUNDING}, got {BG_ROUNDING}"
    
    def test_reference_background_rgba(self):
        """Verify background color matches LianFlow reference rgba(22,22,22,0.71)."""
        # Reference: rgba(22, 22, 22, 0.71)
        # Normalized: (22/255, 22/255, 22/255, 0.71) = (0.086, 0.086, 0.086, 0.71)
        REFERENCE_R = 22 / 255.0
        REFERENCE_G = 22 / 255.0
        REFERENCE_B = 22 / 255.0
        REFERENCE_A = 0.71
        
        assert abs(BG_BACKGROUND[0] - REFERENCE_R) < 0.001, \
            f"Red component should be ~{REFERENCE_R}, got {BG_BACKGROUND[0]}"
        assert abs(BG_BACKGROUND[1] - REFERENCE_G) < 0.001, \
            f"Green component should be ~{REFERENCE_G}, got {BG_BACKGROUND[1]}"
        assert abs(BG_BACKGROUND[2] - REFERENCE_B) < 0.001, \
            f"Blue component should be ~{REFERENCE_B}, got {BG_BACKGROUND[2]}"
        assert BG_BACKGROUND[3] == REFERENCE_A, \
            f"Alpha component should be {REFERENCE_A}, got {BG_BACKGROUND[3]}"


class TestAspectRatio:
    """Test window aspect ratio."""
    
    def test_aspect_ratio(self):
        """Verify window aspect ratio is approximately 1.426 (850/596)."""
        expected_ratio = 850.0 / 596.0  # ~1.426
        actual_ratio = WINDOW_W / WINDOW_H
        assert abs(actual_ratio - expected_ratio) < 0.001, \
            f"Aspect ratio should be ~{expected_ratio}, got {actual_ratio}"
    
    def test_aspect_ratio_from_bg_size(self):
        """Verify BG_SIZE aspect ratio matches window aspect ratio."""
        bg_ratio = BG_SIZE[0] / BG_SIZE[1]
        window_ratio = WINDOW_W / WINDOW_H
        assert abs(bg_ratio - window_ratio) < 0.001, \
            f"BG_SIZE ratio ({bg_ratio}) should match window ratio ({window_ratio})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
