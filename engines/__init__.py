"""
Detection engines for the framework.

Post aim-pipeline-simplification (req 2.13, 2.14, 4.4, 4.5, 4.6) the
package exports only the surfaces that survive the collapse:

* ``AIVisionEngine`` / ``Detection`` — YOLO inference + class filter
  (req 3.4, UNCHANGED).
* ``pick_hsv_target`` — stateless ≤100-line HSV fallback that replaces
  the 2,633-line ``TargetTracker`` god-class (req 2.13, 4.4).
* ``FovOverlay`` — debug-only Tk overlay (out-of-scope per bugfix.md
  §3, kept for the debug FOV circle).

Removed modules (any import attempt raises ``ImportError`` by design):

* ``engines.aim_resolver``  — collapsed into ``aim/pipeline.py::aim_step``.
* ``engines.aim_controller`` — collapsed into ``aim/pipeline.py::_smooth``
  + ``_LockState``.
* ``engines.target_tracker`` — replaced by ``engines.hsv_tracker``.
"""

from .ai_engine import AIVisionEngine, Detection
from .hsv_tracker import pick_hsv_target
from .fov_overlay import FovOverlay

__all__ = [
    'AIVisionEngine',
    'Detection',
    'pick_hsv_target',
    'FovOverlay',
]
