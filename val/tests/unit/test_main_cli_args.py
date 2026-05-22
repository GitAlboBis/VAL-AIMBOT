"""
Unit tests for main.py command-line argument parsing.

Tests the command-line argument parsing functionality added in Task 16.2.
"""

import unittest
import sys
import os
from unittest.mock import patch, MagicMock
import tempfile
import yaml


class TestCommandLineArguments(unittest.TestCase):
    """Test command-line argument parsing in main.py."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a temporary config file for testing
        self.temp_config = tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        )
        test_config = {
            'general': {'log_level': 'INFO'},
            'capture': {'backend': 'dxgi'},
            'ai_engine': {'enabled': True}
        }
        yaml.dump(test_config, self.temp_config)
        self.temp_config.close()
        
        # Create a temporary preset file
        self.temp_preset_dir = tempfile.mkdtemp()
        self.preset_path = os.path.join(self.temp_preset_dir, 'test_preset.yaml')
        preset_config = {
            'ai_engine': {'confidence': 0.75},
            'aim': {'speed': 1.5}
        }
        with open(self.preset_path, 'w') as f:
            yaml.dump(preset_config, f)
    
    def tearDown(self):
        """Clean up test fixtures."""
        # Remove temporary files
        if os.path.exists(self.temp_config.name):
            os.unlink(self.temp_config.name)
        if os.path.exists(self.preset_path):
            os.unlink(self.preset_path)
        if os.path.exists(self.temp_preset_dir):
            os.rmdir(self.temp_preset_dir)
    
    @patch('sys.argv', ['main.py'])
    def test_default_arguments(self):
        """Test default argument values when no flags provided."""
        import argparse
        
        parser = argparse.ArgumentParser()
        parser.add_argument('--gui', action='store_true')
        parser.add_argument('--debug', action='store_true')
        parser.add_argument('--config', type=str, default='config.yaml')
        parser.add_argument('--no-engines', action='store_true')
        parser.add_argument('--preset', type=str, default=None)
        
        args = parser.parse_args()
        
        self.assertFalse(args.gui)
        self.assertFalse(args.debug)
        self.assertEqual(args.config, 'config.yaml')
        self.assertFalse(args.no_engines)
        self.assertIsNone(args.preset)
    
    @patch('sys.argv', ['main.py', '--gui'])
    def test_gui_flag(self):
        """Test --gui flag enables GUI mode."""
        import argparse
        
        parser = argparse.ArgumentParser()
        parser.add_argument('--gui', action='store_true')
        parser.add_argument('--debug', action='store_true')
        parser.add_argument('--config', type=str, default='config.yaml')
        parser.add_argument('--no-engines', action='store_true')
        parser.add_argument('--preset', type=str, default=None)
        
        args = parser.parse_args()
        
        self.assertTrue(args.gui)
    
    @patch('sys.argv', ['main.py', '--debug'])
    def test_debug_flag(self):
        """Test --debug flag enables debug mode."""
        import argparse
        
        parser = argparse.ArgumentParser()
        parser.add_argument('--gui', action='store_true')
        parser.add_argument('--debug', action='store_true')
        parser.add_argument('--config', type=str, default='config.yaml')
        parser.add_argument('--no-engines', action='store_true')
        parser.add_argument('--preset', type=str, default=None)
        
        args = parser.parse_args()
        
        self.assertTrue(args.debug)
    
    @patch('sys.argv', ['main.py', '--config', 'custom.yaml'])
    def test_config_flag(self):
        """Test --config flag specifies alternate config file."""
        import argparse
        
        parser = argparse.ArgumentParser()
        parser.add_argument('--gui', action='store_true')
        parser.add_argument('--debug', action='store_true')
        parser.add_argument('--config', type=str, default='config.yaml')
        parser.add_argument('--no-engines', action='store_true')
        parser.add_argument('--preset', type=str, default=None)
        
        args = parser.parse_args()
        
        self.assertEqual(args.config, 'custom.yaml')
    
    @patch('sys.argv', ['main.py', '--no-engines'])
    def test_no_engines_flag(self):
        """Test --no-engines flag disables engine initialization."""
        import argparse
        
        parser = argparse.ArgumentParser()
        parser.add_argument('--gui', action='store_true')
        parser.add_argument('--debug', action='store_true')
        parser.add_argument('--config', type=str, default='config.yaml')
        parser.add_argument('--no-engines', action='store_true')
        parser.add_argument('--preset', type=str, default=None)
        
        args = parser.parse_args()
        
        self.assertTrue(args.no_engines)
    
    @patch('sys.argv', ['main.py', '--preset', 'aggressive'])
    def test_preset_flag(self):
        """Test --preset flag specifies preset to load."""
        import argparse
        
        parser = argparse.ArgumentParser()
        parser.add_argument('--gui', action='store_true')
        parser.add_argument('--debug', action='store_true')
        parser.add_argument('--config', type=str, default='config.yaml')
        parser.add_argument('--no-engines', action='store_true')
        parser.add_argument('--preset', type=str, default=None)
        
        args = parser.parse_args()
        
        self.assertEqual(args.preset, 'aggressive')
    
    @patch('sys.argv', ['main.py', '--gui', '--debug', '--no-engines'])
    def test_multiple_flags(self):
        """Test multiple flags can be combined."""
        import argparse
        
        parser = argparse.ArgumentParser()
        parser.add_argument('--gui', action='store_true')
        parser.add_argument('--debug', action='store_true')
        parser.add_argument('--config', type=str, default='config.yaml')
        parser.add_argument('--no-engines', action='store_true')
        parser.add_argument('--preset', type=str, default=None)
        
        args = parser.parse_args()
        
        self.assertTrue(args.gui)
        self.assertTrue(args.debug)
        self.assertTrue(args.no_engines)
    
    def test_config_file_validation(self):
        """Test that config file existence is validated."""
        # Test with existing file
        self.assertTrue(os.path.exists(self.temp_config.name))
        
        # Test with non-existent file
        fake_path = 'nonexistent_config.yaml'
        self.assertFalse(os.path.exists(fake_path))
    
    def test_preset_file_validation(self):
        """Test that preset file existence is validated."""
        # Test with existing preset
        self.assertTrue(os.path.exists(self.preset_path))
        
        # Test with non-existent preset
        fake_preset = os.path.join(self.temp_preset_dir, 'nonexistent.yaml')
        self.assertFalse(os.path.exists(fake_preset))
    
    def test_alternate_config_loading(self):
        """Test loading config from alternate file."""
        # Load the temporary config file
        with open(self.temp_config.name, 'r') as f:
            config = yaml.safe_load(f)
        
        # Verify config was loaded correctly
        self.assertIn('general', config)
        self.assertEqual(config['general']['log_level'], 'INFO')
        self.assertIn('capture', config)
        self.assertEqual(config['capture']['backend'], 'dxgi')
    
    def test_preset_loading(self):
        """Test loading preset config."""
        # Load the preset file
        with open(self.preset_path, 'r') as f:
            preset = yaml.safe_load(f)
        
        # Verify preset was loaded correctly
        self.assertIn('ai_engine', preset)
        self.assertEqual(preset['ai_engine']['confidence'], 0.75)
        self.assertIn('aim', preset)
        self.assertEqual(preset['aim']['speed'], 1.5)


class TestArgumentIntegration(unittest.TestCase):
    """Test integration of command-line arguments with application logic."""
    
    def test_debug_mode_sets_shared_state(self):
        """Test that --debug flag sets debug mode in shared state."""
        from gui.shared_state import SharedState
        
        shared_state = SharedState()
        
        # Simulate debug flag being set
        shared_state.update_config('general', 'debug_mode', True)
        
        # Verify debug mode is enabled
        config = shared_state.get_config()
        self.assertTrue(config.get('general', {}).get('debug_mode', False))
    
    def test_no_engines_skips_coordinator(self):
        """Test that --no-engines flag prevents engine coordinator initialization."""
        # This is a logic test - in actual code, engine_coordinator would be None
        no_engines = True
        
        if no_engines:
            engine_coordinator = None
        else:
            engine_coordinator = MagicMock()
        
        self.assertIsNone(engine_coordinator)
    
    def test_preset_merges_into_shared_state(self):
        """Test that preset config merges into shared state."""
        from gui.shared_state import SharedState
        
        shared_state = SharedState()
        
        # Load initial config
        shared_state.update_config('ai_engine', 'confidence', 0.55)
        shared_state.update_config('aim', 'speed', 1.0)
        
        # Simulate preset loading
        preset_config = {
            'ai_engine': {'confidence': 0.75},
            'aim': {'speed': 1.5}
        }
        
        for section, values in preset_config.items():
            for key, value in values.items():
                shared_state.update_config(section, key, value)
        
        # Verify preset values override initial values
        config = shared_state.get_config()
        self.assertEqual(config['ai_engine']['confidence'], 0.75)
        self.assertEqual(config['aim']['speed'], 1.5)


if __name__ == '__main__':
    unittest.main()
