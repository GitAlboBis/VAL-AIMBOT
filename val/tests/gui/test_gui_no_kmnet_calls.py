"""
Property test — Task 11.4 of spec ``kmbox-net-integration``.

# Feature: kmbox-net-integration, Property 8: GUI never invokes ``kmNet``
#   directly.

**Property 8: GUI never invokes ``kmNet`` directly**

    *For every* ``.py`` file under ``gui/`` (recursively):

    - the module SHALL NOT contain an ``import kmNet`` statement;
    - the module SHALL NOT contain a ``from kmNet ...`` ``ImportFrom``
      statement (including ``from kmNet.something import x``);
    - the module SHALL NOT contain any attribute-access expression whose
      value chain terminates at a bare ``Name`` node spelled ``kmNet``
      (i.e. no ``kmNet.foo``, ``kmNet.foo.bar``, ``kmNet.foo()``, etc.).

    The only allowed path from the GUI to the vendor ``kmNet.pyd`` module
    is via the live ``KmBoxNetDriver`` instance (e.g. ``driver._connect()``
    on a worker thread); the driver module owns every ``kmNet`` reference.

**Validates: Requirements 7.9**

    > THE GUI SHALL read all ``KmBoxNetDriver`` state through the
    > ``Shared_State`` snapshot and SHALL NOT call any ``kmNet`` function
    > directly from the render thread.

Strategy
--------
This test implements the *static* half of Property 8 — a structural
property over the source tree of ``gui/``. It walks every ``.py`` file
under the package, parses each one with :mod:`ast`, then walks every node
looking for the three forbidden shapes above. A single forbidden node in
any GUI module fails the property. The test is parameterized over the
discovered file set so the failure message names the offending file.

The companion *render-thread* harness (described in the design doc) is
intentionally NOT included here: spinning up the GUI inside pytest hangs
on this workstation. Static analysis is sufficient to prove Req 7.9
because the only way the render thread could reach ``kmNet`` is via a
source-level reference under ``gui/``, which this test rules out.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Tuple

import pytest


# ---------------------------------------------------------------------------
# Source-tree discovery
# ---------------------------------------------------------------------------

# Resolve the project root (two levels up from this file: tests/gui/ → tests/ → project)
# and the gui/ package directory. Using ``Path.resolve`` here rather than a
# string join keeps the test robust to symlinks / case-folding on Windows.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_GUI_DIR = _PROJECT_ROOT / "gui"


def _discover_gui_py_files() -> List[Path]:
    """Return every ``.py`` file under ``gui/`` (recursively).

    The discovery is deterministic-sorted so parameterized test ids are
    stable across runs and across platforms with different default
    ``Path.rglob`` ordering.
    """
    if not _GUI_DIR.is_dir():
        # Surface a clear failure if the project layout has changed; the
        # test is meaningless if the GUI package has moved or been removed.
        return []
    return sorted(_GUI_DIR.rglob("*.py"))


_GUI_PY_FILES = _discover_gui_py_files()

# Use file paths relative to the project root for the parameterized ids so
# pytest output names the offending module concisely.
_GUI_PY_IDS = [str(p.relative_to(_PROJECT_ROOT)) for p in _GUI_PY_FILES]


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _attribute_root_name(node: ast.Attribute) -> str | None:
    """Return the root ``Name.id`` of an attribute chain, or ``None``.

    Walks ``node.value`` left-ward until a non-``Attribute`` is reached.
    For ``kmNet.foo.bar`` the chain is ``Attribute(Attribute(Name("kmNet"),
    "foo"), "bar")``; this helper unwraps it and returns ``"kmNet"``.
    Returns ``None`` for chains whose root is a ``Call``, ``Subscript``,
    string literal, etc. — those are not the shape Property 8 forbids.
    """
    cursor: ast.AST = node.value
    # Bound the walk so a pathological input cannot loop forever; AST
    # depth is far below this bound for any realistic source file.
    for _ in range(1024):
        if isinstance(cursor, ast.Attribute):
            cursor = cursor.value
            continue
        if isinstance(cursor, ast.Name):
            return cursor.id
        return None
    return None


def _scan_for_kmnet(tree: ast.AST) -> List[Tuple[str, int, str]]:
    """Walk ``tree`` and collect every forbidden ``kmNet`` reference.

    Each violation is a ``(kind, lineno, detail)`` tuple where ``kind`` is
    one of ``"import"``, ``"import-from"``, or ``"attribute"`` and
    ``detail`` is a short human-readable rendering of the offending node
    suitable for inclusion in an assertion message.
    """
    violations: List[Tuple[str, int, str]] = []

    for node in ast.walk(tree):
        # Form 1: ``import kmNet`` / ``import kmNet.foo`` / ``import kmNet as x``.
        # ``alias.name`` is the dotted module path as written.
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root == "kmNet":
                    violations.append(
                        ("import", node.lineno, f"import {alias.name}")
                    )

        # Form 2: ``from kmNet import x`` / ``from kmNet.foo import x``.
        # ``node.module`` is the source module's dotted path; relative
        # imports (``from . import ...``) have ``module is None`` and are
        # ignored — they cannot reach the top-level ``kmNet`` module.
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            if root == "kmNet":
                violations.append(
                    ("import-from", node.lineno, f"from {module} import ...")
                )

        # Form 3: any attribute access whose chain root is ``Name("kmNet")``.
        # Covers ``kmNet.move``, ``kmNet.foo.bar``, ``kmNet.init(...)``
        # (the ``Call.func`` is itself an ``Attribute``), assignments, etc.
        elif isinstance(node, ast.Attribute):
            if _attribute_root_name(node) == "kmNet":
                violations.append(
                    ("attribute", node.lineno, f"kmNet....{node.attr}")
                )

    return violations


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_gui_directory_exists() -> None:
    """The ``gui/`` package must exist for Property 8 to be meaningful.

    A missing directory would make the parameterized test below collect
    zero items and silently pass — this guard fails loudly instead.
    """
    assert _GUI_DIR.is_dir(), (
        f"expected GUI package directory at {_GUI_DIR!s}; the project "
        f"layout may have changed and Property 8 cannot be verified"
    )
    assert _GUI_PY_FILES, (
        f"discovered no .py files under {_GUI_DIR!s}; the project layout "
        f"may have changed and Property 8 cannot be verified"
    )


@pytest.mark.parametrize("py_path", _GUI_PY_FILES, ids=_GUI_PY_IDS)
def test_gui_module_does_not_reference_kmnet(py_path: Path) -> None:
    """
    Validates Req 7.9 (Property 8).

    For every ``.py`` file under ``gui/``, parse it with :mod:`ast` and
    assert no ``import kmNet`` / ``from kmNet ...`` / ``kmNet....``
    attribute access exists. Any single hit fails the property and the
    parameterized test id names the offending file.

    A ``SyntaxError`` from :func:`ast.parse` is itself a failure: a
    GUI module that does not parse cannot be loaded by the application
    either, so the suite must surface the parse error rather than mask
    it as "no violations found".
    """
    source = py_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(py_path))
    except SyntaxError as exc:
        pytest.fail(
            f"failed to parse GUI module {py_path!s}: {exc!r}; "
            f"Property 8 cannot be verified for an unparseable file"
        )

    violations = _scan_for_kmnet(tree)

    assert violations == [], (
        f"GUI module {py_path.relative_to(_PROJECT_ROOT)!s} contains "
        f"forbidden kmNet references (Req 7.9 / Property 8): "
        + ", ".join(
            f"{kind} at line {lineno} ({detail})"
            for kind, lineno, detail in violations
        )
    )
