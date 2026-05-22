"""
Integration test for gui/app.py SharedState flow.

This test demonstrates the complete flow:
1. Create SharedState instance
2. Pass it to gui.app.run()
3. Verify config is loaded from config.yaml
4. Verify shared_state is accessible in callbacks
"""

import unittest
import sys
import os
from unittest.mock import patch, MagicMock
import yaml

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.shared_state import SharedState


class TestAppIntegration(unittest.TestCase):
    """Integration test for SharedState flow in gui/app.py."""
    
    @patch('gui.app._run_imgui_bundle')
    @patch('gui.app._init_tabs')
    def test_full_integration_flow(self, mock_init_tabs, mock_run):
        """Test complete integration flow from startup to config loading."""
        from gui import app
        
        # Create a SharedState instance (simulating main.py)
        shared_state = SharedState()
        
        # Verify shared state is empty initially
        initial_config = shared_state.get_config()
        self.assertEqual(initial_config, {})
        
        # Call run() with shared_state (simulating main.py startup)
        app.run(shared_state=shared_state)
        
        # Verify config was loaded into shared state
        loaded_config = shared_state.get_config()
        
        # Config should now contain sections from config.yaml
        self.assertIsInstance(loaded_config, dict)
        self.assertGreater(len(loaded_config), 0, "Config should be loaded from config.yaml")
        
        # Verify typical sections exist (based on config.yaml structure)
        # Note: This test uses the actual config.yaml file
        if 'ai_engine' in loaded_config:
            self.assertIn('confidence', loaded_config['ai_engine'])
        
        if 'aim' in loaded_config:
            self.assertIn('speed', loaded_config['aim'])
        
        # Verify global _shared_state was set
        self.assertIsNotNone(app._shared_state)
        self.assertEqual(app._shared_state, shared_state)
    
    @patch('gui.app._run_imgui_bundle')
    @patch('gui.app._init_tabs')
    def test_bidirectional_data_flow(self, mock_init_tabs, mock_run):
        """Test bidirectional data flow: GUI → Engine and Engine → GUI."""
        from gui import app
        
        shared_state = SharedState()
        
        # Simulate GUI startup
        app.run(shared_state=shared_state)
        
        # Simulate GUI updating config (GUI → Engine)
        shared_state.update_config('ai_engine', 'confidence', 0.75)
        shared_state.update_config('aim', 'speed', 0.85)
        
        # Verify config updates are stored
        config = shared_state.get_config()
        self.assertEqual(config['ai_engine']['confidence'], 0.75)
        self.assertEqual(config['aim']['speed'], 0.85)
        
        # Verify modified flag is set
        self.assertTrue(shared_state.check_and_clear_modified())
        
        # Simulate engine updating state (Engine → GUI)
        shared_state.update_state('fps', 144.5)
        shared_state.update_state('ai_inference_ms', 3.2)
        shared_state.update_state('aim_state', 'track')
        
        # Verify state updates are readable
        self.assertEqual(shared_state.get_state('fps'), 144.5)
        self.assertEqual(shared_state.get_state('ai_inference_ms'), 3.2)
        self.assertEqual(shared_state.get_state('aim_state'), 'track')
    
    @patch('gui.app._run_imgui_bundle')
    @patch('gui.app._init_tabs')
    def test_legacy_compatibility(self, mock_init_tabs, mock_run):
        """Test that legacy shared_config parameter still works."""
        from gui import app
        
        legacy_config = {
            'aim': {'speed': 0.6},
            'ai_engine': {'confidence': 0.5}
        }
        
        # Call with legacy parameter
        app.run(shared_config=legacy_config)
        
        # Verify legacy config is stored
        self.assertEqual(app._config, legacy_config)
        
        # Verify _shared_state is None (legacy mode)
        self.assertIsNone(app._shared_state)
    
    @patch('gui.app._run_imgui_bundle')
    @patch('gui.app._init_tabs')
    def test_both_parameters_provided(self, mock_init_tabs, mock_run):
        """Test behavior when both shared_state and shared_config are provided."""
        from gui import app
        
        shared_state = SharedState()
        legacy_config = {'aim': {'speed': 0.6}}
        
        # Call with both parameters
        app.run(shared_state=shared_state, shared_config=legacy_config)
        
        # Verify both are set
        self.assertIsNotNone(app._shared_state)
        self.assertEqual(app._shared_state, shared_state)
        self.assertEqual(app._config, legacy_config)
        
        # Verify config was loaded into shared_state
        loaded_config = shared_state.get_config()
        self.assertGreater(len(loaded_config), 0)


if __name__ == '__main__':
    unittest.main()
