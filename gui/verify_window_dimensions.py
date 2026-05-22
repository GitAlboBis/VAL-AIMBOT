"""
Window Dimensions and Background Verification Script

Verifies that window dimensions and background colors match LianFlow reference.
This script can be run without pytest.

Reference: ImGui LianFlow/examples/example_win32_directx11/main.cpp
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.theme import BG_SIZE, BG_ROUNDING, BG_BACKGROUND, WINDOW_BG_COLOR
from gui.app import WINDOW_W, WINDOW_H


def verify_window_dimensions():
    """Verify window dimensions match reference (850x596)."""
    print("=" * 70)
    print("WINDOW DIMENSIONS VERIFICATION")
    print("=" * 70)
    
    errors = []
    
    # Test window width
    if WINDOW_W != 850:
        errors.append(f"❌ Window width: expected 850, got {WINDOW_W}")
    else:
        print(f"✅ Window width: {WINDOW_W} (matches reference)")
    
    # Test window height
    if WINDOW_H != 596:
        errors.append(f"❌ Window height: expected 596, got {WINDOW_H}")
    else:
        print(f"✅ Window height: {WINDOW_H} (matches reference)")
    
    # Test BG_SIZE tuple
    if BG_SIZE != (850.0, 596.0):
        errors.append(f"❌ BG_SIZE: expected (850.0, 596.0), got {BG_SIZE}")
    else:
        print(f"✅ BG_SIZE: {BG_SIZE} (matches reference)")
    
    # Test aspect ratio
    expected_ratio = 850.0 / 596.0
    actual_ratio = WINDOW_W / WINDOW_H
    if abs(actual_ratio - expected_ratio) > 0.001:
        errors.append(f"❌ Aspect ratio: expected ~{expected_ratio:.3f}, got {actual_ratio:.3f}")
    else:
        print(f"✅ Aspect ratio: {actual_ratio:.3f} (matches reference)")
    
    return errors


def verify_window_rounding():
    """Verify window rounding matches reference (15.0)."""
    print("\n" + "=" * 70)
    print("WINDOW ROUNDING VERIFICATION")
    print("=" * 70)
    
    errors = []
    
    # Test rounding value
    if BG_ROUNDING != 15.0:
        errors.append(f"❌ Window rounding: expected 15.0, got {BG_ROUNDING}")
    else:
        print(f"✅ Window rounding: {BG_ROUNDING} pixels (matches reference)")
    
    # Test rounding type
    if not isinstance(BG_ROUNDING, float):
        errors.append(f"❌ Rounding type: expected float, got {type(BG_ROUNDING)}")
    else:
        print(f"✅ Rounding type: float (correct)")
    
    return errors


def verify_background_color():
    """Verify background color matches reference rgba(22,22,22,0.71)."""
    print("\n" + "=" * 70)
    print("BACKGROUND COLOR VERIFICATION")
    print("=" * 70)
    
    errors = []
    
    # Reference: rgba(22, 22, 22, 0.71)
    # Normalized: (22/255, 22/255, 22/255, 0.71) = (0.086, 0.086, 0.086, 0.71)
    expected = (0.086, 0.086, 0.086, 0.71)
    
    # Test BG_BACKGROUND
    if BG_BACKGROUND != expected:
        errors.append(f"❌ BG_BACKGROUND: expected {expected}, got {BG_BACKGROUND}")
    else:
        print(f"✅ BG_BACKGROUND: {BG_BACKGROUND} (matches reference)")
    
    # Test WINDOW_BG_COLOR
    if WINDOW_BG_COLOR != expected:
        errors.append(f"❌ WINDOW_BG_COLOR: expected {expected}, got {WINDOW_BG_COLOR}")
    else:
        print(f"✅ WINDOW_BG_COLOR: {WINDOW_BG_COLOR} (matches reference)")
    
    # Test color consistency
    if BG_BACKGROUND != WINDOW_BG_COLOR:
        errors.append(f"❌ Color consistency: BG_BACKGROUND and WINDOW_BG_COLOR don't match")
    else:
        print(f"✅ Color consistency: BG_BACKGROUND == WINDOW_BG_COLOR")
    
    # Test individual components
    REFERENCE_R = 22 / 255.0
    REFERENCE_G = 22 / 255.0
    REFERENCE_B = 22 / 255.0
    REFERENCE_A = 0.71
    
    if abs(BG_BACKGROUND[0] - REFERENCE_R) > 0.001:
        errors.append(f"❌ Red component: expected ~{REFERENCE_R:.3f}, got {BG_BACKGROUND[0]:.3f}")
    else:
        print(f"✅ Red component: {BG_BACKGROUND[0]:.3f} (matches reference)")
    
    if abs(BG_BACKGROUND[1] - REFERENCE_G) > 0.001:
        errors.append(f"❌ Green component: expected ~{REFERENCE_G:.3f}, got {BG_BACKGROUND[1]:.3f}")
    else:
        print(f"✅ Green component: {BG_BACKGROUND[1]:.3f} (matches reference)")
    
    if abs(BG_BACKGROUND[2] - REFERENCE_B) > 0.001:
        errors.append(f"❌ Blue component: expected ~{REFERENCE_B:.3f}, got {BG_BACKGROUND[2]:.3f}")
    else:
        print(f"✅ Blue component: {BG_BACKGROUND[2]:.3f} (matches reference)")
    
    if BG_BACKGROUND[3] != REFERENCE_A:
        errors.append(f"❌ Alpha component: expected {REFERENCE_A}, got {BG_BACKGROUND[3]}")
    else:
        print(f"✅ Alpha component: {BG_BACKGROUND[3]} (matches reference)")
    
    return errors


def verify_constants_derivation():
    """Verify window constants are correctly derived from theme."""
    print("\n" + "=" * 70)
    print("CONSTANTS DERIVATION VERIFICATION")
    print("=" * 70)
    
    errors = []
    
    # Test WINDOW_W derivation
    if WINDOW_W != int(BG_SIZE[0]):
        errors.append(f"❌ WINDOW_W derivation: expected int(BG_SIZE[0])={int(BG_SIZE[0])}, got {WINDOW_W}")
    else:
        print(f"✅ WINDOW_W = int(BG_SIZE[0]) = {WINDOW_W}")
    
    # Test WINDOW_H derivation
    if WINDOW_H != int(BG_SIZE[1]):
        errors.append(f"❌ WINDOW_H derivation: expected int(BG_SIZE[1])={int(BG_SIZE[1])}, got {WINDOW_H}")
    else:
        print(f"✅ WINDOW_H = int(BG_SIZE[1]) = {WINDOW_H}")
    
    # Test types
    if not isinstance(WINDOW_W, int):
        errors.append(f"❌ WINDOW_W type: expected int, got {type(WINDOW_W)}")
    else:
        print(f"✅ WINDOW_W type: int (correct)")
    
    if not isinstance(WINDOW_H, int):
        errors.append(f"❌ WINDOW_H type: expected int, got {type(WINDOW_H)}")
    else:
        print(f"✅ WINDOW_H type: int (correct)")
    
    return errors


def main():
    """Run all verification tests."""
    print("\n" + "=" * 70)
    print("TASK 15.6: WINDOW DIMENSIONS AND BACKGROUND VERIFICATION")
    print("=" * 70)
    print("Reference: ImGui LianFlow/examples/example_win32_directx11/main.cpp")
    print("=" * 70)
    
    all_errors = []
    
    # Run all verification tests
    all_errors.extend(verify_window_dimensions())
    all_errors.extend(verify_window_rounding())
    all_errors.extend(verify_background_color())
    all_errors.extend(verify_constants_derivation())
    
    # Print summary
    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)
    
    if all_errors:
        print(f"\n❌ VERIFICATION FAILED - {len(all_errors)} error(s) found:\n")
        for error in all_errors:
            print(f"  {error}")
        print("\n" + "=" * 70)
        return 1
    else:
        print("\n✅ ALL VERIFICATIONS PASSED")
        print("\nWindow dimensions: 850x596 ✅")
        print("Window rounding: 15.0 pixels ✅")
        print("Background color: rgba(22,22,22,0.71) ✅")
        print("Constants derivation: Correct ✅")
        print("\n" + "=" * 70)
        print("Task 15.6: COMPLETE - Window dimensions and background match reference")
        print("=" * 70)
        return 0


if __name__ == "__main__":
    exit(main())
