"""
Base mouse abstraction layer.
Ported from Unibot (vike256, GPLv3) — adapted for Tuborg architecture.

Provides:
  - Sub-pixel remainder tracking (no precision loss between frames)
  - Thread-safe click with CPS rate limiting
  - Unified API for all backends (DD, MAKCU Serial, WinAPI)
"""
import abc
import threading
import time


class BaseMouse(abc.ABC):
    """Abstract base for all mouse backends."""

    def __init__(self, target_cps: float = 10.0):
        self.click_thread = threading.Thread(target=self.send_click)
        self.last_click_time = 0.0
        self.target_cps = max(target_cps, 1.0)

        # Sub-pixel remainder accumulation (from Unibot)
        # Prevents precision loss when fractional moves are truncated to int
        self.remainder_x = 0.0
        self.remainder_y = 0.0

    @abc.abstractmethod
    def send_move(self, x: int, y: int):
        """Send a relative mouse move (integer pixels)."""
        pass

    @abc.abstractmethod
    def send_click(self, delay_before_click: float = 0.0):
        """Send a mouse click (left button)."""
        pass

    def calculate_move_amount(self, move_x: float, move_y: float):
        """
        Convert fractional movement to integer, accumulating remainder.

        This is CRITICAL for smooth aim — without it, fractional px are
        discarded every frame, causing drift and jitter on slow movements.
        """
        # Add the remainder from the previous calculation
        move_x += self.remainder_x
        move_y += self.remainder_y

        # Round x and y, and calculate the new remainder
        self.remainder_x = move_x
        self.remainder_y = move_y
        int_x = int(move_x)
        int_y = int(move_y)
        self.remainder_x -= int_x
        self.remainder_y -= int_y

        return int_x, int_y

    def click(self, delay_before_click: float = 0.0):
        """Rate-limited click — respects target_cps."""
        if (
            not self.click_thread.is_alive() and
            time.time() - self.last_click_time >= 1.0 / self.target_cps
        ):
            self.last_click_time = time.time()
            self.click_thread = threading.Thread(
                target=self.send_click, args=(delay_before_click,),
                daemon=True
            )
            self.click_thread.start()

    def move(self, x: float, y: float):
        """Move with sub-pixel remainder tracking."""
        move_x, move_y = self.calculate_move_amount(x, y)
        if move_x != 0 or move_y != 0:
            self.send_move(move_x, move_y)

    def reset_remainder(self):
        """Clear accumulated remainder (call on target loss)."""
        self.remainder_x = 0.0
        self.remainder_y = 0.0


__all__ = ['BaseMouse']
