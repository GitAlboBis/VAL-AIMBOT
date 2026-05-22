"""Integration tests for GUI importability after the refactor (task 14.2).

These tests verify the non-regressive preservation of the ``gui/`` package
required by Requirement 8 of the ``single-config-streamlining`` spec. In
particular:

* **Filesystem invariant (Requirement 8.1 / 8.5)** — the set of filenames
  in ``gui/`` (excluding ``__pycache__`` and ``*.pyc``) is identical to
  the pre-refactor snapshot recorded below. No new files have been
  added, no existing files have been removed.
* **Import invariant (Requirement 8.4 / 8.7)** — each of the production
  ``gui`` sub-modules (``gui.app``, ``gui.shared_state``,
  ``gui.error_handler``, ``gui.config_manager``, ``gui.theme``,
  ``gui.widgets``, ``gui.imgui_compat``) and the top-level ``gui``
  package can be imported via :func:`importlib.import_module` within 10
  seconds without raising ``ImportError``, ``ModuleNotFoundError`` or
  ``SyntaxError``. Files matching ``verify_*.py`` or ``*_example.py``
  are exempt per Requirement 8.7.

Heavy GUI dependencies (``glfw``, ``imgui_bundle``, ``OpenGL``) may not
be installed in the test environment. When an import fails purely
because of one of those optional dependencies the corresponding module
test is skipped with a clear message; the filesystem invariant and the
import of non-GUI-dependency modules are still exercised.

Validates: Requirements 8.1, 8.4, 8.5, 8.7
"""

from __future__ import annotations

import importlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import FrozenSet, Tuple

