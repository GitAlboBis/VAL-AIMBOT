"""
Task 15.1: Color Palette Verification Script

This script verifies that all color values in theme.py match the LianFlow reference
implementation from ImGui LianFlow/imgui_settings.h

Reference: ImGui LianFlow/imgui_settings.h (namespace c::)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui import theme


def approx_equal(actual, expected, tolerance=0.001):
    """Check if two tuples are approximately equal within tolerance."""
    if len(actual) != len(expected):
        return False
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected))


def verify_color(name, actual, expected):
    """Verify a single color matches the expected value."""
    if approx_equal(actual, expected):
        print(f"✓ {name}: PASS")
        return True
    else:
        print(f"✗ {name}: FAIL")
        print(f"  Expected: {expected}")
        print(f"  Got:      {actual}")
        return False


def main():
    """Run all color verification checks."""
    print("=" * 70)
    print("Color Palette Verification - Task 15.1")
    print("=" * 70)
    print()
    
    all_passed = True
    
    # Primary Palette
    print("PRIMARY PALETTE (namespace c::)")
    print("-" * 70)
    all_passed &= verify_color("MAIN_COLOR", theme.MAIN_COLOR, (173/255, 143/255, 233/255, 1.0))
    all_passed &= verify_color("SECOND_COLOR", theme.SECOND_COLOR, (100/255, 92/255, 122/255, 1.0))
    all_passed &= verify_color("BACKGROUND_COLOR", theme.BACKGROUND_COLOR, (20/255, 20/255, 20/255, 0.5))
    all_passed &= verify_color("STROKE_COLOR", theme.STROKE_COLOR, (1.0, 1.0, 1.0, 0.0))
    all_passed &= verify_color("WINDOW_BG_COLOR", theme.WINDOW_BG_COLOR, (22/255, 22/255, 22/255, 0.71))
    all_passed &= verify_color("SEPARATOR", theme.SEPARATOR, (22/255, 23/255, 26/255, 1.0))
    print()
    
    # Animation Colors
    print("ANIMATION COLORS (namespace c::anim::)")
    print("-" * 70)
    all_passed &= verify_color("ANIM_ACTIVE", theme.ANIM_ACTIVE, (114/255, 149/255, 255/255, 1.0))
    all_passed &= verify_color("ANIM_DEFAULT", theme.ANIM_DEFAULT, (22/255, 23/255, 26/255, 1.0))
    print()
    
    # Background Panel
    print("BACKGROUND PANEL (namespace c::bg::)")
    print("-" * 70)
    all_passed &= verify_color("BG_BACKGROUND", theme.BG_BACKGROUND, (22/255, 22/255, 22/255, 0.71))
    if theme.BG_SIZE == (850.0, 596.0):
        print(f"✓ BG_SIZE: PASS")
    else:
        print(f"✗ BG_SIZE: FAIL - Expected (850.0, 596.0), Got {theme.BG_SIZE}")
        all_passed = False
    if theme.BG_ROUNDING == 15.0:
        print(f"✓ BG_ROUNDING: PASS")
    else:
        print(f"✗ BG_ROUNDING: FAIL - Expected 15.0, Got {theme.BG_ROUNDING}")
        all_passed = False
    print()
    
    # Child Panel
    print("CHILD PANEL (namespace c::child::)")
    print("-" * 70)
    all_passed &= verify_color("CHILD_BACKGROUND", theme.CHILD_BACKGROUND, (60/255, 60/255, 60/255, 0.25))
    all_passed &= verify_color("CHILD_STROKE", theme.CHILD_STROKE, (18/255, 18/255, 24/255, 0.0))
    if theme.CHILD_ROUNDING == 8.0:
        print(f"✓ CHILD_ROUNDING: PASS")
    else:
        print(f"✗ CHILD_ROUNDING: FAIL - Expected 8.0, Got {theme.CHILD_ROUNDING}")
        all_passed = False
    print()
    
    # Page/Tab Colors
    print("PAGE/TAB COLORS (namespace c::page::)")
    print("-" * 70)
    all_passed &= verify_color("PAGE_BG_ACTIVE", theme.PAGE_BG_ACTIVE, (21/255, 22/255, 25/255, 1.0))
    all_passed &= verify_color("PAGE_BG", theme.PAGE_BG, (16/255, 17/255, 18/255, 1.0))
    all_passed &= verify_color("PAGE_TEXT_HOV", theme.PAGE_TEXT_HOV, (150/255, 162/255, 205/255, 1.0))
    all_passed &= verify_color("PAGE_TEXT", theme.PAGE_TEXT, (150/255, 162/255, 205/255, 1.0))
    if theme.PAGE_ROUNDING == 4.0:
        print(f"✓ PAGE_ROUNDING: PASS")
    else:
        print(f"✗ PAGE_ROUNDING: FAIL - Expected 4.0, Got {theme.PAGE_ROUNDING}")
        all_passed = False
    print()
    
    # Element Colors
    print("ELEMENT COLORS (namespace c::elements::)")
    print("-" * 70)
    all_passed &= verify_color("ELEMENT_BG_HOV", theme.ELEMENT_BG_HOV, (21/255, 22/255, 25/255, 1.0))
    all_passed &= verify_color("ELEMENT_BG", theme.ELEMENT_BG, (16/255, 17/255, 18/255, 1.0))
    if theme.ELEMENT_ROUNDING == 2.5:
        print(f"✓ ELEMENT_ROUNDING: PASS")
    else:
        print(f"✗ ELEMENT_ROUNDING: FAIL - Expected 2.5, Got {theme.ELEMENT_ROUNDING}")
        all_passed = False
    print()
    
    # Text Colors
    print("TEXT COLORS (namespace c::text::)")
    print("-" * 70)
    all_passed &= verify_color("TEXT_ACTIVE", theme.TEXT_ACTIVE, (1.0, 1.0, 1.0, 1.0))
    all_passed &= verify_color("TEXT_HOVER", theme.TEXT_HOVER, (205/255, 205/255, 205/255, 1.0))
    all_passed &= verify_color("TEXT_DEFAULT", theme.TEXT_DEFAULT, (150/255, 150/255, 150/255, 220/255))
    all_passed &= verify_color("TEXT_DESC_ACTIVE", theme.TEXT_DESC_ACTIVE, (200/255, 200/255, 200/255, 102/255))
    all_passed &= verify_color("TEXT_DESC_HOVER", theme.TEXT_DESC_HOVER, (200/255, 200/255, 200/255, 63/255))
    all_passed &= verify_color("TEXT_DESC_DEFAULT", theme.TEXT_DESC_DEFAULT, (200/255, 200/255, 200/255, 40/255))
    all_passed &= verify_color("TEXT_TEXT_ACTIVE", theme.TEXT_TEXT_ACTIVE, (1.0, 1.0, 1.0, 1.0))
    all_passed &= verify_color("TEXT_TEXT_HOV", theme.TEXT_TEXT_HOV, (150/255, 162/255, 205/255, 1.0))
    all_passed &= verify_color("TEXT_TEXT", theme.TEXT_TEXT, (150/255, 162/255, 205/255, 1.0))
    all_passed &= verify_color("CHECKBOX_MARK", theme.CHECKBOX_MARK, (1.0, 1.0, 1.0, 1.0))
    print()
    
    # Utility Colors
    print("UTILITY COLORS")
    print("-" * 70)
    all_passed &= verify_color("TRANSPARENT", theme.TRANSPARENT, (0.0, 0.0, 0.0, 0.0))
    all_passed &= verify_color("SCROLLBAR_BG", theme.SCROLLBAR_BG, (0.0, 0.0, 0.0, 0.08))
    print()
    
    # Gradient Colors
    print("GRADIENT COLORS (used in sliders and checkboxes)")
    print("-" * 70)
    print("Gradient: SECOND_COLOR → MAIN_COLOR")
    all_passed &= verify_color("  Start (SECOND_COLOR)", theme.SECOND_COLOR, (100/255, 92/255, 122/255, 1.0))
    all_passed &= verify_color("  End (MAIN_COLOR)", theme.MAIN_COLOR, (173/255, 143/255, 233/255, 1.0))
    print()
    
    # Status Indicator Colors
    print("STATUS INDICATOR COLORS")
    print("-" * 70)
    print("ℹ Status colors (green/red/yellow) are not defined in the LianFlow")
    print("  reference implementation. They are application-specific.")
    print()
    
    # Summary
    print("=" * 70)
    if all_passed:
        print("✓ ALL COLOR VERIFICATIONS PASSED")
        print("  All colors in theme.py match the LianFlow reference implementation.")
    else:
        print("✗ SOME COLOR VERIFICATIONS FAILED")
        print("  See details above for mismatches.")
    print("=" * 70)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())
