"""
Example usage of ErrorHandler class.

This file demonstrates how to use the ErrorHandler in the GUI and engine code.
"""

from gui.shared_state import SharedState
from gui.error_handler import ErrorHandler


def example_gui_usage():
    """Example of using ErrorHandler in GUI code."""
    # Initialize shared state and error handler
    shared_state = SharedState()
    error_handler = ErrorHandler(shared_state)
    
    # Example 1: Validate user input from a slider
    user_input = 1.5  # User moved confidence slider to 1.5
    validated = error_handler.validate_config_value(
        'ai_engine', 'confidence', user_input
    )
    print(f"User input: {user_input}, Validated: {validated}")
    # Output: User input: 1.5, Validated: 1.0 (clamped to max)
    
    # Update config with validated value
    shared_state.update_config('ai_engine', 'confidence', validated)
    
    # Example 2: Get validation range for slider widget
    min_val, max_val = error_handler.get_validation_range(
        'ai_engine', 'confidence'
    )
    print(f"Confidence range: [{min_val}, {max_val}]")
    # Output: Confidence range: [0.0, 1.0]
    
    # Example 3: Get default value for reset button
    default = error_handler.get_default_value('ai_engine', 'confidence')
    print(f"Default confidence: {default}")
    # Output: Default confidence: 0.55


def example_engine_usage():
    """Example of using ErrorHandler in engine code."""
    # Initialize shared state and error handler
    shared_state = SharedState()
    error_handler = ErrorHandler(shared_state)
    
    # Example 1: Handle engine initialization error
    try:
        # Simulate model loading failure
        raise FileNotFoundError("Model file not found: yolov8n.pt")
    except Exception as e:
        error_handler.handle_engine_error('AI Engine', e)
        # This logs the error, adds it to error log, and shows notification
        # The application continues running
    
    # Example 2: Handle runtime error
    try:
        # Simulate inference error
        raise RuntimeError("CUDA out of memory")
    except Exception as e:
        error_handler.handle_engine_error('AI Engine', e)
        # Engine can disable itself and continue
        shared_state.update_config('ai_engine', 'enabled', False)
    
    # Example 3: Check recent errors
    recent_errors = error_handler.get_recent_errors(5)
    for error in recent_errors:
        print(f"[{error['engine']}] {error['message']}")


def example_config_validation():
    """Example of validating all config parameters."""
    shared_state = SharedState()
    error_handler = ErrorHandler(shared_state)
    
    # Example config from user or file
    config = {
        'ai_engine': {
            'confidence': 1.5,  # Out of range
            'iou_threshold': 0.45,  # Valid
            'capture_size': 1000,  # Out of range
            'headshot_bias': 0.8,  # Valid
        },
        'aim': {
            'speed': 1.5,  # Valid
            'smoothing_factor': 2.0,  # Out of range
            'max_step': 150.0,  # Valid
        }
    }
    
    # Validate all parameters
    validated_config = {}
    for section, params in config.items():
        validated_config[section] = {}
        for key, value in params.items():
            validated = error_handler.validate_config_value(section, key, value)
            validated_config[section][key] = validated
            
            # Update shared state with validated value
            shared_state.update_config(section, key, validated)
    
    print("Validated config:")
    for section, params in validated_config.items():
        print(f"  {section}:")
        for key, value in params.items():
            original = config[section][key]
            if original != value:
                print(f"    {key}: {original} -> {value} (clamped)")
            else:
                print(f"    {key}: {value}")


if __name__ == '__main__':
    print("=== GUI Usage Example ===")
    example_gui_usage()
    
    print("\n=== Engine Usage Example ===")
    example_engine_usage()
    
    print("\n=== Config Validation Example ===")
    example_config_validation()
