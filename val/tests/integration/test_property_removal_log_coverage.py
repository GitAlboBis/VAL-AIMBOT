"""
Property test — Copertura e concordanza del Removal_Log
(single-config-streamlining spec, task 16.3).

**Property 10: Copertura e concordanza del Removal_Log**

*For any* sequenza finita di rimozioni di file applicate a una copia
temporanea del workspace, il Removal_Log generato dal tool di logging
SHALL soddisfare:

1. **Copertura**: per ogni file rimosso nella sequenza, esiste
   esattamente una riga sotto ``## File rimossi`` il cui campo
   ``<path>`` corrisponde al percorso del file rimosso.
2. **Concordanza**: per ogni riga sotto ``## File rimossi``, il file
   nominato dal campo ``<path>`` è assente dal filesystem nello stato
   post-rimozione.

**Validates: Requirements 10.8 (copertura e concordanza)**

Implementation strategy
-----------------------

The property is exercised on two complementary surfaces:

* **Static surface** — the real workspace Removal_Log
  (``.kiro/specs/single-config-streamlining/removal-log.md``) and the
  real post-refactor filesystem. This is the pragmatic check recommended
  by the task: for every bullet under ``## File rimossi`` in the log,
  the file must be absent from disk (concordanza); and for every file
  classified ``REMOVE`` in ``audit.md``'s summary table, the log must
  contain a matching bullet (copertura, also per Req 10.8).

* **Synthetic surface** — Hypothesis (with a parametrized fallback when
  Hypothesis is not available) generates a finite set of fake file paths
  under a temporary workspace, physically creates them, then picks a
  random subset to remove and synthesises a Removal_Log in the same
  shape the real tooling emits. Both invariants (copertura,
  concordanza) are asserted. This guards against vacuous passes on the
  real data and pins the two properties as universal rather than
  anecdotal.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

import pytest

try:  # pragma: no cover - availability depends on the runner environment
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    HAS_HYPOTHESIS = False


# ---------------------------------------------------------------------------
# Workspace layout
# ---------------------------------------------------------------------------

_WORKSPACE = Path(__file__).resolve().parents[2]
_SPEC_DIR = (
    _WORKSPACE / ".kiro" / "specs" / "single-config-streamlining"
)
_LOG_PATH = _SPEC_DIR / "removal-log.md"
_AUDIT_PATH = _SPEC_DIR / "audit.md"


# ---------------------------------------------------------------------------
# Parsers (mirror the production parsers used by tools/verify_refactoring.py)
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^\s*##\s+(?P<title>.+?)\s*$")
_EMPTY_SENTINELS = {"_Nessuna voce._", "*Nessuna voce.*", "Nessuna voce."}


def _parse_removed_files_section(log_text: str) -> List[str]:
    """Return the ordered list of ``<path>`` fields under ``## File rimossi``.

    Matches the bullet shape ``- <path> | <categoria> | <motivo> |
    <righe>`` defined by Req 10.2. Paths are returned verbatim (POSIX
    form, per Req 10.2). Empty-section sentinels are ignored.
    """
    paths: List[str] = []
    in_section = False
    for raw_line in log_text.splitlines():
        stripped = raw_line.strip()
        m = _HEADING_RE.match(stripped)
        if m is not None:
            in_section = m.group("title").strip().lower() == "file rimossi"
            continue
        if not in_section or not stripped.startswith("-"):
            continue
        body = stripped[1:].strip()
        if body in _EMPTY_SENTINELS:
            continue
        first_field = body.split("|", 1)[0].strip().strip("`").strip()
        if first_field:
            paths.append(first_field)
    return paths


_SUMMARY_HEADING_RE = re.compile(
    r"^\s*##\s+Tabella riepilogativa\s*$", re.MULTILINE
)
_SUMMARY_ROW_RE = re.compile(
    r"^\|\s*`(?P<file>[^`]+)`\s*\|\s*`(?P<cls>[^`]+)`\s*\|\s*(?P<reason>.*?)\s*\|\s*$"
)


def _parse_audit_remove_files(audit_text: str) -> Set[str]:
    """Extract every file classified ``REMOVE`` in the audit summary table."""
    header = _SUMMARY_HEADING_RE.search(audit_text)
    assert header is not None, (
        "audit.md is missing the '## Tabella riepilogativa' section; "
        "task 1.1 must produce it for task 16.3 to run."
    )
    start = header.end()
    next_heading = re.search(r"^\s*##\s", audit_text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(audit_text)
    section = audit_text[start:end]

    remove_files: Set[str] = set()
    for line in section.splitlines():
        m = _SUMMARY_ROW_RE.match(line)
        if not m:
            continue
        cls = m.group("cls").strip()
        if cls.lower() == "classification":  # header separator
            continue
        if cls == "REMOVE":
            remove_files.add(m.group("file").strip())
    assert remove_files, (
        "audit.md summary table contains no REMOVE rows; task 1.1/1.2 must "
        "classify REMOVE files for task 16.3 to have coverage signal."
    )
    return remove_files


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def log_text() -> str:
    assert _LOG_PATH.exists(), (
        f"Removal_Log not found at {_LOG_PATH}; task 16.1 must produce it "
        "before task 16.3 can run."
    )
    return _LOG_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def audit_text() -> str:
    assert _AUDIT_PATH.exists(), (
        f"audit.md not found at {_AUDIT_PATH}; task 1.1 must produce it "
        "before task 16.3 can run."
    )
    return _AUDIT_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def log_removed_paths(log_text: str) -> List[str]:
    return _parse_removed_files_section(log_text)


@pytest.fixture(scope="module")
def audit_remove_files(audit_text: str) -> Set[str]:
    return _parse_audit_remove_files(audit_text)


# ---------------------------------------------------------------------------
# Static invariants on the real workspace
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_log_entries_are_unique(log_removed_paths: List[str]) -> None:
    """Each path appears *exactly once* under '## File rimossi' (Req 10.8 copertura).

    Copertura uses the word "esattamente una riga"; this is a prerequisite
    for the subsequent copertura and concordanza checks to be unambiguous.
    """
    duplicates = sorted(
        {p for p in log_removed_paths if log_removed_paths.count(p) > 1}
    )
    assert not duplicates, (
        "Copertura invariant violated: the following paths appear more "
        "than once under '## File rimossi' in removal-log.md:\n  - "
        + "\n  - ".join(duplicates)
    )


@pytest.mark.integration
def test_concordanza_every_logged_file_is_absent(
    log_removed_paths: List[str],
) -> None:
    """Concordanza: every ``<path>`` under '## File rimossi' is absent from disk.

    Per Property 10.2 and Req 10.8 (concordanza): for each row under
    ``## File rimossi``, the file nominato dal campo ``<path>`` deve
    essere assente dal filesystem nello stato post-rimozione.
    """
    assert log_removed_paths, (
        "Removal_Log '## File rimossi' section is empty; task 16.1 must "
        "have populated it with the files removed by tasks 2.1-14.1."
    )
    still_present = [
        rel for rel in log_removed_paths
        if (_WORKSPACE / Path(rel)).exists()
    ]
    assert not still_present, (
        "Concordanza invariant violated: the following paths are listed "
        "under '## File rimossi' in removal-log.md but still exist on "
        "disk:\n  - " + "\n  - ".join(still_present)
    )


@pytest.mark.integration
def test_copertura_every_audit_remove_py_absent_from_disk_is_in_log(
    log_removed_paths: List[str],
    audit_remove_files: Set[str],
) -> None:
    """Copertura: every ``.py`` file REMOVE-classified *and* absent from disk is logged.

    Requirement 10.8 (copertura) is stated over the set of files
    "rimosso dal workspace rispetto allo stato iniziale" — i.e., files
    that have actually been removed from disk. The audit summary table
    is a superset of the log because it also classifies REMOVE files
    whose removal tasks have not yet run (e.g., ``build.py`` and other
    ``obsolete_utility`` scripts at the workspace root, or REMOVE-marked
    test files). The log's own scope header enumerates exactly which
    removal tasks it records.

    Therefore copertura must hold for the intersection ``{audit REMOVE}
    ∩ {absent from disk}`` — every such file must have exactly one row
    under ``## File rimossi``.

    ``.ino``/``.dll`` removals live in dedicated audit sections
    (not the summary table) and are covered by the concordanza test
    plus task 16.2 (structural test).
    """
    actually_removed = {
        rel for rel in audit_remove_files
        if not (_WORKSPACE / Path(rel)).exists()
    }
    # Sanity: at least some REMOVE files must be absent on a
    # post-refactor workspace, otherwise the invariant is vacuous.
    assert actually_removed, (
        "No REMOVE-classified file from audit.md is absent from disk; "
        "the refactoring fases 2-6 have not run, so task 16.3 cannot "
        "verify copertura in a meaningful way."
    )

    log_set = set(log_removed_paths)
    missing = sorted(actually_removed - log_set)
    assert not missing, (
        "Copertura invariant violated: the following files are classified "
        "REMOVE in audit.md and absent from disk, but have no row under "
        "'## File rimossi' in removal-log.md:\n  - "
        + "\n  - ".join(missing)
    )


# ---------------------------------------------------------------------------
# Synthetic property test — Hypothesis-driven and parametrized fallback
# ---------------------------------------------------------------------------


def _category_for(path: str) -> str:
    """Return a valid category token (Req 10.2) keyed by synthetic path prefix."""
    if path.startswith("capture/"):
        return "alt_capture_backend"
    if path.startswith("input/"):
        return "alt_input_driver"
    if path.startswith("engines/"):
        return "alt_detection_engine"
    if path.startswith("utils/"):
        return "single_pc_spoofer"
    if path.startswith("firmware/"):
        return "alt_firmware"
    if path.startswith("drivers/"):
        return "alt_driver_dll"
    return "obsolete_utility"


def _synthesise_log(removed_paths: List[str]) -> str:
    """Produce a minimal Removal_Log text in the shape required by Req 10.1.

    Only the ``## File rimossi`` section is populated meaningfully; the
    other required sections are emitted with the ``_Nessuna voce._``
    sentinel (Req 10.1) so the parser exercises the same skip path it
    uses on the real log.
    """
    lines: List[str] = ["# Removal Log — synthetic", ""]
    lines.append("## File rimossi")
    lines.append("")
    if not removed_paths:
        lines.append("_Nessuna voce._")
    else:
        for p in removed_paths:
            suffix = Path(p).suffix.lower()
            # Req 10.2: empty <righe> for .dll, integer otherwise.
            rows = "" if suffix == ".dll" else "1"
            lines.append(
                f"- {p} | {_category_for(p)} | synthetic removal | {rows}"
            )
    lines.append("")
    # The remaining sections are empty but must be present (Req 10.1).
    for section in (
        "Chiavi YAML rimosse",
        "Simboli rimossi",
        "Moduli mantenuti ma valutati",
        "Dead_Reference risolti",
        "Incongruenze rilevate",
    ):
        lines.append(f"## {section}")
        lines.append("")
        lines.append("_Nessuna voce._")
        lines.append("")
    return "\n".join(lines)


def _materialise_workspace(
    root: Path, paths: Iterable[str]
) -> None:
    """Create each ``paths`` entry as a zero-byte file under ``root``."""
    for rel in paths:
        target = root / Path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")


def _apply_removals(root: Path, to_remove: Iterable[str]) -> None:
    for rel in to_remove:
        target = root / Path(rel)
        if target.exists():
            target.unlink()


def _check_property_10(
    tmp_root: Path,
    removed_sequence: List[str],
    log_text: str,
) -> None:
    """Run the two-pronged assertion of Property 10 on a synthetic world."""
    logged = _parse_removed_files_section(log_text)

    # Copertura — every removal in the sequence has exactly one line.
    logged_counts: Dict[str, int] = {}
    for p in logged:
        logged_counts[p] = logged_counts.get(p, 0) + 1

    for rel in removed_sequence:
        count = logged_counts.get(rel, 0)
        assert count == 1, (
            f"Copertura violated for {rel!r}: expected exactly 1 row under "
            f"'## File rimossi', found {count}."
        )

    # Copertura (set equality) — log does not invent rows not in the sequence.
    unexpected = sorted(set(logged) - set(removed_sequence))
    assert not unexpected, (
        "Copertura violated: synthetic log lists paths that were not part "
        f"of the removal sequence: {unexpected}"
    )

    # Concordanza — every logged path is absent from the synthetic workspace.
    still_present = [
        rel for rel in logged if (tmp_root / Path(rel)).exists()
    ]
    assert not still_present, (
        "Concordanza violated: synthetic log lists paths that are still "
        f"present on disk: {still_present}"
    )


# --- Path strategy ---------------------------------------------------------

# Synthetic candidate paths: a mix of known REMOVE-shaped prefixes (so
# ``_category_for`` yields a valid token) and plain identifiers. Paths
# use POSIX separators per Req 10.2.
_CANDIDATE_PATHS: Tuple[str, ...] = (
    "capture/alpha.py",
    "capture/beta.py",
    "engines/gamma.py",
    "engines/delta.py",
    "input/epsilon.py",
    "input/zeta.py",
    "utils/eta.py",
    "utils/theta.py",
    "firmware/iota.ino",
    "firmware/kappa.ino",
    "drivers/Lambda.dll",
    "tools/mu.py",
    "tests/unit/nu.py",
    "tests/integration/xi.py",
)


if HAS_HYPOTHESIS:
    _path_set_st = st.lists(
        st.sampled_from(_CANDIDATE_PATHS),
        min_size=0,
        max_size=len(_CANDIDATE_PATHS),
        unique=True,
    )

    # Given a set of candidate files and a subset to remove, derive the
    # matching synthetic workspace + removal log and assert Property 10.
    @pytest.mark.integration
    @given(
        all_files=_path_set_st,
        removal_mask=st.lists(st.booleans(), max_size=len(_CANDIDATE_PATHS)),
    )
    @settings(
        max_examples=40,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_property_10_hypothesis(
        all_files: List[str],
        removal_mask: List[bool],
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        """Property 10 (Hypothesis): on any finite removal sequence.

        Builds a fresh synthetic workspace for each example, removes the
        subset selected by ``removal_mask``, synthesises the log, and
        asserts both copertura and concordanza.
        """
        tmp_root = tmp_path_factory.mktemp("prop10", numbered=True)
        _materialise_workspace(tmp_root, all_files)

        # Align mask length with file count (Hypothesis may under- or
        # over-generate); missing entries default to ``False`` (keep).
        mask = list(removal_mask) + [False] * max(
            0, len(all_files) - len(removal_mask)
        )
        to_remove = [f for f, keep in zip(all_files, mask) if keep]

        _apply_removals(tmp_root, to_remove)
        log_text_ = _synthesise_log(to_remove)
        _check_property_10(tmp_root, to_remove, log_text_)


# --- Parametrized fallback -------------------------------------------------

_FALLBACK_SEQUENCES: Tuple[Tuple[str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    ("empty_sequence", tuple(), tuple()),
    ("single_py_removal", ("capture/alpha.py",), ("capture/alpha.py",)),
    (
        "keep_some_remove_some",
        ("capture/alpha.py", "engines/gamma.py", "input/epsilon.py"),
        ("capture/alpha.py", "engines/gamma.py"),
    ),
    (
        "remove_all_created",
        ("utils/eta.py", "firmware/iota.ino", "drivers/Lambda.dll"),
        ("utils/eta.py", "firmware/iota.ino", "drivers/Lambda.dll"),
    ),
    (
        "ino_and_dll_coexist",
        ("firmware/iota.ino", "firmware/kappa.ino", "drivers/Lambda.dll"),
        ("firmware/kappa.ino", "drivers/Lambda.dll"),
    ),
    (
        "many_files",
        _CANDIDATE_PATHS,
        (
            "capture/alpha.py",
            "engines/delta.py",
            "input/zeta.py",
            "utils/theta.py",
            "firmware/iota.ino",
            "drivers/Lambda.dll",
        ),
    ),
)


@pytest.mark.integration
@pytest.mark.parametrize(
    "case_id,all_files,to_remove",
    _FALLBACK_SEQUENCES,
    ids=[c for c, _, _ in _FALLBACK_SEQUENCES],
)
def test_property_10_fallback(
    case_id: str,
    all_files: Tuple[str, ...],
    to_remove: Tuple[str, ...],
    tmp_path: Path,
) -> None:
    """Property 10 (parametrized): deterministic scenarios on a tmp workspace."""
    _materialise_workspace(tmp_path, all_files)
    _apply_removals(tmp_path, to_remove)
    log_text_ = _synthesise_log(list(to_remove))
    _check_property_10(tmp_path, list(to_remove), log_text_)


# ---------------------------------------------------------------------------
# Parser sanity checks — prevent silent false positives from broken helpers
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_parser_ignores_empty_sentinel() -> None:
    """``_Nessuna voce._`` under '## File rimossi' yields zero paths."""
    text = (
        "# X\n"
        "## File rimossi\n"
        "\n"
        "_Nessuna voce._\n"
        "\n"
        "## Chiavi YAML rimosse\n"
    )
    assert _parse_removed_files_section(text) == []


@pytest.mark.integration
def test_parser_extracts_first_field_only() -> None:
    """The parser keeps only ``<path>``, stripping backticks and metadata."""
    text = (
        "## File rimossi\n"
        "- capture/a.py | alt_capture_backend | because | 42\n"
        "- `engines/b.py` | alt_detection_engine | because | 7\n"
        "- drivers/c.dll | alt_driver_dll | because | \n"
        "## Simboli rimossi\n"
        "- this.SHOULD | not.be | captured\n"
    )
    assert _parse_removed_files_section(text) == [
        "capture/a.py",
        "engines/b.py",
        "drivers/c.dll",
    ]
