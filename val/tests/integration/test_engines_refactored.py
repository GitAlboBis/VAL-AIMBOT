"""Integration tests for the ``engines/`` package after the streamlining.

Task 4.4 of the ``single-config-streamlining`` spec verifies that, once
tasks 4.1 and 4.2 are complete, the ``engines/`` folder reflects the
Target_Configuration (AI-only detection engine) and the package remains
importable.

Updated by ``aim-pipeline-simplification`` task 3.9 (req 2.13, 2.14, 4.4,
4.5, 4.6): the multi-stage aim modules ``engines/aim_controller.py``,
``engines/aim_resolver.py``, and ``engines/target_tracker.py`` have been
deleted (replaced by ``aim/pipeline.py::aim_step`` and
``engines/hsv_tracker.py::pick_hsv_target``). Their entries are moved
from the KEEP set to the REMOVED set; ``engines/hsv_tracker.py`` is
added to KEEP. ``engines/fov_overlay.py`` is preserved (debug-only,
out of scope per ``bugfix.md`` §3).

* **Filesystem invariant** — the modules ``engines/hsv_engine.py``,
  ``engines/memory_esp.py``, ``engines/xor_decrypt.py``,
  ``engines/aim_controller.py``, ``engines/aim_resolver.py`` and
  ``engines/target_tracker.py`` are absent from the workspace
  (Requirements 4.1, 4.2, 4.3 + aim-pipeline-simplification req 2.14).
* **Filesystem invariant (KEEP)** — the modules ``engines/ai_engine.py``,
  ``engines/coordinator.py``, ``engines/directml_provider.py``,
  ``engines/hsv_tracker.py`` and ``engines/fov_overlay.py`` exist and
  are non-empty (Requirement 4.5 + aim-pipeline-simplification req
  2.13, 4.4).
* **Import invariant** — each KEEP engine module is importable within
  10 seconds without raising ``ImportError``, ``ModuleNotFoundError`` or
  ``SyntaxError`` (Requirement 4.5). Modules that legitimately depend on
  heavy native/optional libraries (``cv2``, ``torch``, ``onnxruntime``)
  are skipped individually with a clear message when those deps are not
  installed on the test host; the filesystem and ``__all__`` checks are
  not affected by those skips.
* **Public API invariant** — ``engines/__init__.py``'s ``__all__`` does
  not contain ``HSVEngine``, ``MemoryESP``, ``PlayerData``,
  ``CameraData``, ``AimResolver``, ``AimController`` or
  ``TargetTracker`` (Requirements 4.6, 4.7, 4.13 +
  aim-pipeline-simplification req 2.14).

The tests here are intentionally filesystem- and import-oriented: any
behavioural contract of the surviving engines is covered by dedicated
integration tests (e.g. ``test_engine_coordinator.py``).
"""

from __future__ import annotations

import ast
import importlib
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable, Tuple

import pytest


# --- Workspace layout -----------------------------------------------------

_WORKSPACE = Path(__file__).resolve().parents[2]
_ENGINES_DIR = _WORKSPACE / "engines"
_ENGINES_INIT = _ENGINES_DIR / "__init__.py"

# Ensure the workspace root is on ``sys.path`` so ``import engines.*``
# resolves the project package rather than any installed namespace.
_WORKSPACE_STR = str(_WORKSPACE)
if _WORKSPACE_STR not in sys.path:
    sys.path.insert(0, _WORKSPACE_STR)


# Modules that must NOT exist after tasks 4.1 / aim-pipeline-simplification
# task 3.8. ``aim_controller.py``, ``aim_resolver.py``, and
# ``target_tracker.py`` were removed by aim-pipeline-simplification (req
# 2.13, 2.14, 4.4): the multi-stage aim chain collapsed into
# ``aim/pipeline.py::aim_step`` and the 2,633-line HSV god-class became
# the stateless ``engines/hsv_tracker.py``.
_REMOVED_ENGINE_FILES: Tuple[str, ...] = (
    "hsv_engine.py",
    "memory_esp.py",
    "xor_decrypt.py",
    "aim_controller.py",
    "aim_resolver.py",
    "target_tracker.py",
)

