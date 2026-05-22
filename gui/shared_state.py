"""
Shared state manager for bidirectional data flow between GUI and engines.

This module provides thread-safe communication between the GUI thread and
backend engine threads. The SharedState class manages:
- Configuration updates (GUI → Engine) with mutex protection
- State updates (Engine → GUI) with lock-free reads for performance
- Modified flag tracking for hot-reload configuration changes
"""

import threading
import copy
import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from gui.error_handler import ErrorHandler

logger = logging.getLogger(__name__)


class SharedState:
    """Thread-safe shared state between GUI and engines.
    
    This class provides the central hub for bidirectional data flow:
    - GUI writes config, Engine reads config (mutex-protected)
    - Engine writes state, GUI reads state (lock-free for performance)
    - Modified flag signals config changes to engines
    
    Thread Safety:
    - Config dict: Protected by threading.Lock for writes, deep copy for reads
    - State dict: Lock-free writes and reads (single writer, single reader)
    - Modified flag: Protected by same lock as config dict
    """
    
    def __init__(self, error_handler: Optional['ErrorHandler'] = None):
        """Initialize shared state with empty config and state dicts.
        
        Args:
            error_handler: Optional ErrorHandler instance for config validation.
                          If provided, all config updates will be validated.
        """
        self._config_lock = threading.Lock()
        self._config: Dict[str, Any] = {}
        self._state: Dict[str, Any] = {}
        self._config_modified = False
        self._error_handler = error_handler
    
    def set_error_handler(self, error_handler: 'ErrorHandler') -> None:
        """Set the error handler for config validation.
        
        This method allows setting the error handler after SharedState
        initialization, which is useful when there's a circular dependency
        (ErrorHandler needs SharedState, SharedState needs ErrorHandler).
        
        Args:
            error_handler: ErrorHandler instance for config validation
        
        Thread Safety:
            Should only be called during initialization, before any
            config updates occur.
        
        Example:
            shared_state = SharedState()
            error_handler = ErrorHandler(shared_state)
            shared_state.set_error_handler(error_handler)
        """
        self._error_handler = error_handler
    
    # Config methods (GUI writes, Engine reads)
    
    def update_config(self, section: str, key: str, value: Any) -> None:
        """Update configuration value (GUI → Engine).
        
        This method is called by the GUI thread when a user modifies a setting.
        The change is stored in the config dict and the modified flag is set,
        signaling to engines that they should reload configuration.
        
        If an ErrorHandler is configured, the value will be validated and
        clamped to the valid range before being stored.
        
        Args:
            section: Configuration section (e.g., 'ai_engine', 'aim', 'input')
            key: Configuration key within the section (e.g., 'confidence', 'speed')
            value: New value for the configuration parameter
        
        Thread Safety:
            Protected by mutex lock. Safe to call from GUI thread.
        
        Example:
            shared_state.update_config('ai_engine', 'confidence', 0.65)
        """
        # Get old value for logging
        old_value = None
        with self._config_lock:
            if section in self._config and key in self._config[section]:
                old_value = self._config[section][key]
        
        # Validate value if error handler is configured
        if self._error_handler is not None:
            value = self._error_handler.validate_config_value(section, key, value)
        
        with self._config_lock:
            if section not in self._config:
                self._config[section] = {}
            self._config[section][key] = value
            self._config_modified = True

            # Debug logging: Log config changes when debug mode is enabled.
            # The debug_mode read is performed inside the config lock so it is
            # serialized with the mutation it logs. get_state() itself remains
            # lock-free (it reads self._state directly without acquiring
            # self._config_lock), so no re-entrant lock acquisition occurs.
            debug_mode = self.get_state('general.debug_mode', False)
            if debug_mode:
                if old_value is not None:
                    logger.debug(f"Config change: {section}.{key} = {old_value} → {value}")
                else:
                    logger.debug(f"Config change: {section}.{key} = {value} (new)")
    
    def get_config(self) -> Dict[str, Any]:
        """Get full config snapshot (Engine reads).
        
        Returns a deep copy of the entire configuration dict. This allows
        engines to read configuration without holding locks, improving
        performance. The deep copy ensures engines can't accidentally
        modify the shared config.
        
        Returns:
            Deep copy of the configuration dictionary
        
        Thread Safety:
            Protected by mutex lock. Safe to call from engine thread.
        
        Example:
            config = shared_state.get_config()
            confidence = config.get('ai_engine', {}).get('confidence', 0.55)
        """
        with self._config_lock:
            return copy.deepcopy(self._config)
    
    def check_and_clear_modified(self) -> bool:
        """Check if config was modified and clear flag.
        
        This method is called by engines to check if configuration has
        changed since the last check. It atomically reads and clears the
        modified flag, ensuring engines don't miss updates or process
        the same update twice.
        
        Returns:
            True if config was modified since last check, False otherwise
        
        Thread Safety:
            Protected by mutex lock. Safe to call from engine thread.
        
        Example:
            if shared_state.check_and_clear_modified():
                config = shared_state.get_config()
                apply_config_updates(config)
        """
        with self._config_lock:
            modified = self._config_modified
            self._config_modified = False
            return modified
    
    # State methods (Engine writes, GUI reads)
    
    def update_state(self, key: str, value: Any) -> None:
        """Update state value (Engine → GUI). Lock-free write.
        
        This method is called by engine threads to push performance metrics
        and runtime state to the GUI. It uses lock-free writes for maximum
        performance, as the engine loop runs at high frequency (240+ Hz).
        
        Lock-free design assumes:
        - Single writer (engine thread)
        - Single reader (GUI thread)
        - Python dict operations are atomic for simple assignments
        
        Args:
            key: State key (e.g., 'fps', 'ai_inference_ms', 'aim_state')
            value: Current state value
        
        Thread Safety:
            Lock-free. Safe for single writer, single reader pattern.
        
        Example:
            shared_state.update_state('fps', 144.5)
            shared_state.update_state('ai_inference_ms', 3.2)
            shared_state.update_state('aim_state', 'track')
        """
        self._state[key] = value
    
    def get_state(self, key: str, default: Any = None) -> Any:
        """Get state value (GUI reads). Lock-free read.
        
        This method is called by the GUI thread every frame to read current
        engine state and performance metrics. It uses lock-free reads for
        maximum performance, ensuring the GUI maintains 60+ FPS.
        
        Args:
            key: State key to read
            default: Default value if key doesn't exist
        
        Returns:
            Current state value, or default if key not found
        
        Thread Safety:
            Lock-free. Safe for single writer, single reader pattern.
        
        Example:
            fps = shared_state.get_state('fps', 0.0)
            aim_state = shared_state.get_state('aim_state', 'acquire')
            target_detected = shared_state.get_state('ai_target_detected', False)
        """
        return self._state.get(key, default)
    
    def get_all_state(self) -> Dict[str, Any]:
        """Get all state values as a dictionary.
        
        Returns a shallow copy of the entire state dict. Useful for
        debugging or bulk state inspection.
        
        Returns:
            Shallow copy of the state dictionary
        
        Thread Safety:
            Lock-free. Safe for single writer, single reader pattern.
        
        Example:
            all_state = shared_state.get_all_state()
            print(f"Current state: {all_state}")
        """
        return self._state.copy()
    
    def clear_state(self) -> None:
        """Clear all state values.
        
        Useful for resetting state when engines are stopped or restarted.
        
        Thread Safety:
            Lock-free. Should only be called when engines are stopped.
        """
        self._state.clear()
    
    def get_config_section(self, section: str) -> Dict[str, Any]:
        """Get a specific configuration section.
        
        Returns a deep copy of a single configuration section. More
        efficient than get_config() when only one section is needed.
        
        Args:
            section: Configuration section name
        
        Returns:
            Deep copy of the section dict, or empty dict if not found
        
        Thread Safety:
            Protected by mutex lock. Safe to call from any thread.
        
        Example:
            ai_config = shared_state.get_config_section('ai_engine')
            confidence = ai_config.get('confidence', 0.55)
        """
        with self._config_lock:
            section_data = self._config.get(section, {})
            return copy.deepcopy(section_data)
    
    def update_config_section(self, section: str, values: Dict[str, Any]) -> None:
        """Update multiple values in a configuration section.
        
        Efficiently updates multiple config values in a single section
        with a single lock acquisition.
        
        If an ErrorHandler is configured, each value will be validated and
        clamped to the valid range before being stored.
        
        Args:
            section: Configuration section name
            values: Dictionary of key-value pairs to update
        
        Thread Safety:
            Protected by mutex lock. Safe to call from GUI thread.
        
        Example:
            shared_state.update_config_section('ai_engine', {
                'confidence': 0.65,
                'iou_threshold': 0.45,
                'headshot_bias': 0.8
            })
        """
        # Validate all values if error handler is configured
        if self._error_handler is not None:
            validated_values = {}
            for key, value in values.items():
                validated_values[key] = self._error_handler.validate_config_value(section, key, value)
            values = validated_values
        
        with self._config_lock:
            if section not in self._config:
                self._config[section] = {}
            self._config[section].update(values)
            self._config_modified = True
