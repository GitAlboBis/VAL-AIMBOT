"""
Exception hierarchy for the detection framework.

This module defines a structured exception hierarchy for all framework errors,
enabling precise error handling and recovery at appropriate levels.

Exception Hierarchy:
    FrameworkException (base)
    ├── EngineException (base for all engine errors)
    │   └── AIEngineException (AI/ML inference errors)
    ├── CaptureException (screen capture errors)
    ├── InputException (input driver errors)
    ├── ConfigException (configuration errors)
    └── ValidationException (input validation errors)
"""


class FrameworkException(Exception):
    """
    Base exception for all framework errors.
    
    All custom exceptions in the framework inherit from this class,
    allowing catch-all error handling at the top level when needed.
    
    Usage:
        Catch this at the main loop level to prevent application crashes
        from any framework component.
    """
    pass


class EngineException(FrameworkException):
    """
    Base exception for all engine-related errors.
    
    This includes errors from the AI engine, target tracker, and aim
    controller components.
    
    When to raise:
        - Engine initialization failures
        - Engine processing errors
        - Engine configuration errors
    
    When to catch:
        - In EngineCoordinator to implement error boundaries
        - For auto-disable logic after repeated failures
        - For fallback mechanism activation
    """
    pass


class AIEngineException(EngineException):
    """
    AI engine specific errors.
    
    Raised when AI/ML inference operations fail, including model loading,
    DirectML/CUDA initialization, and inference execution.
    
    When to raise:
        - ONNX model file not found or corrupted
        - DirectML/CUDA provider initialization failure
        - Inference session creation failure
        - Inference execution failure (invalid input, OOM, etc.)
        - Model output shape mismatch
    
    When to catch:
        - In EngineCoordinator for error boundaries
        - For retry logic with exponential backoff
        - For health status tracking
    
    Example:
        >>> if not os.path.exists(model_path):
        ...     raise AIEngineException(f"Model file not found: {model_path}")
    """
    pass


class CaptureException(FrameworkException):
    """
    Capture backend errors.
    
    Raised when screen capture operations fail, including backend initialization,
    frame capture timeout, and invalid frame data.
    
    When to raise:
        - Capture backend initialization failure (DXGI, MSS)
        - Frame capture timeout (>200ms)
        - Invalid frame data (None, wrong shape, wrong dtype)
        - Capture region out of bounds
        - Display adapter not found
    
    When to catch:
        - In main capture loop to prevent crash
        - For fallback to alternative capture backend
        - For timeout handling
    
    Example:
        >>> if frame is None:
        ...     raise CaptureException("Frame capture returned None")
    """
    pass


class InputException(FrameworkException):
    """
    Input driver errors.
    
    Raised when input injection operations fail, including driver not found,
    device connection failure, and send operation timeout.
    
    When to raise:
        - Input driver not found or not installed
        - Device connection failure (KmBox, MAKCU, etc.)
        - Mouse movement send timeout (>50ms)
        - Invalid movement values (NaN, out of bounds)
        - Driver communication error
    
    When to catch:
        - In aim output loop to prevent crash
        - For graceful degradation (disable aim output)
        - For driver reconnection logic
    
    Example:
        >>> if not driver.is_connected():
        ...     raise InputException("Input driver not connected")
    """
    pass


class ConfigException(FrameworkException):
    """
    Configuration errors.
    
    Raised when configuration loading or validation fails, including file not found,
    invalid YAML syntax, and out-of-range values.
    
    When to raise:
        - config.yaml file not found
        - YAML syntax error
        - Required configuration key missing
        - Configuration value out of valid range
        - Configuration value wrong type
        - Configuration file load timeout (>5s)
    
    When to catch:
        - In ConfigManager to use default configuration
        - For configuration validation before applying
        - For hot-reload error handling
    
    Example:
        >>> if 'ai_engine' not in config:
        ...     raise ConfigException("Required key 'ai_engine' missing from config")
    """
    pass


class ValidationException(FrameworkException):
    """
    Input validation errors.
    
    Raised when input validation fails on critical paths, including invalid
    coordinates, invalid frame data, and invalid time deltas.
    
    When to raise:
        - Coordinates are NaN or out of bounds
        - Frame is None, wrong shape, or wrong dtype
        - Delta time is negative or unreasonably large
        - HSV values out of valid range
        - Any critical input parameter is invalid
    
    When to catch:
        - At validation points to use safe defaults
        - For logging validation failures
        - To prevent invalid data from propagating
    
    Note:
        ValidationException should NOT crash the application. Always catch
        at the validation point, log the error, and use safe defaults.
    
    Example:
        >>> if np.isnan(x) or np.isnan(y):
        ...     raise ValidationException(f"Coordinates contain NaN: ({x}, {y})")
    """
    pass
