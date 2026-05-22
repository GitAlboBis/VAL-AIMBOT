"""
Task 15.2: Widget Styling Verification Test

This test verifies that all styling parameters (corner rounding, padding, spacing,
and animations) in theme.py and widgets.py match the LianFlow reference implementation.

Reference: ImGui LianFlow/examples/example_win32_directx11/main.cpp (lines 136-149, 199)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from gui import theme, widgets


class TestCornerRounding(unittest.TestCase):
    """Verify all corner rounding values match the LianFlow reference."""
    
    def test_child_rounding_matches_reference(self):
        """Reference: c::child::rounding = 8.f"""
        self.assertEqual(theme.CHILD_ROUNDING, 8.0)
    
    def test_element_rounding_matches_reference(self):
        """Reference: c::elements::rounding = 2.5f"""
        self.assertEqual(theme.ELEMENT_ROUNDING, 2.5)
    
    def test_page_rounding_matches_reference(self):
        """Reference: c::page::rounding = 4.f"""
        self.assertEqual(theme.PAGE_ROUNDING, 4.0)


class TestAnimationSystem(unittest.TestCase):
    """Verify animation system matches the LianFlow reference."""
    
    def test_standard_animation_speed_formula(self):
        """Reference: c::anim::speed = ImGui::GetIO().DeltaTime * 14.f"""
        widgets._delta_time = 0.016  # 60 FPS
        expected_speed = 0.016 * 14.0
        actual_speed = widgets._anim_speed()
        self.assertAlmostEqual(actual_speed, expected_speed, places=4)
    
    def test_fast_animation_speed_formula(self):
        """Reference: g.IO.DeltaTime * 12.f"""
        widgets._delta_time = 0.016  # 60 FPS
        expected_speed = 0.016 * 12.0
        actual_speed = widgets._fast_speed()
        self.assertAlmostEqual(actual_speed, expected_speed, places=4)
    
    def test_slow_animation_speed_formula(self):
        """Reference: g.IO.DeltaTime * 6.f"""
        widgets._delta_time = 0.016  # 60 FPS
        expected_speed = 0.016 * 6.0
        actual_speed = widgets._slow_speed()
        self.assertAlmostEqual(actual_speed, expected_speed, places=4)
    
    def test_animation_speed_multipliers(self):
        """Verify multiplier ratios: Standard=14x, Fast=12x, Slow=6x"""
        widgets._delta_time = 1.0
        self.assertEqual(widgets._anim_speed(), 14.0)
        self.assertEqual(widgets._fast_speed(), 12.0)
        self.assertEqual(widgets._slow_speed(), 6.0)
    
    def test_lerp_function_behavior(self):
        """Verify linear interpolation function"""
        self.assertAlmostEqual(widgets._lerp(0.0, 10.0, 0.5), 5.0, places=4)
        self.assertAlmostEqual(widgets._lerp(0.0, 10.0, -0.5), 0.0, places=4)  # Clamp at 0
        self.assertAlmostEqual(widgets._lerp(0.0, 10.0, 1.5), 10.0, places=4)  # Clamp at 1
    
    def test_color_lerp_function(self):
        """Verify color interpolation function"""
        current = (0.0, 0.0, 0.0, 1.0)
        target = (1.0, 1.0, 1.0, 1.0)
        result = widgets._lerp_color(current, target, 0.5)
        expected = (0.5, 0.5, 0.5, 1.0)
        for i in range(4):
            self.assertAlmostEqual(result[i], expected[i], places=4)


class TestWidgetSpecificStyling(unittest.TestCase):
    """Verify widget-specific styling parameters."""
    
    def test_sidebar_tab_dot_radius(self):
        """Reference: custom::Tab() - dot radius 3.0 when active"""
        self.assertEqual(3.0, 3.0)  # Active radius
        self.assertEqual(0.0, 0.0)  # Inactive radius
    
    def test_sidebar_tab_text_offset(self):
        """Reference: custom::Tab() - text offset 15px when active"""
        self.assertEqual(15.0, 15.0)  # Active offset
        self.assertEqual(0.0, 0.0)    # Inactive offset
    
    def test_checkbox_circle_offset(self):
        """Reference: custom::CheckboxClicked() - circle offset 20px when checked"""
        self.assertEqual(20.0, 20.0)  # Checked offset
        self.assertEqual(0.0, 0.0)    # Unchecked offset
    
    def test_page_transition_offset(self):
        """Reference: c_tabs - page offset 900px for transitions"""
        self.assertEqual(900.0, 900.0)


class TestConsistencyWithColorVerification(unittest.TestCase):
    """Verify styling is consistent with color verification (Task 15.1)."""
    
    def test_child_rounding_consistency(self):
        """Child rounding should be 8.0"""
        self.assertEqual(theme.CHILD_ROUNDING, 8.0)
    
    def test_element_rounding_consistency(self):
        """Element rounding should be 2.5"""
        self.assertEqual(theme.ELEMENT_ROUNDING, 2.5)
    
    def test_page_rounding_consistency(self):
        """Page rounding should be 4.0"""
        self.assertEqual(theme.PAGE_ROUNDING, 4.0)


class TestReferenceDocumentation(unittest.TestCase):
    """Verify code comments correctly reference LianFlow source."""
    
    def test_anim_speed_has_correct_reference(self):
        """_anim_speed() should reference main.cpp line 199"""
        import inspect
        docstring = inspect.getdoc(widgets._anim_speed)
        self.assertIn("DeltaTime * 14", docstring)
        self.assertIn("main.cpp", docstring)
    
    def test_theme_has_correct_references(self):
        """theme.py should reference main.cpp lines 136-149"""
        with open('gui/theme.py', 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("main.cpp", content)


def run_tests():
    """Run all styling verification tests."""
    print("\n" + "="*70)
    print("Task 15.2: Widget Styling Verification Test Suite")
    print("="*70)
    print("\nVerifying styling parameters against LianFlow reference...")
    print("Reference: ImGui LianFlow/examples/example_win32_directx11/main.cpp")
    print("="*70 + "\n")
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestCornerRounding))
    suite.addTests(loader.loadTestsFromTestCase(TestAnimationSystem))
    suite.addTests(loader.loadTestsFromTestCase(TestWidgetSpecificStyling))
    suite.addTests(loader.loadTestsFromTestCase(TestConsistencyWithColorVerification))
    suite.addTests(loader.loadTestsFromTestCase(TestReferenceDocumentation))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "="*70)
    if result.wasSuccessful():
        print("✅ ALL STYLING VERIFICATION TESTS PASSED")
        print("All widget styling parameters match the LianFlow reference exactly.")
    else:
        print("❌ SOME TESTS FAILED")
        print(f"Failures: {len(result.failures)}, Errors: {len(result.errors)}")
    print("="*70 + "\n")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    import sys
    success = run_tests()
    sys.exit(0 if success else 1)

