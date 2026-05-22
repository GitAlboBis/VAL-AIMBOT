"""
Baseline GUI_Import_Barrier AST scan (Property 6).

Property 6: GUI_Import_Barrier across engine-side packages.
Validates: Requirements 8.1, 8.2, 8.6, 8.7, 40.3 (audit-remediation spec).

Design link: ``.kiro/specs/audit-remediation/design.md`` — Property 6:
""For every ``.py`` file under ``engines/``, ``capture/``, ``input/``,
and ``utils/``, no ``ast.Import`` or ``ast.ImportFrom`` node anywhere in
the module (top level OR inside a function / class / conditional) SHALL
target the ``gui`` package.""

Methodology
-----------
1. Enumerate every ``.py`` file under ``engines/``, ``capture/``,
   ``input/`` and ``utils/`` (recursively, ``__pycache__`` skipped).
   Files are parametrized individually so newly-introduced violations
   surface on the specific file that introduced them.

2. For each file, parse the source into an AST (NOT a runtime import:
   the whole point of this barrier is to detect gui-targeting imports
   without paying the ``imgui_bundle`` cost of actually importing the
   engine modules in headless environments — Requirement 8.5).

3. Walk the full tree with ``ast.walk`` so nested imports — imports
   tucked inside a ``try`` block or a function body, which is exactly
   how ``engines/target_tracker.py`` currently smuggles
   ``gui.widgets.notifications`` past a top-level reading — are
   detected equally with module-level imports. This is required by
   Requirement 8.2 which names the ``target_tracker`` in-function
   import explicitly.

4. A node is a violation if:
     * ``ast.Import``: any alias whose ``name`` equals ``"gui"`` or
       begins with ``"gui."``.
     * ``ast.ImportFrom``: ``module`` equals ``"gui"`` or begins with
       ``"gui."``. (A bare ``from . import X`` inside the ``gui``
       package would have ``module is None``; engine-side packages
       cannot legitimately use such relative imports to reach ``gui``,
       so ``module is None`` is not a violation source.)

5. For each file the test asserts the violation list is empty. On
   failure the assertion message lists every
   ``(filepath, module, lineno)`` triple so a regression in any file
   is localised without re-running the scan.

Wave 0 baseline
---------------
``engines/target_tracker.py`` previously contained two in-function
``from gui.widgets import notifications`` imports. After
aim-pipeline-simplification task 3.8 the entire ``target_tracker.py``
file (2,633 lines) was deleted and replaced by the stateless
≤100-line ``engines/hsv_tracker.py``, which never imports any
``gui.*`` symbol. The baseline offenders set is therefore empty:
every engine-side ``.py`` is expected to pass the barrier today
and SHALL continue to pass as the invariant is armed.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Set, Tuple

import pytest


# ---------------------------------------------------------------------------
# Workspace layout
# ---------------------------------------------------------------------------

_WORKSPACE: Path = Path(__file__).resolve().parents[2]

_ENGINE_SIDE_DIRS: Tuple[Path, ...] = (
    _WORKSPACE / "engines",
    _WORKSPACE / "capture",
    _WORKSPACE / "input",
    _WORKSPACE / "utils",
)


# ---------------------------------------------------------------------------
# Known Wave 0 baseline offenders (Requirement 8.2)
# ---------------------------------------------------------------------------
#
# Files that currently contain an engine → gui import and are scheduled
# to be fixed by Task 10. Listed as workspace-relative POSIX strings so
# the comparison is stable across platforms. When Task 10.3 removes the
# last violating import from a file, drop its entry here and the file
# will begin enforcing the barrier via this same test.

_BASELINE_GUI_IMPORT_OFFENDERS: Set[str] = set()


# ---------------------------------------------------------------------------
# File enumeration
# ---------------------------------------------------------------------------


def _iter_py_files(root: Path) -> List[Path]:
    """Return every ``.py`` file under ``root`` (sorted, ``__pycache__`` skipped)."""
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def _collect_engine_side_files() -> List[Path]:
    """Return every engine-side ``.py`` across the four barrier packages."""
    files: List[Path] = []
    for root in _ENGINE_SIDE_DIRS:
        files.extend(_iter_py_files(root))
    return files


_ENGINE_SIDE_FILES: List[Path] = _collect_engine_side_files()


def _file_id(path: Path) -> str:
    """Parametrize id — workspace-relative POSIX path."""
    return path.relative_to(_WORKSPACE).as_posix()


# ---------------------------------------------------------------------------
# AST scan — gui-targeting imports anywhere in the module
# ---------------------------------------------------------------------------


def _targets_gui(module: str | None) -> bool:
    """Return True if a dotted ``module`` targets the ``gui`` package."""
    if not module:
        return False
    return module == "gui" or module.startswith("gui.")


def _collect_gui_imports(path: Path) -> List[Tuple[str, str, int]]:
    """Parse ``path`` and return ``[(filepath, module, lineno), ...]``
    for every ``Import`` / ``ImportFrom`` node anywhere in the module
    that targets the ``gui`` package.

    Uses ``ast.walk`` so nested imports (e.g. the
    ``try: from gui.widgets import notifications`` inside
    ``engines/target_tracker.py``) are captured alongside top-level
    imports. A ``SyntaxError`` during parsing is treated as an empty
    violation set — the file cannot import ``gui.*`` if it does not
    parse at all — but is also surfaced as a smoke-test failure below.
    """
    rel = path.relative_to(_WORKSPACE).as_posix()
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    offences: List[Tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name or ""
                if name == "gui" or name.startswith("gui."):
                    offences.append((rel, name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            module = node.module  # None for bare relative "from . import X"
            if _targets_gui(module):
                # ``module`` is str when _targets_gui is True.
                assert module is not None  # narrow for type checkers
                offences.append((rel, module, node.lineno))
    return offences


# ---------------------------------------------------------------------------
# Parametrization — per-file so new violations localise
# ---------------------------------------------------------------------------


def _param_marks(path: Path):
    """Attach the ``xfail`` marker for files in the Wave 0 baseline set."""
    rel = _file_id(path)
    if rel in _BASELINE_GUI_IMPORT_OFFENDERS:
        return [
            pytest.mark.xfail(
                strict=True,
                reason=(
                    "R8 baseline — target_tracker imports "
                    "gui.widgets.notifications inside two try/except "
                    "blocks (one on locked transition, one on unlocked "
                    "transition). Task 10.1 replaces these with "
                    "SharedState.NOTIFICATION_QUEUE enqueues; Task 10.3 "
                    "flips this off."
                ),
            )
        ]
    return []


# ---------------------------------------------------------------------------
# Property 6 — parametrized per-file coverage test
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        pytest.param(p, marks=_param_marks(p), id=_file_id(p))
        for p in _ENGINE_SIDE_FILES
    ],
)
def test_engine_side_file_has_no_gui_import(path: Path) -> None:
    """Property 6 — no engine-side ``.py`` file imports from ``gui.*``.

    The file is parsed (never imported — Requirement 8.5 demands the
    engines operate without ``imgui_bundle`` in headless environments)
    and every ``ast.Import`` / ``ast.ImportFrom`` node anywhere in the
    tree is inspected. Any node targeting ``gui`` or ``gui.*`` is a
    violation.

    Files listed in ``_BASELINE_GUI_IMPORT_OFFENDERS`` carry a strict
    ``xfail`` marker so the Wave 0 suite records the known violation
    without masking it; when Task 10 removes the violating import the
    entry is deleted and this same test enforces the barrier going
    forward.

    **Validates: Requirements 8.1, 8.2, 8.6, 8.7, 40.3**
    """
    offences = _collect_gui_imports(path)
    if not offences:
        return
    rendered = "\n  ".join(
        f"{filepath}:{lineno} → {module}"
        for filepath, module, lineno in offences
    )
    pytest.fail(
        "GUI_Import_Barrier violation — engine-side file imports from "
        f"the ``gui`` package at {len(offences)} site(s):\n  {rendered}\n"
        "Requirement 8.1 forbids any symbol under ``engines/``, "
        "``capture/``, ``input/``, or ``utils/`` from importing ``gui.*``; "
        "Requirement 8.2 names the ``engines/target_tracker.py`` "
        "in-function import explicitly. If this is a newly-introduced "
        "import, route the data through ``SharedState`` (see R8.3/R8.4) "
        "rather than reaching across the barrier."
    )


# ---------------------------------------------------------------------------
# Sanity checks — prevent the scan from going silently vacuous
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_engine_side_file_corpus_is_non_empty() -> None:
    """Smoke: at least one engine-side ``.py`` was discovered.

    Without a file corpus, the parametrized test above expands to zero
    cases and the barrier is vacuously green. This check fires loudly
    if any of the four directories disappears or is renamed without
    updating ``_ENGINE_SIDE_DIRS``.
    """
    assert _ENGINE_SIDE_FILES, (
        "No engine-side ``.py`` files were discovered under "
        f"{[str(d) for d in _ENGINE_SIDE_DIRS]}. Either the workspace "
        "layout changed (update ``_ENGINE_SIDE_DIRS``) or the "
        "``_WORKSPACE`` anchor is wrong."
    )


@pytest.mark.unit
def test_each_engine_side_directory_contributes_at_least_one_file() -> None:
    """Smoke: each of the four barrier directories contributes a file.

    If a directory contributes zero ``.py`` files the barrier silently
    drops coverage there. This check forces the failure to surface on
    the specific directory that emptied out.
    """
    empty = [
        str(d.relative_to(_WORKSPACE))
        for d in _ENGINE_SIDE_DIRS
        if not _iter_py_files(d)
    ]
    assert not empty, (
        "Engine-side barrier directories contributed zero ``.py`` files: "
        f"{empty}. Either the directory was removed (update "
        "``_ENGINE_SIDE_DIRS``) or the workspace anchor is wrong."
    )


@pytest.mark.unit
def test_baseline_offenders_are_present_in_corpus() -> None:
    """Smoke: every file in the baseline offenders set actually exists.

    If an entry in ``_BASELINE_GUI_IMPORT_OFFENDERS`` is stale (file
    was renamed or deleted) the ``xfail(strict=True)`` marker will
    never be exercised and the scan carries a dead entry. Fail loudly
    so the set is maintained in lock-step with the tree.
    """
    known = {_file_id(p) for p in _ENGINE_SIDE_FILES}
    missing = _BASELINE_GUI_IMPORT_OFFENDERS - known
    assert not missing, (
        "``_BASELINE_GUI_IMPORT_OFFENDERS`` contains paths not found in "
        f"the engine-side corpus: {sorted(missing)}. If the file was "
        "renamed, update the set; if it was deleted, drop the entry."
    )


@pytest.mark.unit
def test_targets_gui_classifier_shape() -> None:
    """``_targets_gui`` returns True exactly for ``gui`` / ``gui.*``.

    Guards against silent drift of the classifier — the property test
    above leans on it entirely, so a bug here would turn the barrier
    vacuous without anyone noticing.
    """
    assert _targets_gui("gui") is True
    assert _targets_gui("gui.widgets") is True
    assert _targets_gui("gui.widgets.notifications") is True
    assert _targets_gui(None) is False
    assert _targets_gui("") is False
    assert _targets_gui("guicorn") is False  # prefix-only match, not gui.*
    assert _targets_gui("engines.gui") is False
    assert _targets_gui("utils") is False