# Modules that must exist and be importable. ``fov_overlay`` is listed
# here because the Audit_Document keeps it (Req 4.4 resolved to KEEP);
# if future audits flip it to REMOVE, simply drop the entry.
# ``hsv_tracker`` is the aim-pipeline-simplification replacement for
# ``target_tracker`` (req 2.13, 4.4).
_KEPT_ENGINE_FILES: Tuple[str, ...] = (
    "ai_engine.py",
    "coordinator.py",
    "directml_provider.py",
    "hsv_tracker.py",
    "fov_overlay.py",
)

# Subset of KEEP modules to exercise at import time. ``fov_overlay`` is
# excluded from the hard import requirement because it already guards
# its heavy GUI deps in a top-level try/except.
_IMPORT_TARGETS: Tuple[str, ...] = (
    "engines.ai_engine",
    "engines.coordinator",
    "engines.directml_provider",
    "engines.hsv_tracker",
    "engines.fov_overlay",
)

# Symbols forbidden from ``engines.__all__`` after task 4.2 +
# aim-pipeline-simplification task 3.8 (the multi-stage aim classes
# ``AimResolver``, ``AimController``, ``TargetTracker`` are removed
# alongside the legacy ``HSVEngine`` / ``MemoryESP`` symbols).
_FORBIDDEN_ALL_SYMBOLS: Tuple[str, ...] = (
    "HSVEngine",
    "MemoryESP",
    "PlayerData",
    "CameraData",
    "AimResolver",
    "AimController",
    "TargetTracker",
)

# Heavy optional dependencies that may legitimately be missing on a
# test host. Missing any of these triggers a targeted skip of the
# per-module import check; filesystem and ``__all__`` checks are
# unaffected.
_HEAVY_DEPS: Tuple[str, ...] = ("cv2", "torch", "onnxruntime")

# Per-module heavy-dependency requirements. A module is skipped only if
# one of its declared heavy deps is missing. Modules absent from the
# map have no heavy deps.
_MODULE_HEAVY_DEPS: dict = {
    "engines.ai_engine": ("cv2",),
    "engines.hsv_tracker": ("cv2",),
    # ``engines.directml_provider`` imports ``onnxruntime`` lazily
    # inside functions, so top-level import does not require it.
}

_IMPORT_TIMEOUT_SECONDS = 10.0


# --- Helpers --------------------------------------------------------------


def _missing_heavy_deps(module_name: str) -> Tuple[str, ...]:
    """Return the heavy deps declared by ``module_name`` that are missing."""
    required = _MODULE_HEAVY_DEPS.get(module_name, ())
    missing = []
    for dep in required:
        try:
            importlib.import_module(dep)
        except Exception:
            missing.append(dep)
    return tuple(missing)


def _import_with_timeout(module_name: str, timeout: float) -> object:
    """Import ``module_name`` in a worker thread, enforcing ``timeout``.

    Using ``ThreadPoolExecutor`` instead of ``signal`` keeps this test
    compatible with Windows, where ``signal.alarm`` is unavailable.

    If the module is already imported, return the cached instance
    without forcing a re-import — re-importing shared modules would
    break test isolation by replacing the ``sys.modules`` entry that
    other tests depend on (e.g. ``@patch('engines.ai_engine.logger')``
    in ``tests/unit/test_ai_engine.py`` holds a reference to the
    originally-imported module).
    """
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(importlib.import_module, module_name)
        return future.result(timeout=timeout)


