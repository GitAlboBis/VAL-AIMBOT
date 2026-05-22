"""
Error handler for validation and error management.

This module provides centralized error handling for the GUI and backend engines:
- Configuration value validation with type checking and range clamping
- Engine error handling that logs errors without crashing the application
- User-friendly error notifications via the notification system
- Safe default fallback values for invalid configurations
- Exception logging with context and recovery suggestions
- Error frequency tracking for auto-disable logic

File-write responsibility for ``errors.log`` is deliberately NOT owned by this
module (R2, Single_Writer_Invariant). ``main.setup_logging`` installs the sole
``logging.FileHandler`` for the configured log path, and records flow through
the standard logging subsystem. This module only delivers notifications and
mutates in-memory error state.
"""

import logging
import time
import os
from typing import Any, Dict, List, Optional, Tuple, Union

from gui.shared_state import SharedState
from gui.widgets import notifications
from exceptions import (
    FrameworkException,
    EngineException,
    AIEngineException,
    CaptureException,
    InputException,
    ConfigException,
    ValidationException
)


# Setup logger
logger = logging.getLogger(__name__)

# Error log file path
ERROR_LOG_FILE = "errors.log"


class ErrorHandler:
    """Centralized error handling for GUI and engines.
    
    This class provides:
    - Config value validation with range clamping
    - Engine error handling without crashes
    - Error logging and notification integration
    - Validation rules for all config parameters
    
    Thread Safety:
        Safe to call from both GUI and engine threads.
        Uses SharedState's thread-safe methods for state updates.
    """
    
    # Validation rules: (section, key) -> (min_val, max_val, type_fn, default)
    VALIDATION_RULES: Dict[Tuple[str, str], Tuple[Union[int, float], Union[int, float], type, Union[int, float]]] = {
        # AI Engine parameters
        ('ai_engine', 'confidence'): (0.0, 1.0, float, 0.55),
        ('ai_engine', 'iou_threshold'): (0.0, 1.0, float, 0.45),
        ('ai_engine', 'capture_size'): (320, 640, int, 416),
        ('ai_engine', 'headshot_bias'): (0.0, 1.0, float, 0.5),
        
        # Aim parameters
        ('aim', 'speed'): (0.0, 2.0, float, 1.0),
        ('aim', 'smoothing_factor'): (0.0, 1.0, float, 0.5),
        ('aim', 'max_step'): (10.0, 500.0, float, 100.0),
        ('aim', 'x_speed_multiplier'): (0.1, 5.0, float, 1.0),
        ('aim', 'y_speed_multiplier'): (0.1, 5.0, float, 1.0),
        ('aim', 'target_prediction'): (0.0, 1.0, float, 0.0),
        
        # Recoil parameters
        ('recoil', 'recoil_x'): (-10.0, 10.0, float, 0.0),
        ('recoil', 'recoil_y'): (-10.0, 10.0, float, 0.0),
        ('recoil', 'max_offset'): (0.0, 100.0, float, 50.0),
        ('recoil', 'recover'): (0.0, 1.0, float, 0.1),
        
        # Input parameters
        ('input', 'smoothing'): (0.0, 1.0, float, 0.5),
        ('input', 'reaction_min'): (0.0, 1.0, float, 0.05),
        ('input', 'reaction_max'): (0.0, 2.0, float, 0.15),
        ('input', 'cooldown_min'): (0.0, 1.0, float, 0.1),
        ('input', 'cooldown_max'): (0.0, 2.0, float, 0.3),
        ('input', 'hold_min'): (0.0, 1.0, float, 0.05),
        ('input', 'hold_max'): (0.0, 2.0, float, 0.2),
        ('input', 'jitter_sigma'): (0.0, 5.0, float, 0.5),
        ('input', 'bezier_steps'): (5, 50, int, 20),
        
        # Capture parameters
        ('capture', 'monitor'): (0, 10, int, 0),
        ('capture', 'fps_cap'): (30, 300, int, 144),
    }
    
    def __init__(self, shared_state: SharedState):
        """Initialize error handler.
        
        Args:
            shared_state: Shared state instance for communication with GUI/engines
        """
        self.shared_state = shared_state
        self.error_log: List[Dict[str, Any]] = []
        self._max_log_size = 100  # Keep last 100 errors
        self._error_counts: Dict[str, int] = {}  # Track error frequency by component
    
    def log_exception(self, exc: FrameworkException, context: str) -> None:
        """Log exception with context, exception class name, and full traceback.
        
        This method provides structured exception logging with:
        - Exception class name for categorization
        - Full stack trace for debugging
        - Context information about where the error occurred
        - Error frequency tracking for auto-disable logic
        - Recovery suggestions based on exception type
        
        Args:
            exc: The framework exception that was raised
            context: Descriptive context about where/why the error occurred
        
        Thread Safety:
            Safe to call from any thread.
        
        Example:
            try:
                result = ai_engine.process_frame(frame)
            except AIEngineException as e:
                error_handler.log_exception(e, "AI engine frame processing")
        """
        exc_class = exc.__class__.__name__
        exc_message = str(exc)
        
        # Track error frequency by exception class
        self._error_counts[exc_class] = self._error_counts.get(exc_class, 0) + 1
        
        # Log with full traceback
        logger.error(
            f"{context}: {exc_class}: {exc_message}",
            exc_info=True
        )
        
        # Provide recovery suggestions based on exception type
        self._log_recovery_suggestion(exc)
        
        # Add to error log with timestamp
        error_entry = {
            'timestamp': time.time(),
            'context': context,
            'exception_class': exc_class,
            'message': exc_message,
            'error_count': self._error_counts[exc_class]
        }
        self.error_log.append(error_entry)
        
        # Trim log if too large
        if len(self.error_log) > self._max_log_size:
            self.error_log = self.error_log[-self._max_log_size:]
        
        # Push to shared state for GUI display
        self.shared_state.update_state('engine_errors', self.error_log[-10:])
        self.shared_state.update_state('last_error', f"{context}: {exc_class}")

        # Display user-friendly notification
        notifications.add(
            f"{exc_class}: {context}",
            color=(1.0, 0.3, 0.3, 1.0)  # Red color for errors
        )
    
    def _log_recovery_suggestion(self, exc: FrameworkException) -> None:
        """Log recovery suggestions based on exception type.
        
        Args:
            exc: The framework exception that was raised
        """
        if isinstance(exc, AIEngineException):
            logger.info(
                "Recovery suggestion: Check that model file exists at the specified path. "
                "Verify DirectML (AMD) or CUDA (NVIDIA) is properly installed. "
                "Try reducing capture_size in config.yaml if out of memory."
            )
        elif isinstance(exc, ConfigException):
            logger.info(
                "Recovery suggestion: Verify config.yaml syntax is valid YAML. "
                "Check that all numeric values are within documented ranges. "
                "Try resetting to default configuration if issues persist."
            )
        elif isinstance(exc, CaptureException):
            logger.info(
                "Recovery suggestion: Check capture backend is available (DXGI, MSS, or capture card). "
                "Verify monitor index is correct. "
                "Check Windows permissions for screen capture."
            )
        elif isinstance(exc, InputException):
            logger.info(
                "Recovery suggestion: Check input driver installation (IB DLL, KmBox connection, etc.). "
                "Verify COM port settings for serial drivers. "
                "Try a different input driver in config.yaml."
            )
        elif isinstance(exc, ValidationException):
            logger.info(
                "Recovery suggestion: Check input data types and ranges. "
                "Verify frame dimensions match expected capture size. "
                "Ensure coordinates are within screen bounds."
            )
    
    def should_auto_disable(self, component: str) -> bool:
        """Check if component should be auto-disabled due to error frequency.
        
        Components are auto-disabled after 3 consecutive errors to prevent
        crash loops and allow fallback mechanisms to take over.
        
        Args:
            component: Component name or exception class to check
        
        Returns:
            True if error count >= 3, False otherwise
        
        Thread Safety:
            Safe to call from any thread.
        
        Example:
            if error_handler.should_auto_disable('AIEngineException'):
                logger.warning("AI engine auto-disabled; no detection active")
                ai_engine.enabled = False
        """
        error_count = self._error_counts.get(component, 0)
        return error_count >= 3
    
    def reset_error_count(self, component: str) -> None:
        """Reset error count for a component.
        
        Used when a component recovers or is manually re-enabled.
        
        Args:
            component: Component name or exception class to reset
        
        Thread Safety:
            Safe to call from any thread.
        
        Example:
            # After successful recovery
            error_handler.reset_error_count('AIEngineException')
            ai_engine.enabled = True
        """
        if component in self._error_counts:
            self._error_counts[component] = 0
            logger.info(f"Error count reset for {component}")
    
    def get_error_count(self, component: str) -> int:
        """Get current error count for a component.
        
        Args:
            component: Component name or exception class
        
        Returns:
            Current error count
        """
        return self._error_counts.get(component, 0)

    def handle_engine_error(self, engine_name: str, error: Exception) -> None:
        """Handle engine error without crashing.
        
        This method logs engine errors, adds them to the error log,
        and displays a user-friendly notification. The application
        continues running even if an engine fails.
        
        Args:
            engine_name: Name of the engine that encountered the error
            error: The exception that was raised
        
        Thread Safety:
            Safe to call from engine threads.
        
        Example:
            try:
                detection = ai_engine.process_frame(frame)
            except Exception as e:
                error_handler.handle_engine_error('AI Engine', e)
        """
        error_msg = f"{engine_name}: {str(error)}"
        error_type = type(error).__name__
        
        # Add to error log with timestamp
        error_entry = {
            'timestamp': time.time(),
            'engine': engine_name,
            'message': error_msg,
            'type': error_type
        }
        self.error_log.append(error_entry)
        
        # Trim log if too large
        if len(self.error_log) > self._max_log_size:
            self.error_log = self.error_log[-self._max_log_size:]
        
        # Push to shared state for GUI display
        self.shared_state.update_state('engine_errors', self.error_log[-10:])
        self.shared_state.update_state('last_error', error_msg)
        
        # Log to console with full traceback
        logger.error(f"Engine error: {error_msg}", exc_info=True)

        # Display user-friendly notification (red for errors)
        notifications.add(
            f"{engine_name} error: {error_type}",
            color=(1.0, 0.3, 0.3, 1.0)  # Red color for errors
        )
    
    def handle_config_error(self, key: str, value: Any, error: Exception) -> None:
        """Handle configuration error.
        
        This method logs configuration errors and displays a user-friendly
        notification. It does not crash the application.
        
        Args:
            key: Configuration key that caused the error
            value: The invalid value that was provided
            error: The exception that was raised
        
        Thread Safety:
            Safe to call from GUI thread.
        
        Example:
            try:
                validated = validate_config_value('ai_engine', 'confidence', 'invalid')
            except Exception as e:
                error_handler.handle_config_error('confidence', 'invalid', e)
        """
        error_msg = f"Config error: {key}={value}: {str(error)}"
        error_type = type(error).__name__
        
        # Add to error log with timestamp
        error_entry = {
            'timestamp': time.time(),
            'engine': 'Config',
            'message': error_msg,
            'type': error_type
        }
        self.error_log.append(error_entry)
        
        # Trim log if too large
        if len(self.error_log) > self._max_log_size:
            self.error_log = self.error_log[-self._max_log_size:]
        
        # Push to shared state for GUI display
        self.shared_state.update_state('engine_errors', self.error_log[-10:])
        
        # Log to console
        logger.warning(error_msg)

        # Display user-friendly notification (orange for warnings)
        notifications.add(
            f"Invalid config: {key}",
            color=(1.0, 0.5, 0.3, 1.0)  # Orange color for warnings
        )
    
    def validate_config_value(self, section: str, key: str, value: Any) -> Any:
        """Validate and clamp config value to valid range.
        
        This method checks if a configuration value is valid according to
        the validation rules. If the value is out of range, it clamps it
        to the valid range and displays a notification. If the value has
        an invalid type, it returns the safe default value.
        
        Args:
            section: Configuration section (e.g., 'ai_engine', 'aim')
            key: Configuration key within the section
            value: Value to validate
        
        Returns:
            Validated and clamped value, or default if validation fails
        
        Thread Safety:
            Safe to call from GUI thread.
        
        Example:
            validated = error_handler.validate_config_value(
                'ai_engine', 'confidence', 1.5)
            # Returns 1.0 (clamped to max) and shows notification
        """
        rule = self.VALIDATION_RULES.get((section, key))
        
        # If no validation rule exists, return value as-is
        if rule is None:
            return value
        
        min_val, max_val, type_fn, default_val = rule
        
        try:
            # Convert to correct type
            typed_value = type_fn(value)
            
            # Clamp to valid range
            clamped_value = max(min_val, min(max_val, typed_value))
            
            # Notify user if value was clamped
            if clamped_value != typed_value:
                clamp_msg = (
                    f"Config value clamped: {section}.{key} "
                    f"from {typed_value} to {clamped_value} "
                    f"(valid range: [{min_val}, {max_val}])"
                )
                logger.info(clamp_msg)

                # Show yellow warning notification
                notifications.add(
                    f"{key} clamped to [{min_val}, {max_val}]",
                    color=(1.0, 0.8, 0.3, 1.0)  # Yellow color for warnings
                )

            return clamped_value

        except (ValueError, TypeError) as e:
            # Type conversion failed - use default value
            error_msg = (
                f"Config validation failed for {section}.{key}={value}: {e}. "
                f"Using default: {default_val}"
            )
            logger.warning(error_msg)

            # Handle the error (adds to error log and shows notification)
            self.handle_config_error(f"{section}.{key}", value, e)

            return default_val
    
    def get_validation_range(self, section: str, key: str) -> Optional[Tuple[Union[int, float], Union[int, float]]]:
        """Get the valid range for a configuration parameter.
        
        Useful for displaying valid ranges in the GUI or for
        configuring slider widgets.
        
        Args:
            section: Configuration section
            key: Configuration key
        
        Returns:
            Tuple of (min_value, max_value) if validation rule exists,
            None otherwise
        
        Example:
            min_val, max_val = error_handler.get_validation_range(
                'ai_engine', 'confidence')
            # Returns (0.0, 1.0)
        """
        rule = self.VALIDATION_RULES.get((section, key))
        if rule is None:
            return None
        
        min_val, max_val, _, _ = rule
        return (min_val, max_val)
    
    def get_default_value(self, section: str, key: str) -> Optional[Union[int, float]]:
        """Get the default value for a configuration parameter.
        
        Args:
            section: Configuration section
            key: Configuration key
        
        Returns:
            Default value if validation rule exists, None otherwise
        
        Example:
            default = error_handler.get_default_value('ai_engine', 'confidence')
            # Returns 0.55
        """
        rule = self.VALIDATION_RULES.get((section, key))
        if rule is None:
            return None
        
        _, _, _, default_val = rule
        return default_val
    
    def clear_error_log(self) -> None:
        """Clear the error log.
        
        Useful for resetting error state or when starting a new session.
        
        Thread Safety:
            Safe to call from GUI thread.
        """
        self.error_log.clear()
        self.shared_state.update_state('engine_errors', [])
        self.shared_state.update_state('last_error', '')
    
    def get_recent_errors(self, count: int = 10) -> List[Dict[str, Any]]:
        """Get the most recent errors from the log.
        
        Args:
            count: Number of recent errors to return
        
        Returns:
            List of error entries (most recent first)
        
        Example:
            recent = error_handler.get_recent_errors(5)
            for error in recent:
                print(f"{error['engine']}: {error['message']}")
        """
        return self.error_log[-count:][::-1]  # Reverse to get most recent first
    
    def get_error_log_path(self) -> str:
        """Get the path to the error log file.

        Returns:
            Absolute path to the error log file

        Notes:
            File-write responsibility for the log path is owned by
            ``main.setup_logging`` (R2, Single_Writer_Invariant); this method
            exposes only the configured path for display purposes and does not
            perform file I/O.
        """
        return os.path.abspath(ERROR_LOG_FILE)

    def detect_conflicts(self, config: Dict[str, Any]) -> List[str]:
        """Detect conflicting settings in the configuration.
        
        This method checks for various types of conflicts:
        - Both detection engines disabled (no detection possible)
        - Min/max parameter inversions (e.g., reaction_min > reaction_max)
        - Invalid engine combinations
        
        Args:
            config: Configuration dictionary to check
        
        Returns:
            List of conflict warning messages (empty if no conflicts)
        
        Thread Safety:
            Safe to call from GUI thread.
        
        Example:
            conflicts = error_handler.detect_conflicts(config)
            for conflict in conflicts:
                notifications.add(conflict, color=(1.0, 0.5, 0.3, 1.0))
        """
        conflicts = []
        
        # Check that the only detection engine (AI) is still enabled. HSV and
        # Memory ESP were removed by the single-config-streamlining refactor
        # (Req 4.1 / 4.2), so "both detection engines disabled" now collapses
        # to "AI engine disabled".
        ai_enabled = config.get('ai_engine', {}).get('enabled', True)
        
        if not ai_enabled:
            conflicts.append("Both detection engines disabled - no target detection possible!")
        
        # Check for min/max parameter inversions
        input_cfg = config.get('input', {})
        
        # Reaction time conflict
        reaction_min = input_cfg.get('reaction_min', 0.05)
        reaction_max = input_cfg.get('reaction_max', 0.15)
        if reaction_min > reaction_max:
            conflicts.append(f"Reaction time conflict: min ({reaction_min:.2f}) > max ({reaction_max:.2f})")
        
        # Cooldown time conflict
        cooldown_min = input_cfg.get('cooldown_min', 0.1)
        cooldown_max = input_cfg.get('cooldown_max', 0.3)
        if cooldown_min > cooldown_max:
            conflicts.append(f"Cooldown time conflict: min ({cooldown_min:.2f}) > max ({cooldown_max:.2f})")
        
        # Hold time conflict
        hold_min = input_cfg.get('hold_min', 0.05)
        hold_max = input_cfg.get('hold_max', 0.2)
        if hold_min > hold_max:
            conflicts.append(f"Hold time conflict: min ({hold_min:.2f}) > max ({hold_max:.2f})")
        
        return conflicts
    
    def get_default_config(self) -> Dict[str, Any]:
        """Get safe default configuration values.
        
        Returns a configuration dictionary with all parameters set to
        safe default values. This can be used to reset the configuration
        when conflicts are detected or when the user requests a reset.
        
        Returns:
            Dictionary with default configuration values
        
        Example:
            default_config = error_handler.get_default_config()
            for section, values in default_config.items():
                for key, value in values.items():
                    shared_state.update_config(section, key, value)
        """
        default_config = {
            'ai_engine': {
                'enabled': True,
                'confidence': 0.55,
                'iou_threshold': 0.45,
                'capture_size': 416,
                'headshot_bias': 0.5,
            },
            'aim': {
                'speed': 1.0,
                'smoothing_factor': 0.5,
                'max_step': 100.0,
                'x_speed_multiplier': 1.0,
                'y_speed_multiplier': 1.0,
                'target_prediction': 0.0,
                'distance': 50,
                'fov_size': 30,
                'smoothing': 5,
                'prediction': False,
                'ignore_knocked': True,
                'visible_check': True,
                'auto_aim': False,
                'enabled': False,
            },
            'recoil': {
                'mode': 'off',
                'recoil_x': 0.0,
                'recoil_y': 0.0,
                'max_offset': 50.0,
                'recover': 0.1,
            },
            'input': {
                # Only the target driver is supported in the
                # Target_Configuration (Req 3.2). Legacy drivers were
                # removed by the single-config-streamlining refactor.
                'driver': 'kmbox_net',
                'smoothing': 0.5,
                'reaction_min': 0.05,
                'reaction_max': 0.15,
                'cooldown_min': 0.1,
                'cooldown_max': 0.3,
                'hold_min': 0.05,
                'hold_max': 0.2,
                'jitter_sigma': 0.5,
                'bezier_steps': 20,
            },
            'general': {
                # The Target_Configuration pins these four values
                # (Req 7.1-7.4). Legacy top-level keys were removed by
                # Req 5.11.
                'architecture': 'dual_pc',
                'primary_engine': 'ai',
                'activation_key': 'CapsLock',
                'panic_key': 'End',
                'log_level': 'INFO',
                'overlay': False,
            },
            'capture': {
                # Only the target backend is supported in the
                # Target_Configuration (Req 7.2). Legacy backends were
                # removed by the single-config-streamlining refactor.
                'backend': 'capture_card',
                'monitor': 0,
                'fps_cap': 144,
            },
            'visuals': {
                'box_esp': True,
                'skeleton': False,
                'health_bar': True,
                'name_tag': True,
                'distance_tag': False,
            },
            'misc': {
                'debug_mode': False,
                'no_recoil': False,
                'rapid_fire': False,
            },
        }
        
        return default_config