import pytest


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Pre-refactor snapshot of ``gui/`` filenames (excluding ``__pycache__`` and
# ``*.pyc``). This is the baseline recorded before the
# ``single-config-streamlining`` refactor started and is the ground truth
# for Requirement 8.1 / 8.5.
EXPECTED_GUI_FILENAMES: FrozenSet[str] = frozenset(
    {
        "__init__.py",
        "app.py",
        "config_manager.py",
        "error_handler.py",
        "error_handler_example.py",
        "imgui_compat.py",
        "shared_state.py",
        "theme.py",
        "verify_animations.py",
        "verify_colors.py",
        "verify_window_dimensions.py",
        "widgets.py",
    }
)

# Modules whose importability is required by Requirement 8.4. Files
# matching ``verify_*.py`` or ``*_example.py`` are exempt per 8.7 and are
# therefore deliberately absent from this list.
GUI_MODULES_TO_IMPORT: Tuple[str, ...] = (
    "gui",
    "gui.app",
    "gui.shared_state",
    "gui.error_handler",
    "gui.config_manager",
    "gui.theme",
    "gui.widgets",
    "gui.imgui_compat",
)

# Per Requirement 8.4 each import must complete within 10 seconds.
IMPORT_TIMEOUT_SECONDS: float = 10.0

# Optional heavy GUI-rendering dependencies that may legitimately be
# absent from a non-desktop CI environment. If import of a GUI module
# fails solely because one of these is missing we ``skip`` rather than
# ``fail`` — the requirement only binds "in an environment where the
# project's declared dependencies are installed" (8.4).
OPTIONAL_GUI_DEPENDENCIES: FrozenSet[str] = frozenset(
    {"glfw", "imgui_bundle", "imgui", "OpenGL", "PIL", "pygame"}
)

# Repo root — tests must resolve ``gui/`` relative to the project, not
# the current working directory of the test runner.
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
GUI_DIR: Path = REPO_ROOT / "gui"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _current_gui_filenames() -> FrozenSet[str]:
    """Return ``set(os.listdir(GUI_DIR)) - {'__pycache__'}`` minus ``*.pyc``."""
    if not GUI_DIR.is_dir():
        return frozenset()
    raw = set(os.listdir(GUI_DIR))
    raw.discard("__pycache__")
    return frozenset(name for name in raw if not name.endswith(".pyc"))


def _import_with_timeout(module_name: str, timeout: float) -> object:
    """Import ``module_name`` in a worker thread, failing after ``timeout``.

    Uses :class:`concurrent.futures.ThreadPoolExecutor` so the main test
    thread can enforce the 10-second ceiling mandated by Requirement 8.4
    even if the import hangs (e.g. on a blocking subsystem call). Any
    exception raised inside the worker is re-raised here unchanged so
    the test can inspect it and decide between ``fail`` and ``skip``.
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(importlib.import_module, module_name)
        return future.result(timeout=timeout)


def _is_optional_dep_missing(exc: BaseException) -> Tuple[bool, str]:
    """Return (True, depname) if ``exc`` is caused by a missing optional GUI dep.

    Walks the exception chain so that a ``ModuleNotFoundError`` raised
    deep inside an ``imgui_bundle`` re-export is still recognised.
    """
    seen: list[BaseException] = []
    cur: BaseException | None = exc
    while cur is not None and cur not in seen:
        seen.append(cur)
        if isinstance(cur, ModuleNotFoundError):
            missing = getattr(cur, "name", None)
            if missing:
                # Match on the top-level package name, e.g. "OpenGL.GL"
                # should be considered a missing ``OpenGL`` dependency.
                top = missing.split(".", 1)[0]
                if top in OPTIONAL_GUI_DEPENDENCIES:
                    return True, top
        # Fall back to message-based detection for bare ImportError.
        if isinstance(cur, ImportError):
            msg = str(cur)
            for dep in OPTIONAL_GUI_DEPENDENCIES:
                if dep in msg:
                    return True, dep
        cur = cur.__cause__ or cur.__context__
    return False, ""


@pytest.fixture(autouse=True)
def _ensure_repo_on_syspath():
    """Make sure the project root is importable even when pytest is run
    from an unusual working directory.
    """
    repo_root_str = str(REPO_ROOT)
    added = False
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
        added = True
    try:
        yield
    finally:
        if added:
            try:
                sys.path.remove(repo_root_str)
            except ValueError:
                pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGuiFilesystemInvariant:
    """Requirement 8.1 / 8.5 — filesystem snapshot is unchanged."""

    def test_gui_directory_exists(self) -> None:
        assert GUI_DIR.is_dir(), (
            f"Expected gui/ directory at {GUI_DIR}; refactor must not "
            "remove the package."
        )

    def test_gui_filenames_match_pre_refactor_snapshot(self) -> None:
        """``set(os.listdir('gui')) - {'__pycache__'}`` (minus ``*.pyc``)
        equals the pre-refactor baseline.
        """
        actual = _current_gui_filenames()

        missing = EXPECTED_GUI_FILENAMES - actual
        added = actual - EXPECTED_GUI_FILENAMES

        assert not missing, (
            f"Refactor removed file(s) from gui/ in violation of "
            f"Requirement 8.5: {sorted(missing)}"
        )
        assert not added, (
            f"Refactor added file(s) to gui/ in violation of "
            f"Requirement 8.5: {sorted(added)}"
        )
        assert actual == EXPECTED_GUI_FILENAMES

    def test_expected_snapshot_contains_init(self) -> None:
        """Sanity check on the baseline itself: ``__init__.py`` must be
        present so ``gui`` is importable as a package.
        """
        assert "__init__.py" in EXPECTED_GUI_FILENAMES


@pytest.mark.integration
class TestGuiModuleImportability:
    """Requirement 8.4 / 8.7 — importable within 10 s, no hard failures."""

    @pytest.mark.parametrize("module_name", GUI_MODULES_TO_IMPORT)
    def test_module_imports_within_timeout(self, module_name: str) -> None:
        """Each target module imports within 10 s without ImportError /
        ModuleNotFoundError / SyntaxError.

        If the failure is caused by a missing optional heavy GUI
        dependency (``glfw``, ``imgui_bundle``, ``OpenGL`` …) we skip
        with a clear message, consistent with the "dependencies
        installed" precondition of Requirement 8.4.
        """
        # Drop any previously-cached copy so the import is actually
        # executed now and failures aren't silently masked by a stale
        # ``sys.modules`` entry from another test.
        sys.modules.pop(module_name, None)

        try:
            mod = _import_with_timeout(module_name, IMPORT_TIMEOUT_SECONDS)
        except FuturesTimeoutError:
            pytest.fail(
                f"import {module_name} did not complete within "
                f"{IMPORT_TIMEOUT_SECONDS:.0f}s (Requirement 8.4)."
            )
        except SyntaxError as exc:
            pytest.fail(
                f"import {module_name} raised SyntaxError at "
                f"{exc.filename}:{exc.lineno}: {exc.msg} "
                "(Requirement 8.4 forbids syntax errors)."
            )
        except (ImportError, ModuleNotFoundError) as exc:
            optional, dep = _is_optional_dep_missing(exc)
            if optional:
                pytest.skip(
                    f"Skipping import of {module_name!r}: optional GUI "
                    f"dependency {dep!r} is not installed in this "
                    f"environment (underlying error: {exc})."
                )
            pytest.fail(
                f"import {module_name} failed with "
                f"{type(exc).__name__}: {exc} (Requirement 8.4)."
            )
        else:
            assert mod is not None
            assert getattr(mod, "__name__", None) == module_name


@pytest.mark.integration
class TestGuiImportExemptions:
    """Requirement 8.7 — ``verify_*.py`` and ``*_example.py`` are exempt.

    These tests document the exemption so that a future change that
    accidentally adds one of these files to the importability list is
    caught.
    """

    def test_exempt_files_are_present_on_disk(self) -> None:
        """Exempt files must still exist on disk (Requirement 8.1 / 8.5)
        even though they are not required to import cleanly (8.7).
        """
        actual = _current_gui_filenames()
        exempt = {
            name
            for name in actual
            if name.startswith("verify_") or name.endswith("_example.py")
        }
        assert exempt, (
            "Expected at least one verify_*.py or *_example.py in gui/ "
            "per the pre-refactor snapshot."
        )
        # And none of them should appear in the mandatory-import list.
        for name in exempt:
            module_name = f"gui.{name[:-3]}"  # strip .py
            assert module_name not in GUI_MODULES_TO_IMPORT, (
                f"{module_name} is exempt from Requirement 8.4 per 8.7 "
                "and must not be in the mandatory import list."
            )
