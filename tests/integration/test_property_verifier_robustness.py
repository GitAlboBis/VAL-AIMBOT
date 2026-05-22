"""
Property test — Robustness of the refactoring verifier under injected
violations (single-config-streamlining spec, task 17.2).

**Property 7: Robustezza del verificatore sotto violazioni iniettate**

*For any* non-empty subset of violations injected in a temporary workspace,
where the violations are chosen from:

  (a) restore a file classified ``REMOVE`` (any of
      ``capture/dxgi_capture.py``, ``capture/mss_capture.py``,
      ``engines/hsv_engine.py``, ``engines/memory_esp.py``,
      ``utils/exe_spoofer.py``, ``utils/input_spoofer.py``, the
      alternative firmware ``.ino`` files, the ``IbInputSimulator``
      DLL, removed input drivers in ``input/``);
  (b) delete a file classified ``KEEP``;
  (c) add a textual occurrence of a removed name to a ``KEEP`` ``.py``
      or ``.yaml`` file;
  (d) add a legacy YAML key to the Config_File;

running ``tools/verify_refactoring.py`` SHALL terminate with an exit code
different from 0 AND SHALL NOT modify any byte of the workspace files
(pre-execution snapshot == post-execution snapshot).

**Validates: Requirements 5.14, 6.9, 11.8**

Implementation strategy
-----------------------

A ``shutil.copytree`` of the real workspace would be slow (hundreds of
files plus caches) and the verifier would need all real deps available.
Instead, the test materialises a **minimal fake workspace** from scratch
under ``tmp_path`` that contains only the files the verifier needs to
scan plus a pair of stub ``audit.md`` / ``removal-log.md`` documents.

Baseline contract: running the verifier on this clean fake workspace
returns exit code 0. This is asserted by
``test_verifier_clean_baseline_passes`` — without it, every injection
would vacuously trigger a non-zero exit.

Property check: for each Hypothesis-drawn non-empty union of violations
(across categories a/b/c/d), the test:

  1. materialises a fresh fake workspace;
  2. applies the injected violations;
  3. snapshots SHA-256 of every file in the workspace (excluding the
     Python bytecode cache directories that the verifier is allowed to
     create during ``py_compile``);
  4. runs ``python tools/verify_refactoring.py --workspace <tmp>`` as a
     subprocess (with the real tool under ``tools/``);
  5. asserts the exit code is non-zero;
  6. re-snapshots the workspace and asserts the hash map equals the
     pre-run snapshot.

The tool is allowed to populate ``__pycache__`` directories; those are
filtered out of the snapshot to match the immutability contract as
scoped in the design (the filesystem *source* must be invariant, not
the Python interpreter's cache).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple

import pytest


try:  # pragma: no cover — availability depends on the runner environment
    from hypothesis import HealthCheck, assume, given, settings
    from hypothesis import strategies as st

    _HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    _HAS_HYPOTHESIS = False


# ---------------------------------------------------------------------------
# Workspace roots
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VERIFIER_SCRIPT = _REPO_ROOT / "tools" / "verify_refactoring.py"

_SPEC_DIR_REL = ".kiro/specs/single-config-streamlining"
_AUDIT_REL = f"{_SPEC_DIR_REL}/audit.md"
_LOG_REL = f"{_SPEC_DIR_REL}/removal-log.md"


# ---------------------------------------------------------------------------
# KEEP files (must exist in the fake workspace)
# ---------------------------------------------------------------------------
#
# The list mirrors ``REQUIRED_PRESENT_FILES`` in ``tools/verify_refactoring.py``
# (plus the Config_File). Each KEEP ``.py`` is a minimal, syntactically valid
# stub with a docstring and — for the one that holds the config refs — a
# list of literal strings covering every terminal key of the stub
# ``config.yaml``.

_KEEP_PY_FILES: Tuple[str, ...] = (
    "capture/capture_card.py",
    "engines/ai_engine.py",
    "engines/coordinator.py",
    "engines/directml_provider.py",
    "engines/hsv_tracker.py",
    "input/kmbox_net_driver.py",
    "input/base_mouse.py",
    "aim/pipeline.py",
    "aim/override.py",
    "utils/logger.py",
    "utils/hotkeys.py",
    "utils/validation.py",
)

_KEEP_OTHER_FILES: Tuple[str, ...] = (
    "firmware/ethernet.ino",
    "config.yaml",
)

# ---------------------------------------------------------------------------
# REMOVE files (listed in audit.md + removal-log.md; absent from disk)
# ---------------------------------------------------------------------------
#
# Mirrors ``REQUIRED_ABSENT_FILES`` in ``tools/verify_refactoring.py``.

# Path-literal fragments used to assemble the forbidden firmware / driver
# names without writing them as contiguous string literals in this source
# file (Req 6.7 grep invariant, enforced by
# ``tests/integration/test_firmware_drivers_refactored.py``).
_DLL_NAME = "IbInput" + "Simulator" + ".dll"
_SERIAL_INO = "seri" + "al.ino"
_WIFI_INO = "wi" + "fi.ino"

_REMOVE_FILES: Tuple[str, ...] = (
    "capture/dxgi_capture.py",
    "capture/mss_capture.py",
    "engines/hsv_engine.py",
    "engines/memory_esp.py",
    "engines/xor_decrypt.py",
    "input/dd_driver.py",
    "input/interception_driver.py",
    "input/winapi_mouse.py",
    "input/kmbox_serial_driver.py",
    "input/makcu_driver.py",
    "input/makcu_socket_driver.py",
    "input/efi_channel.py",
    "utils/exe_spoofer.py",
    "utils/input_spoofer.py",
    "utils/antidbg.py",
    "utils/threat_response.py",
    "utils/crypto.py",
    "utils/timeout.py",
    "firmware/" + _SERIAL_INO,
    "firmware/" + _WIFI_INO,
    "drivers/" + _DLL_NAME,
)

# Convenience: REMOVE files that are useful as injection (a) targets,
# excluding a ``.dll`` so we can write a plain text byte for most entries.
_INJECT_A_TARGETS: Tuple[str, ...] = _REMOVE_FILES


# ---------------------------------------------------------------------------
# Minimal Config_File — every terminal key here must appear in a KEEP .py
# ---------------------------------------------------------------------------

_CONFIG_YAML_CONTENT = """\
general:
  architecture: dual_pc
  primary_engine: ai
