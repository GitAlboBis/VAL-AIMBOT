"""
Pytest configuration and common fixtures for the test suite.

This module provides shared fixtures and configuration for all tests.
"""

import pytest
import sys
import os
from typing import Dict, Any

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def mock_config() -> Dict[str, Any]:
    """Provide a mock configuration dictionary for testing.
    
    Returns:
        Dict containing test configuration with all major sections
        and commonly used values for testing.
    """
    return {
        'ai_engine': {
            'enabled': True,
            'confidence': 0.55,
            'model_path': 'models/test_model.onnx',
            'capture_size': 320
        },
        'hsv_engine': {
            'enabled': False,
            'hue_min': 0,
            'hue_max': 10,
            'sat_min': 100,
            'sat_max': 255,
            'val_min': 100,
            'val_max': 255
        },
        'aim': {
            'enabled': True,
            'speed': 0.70,
            'smoothing_factor': 0.80,
            'fov_x': 90.0,
            'fov_y': 60.0
        },
        'target_tracker': {
            'enabled': True,
            'max_distance': 100.0,
            'prediction_time': 0.1
        },
        'memory_esp': {
            'enabled': False,
            'process_name': 'test_process.exe'
        },
        'general': {
            'debug_mode': False,
            'log_level': 'INFO',
            'log_file': 'test_errors.log'
        },
        'capture': {
            'backend': 'mss',
            'region_x': 0,
            'region_y': 0,
            'region_width': 1920,
            'region_height': 1080
        }
    }


@pytest.fixture
def mock_shared_state():
    """Provide a SharedState instance for testing.
    
    Returns:
        SharedState instance initialized with test configuration.
        Does not require ErrorHandler dependency for basic testing.
    """
    from gui.shared_state import SharedState
    
    # Create SharedState without ErrorHandler for testing
    shared_state = SharedState(error_handler=None)
    
    # Initialize with some test state
    shared_state.update_state('fps', 60.0)
    shared_state.update_state('ai_inference_time', 8.5)
    shared_state.update_state('engine_loop_time', 3.2)
    shared_state.update_state('ai_engine_enabled', True)
    shared_state.update_state('hsv_engine_enabled', False)
    shared_state.update_state('target_count', 0)
    
    return shared_state


@pytest.fixture
def mock_error_handler():
    """Provide a mock ErrorHandler instance for testing.
    
    Returns:
        Mock ErrorHandler that can be used in tests without
        requiring full error handling infrastructure.
    """
    from unittest.mock import Mock
    
    error_handler = Mock()
    error_handler.validate_config_value = Mock(return_value=True)
    error_handler.log_exception = Mock()
    error_handler.should_auto_disable = Mock(return_value=False)
    error_handler.reset_error_count = Mock()
    
    return error_handler


@pytest.fixture
def temp_config_file(tmp_path, mock_config):
    """Create a temporary config.yaml file for testing.
    
    Args:
        tmp_path: Pytest temporary directory fixture
        mock_config: Mock configuration dictionary
        
    Returns:
        Path to temporary config.yaml file
    """
    import yaml
    
    config_file = tmp_path / "config.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(mock_config, f)
    
    return config_file


@pytest.fixture(autouse=True)
def cleanup_logs():
    """Automatically clean up test log files after each test."""
    yield
    
    # Clean up any test log files
    test_log_files = ['test_errors.log', 'errors.log']
    for log_file in test_log_files:
        if os.path.exists(log_file):
            try:
                os.remove(log_file)
            except OSError:
                pass  # Ignore if file is locked or doesn't exist