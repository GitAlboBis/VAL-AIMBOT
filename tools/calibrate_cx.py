"""One-shot calibration of ``aim.cx_counts_per_2pi``.

Empirically derives the kmbox-firmware mouse-count constant that
advances the in-game crosshair through 360 deg at the given Valorant
sensitivity, ADS multiplier, and mouse DPI. Writes the result to
``config.yaml`` under ``aim.cx_counts_per_2pi`` so ``main_simple.py``
picks it up on the next launch.

Aim-tracking-stabilization spec:

* **Requirement 2.6** -- ``Cx`` SHALL be derived empirically and stored
  in ``config.yaml`` under ``aim.cx_counts_per_2pi``.
* **Requirement 3.2** -- the kmbox UDP wire protocol is preserved; this
  tool uses **only** ``driver.move`` (existing ``CMD_MOUSE_MOVE``) and
  ``driver.trace`` (the once-at-startup ``CMD_BAZERMOVE`` config
  packet) -- the same shims ``main_simple.py`` consumes. **No new wire
  bytes** are introduced. The ``Cx`` value lives in ``config.yaml`` and
  never crosses the kmbox UDP boundary; it is a pure host-side scalar
  that scales the ``(dx_px, dy_px) -> (mx, my)`` conversion.

Procedure (design.md File 5 / section 4.5):

    1. Connect the kmbox driver and call ``driver.trace(2, 80)``
       (the same startup configuration ``main_simple.py`` will use).
    2. Issue N test moves of known count magnitude (e.g.
       ``driver.move(500, 0)`` ten times -- 5000 counts total).
    3. The operator visually estimates how many full 360 deg
       rotations the in-game crosshair completed.
    4. Compute::

           pixels_per_360 = total_counts / num_revolutions
           Cx             = pixels_per_360 / (2 * pi)

    5. Cross-check against the pragmatic formula::

           pixels_per_360_estimate ~ 360 / (sensitivity * DPI_factor)

       where ``DPI_factor`` is Valorant's documented per-DPI cm/360 deg
       constant (default 0.07 cm/360 deg at sens=1.0, 1 DPI).
    6. Write ``aim.cx_counts_per_2pi`` to ``config.yaml``.

The tool is invoked manually before the first run on a new mouse / sens
setting and is **NOT** part of the runtime path.

Run with::

    python tools\\calibrate_cx.py
"""

from __future__ import annotations

import argparse
import math
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from input.kmbox_net_driver import KmBoxNetDriver, ConnectionStatus  # noqa: E402

CONFIG_PATH = REPO_ROOT / "config.yaml"

# Default test-move parameters. Total counts is N * dx_per_move, large
# enough that the operator can count whole revolutions without aliasing
# but small enough that one calibration round completes in a few seconds.
DEFAULT_NUM_MOVES = 10
DEFAULT_DX_PER_MOVE = 500
DEFAULT_INTERMOVE_SLEEP_S = 0.15  # > trace_delay_ms / 1000 so each Bezier lands

# Valorant's documented cm/360deg at sens=1.0, 1 DPI. Used for the
# pragmatic cross-check only; not consumed by ``main_simple.py``.
VALORANT_CM_PER_360_AT_UNIT_SENS = 0.07


# --------------------------------------------------------------------- #
# Pure helpers (testable; no side effects).
# --------------------------------------------------------------------- #
def compute_cx(total_counts: float, num_revolutions: float) -> float:
    """Return ``Cx`` from a measured ``(total_counts, num_revolutions)`` pair.

    ``Cx`` = ``pixels_per_360 / (2 * pi)`` where ``pixels_per_360``
    is the kmbox mouse-count delta corresponding to a full 360 deg
    in-game rotation (design.md section 4.5).

    Args:
        total_counts:    Sum of ``|dx|`` across the test moves.
        num_revolutions: Operator-measured full 360 deg rotations.

    Raises:
        ValueError: ``num_revolutions`` is non-positive.
    """
    if num_revolutions <= 0.0:
        raise ValueError(
            f"num_revolutions must be > 0 (got {num_revolutions!r})"
        )
    pixels_per_360 = total_counts / num_revolutions
    return pixels_per_360 / (2.0 * math.pi)


