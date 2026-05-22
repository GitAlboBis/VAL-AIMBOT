"""aim — single home for the Detection → UDP path.

Per the aim-pipeline-simplification spec (req 2.6, 2.12, 4.10) this
package is the ONE place where smoothing (`_smooth`), sticky-lock
identity (`_LockState`, `_select_sticky`), per-tick clamping
(`_clamp_step`), pixel→HID-count scaling (`_to_counts`), and the
≤50-line `aim_step` function live.

Public surface:
    aim_step    — the entire Detection → UDP function
    _LockState  — the canonical pipeline state container

Sub-pixel quantization stays in `input.base_mouse.BaseMouse`
(req 2.7, 3.7); operator-override lives in `aim.override`
(added by task 3.2).
"""

from .pipeline import (
    _LockState,
    _clamp_step,
    _select_sticky,
    _smooth,
    _to_counts,
    aim_step,
)

__all__ = [
    "_LockState",
    "_clamp_step",
    "_select_sticky",
    "_smooth",
    "_to_counts",
    "aim_step",
]
