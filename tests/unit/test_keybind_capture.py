"""
Unit tests for keybind capture functionality.

Tests the keybind capture UI components including:
- Keybind capture mode activation
- Key name conversion (VK to readable format)
- System key validation
- Duplicate keybind detection
- Capture state management
"""

import unittest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from gui.widgets import (
    get_key_name,
    is_system_key,
    start_keybind_capture,
    stop_keybind_capture,
    is_capturing_keybind,
    get_captured_key,
    _keybind_capture_state,
    _VK_NAMES,
    _SYSTEM_KEYS,
)


class TestKeyNameConversion(unittest.TestCase):
    """Test virtual key code to readable name conversion."""
    
    def test_get_key_name_common_keys(self):
        """Test common key name conversions."""
        self.assertEqual(get_key_name(20), "CapsLock")
        self.assertEqual(get_key_name(112), "F1")
        self.assertEqual(get_key_name(121), "F10")
        self.assertEqual(get_key_name(123), "F12")
        self.assertEqual(get_key_name(32), "Space")
        self.assertEqual(get_key_name(13), "Enter")
        self.assertEqual(get_key_name(27), "Escape")
    
    def test_get_key_name_mouse_buttons(self):
        """Test mouse button name conversions."""
        self.assertEqual(get_key_name(1), "LMB")
        self.assertEqual(get_key_name(2), "RMB")
        self.assertEqual(get_key_name(4), "MMB")
        self.assertEqual(get_key_name(5), "Mouse4")
        self.assertEqual(get_key_name(6), "Mouse5")
    
    def test_get_key_name_letters(self):
        """Test letter key name conversions."""
        self.assertEqual(get_key_name(65), "A")
        self.assertEqual(get_key_name(90), "Z")
        self.assertEqual(get_key_name(77), "M")
    
    def test_get_key_name_numbers(self):
        """Test number key name conversions."""
        self.assertEqual(get_key_name(48), "0")
        self.assertEqual(get_key_name(57), "9")
        self.assertEqual(get_key_name(53), "5")
    
    def test_get_key_name_numpad(self):
        """Test numpad key name conversions."""
        self.assertEqual(get_key_name(96), "Num0")
        self.assertEqual(get_key_name(105), "Num9")
    
    def test_get_key_name_unknown(self):
        """Test unknown key code fallback."""
        self.assertEqual(get_key_name(999), "Key#999")
        self.assertEqual(get_key_name(500), "Key#500")


class TestSystemKeyValidation(unittest.TestCase):
    """Test system key validation."""
    
    def test_is_system_key_escape(self):
        """Test that Escape is identified as a system key."""
        self.assertTrue(is_system_key(27))
    
    def test_is_system_key_normal_keys(self):
        """Test that normal keys are not system keys."""
        self.assertFalse(is_system_key(20))  # CapsLock
        self.assertFalse(is_system_key(112))  # F1
        self.assertFalse(is_system_key(65))  # A
        self.assertFalse(is_system_key(32))  # Space


class TestCaptureStateManagement(unittest.TestCase):
    """Test keybind capture state management."""
    
    def setUp(self):
        """Reset capture state before each test."""
        stop_keybind_capture()
    
    def test_start_keybind_capture(self):
        """Test starting keybind capture mode."""
        widget_id = "test_widget"
        start_keybind_capture(widget_id)
        
        self.assertTrue(_keybind_capture_state['active'])
        self.assertEqual(_keybind_capture_state['widget_id'], widget_id)
        self.assertIsNone(_keybind_capture_state['captured_key'])
    
    def test_stop_keybind_capture(self):
        """Test stopping keybind capture mode."""
        start_keybind_capture("test_widget")
        stop_keybind_capture()
        
        self.assertFalse(_keybind_capture_state['active'])
        self.assertIsNone(_keybind_capture_state['widget_id'])
        self.assertIsNone(_keybind_capture_state['captured_key'])
    
    def test_is_capturing_keybind_no_widget(self):
        """Test checking if any capture is active."""
        self.assertFalse(is_capturing_keybind())
        
        start_keybind_capture("test_widget")
        self.assertTrue(is_capturing_keybind())
        
        stop_keybind_capture()
        self.assertFalse(is_capturing_keybind())
    
    def test_is_capturing_keybind_specific_widget(self):
        """Test checking if specific widget is capturing."""
        widget_id = "test_widget"
        other_widget_id = "other_widget"
        
        start_keybind_capture(widget_id)
        
        self.assertTrue(is_capturing_keybind(widget_id))
        self.assertFalse(is_capturing_keybind(other_widget_id))
    
    def test_get_captured_key_none(self):
        """Test getting captured key when none captured."""
        self.assertIsNone(get_captured_key())
    
    def test_get_captured_key_clears_state(self):
        """Test that getting captured key clears the state."""
        start_keybind_capture("test_widget")
        _keybind_capture_state['captured_key'] = 20  # CapsLock
        
        key = get_captured_key()
        self.assertEqual(key, 20)
        
        # Second call should return None (state cleared)
        key = get_captured_key()
        self.assertIsNone(key)


