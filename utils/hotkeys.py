"""
Global Hotkey Manager for the detection framework.
Uses the `keyboard` library for system-wide hotkey listening.

Hotkey Table (from PRD Module 9):
  F1        → Toggle AI Aimbot ON/OFF
  F2        → Toggle HSV Triggerbot ON/OFF
  F3        → Toggle ESP overlay ON/OFF
  F4        → Cycle smoothing preset (low/med/high)
  F5        → Reload config from file
  Caps Lock → Hold = activate aimbot (activation key)
  F10       → Panic kill — terminate all
"""

import logging
import threading
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


class HotkeyManager:
    """Manages global hotkey bindings for the framework."""

    def __init__(self):
        self._bindings: Dict[str, Callable] = {}
        self._hold_states: Dict[str, bool] = {}
        self._active = False
        self._keyboard = None

    def start(self) -> bool:
        """
        Initialize the keyboard listener.

        Returns:
            True if started successfully
        """
        try:
            import keyboard
            self._keyboard = keyboard
            self._active = True
            logger.info("Hotkey manager started")
            return True
        except ImportError:
            logger.error("keyboard library not installed. Run: pip install keyboard")
            return False

    def register(self, key: str, callback: Callable, description: str = ""):
        """
        Register a hotkey toggle.

        Args:
            key: Key name (e.g. 'f1', 'f10', 'caps lock')
            callback: Function to call when key is pressed
            description: Human-readable description for logging
        """
        if self._keyboard is None:
            logger.warning(f"Cannot register {key}: keyboard not initialized")
            return

        self._bindings[key] = callback
        self._keyboard.on_press_key(key, lambda e: callback())
        logger.info(f"Hotkey registered: {key} → {description or callback.__name__}")

    def register_hold(self, key: str, on_press: Callable, on_release: Callable, description: str = ""):
        """
        Register a hold-to-activate key (like Caps Lock for aimbot).

        Args:
            key: Key name
            on_press: Called when key is pressed down
            on_release: Called when key is released
            description: Human-readable description
        """
        if self._keyboard is None:
            return

        self._hold_states[key] = False

        def handle_press(e):
            if not self._hold_states[key]:
                self._hold_states[key] = True
                on_press()

        def handle_release(e):
            if self._hold_states[key]:
                self._hold_states[key] = False
                on_release()

        self._keyboard.on_press_key(key, handle_press)
        self._keyboard.on_release_key(key, handle_release)
        logger.info(f"Hold-key registered: {key} → {description}")

    def is_held(self, key: str) -> bool:
        """Check if a hold-key is currently held down."""
        return self._hold_states.get(key, False)

    def register_panic(self, key: str, callback: Callable):
        """
        Register the panic key (F10). Highest priority — stops everything.

        Args:
            key: Panic key name (typically 'f10')
            callback: Cleanup/shutdown function
        """
        if self._keyboard is None:
            return

        self._bindings[key] = callback
        self._keyboard.on_press_key(key, lambda e: callback())
        logger.warning(f"Panic key registered: {key}")

    def stop(self):
        """Unhook all hotkeys and stop listening."""
        if self._keyboard is not None:
            try:
                self._keyboard.unhook_all()
            except Exception:
                pass
        self._active = False
        self._bindings.clear()
        self._hold_states.clear()
        logger.info("Hotkey manager stopped")


__all__ = ['HotkeyManager']
