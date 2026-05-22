"""Integration tests for the ``utils/`` package after the refactor.

Task 5.3 of the ``single-config-streamlining`` spec verifies that the
filesystem and import surface of ``utils/`` matches the Target_Configuration
after tasks 5.1 (physical removals) and 5.2 (``__all__`` cleanup):

* **Spoofer absence** — ``utils/exe_spoofer.py`` and ``utils/input_spoofer.py``
  are never present (Req 5.1, 5.2).
* **Conditional removals** — ``utils/antidbg.py``, ``utils/threat_response.py``,
  ``utils/crypto.py`` and ``utils/timeout.py`` are absent because the
  Audit_Document classifies each as ``REMOVE`` (Req 5.3-5.5, 5.8).
* **KEEP files present & importable** — ``utils/logger.py``, ``utils/hotkeys.py``
  and ``utils/validation.py`` exist with non-empty content and import cleanly
  (Req 5.6).
* **``__all__`` coherence** — ``utils/__init__.py`` exports only symbols
  defined in ``.py`` files physically present in ``utils/`` and classified
  ``KEEP`` (Req 5.9).
* **Public API** — ``from utils import HotkeyManager, setup_logger`` succeeds
  (Req 5.9, 5.12).
* **Verification fail-closed** — if any file listed in Req 5.1-5.5 is
  unexpectedly present, the test fails and names the offending path
  (Req 5.14).
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path
from typing import List, Set

import pytest


# --- Workspace layout -----------------------------------------------------

_WORKSPACE = Path(__file__).resolve().parents[2]
_UTILS_DIR = _WORKSPACE / "utils"

# Files that MUST be absent regardless of Audit_Document content
# (Req 5.1, 5.2 — unconditional spoofer removal).
_ALWAYS_REMOVED: tuple[str, ...] = (
    "exe_spoofer.py",
    "input_spoofer.py",
)

# Files classified REMOVE in the Audit_Document (Req 5.3-5.5, 5.8) and
# therefore absent from the Refactored_Codebase after task 5.1.
_CONDITIONALLY_REMOVED: tuple[str, ...] = (
    "antidbg.py",
    "threat_response.py",
    "crypto.py",
    "timeout.py",
)

# Files classified KEEP — must exist, be non-empty, and import cleanly.
_KEEP_FILES: tuple[str, ...] = (
    "logger.py",
    "hotkeys.py",
    "validation.py",
)


# --- Helpers --------------------------------------------------------------

def _ensure_workspace_on_path() -> None:
    """Make sure the workspace root is importable for ``import utils``."""
    workspace_str = str(_WORKSPACE)
    if workspace_str not in sys.path:
        sys.path.insert(0, workspace_str)


def _public_symbols_defined_in(py_file: Path) -> Set[str]:
    """Return the set of top-level public symbols defined in a module file.

    A symbol is "public" if its name does not start with an underscore. This
    mirrors the notion used by ``utils/__init__.py``'s ``__all__`` — it must
    reference names actually defined in KEEP files.
    """
    source = py_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(py_file))

    names: Set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if not node.target.id.startswith("_"):
                names.add(node.target.id)
    return names


# --- Tests ----------------------------------------------------------------

@pytest.mark.integration
def test_spoofer_files_are_absent() -> None:
    """Req 5.1, 5.2, 5.14 — spoofer files must not exist."""
    offenders: List[str] = [
        f"utils/{name}" for name in _ALWAYS_REMOVED
        if (_UTILS_DIR / name).exists()
    ]
    assert not offenders, (
        "Spoofer absence invariant violated: the following files must not "
        "exist in the Refactored_Codebase (Req 5.1, 5.2):\n  - "
        + "\n  - ".join(offenders)
    )


@pytest.mark.integration
def test_conditionally_removed_files_are_absent() -> None:
    """Req 5.3, 5.4, 5.5, 5.8, 5.14 — REMOVE-classified utils are gone.

    The Audit_Document (``audit.md``) classifies each of these files as
    ``REMOVE`` in the "Tabella riepilogativa" section, so task 5.1 must
    have deleted them.
    """
    offenders: List[str] = [
        f"utils/{name}" for name in _CONDITIONALLY_REMOVED
        if (_UTILS_DIR / name).exists()
    ]
    assert not offenders, (
        "Conditional removal consistency violated: the following files are "
        "classified REMOVE in audit.md but still exist on disk (Req 5.3-5.5, "
        "5.8):\n  - " + "\n  - ".join(offenders)
    )


@pytest.mark.integration
def test_keep_files_exist_and_are_non_empty() -> None:
    """Req 5.6 — KEEP files exist on disk with non-empty content."""
    missing: List[str] = []
    empty: List[str] = []
    for name in _KEEP_FILES:
        path = _UTILS_DIR / name
        if not path.is_file():
            missing.append(f"utils/{name}")
        elif path.stat().st_size == 0:
            empty.append(f"utils/{name}")

    assert not missing, (
        "Keep-set completeness violated: missing KEEP files in utils/ "
        "(Req 5.6):\n  - " + "\n  - ".join(missing)
    )
    assert not empty, (
        "Keep-set completeness violated: KEEP files in utils/ must be "
        "non-empty (Req 5.6):\n  - " + "\n  - ".join(empty)
    )


@pytest.mark.integration
@pytest.mark.parametrize("module_name", ["utils.logger", "utils.hotkeys", "utils.validation"])
def test_keep_modules_import_cleanly(module_name: str) -> None:
    """Req 5.6 — each KEEP module imports without raising."""
    _ensure_workspace_on_path()
    # Force a fresh import so a stale cached version from an earlier state
    # of the workspace cannot hide a regression.
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)
    assert module is not None


@pytest.mark.integration
def test_utils_all_contains_only_symbols_from_keep_files() -> None:
    """Req 5.9 — ``__all__`` entries resolve to symbols defined in KEEP files.

    Every name listed in ``utils/__init__.py``'s ``__all__`` must:
      * be an attribute of the imported ``utils`` package, and
      * be defined in one of the KEEP ``.py`` files physically present
        in ``utils/`` (i.e. no re-exports from removed modules).
    """
    _ensure_workspace_on_path()
    sys.modules.pop("utils", None)
    import utils  # noqa: WPS433 — intentional late import after path setup

    exported = getattr(utils, "__all__", None)
    assert exported is not None, (
        "utils/__init__.py must define __all__ to pin the public surface "
        "(Req 5.9)."
    )
    assert isinstance(exported, (list, tuple)), (
        f"utils.__all__ must be a list/tuple, got {type(exported).__name__}."
    )

    # Build the set of symbols legitimately defined in KEEP files.
    allowed: Set[str] = set()
    for name in _KEEP_FILES:
        path = _UTILS_DIR / name
        if path.is_file():
            allowed |= _public_symbols_defined_in(path)

    # Every name in __all__ must (a) be resolvable as a package attribute
    # and (b) come from a KEEP file.
    unresolved = [n for n in exported if not hasattr(utils, n)]
    assert not unresolved, (
        "utils.__all__ references names not attached to the package: "
        f"{unresolved}. Each __all__ entry must map to an attribute of "
        "the utils package (Req 5.9)."
    )

    foreign = [n for n in exported if n not in allowed]
    assert not foreign, (
        "utils.__all__ exports symbols not defined in any KEEP file of "
        f"utils/: {foreign}. Allowed symbols (defined in "
        f"{list(_KEEP_FILES)}): {sorted(allowed)} (Req 5.9)."
    )


@pytest.mark.integration
def test_utils_public_api_imports() -> None:
    """Req 5.9, 5.12 — ``from utils import HotkeyManager, setup_logger`` works."""
    _ensure_workspace_on_path()
    # Clear cached modules so the import exercises the current ``__init__``.
    for mod in ("utils", "utils.hotkeys", "utils.logger"):
        sys.modules.pop(mod, None)

    from utils import HotkeyManager, setup_logger  # noqa: WPS433

    assert HotkeyManager is not None
    assert setup_logger is not None
    # Sanity: the callables come from the expected KEEP modules, not from
    # a shim that re-exports a removed module.
    assert HotkeyManager.__module__ == "utils.hotkeys"
    assert setup_logger.__module__ == "utils.logger"
