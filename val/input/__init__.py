"""
Input module for the detection framework.

Target_Configuration build: only the KmBox Net driver and the canonical
sub-pixel ``BaseMouse`` layer are exposed.

All legacy single-PC drivers (DD, Interception, WinAPI, MAKCU
serial/socket, KmBox serial, EFI) have been removed from the codebase;
importing their names from this package raises ``ImportError`` by
design.

Per the aim-pipeline-simplification spec (req 2.14, 4.7, 4.8) the
following helpers were also removed:

* ``input.aim_output`` — the 240 Hz sub-tick blender; quantization is
  done exactly once in ``BaseMouse.calculate_move_amount`` (req 2.7,
  3.7) and ``aim/pipeline.py::aim_step`` calls the driver directly.
* ``input.humanizer`` — every helper had zero live callers
  post-simplification (``bezier_move`` already dead;
  ``calculate_reaction_delay`` only wired to the now-disabled
  auto-fire path of req 2.10; the rest unused).
"""

from .base_mouse import BaseMouse
from .kmbox_net_driver import ConnectionStatus, KmBoxNetDriver

__all__ = [
    'ConnectionStatus',
    'KmBoxNetDriver',
    'BaseMouse',
]
