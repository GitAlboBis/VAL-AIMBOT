"""
Unit tests for gui/app.py SharedState integration.

Tests verify that:
1. run() accepts shared_state parameter
2. Global _shared_state is set correctly
3. Initial config is loaded into shared state
4. Page functions accept shared_state parameter
"""

import unittest
import sys
import os
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.shared_state import SharedState


class TestAppSharedStateIntegration(unittest.TestCase):
    """Test SharedState integration in gui/app.py."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.shared_state = SharedState()
    
    @patch('gui.app._run_imgui_bundle')
    @patch('gui.app._init_tabs')
    @patch('config.load_config')
    def test_run_accepts_shared_state_parameter(self, mock_load_config, mock_init_tabs, mock_run):
        """Test that run() accepts shared_state parameter."""
        from gui import app
        
        # Mock config loading
        mock_load_config.return_value = {
            'ai_engine': {'confidence': 0.5},
            'aim': {'speed': 0.7}
        }
        
        # Call run with shared_state
        app.run(shared_state=self.shared_state)
        
        # Verify global _shared_state was set
        self.assertIsNotNone(app._shared_state)
        self.assertEqual(app._shared_state, self.shared_state)
    
    @patch('gui.app._run_imgui_bundle')
    @patch('gui.app._init_tabs')
    @patch('config.load_config')
    def test_run_loads_config_into_shared_state(self, mock_load_config, mock_init_tabs, mock_run):
        """Test that run() loads initial config into shared state."""
        from gui import app
        
        # Mock config with nested structure
        test_config = {
            'ai_engine': {
                'confidence': 0.55,
                'iou_threshold': 0.45
            },
            'aim': {
                'speed': 0.7,
                'smoothing_factor': 0.8
            },
            'input': {
                'driver': 'ib'
            }
        }
        mock_load_config.return_value = test_config
        
        # Call run with shared_state
        app.run(shared_state=self.shared_state)
        
        # Verify config was loaded into shared state
        loaded_config = self.shared_state.get_config()
        
        # Check that all sections and keys were loaded
        self.assertIn('ai_engine', loaded_config)
        self.assertEqual(loaded_config['ai_engine']['confidence'], 0.55)
        self.assertEqual(loaded_config['ai_engine']['iou_threshold'], 0.45)
        
        self.assertIn('aim', loaded_config)
        self.assertEqual(loaded_config['aim']['speed'], 0.7)
        self.assertEqual(loaded_config['aim']['smoothing_factor'], 0.8)
        
        self.assertIn('input', loaded_config)
        self.assertEqual(loaded_config['input']['driver'], 'ib')
    
    @patch('gui.app._run_imgui_bundle')
    @patch('gui.app._init_tabs')
    @patch('config.load_config')
    def test_run_handles_none_shared_state(self, mock_load_config, mock_init_tabs, mock_run):
        """Test that run() handles None shared_state gracefully."""
        from gui import app
        
        mock_load_config.return_value = {}
        
        # Call run without shared_state (legacy mode)
        app.run(shared_state=None)
        
        # Verify it doesn't crash and _shared_state is None
        self.assertIsNone(app._shared_state)
    
    @patch('gui.app._run_imgui_bundle')
    @patch('gui.app._init_tabs')
    @patch('config.load_config')
    def test_run_supports_legacy_shared_config(self, mock_load_config, mock_init_tabs, mock_run):
        """Test that run() still supports legacy shared_config parameter."""
        from gui import app
        
        mock_load_config.return_value = {}
        legacy_config = {'aim': {'speed': 0.5}}
        
        # Call run with legacy shared_config
        app.run(shared_config=legacy_config)
        
        # Verify legacy config is stored
        self.assertEqual(app._config, legacy_config)
    
    def test_page_functions_accept_shared_state(self):
        """Test that all page functions accept shared_state parameter."""
        from gui import app
        
        # Mock imgui functions to prevent actual rendering
        with patch('gui.app.imgui'), \
             patch('gui.app.styled_child_panel'), \
             patch('gui.app.end_child_panel'), \
             patch('gui.app.gradient_slider_int', return_value=(False, 0)), \
             patch('gui.app.gradient_slider_float', return_value=(False, 0.0)), \
             patch('gui.app.styled_checkbox', return_value=(False, False)), \
             patch('gui.app.styled_button', return_value=False):
            
            cfg = {}
            w, h = 400, 300
            
            # Test each page function accepts shared_state parameter
            try:
                app._page_aim_assistance(cfg, w, h, self.shared_state)
                app._page_close_aim(cfg, w, h, self.shared_state)
                app._page_weapon_config(cfg, w, h, self.shared_state)
                app._page_visuals_players(cfg, w, h, self.shared_state)
                app._page_visuals_radar(cfg, w, h, self.shared_state)
                app._page_visuals_world(cfg, w, h, self.shared_state)
                app._page_misc(cfg, w, h, self.shared_state)
                app._page_exploits(cfg, w, h, self.shared_state)
            except TypeError as e:
                self.fail(f"Page function doesn't accept shared_state parameter: {e}")
    
    @patch('gui.app._run_imgui_bundle')
    @patch('gui.app._init_tabs')
    @patch('config.load_config')
    def test_config_loading_skips_non_dict_values(self, mock_load_config, mock_init_tabs, mock_run):
        """Test that config loading skips non-dict top-level values."""
        from gui import app
        
        # Config with mixed types at top level
        test_config = {
            'ai_engine': {
                'confidence': 0.55
            },
            'primary_engine': 'ai',  # String value, not dict
            'mode': 'aimbot',  # String value, not dict
            'aim': {
                'speed': 0.7
            }
        }
        mock_load_config.return_value = test_config
        
        # Call run with shared_state
        app.run(shared_state=self.shared_state)
        
        # Verify only dict sections were loaded
        loaded_config = self.shared_state.get_config()
        
        self.assertIn('ai_engine', loaded_config)
        self.assertIn('aim', loaded_config)
        # Non-dict values should be skipped
        self.assertNotIn('primary_engine', loaded_config)
        self.assertNotIn('mode', loaded_config)


if __name__ == '__main__':
    unittest.main()
