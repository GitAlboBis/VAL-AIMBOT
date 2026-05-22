"""Replay a recorded ``Detection`` log through ``aim_step`` (req 2.12).

Reads a JSON or JSONL file of detection frames and runs each frame
through the simplified aim pipeline against a fake ``BaseMouse``
recorder, with ``logging`` configured at ``DEBUG`` so ``aim_step``'s
``head=(...) delta=(...) smooth=(...) counts=(...)`` line is printed
once per frame.

Input format
------------
* JSONL (one frame per line) — preferred for live captures.
* JSON  (single list of frames).

Each frame is a list of ``Detection``-shaped dicts; an empty frame is
``[]``. See ``engines.ai_engine.Detection`` for the field set.

Usage
-----
    python tools/diag_pipeline.py --replay last_engagement.jsonl
    python tools/diag_pipeline.py --replay run.json --config config.yaml
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from aim import _LockState, aim_step  # noqa: E402
from engines.ai_engine import Detection  # noqa: E402
from input.base_mouse import BaseMouse  # noqa: E402


class _RecorderMouse(BaseMouse):
    """Minimal ``BaseMouse`` for replay — records ``send_move`` calls."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[tuple[int, int]] = []

    def send_move(self, x: int, y: int) -> None:
        self.sent.append((x, y))

    def send_click(self, delay_before_click: float = 0.0) -> None:
        pass


def _load_frames(path: Path) -> list[list[Detection]]:
    """Accept both JSON (one list of frames) and JSONL (one frame per line)."""
    text = path.read_text(encoding="utf-8").strip()
    try:
        raw = json.loads(text)
        if not raw or not isinstance(raw[0], list):
            raise ValueError  # not a list-of-frames; fall through to JSONL
    except (json.JSONDecodeError, ValueError):
        raw = [json.loads(line) for line in text.splitlines() if line.strip()]
    return [[Detection(**d) for d in frame] for frame in raw]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay Detection log through aim_step.")
    parser.add_argument("--replay", required=True, help="Path to JSON/JSONL detection log")
    parser.add_argument("--config", default=str(REPO_ROOT / "config.yaml"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG, format="[t+%(relativeCreated)07.0fms] %(message)s")
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    state, mouse = _LockState(), _RecorderMouse()
    for frame in _load_frames(Path(args.replay)):
        aim_step(frame, state, cfg, mouse, operator_overridden=False)
    logging.getLogger(__name__).info("replay done: %d send_move calls", len(mouse.sent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
