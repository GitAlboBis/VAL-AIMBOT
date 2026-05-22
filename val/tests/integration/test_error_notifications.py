"""
Unit tests for error notification functionality.

Tests the integration of ErrorHandler with the notification system,
including color-coded notifications, error log persistence, and
error display panel functionality.
"""

import unittest
import os
import time
import tempfile
from unittest.mock import Mock, patch, MagicMock

from gui.error_handler import ErrorHandler, ERROR_LOG_FILE
from gui.shared_state import SharedState


class TestErrorNotifications(unittest.TestCase):
    """Test error notification functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.shared_state = SharedState()
        
        # Use a unique test log file to avoid conflicts
        self.test_log_file = f"test_errors_{int(time.time() * 1000)}.log"
        
        # Patch ERROR_LOG_FILE for tests
        self.patcher = patch('gui.error_handler.ERROR_LOG_FILE', self.test_log_file)
        self.patcher.start()
        
        # Now create error handler with patched log file
        self.error_handler = ErrorHandler(self.shared_state)
    
    def tearDown(self):
        """Clean up after tests."""
        # Stop the patcher
        self.patcher.stop()
        
        # Clean up test log file
        if os.path.exists(self.test_log_file):
            try:
                os.remove(self.test_log_file)
            except PermissionError:
                pass  # File might still be open, ignore
    
    def test_engine_error_creates_notification(self):
        """Test that engine errors trigger notifications."""
        with patch('gui.error_handler.notifications') as mock_notifications:
            # Trigger an engine error
            test_error = ValueError("Test error message")
            self.error_handler.handle_engine_error("Test Engine", test_error)
            
            # Verify notification was added with red color
            mock_notifications.add.assert_called_once()
            call_args = mock_notifications.add.call_args
            self.assertIn("Test Engine error", call_args[0][0])
            self.assertEqual(call_args[1]['color'], (1.0, 0.3, 0.3, 1.0))  # Red
    
    def test_config_error_creates_warning_notification(self):
        """Test that config errors trigger warning notifications."""
        with patch('gui.error_handler.notifications') as mock_notifications:
            # Trigger a config error
            test_error = TypeError("Invalid type")
            self.error_handler.handle_config_error("test_key", "invalid_value", test_error)
            
            # Verify notification was added with orange color
            mock_notifications.add.assert_called_once()
            call_args = mock_notifications.add.call_args
            self.assertIn("Invalid config", call_args[0][0])
            self.assertEqual(call_args[1]['color'], (1.0, 0.5, 0.3, 1.0))  # Orange
    
    def test_validation_clamp_creates_yellow_notification(self):
        """Test that value clamping triggers yellow warning notifications."""
        with patch('gui.error_handler.notifications') as mock_notifications:
            # Try to set confidence to invalid value (> 1.0)
            result = self.error_handler.validate_config_value('ai_engine', 'confidence', 1.5)
            
            # Verify value was clamped
            self.assertEqual(result, 1.0)
            
            # Verify notification was added with yellow color
            mock_notifications.add.assert_called_once()
            call_args = mock_notifications.add.call_args
            self.assertIn("clamped", call_args[0][0])
            self.assertEqual(call_args[1]['color'], (1.0, 0.8, 0.3, 1.0))  # Yellow
    
    def test_error_log_persistence_delegated_to_logging(self):
        """ErrorHandler no longer writes the log file directly (R2.3, R2.4).

        File persistence is owned by ``main.setup_logging`` via the single
        ``logging.FileHandler``; ``ErrorHandler.handle_engine_error`` emits
        through the standard logger and MUST NOT open the log file itself.
        """
        with self.assertLogs('gui.error_handler', level='ERROR') as log_ctx:
            test_error = RuntimeError("Test runtime error")
            self.error_handler.handle_engine_error("AI Engine", test_error)

        joined = "\n".join(log_ctx.output)
        self.assertIn("ERROR", joined)
        self.assertIn("AI Engine", joined)
        self.assertIn("Test runtime error", joined)
        # ErrorHandler must not own the file; setup_logging does.
        self.assertFalse(os.path.exists(self.test_log_file))

    def test_config_error_delegated_to_logging(self):
        """Config errors flow through the standard logger, not raw file I/O."""
        with self.assertLogs('gui.error_handler', level='WARNING') as log_ctx:
            test_error = ValueError("Invalid value")
            self.error_handler.handle_config_error("test_param", 999, test_error)

        joined = "\n".join(log_ctx.output)
        self.assertIn("WARNING", joined)
        self.assertIn("Config", joined)
        self.assertIn("test_param", joined)
        self.assertFalse(os.path.exists(self.test_log_file))

    def test_validation_clamp_delegated_to_logging(self):
        """Clamp notices flow through the standard logger, not raw file I/O."""
        with self.assertLogs('gui.error_handler', level='INFO') as log_ctx:
            result = self.error_handler.validate_config_value('aim', 'speed', 5.0)

        self.assertEqual(result, 2.0)  # Max value for aim.speed
        joined = "\n".join(log_ctx.output)
        self.assertIn("INFO", joined)
        self.assertIn("clamped", joined)
        self.assertIn("aim.speed", joined)
        self.assertFalse(os.path.exists(self.test_log_file))
    
    def test_error_log_added_to_shared_state(self):
        """Test that errors are added to shared state for GUI display."""
        # Trigger an engine error
        test_error = Exception("Test exception")
        self.error_handler.handle_engine_error("HSV Engine", test_error)
        
        # Verify error was added to shared state
        engine_errors = self.shared_state.get_state('engine_errors', [])
        self.assertEqual(len(engine_errors), 1)
        self.assertEqual(engine_errors[0]['engine'], 'HSV Engine')
        self.assertIn('Test exception', engine_errors[0]['message'])
        
        # Verify last_error was set
        last_error = self.shared_state.get_state('last_error', '')
        self.assertIn('HSV Engine', last_error)
        self.assertIn('Test exception', last_error)
    
    def test_get_recent_errors(self):
        """Test retrieving recent errors from error log."""
        # Add multiple errors
        for i in range(5):
            error = ValueError(f"Error {i}")
            self.error_handler.handle_engine_error(f"Engine {i}", error)
        
        # Get recent errors
        recent = self.error_handler.get_recent_errors(3)
        
        # Verify we got 3 most recent errors in reverse order
        self.assertEqual(len(recent), 3)
        self.assertIn("Engine 4", recent[0]['engine'])  # Most recent first
        self.assertIn("Engine 3", recent[1]['engine'])
        self.assertIn("Engine 2", recent[2]['engine'])
    
    def test_clear_error_log_file_removed(self):
        """`clear_error_log_file` is removed per R2.4 / Task 3.2.

        ``ErrorHandler`` must not own file-write responsibility for the log
        path; the sole ``FileHandler`` lives in ``main.setup_logging``.
        """
        self.assertFalse(
            hasattr(self.error_handler, 'clear_error_log_file'),
            "ErrorHandler must not expose clear_error_log_file "
            "(raw file I/O violates Single_Writer_Invariant, R2.4)."
        )
    
    def test_get_error_log_path(self):
        """Test getting the error log file path."""
        path = self.error_handler.get_error_log_path()
        
        # Verify path is absolute and points to the test log file
        self.assertTrue(os.path.isabs(path))
        self.assertTrue(path.endswith(self.test_log_file))
    
    def test_error_log_max_size(self):
        """Test that error log is trimmed when it exceeds max size."""
        # Add more errors than max log size
        for i in range(150):
            error = ValueError(f"Error {i}")
            self.error_handler.handle_engine_error(f"Engine {i}", error)
        
        # Verify log was trimmed to max size
        self.assertEqual(len(self.error_handler.error_log), 100)
        
        # Verify oldest errors were removed (should start from error 50)
        self.assertIn("Engine 50", self.error_handler.error_log[0]['engine'])
        self.assertIn("Engine 149", self.error_handler.error_log[-1]['engine'])
    
    def test_validation_with_invalid_type(self):
        """Test validation with invalid type returns default value."""
        with patch('gui.error_handler.notifications') as mock_notifications:
            # Try to set confidence to invalid type
            result = self.error_handler.validate_config_value('ai_engine', 'confidence', 'invalid')
            
            # Verify default value was returned
            self.assertEqual(result, 0.55)  # Default for ai_engine.confidence
            
            # Verify error notification was shown
            mock_notifications.add.assert_called()
            call_args = mock_notifications.add.call_args
            self.assertIn("Invalid config", call_args[0][0])
    
    def test_validation_with_no_rule(self):
        """Test validation with no rule returns value unchanged."""
        # Try to validate a parameter with no validation rule
        result = self.error_handler.validate_config_value('unknown', 'param', 'any_value')
        
        # Verify value was returned unchanged
        self.assertEqual(result, 'any_value')
    
    def test_multiple_errors_in_shared_state(self):
        """Test that multiple errors are tracked in shared state."""
        # Add multiple errors
        for i in range(15):
            error = Exception(f"Error {i}")
            self.error_handler.handle_engine_error(f"Engine {i}", error)
        
        # Verify only last 10 errors are in shared state
        engine_errors = self.shared_state.get_state('engine_errors', [])
        self.assertEqual(len(engine_errors), 10)
        
        # Verify they are the most recent errors
        self.assertIn("Engine 5", engine_errors[0]['engine'])
        self.assertIn("Engine 14", engine_errors[-1]['engine'])


if __name__ == '__main__':
    unittest.main()
