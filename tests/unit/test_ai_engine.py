"""
Unit tests for AI Engine module.
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch

from engines.ai_engine import AIVisionEngine
from exceptions import AIEngineException, ValidationException


@pytest.mark.unit
class TestAIEngine:
    """Test cases for AI Engine functionality."""
    
    def test_ai_engine_initialization(self, mock_config):
        """Test AI engine initializes correctly."""
        config = mock_config['ai_engine']
        engine = AIVisionEngine(config)
        
        assert engine.enabled == config['enabled']
        assert engine.confidence_threshold == config['confidence']
        assert engine.capture_size == config['capture_size']
    
    def test_process_frame_with_none_frame(self, mock_config):
        """Test process_frame raises AIEngineException for None frame."""
        config = mock_config['ai_engine']
        engine = AIVisionEngine(config)
        
        with pytest.raises(AIEngineException):
            engine.process_frame(None)
    
    def test_process_frame_with_invalid_shape(self, mock_config):
        """Test process_frame raises AIEngineException for invalid frame shape."""
        config = mock_config['ai_engine']
        engine = AIVisionEngine(config)
        
        # Create frame with wrong shape
        invalid_frame = np.zeros((100, 100, 1), dtype=np.uint8)
        
        with pytest.raises(AIEngineException):
            engine.process_frame(invalid_frame)
    
    def test_process_frame_when_disabled(self, mock_config):
        """Test process_frame returns empty list when engine is disabled.

        Per task 3.4 of the aim-pipeline-simplification spec, the engine
        now returns ``List[Detection]`` (req 4.9). When the engine is
        disabled, the list is empty.
        """
        config = mock_config['ai_engine']
        config['enabled'] = False
        engine = AIVisionEngine(config)
        
        # Create valid frame
        frame = np.zeros((320, 320, 3), dtype=np.uint8)
        
        result = engine.process_frame(frame)
        assert result == []
    
    def test_update_config(self, mock_config):
        """Test config update functionality."""
        config = mock_config['ai_engine']
        engine = AIVisionEngine(config)
        
        new_config = {'confidence': 0.75, 'enabled': False}
        engine.update_config(new_config)
        
        assert engine.confidence_threshold == 0.75
        assert engine.enabled is False
    
    @patch('engines.ai_engine.logger')
    def test_exception_handling(self, mock_logger, mock_config):
        """Test that exceptions are properly logged and raised."""
        config = mock_config['ai_engine']
        engine = AIVisionEngine(config)
        
        # Test with None frame to trigger validation exception; engine should
        # raise AIEngineException after Bug 5 migration.
        with pytest.raises(AIEngineException):
            engine.process_frame(None)
        
        mock_logger.debug.assert_called()