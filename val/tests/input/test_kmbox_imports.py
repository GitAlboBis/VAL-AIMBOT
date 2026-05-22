"""
Static import-graph scan for ``input/kmbox_net_driver.py`` — Task 9.2.

**Validates: Requirements 2.1, 2.2**

Req 2.1 mandates that every device command is routed through the vendor
``kmNet`` Python module; Req 2.2 forbids any reference to ``serial``,
``pyserial``, COM-port, or named-pipe transports anywhere in the driver
module. Both clauses are structural — they constrain the driver's import
graph, not its runtime behaviour — so the cleanest way to enforce them is
a static AST scan that runs as part of the test suite.

The scan walks every ``ast.Import`` / ``ast.ImportFrom`` node in the
driver source and asserts:

  1. No imported module name contains any of the banned tokens (``serial``,
     ``pyserial``, ``com_port``, ``named_pipe``). The check is
     case-insensitive and matches as a substring so spellings such as
     ``Serial`` (Windows-flavoured), ``serial.tools.list_ports``, or a
     hypothetical ``win32_named_pipe`` shim all fail the assertion.
  2. ``importlib.import_module`` is invoked at least once with the literal
     string ``"kmNet"``. This is how the driver lazy-loads the vendor
     module (see ``_ensure_kmnet`` in the driver source); requiring at
     least one such call confirms ``kmNet`` is the transport module the
     driver actually reaches for, even though it is never imported via a
     top-level ``import kmNet`` statement.

The test deliberately avoids importing ``input.kmbox_net_driver`` at
module level — parsing the source as text means the scan runs even when
the vendor ``kmNet.pyd`` is absent on the test machine (the common case
on CI / non-Windows hosts).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


# Tokens forbidden anywhere in an imported module name (Req 2.2).
# Matching is case-insensitive substring so that ``Serial``, ``pyserial``,
# ``serial.tools.list_ports``, or a hypothetical ``com_port_shim`` /
# ``win_named_pipe`` module all fail the assertion.
_BANNED_TOKENS: tuple[str, ...] = (
    "serial",
    "pyserial",
    "com_port",
    "named_pipe",
)


# Resolve the driver path from this test file's location so the scan
# works regardless of the directory pytest is invoked from. Layout:
#   <repo>/input/kmbox_net_driver.py
#   <repo>/tests/input/test_kmbox_imports.py
_DRIVER_PATH = (
    Path(__file__).resolve().parent.parent.parent / "input" / "kmbox_net_driver.py"
)


@pytest.fixture(scope="module")
def driver_ast() -> ast.AST:
    """
    Parse ``input/kmbox_net_driver.py`` once per module.

    Reading the source as text (rather than ``import``-ing the module)
    keeps the scan independent of the vendor ``kmNet.pyd`` being
    installed — important because the driver's lazy-import contract
    (``_ensure_kmnet``) only touches ``kmNet`` at runtime.
    """
    assert _DRIVER_PATH.is_file(), (
        f"driver source not found at {_DRIVER_PATH}"
    )
    source = _DRIVER_PATH.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(_DRIVER_PATH))


def _iter_imported_names(tree: ast.AST):
    """
    Yield every (lineno, module_name) pair in the AST.

    Covers both forms:

      - ``import a, b.c``                    →  ``"a"``, ``"b.c"``
      - ``from x.y import z``                →  ``"x.y"``
      - ``from . import sibling``            →  ``""`` (relative root)

    The ``from`` form yields the *source* module (the part after
    ``from``), not the imported attribute names — that is the level at
    which transport modules would be introduced.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            yield node.lineno, node.module or ""


