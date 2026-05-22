"""
Property test — Task 3.10 of spec ``aim-pipeline-simplification``.

# Feature: aim-pipeline-simplification, Property 8: Single Quantization

**Property 8: Single quantization site** — *the only location in the
post-simplification aim pipeline that converts a fractional move
into an integer (via ``int()`` / ``round()`` / floor-division
``//``) on data flowing toward the mouse driver SHALL be
``BaseMouse.calculate_move_amount``.*

**Validates: Requirement 2.7** — "WHEN integer pixel quantization is
performed THEN the system SHALL quantize EXACTLY ONCE on the path,
at the layer that owns sub-pixel remainder accumulation
(``BaseMouse.calculate_move_amount`` is the canonical owner). All
upstream layers SHALL pass ``float`` through; ``AimController.clamp_step``
and ``AimOutput.set_move`` SHALL NOT call ``int()`` on their outputs."

The unfixed pipeline performed integer truncation in two places —
``AimController.clamp_step`` returned floats but ``AimOutput`` later
truncated for sub-tick partitioning, and ``BaseMouse.calculate_move_amount``
truncated again for the wire. The two state machines disagreed on
the fractional pixels each had already emitted (defect 1.7). The
simplification routes a single ``float`` from ``aim_step._to_counts``
to ``BaseMouse.move``; only ``calculate_move_amount`` calls ``int()``.

Scope: this is a **structural** test that walks the post-simplification
source files line-by-line. It targets the modules that own the move
data flow:

* ``aim/pipeline.py`` — the ``Detection`` → driver function. MUST
  NOT call ``int()`` / ``round()`` / ``//`` on coordinate data.
* ``input/base_mouse.py`` — owns the canonical sub-pixel layer.
  ``calculate_move_amount`` is the ONLY allowlisted use of
  quantization on this path.

The HSV tracker (``engines/hsv_tracker.py``) and the kmbox wire
layer (``input/kmbox_net_driver.py``) are out of scope: HSV produces
``float`` deltas; the wire layer encodes already-integer values into
network bytes, which is a different concern (req 3.1).
"""

from __future__ import annotations

import os
import re
from typing import List, Tuple

import pytest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# Files in the simplified pipeline that may NOT contain integer
# quantization on coordinate data, except where explicitly allowed.
# Each entry is ``(rel_path, allowed_lines_predicate)`` where the
# predicate, given the source line text, returns True iff the
# quantization on that line is permitted by the spec.
def _allow_in_calculate_move_amount(line: str) -> bool:
    """The canonical sub-pixel quantization site (req 2.7 / 3.7)."""
    return True  # ``BaseMouse.calculate_move_amount`` may quantize freely


PIPELINE_FILES: Tuple[Tuple[str, str], ...] = (
    # (rel_path, function-scope predicate). The predicate runs only
    # inside the function the path's quantization is restricted to.
    (os.path.join("aim", "pipeline.py"), ""),  # NOTHING is allowed
    (os.path.join("aim", "override.py"), ""),  # NOTHING on coord data
)

# Quantization patterns we look for. ``int(``, ``round(``, ``//``
# (floor-division). We deliberately match the *call form* for
# ``int`` / ``round`` so type annotations like ``int_x: int`` and
# the literal ``int`` in ``isinstance(x, int)`` do not register as
# quantization. Floor-division ``//`` is matched only when surrounded
# by something that could be a numeric expression on the right (we
# accept a permissive heuristic and let the per-file allowlist
# handle false positives).
QUANTIZATION_RE = re.compile(
    r"\bint\(|\bround\(|//"
)

# Allowlist of substrings: any source line containing one of these
# substrings is exempt from the quantization check. The spec's
# req 2.7 forbids quantization of *coordinate / move data flowing
# toward the driver*; the exemptions below are integer casts on
# config values, integer counts, or already-integer device deltas
# — none of which carry a fractional move.
COORDINATE_NEUTRAL_SUBSTRINGS: Tuple[str, ...] = (
    # ``cap_size`` is the capture frame size (an integer config key
    # like 416 / 320). The cast normalises ``cfg`` types loaded
    # from YAML; the value is then used to compute the crosshair
    # midpoint via float division (``cap_size / 2.0``), so the
    # downstream coordinate path is ``float`` end-to-end.
    'cap_size = int(ai_cfg["capture_size"])',
    # ``OperatorOverride`` configuration: integer thresholds and
    # already-integer device deltas. The Monitor_Channel hands the
    # framework signed 16-bit ``dx`` / ``dy`` which are integers by
    # construction — no fractional move is being quantized.
    'self._threshold = int(threshold_counts)',
    'self._events.append((now, int(dx), int(dy)))',
)

# Lines we explicitly skip — they are not quantization on coordinate
# data flowing toward the driver. Match the *raw line text*; the
# patterns are conservative (only known false positives).
SKIP_PATTERNS: Tuple[re.Pattern, ...] = (
    # Comments that *describe* the property (the docstring text
    # itself is filtered by the in-block-string check below; this
    # catches inline comments that mention ``int()`` etc).
    re.compile(r"^\s*#"),
    # Type annotations / casts that don't quantize coordinate data.
    re.compile(r"->\s*int\b"),
    re.compile(r":\s*int\b(?!_)"),
)


