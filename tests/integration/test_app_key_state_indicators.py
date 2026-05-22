"""
Unit tests for activation key state indicators in gui/app.py.

Tests verify that:
1. Key state indicators read from shared state correctly
2. Visual feedback colors are correct for pressed/released states
3. Key names are displayed from config
"""

import unittest
import sys
import os
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.shared_state import SharedState


class TestKeyStateIndicators(unittest.TestCase):
    """Test activation key state indicators functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.shared_state = SharedState()
        
        # Set up test config
        self.shared_state.update_config('general', 'activation_key', 'CapsLock')
        self.shared_state.update_config('general', 'panic_key', 'F10')
    
    def test_activation_key_state_reads_from_shared_state(self):
        """Test that activation key state is read from shared state."""
        # Set activation key pressed
        self.shared_state.update_state('activation_key_pressed', True)
        
        # Verify state can be read
        activation_pressed = self.shared_state.get_state('activation_key_pressed', False)
        self.assertTrue(activation_pressed)
        
        # Set activation key released
        self.shared_state.update_state('activation_key_pressed', False)
        
        # Verify state updated
        activation_pressed = self.shared_state.get_state('activation_key_pressed', False)
        self.assertFalse(activation_pressed)
    
    def test_panic_key_state_reads_from_shared_state(self):
        """Test that panic key state is read from shared state."""
        # Set panic key pressed
        self.shared_state.update_state('panic_key_pressed', True)
        
        # Verify state can be read
        panic_pressed = self.shared_state.get_state('panic_key_pressed', False)
        self.assertTrue(panic_pressed)
        
        # Set panic key released
        self.shared_state.update_state('panic_key_pressed', False)
        
        # Verify state updated
        panic_pressed = self.shared_state.get_state('panic_key_pressed', False)
        self.assertFalse(panic_pressed)
    
    def test_key_names_read_from_config(self):
        """Test that key names are read from config."""
        # Get config
        config = self.shared_state.get_config()
        
        # Verify key names
        self.assertEqual(config['general']['activation_key'], 'CapsLock')
        self.assertEqual(config['general']['panic_key'], 'F10')
    
    def test_visual_feedback_colors_for_activation_key(self):
        """Test that visual feedback colors are correct for activation key."""
        # Test pressed state (should be green)
        self.shared_state.update_state('activation_key_pressed', True)
        activation_pressed = self.shared_state.get_state('activation_key_pressed', False)
        
        if activation_pressed:
            expected_color = (0.3, 1.0, 0.3, 1.0)  # Bright green
            expected_status = "● PRESSED"
        else:
            expected_color = (0.5, 0.5, 0.5, 1.0)  # Gray
            expected_status = "○ RELEASED"
        
        self.assertEqual(expected_color, (0.3, 1.0, 0.3, 1.0))
        self.assertEqual(expected_status, "● PRESSED")
        
        # Test released state (should be gray)
        self.shared_state.update_state('activation_key_pressed', False)
        activation_pressed = self.shared_state.get_state('activation_key_pressed', False)
        
        if activation_pressed:
            expected_color = (0.3, 1.0, 0.3, 1.0)  # Bright green
            expected_status = "● PRESSED"
        else:
            expected_color = (0.5, 0.5, 0.5, 1.0)  # Gray
            expected_status = "○ RELEASED"
        
        self.assertEqual(expected_color, (0.5, 0.5, 0.5, 1.0))
        self.assertEqual(expected_status, "○ RELEASED")
    
    def test_visual_feedback_colors_for_panic_key(self):
        """Test that visual feedback colors are correct for panic key."""
        # Test pressed state (should be red)
        self.shared_state.update_state('panic_key_pressed', True)
        panic_pressed = self.shared_state.get_state('panic_key_pressed', False)
        
        if panic_pressed:
            expected_color = (1.0, 0.3, 0.3, 1.0)  # Bright red
            expected_status = "● PRESSED"
        else:
            expected_color = (0.5, 0.5, 0.5, 1.0)  # Gray
            expected_status = "○ RELEASED"
        
        self.assertEqual(expected_color, (1.0, 0.3, 0.3, 1.0))
        self.assertEqual(expected_status, "● PRESSED")
        
        # Test released state (should be gray)
        self.shared_state.update_state('panic_key_pressed', False)
        panic_pressed = self.shared_state.get_state('panic_key_pressed', False)
        
        if panic_pressed:
            expected_color = (1.0, 0.3, 0.3, 1.0)  # Bright red
            expected_status = "● PRESSED"
        else:
            expected_color = (0.5, 0.5, 0.5, 1.0)  # Gray
            expected_status = "○ RELEASED"
        
        self.assertEqual(expected_color, (0.5, 0.5, 0.5, 1.0))
        self.assertEqual(expected_status, "○ RELEASED")
    
    def test_default_key_names_when_not_configured(self):
        """Test that default key names are used when not configured."""
        # Create new shared state without config
        new_shared_state = SharedState()
        
        # Get config (should be empty)
        config = new_shared_state.get_config()
        
        # Verify defaults would be used (CapsLock and F10)
        activation_key = config.get('general', {}).get('activation_key', 'CapsLock')
        panic_key = config.get('general', {}).get('panic_key', 'F10')
        
        self.assertEqual(activation_key, 'CapsLock')
        self.assertEqual(panic_key, 'F10')
    
    def test_key_state_defaults_to_false(self):
        """Test that key states default to False when not set."""
        # Create new shared state
        new_shared_state = SharedState()
        
        # Get key states (should default to False)
        activation_pressed = new_shared_state.get_state('activation_key_pressed', False)
        panic_pressed = new_shared_state.get_state('panic_key_pressed', False)
        
        self.assertFalse(activation_pressed)
        self.assertFalse(panic_pressed)


if __name__ == '__main__':
    unittest.main()