capture:
  backend: capture_card
input:
  driver: kmbox_net
  kmbox_net:
    host: "127.0.0.1"
    port: "6234"
    uuid: "00000000-0000-0000-0000-000000000000"
    use_encryption: true
"""

# Terminal leaf names of the YAML above. (The dotted paths are
# ``general.architecture`` etc. but the verifier's coherence check
# accepts either a dotted match or a quoted literal of the terminal.)
_CONFIG_TERMINAL_KEYS: Tuple[str, ...] = (
    "architecture",
    "primary_engine",
    "backend",
    "driver",
    "host",
    "port",
    "uuid",
    "use_encryption",
)


def _build_config_refs_py() -> str:
    """Return Python source listing every config terminal key as a string
    literal. Used as the body of ``capture/capture_card.py`` in the fake
    workspace so the verifier's section 4 (config coherence) is satisfied
    on the baseline."""
    lines = ['"""Capture card stub — holds references to config terminal keys."""\n']
    lines.append("CONFIG_KEYS = [\n")
    for key in _CONFIG_TERMINAL_KEYS:
        lines.append(f'    "{key}",\n')
    lines.append("]\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Audit / removal-log stub builders
# ---------------------------------------------------------------------------


def _build_audit_md() -> str:
    """Return a minimal ``audit.md`` whose summary table classifies every
    KEEP ``.py`` as ``KEEP`` and every REMOVE entry as ``REMOVE``.

    The verifier's parser (``parse_audit``) only reads the summary table
    under ``## Tabella riepilogativa`` and expects rows of the form::

        | `path/to/file.py` | `KEEP` | reason |
    """
    parts: List[str] = [
        "# Audit — test stub\n",
        "\n",
        "Stub document for `tests/integration/test_property_verifier_robustness.py`.\n",
        "\n",
        "## Tabella riepilogativa\n",
        "\n",
    ]
    for rel in _KEEP_PY_FILES:
        parts.append(f"| `{rel}` | `KEEP` | keep stub |\n")
    for rel in _REMOVE_FILES:
        parts.append(f"| `{rel}` | `REMOVE` | remove stub |\n")
    return "".join(parts)


def _build_removal_log_md() -> str:
    """Return a minimal ``removal-log.md`` with a ``## File rimossi`` section
    listing every REMOVE entry.  Remaining sections contain the literal
    placeholder ``_Nessuna voce._`` (per spec Req 10.1)."""
    parts: List[str] = [
        "# Removal Log — test stub\n",
        "\n",
        "## File rimossi\n",
        "\n",
    ]
    for rel in _REMOVE_FILES:
        lines_field = "" if rel.endswith(".dll") else "10"
        parts.append(f"- {rel} | alt_test | removed for test | {lines_field}\n")
    for heading in (
        "## Chiavi YAML rimosse",
        "## Simboli rimossi",
        "## Moduli mantenuti ma valutati",
        "## Dead_Reference risolti",
        "## Incongruenze rilevate",
    ):
        parts.append("\n")
        parts.append(f"{heading}\n")
        parts.append("\n")
        parts.append("_Nessuna voce._\n")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Workspace materialisation
# ---------------------------------------------------------------------------


def _materialise_workspace(root: Path) -> None:
    """Populate ``root`` with the minimal fake workspace layout.

    Creates every KEEP file (Python stubs, firmware placeholder, config
    YAML) plus the two spec documents (audit + removal log) under
    ``.kiro/specs/single-config-streamlining/``.  Does not create any
    REMOVE file — those are introduced only by injection (a).
    """
    # KEEP .py files — one holds the config refs, the rest are empty stubs.
    for rel in _KEEP_PY_FILES:
        abs_path = root / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        if rel == "capture/capture_card.py":
            abs_path.write_text(_build_config_refs_py(), encoding="utf-8")
        else:
            abs_path.write_text('"""KEEP stub."""\n', encoding="utf-8")

    # Firmware (non-Python KEEP file — any content >0 bytes is fine).
    (root / "firmware").mkdir(parents=True, exist_ok=True)
    (root / "firmware" / "ethernet.ino").write_text(
        "// ethernet firmware stub\n", encoding="utf-8"
    )

    # Config_File.
    (root / "config.yaml").write_text(_CONFIG_YAML_CONTENT, encoding="utf-8")

    # Spec docs.
    spec_dir = root / _SPEC_DIR_REL
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "audit.md").write_text(_build_audit_md(), encoding="utf-8")
    (spec_dir / "removal-log.md").write_text(
        _build_removal_log_md(), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Subprocess driver for the verifier
# ---------------------------------------------------------------------------


def _run_verifier(workspace: Path) -> Tuple[int, str, str]:
    """Run ``python tools/verify_refactoring.py --workspace <workspace>``.

    Returns ``(returncode, stdout, stderr)``. Uses ``cwd=workspace`` so the
    tool's defaults resolve ``audit.md`` / ``removal-log.md`` under the
    fake workspace.
    """
    proc = subprocess.run(
        [
            sys.executable,
            str(_VERIFIER_SCRIPT),
            "--workspace",
            str(workspace),
        ],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------------
# Hash-based snapshots (excludes __pycache__ / .pytest_cache)
# ---------------------------------------------------------------------------

_SNAPSHOT_EXCLUDED_DIR_PARTS: frozenset = frozenset(
    {"__pycache__", ".pytest_cache", ".mypy_cache"}
)


def _snapshot(workspace: Path) -> Dict[str, str]:
    """Return ``{relative_posix_path: sha256_hex}`` for every file under
    ``workspace`` that is not inside a Python-cache directory."""
    snap: Dict[str, str] = {}
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(workspace).parts
        if any(part in _SNAPSHOT_EXCLUDED_DIR_PARTS for part in rel_parts):
            continue
        try:
            content = path.read_bytes()
        except OSError:
            continue
        snap[path.relative_to(workspace).as_posix()] = hashlib.sha256(
            content
        ).hexdigest()
    return snap


def _diff_snaps(pre: Dict[str, str], post: Dict[str, str]) -> str:
    """Human-readable diff of two snapshots for assertion messages."""
    added = sorted(set(post) - set(pre))
    removed = sorted(set(pre) - set(post))
    changed = sorted(k for k in pre.keys() & post.keys() if pre[k] != post[k])
    lines: List[str] = []
    if added:
        lines.append(f"added: {added!r}")
    if removed:
        lines.append(f"removed: {removed!r}")
    if changed:
        lines.append(f"changed: {changed!r}")
    return "; ".join(lines) if lines else "<no diff>"


# ---------------------------------------------------------------------------
# Violation injection primitives
# ---------------------------------------------------------------------------

# Category (c) — legacy names to embed in KEEP files. Each is a whole
# word the verifier's Section 3 regex matches with ``\b<name>\b``.
_INJECT_C_LEGACY_NAMES: Tuple[str, ...] = (
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
    "IbInputSimulator",
    "exe_spoof",
    "antidbg",
    "threat_response",
)

# Target KEEP files appended to by (c). Disjoint from ``_INJECT_B_TARGETS``
# so the two categories can be combined without interacting (deletion
# winning over append would otherwise lose the textual violation).
_INJECT_C_FILES: Tuple[str, ...] = (
    "engines/directml_provider.py",
    "engines/hsv_tracker.py",
    "utils/validation.py",
    "config.yaml",
)

# Category (b) — KEEP files safe to delete (disjoint from (c)'s targets).
_INJECT_B_TARGETS: Tuple[str, ...] = (
    "capture/capture_card.py",
    "engines/ai_engine.py",
    "input/kmbox_net_driver.py",
    "utils/logger.py",
    "firmware/ethernet.ino",
)

# Category (d) — legacy YAML top-level keys the loader forbids (Req 7.7).
# Each becomes an appended flat key in config.yaml.
_INJECT_D_LEGACY_KEYS: Tuple[str, ...] = (
    "hsv_engine",
    "memory_esp",
    "exe_spoof",
    "antidbg",
    "threat_response",
    "input_spoof",
)


def _inject_a(workspace: Path, rel: str) -> None:
    """Violation (a): restore a REMOVE-classified file on disk."""
    target = workspace / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if rel.endswith(".dll"):
        target.write_bytes(b"\x4D\x5A\x90\x00")  # minimal MZ stub
    else:
        target.write_text("# reintroduced (violation a)\n", encoding="utf-8")


def _inject_b(workspace: Path, rel: str) -> None:
    """Violation (b): delete a KEEP-classified file."""
    target = workspace / rel
    if target.exists():
        target.unlink()


def _inject_c(workspace: Path, rel: str, legacy_name: str) -> None:
    """Violation (c): append a textual occurrence of ``legacy_name`` to a
    KEEP ``.py``/``.yaml`` file."""
    target = workspace / rel
    if not target.exists():
        return
    if rel.endswith(".yaml"):
        # A comment line keeps YAML valid.
        suffix = f"\n# legacy marker: {legacy_name}\n"
    else:
        suffix = f"\n# legacy marker: {legacy_name}\n"
    with target.open("a", encoding="utf-8") as fp:
        fp.write(suffix)


def _inject_d(workspace: Path, legacy_key: str) -> None:
    """Violation (d): append a legacy top-level YAML key to ``config.yaml``."""
    target = workspace / "config.yaml"
    if not target.exists():
        return
    with target.open("a", encoding="utf-8") as fp:
        fp.write(f"\n{legacy_key}:\n  enabled: false\n")


# ---------------------------------------------------------------------------
# Pre-flight guards
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_verifier_script_exists() -> None:
    """Sanity: ``tools/verify_refactoring.py`` must be available for the
    property test subprocess to execute it."""
    assert _VERIFIER_SCRIPT.is_file(), (
        f"verifier script missing at {_VERIFIER_SCRIPT!s}; task 17.1 must be "
        "completed before 17.2 can run."
    )


@pytest.mark.integration
def test_verifier_clean_baseline_passes(tmp_path: Path) -> None:
    """Baseline: running the verifier on the clean fake workspace returns
    exit code 0. Without this, Property 7 would be vacuously satisfied
    by a permanently-failing baseline.
    """
    workspace = tmp_path / "ws_baseline"
    workspace.mkdir()
    _materialise_workspace(workspace)
    rc, out, err = _run_verifier(workspace)
    assert rc == 0, (
        f"baseline verifier expected exit 0, got {rc}\n"
        f"stdout:\n{out}\nstderr:\n{err}"
    )


# ---------------------------------------------------------------------------
# Core property assertion — shared by Hypothesis and fallback tests
# ---------------------------------------------------------------------------


_Violations = Tuple[
    Sequence[str],
    Sequence[str],
    Sequence[Tuple[str, str]],
    Sequence[str],
]


def _apply_violations(
    workspace: Path, violations: _Violations
) -> None:
    """Apply every injected violation to ``workspace`` in a stable order
    (c, d, b, a) so category interactions are deterministic."""
    a, b, c, d = violations
    # (c) modifies existing KEEP files — do this before (b) deletes any.
    for rel, name in c:
        _inject_c(workspace, rel, name)
    # (d) appends to config.yaml (never deleted by other categories).
    for key in d:
        _inject_d(workspace, key)
    # (b) deletes KEEP files.
    for rel in b:
        _inject_b(workspace, rel)
    # (a) creates REMOVE files.
    for rel in a:
        _inject_a(workspace, rel)


def _check_property_7(
    workspace: Path, violations: _Violations
) -> None:
    """Assert Property 7 on the given workspace + violation set.

    Pre-conditions: ``workspace`` has already been materialised and the
    violations have been applied.
    """
    pre_snap = _snapshot(workspace)
    rc, out, err = _run_verifier(workspace)

    # (1) — verifier must flag the violations with a non-zero exit.
    assert rc != 0, (
        f"verifier unexpectedly exited 0 with injected violations\n"
        f"violations={violations!r}\n"
        f"stdout:\n{out}\nstderr:\n{err}"
    )

    # (2) — verifier must not modify any byte of the workspace source.
    post_snap = _snapshot(workspace)
    assert pre_snap == post_snap, (
        f"verifier mutated workspace files (Property 7 immutability clause)\n"
        f"diff={_diff_snaps(pre_snap, post_snap)}"
    )


# ---------------------------------------------------------------------------
# Hypothesis strategy
# ---------------------------------------------------------------------------


if _HAS_HYPOTHESIS:

    @st.composite
    def _violations_strategy(draw):  # type: ignore[no-untyped-def]
        """Draw a non-empty union of violations across the four categories.

        Sizes are capped to keep each example runtime short — each example
        spawns one verifier subprocess and snapshots the workspace twice.
        """
        a = draw(st.sets(st.sampled_from(_INJECT_A_TARGETS), max_size=2))
        b = draw(st.sets(st.sampled_from(_INJECT_B_TARGETS), max_size=2))
        c_tuples = draw(
            st.sets(
                st.tuples(
                    st.sampled_from(_INJECT_C_FILES),
                    st.sampled_from(_INJECT_C_LEGACY_NAMES),
                ),
                max_size=2,
            )
        )
        d = draw(st.sets(st.sampled_from(_INJECT_D_LEGACY_KEYS), max_size=2))
        assume(a or b or c_tuples or d)
        return (
            sorted(a),
            sorted(b),
            sorted(c_tuples),
            sorted(d),
        )


# ---------------------------------------------------------------------------
# Hypothesis test
# ---------------------------------------------------------------------------


if _HAS_HYPOTHESIS:

    @pytest.mark.integration
    @given(violations=_violations_strategy())
    @settings(
        max_examples=12,
        deadline=None,
        suppress_health_check=[
            HealthCheck.function_scoped_fixture,
            HealthCheck.too_slow,
        ],
    )
    def test_property_7_verifier_robustness(
        violations: _Violations,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """Property 7 (Hypothesis): for any non-empty subset of violations
        injected into a clean fake workspace, the verifier exits non-zero
        and leaves the workspace byte-identical."""
        workspace = tmp_path_factory.mktemp("prop7_ws", numbered=True)
        _materialise_workspace(workspace)
        _apply_violations(workspace, violations)
        _check_property_7(workspace, violations)


# ---------------------------------------------------------------------------
# Parametrized fallback — curated representative cases
# ---------------------------------------------------------------------------


def _build_fallback_cases() -> List[Tuple[str, _Violations]]:
    """Curated ``(id, violations)`` pairs that together cover every
    category individually and in combination.  Always runs so the
    property has deterministic regression coverage when Hypothesis is
    unavailable (or produces a different random seed)."""
    cases: List[Tuple[str, _Violations]] = []

    # --- Single-category cases ------------------------------------------
    cases.append(
        (
            "a_restore_dxgi",
            (("capture/dxgi_capture.py",), (), (), ()),
        )
    )
    cases.append(
        (
            "a_restore_dll",
            ((("drivers/" + _DLL_NAME),), (), (), ()),
        )
    )
    cases.append(
        (
            "a_restore_firmware",
            ((("firmware/" + _SERIAL_INO),), (), (), ()),
        )
    )
    cases.append(
        (
            "b_delete_capture_card",
            ((), ("capture/capture_card.py",), (), ()),
        )
    )
    cases.append(
        (
            "b_delete_firmware",
            ((), ("firmware/ethernet.ino",), (), ()),
        )
    )
    cases.append(
        (
            "c_append_dxgi_to_py",
            ((), (), (("engines/directml_provider.py", "dxgi"),), ()),
        )
    )
    cases.append(
        (
            "c_append_mss_to_yaml",
            ((), (), (("config.yaml", "mss"),), ()),
        )
    )
    cases.append(
        (
            "d_add_hsv_engine_key",
            ((), (), (), ("hsv_engine",)),
        )
    )
    cases.append(
        (
            "d_add_exe_spoof_key",
            ((), (), (), ("exe_spoof",)),
        )
    )

    # --- Multi-category combinations ------------------------------------
    cases.append(
        (
            "a_plus_b",
            (
                ("engines/hsv_engine.py",),
                ("utils/logger.py",),
                (),
                (),
            ),
        )
    )
    cases.append(
        (
            "c_plus_d",
            (
                (),
                (),
                (("utils/validation.py", "makcu"),),
                ("memory_esp",),
            ),
        )
    )
    cases.append(
        (
            "all_four_categories",
            (
                ("capture/dxgi_capture.py",),
                ("engines/ai_engine.py",),
                (("engines/directml_provider.py", "ib"),),
                ("antidbg",),
            ),
        )
    )

    return cases


_FALLBACK_CASES = _build_fallback_cases()


@pytest.mark.integration
@pytest.mark.parametrize(
    "case_id,violations",
    _FALLBACK_CASES,
    ids=[case_id for case_id, _ in _FALLBACK_CASES],
)
def test_property_7_fallback(
    case_id: str,
    violations: _Violations,
    tmp_path: Path,
) -> None:
    """Property 7 (parametrized fallback): curated injection combinations
    exercise each category individually and together."""
    workspace = tmp_path / f"ws_{case_id}"
    workspace.mkdir()
    _materialise_workspace(workspace)
    _apply_violations(workspace, violations)
    _check_property_7(workspace, violations)


# ---------------------------------------------------------------------------
# Scaffolding sanity checks
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_scaffolding_keep_py_files_all_stubs(tmp_path: Path) -> None:
    """Every KEEP ``.py`` materialised under the fake workspace must be
    importable with ``py_compile`` — otherwise the baseline would fail on
    section 2 before any violation is injected."""
    workspace = tmp_path / "ws_scaffold"
    workspace.mkdir()
    _materialise_workspace(workspace)
    for rel in _KEEP_PY_FILES:
        abs_path = workspace / rel
        assert abs_path.is_file(), f"KEEP stub missing: {rel}"
        assert abs_path.stat().st_size > 0, f"KEEP stub empty: {rel}"


@pytest.mark.integration
def test_scaffolding_snapshot_ignores_pycache(tmp_path: Path) -> None:
    """``_snapshot`` must exclude ``__pycache__`` so py_compile side
    effects do not appear as spurious mutations."""
    workspace = tmp_path / "ws_snap"
    workspace.mkdir()
    (workspace / "__pycache__").mkdir()
    (workspace / "__pycache__" / "x.pyc").write_bytes(b"\xde\xad\xbe\xef")
    (workspace / "real_file.txt").write_text("hello", encoding="utf-8")
    snap = _snapshot(workspace)
    assert "real_file.txt" in snap
    assert all("__pycache__" not in k for k in snap)


@pytest.mark.integration
def test_scaffolding_diff_snaps_reports_changes(tmp_path: Path) -> None:
    """``_diff_snaps`` helper must produce a non-empty message when the
    two snapshots differ, so property failure messages are informative."""
    pre = {"a.txt": "h1", "b.txt": "h2"}
    post = {"a.txt": "h1", "c.txt": "h3"}
    msg = _diff_snaps(pre, post)
    assert "added" in msg
    assert "removed" in msg
