"""
Integration tests for main.py entry point.

Tests the main application initialization sequence:
- SharedState initialization
- ErrorHandler initialization
- EngineCoordinator initialization
- Config loading and saving
- Graceful shutdown
"""

import unittest
import sys
import os
import time
import threading
from unittest.mock import Mock, patch, MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from gui.shared_state import SharedState
from gui.error_handler import ErrorHandler
from gui.config_manager import load_config_into_shared_state, save_live_config_auto


class TestMainEntryPoint(unittest.TestCase):
    """Test main application entry point initialization."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.shared_state = None
        self.error_handler = None
        self.engine_coordinator = None
    
    def tearDown(self):
        """Clean up after tests."""
        if self.engine_coordinator:
            try:
                self.engine_coordinator.stop()
            except Exception:
                pass
    
    def test_shared_state_initialization(self):
        """Test SharedState initializes correctly."""
        shared_state = SharedState()
        
        # Verify initial state
        self.assertIsNotNone(shared_state)
        self.assertEqual(shared_state.get_config(), {})
        self.assertEqual(shared_state.get_all_state(), {})
    
    def test_error_handler_initialization(self):
        """Test ErrorHandler initializes with SharedState."""
        shared_state = SharedState()
        error_handler = ErrorHandler(shared_state)
        
        # Verify error handler is initialized
        self.assertIsNotNone(error_handler)
        self.assertEqual(error_handler.shared_state, shared_state)
        
        # Test validation
        validated = error_handler.validate_config_value('ai_engine', 'confidence', 1.5)
        self.assertEqual(validated, 1.0)  # Should clamp to max
    
    def test_config_loading_into_shared_state(self):
        """Test config loads from YAML into SharedState."""
        shared_state = SharedState()
        
        # Load config
        success = load_config_into_shared_state(shared_state)
        
        # Verify config was loaded
        self.assertTrue(success)
        
        config = shared_state.get_config()
        self.assertIsNotNone(config)
        self.assertIn('capture', config)
        self.assertIn('ai_engine', config)
        self.assertIn('aim', config)
    
    def test_engine_coordinator_initialization(self):
        """Test EngineCoordinator initializes with SharedState."""
        from engines.coordinator import EngineCoordinator
        
        shared_state = SharedState()
        load_config_into_shared_state(shared_state)
        
        # Initialize coordinator
        engine_coordinator = EngineCoordinator(shared_state)
        self.engine_coordinator = engine_coordinator
        
        # Verify coordinator is initialized
        self.assertIsNotNone(engine_coordinator)
        self.assertEqual(engine_coordinator.shared_state, shared_state)
        self.assertFalse(engine_coordinator._running)
    
    def test_engine_coordinator_start_stop(self):
        """Test EngineCoordinator starts and stops correctly."""
        from engines.coordinator import EngineCoordinator
        
        shared_state = SharedState()
        load_config_into_shared_state(shared_state)
        
        # Initialize and start coordinator
        engine_coordinator = EngineCoordinator(shared_state)
        self.engine_coordinator = engine_coordinator
        
        engine_coordinator.start()
        
        # Verify coordinator is running
        self.assertTrue(engine_coordinator._running)
        self.assertIsNotNone(engine_coordinator._thread)
        self.assertTrue(engine_coordinator._thread.is_alive())
        
        # Wait a bit for thread to start
        time.sleep(0.1)
        
        # Stop coordinator
        engine_coordinator.stop()
        
        # Verify coordinator stopped
        self.assertFalse(engine_coordinator._running)
        
        # Wait for thread to exit
        time.sleep(0.5)
        
        if engine_coordinator._thread:
            self.assertFalse(engine_coordinator._thread.is_alive())
    
    def test_config_save_on_exit(self):
        """Test config saves correctly on exit."""
        shared_state = SharedState()
        load_config_into_shared_state(shared_state)
        
        # Modify a config value
        shared_state.update_config('ai_engine', 'confidence', 0.75)
        
        # Save config
        success = save_live_config_auto(shared_state)
        
        # Verify save succeeded
        self.assertTrue(success)
        
        # Load config again and verify change persisted
        new_shared_state = SharedState()
        load_config_into_shared_state(new_shared_state)
        
        config = new_shared_state.get_config()
        self.assertEqual(config['ai_engine']['confidence'], 0.75)
    
    def test_graceful_shutdown_sequence(self):
        """Test graceful shutdown stops engines and saves config."""
        from engines.coordinator import EngineCoordinator
        
        shared_state = SharedState()
        load_config_into_shared_state(shared_state)
        
        # Initialize and start coordinator
        engine_coordinator = EngineCoordinator(shared_state)
        self.engine_coordinator = engine_coordinator
        engine_coordinator.start()
        
        # Wait for thread to start
        time.sleep(0.1)
        
        # Verify running
        self.assertTrue(engine_coordinator._running)
        
        # Simulate graceful shutdown
        engine_coordinator.stop()
        
        # Verify stopped
        self.assertFalse(engine_coordinator._running)
        
        # Save config
        success = save_live_config_auto(shared_state)
        self.assertTrue(success)
    
    def test_error_handler_integration(self):
        """Test ErrorHandler integrates with SharedState."""
        shared_state = SharedState()
        error_handler = ErrorHandler(shared_state)
        shared_state.set_error_handler(error_handler)
        
        # Test validation through shared state
        shared_state.update_config('ai_engine', 'confidence', 2.0)
        
        # Value should be clamped to 1.0
        config = shared_state.get_config()
        self.assertEqual(config['ai_engine']['confidence'], 1.0)
    
    def test_config_modified_flag(self):
        """Test config modified flag is set and cleared correctly."""
        shared_state = SharedState()
        
        # Initially not modified
        self.assertFalse(shared_state.check_and_clear_modified())
        
        # Update config
        shared_state.update_config('ai_engine', 'confidence', 0.6)
        
        # Should be modified
        self.assertTrue(shared_state.check_and_clear_modified())
        
        # Should be cleared after check
        self.assertFalse(shared_state.check_and_clear_modified())
    
    def test_state_updates(self):
        """Test state updates work correctly."""
        shared_state = SharedState()
        
        # Update state
        shared_state.update_state('fps', 144.5)
        shared_state.update_state('ai_inference_ms', 3.2)
        
        # Read state
        self.assertEqual(shared_state.get_state('fps'), 144.5)
        self.assertEqual(shared_state.get_state('ai_inference_ms'), 3.2)
        self.assertEqual(shared_state.get_state('nonexistent', 'default'), 'default')


class TestMainIntegration(unittest.TestCase):
    """Test full main() integration (mocked)."""
    
    @patch('engines.coordinator.EngineCoordinator')
    @patch('gui.app.run')
    @patch('gui.config_manager.save_live_config_auto')
    @patch('gui.config_manager.load_config_into_shared_state')
    def test_gui_mode_initialization(self, mock_load_config, mock_save_config, 
                                     mock_gui_run, mock_coordinator_class):
        """Test GUI mode initializes all components correctly."""
        # Mock coordinator
        mock_coordinator = Mock()
        mock_coordinator_class.return_value = mock_coordinator
        
        # Mock config functions
        mock_load_config.return_value = True
        mock_save_config.return_value = True
        
        # Mock GUI run to exit immediately
        mock_gui_run.return_value = None
        
        # Import main after patching
        import main as main_module
        
        # Mock sys.argv to enable GUI mode
        with patch.object(sys, 'argv', ['main.py', '--gui']):
            # Run main (should exit cleanly)
            try:
                main_module.main()
            except SystemExit:
                pass  # Expected on normal exit
        
        # Verify coordinator was started and stopped
        mock_coordinator.start.assert_called_once()
        mock_coordinator.stop.assert_called_once()
        
        # Verify GUI was launched
        mock_gui_run.assert_called_once()
        
        # Verify config was saved on exit
        mock_save_config.assert_called()


def run_tests():
    """Run all tests."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestMainEntryPoint))
    suite.addTests(loader.loadTestsFromTestCase(TestMainIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Return exit code
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run_tests())