def _extract_all_from_init(init_path: Path) -> Iterable[str]:
    """Return the literal entries of ``__all__`` declared in ``init_path``.

    The list is parsed statically via ``ast`` to avoid side effects from
    importing ``engines/__init__.py`` (which may itself pull in heavy
    deps through its re-exports).
    """
    source = init_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(init_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    value = node.value
                    if isinstance(value, (ast.List, ast.Tuple)):
                        for elt in value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(
                                elt.value, str
                            ):
                                yield elt.value
                    return
        if isinstance(node, ast.AnnAssign):
            target = node.target
            if (
                isinstance(target, ast.Name)
                and target.id == "__all__"
                and isinstance(node.value, (ast.List, ast.Tuple))
            ):
                for elt in node.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(
                        elt.value, str
                    ):
                        yield elt.value
                return


# --- Tests ----------------------------------------------------------------


@pytest.mark.integration
class TestEnginesFilesystem:
    """Filesystem invariants for ``engines/`` (Req 4.1, 4.2, 4.3, 4.5)."""

    @pytest.mark.parametrize("filename", _REMOVED_ENGINE_FILES)
    def test_removed_engine_file_absent(self, filename: str) -> None:
        """Each removed engine module must not exist on disk."""
        path = _ENGINES_DIR / filename
        assert not path.exists(), (
            f"engines/{filename} should have been removed by task 4.1 "
            f"but still exists at {path}"
        )

    @pytest.mark.parametrize("filename", _KEPT_ENGINE_FILES)
    def test_kept_engine_file_present(self, filename: str) -> None:
        """Each KEEP engine module must exist and be non-empty."""
        path = _ENGINES_DIR / filename
        assert path.is_file(), f"engines/{filename} is missing at {path}"
        assert path.stat().st_size > 0, (
            f"engines/{filename} exists but is empty"
        )


@pytest.mark.integration
class TestEnginesInitAll:
    """``engines/__init__.py`` public API invariants (Req 4.6, 4.7, 4.13)."""

    def test_engines_init_exists(self) -> None:
        assert _ENGINES_INIT.is_file(), (
            f"engines/__init__.py is missing at {_ENGINES_INIT}"
        )

    @pytest.mark.parametrize("symbol", _FORBIDDEN_ALL_SYMBOLS)
    def test_all_does_not_contain_removed_symbol(self, symbol: str) -> None:
        """``__all__`` must not re-export HSV/memory_esp symbols."""
        exported = set(_extract_all_from_init(_ENGINES_INIT))
        assert symbol not in exported, (
            f"engines.__all__ still contains {symbol!r}; expected it "
            f"to be removed by task 4.2. Current __all__ = {sorted(exported)!r}"
        )


@pytest.mark.integration
class TestEnginesImportable:
    """Each KEEP engine module imports cleanly within 10 seconds (Req 4.5)."""

    @pytest.mark.parametrize("module_name", _IMPORT_TARGETS)
    def test_module_imports_within_timeout(self, module_name: str) -> None:
        missing = _missing_heavy_deps(module_name)
        if missing:
            pytest.skip(
                f"Skipping import check for {module_name}: optional heavy "
                f"dependency not available on this host -> {', '.join(missing)}. "
                f"Filesystem and __all__ invariants are still enforced by "
                f"sibling tests."
            )

        try:
            module = _import_with_timeout(
                module_name, timeout=_IMPORT_TIMEOUT_SECONDS
            )
        except (ImportError, ModuleNotFoundError) as exc:
            # Some modules import heavy deps transitively without
            # declaring them in ``_MODULE_HEAVY_DEPS``. If the root
            # cause is one of the known heavy deps, skip rather than
            # fail so the Req 4.5 contract is honoured on minimal
            # hosts without masking real regressions.
            cause_name = getattr(exc, "name", "") or str(exc)
            if any(dep in cause_name for dep in _HEAVY_DEPS):
                pytest.skip(
                    f"Skipping import check for {module_name}: missing "
                    f"heavy dependency detected via transitive import "
                    f"({cause_name!r})."
                )
            pytest.fail(
                f"Importing {module_name} raised {type(exc).__name__}: {exc}"
            )
        except SyntaxError as exc:
            pytest.fail(
                f"engines module {module_name} has a syntax error: {exc}"
            )

        assert module is not None, (
            f"Import of {module_name} returned None"
        )
        assert getattr(module, "__name__", None) == module_name, (
            f"Imported module reports __name__={getattr(module, '__name__', None)!r}, "
            f"expected {module_name!r}"
        )
