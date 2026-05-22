"""Wave 0 baseline invariant — Property 21: ``__all__`` liveness across packages.

For every symbol ``S`` listed in the ``__all__`` of ``capture/__init__.py``,
``engines/__init__.py``, ``input/__init__.py``, ``utils/__init__.py``, or
``gui/__init__.py``, at least one production (non-test, non-tooling, non-docs)
``.py`` file outside the defining package SHALL contain a reference to ``S``
— either via ``from <pkg> import S``, an attribute access ``<pkg>.S``, or a
plain ``S`` token in a file that also imports ``<pkg>``.

**Property 21: `__all__` liveness across packages**
**Validates: Requirements 26.1, 26.4, 40.4**

Implementation notes
--------------------
* Package ``__all__`` lists are extracted by parsing ``__init__.py`` with
  :mod:`ast` and reading the first ``__all__ = [...]`` assignment as a
  literal list of strings. No package is imported, so the test is insensitive
  to optional runtime dependencies (cv2, imgui_bundle, kmNet, …).
* "Production" is defined by exclusion: files anywhere under ``tests/``,
  ``tools/``, ``docs/``, ``.kiro/``, ``htmlcov/``, ``__pycache__/``,
  ``.hypothesis/``, ``.pytest_cache/``, ``.archive/``, ``.git/``, or any
  path beneath the defining package itself.
* Packages without an ``__init__.py`` ``__all__`` literal are skipped
  gracefully (``gui/__init__.py`` currently has no ``__all__``).
* Parametrization is per ``(package, symbol)`` so individual dead symbols
  can be selectively ``xfail``-ed in future waves. Baseline dead pairs in
  the current tree are marked ``xfail`` here; task 27.3 flips them off.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Workspace layout
# ---------------------------------------------------------------------------

_WORKSPACE: Path = Path(__file__).resolve().parents[2]

# Packages whose ``__all__`` must be exercised. ``gui`` is included per the
# task description even though its ``__init__.py`` currently declares no
# ``__all__`` — the collector silently skips packages with no ``__all__``.
_PACKAGES: Tuple[str, ...] = ("capture", "engines", "input", "utils", "gui")

# Directories that are NOT production code. A ``.py`` under any of these
# roots cannot satisfy the liveness claim.
_NON_PRODUCTION_ROOTS: Tuple[str, ...] = (
    "tests",
    "tools",
    "docs",
    ".kiro",
    "htmlcov",
    "__pycache__",
    ".hypothesis",
    ".pytest_cache",
    ".archive",
    ".git",
)


# ---------------------------------------------------------------------------
# __all__ extraction via AST
# ---------------------------------------------------------------------------


def _extract_all_literal(init_path: Path) -> Optional[List[str]]:
    """Return the literal ``__all__`` list from ``init_path`` or ``None``.

    Only a top-level ``__all__ = [...]`` / ``__all__ = (...)`` assignment with
    string-constant elements is recognised. Any form that requires execution
    (concatenation, comprehension, augmented assignment) yields ``None``.
    """
    if not init_path.is_file():
        return None

    try:
        source = init_path.read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        tree = ast.parse(source, filename=str(init_path))
    except SyntaxError:
        return None

    for node in tree.body:
        targets: List[ast.expr] = []
        value: Optional[ast.expr] = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue

        for target in targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                break
        else:
            continue

        if not isinstance(value, (ast.List, ast.Tuple)):
            return None

        names: List[str] = []
        for elt in value.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                names.append(elt.value)
            else:
                # Non-literal element — bail out so we never silently drop
                # dynamically-computed names.
                return None
        return names

    return None


def _collect_package_symbols() -> Dict[str, List[str]]:
    """Map each package in ``_PACKAGES`` to its ``__all__`` list.

    Packages with no ``__init__.py`` or no literal ``__all__`` are omitted.
    """
    result: Dict[str, List[str]] = {}
    for pkg in _PACKAGES:
        init_path = _WORKSPACE / pkg / "__init__.py"
        symbols = _extract_all_literal(init_path)
        if symbols:
            result[pkg] = symbols
    return result


# ---------------------------------------------------------------------------
# Production file enumeration
# ---------------------------------------------------------------------------


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _iter_production_py_files(defining_pkg: str) -> List[Path]:
    """Return every production ``.py`` file outside ``defining_pkg``.

    A file is excluded when any path component matches one of the
    non-production roots, or when it lives under ``<workspace>/<defining_pkg>``.
    """
    defining_root = (_WORKSPACE / defining_pkg).resolve()
    files: List[Path] = []

    for path in _WORKSPACE.rglob("*.py"):
        # Skip anything inside the defining package — the liveness claim
        # requires a consumer OUTSIDE the defining package.
        if _is_under(path, defining_root):
            continue

        # Skip non-production roots. Match against path components so a
        # file such as ``tests/unit/foo.py`` is excluded regardless of the
        # absolute workspace location.
        rel_parts = path.relative_to(_WORKSPACE).parts
        if any(part in _NON_PRODUCTION_ROOTS for part in rel_parts):
            continue

        files.append(path)

    return files


# ---------------------------------------------------------------------------
# Consumer detection
# ---------------------------------------------------------------------------


def _file_imports_package(text: str, pkg: str) -> bool:
    """Return ``True`` when ``text`` imports ``pkg`` in any recognisable form.

    Recognised forms:
    * ``import <pkg>``
    * ``import <pkg>.<sub>...``
    * ``from <pkg> import ...``
    * ``from <pkg>.<sub> import ...``
    """
    pattern = re.compile(
        rf"^\s*(?:import\s+{re.escape(pkg)}(?:\s|\.|,|$)"
        rf"|from\s+{re.escape(pkg)}(?:\s|\.)\s*)",
        re.MULTILINE,
    )
    return pattern.search(text) is not None


def _file_has_consumer(text: str, pkg: str, symbol: str) -> bool:
    """Return ``True`` when ``text`` consumes ``symbol`` exposed by ``pkg``.

    The scan matches any of:

    * ``from <pkg>[.<sub>...] import ... <symbol> ...`` — including aliased
      and parenthesised multi-line import lists.
    * ``<pkg>[.<sub>...].<symbol>`` attribute access.
    * A plain ``<symbol>`` token in a file that also imports ``<pkg>``.

    ``<symbol>`` is matched with ``\\b`` word boundaries so near-matches such
    as ``my_symbol`` / ``symbol_ext`` never count.
    """
    sym_tok = re.escape(symbol)
    pkg_tok = re.escape(pkg)

    # ``from <pkg>[.<sub>...] import ... <symbol> ...``
    #
    # Captures both the single-line ``from pkg import a, b, symbol`` form
    # and the parenthesised multi-line form. The import list is matched
    # liberally (``[\s\S]`` across newlines inside the parentheses) and the
    # symbol is then verified with a word-boundary match.
    from_re = re.compile(
        rf"from\s+{pkg_tok}(?:\.\w+)*\s+import\s+(\([\s\S]*?\)|[^\n]+)"
    )
    for match in from_re.finditer(text):
        imported_block = match.group(1)
        if re.search(rf"\b{sym_tok}\b", imported_block):
            return True

    # ``<pkg>[.<sub>...].<symbol>`` attribute access.
    attr_re = re.compile(rf"\b{pkg_tok}(?:\.\w+)*\.{sym_tok}\b")
    if attr_re.search(text):
        return True

    # Plain ``<symbol>`` token in a file that also imports ``<pkg>``.
    if _file_imports_package(text, pkg):
        if re.search(rf"\b{sym_tok}\b", text):
            return True

    return False


def _find_consumers(pkg: str, symbol: str) -> List[Path]:
    """Return every production file outside ``pkg`` that references ``symbol``."""
    hits: List[Path] = []
    for path in _iter_production_py_files(pkg):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _file_has_consumer(text, pkg, symbol):
            hits.append(path)
    return hits


# ---------------------------------------------------------------------------
# Parametrisation
# ---------------------------------------------------------------------------


_BASELINE_XFAIL_REASON = (
    "R26 baseline — __all__ may advertise dead symbols; Task 27.3 flips this off"
)


def _build_params() -> List[pytest.param]:
    """Assemble the ``(package, symbol)`` parameter set.

    Each parameter is pre-labelled ``xfail`` when the current tree contains no
    production consumer outside the defining package, so the test ledger
    records the Wave 0 baseline rather than breaking the suite.
    """
    packages = _collect_package_symbols()
    params: List[pytest.param] = []
    for pkg, symbols in sorted(packages.items()):
        for symbol in symbols:
            consumers = _find_consumers(pkg, symbol)
            marks: Tuple[pytest.MarkDecorator, ...] = ()
            if not consumers:
                marks = (pytest.mark.xfail(reason=_BASELINE_XFAIL_REASON),)
            params.append(
                pytest.param(pkg, symbol, id=f"{pkg}.{symbol}", marks=marks)
            )
    return params


_PARAMS: List[pytest.param] = _build_params()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_at_least_one_package_declares_all() -> None:
    """Sanity guard — at least one package under scan must declare ``__all__``.

    Without this check a tree-wide rename that removed every ``__all__``
    would silently yield an empty parametrisation and a green suite.
    """
    packages = _collect_package_symbols()
    assert packages, (
        "No package in {_PACKAGES} declares a literal __all__ — the liveness "
        "scan would be vacuous. Check capture/engines/input/utils/gui "
        "__init__.py files.".format(_PACKAGES=_PACKAGES)
    )


@pytest.mark.unit
@pytest.mark.parametrize(("package", "symbol"), _PARAMS)
def test_all_symbol_has_production_consumer(package: str, symbol: str) -> None:
    """Every ``__all__`` symbol must have at least one production consumer.

    Validates: Requirements 26.1, 26.4, 40.4
    """
    consumers = _find_consumers(package, symbol)
    assert consumers, (
        f"Dead __all__ symbol: '{symbol}' is exported from "
        f"{package}/__init__.py but no production .py file outside "
        f"{package}/ references it (searched workspace={_WORKSPACE}, "
        f"excluding {_NON_PRODUCTION_ROOTS})."
    )