def _scan_for_quantization(rel_path: str) -> List[Tuple[int, str]]:
    """Return ``(lineno, line)`` for each quantization hit."""
    abs_path = os.path.join(REPO_ROOT, rel_path)
    if not os.path.isfile(abs_path):
        return []
    with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
        source = fh.read()

    hits: List[Tuple[int, str]] = []
    in_block_string = False
    block_quote = ""
    for lineno, raw in enumerate(source.splitlines(), start=1):
        stripped = raw.strip()
        # Skip block-string contents.
        if in_block_string:
            if block_quote in stripped:
                in_block_string = False
            continue
        for q in ('"""', "'''"):
            if stripped.startswith(q):
                if stripped.count(q) >= 2:
                    pass  # single-line docstring
                else:
                    in_block_string = True
                    block_quote = q
                break
        if in_block_string:
            continue

        if any(p.search(raw) for p in SKIP_PATTERNS):
            continue
        if any(s in raw for s in COORDINATE_NEUTRAL_SUBSTRINGS):
            continue

        # Drop any code after a `#` to avoid matching commentary.
        code = raw.split("#", 1)[0]
        if QUANTIZATION_RE.search(code):
            hits.append((lineno, raw.rstrip()))
    return hits


@pytest.mark.unit
def test_aim_pipeline_does_not_quantize_coordinates() -> None:
    """Validates: Requirement 2.7 — single quantization site.

    Walks the simplified aim modules (``aim/pipeline.py`` and
    ``aim/override.py``) and asserts neither contains an ``int()``
    call, ``round()`` call, or floor-division on data flowing toward
    the driver. The ``OperatorOverride`` module accepts ``int`` dx /
    dy from the kmbox device (those are already integers; no
    quantization happens), so its scan also expects zero hits.

    Per req 2.7 / 3.7 the only quantization on coordinate data in
    the entire pipeline is inside ``BaseMouse.calculate_move_amount``,
    which the next test asserts.
    """
    bad: List[Tuple[str, int, str]] = []
    for rel_path, _allow in PIPELINE_FILES:
        for lineno, line in _scan_for_quantization(rel_path):
            bad.append((rel_path, lineno, line))

    assert not bad, (
        "Property 8 (single quantization, req 2.7): the simplified "
        "aim pipeline must hand the driver a float; only "
        "``BaseMouse.calculate_move_amount`` may call int() / round() "
        "/ //. Found unexpected quantization sites:\n"
        + "\n".join(
            f"  {rel}:{ln}  {text!r}" for rel, ln, text in bad
        )
    )


@pytest.mark.unit
def test_base_mouse_owns_canonical_quantization() -> None:
    """req 2.7 / 3.7 — ``calculate_move_amount`` is the owner.

    Confirms that the canonical sub-pixel quantization site is
    ``BaseMouse.calculate_move_amount``: the function MUST contain
    at least one ``int(`` call (it converts the accumulated float
    move to an integer for the wire) and the file's *only*
    quantization sites MUST be inside that function.
    """
    rel_path = os.path.join("input", "base_mouse.py")
    abs_path = os.path.join(REPO_ROOT, rel_path)
    with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
        source = fh.read()

    # Locate the ``calculate_move_amount`` method body — from its
    # ``def`` line to the next top-level dedent (or end of class).
    lines = source.splitlines()
    start: int = -1
    for i, ln in enumerate(lines, start=1):
        if re.match(r"\s+def\s+calculate_move_amount\b", ln):
            start = i
            break
    assert start > 0, (
        "Property 8 owner check (req 2.7): "
        "BaseMouse.calculate_move_amount not found in "
        f"{rel_path} — the canonical sub-pixel quantization site "
        "is missing"
    )

    # Find the end of the function: the next ``def`` at the same or
    # lower indent, or end of file.
    base_indent = len(lines[start - 1]) - len(lines[start - 1].lstrip())
    end = len(lines)
    for i in range(start, len(lines)):
        ln = lines[i]
        if not ln.strip():
            continue
        indent = len(ln) - len(ln.lstrip())
        if indent <= base_indent and (ln.lstrip().startswith("def ")
                                      or ln.lstrip().startswith("class ")):
            end = i
            break

    body = "\n".join(lines[start - 1:end])
    assert "int(" in body, (
        "Property 8 owner check (req 2.7): "
        "BaseMouse.calculate_move_amount does not call int() — "
        "the canonical sub-pixel layer must perform the integer "
        "conversion itself"
    )

    # Ensure no quantization happens elsewhere in the file. The
    # ``BaseMouse.move`` method *uses* the integer outputs of
    # ``calculate_move_amount`` but does not quantize itself; the
    # whole-file scan here is a soft check (the function-scope check
    # above is the binding one for req 2.7).
    quantization_lines = []
    in_block_string = False
    block_quote = ""
    for lineno, raw in enumerate(lines, start=1):
        if start <= lineno < end:
            continue  # inside the allowlisted owner
        stripped = raw.strip()
        if in_block_string:
            if block_quote in stripped:
                in_block_string = False
            continue
        for q in ('"""', "'''"):
            if stripped.startswith(q):
                if stripped.count(q) >= 2:
                    pass
                else:
                    in_block_string = True
                    block_quote = q
                break
        if in_block_string:
            continue
        if any(p.search(raw) for p in SKIP_PATTERNS):
            continue
        if any(s in raw for s in COORDINATE_NEUTRAL_SUBSTRINGS):
            continue
        code = raw.split("#", 1)[0]
        if QUANTIZATION_RE.search(code):
            quantization_lines.append((lineno, raw.rstrip()))

    assert not quantization_lines, (
        "Property 8 (req 2.7): quantization outside "
        "calculate_move_amount in input/base_mouse.py:\n"
        + "\n".join(f"  line {ln}: {text!r}" for ln, text in quantization_lines)
    )
