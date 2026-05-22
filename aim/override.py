"""No-op operator-override shim.

Live testing on the Valorant range showed the operator-override path
was the cause of the "lock stuck after first acquisition" defect: the
framework's own moves echo back through the kmbox Monitor_Channel and
the override accumulator counted them as operator input, freezing the
pipeline. The minimal aim pipeline (see ``aim/pipeline.py``) does not
need an explicit operator-override gate: when the operator moves the
mouse physically, the next detection frame's closest-enemy selection
naturally re-anchors to whichever bot is now near the new crosshair
position.

This module is preserved as a no-op shim so ``main.py`` does not need
to change its imports or its ``self.operator_override`` attribute. The
class still exposes ``start`` / ``stop`` / ``is_overridden`` / ``clear``
/ ``note_self_move`` so any caller that references them gets a quiet
no-op rather than ``AttributeError``.
"""

from __future__ import annotations

from typing import Optional

from input.kmbox_net_driver import KmBoxNetDriver

DEFAULT_THRESHOLD_COUNTS: int = 5
DEFAULT_WINDOW_S: float = 0.050


class OperatorOverride:
    """Quiet no-op operator-override.

    The class accepts the same constructor arguments as before so
    existing call sites (``DetectionFramework.initialize_input``)
    do not need to change. Every method is intentionally a no-op:

    * :meth:`start` — does NOT register a Monitor_Channel callback,
      so the driver's listener thread never invokes anything.
    * :meth:`is_overridden` — always returns ``False``, so the aim
      pipeline never gates on it.
    * :meth:`clear` / :meth:`note_self_move` — no state to clear.

    The driver's Monitor_Channel listener still runs (it's wired into
    ``KmBoxNetDriver.monitor`` independently and used for ``isdown_*``
    queries elsewhere); we just do not consume its events for
    operator-override purposes.
    """

    def __init__(
        self,
        driver: KmBoxNetDriver,
        threshold_counts: int = DEFAULT_THRESHOLD_COUNTS,
        window_s: float = DEFAULT_WINDOW_S,
    ) -> None:
        # Accept the constructor signature unchanged so existing
        # call sites do not break, but store nothing — the class is a
        # no-op.
        del driver, threshold_counts, window_s

    def start(self) -> None:
        """No-op."""

    def stop(self) -> None:
        """No-op."""

    def is_overridden(self) -> bool:
        """Always ``False`` — the aim pipeline never trips."""
        return False

    def clear(self) -> None:
        """No-op."""

    def note_self_move(self) -> None:
        """No-op."""
