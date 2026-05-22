"""Integration tests for Task 6.3 of ``single-config-streamlining``.

This suite verifies the filesystem and source-level invariants that follow
the removal of alternative firmware files and the ``drivers/`` folder
(Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.7, 6.8, 6.9).

Design note — self-referential safety
-------------------------------------
Test ``test_no_forbidden_strings_in_sources`` greps every eligible source
file for the forbidden path literals defined by Req 6.7, and
``test_no_load_calls_reference_removed_artifacts`` AST-walks every ``.py``
file in the workspace. Since *this* file is a ``.py`` file inside
``tests/`` it would otherwise match itself simply by spelling the
forbidden substrings out. To avoid that (and to avoid adding
self-exclusions that would weaken the guarantee) the forbidden strings
are assembled at runtime via Python string concatenation, so the file's
source text never contains any contiguous match.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import pytest


# --- Workspace layout -----------------------------------------------------

_WORKSPACE = Path(__file__).resolve().parents[2]
_FIRMWARE_DIR = _WORKSPACE / "firmware"
_DRIVERS_DIR = _WORKSPACE / "drivers"


# --- Forbidden string construction ---------------------------------------
#
# Split into fragments so that no contiguous literal match is ever present
# in this source file (see module docstring).

_DLL_NAME = "IbInput" + "Simulator" + ".dll"
_SERIAL_INO = "seri" + "al.ino"
_WIFI_INO = "wi" + "fi.ino"

# Req 6.7 — forbidden path strings (case-insensitive substring match).
_FORBIDDEN_PATH_STRINGS: Tuple[str, ...] = (
    "drivers/" + _DLL_NAME,
    "firmware/" + _SERIAL_INO,
    "firmware/" + _WIFI_INO,
)

# Req 6.8 — forbidden substrings inside load/open call arguments.
_FORBIDDEN_LOAD_SUBSTRINGS: Tuple[str, ...] = (
    _DLL_NAME,
    _SERIAL_INO,
    _WIFI_INO,
)


# --- Scan configuration --------------------------------------------------

_EXCLUDED_DIRS: Tuple[str, ...] = (
    ".archive",
    "htmlcov",
    "__pycache__",
    ".kiro",
    ".pytest_cache",
    ".git",
)

# Files excluded from the grep scan per Task 6.3 instructions.
_EXCLUDED_SCAN_FILES: Tuple[str, ...] = (
    "audit.md",
    "removal-log.md",
)

_BAK_RE = re.compile(r"\.bak", re.IGNORECASE)
_SCAN_EXTENSIONS: Tuple[str, ...] = (".py", ".yaml", ".yml", ".md", ".ino")

# Call names whose first argument is treated as a load/open target.
_LOAD_CALL_NAMES: Tuple[str, ...] = ("WinDLL", "CDLL", "LoadLibrary", "open")
_LOAD_KW_NAMES = frozenset({"name", "file", "filename", "path"})


# --- Helpers -------------------------------------------------------------


def _is_excluded_dir(name: str) -> bool:
    return name in _EXCLUDED_DIRS or bool(_BAK_RE.search(name))


def _is_excluded_file(name: str) -> bool:
    return name in _EXCLUDED_SCAN_FILES or bool(_BAK_RE.search(name))


def _iter_scan_files() -> Iterable[Path]:
    """Yield source files under the workspace subject to the grep invariant."""
    for root, dirs, files in os.walk(_WORKSPACE):
        dirs[:] = [d for d in dirs if not _is_excluded_dir(d)]
        root_path = Path(root)
        for fname in files:
            if _is_excluded_file(fname):
                continue
            if Path(fname).suffix.lower() not in _SCAN_EXTENSIONS:
                continue
            yield root_path / fname


def _iter_python_files() -> Iterable[Path]:
    """Yield every ``.py`` file in the workspace (respecting dir exclusions)."""
    for root, dirs, files in os.walk(_WORKSPACE):
        dirs[:] = [d for d in dirs if not _is_excluded_dir(d)]
        root_path = Path(root)
        for fname in files:
            if _BAK_RE.search(fname):
                continue
            if Path(fname).suffix.lower() == ".py":
                yield root_path / fname


def _read_text_safe(path: Path) -> Optional[str]:
    for encoding in ("utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, OSError):
            continue
    return None


def _static_string_value(node: ast.AST) -> Optional[str]:
    """Fold simple string-literal expressions (``Constant``, ``+`` of literals,
    f-strings composed only of constants) into a Python ``str``. Returns
    ``None`` for anything non-static."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string_value(node.left)
        right = _static_string_value(node.right)
        if left is not None and right is not None:
            return left + right
        return None
    if isinstance(node, ast.JoinedStr):
        parts: List[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                return None
        return "".join(parts)
    return None


def _called_name(func: ast.AST) -> Optional[str]:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _iter_load_call_args(tree: ast.AST) -> Iterable[Tuple[str, int]]:
    """Yield ``(literal_value, lineno)`` for every call that names a
    load/open function and whose first positional argument — or any
    ``name=``/``file=``/``filename=``/``path=`` keyword — is a statically
    resolvable string."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node.func)
        if name not in _LOAD_CALL_NAMES:
            continue
        candidates: List[ast.AST] = []
        if node.args:
            candidates.append(node.args[0])
        for kw in node.keywords:
            if kw.arg in _LOAD_KW_NAMES:
                candidates.append(kw.value)
        for candidate in candidates:
            literal = _static_string_value(candidate)
            if literal is not None:
                yield literal, getattr(node, "lineno", 0)


# --- Filesystem invariants (Req 6.1, 6.2, 6.3, 6.4, 6.5) -----------------


@pytest.mark.integration
def test_firmware_ethernet_ino_exists():
    """Req 6.1: ``firmware/ethernet.ino`` must exist."""
    path = _FIRMWARE_DIR / "ethernet.ino"
    assert path.is_file(), f"expected {path} to exist and be a regular file"


@pytest.mark.integration
def test_firmware_alternative_ino_files_removed():
    """Req 6.2 & 6.3: the two alternative firmware ``.ino`` files must be absent.

    The forbidden file names are reconstructed from fragments so this
    test's own source does not contain a contiguous match against the
    Req 6.7 grep invariant enforced by
    ``test_no_forbidden_path_strings_in_sources``.
    """
    serial_path = _FIRMWARE_DIR / _SERIAL_INO
    wifi_path = _FIRMWARE_DIR / _WIFI_INO
    assert not serial_path.exists(), (
        f"alternative firmware {serial_path.name!r} must be removed "
        f"from {_FIRMWARE_DIR}"
    )
    assert not wifi_path.exists(), (
        f"alternative firmware {wifi_path.name!r} must be removed "
        f"from {_FIRMWARE_DIR}"
    )


@pytest.mark.integration
def test_firmware_contains_exactly_one_ino_file():
    """Req 6.1: ``firmware/`` must hold exactly one ``.ino`` file (case-insensitive)
    and that file must be ``ethernet.ino``."""
    assert _FIRMWARE_DIR.is_dir(), f"{_FIRMWARE_DIR} must exist and be a directory"
    ino_files = [
        entry
        for entry in _FIRMWARE_DIR.iterdir()
        if entry.is_file() and entry.suffix.lower() == ".ino"
    ]
    assert len(ino_files) == 1, (
        f"firmware/ must contain exactly one .ino file, found {len(ino_files)}: "
        f"{[p.name for p in ino_files]!r}"
    )
    assert ino_files[0].name.lower() == "ethernet.ino", (
        f"the single .ino file in firmware/ must be ethernet.ino (case-insensitive); "
        f"found {ino_files[0].name!r}"
    )


@pytest.mark.integration
def test_drivers_dll_removed():
    """Req 6.4: the removed driver DLL (path reconstructed via ``_DRIVERS_DIR``
    and ``_DLL_NAME``) must not exist."""
    dll_path = _DRIVERS_DIR / _DLL_NAME
    assert not dll_path.exists(), f"{dll_path} must be removed"


@pytest.mark.integration
def test_drivers_folder_absent_or_empty():
    """Req 6.5: the ``drivers/`` folder either must not exist or must contain
    no files and no subfolders."""
    if not _DRIVERS_DIR.exists():
        return
    assert _DRIVERS_DIR.is_dir(), (
        f"{_DRIVERS_DIR} exists but is not a directory"
    )
    entries = list(_DRIVERS_DIR.iterdir())
    assert entries == [], (
        "drivers/ must be empty or absent; found: "
        f"{[entry.name for entry in entries]!r}"
    )


# --- Source invariants (Req 6.7, 6.8, 6.9) -------------------------------


@pytest.mark.integration
def test_no_forbidden_path_strings_in_sources():
    """Req 6.7: no source file with extension ``.py|.yaml|.yml|.md|.ino``
    (excluding ``audit.md``, ``removal-log.md``, ``*.bak*``, ``.archive/``,
    ``htmlcov/``, ``__pycache__/``, ``.kiro/``) may contain the forbidden
    path literals as a case-insensitive substring."""
    offending: List[Tuple[str, str, int]] = []
    for file_path in _iter_scan_files():
        text = _read_text_safe(file_path)
        if text is None:
            continue
        lowered = text.lower()
        rel = file_path.relative_to(_WORKSPACE).as_posix()
        for needle in _FORBIDDEN_PATH_STRINGS:
            idx = lowered.find(needle.lower())
            if idx != -1:
                line_no = text.count("\n", 0, idx) + 1
                offending.append((rel, needle, line_no))
    assert offending == [], (
        "Forbidden path strings found in source files (Req 6.7):\n"
        + "\n".join(
            f"  {rel} (line {line}): contains {needle!r}"
            for rel, needle, line in offending
        )
    )


@pytest.mark.integration
def test_no_load_calls_reference_removed_artifacts():
    """Req 6.8: no ``.py`` file may contain a call to ``ctypes.WinDLL``,
    ``ctypes.CDLL``, ``ctypes.LoadLibrary`` or ``open`` whose literal
    argument contains the removed-artifact substrings defined in
    ``_FORBIDDEN_LOAD_SUBSTRINGS`` (case-insensitive)."""
    offending: List[Tuple[str, int, str, str]] = []
    for file_path in _iter_python_files():
        source = _read_text_safe(file_path)
        if source is None:
            continue
        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            # Syntactically broken files are out of scope for this
            # invariant — other tests guard against their presence.
            continue
        rel = file_path.relative_to(_WORKSPACE).as_posix()
        for literal, line_no in _iter_load_call_args(tree):
            lowered_literal = literal.lower()
            for needle in _FORBIDDEN_LOAD_SUBSTRINGS:
                if needle.lower() in lowered_literal:
                    offending.append((rel, line_no, needle, literal))
    assert offending == [], (
        "Load/open calls referencing removed artifacts (Req 6.8):\n"
        + "\n".join(
            f"  {rel} (line {line}): {needle!r} appears in literal {literal!r}"
            for rel, line, needle, literal in offending
        )
    )
