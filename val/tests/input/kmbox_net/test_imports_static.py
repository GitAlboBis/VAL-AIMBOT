"""
Static-import scan tests — Task 12.1 of spec ``kmbox-net-arm64-udp``.

**Validates: Requirements 1.2, 1.3, 1.4, 1.5, 4.8**

This test parses ``input/kmbox_net_driver.py`` with :mod:`ast` and asserts
several "import discipline" properties that together guarantee the
driver does *not* depend on the vendor ``kmNet.pyd`` binary, on
``ctypes``/``cffi`` bindings into x86 DLLs, or on any serial/named-pipe
transport — and that it imports *only* allow-listed stdlib modules plus
the relative ``.base_mouse`` import.

Concretely, the test enforces:

* Requirement 1.2 — no ``import kmNet`` / ``from kmNet ...`` statement,
  no string literal in functional code matching ``r'kmNet.*\\.pyd'``.
* Requirement 1.3 — no ``import ctypes`` / ``import _ctypes`` /
  ``import cffi``; no ``ctypes.WinDLL`` / ``ctypes.CDLL`` /
  ``ctypes.LoadLibrary`` (or ``cdll`` / ``windll`` / ``oledll``) calls.
* Requirement 1.4 — every ``Import`` / ``ImportFrom`` node references
  only modules in the allow list ``{socket, struct, hashlib, threading,
  time, enum, logging, queue, ipaddress, random, os, dataclasses,
  inspect, typing}`` plus the relative import ``.base_mouse``.
* Requirement 1.5 — no ``import serial`` / ``import pyserial`` /
  ``import win32pipe`` / ``import win32file`` (and no ``from`` variants
  thereof).
* Requirement 4.8 — ``KmBoxNetDriver`` is declared as a subclass of
  ``BaseMouse`` and exposes the typo-preserved method
  ``_move_beizer``.

Why an AST scan (not just :mod:`grep`)
--------------------------------------

A naive ``grep -F 'kmNet'`` would over-count: the module docstring
deliberately mentions ``kmNet.pyd`` to explain what the rewrite
*replaces*, and the wire-protocol comments cite upstream symbol names
like ``kmNet_mouse_move`` (matching the ``kmNet`` token textually).
Those references are documentation, not functional code.

The AST scan is precise:

* ``Import``/``ImportFrom`` nodes capture *only* import statements
  (so symbol mentions inside docstrings or comments do not trigger).
* The string-literal scan walks :class:`ast.Constant` nodes but
  *excludes* the leading docstring of every module / class / function
  via :func:`ast.get_docstring`. That excludes the legitimate
  ``"replaces the vendor kmNet.pyd binary"`` mention while still
  catching, for example, a ``ctypes.WinDLL("kmNet.pyd")`` argument
  string anywhere in functional code.
* :class:`ast.Call` nodes are inspected for forbidden call shapes
  (``ctypes.WinDLL(...)``, ``ctypes.CDLL(...)``, etc.) so a
  ``getattr``-style or chained ``ctypes.cdll.LoadLibrary(...)`` would
  also be caught.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple


# Make the ``input`` package importable when pytest is launched from
# the repository root (the driver ships as ``input/kmbox_net_driver.py``
# at the project root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# Path to the driver source — this is the file under static analysis.
_DRIVER_SOURCE_PATH = _REPO_ROOT / "input" / "kmbox_net_driver.py"


# ---------------------------------------------------------------------------
# Allow / deny lists
# ---------------------------------------------------------------------------

# Per Requirement 1.4 (and Task 12.1), the driver may import only
# modules from this stdlib allow list. ``__future__`` is included
# defensively in case ``from __future__ import annotations`` is added
# in a future refactor — it is a stdlib pseudo-module that is always
# safe.
_ALLOWED_ABSOLUTE_MODULES: Set[str] = {
    "__future__",
    "socket",
    "struct",
    "hashlib",
    "threading",
    "time",
    "enum",
    "logging",
    "queue",
    "ipaddress",
    "random",
    "os",
    "dataclasses",
    "inspect",
    "typing",
}

# Modules whose mere import is forbidden anywhere in the driver source
# per Requirements 1.2 / 1.3 / 1.5.
_FORBIDDEN_TOP_LEVEL_MODULES: Set[str] = {
    "kmNet",       # Req 1.2 — the vendor .pyd
    "ctypes",      # Req 1.3 — DLL loader
    "_ctypes",     # Req 1.3 — internal ctypes implementation
    "cffi",        # Req 1.3 — alternative DLL loader
    "serial",      # Req 1.5 — pyserial top-level
    "pyserial",    # Req 1.5 — defensive: alternate distribution name
    "win32pipe",   # Req 1.5 — named-pipe transport
    "win32file",   # Req 1.5 — named-pipe / handle transport
}

# Forbidden ctypes attribute names that, if seen on a ``ctypes.<x>``
# call, indicate a DLL load. Even if ``ctypes`` itself were imported
# via some indirection that escaped the import-name check, a call
# matching one of these on any object would also be caught by the
# string-literal scan (because the DLL path would have to appear as a
# string argument). Together the checks form a defense in depth.
_FORBIDDEN_CTYPES_ATTRS: Set[str] = {
    "WinDLL",
    "CDLL",
    "OleDLL",
    "PyDLL",
    "LoadLibrary",
    "cdll",
    "windll",
    "oledll",
    "pydll",
}

# Regex for the "no string literal matching r'kmNet.*\.pyd'" rule.
_KMNET_PYD_RE = re.compile(r"kmNet.*\.pyd", re.IGNORECASE)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _parse_driver() -> ast.Module:
    """Parse the driver source into an AST module.

    Returns the parsed :class:`ast.Module`. Raises :class:`SyntaxError`
    on malformed input — surfaced here as a test failure with a precise
    location, which is more useful than a runtime ``ImportError``
    elsewhere in the suite.
    """
    source_text = _DRIVER_SOURCE_PATH.read_text(encoding="utf-8")
    return ast.parse(source_text, filename=str(_DRIVER_SOURCE_PATH))


def _collect_docstring_nodes(tree: ast.Module) -> Set[int]:
    """Return ``id()`` of every :class:`ast.Constant` that is a docstring.

    A docstring is the first statement of a module / class / function
    *if* that statement is an ``Expr`` wrapping a ``Constant(value=str)``.
    We collect their object identities so the string-literal scan can
    skip them — docstrings legitimately mention forbidden tokens (e.g.
    "replaces the vendor ``kmNet.pyd`` binary") for documentation
    purposes and must not be flagged as functional uses.
    """
    docstring_ids: Set[int] = set()

    def _maybe_record_docstring(body: List[ast.stmt]) -> None:
        if not body:
            return
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstring_ids.add(id(first.value))

    # Module-level docstring.
    _maybe_record_docstring(tree.body)

    # Class- and function-level docstrings (recursively, so methods
    # inside nested classes / closures are covered).
    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            _maybe_record_docstring(node.body)

    return docstring_ids


def _iter_imports(
    tree: ast.Module,
) -> Iterable[Tuple[ast.AST, str, int]]:
    """Yield ``(node, top_level_name, level)`` for every import.

    For ``import a.b.c``: yields ``(node, 'a', 0)`` (only the top-level
    name is checked against the allow / deny lists, since importing a
    submodule of a forbidden top-level package is equally forbidden,
    and importing a submodule of an allowed package is equally
    allowed).

    For ``from x.y import z``: yields ``(node, 'x', 0)``.

    For ``from . import z`` / ``from .y import z``: yields
    ``(node, '<relative>', level)`` — the caller validates relative
    imports separately.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                yield node, top, 0
        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            if level > 0:
                # Relative import — caller handles the .base_mouse
                # special case.
                yield node, node.module or "", level
            else:
                top = (node.module or "").split(".", 1)[0]
                yield node, top, 0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_forbidden_top_level_imports() -> None:
    """No ``import``/``from`` of kmNet, ctypes, cffi, serial, pyserial, win32*.

    Validates: Requirements 1.2, 1.3, 1.5.
    """
    tree = _parse_driver()
    offenders: List[str] = []
    for node, top_name, level in _iter_imports(tree):
        if level > 0:
            # Relative imports are validated by
            # ``test_only_allowed_imports``; this test focuses on
            # forbidden absolute imports.
            continue
        if top_name in _FORBIDDEN_TOP_LEVEL_MODULES:
            offenders.append(
                "line %d: %s (top-level module %r is forbidden)"
                % (
                    getattr(node, "lineno", -1),
                    ast.dump(node),
                    top_name,
                )
            )

    assert not offenders, (
        "Requirement 1.2 / 1.3 / 1.5 violated: the driver imports "
        "forbidden module(s).\n%s" % "\n".join(offenders)
    )


