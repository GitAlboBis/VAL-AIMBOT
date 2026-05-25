"""
Detection engines for the framework.

Post dead-code-cleanup: only the AI vision engine (YOLO inference) is
exported. All other engines (HSV tracker, FOV overlay, coordinator) have
been removed as dead code — they were never imported by main_simple.py.
"""

from .ai_engine import AIVisionEngine, Detection

__all__ = [
    'AIVisionEngine',
    'Detection',
]
