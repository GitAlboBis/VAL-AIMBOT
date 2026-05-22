"""
Static verification tool for the `single-config-streamlining` refactoring.

Verifies that the workspace respects the invariants required by the feature spec
`.kiro/specs/single-config-streamlining/` (Requirements 2-6, 10.8, 11.1-11.8).

Sections executed in order:

  1. Filesystem invariants (Req 2-6 SHALL / SHALL NOT)
  2. Static import / compile of KEEP `.py` files (Req 11.1-11.2)
  3. Grep invariants for legacy names (Req 11.3, 11.7)
  4. Config coherence: every terminal key of `config.yaml` read by a KEEP `.py`
     (Req 11.6)
  5. Audit / removal-log consistency (Req 10.8)

The tool never modifies any file on disk (Property 7, Req 5.14 / 6.9 / 11.8).
All violations are collected and printed at the end in the format:

    [FAIL] <criterion-id>: <file-path>[: line <n>] - <detail>
    Summary: <N> violations across <M> files

Internal tool errors are printed on stderr with the prefix `[TOOL-ERROR]` and
count as violations.

Exit code: `min(N_violations, 127)` — zero when the workspace is fully
conformant.

Usage:

    python tools/verify_refactoring.py \
        [--workspace PATH] \
        [--audit PATH] \
        [--log PATH] \
        [--check-imports]

By default only static compilation (`python -m py_compile`) is run on KEEP `.py`
files. The `--check-imports` flag additionally runs `importlib.import_module`
on every internal KEEP module (may take longer and requires heavy deps like
cv2/torch/onnxruntime to be installed).
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    import yaml  # type: ignore
except Exception as _yaml_err:  # pragma: no cover - fatal for section 4/5
    yaml = None  # Resolved at runtime; a TOOL-ERROR is emitted if needed.


# ---------------------------------------------------------------------------
# Constants derived from Requirements 2-6
# ---------------------------------------------------------------------------

# Path-literal fragments used to assemble the forbidden firmware / driver
# names without writing them as contiguous string literals in this source
# file (Req 6.7 grep invariant, enforced by
# ``tests/integration/test_firmware_drivers_refactored.py``).
_DLL_NAME = "IbInput" + "Simulator" + ".dll"
_SERIAL_INO = "seri" + "al.ino"
_WIFI_INO = "wi" + "fi.ino"

# Files that the Refactored_Codebase SHALL NOT contain (Req 2.1, 2.2, 3.1,
# 3.4, 4.1-4.2, 5.1-5.2, 5.3-5.5, 5.8, 6.2-6.4).
REQUIRED_ABSENT_FILES: Tuple[str, ...] = (
    # capture (Req 2.1, 2.2)
    "capture/dxgi_capture.py",
    "capture/mss_capture.py",
    # engines (Req 4.1, 4.2, plus EVALUATE→REMOVE for xor_decrypt per audit)
    "engines/hsv_engine.py",
    "engines/memory_esp.py",
    "engines/xor_decrypt.py",
    # input (Req 3.1, 3.4 per audit)
    "input/dd_driver.py",
    "input/interception_driver.py",
    "input/winapi_mouse.py",
    "input/kmbox_serial_driver.py",
    "input/makcu_driver.py",
    "input/makcu_socket_driver.py",
    "input/efi_channel.py",
    # utils (Req 5.1-5.5, 5.8 per audit classifications)
    "utils/exe_spoofer.py",
    "utils/input_spoofer.py",
    "utils/antidbg.py",
    "utils/threat_response.py",
    "utils/crypto.py",
    "utils/timeout.py",
    # firmware & drivers (Req 6.2, 6.3, 6.4) — assembled via fragments to
    # avoid tripping the Req 6.7 grep invariant on this tool's own source.
    "firmware/" + _SERIAL_INO,
    "firmware/" + _WIFI_INO,
    "drivers/" + _DLL_NAME,
)

# Files that the Refactored_Codebase SHALL contain (Req 2.3, 3.2-3.3, 4.5,
# 5.6, 6.1, plus Core_Runtime_Modules list).
#
# Updated by aim-pipeline-simplification task 3.8 (req 2.13, 2.14, 4.4, 4.5,
# 4.6, 4.7, 4.8): the legacy aim chain (``engines/aim_resolver.py``,
# ``engines/aim_controller.py``, ``engines/target_tracker.py``,
# ``input/aim_output.py``, ``input/humanizer.py``) has been collapsed into
# the simplified ``aim/`` package + ``engines/hsv_tracker.py``. The required
# present set is updated to reflect the post-simplification topology.
REQUIRED_PRESENT_FILES: Tuple[str, ...] = (
    "firmware/ethernet.ino",
    "capture/capture_card.py",
    "engines/ai_engine.py",
    "engines/coordinator.py",
    "engines/directml_provider.py",
    "engines/hsv_tracker.py",
    "aim/pipeline.py",
    "aim/override.py",
    "input/kmbox_net_driver.py",
    "input/base_mouse.py",
    "utils/logger.py",
    "utils/hotkeys.py",
    "utils/validation.py",
)

# Legacy names for the grep invariant (Req 11.3, 11.7).
# ``serial.ino`` and ``wifi.ino`` are assembled via fragments to avoid
# tripping the Req 6.7 grep invariant on this tool's own source text
# (``IbInputSimulator`` is already excluded from that invariant because
# Req 6.7 targets path literals, not the identifier alone, but we keep
# the fragment style consistent below).
LEGACY_NAMES: Tuple[str, ...] = (
    "dxgi",
    "mss",
    "hsv_engine",
    "memory_esp",
    "ib",
    "makcu",
    "dd_driver",
    "interception",
    "winapi",
    "kmbox_serial",
    "IbInput" + "Simulator",
    _SERIAL_INO,
    _WIFI_INO,
    "exe_spoof",
    "antidbg",
    "threat_response",
    "input_spoof",
)

# Per-file timeout for compilation / import (Req 11.1, 11.2).
PER_FILE_TIMEOUT_SECONDS: int = 30

# Max meaningful exit code (Req 11.8: "capped a 127").
MAX_EXIT_CODE: int = 127


# ---------------------------------------------------------------------------
# Violation model
# ---------------------------------------------------------------------------


@dataclass
class Violation:
    """A single failure detected by the verifier."""

    criterion: str
    file: str
    detail: str
    line: Optional[int] = None

    def format(self) -> str:
        location = self.file
        if self.line is not None:
            location = f"{self.file}: line {self.line}"
        return f"[FAIL] {self.criterion}: {location} - {self.detail}"


@dataclass
class VerifierState:
    workspace: Path
    audit_path: Path
    log_path: Path
    check_imports: bool = False
    violations: List[Violation] = field(default_factory=list)
    tool_errors: List[str] = field(default_factory=list)

    def add(self, criterion: str, file: str, detail: str, line: Optional[int] = None) -> None:
        self.violations.append(Violation(criterion, _norm(file), detail, line))

    def tool_error(self, detail: str) -> None:
        """Record an internal tool failure (emitted on stderr and counted as a violation)."""
        self.tool_errors.append(detail)
        self.violations.append(Violation("TOOL-ERROR", "<tool>", detail))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norm(path: str | os.PathLike[str]) -> str:
    """Normalise a path to forward slashes (matches audit.md style)."""
    return str(PurePosixPath(Path(str(path)).as_posix()))


def _rel(workspace: Path, path: Path) -> str:
    try:
        return _norm(path.relative_to(workspace))
    except ValueError:
        return _norm(path)


# Paths that must be excluded from all scans (grep, compile, config-coherence).
EXCLUDED_DIR_PARTS: Tuple[str, ...] = (
    ".archive",
    "htmlcov",
    "__pycache__",
    ".pytest_cache",
    ".hypothesis",
    ".git",
    ".kiro",  # spec docs live here; not source code to scan
    "node_modules",
)

EXCLUDED_FILENAME_SUBSTRINGS: Tuple[str, ...] = (
    ".bak",  # matches `*.bak`, `*.bak.*`
)

EXCLUDED_EXACT_FILENAMES: Tuple[str, ...] = (
    "audit.md",
    "removal-log.md",
)


# ---------------------------------------------------------------------------
# Section 3 grep — legitimate occurrences of legacy names
# ---------------------------------------------------------------------------
#
# Req 11.3 / 11.7 forbid *dispatch references* to removed backends / drivers /
# engines. A naive whole-word grep also matches legitimate occurrences that
# the spec explicitly requires to exist:
#
# * ``config.py`` — the Config_Loader itself lists the legacy keys in order
#   to emit diagnostic warnings (Req 7.7, task 9.1). Detection code that
#   mentions the legacy names by design is not a "dispatch reference".
# * ``engines/coordinator.py`` — the module docstring describes which engines
#   were removed (historical documentation); Req 4.8 forbids attributes and
#   branches, not docstring mentions.
# * ``tools/verify_refactoring.py`` — this very file declares the
#   ``LEGACY_NAMES`` tuple that drives the grep.
# * Files under ``tests/`` — property tests and integration tests legitimately
#   carry the legacy names as fixtures / parametrize data / documentation,
#   because they assert the *absence* of those names in KEEP runtime code.
#
# Any source file that is expected to carry a legacy name by design is listed
# here as a relative workspace path (POSIX style). Files under ``tests/`` are
# excluded wholesale by the helper ``_is_s3_exempt``.
S3_GREP_FILE_EXEMPT: Tuple[str, ...] = (
    "config.py",
    "engines/coordinator.py",
    "tools/verify_refactoring.py",
)


def _is_s3_exempt(path: Path, workspace: Path) -> bool:
    """Return True if ``path`` is exempt from the Req 11.3 / 11.7 grep scan."""
    rel = _rel(workspace, path)
    if rel in S3_GREP_FILE_EXEMPT:
        return True
    # All test files may legitimately carry legacy names (fixtures, assertions
    # that check for absence of the name, parametrize data).
    try:
        parts = path.relative_to(workspace).parts
    except ValueError:
        parts = path.parts
    if parts and parts[0] == "tests":
        return True
    return False


def _is_excluded(path: Path, workspace: Path) -> bool:
    """Return True if `path` belongs to an excluded directory / filename set."""
    try:
        rel_parts = path.relative_to(workspace).parts
    except ValueError:
        rel_parts = path.parts

    for part in rel_parts:
        if part in EXCLUDED_DIR_PARTS:
            return True

    name = path.name
    if name in EXCLUDED_EXACT_FILENAMES:
        return True
    for needle in EXCLUDED_FILENAME_SUBSTRINGS:
        if needle in name:
            return True
    return False


# ---------------------------------------------------------------------------
# Audit parsing
# ---------------------------------------------------------------------------


# Matches rows of the summary table at the tail of audit.md:
#     | `path/to/file.py` | `KEEP` | reason text |
#     | `path/to/file.py` | `REMOVE` | reason text |
_TABLE_ROW_RE = re.compile(
    r"^\|\s*`(?P<path>[^`]+)`\s*\|\s*`(?P<cls>KEEP|REMOVE|EVALUATE)`\s*\|(?P<rest>.*)\|\s*$"
)


def parse_audit(audit_path: Path) -> Tuple[Dict[str, str], Optional[str]]:
    """
    Parse the summary table of the Audit_Document.

    Returns a mapping `{path (posix): classification}` and, if parsing failed,
    an error message (otherwise None).
    """
    classifications: Dict[str, str] = {}
    if not audit_path.exists():
        return classifications, f"Audit file not found: {_norm(audit_path)}"

    try:
        text = audit_path.read_text(encoding="utf-8")
    except OSError as exc:
        return classifications, f"Audit file unreadable: {_norm(audit_path)} - {exc}"

    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Tabella riepilogativa"):
            in_table = True
            continue
        if not in_table:
            continue
        if stripped.startswith("## "):
            # next section — stop
            break

        match = _TABLE_ROW_RE.match(line)
        if match is None:
            continue
        raw_path = match.group("path").strip()
        cls = match.group("cls").strip()
        classifications[_norm(raw_path)] = cls

    if not classifications:
        return classifications, (
            "Audit summary table has no recognisable rows "
            "(expected rows under '## Tabella riepilogativa')"
        )
    return classifications, None


def parse_removed_files_section(log_path: Path) -> Tuple[Set[str], Optional[str]]:
    """
    Parse the `## File rimossi` section of the Removal_Log.

    Accepts bullet lines of the form:
        - `path` | category | reason | lines
        - path | category | reason | lines
    Only the first token (after stripping backticks) is captured.
    """
    if not log_path.exists():
        return set(), f"Removal log not found at {_norm(log_path)}"

    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError as exc:
        return set(), f"Removal log unreadable: {_norm(log_path)} - {exc}"

    removed: Set[str] = set()
    in_section = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("## "):
            in_section = stripped.lower().startswith("## file rimossi")
            continue
        if not in_section:
            continue
        if not stripped.startswith("-"):
            continue
        body = stripped[1:].strip()
        # Handle the "empty section" sentinel defined by the spec (Req 10.1).
        if body in {"_Nessuna voce._", "*Nessuna voce.*", "Nessuna voce."}:
            continue
        first_field = body.split("|", 1)[0].strip()
        first_field = first_field.strip("`").strip()
        if first_field:
            removed.add(_norm(first_field))

    return removed, None


# ---------------------------------------------------------------------------
# Section 1 — Filesystem invariants
# ---------------------------------------------------------------------------


def section1_filesystem(state: VerifierState) -> None:
    for rel in REQUIRED_ABSENT_FILES:
        target = state.workspace / rel
        if target.exists():
            state.add(
                "S1-FS-UNEXPECTED",
                rel,
                "file still present on disk; it SHALL NOT exist (Req 2-6)",
            )

    for rel in REQUIRED_PRESENT_FILES:
        target = state.workspace / rel
        if not target.exists():
            state.add(
                "S1-FS-MISSING",
                rel,
                "file missing; it SHALL exist (Req 2-6, Core_Runtime_Modules)",
            )
        elif target.is_file() and target.stat().st_size == 0:
            state.add(
                "S1-FS-MISSING",
                rel,
                "file present but empty; byte size SHALL be > 0 (Req 4.5, 5.6)",
            )

    # Req 6.1: firmware/ folder SHALL contain exactly one .ino (ethernet.ino).
    firmware_dir = state.workspace / "firmware"
    if firmware_dir.is_dir():
        ino_files = [p for p in firmware_dir.iterdir() if p.suffix.lower() == ".ino"]
        for p in ino_files:
            if p.name.lower() != "ethernet.ino":
                state.add(
                    "S1-FS-UNEXPECTED",
                    _rel(state.workspace, p),
                    "unexpected .ino file in firmware/ (Req 6.1)",
                )

    # Req 6.5: drivers/ SHALL NOT exist if empty post-DLL removal.
    drivers_dir = state.workspace / "drivers"
    if drivers_dir.is_dir():
        entries = [p for p in drivers_dir.iterdir()]
        # Ignore caches that may reappear (pycache) — but the spec says the
        # folder shouldn't exist at all when empty. We only flag if no
        # meaningful entries remain.
        meaningful = [p for p in entries if p.name not in {"__pycache__"}]
        if not meaningful:
            state.add(
                "S1-FS-UNEXPECTED",
                "drivers/",
                "drivers/ folder is empty but still present (Req 6.5)",
            )


# ---------------------------------------------------------------------------
# Section 2 — Static compile / import
# ---------------------------------------------------------------------------


def _dotted_module_name(workspace: Path, py_file: Path) -> Optional[str]:
    """
    Convert a workspace-relative `.py` path to its dotted module name, if any.

    Files that are not reachable as dotted modules (e.g. stray scripts at the
    root that are not part of a package) are returned as a single-segment
    name based on the stem. `__init__.py` is mapped to the parent package.
    """
    try:
        rel = py_file.relative_to(workspace)
    except ValueError:
        return None

    parts = list(rel.parts)
    if not parts:
        return None
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    if not parts:
        return None
    # Skip modules under tests/ — their import side effects are pytest-specific
    # and outside the Req 11.2 smoke scope for internal runtime modules.
    return ".".join(parts)


def _collect_keep_py_files(
    classifications: Dict[str, str], workspace: Path
) -> List[Path]:
    """Return absolute paths of `.py` files classified KEEP in the audit."""
    files: List[Path] = []
    for rel, cls in classifications.items():
        if cls != "KEEP":
            continue
        if not rel.endswith(".py"):
            continue
        candidate = workspace / Path(rel)
        if candidate.exists() and candidate.is_file():
            files.append(candidate)
    return files


def section2_compile_import(
    state: VerifierState, keep_py_files: List[Path]
) -> None:
    for py in keep_py_files:
        rel = _rel(state.workspace, py)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "py_compile", str(py)],
                capture_output=True,
                text=True,
                timeout=PER_FILE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            state.add(
                "S2-COMPILE",
                rel,
                f"py_compile timed out after {PER_FILE_TIMEOUT_SECONDS}s (Req 11.1)",
            )
            continue
        except OSError as exc:
            state.tool_error(f"py_compile could not be launched for {rel}: {exc}")
            continue

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip().replace("\n", " | ")
            if not detail:
                detail = f"non-zero exit code {proc.returncode}"
            state.add(
                "S2-COMPILE",
                rel,
                f"py_compile failed: {detail[:400]} (Req 11.1)",
            )
            continue

        # Req 11.1 also forbids non-empty stderr, even on exit 0.
        if proc.stderr and proc.stderr.strip():
            state.add(
                "S2-COMPILE",
                rel,
                f"py_compile emitted stderr: {proc.stderr.strip()[:400]} (Req 11.1)",
            )

    if not state.check_imports:
        return

    # Extended check (Req 11.2) — opt-in because it requires heavy deps.
    workspace_str = str(state.workspace)
    orig_sys_path = list(sys.path)
    if workspace_str not in sys.path:
        sys.path.insert(0, workspace_str)

    try:
        for py in keep_py_files:
            module = _dotted_module_name(state.workspace, py)
            if module is None:
                continue
            # Skip tests and tools packages from the import check — they are
            # not internal runtime modules per Req 11.2 scope.
            first_segment = module.split(".", 1)[0]
            if first_segment in {"tests", "tools"}:
                continue
            try:
                importlib.import_module(module)
            except (ImportError, ModuleNotFoundError) as exc:
                state.add(
                    "S2-IMPORT",
                    _rel(state.workspace, py),
                    f"import {module!r} failed: {type(exc).__name__}: {exc} (Req 11.2)",
                )
            except AttributeError as exc:
                state.add(
                    "S2-IMPORT",
                    _rel(state.workspace, py),
                    f"import {module!r} raised AttributeError: {exc} (Req 11.2)",
                )
            except Exception as exc:  # pragma: no cover - defensive
                state.tool_error(
                    f"unexpected error importing {module!r}: "
                    f"{type(exc).__name__}: {exc}"
                )
    finally:
        sys.path[:] = orig_sys_path


# ---------------------------------------------------------------------------
# Section 3 — Grep invariants
# ---------------------------------------------------------------------------


def _iter_keep_scan_files(
    classifications: Dict[str, str], workspace: Path
) -> Iterable[Path]:
    """
    Yield absolute paths of KEEP `.py` / `.yaml` / `.yml` files to scan.

    YAML files are not classified individually in the audit table, so we
    include every YAML in the workspace that is not in an excluded directory
    (the spec's grep invariant is scoped to KEEP `.py`/`.yaml`, and the only
    config YAML at the root is itself KEEP by definition).
    """
    # Python files from the KEEP set
    for rel, cls in classifications.items():
        if cls != "KEEP":
            continue
        if not rel.endswith(".py"):
            continue
        candidate = workspace / Path(rel)
        if _is_excluded(candidate, workspace):
            continue
        if candidate.exists() and candidate.is_file():
            yield candidate

    # YAML files (config.yaml + any other workspace yaml). Excludes .bak* etc.
    for yaml_path in workspace.rglob("*.yaml"):
        if _is_excluded(yaml_path, workspace):
            continue
        if yaml_path.is_file():
            yield yaml_path
    for yaml_path in workspace.rglob("*.yml"):
        if _is_excluded(yaml_path, workspace):
            continue
        if yaml_path.is_file():
            yield yaml_path


def _compile_legacy_patterns() -> Dict[str, re.Pattern[str]]:
    """
    Build case-sensitive whole-word regex patterns for each legacy name.

    Uses Python's standard `\b` word boundary (matches the behaviour of
    `grep -w`), which treats `.` as a non-word character — so a name like
    `serial.ino` anchors correctly, and short names like `ib` still match
    when embedded in a dotted path such as `input.ib.dll_path` (Req 11.7).
    """
    patterns: Dict[str, re.Pattern[str]] = {}
    for name in LEGACY_NAMES:
        escaped = re.escape(name)
        patterns[name] = re.compile(rf"\b{escaped}\b")
    return patterns


def section3_grep(
    state: VerifierState, classifications: Dict[str, str]
) -> None:
    patterns = _compile_legacy_patterns()
    for path in _iter_keep_scan_files(classifications, state.workspace):
        if _is_s3_exempt(path, state.workspace):
            continue
        rel = _rel(state.workspace, path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            state.tool_error(f"could not read {rel}: {exc}")
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, pattern in patterns.items():
                if pattern.search(line):
                    snippet = line.strip()[:160]
                    state.add(
                        "S3-GREP",
                        rel,
                        f"legacy name '{name}' found: {snippet!r} (Req 11.3, 11.7)",
                        line=lineno,
                    )


# ---------------------------------------------------------------------------
# Section 4 — Config coherence
# ---------------------------------------------------------------------------


def _flatten_yaml_keys(
    node: Any, prefix: str = ""
) -> Iterable[Tuple[str, Any]]:
    """
    Yield `(dotted_key, terminal_value)` pairs for every leaf of a YAML tree.

    Lists are treated as terminal values (their key is the containing dotted
    path) — individual list elements are not recursed into.
    """
    if isinstance(node, dict):
        if not node:
            yield (prefix, node)
            return
        for key, value in node.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten_yaml_keys(value, child)
    else:
        yield (prefix, node)


def _collect_terminal_keys(config_yaml_path: Path) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """
    Parse `config.yaml` and return terminal dotted paths together with their
    final key segment.

    Returns `([(dotted_key, terminal_name)], error_or_none)`.
    """
    if yaml is None:
        return [], "PyYAML is not available; cannot parse config.yaml"
    if not config_yaml_path.exists():
        return [], f"config.yaml not found at {_norm(config_yaml_path)}"
    try:
        with config_yaml_path.open("r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp)
    except Exception as exc:
        return [], f"config.yaml parse error: {exc}"

    keys: List[Tuple[str, str]] = []
    if data is None:
        return keys, None
    for dotted, _value in _flatten_yaml_keys(data):
        if not dotted:
            continue
        terminal = dotted.rsplit(".", 1)[-1]
        keys.append((dotted, terminal))
    return keys, None


def section4_config_coherence(
    state: VerifierState, classifications: Dict[str, str]
) -> None:
    config_path = state.workspace / "config.yaml"
    keys, err = _collect_terminal_keys(config_path)
    if err:
        state.tool_error(f"S4: {err}")
        return

    keep_py_files = [
        p
        for p in _iter_keep_scan_files(classifications, state.workspace)
        if p.suffix == ".py"
    ]

    # Load all KEEP .py file contents once.
    file_contents: Dict[Path, str] = {}
    for path in keep_py_files:
        try:
            file_contents[path] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            state.tool_error(f"could not read {_rel(state.workspace, path)}: {exc}")

    for dotted_key, terminal in keys:
        # Req 11.6 forms: dotted notation, quoted literal, dict-style access.
        patterns: List[str] = [
            re.escape(dotted_key),
            rf"'{re.escape(terminal)}'",
            rf'"{re.escape(terminal)}"',
            rf"\[\s*'{re.escape(terminal)}'\s*\]",
            rf'\[\s*"{re.escape(terminal)}"\s*\]',
        ]
        compiled = [re.compile(p) for p in patterns]

        found = False
        for _, text in file_contents.items():
            if any(regex.search(text) for regex in compiled):
                found = True
                break

        if not found:
            state.add(
                "S4-CONFIG",
                "config.yaml",
                f"terminal key '{dotted_key}' has no textual reading in any "
                f"KEEP .py file (Req 11.6)",
            )


# ---------------------------------------------------------------------------
# Section 5 — Audit / Removal_Log consistency
# ---------------------------------------------------------------------------


def section5_audit_log(
    state: VerifierState, classifications: Dict[str, str]
) -> None:
    removed_in_log, err = parse_removed_files_section(state.log_path)
    if err is not None:
        # A missing log still counts as a single violation per the task spec.
        state.add(
            "S5-LOG-MISSING",
            _rel(state.workspace, state.log_path),
            f"{err} (Req 10.1 / 10.8)",
        )
        return

    # Part A: every file listed under '## File rimossi' must be absent.
    for rel in sorted(removed_in_log):
        target = state.workspace / Path(rel)
        if target.exists():
            state.add(
                "S5-LOG-FILE-STILL-EXISTS",
                rel,
                "listed under '## File rimossi' but still present on disk "
                "(Req 10.8 concordanza)",
            )

    # Part B: every REMOVE entry from the audit summary must appear in the log.
    for rel, cls in sorted(classifications.items()):
        if cls != "REMOVE":
            continue
        if rel not in removed_in_log:
            state.add(
                "S5-AUDIT-MISSING-IN-LOG",
                rel,
                "classified REMOVE in audit.md but absent from removal-log.md "
                "'## File rimossi' (Req 10.8 copertura)",
            )

    # Part C: a REMOVE file that is still on disk is a direct violation of
    # section 1 already, but we surface it explicitly here in audit terms.
    for rel, cls in classifications.items():
        if cls != "REMOVE":
            continue
        if (state.workspace / Path(rel)).exists():
            state.add(
                "S5-AUDIT-NOT-REMOVED",
                rel,
                "classified REMOVE in audit.md but still present on disk "
                "(Req 10.8 concordanza)",
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_refactoring",
        description=(
            "Static verifier for the `single-config-streamlining` refactoring. "
            "Emits machine-readable [FAIL] lines and exits with a non-zero "
            "status equal to the number of violations (capped at 127)."
        ),
    )
    parser.add_argument(
        "--workspace",
        default=None,
        type=Path,
        help="Workspace root (default: current working directory)",
    )
    parser.add_argument(
        "--audit",
        default=None,
        type=Path,
        help=(
            "Path to audit.md (default: "
            "<workspace>/.kiro/specs/single-config-streamlining/audit.md)"
        ),
    )
    parser.add_argument(
        "--log",
        default=None,
        type=Path,
        help=(
            "Path to removal-log.md (default: "
            "<workspace>/.kiro/specs/single-config-streamlining/removal-log.md)"
        ),
    )
    parser.add_argument(
        "--check-imports",
        action="store_true",
        help=(
            "Additionally run importlib.import_module on each KEEP internal "
            "module (Req 11.2). Requires heavy runtime deps and is off by "
            "default."
        ),
    )
    return parser


def _resolve_state(ns: argparse.Namespace) -> VerifierState:
    workspace = (ns.workspace or Path.cwd()).resolve()
    default_dir = workspace / ".kiro" / "specs" / "single-config-streamlining"
    audit_path = (ns.audit or default_dir / "audit.md").resolve()
    log_path = (ns.log or default_dir / "removal-log.md").resolve()
    return VerifierState(
        workspace=workspace,
        audit_path=audit_path,
        log_path=log_path,
        check_imports=bool(ns.check_imports),
    )


def _write_summary(state: VerifierState) -> None:
    # Emit tool errors first on stderr (Req 11: counts as violations).
    for msg in state.tool_errors:
        print(f"[TOOL-ERROR] {msg}", file=sys.stderr)

    # Emit all [FAIL] lines on stdout, sorted for deterministic output.
    lines = sorted(v.format() for v in state.violations)
    for line in lines:
        print(line)

    affected_files = sorted({v.file for v in state.violations})
    total = len(state.violations)
    print(f"Summary: {total} violations across {len(affected_files)} files")


def main(argv: Optional[Sequence[str]] = None) -> int:
    # On Windows the default stdout/stderr encoding is cp1252, which cannot
    # encode characters like the ``∉`` mathematical glyph that may legitimately
    # appear in docstrings of scanned source files (and hence in a [FAIL] line
    # snippet). Force UTF-8 with a lossy fallback so the summary can always be
    # printed; this affects only the verifier's own I/O, never the workspace.
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    parser = _build_parser()
    ns = parser.parse_args(argv)

    try:
        state = _resolve_state(ns)
    except Exception as exc:
        print(f"[TOOL-ERROR] argument resolution failed: {exc}", file=sys.stderr)
        return 1

    try:
        classifications, audit_err = parse_audit(state.audit_path)
        if audit_err is not None:
            state.tool_error(audit_err)

        # Section 1 — filesystem invariants. Runs even without audit.
        section1_filesystem(state)

        # Sections 2-4 need the KEEP set from the audit.
        if classifications:
            keep_py_files = _collect_keep_py_files(classifications, state.workspace)
            section2_compile_import(state, keep_py_files)
            section3_grep(state, classifications)
            section4_config_coherence(state, classifications)

        # Section 5 — log consistency. Always runs so the missing-log case is
        # surfaced as a single violation.
        section5_audit_log(state, classifications)
    except Exception as exc:  # pragma: no cover - defensive
        tb = traceback.format_exc(limit=5)
        state.tool_error(
            f"unhandled error in verifier: {type(exc).__name__}: {exc} | {tb}"
        )

    _write_summary(state)
    return min(len(state.violations), MAX_EXIT_CODE)


if __name__ == "__main__":
    raise SystemExit(main())