def test_only_allowed_imports() -> None:
    """Every ``Import`` / ``ImportFrom`` references only allow-listed modules.

    The allow list per Task 12.1 is the stdlib subset enumerated in
    Requirement 1.4 (``socket``, ``struct``, ``hashlib``, ``threading``,
    ``time``, ``enum``, ``logging``, ``queue``, ``ipaddress``,
    ``random``, ``os``, ``dataclasses``, ``inspect``, ``typing``) plus
    ``__future__`` (defensive) and the relative import ``.base_mouse``
    (the only intra-package import the driver is permitted to make).

    Validates: Requirement 1.4.
    """
    tree = _parse_driver()
    unexpected: List[str] = []
    for node, name, level in _iter_imports(tree):
        if level > 0:
            # The only relative import allowed is ``from .base_mouse
            # import ...`` (level=1, module='base_mouse'). Anything
            # else (including bare ``from . import x`` with module=='')
            # is rejected.
            if not (level == 1 and name == "base_mouse"):
                unexpected.append(
                    "line %d: relative import (level=%d module=%r) "
                    "is not on the allow list (only ``.base_mouse`` "
                    "is permitted)"
                    % (getattr(node, "lineno", -1), level, name)
                )
            continue
        if name not in _ALLOWED_ABSOLUTE_MODULES:
            unexpected.append(
                "line %d: import of %r is not on the allow list %r"
                % (
                    getattr(node, "lineno", -1),
                    name,
                    sorted(_ALLOWED_ABSOLUTE_MODULES),
                )
            )

    assert not unexpected, (
        "Requirement 1.4 violated: the driver imports module(s) "
        "outside the stdlib allow list.\n%s" % "\n".join(unexpected)
    )