def test_no_serial_or_named_pipe_imports(driver_ast: ast.AST) -> None:
    """
    Req 2.2 — no ``serial`` / ``pyserial`` / ``com_port`` / ``named_pipe``
    module is imported by the KmBox Net driver.

    Walks every ``ast.Import`` / ``ast.ImportFrom`` node and asserts the
    module name does not contain any banned token (case-insensitive
    substring match). Examples that WOULD fail this test:

      * ``import serial``
      * ``import pyserial``
      * ``from serial.tools import list_ports``
      * ``import win_com_port_shim``
      * ``from os import named_pipe``  (hypothetical)
    """
    offenders: list[tuple[int, str, str]] = []
    for lineno, module_name in _iter_imported_names(driver_ast):
        lower = module_name.lower()
        for token in _BANNED_TOKENS:
            if token in lower:
                offenders.append((lineno, module_name, token))

    assert offenders == [], (
        "Req 2.2 violation: banned transport import(s) found in "
        f"{_DRIVER_PATH.name}: "
        + ", ".join(
            f"line {ln}: {mod!r} contains {tok!r}"
            for ln, mod, tok in offenders
        )
    )


def test_kmnet_is_only_transport_module_referenced(driver_ast: ast.AST) -> None:
    """
    Req 2.1 — ``kmNet`` is the (only) transport module the driver routes
    device commands through.

    The driver loads the vendor module lazily via
    ``importlib.import_module('kmNet')`` rather than a top-level
    ``import kmNet``, so the scan must look at the literal-string
    argument of ``import_module`` calls instead of (or in addition to)
    the AST's ``Import`` / ``ImportFrom`` nodes.

    Two assertions:

      1. At least one ``importlib.import_module("kmNet")`` invocation
         exists in the source — confirming the driver does reach for
         the vendor module.
      2. No other ``importlib.import_module(...)`` invocation in the
         driver targets a module with a known transport-y name token
         (``serial`` / ``pyserial`` / ``com_port`` / ``named_pipe``).
         This is the dynamic-dispatch counterpart to
         ``test_no_serial_or_named_pipe_imports`` — covers the case
         where someone tries to sneak ``importlib.import_module('serial')``
         past the static-import scan.
    """
    import_module_calls: list[tuple[int, str]] = []
    for node in ast.walk(driver_ast):
        if not isinstance(node, ast.Call):
            continue
        # Match ``importlib.import_module(...)`` (Attribute call) and the
        # bare ``import_module(...)`` form (Name call) for completeness.
        func = node.func
        is_import_module = False
        if isinstance(func, ast.Attribute) and func.attr == "import_module":
            is_import_module = True
        elif isinstance(func, ast.Name) and func.id == "import_module":
            is_import_module = True
        if not is_import_module:
            continue
        # Only string-literal arguments are scannable. Non-literal
        # arguments (variables, f-strings) would defeat any static scan
        # and should not exist in this driver — the test fails loudly
        # on them so a future refactor cannot smuggle in a runtime-
        # computed transport module name.
        if not node.args:
            continue
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            import_module_calls.append((node.lineno, first_arg.value))
        else:
            pytest.fail(
                f"line {node.lineno}: importlib.import_module called with a "
                "non-literal argument; static transport-graph scan cannot "
                "verify Req 2.1 / 2.2 against dynamic module names."
            )

    # 1. kmNet must be referenced as a dynamically-imported transport.
    kmnet_calls = [c for c in import_module_calls if c[1] == "kmNet"]
    assert kmnet_calls, (
        "Req 2.1 violation: no ``importlib.import_module('kmNet')`` call "
        f"found in {_DRIVER_PATH.name}; the driver must route device "
        "commands through the vendor kmNet module."
    )

    # 2. No other dynamic import targets a banned transport.
    banned_dynamic: list[tuple[int, str, str]] = []
    for lineno, mod in import_module_calls:
        lower = mod.lower()
        for token in _BANNED_TOKENS:
            if token in lower:
                banned_dynamic.append((lineno, mod, token))
    assert banned_dynamic == [], (
        "Req 2.2 violation: banned dynamic transport import(s) found in "
        f"{_DRIVER_PATH.name}: "
        + ", ".join(
            f"line {ln}: import_module({mod!r}) contains {tok!r}"
            for ln, mod, tok in banned_dynamic
        )
    )