def pragmatic_pixels_per_360(
    sensitivity: float,
    dpi: float,
    cm_per_360_at_unit_sens: float = VALORANT_CM_PER_360_AT_UNIT_SENS,
) -> float:
    """Cross-check estimate of ``pixels_per_360`` from sens / DPI.

    Uses Valorant's documented cm/360deg constant (default 0.07 at
    sens=1.0, 1 DPI). For sens=0.5 / 800 DPI, this returns approximately
    the count delta the device would emit per full rotation on a typical
    mousepad. The result is informational only; the calibrated ``Cx``
    is derived from the operator measurement (design.md section 4.5
    step 5).
    """
    if sensitivity <= 0.0 or dpi <= 0.0:
        raise ValueError(
            f"sensitivity ({sensitivity!r}) and dpi ({dpi!r}) must be > 0"
        )
    cm_per_360 = cm_per_360_at_unit_sens / sensitivity
    inches_per_360 = cm_per_360 / 2.54
    return inches_per_360 * dpi


def _prompt_float(prompt: str, default: Optional[float] = None) -> float:
    """Prompt the operator for a positive float."""
    suffix = f" [default {default}]" if default is not None else ""
    while True:
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return float(default)
        try:
            value = float(raw)
        except ValueError:
            print(f"  '{raw}' is not a number; try again.")
            continue
        if value <= 0.0:
            print(f"  value must be > 0 (got {value}); try again.")
            continue
        return value


def _prompt_int(prompt: str, default: Optional[int] = None) -> int:
    """Prompt the operator for a positive int."""
    suffix = f" [default {default}]" if default is not None else ""
    while True:
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return int(default)
        try:
            value = int(raw)
        except ValueError:
            print(f"  '{raw}' is not an integer; try again.")
            continue
        if value <= 0:
            print(f"  value must be > 0 (got {value}); try again.")
            continue
        return value


