"""
Capture module for the detection framework.

Esposizione dell'unico capture backend supportato dalla Target_Configuration
(`capture.backend = capture_card`): la classe `CaptureCardCapture`, basata su
OpenCV `VideoCapture` per USB capture card.
"""

from .capture_card import CaptureCardCapture

__all__ = ["CaptureCardCapture"]