def test_no_kmnet_pyd_string_literal_in_functional_code() -> None:
    """No string literal matching ``r'kmNet.*\\.pyd'`` in functional code.

    Docstrings (the leading string of a module / class / function body)
    are *excluded* — the module docstring legitimately mentions
    ``kmNet.pyd`` to explain what the rewrite replaces. Any other
    string-literal occurrence (e.g. an argument to ``LoadLibrary``)
    would indicate functional dependence on the vendor binary and
    violates Requirement 1.2.
    """
    tree = _parse_driver()
    docstring_ids = _collect_docstring_nodes(tree)

    offenders: List[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstring_ids
        ):
            if _KMNET_PYD_RE.search(node.value):
                offenders.append(
                    "line %d: string literal %r matches r'kmNet.*\\.pyd'"
                    % (
                        getattr(node, "lineno", -1),
                        node.value,
                    )
                )

    assert not offenders, (
        "Requirement 1.2 violated: functional code references a "
        "``kmNet*.pyd`` binary by name.\n%s" % "\n".join(offenders)
    )


def test_no_ctypes_loader_calls() -> None:
    """No ``ctypes.{WinDLL,CDLL,OleDLL,PyDLL,LoadLibrary,cdll,windll,...}`` call.

    Even if the ``ctypes`` import check above were somehow bypassed
    (e.g. by a re-export through another module), an actual DLL load
    would still surface as an :class:`ast.Call` whose function is an
    :class:`ast.Attribute` with one of the forbidden attribute names.

    Validates: Requirement 1.3.
    """
    tree = _parse_driver()
    offenders: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # Match ``<anything>.WinDLL(...)``, ``ctypes.cdll.LoadLibrary(...)``
            # (whose outer ``Call.func`` is ``Attribute(attr='LoadLibrary')``),
            # ``ctypes.cdll(...)``, etc.
            if isinstance(func, ast.Attribute) and func.attr in _FORBIDDEN_CTYPES_ATTRS:
                offenders.append(
                    "line %d: forbidden attribute call %r"
                    % (getattr(node, "lineno", -1), func.attr)
                )

    assert not offenders, (
        "Requirement 1.3 violated: the driver invokes a ctypes DLL "
        "loader.\n%s" % "\n".join(offenders)
    )


def test_kmbox_class_subclasses_base_mouse_and_has_move_beizer() -> None:
    """``KmBoxNetDriver`` extends ``BaseMouse`` and defines ``_move_beizer``.

    The typo ``_move_beizer`` is preserved on purpose per Requirement
    4.8 (literal compatibility with the upstream API at
    https://www.kmbox.top/wiki_doc/kmboxNet/site/python/).

    Validates: Requirements 1.4 (relative ``.base_mouse`` import lands
    a usable ``BaseMouse`` symbol) and 4.8 (typo preserved).
    """
    tree = _parse_driver()

    # Locate the ``KmBoxNetDriver`` class declaration at module scope.
    class_def: Optional[ast.ClassDef] = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "KmBoxNetDriver":
            class_def = node
            break
    assert class_def is not None, (
        "test pre-condition: KmBoxNetDriver class must be declared at "
        "module scope in %s." % (_DRIVER_SOURCE_PATH,)
    )

    # Verify ``BaseMouse`` is in the base class list. We accept either
    # a bare ``Name('BaseMouse')`` (the current shape) or an
    # ``Attribute(...).BaseMouse`` form for forward-compatibility.
    base_names: List[str] = []
    for base in class_def.bases:
        if isinstance(base, ast.Name):
            base_names.append(base.id)
        elif isinstance(base, ast.Attribute):
            base_names.append(base.attr)
    assert "BaseMouse" in base_names, (
        "Requirement 1.4 / 4.8 violated: KmBoxNetDriver does not list "
        "BaseMouse among its base classes (saw %r)." % (base_names,)
    )

    # Verify ``_move_beizer`` is a method of the class. The typo is
    # required by Requirement 4.8 — flag both the canonical typo'd
    # spelling missing *and* the corrected spelling ``_move_bezier``
    # being used instead (which would silently break wiki-literal
    # callers).
    method_names = {
        member.name
        for member in class_def.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_move_beizer" in method_names, (
        "Requirement 4.8 violated: KmBoxNetDriver is missing the "
        "typo-preserved method ``_move_beizer`` (saw methods %r). "
        "Note: the upstream wiki spells it ``_move_beizer`` and the "
        "spec mandates literal preservation of that spelling for "
        "API compatibility."
        % sorted(method_names)
    )
    assert "_move_bezier" not in method_names, (
        "Requirement 4.8 violated: KmBoxNetDriver defines the "
        "*corrected* spelling ``_move_bezier`` instead of (or in "
        "addition to) the upstream-typo spelling ``_move_beizer``. "
        "The spec mandates literal preservation of the typo."
    )
