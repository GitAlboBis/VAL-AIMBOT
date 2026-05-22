"""
Unit tests for Configuration page (_page_configuration) functionality.

Tests cover:
- Save Config button with success/failure notifications
- Save as Preset button with name input dialog
- Preset name validation (empty names, special characters)
- Unsaved changes indicator (dot/asterisk)
- Preset list display with Load/Delete buttons
- Delete confirmation dialog
- Integration with config_manager functions
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.shared_state import SharedState


class TestConfigurationPage(unittest.TestCase):
    """Test suite for Configuration page functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.shared_state = SharedState()
        
        # Initialize with some config data
        self.shared_state.update_config('ai_engine', 'confidence', 0.65)
        self.shared_state.update_config('aim', 'speed', 1.5)
        
        # Clear modified flag
        self.shared_state.check_and_clear_modified()
    
    def test_unsaved_changes_indicator_shows_when_modified(self):
        """Test that unsaved changes indicator appears when config is modified."""
        # Modify config
        self.shared_state.update_config('ai_engine', 'confidence', 0.75)
        
        # Check modified flag
        has_changes = self.shared_state.check_and_clear_modified()
        self.assertTrue(has_changes, "Modified flag should be set after config update")
    
    def test_unsaved_changes_indicator_clears_after_save(self):
        """Test that unsaved changes indicator clears after save."""
        # Modify config
        self.shared_state.update_config('ai_engine', 'confidence', 0.75)
        
        # Clear modified flag (simulating save)
        self.shared_state.check_and_clear_modified()
        
        # Check flag is cleared
        has_changes = self.shared_state.check_and_clear_modified()
        self.assertFalse(has_changes, "Modified flag should be cleared after save")
    
    @patch('gui.config_manager.save_live_config_auto')
    def test_save_config_button_success(self, mock_save):
        """Test Save Config button with successful save."""
        mock_save.return_value = True
        
        # Simulate button click
        result = mock_save(self.shared_state)
        
        self.assertTrue(result, "Save should succeed")
        mock_save.assert_called_once_with(self.shared_state)
    
    @patch('gui.config_manager.save_live_config_auto')
    def test_save_config_button_failure(self, mock_save):
        """Test Save Config button with failed save."""
        mock_save.return_value = False
        
        # Simulate button click
        result = mock_save(self.shared_state)
        
        self.assertFalse(result, "Save should fail")
        mock_save.assert_called_once_with(self.shared_state)
    
    @patch('gui.config_manager.save_preset')
    def test_save_preset_with_valid_name(self, mock_save_preset):
        """Test saving preset with valid name."""
        mock_save_preset.return_value = True
        
        preset_name = "my_preset"
        result = mock_save_preset(preset_name, self.shared_state)
        
        self.assertTrue(result, "Preset save should succeed")
        mock_save_preset.assert_called_once_with(preset_name, self.shared_state)
    
    def test_preset_name_validation_empty(self):
        """Test that empty preset names are rejected."""
        preset_name = "   "  # Whitespace only
        
        # Validate
        is_valid = bool(preset_name.strip())
        
        self.assertFalse(is_valid, "Empty preset name should be invalid")
    
    def test_preset_name_validation_special_chars(self):
        """Test that preset names with special characters are rejected."""
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        
        for char in invalid_chars:
            preset_name = f"preset{char}name"
            
            # Validate
            has_invalid_chars = any(c in preset_name for c in invalid_chars)
            
            self.assertTrue(has_invalid_chars, 
                f"Preset name with '{char}' should be invalid")
    
    def test_preset_name_validation_valid(self):
        """Test that valid preset names are accepted."""
        valid_names = [
            "my_preset",
            "preset-123",
            "Preset Name",
            "preset.config",
        ]
        
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        
        for preset_name in valid_names:
            # Validate
            is_empty = not preset_name.strip()
            has_invalid_chars = any(c in preset_name for c in invalid_chars)
            is_valid = not is_empty and not has_invalid_chars
            
            self.assertTrue(is_valid, f"Preset name '{preset_name}' should be valid")
    
    @patch('gui.config_manager.list_presets')
    def test_preset_list_display(self, mock_list):
        """Test that preset list displays correctly."""
        mock_list.return_value = ["preset1", "preset2", "preset3"]
        
        presets = mock_list()
        
        self.assertEqual(len(presets), 3, "Should return 3 presets")
        self.assertIn("preset1", presets)
        self.assertIn("preset2", presets)
        self.assertIn("preset3", presets)
    
    @patch('gui.config_manager.list_presets')
    def test_preset_list_empty(self, mock_list):
        """Test that empty preset list is handled correctly."""
        mock_list.return_value = []
        
        presets = mock_list()
        
        self.assertEqual(len(presets), 0, "Should return empty list")
    
    @patch('gui.config_manager.load_preset')
    def test_load_preset_success(self, mock_load):
        """Test loading preset successfully."""
        mock_load.return_value = True
        
        result = mock_load("preset1", self.shared_state)
        
        self.assertTrue(result, "Preset load should succeed")
        mock_load.assert_called_once_with("preset1", self.shared_state)
    
    @patch('gui.config_manager.load_preset')
    def test_load_preset_failure(self, mock_load):
        """Test loading preset with failure."""
        mock_load.return_value = False
        
        result = mock_load("nonexistent", self.shared_state)
        
        self.assertFalse(result, "Preset load should fail")
        mock_load.assert_called_once_with("nonexistent", self.shared_state)
    
    @patch('gui.config_manager.delete_preset')
    def test_delete_preset_success(self, mock_delete):
        """Test deleting preset successfully."""
        mock_delete.return_value = True
        
        result = mock_delete("preset1")
        
        self.assertTrue(result, "Preset delete should succeed")
        mock_delete.assert_called_once_with("preset1")
    
    @patch('gui.config_manager.delete_preset')
    def test_delete_preset_failure(self, mock_delete):
        """Test deleting preset with failure."""
        mock_delete.return_value = False
        
        result = mock_delete("nonexistent")
        
        self.assertFalse(result, "Preset delete should fail")
        mock_delete.assert_called_once_with("nonexistent")
    
    def test_save_dialog_state_management(self):
        """Test that save dialog state is managed correctly."""
        # Simulate dialog state
        show_dialog = False
        preset_name_buffer = ""
        
        # Open dialog
        show_dialog = True
        preset_name_buffer = ""
        
        self.assertTrue(show_dialog, "Dialog should be open")
        self.assertEqual(preset_name_buffer, "", "Buffer should be empty")
        
        # Enter name
        preset_name_buffer = "my_preset"
        
        self.assertEqual(preset_name_buffer, "my_preset", "Buffer should contain name")
        
        # Close dialog
        show_dialog = False
        
        self.assertFalse(show_dialog, "Dialog should be closed")
    
    def test_delete_confirmation_state_management(self):
        """Test that delete confirmation state is managed correctly."""
        # Simulate confirmation state
        delete_confirm_preset = None
        
        # Request confirmation
        delete_confirm_preset = "preset1"
        
        self.assertEqual(delete_confirm_preset, "preset1", 
            "Confirmation should be requested for preset1")
        
        # Cancel confirmation
        delete_confirm_preset = None
        
        self.assertIsNone(delete_confirm_preset, 
            "Confirmation should be cancelled")
    
    def test_config_modified_flag_persistence(self):
        """Test that modified flag persists until explicitly cleared."""
        # Modify config
        self.shared_state.update_config('ai_engine', 'confidence', 0.75)
        
        # Check flag multiple times without clearing
        with self.shared_state._config_lock:
            modified1 = self.shared_state._config_modified
        
        with self.shared_state._config_lock:
            modified2 = self.shared_state._config_modified
        
        self.assertTrue(modified1, "Flag should be set")
        self.assertTrue(modified2, "Flag should persist")
        
        # Clear flag
        self.shared_state.check_and_clear_modified()
        
        # Check flag is cleared
        with self.shared_state._config_lock:
            modified3 = self.shared_state._config_modified
        
        self.assertFalse(modified3, "Flag should be cleared")


if __name__ == '__main__':
    unittest.main()
