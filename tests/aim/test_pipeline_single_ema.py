"""
Property test — Task 3.10 of spec ``aim-pipeline-simplification``.

# Feature: aim-pipeline-simplification, Property 2: Single EMA Owner

**Property 2: Single EMA / lock / sub-pixel home** — *the only
**fields** in the post-simplification aim pipeline whose names match
``*smooth*`` / ``*previous*`` / ``*pending*`` / ``*residual*`` SHALL
live inside ``_LockState``. The canonical sub-pixel layer
(``BaseMouse.calculate_move_amount``) keeps its ``remainder_x/y``
fields per req 2.7 / 3.7 — that is the OTHER permitted state and is
not in this property's scope.*

**Validates: Requirement 2.6** — "WHEN smoothing is applied THEN the
system SHALL apply EXACTLY ONE smoothing stage on the path from
``Detection`` to ``BaseMouse.send_move``. The other layers SHALL emit
their input unchanged (pass-through), with their EMA / blend /
residual-carry state removed."

Scope: a *field* is a ``@dataclass`` field declaration or a
``self.<name>`` attribute assignment inside an aim-pipeline class.
Local variables inside helper functions and arguments to method
parameters are NOT fields and are out of scope. The ``kmbox_net_driver``
wire layer is excluded entirely per req 3.1 ("the simplification
refactors callers, not the wire layer"); ``engines/qnn_provider.py``,
``engines/ep_selector.py``, ``engines/directml_provider.py``, and
``engines/fov_overlay.py`` are also excluded because the
simplification touches none of them (req 3.4 / design § "Module
layout").

The unfixed pipeline scattered smoothing across four owners
(``AimResolver._smoothed_aim_x/y``, ``AimController.previous_x/y``,
``AimOutput.pending_x/y`` + ``residual_x/y``); design § "Forensic
Walkthrough" verdicts collapse all four into ``_LockState.smooth_x/y``.
This is a structural (static-grep) test — it walks the simplified
source tree on disk and fails the moment any new file accidentally
re-introduces a parallel smoothing field.
"""

from __future__ import annotations

import os
import re
from typing import List, Tuple

import pytest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Directories housing the post-simplification aim pipeline.
SCAN_DIRS = ("aim", "engines", "input")

# Files explicitly excluded from the scan. Each entry is a relative
# path under ``REPO_ROOT``. The kmbox wire layer is preserved
# byte-for-byte by req 3.1 — its internal local variables are out of
# the simplification's scope. The QNN provider stack and the FOV
# overlay are equally untouched by this refactor.
EXCLUDED_FILES = frozenset(
    os.path.normpath(p)
    for p in (
        os.path.join("input", "kmbox_net_driver.py"),
        os.path.join("input", "base_mouse.py"),  # canonical sub-pixel home (req 3.7)
        os.path.join("engines", "qnn_provider.py"),
        os.path.join("engines", "ep_selector.py"),
        os.path.join("engines", "directml_provider.py"),
        os.path.join("engines", "fov_overlay.py"),
        os.path.join("engines", "ai_engine.py"),  # touched only at process_frame (task 3.4)
    )
)

# Substrings that are forbidden in *field* names anywhere outside
# the allowlisted owner.
FORBIDDEN_TOKENS = ("smooth", "previous", "pending", "residual")

# (file_substr, token) — the token may appear in field names of any
# file whose absolute path contains ``file_substr``. Per req 2.6
# only ``aim/pipeline.py`` (home of ``_LockState`` and ``_smooth``)
# is permitted to mention ``smooth``.
ALLOWED: Tuple[Tuple[str, str], ...] = (
    (os.path.join("aim", "pipeline.py"), "smooth"),
)

# A dataclass field is a top-level type-annotated assignment inside
# a ``@dataclass`` class body. We match ``    name: TypeHint = ...``
# at any indentation (the class body is required; the regex catches
# any annotated assignment).
_DATACLASS_FIELD_RE = re.compile(
    r"^\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[^=]+(?:=.*)?$"
)

