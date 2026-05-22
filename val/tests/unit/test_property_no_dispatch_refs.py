"""Property test — Property 8: Assenza di riferimenti di dispatch a nomi rimossi.

*For any* nome ``N`` nell'insieme
``REMOVED_NAMES = {dxgi, mss, hsv_engine, memory_esp, ib, dd, interception,
winapi, kmbox_serial, makcu, makcu_socket, efi}``
e *any* variabile di dispatch
``V ∈ {driver_type, backend, primary_engine, engine, provider, driver}``,
una ricerca testuale case-sensitive che matcha i pattern::

    V == '<N>'
    V == "<N>"
    elif V == '<N>'
    case '<N>'
    V in ('<N>'

su tutti i file ``.py`` classificati ``KEEP`` nel Refactored_Codebase SHALL
restituire zero occorrenze.

**Validates: Requirements 11.3, 11.7**

Implementation notes
--------------------
* The ``(V, N)`` search space is finite (6 dispatch variables × 12 removed
  names = 72 combinations) so the property is exercised by
  ``@pytest.mark.parametrize`` rather than Hypothesis — no generator is
  needed.
* The KEEP ``.py`` set is derived from the summary table under
  ``## Tabella riepilogativa`` in
  ``.kiro/specs/single-config-streamlining/audit.md`` (Requirement 1.10).
  Files that are not present on disk are silently skipped here: their
  existence is an invariant owned by other tests (e.g.
  ``tests/integration/test_audit_document.py``).
* Excluded paths: ``.archive/``, ``htmlcov/``, ``.pytest_cache/``,
  ``__pycache__/``, ``.kiro/`` (docs), ``audit.md``, ``removal-log.md``,
  and ``*.bak*`` backups. Those exclusions are applied both via the
  classification filter (audit.md classifies ``.archive`` / ``htmlcov``
  content as outside the scan) and defensively via per-path filters.
* The five regex patterns match the exact forms enumerated in the
  Property 8 statement. They never span across newlines and they treat
  ``V`` as a whole-word token via ``\\b`` anchors so that, e.g.,
  ``VPN_driver == 'mss'`` would not match under ``V = 'driver'``.
  This is the same "word-boundary" semantics implied by Req 11.3
  ("``<var>`` appartiene all'insieme ... ``<X>`` è il nome esatto").
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pytest


# ---------------------------------------------------------------------------
# Property 8 inputs — literal, finite sets from the design document
# ---------------------------------------------------------------------------

REMOVED_NAMES: Tuple[str, ...] = (
    "dxgi",
    "mss",
    "hsv_engine",
    "memory_esp",
    "ib",
    "dd",
    "interception",
    "winapi",
    "kmbox_serial",
    "makcu",
    "makcu_socket",
    "efi",
)

DISPATCH_VARIABLES: Tuple[str, ...] = (
    "driver_type",
    "backend",
    "primary_engine",
    "engine",
    "provider",
    "driver",
)


# ---------------------------------------------------------------------------
# Workspace layout & exclusions
# ---------------------------------------------------------------------------

_WORKSPACE: Path = Path(__file__).resolve().parents[2]
_AUDIT_PATH: Path = (
    _WORKSPACE
    / ".kiro"
    / "specs"
    / "single-config-streamlining"
    / "audit.md"
)

# Excluded path fragments (case-insensitive substring match on the
# workspace-relative, forward-slash-normalised path).
_EXCLUDED_FRAGMENTS: Tuple[str, ...] = (
    ".archive/",
    "htmlcov/",
    ".pytest_cache/",
    "__pycache__/",
    ".kiro/",
)

# Explicit filenames/extensions to skip even if they surface for any reason.
_EXCLUDED_FILENAMES: Tuple[str, ...] = (
    "audit.md",
    "removal-log.md",
    # This test file itself contains literal ``V == 'N'`` dispatch samples
    # in its negative-/positive-form smoke tests (see
    # ``test_patterns_do_not_match_unrelated_identifiers`` and
    # ``test_patterns_match_all_documented_forms``) that would otherwise
    # produce false positives when the Property 8 scan opens this file.
    "test_property_no_dispatch_refs.py",
)


def _is_excluded(rel_path: str) -> bool:
    """Return ``True`` if ``rel_path`` falls under an excluded location."""
    norm = rel_path.replace("\\", "/").lower()
    for frag in _EXCLUDED_FRAGMENTS:
        if frag in norm:
            return True
    name = norm.rsplit("/", 1)[-1]
    if name in _EXCLUDED_FILENAMES:
        return True
    # ``*.bak`` and ``*.bak.*`` backups
    if ".bak" in name:
        return True
    return False


# ---------------------------------------------------------------------------
# audit.md summary table parsing (mirrors test_property_config_keys_read.py)
# ---------------------------------------------------------------------------

_TABLE_HEADER_RE = re.compile(
    r"^\s*## Tabella riepilogativa\s*$", re.MULTILINE
)
_TABLE_ROW_RE = re.compile(
    r"^\|\s*`(?P<file>[^`]+)`\s*\|\s*`(?P<cls>[^`]+)`\s*\|\s*"
    r"(?P<reason>.*?)\s*\|\s*$"
)


def _parse_summary_table(audit_text: str) -> Dict[str, str]:
    """Return ``{workspace-relative-path: classification}`` from audit.md."""
    header_match = _TABLE_HEADER_RE.search(audit_text)
    assert header_match is not None, (
        "audit.md is missing the '## Tabella riepilogativa' section; "
        "task 1.1 must produce it and task 1.2 must keep it."
    )
    start = header_match.end()
    next_heading = re.search(r"^\s*##\s", audit_text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(audit_text)
    section = audit_text[start:end]

    rows: Dict[str, str] = {}
    for line in section.splitlines():
        m = _TABLE_ROW_RE.match(line)
        if not m:
            continue
        classification = m.group("cls").strip()
        if classification.lower() == "classification":
            # Header row wrapped in backticks — skip.
            continue
        rows[m.group("file").strip()] = classification
    assert rows, (
        "The summary table under '## Tabella riepilogativa' is empty; "
        "task 1.1 must populate it."
    )
    return rows


# ---------------------------------------------------------------------------
# KEEP .py corpus loading (cached at module import)
# ---------------------------------------------------------------------------

def _load_keep_py_contents() -> Dict[str, str]:
    """Return ``{rel_path: source}`` for every KEEP ``.py`` file on disk,
    after applying the excluded-path filter documented above."""
    assert _AUDIT_PATH.is_file(), f"audit.md not found at {_AUDIT_PATH}"
    audit_text = _AUDIT_PATH.read_text(encoding="utf-8")
    table = _parse_summary_table(audit_text)

    contents: Dict[str, str] = {}
    for rel, cls in table.items():
        if cls != "KEEP" or not rel.endswith(".py"):
            continue
        if _is_excluded(rel):
            continue
        path = _WORKSPACE / rel
        if not path.is_file():
            # Missing KEEP files are reported elsewhere; skip silently.
            continue
        try:
            contents[rel] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    assert contents, (
        "No KEEP .py files could be read from the workspace; cannot "
        "verify Property 8."
    )
    return contents


_KEEP_PY_CONTENTS: Dict[str, str] = _load_keep_py_contents()


# ---------------------------------------------------------------------------
# Pattern construction
# ---------------------------------------------------------------------------

def _dispatch_patterns(variable: str, name: str) -> List[re.Pattern[str]]:
    """Build the five regex patterns for the ``(variable, name)`` pair.

    The regex forms correspond one-to-one to the textual patterns in the
    Property 8 statement:

    1. ``V == '<N>'``
    2. ``V == "<N>"``
    3. ``elif V == '<N>'`` / ``elif V == "<N>"``
    4. ``case '<N>'`` / ``case "<N>"``
    5. ``V in ('<N>'`` / ``V in ("<N>"``

    ``V`` is anchored as a whole word with ``\\b`` so unrelated
    identifiers ending in ``_driver`` or ``_backend`` don't false-match.
    ``<N>`` is matched literally between its enclosing quotes.
    """
    v = re.escape(variable)
    n = re.escape(name)
    return [
        # 1. V == 'N'   and   2. V == "N"
        re.compile(rf"\b{v}\b\s*==\s*(?:'{n}'|\"{n}\")"),
        # 3. elif V == 'N'  /  elif V == "N"  (stricter form with "elif ")
        re.compile(rf"\belif\s+{v}\b\s*==\s*(?:'{n}'|\"{n}\")"),
        # 4. case 'N'  /  case "N"
        re.compile(rf"\bcase\s+(?:'{n}'|\"{n}\")"),
        # 5. V in ('N'  /  V in ("N"
        re.compile(rf"\b{v}\b\s*in\s*\(\s*(?:'{n}'|\"{n}\")"),
    ]


def _find_hits(
    patterns: Iterable[re.Pattern[str]],
    corpus: Dict[str, str],
) -> List[Tuple[str, int, str, str]]:
    """Return a list of ``(rel_path, line_no, line_text, pattern_src)`` hits.

    Line numbers are 1-indexed. The scan is line-by-line so that a hit
    report can cite the offending line unambiguously.
    """
    hits: List[Tuple[str, int, str, str]] = []
    for rel, source in corpus.items():
        for lineno, line in enumerate(source.splitlines(), start=1):
            for pat in patterns:
                if pat.search(line):
                    hits.append((rel, lineno, line.rstrip(), pat.pattern))
    return hits


# ---------------------------------------------------------------------------
# Property 8 — parametrized property test
# ---------------------------------------------------------------------------

_PARAMS: List[Tuple[str, str]] = [
    (v, n) for v in DISPATCH_VARIABLES for n in REMOVED_NAMES
]


@pytest.mark.unit
@pytest.mark.parametrize(
    "variable,name",
    _PARAMS,
    ids=[f"{v}__{n}" for v, n in _PARAMS],
)
def test_no_dispatch_reference_to_removed_name(
    variable: str, name: str
) -> None:
    """Property 8 — no KEEP ``.py`` file dispatches on ``variable == name``.

    For the given ``(variable, name)`` pair, none of the five textual
    dispatch forms (``V == 'N'``, ``V == "N"``, ``elif V == 'N'``,
    ``case 'N'``, ``V in ('N'``) must occur in any KEEP ``.py`` file of
    the Refactored_Codebase (after excluding ``.archive/``, ``htmlcov/``,
    ``.pytest_cache/``, ``__pycache__/``, ``.kiro/``, ``audit.md``,
    ``removal-log.md``, and ``*.bak*`` backups).

    **Validates: Requirements 11.3, 11.7**
    """
    patterns = _dispatch_patterns(variable, name)
    hits = _find_hits(patterns, _KEEP_PY_CONTENTS)

    if hits:
        # Build a readable report of up to five violations (the full list
        # would be attached anyway via the final formatted message).
        preview = "\n".join(
            f"  {rel}:{lineno}: {line}   [pattern: {pat}]"
            for rel, lineno, line, pat in hits[:5]
        )
        extra = (
            f"\n  ... and {len(hits) - 5} more" if len(hits) > 5 else ""
        )
        pytest.fail(
            "Property 8 violation — dispatch reference to removed name "
            f"'{name}' via variable '{variable}' found in KEEP .py:\n"
            f"{preview}{extra}\n"
            f"Total occurrences: {len(hits)}\n"
            "Req 11.3/11.7 require zero dispatch references to any "
            "removed backend, driver, or engine in KEEP .py files."
        )


# ---------------------------------------------------------------------------
# Sanity checks — guard against scaffolding bugs masking a real failure
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_keep_py_corpus_is_non_empty() -> None:
    """Smoke check: at least one KEEP .py file was loaded from disk.

    An empty corpus would vacuously satisfy Property 8, hiding a real
    configuration problem.
    """
    assert _KEEP_PY_CONTENTS, (
        "No KEEP .py files loaded; the property test cannot discriminate."
    )


@pytest.mark.unit
def test_parameter_space_is_complete() -> None:
    """Smoke check: the generated parameter grid covers all 6×12 pairs."""
    assert len(_PARAMS) == len(DISPATCH_VARIABLES) * len(REMOVED_NAMES)
    assert len(_PARAMS) == 6 * 12


@pytest.mark.unit
def test_patterns_match_the_five_documented_forms() -> None:
    """Smoke check: each of the five documented dispatch forms is detected.

    This protects against accidental regex drift — every form in the
    Property 8 statement must produce at least one hit on a synthetic
    sample that contains it verbatim.
    """
    variable = "backend"
    name = "dxgi"
    samples = [
        f"{variable} == '{name}'",            # form 1
        f'{variable} == "{name}"',            # form 2
        f"elif {variable} == '{name}':",      # form 3
        f"case '{name}':",                    # form 4
        f"{variable} in ('{name}', 'other')", # form 5
    ]
    patterns = _dispatch_patterns(variable, name)
    for sample in samples:
        assert any(p.search(sample) for p in patterns), (
            f"no pattern matched documented form: {sample!r}"
        )


@pytest.mark.unit
def test_patterns_do_not_match_unrelated_identifiers() -> None:
    """Smoke check: word-boundary anchors must prevent false positives.

    The anchors ``\\b{variable}\\b`` guarantee that identifiers that
    merely contain ``variable`` as a substring (e.g. ``vpn_driver`` when
    ``V = driver``) do not produce a match.
    """
    patterns = _dispatch_patterns("driver", "mss")
    negatives = [
        "vpn_driver == 'mss'",          # prefix: vpn_
        "old_driver_type == 'mss'",     # suffix: _type
        "something.driver_foo == 'mss'",  # attribute with suffix
        "# driver_type == 'mss'  # legacy comment about 'driver_type'",
        # Note: this last one contains the literal string ``'mss'`` but
        # the dispatch variable is not ``driver`` as a standalone token
        # — it's ``driver_type``. We expect no ``driver``-keyed match.
    ]
    for sample in negatives:
        assert not any(p.search(sample) for p in patterns), (
            f"pattern unexpectedly matched non-dispatch form: {sample!r}"
        )


@pytest.mark.unit
def test_patterns_respect_case_sensitivity() -> None:
    """Smoke check: uppercase variants of the removed name must not match.

    Req 11.3/11.7 mandate a case-sensitive comparison on the enumerated
    name ``<N>``. Variants like ``'DXGI'`` or ``'Hsv_Engine'`` therefore
    do not count as dispatch hits.
    """
    patterns = _dispatch_patterns("backend", "dxgi")
    uppercase_sample = "backend == 'DXGI'"
    titlecase_sample = "backend == 'Dxgi'"
    assert not any(p.search(uppercase_sample) for p in patterns)
    assert not any(p.search(titlecase_sample) for p in patterns)