class TestKeybindValidation(unittest.TestCase):
    """Test keybind validation logic."""
    
    def test_duplicate_detection_logic(self):
        """Test the logic for detecting duplicate keybinds."""
        # This tests the logic that would be used in keybind_button
        all_keybinds = {
            'Activation Key': 'CapsLock',
            'Panic Key': 'F10',
        }
        
        # Check for duplicate
        new_key = 'CapsLock'
        current_label = 'Panic Key'
        
        is_duplicate = False
        for bind_label, bind_key in all_keybinds.items():
            if bind_label != current_label and bind_key == new_key:
                is_duplicate = True
                break
        
        self.assertTrue(is_duplicate)
    
    def test_no_duplicate_same_key_same_label(self):
        """Test that setting the same key to the same label is not a duplicate."""
        all_keybinds = {
            'Activation Key': 'CapsLock',
            'Panic Key': 'F10',
        }
        
        # Setting Activation Key to CapsLock again (same label)
        new_key = 'CapsLock'
        current_label = 'Activation Key'
        
        is_duplicate = False
        for bind_label, bind_key in all_keybinds.items():
            if bind_label != current_label and bind_key == new_key:
                is_duplicate = True
                break
        
        self.assertFalse(is_duplicate)
    
    def test_no_duplicate_different_keys(self):
        """Test that different keys are not duplicates."""
        all_keybinds = {
            'Activation Key': 'CapsLock',
            'Panic Key': 'F10',
        }
        
        # Setting Panic Key to F11 (different from all existing)
        new_key = 'F11'
        current_label = 'Panic Key'
        
        is_duplicate = False
        for bind_label, bind_key in all_keybinds.items():
            if bind_label != current_label and bind_key == new_key:
                is_duplicate = True
                break
        
        self.assertFalse(is_duplicate)


class TestVKNamesCompleteness(unittest.TestCase):
    """Test that VK_NAMES mapping is complete for common keys."""
    
    def test_function_keys_complete(self):
        """Test that all F1-F12 keys are mapped."""
        for i in range(12):
            vk = 112 + i
            self.assertIn(vk, _VK_NAMES)
            self.assertEqual(_VK_NAMES[vk], f"F{i + 1}")
    
    def test_letters_complete(self):
        """Test that all A-Z keys are mapped."""
        for i in range(26):
            vk = 65 + i
            self.assertIn(vk, _VK_NAMES)
            self.assertEqual(_VK_NAMES[vk], chr(65 + i))
    
    def test_numbers_complete(self):
        """Test that all 0-9 keys are mapped."""
        for i in range(10):
            vk = 48 + i
            self.assertIn(vk, _VK_NAMES)
            self.assertEqual(_VK_NAMES[vk], str(i))
    
    def test_numpad_complete(self):
        """Test that all numpad 0-9 keys are mapped."""
        for i in range(10):
            vk = 96 + i
            self.assertIn(vk, _VK_NAMES)
            self.assertEqual(_VK_NAMES[vk], f"Num{i}")
    
    def test_mouse_buttons_mapped(self):
        """Test that mouse buttons are mapped."""
        self.assertIn(1, _VK_NAMES)  # LMB
        self.assertIn(2, _VK_NAMES)  # RMB
        self.assertIn(4, _VK_NAMES)  # MMB
        self.assertIn(5, _VK_NAMES)  # Mouse4
        self.assertIn(6, _VK_NAMES)  # Mouse5
    
    def test_common_keys_mapped(self):
        """Test that common special keys are mapped."""
        self.assertIn(32, _VK_NAMES)  # Space
        self.assertIn(13, _VK_NAMES)  # Enter
        self.assertIn(27, _VK_NAMES)  # Escape
        self.assertIn(20, _VK_NAMES)  # CapsLock
        self.assertIn(9, _VK_NAMES)   # Tab
        self.assertIn(8, _VK_NAMES)   # Backspace


if __name__ == "__main__":
    unittest.main()