# A ``self.attr =`` assignment is the canonical instance-field
# declaration in idiomatic Python. We match the leftmost target only;
# multi-target assignments like ``self.a = self.b = 0`` would still
# be caught because we scan each ``self.<ident>`` group.
_SELF_ASSIGN_RE = re.compile(
    r"\bself\.([A-Za-z_][A-Za-z0-9_]*)\s*(?:[+\-*/|&^%]?=)"
)


def _is_allowed(rel_path: str, token: str) -> bool:
    norm = rel_path.replace("/", os.sep)
    for allow_path, allow_token in ALLOWED:
        if allow_token == token and allow_path in norm:
            return True
    return False


def _scan_file(rel_path: str, abs_path: str) -> List[Tuple[int, str, str]]:
    """Return ``(lineno, field_name, line)`` for forbidden FIELDS."""
    hits: List[Tuple[int, str, str]] = []
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    except OSError:
        return hits

    in_block_string = False
    block_quote = ""
    for lineno, raw in enumerate(source.splitlines(), start=1):
        stripped = raw.strip()
        # Skip block-string contents (docstrings).
        if in_block_string:
            if block_quote in stripped:
                in_block_string = False
            continue
        for q in ('"""', "'''"):
            if stripped.startswith(q):
                if stripped.count(q) >= 2:
                    pass  # single-line docstring; not entering block
                else:
                    in_block_string = True
                    block_quote = q
                break

        # Skip pure comment lines.
        if stripped.startswith("#"):
            continue

        # Drop trailing comments to keep the regex from matching tokens
        # that only appear in prose.
        line = raw.split("#", 1)[0]

        # Collect candidate field names.
        candidates: List[str] = []
        m = _DATACLASS_FIELD_RE.match(line)
        if m:
            candidates.append(m.group(1))
        candidates.extend(_SELF_ASSIGN_RE.findall(line))

        for name in candidates:
            name_lower = name.lower()
            for forbidden in FORBIDDEN_TOKENS:
                if forbidden in name_lower:
                    if not _is_allowed(rel_path, forbidden):
                        hits.append((lineno, name, raw.rstrip()))
                    break

    return hits


def _collect_python_files() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for sub in SCAN_DIRS:
        sub_abs = os.path.join(REPO_ROOT, sub)
        if not os.path.isdir(sub_abs):
            continue
        for dirpath, dirs, files in os.walk(sub_abs):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                if not name.endswith(".py"):
                    continue
                abs_path = os.path.join(dirpath, name)
                rel_path = os.path.relpath(abs_path, REPO_ROOT)
                if os.path.normpath(rel_path) in EXCLUDED_FILES:
                    continue
                out.append((rel_path, abs_path))
    return out


@pytest.mark.unit
def test_only_lockstate_owns_smoothing_fields() -> None:
    """Validates: Requirement 2.6 — single EMA owner.

    Walks the post-simplification source tree on disk and fails the
    moment any non-allowlisted module declares a *field* (dataclass
    field or ``self.<name>`` assignment) whose name matches
    ``*smooth*`` / ``*previous*`` / ``*pending*`` / ``*residual*``.
    Only ``aim/pipeline.py`` (the home of ``_LockState.smooth_x/y``
    and the ``_smooth`` helper) is permitted to mention ``smooth``;
    nothing else mentions any of the four tokens.
    """
    bad: List[Tuple[str, int, str, str]] = []
    for rel_path, abs_path in _collect_python_files():
        for lineno, ident, line in _scan_file(rel_path, abs_path):
            bad.append((rel_path, lineno, ident, line))

    assert not bad, (
        "Property 2 (single EMA owner, req 2.6): the simplification "
        "permits ``*smooth*`` / ``*previous*`` / ``*pending*`` / "
        "``*residual*`` *fields* ONLY in ``aim/pipeline.py`` "
        "(``_LockState.smooth_x/y``). Found field-shaped violations:\n"
        + "\n".join(
            f"  {rel}:{ln}  field={ident!r}  line={text!r}"
            for rel, ln, ident, text in bad
        )
    )