# --------------------------------------------------------------------- #
# config.yaml writer -- updates only the single key to avoid losing
# comments / formatting in the rest of the file. PyYAML's safe_dump
# would round-trip-lose every comment; a targeted text edit is safer.
# --------------------------------------------------------------------- #
_AIM_HEADER_RE = re.compile(r"^aim:\s*(?:#.*)?$")
_TOP_LEVEL_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:\s*(?:#.*)?$")
# Match either an active or commented-out cx_counts_per_2pi line, with
# arbitrary leading whitespace. The capture preserves the indentation of
# the surrounding aim: block.
_CX_LINE_RE = re.compile(
    r"^(?P<indent>\s*)(?:#\s*)?cx_counts_per_2pi\s*:\s*\S.*$"
)


def write_cx_to_config(config_path: Path, cx: float) -> Path:
    """Write ``aim.cx_counts_per_2pi = cx`` to ``config.yaml``.

    A timestamped ``.bak.*`` copy of the file is created before the
    write (matches the existing ``config.yaml.bak.*`` convention in
    the repo). Returns the backup path on success.

    Strategy:

    * If a ``cx_counts_per_2pi`` line (commented or active) already
      exists under the ``aim:`` block, replace it in-place so the
      surrounding comments are preserved.
    * Otherwise, insert a fresh ``cx_counts_per_2pi: <value>`` line
      at the start of the ``aim:`` block (after the ``aim:`` header).
    """
    if not config_path.is_file():
        raise FileNotFoundError(f"config.yaml not found at {config_path}")

    text = config_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Locate the aim: header and the next top-level key (the end of the
    # aim: block). Top-level keys have zero indentation.
    aim_start: Optional[int] = None
    aim_end: int = len(lines)
    for idx, line in enumerate(lines):
        stripped = line.rstrip("\r\n")
        if aim_start is None:
            if _AIM_HEADER_RE.match(stripped):
                aim_start = idx
            continue
        # Found aim:; now scan for the next top-level key.
        if _TOP_LEVEL_KEY_RE.match(stripped) and not stripped.startswith(" "):
            aim_end = idx
            break

    if aim_start is None:
        raise ValueError(
            f"{config_path} has no top-level 'aim:' block; refusing to write"
        )

    # Compute the indent the new key should use. Default to 2 spaces if
    # the aim: block is empty (no child lines yet).
    child_indent = "  "
    for line in lines[aim_start + 1 : aim_end]:
        stripped = line.rstrip("\r\n")
        if not stripped or stripped.lstrip().startswith("#"):
            continue
        leading = len(stripped) - len(stripped.lstrip(" "))
        if leading > 0:
            child_indent = " " * leading
            break

    # cx_counts_per_2pi is a float; YAML float formatting must round-trip
    # cleanly. ``repr`` gives a parseable form for finite floats.
    cx_value_str = repr(float(cx))

    # In-place replace if the key already exists in the aim: block.
    replaced = False
    new_lines = list(lines)
    for idx in range(aim_start + 1, aim_end):
        match = _CX_LINE_RE.match(lines[idx].rstrip("\r\n"))
        if match is None:
            continue
        eol = "\n" if lines[idx].endswith("\n") else ""
        new_lines[idx] = (
            f"{match.group('indent')}cx_counts_per_2pi: {cx_value_str}"
            f"  # calibrated by tools/calibrate_cx.py{eol}"
        )
        replaced = True
        break

    if not replaced:
        # Insert immediately after the aim: header so the new key is
        # visually grouped with the rest of the namespace.
        insertion = (
            f"{child_indent}cx_counts_per_2pi: {cx_value_str}"
            f"  # calibrated by tools/calibrate_cx.py\n"
        )
        new_lines.insert(aim_start + 1, insertion)

    new_text = "".join(new_lines)

    # Validate the result is still parseable YAML before committing.
    try:
        parsed = yaml.safe_load(new_text)
    except yaml.YAMLError as exc:
        raise RuntimeError(
            f"refused to write {config_path}: edit produced invalid YAML "
            f"({exc})"
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"refused to write {config_path}: top-level YAML is not a mapping"
        )
    written_cx = parsed.get("aim", {}).get("cx_counts_per_2pi")
    if written_cx is None or not math.isclose(float(written_cx), float(cx)):
        raise RuntimeError(
            f"refused to write {config_path}: round-trip check failed "
            f"(expected aim.cx_counts_per_2pi={cx!r}, got {written_cx!r})"
        )

    # Timestamped backup, then atomic-ish write.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = config_path.with_suffix(config_path.suffix + f".bak.{timestamp}")
    shutil.copy2(config_path, backup_path)
    config_path.write_text(new_text, encoding="utf-8")
    return backup_path


# --------------------------------------------------------------------- #
# Driver wiring -- only ``driver.trace`` and ``driver.move`` are used.
# --------------------------------------------------------------------- #
def _connect_driver(km_cfg: dict) -> KmBoxNetDriver:
    """Construct + connect the kmbox driver from the parsed config block."""
    driver = KmBoxNetDriver(
        ip=km_cfg["ip"],
        port=km_cfg["port"],
        uuid=km_cfg["uuid"],
        use_encryption=km_cfg.get("use_encryption", True),
        target_cps=10,
    )
    if driver.connection_status is not ConnectionStatus.CONNECTED:
        raise RuntimeError(
            f"kmbox not connected: {driver.connection_status} "
            f"(ip={km_cfg['ip']}, port={km_cfg['port']})"
        )
    return driver


def _run_test_moves(
    driver: KmBoxNetDriver,
    num_moves: int,
    dx_per_move: int,
    intermove_sleep_s: float,
    trace_algorithm: int,
    trace_delay_ms: int,
) -> int:
    """Issue N test moves and return the total horizontal count magnitude.

    Mirrors ``main_simple.py``: ``driver.trace(algorithm, delay_ms)`` is
    called ONCE so each subsequent ``driver.move(dx, 0)`` is rendered
    by the device as a hardware Bezier of ``delay_ms`` ms. Inter-move
    sleep is set above ``trace_delay_ms / 1000`` so each Bezier lands
    before the next one is queued (Requirements 2.5 / 2.10).
    """
    driver.trace(algorithm=trace_algorithm, delay_ms=trace_delay_ms)
    print(f"  driver.trace({trace_algorithm}, {trace_delay_ms}) sent")
    print(
        f"  issuing {num_moves} x driver.move({dx_per_move}, 0)"
        f" with {intermove_sleep_s:.3f}s between calls"
    )
    print("  WATCH the in-game crosshair and COUNT full 360 deg revolutions...")
    print()

    for i in range(num_moves):
        driver.move(dx_per_move, 0)
        time.sleep(intermove_sleep_s)
        print(
            f"  [{i + 1:2d}/{num_moves}] move({dx_per_move:+5d}, 0) sent",
            flush=True,
        )

    return abs(int(dx_per_move)) * int(num_moves)


# --------------------------------------------------------------------- #
# Main entry point.
# --------------------------------------------------------------------- #
def _parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calibrate aim.cx_counts_per_2pi for the user's "
                    "Valorant sensitivity, ADS multiplier, and mouse DPI."
    )
    parser.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="Path to config.yaml (default: %(default)s)",
    )
    parser.add_argument(
        "--num-moves",
        type=int,
        default=DEFAULT_NUM_MOVES,
        help="Number of test moves to issue (default: %(default)s)",
    )
    parser.add_argument(
        "--dx-per-move",
        type=int,
        default=DEFAULT_DX_PER_MOVE,
        help="Horizontal count magnitude per move (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the write to config.yaml; print the result only.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = _parse_args(argv)
    config_path = Path(args.config).resolve()

    if not config_path.is_file():
        print(f"[FAIL] config.yaml not found at {config_path}", file=sys.stderr)
        return 1

    with config_path.open(encoding="utf-8") as fp:
        cfg = yaml.safe_load(fp) or {}

    aim_cfg = cfg.get("aim", {}) or {}
    km_cfg = (cfg.get("input", {}) or {}).get("kmbox_net")
    if not km_cfg:
        print(
            f"[FAIL] {config_path} has no 'input.kmbox_net' block",
            file=sys.stderr,
        )
        return 1

    trace_algo = int(aim_cfg.get("trace_algorithm", 2))
    trace_delay = int(aim_cfg.get("trace_delay_ms", 80))
    # Inter-move sleep must exceed trace_delay so each Bezier lands.
    intermove_sleep = max(DEFAULT_INTERMOVE_SLEEP_S, (trace_delay + 20) / 1000.0)

    print("=" * 60)
    print("Cx calibration tool (aim-tracking-stabilization Req 2.6)")
    print("=" * 60)
    print()
    print("Step 1: in-game settings (used for the cross-check formula)")
    sensitivity = _prompt_float("  Valorant in-game sensitivity", 0.5)
    ads_mult = _prompt_float("  ADS multiplier", 0.4)
    dpi = _prompt_float("  Mouse DPI", 800.0)
    _ = ads_mult  # informational only -- ADS is configured per-weapon in-game

    print()
    print("Step 2: connect to kmbox + issue test moves")
    print(f"  ip={km_cfg['ip']}  port={km_cfg['port']}  uuid={km_cfg['uuid']}")
    try:
        driver = _connect_driver(km_cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print(f"  [OK] driver connected ({driver.connection_status})")

    try:
        print()
        print("READY. Place the in-game crosshair on a known reference")
        print("point on the practice range and press ENTER to begin.")
        input("  press ENTER to start...")
        print()
        total_counts = _run_test_moves(
            driver=driver,
            num_moves=int(args.num_moves),
            dx_per_move=int(args.dx_per_move),
            intermove_sleep_s=intermove_sleep,
            trace_algorithm=trace_algo,
            trace_delay_ms=trace_delay,
        )
    finally:
        try:
            driver.release()
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] driver.release(): {exc}", file=sys.stderr)

    print()
    print(f"Step 3: total counts emitted = {total_counts}")
    print("How many full 360 deg rotations did the in-game crosshair complete?")
    print("(Decimals are fine; e.g. 1.5 for one and a half rotations.)")
    num_revs = _prompt_float("  num_revolutions")

    print()
    print("Step 4: compute Cx")
    cx = compute_cx(total_counts=float(total_counts), num_revolutions=num_revs)
    pixels_per_360 = total_counts / num_revs
    print(f"  pixels_per_360 = {total_counts} / {num_revs} = {pixels_per_360:.4f}")
    print(f"  Cx             = {pixels_per_360:.4f} / (2 * pi) = {cx:.4f}")

    print()
    print("Step 5: cross-check against the pragmatic formula")
    estimate = pragmatic_pixels_per_360(sensitivity=sensitivity, dpi=dpi)
    estimated_cx = estimate / (2.0 * math.pi)
    rel_err = abs(cx - estimated_cx) / estimated_cx if estimated_cx > 0 else 0.0
    print(f"  pixels_per_360 (estimate) ~ {estimate:.4f}")
    print(f"  Cx             (estimate) ~ {estimated_cx:.4f}")
    print(f"  relative error            = {rel_err * 100:.2f}%")
    if rel_err > 0.30:
        print(
            "  [WARN] the measured Cx differs from the estimate by > 30%. "
            "Re-run if the rotation count was approximate."
        )

    print()
    if args.dry_run:
        print("Step 6: --dry-run set; NOT writing config.yaml")
        print(f"  would set aim.cx_counts_per_2pi = {cx:.4f}")
        return 0

    print(f"Step 6: write aim.cx_counts_per_2pi = {cx:.4f} to {config_path}")
    try:
        backup = write_cx_to_config(config_path, cx)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] could not write config.yaml: {exc}", file=sys.stderr)
        return 1
    print(f"  [OK] config.yaml updated; backup at {backup.name}")
    print()
    print("Done. Restart main_simple.py to pick up the new Cx.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
