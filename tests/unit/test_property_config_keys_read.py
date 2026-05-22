"""Property test — Property 9: Copertura lettura chiavi YAML terminali.

*For any* chiave terminale ``k`` presente nel Config_File (``config.yaml``),
esiste almeno un file ``.py`` classificato ``KEEP`` nel Refactored_Codebase
che contiene ``k`` come sottostringa case-sensitive, considerando sia la
notazione dotted completa (``section.subsection.k``) sia la forma di
stringa letterale (``'k'``, ``"k"``) sia l'accesso dict-style
(``['k']``, ``["k"]``).

**Validates: Requirements 11.6**

Implementation notes
--------------------
* The terminal-key set is finite and bounded by the shape of the
  repository's ``config.yaml``, so the property is exercised by
  ``@pytest.mark.parametrize`` (one case per terminal key) rather than
  Hypothesis.
* A "terminal key" is a leaf of the YAML mapping tree: any key whose
  value is not a ``dict``. Lists are **not** descended into (per task
  19.1 brief), so a key whose value is a list is still terminal.
* The KEEP ``.py`` set is derived from the summary table under
  ``## Tabella riepilogativa`` in ``audit.md`` (Requirement 1.10).
* For each terminal key with dotted path ``a.b.c`` and leaf ``c``, the
  search patterns are exactly:

  1. ``a.b.c`` — full dotted notation
  2. ``'c'``   — single-quoted literal
  3. ``"c"``   — double-quoted literal
  4. ``['c']`` — dict-style access (single-quoted)
  5. ``["c"]`` — dict-style access (double-quoted)

  A terminal key is considered "read" if at least one of those patterns
  is found, case-sensitive, in at least one KEEP ``.py`` file.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
import yaml


# ---------------------------------------------------------------------------
# Workspace layout
# ---------------------------------------------------------------------------

_WORKSPACE: Path = Path(__file__).resolve().parents[2]
_CONFIG_YAML: Path = _WORKSPACE / "config.yaml"
_AUDIT_PATH: Path = (
    _WORKSPACE
    / ".kiro"
    / "specs"
    / "single-config-streamlining"
    / "audit.md"
)


# ---------------------------------------------------------------------------
# Audit.md summary table parsing (mirrors test_audit_document.py)
# ---------------------------------------------------------------------------

_TABLE_HEADER_RE = re.compile(
    r"^\s*## Tabella riepilogativa\s*$", re.MULTILINE
)
# Matches a row like: | `path/to/file.py` | `KEEP` | reason text |
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
# Terminal-key extraction
# ---------------------------------------------------------------------------

def _iter_terminal_keys(
    node: Any, prefix: Tuple[str, ...] = ()
) -> List[Tuple[str, ...]]:
    """Flatten ``node`` into dotted-path tuples for every terminal key.

    A terminal key is any mapping key whose value is **not** a ``dict``.
    Lists are not descended into: a key whose value is a list remains
    terminal (per task 19.1 brief "walk all nested dict levels, skip
    lists").
    """
    results: List[Tuple[str, ...]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            child_prefix = prefix + (str(key),)
            if isinstance(value, dict):
                results.extend(_iter_terminal_keys(value, child_prefix))
            else:
                results.append(child_prefix)
    # Lists and scalars at the root (unusual for config.yaml) produce no
    # terminal keys on their own: the path leading to them was already
    # appended by the enclosing dict branch above.
    return results


def _load_terminal_keys() -> List[Tuple[str, ...]]:
    assert _CONFIG_YAML.is_file(), f"config.yaml not found at {_CONFIG_YAML}"
    with open(_CONFIG_YAML, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    assert isinstance(cfg, dict), (
        "config.yaml root must be a mapping (got "
        f"{type(cfg).__name__})"
    )
    keys = _iter_terminal_keys(cfg)
    assert keys, "config.yaml produced zero terminal keys"
    # Deterministic order for stable test ids.
    return sorted(keys)


# ---------------------------------------------------------------------------
# KEEP .py corpus loading
# ---------------------------------------------------------------------------

def _load_keep_py_contents() -> Dict[str, str]:
    """Return ``{rel_path: source}`` for every KEEP ``.py`` file on disk."""
    assert _AUDIT_PATH.is_file(), f"audit.md not found at {_AUDIT_PATH}"
    audit_text = _AUDIT_PATH.read_text(encoding="utf-8")
    table = _parse_summary_table(audit_text)

    contents: Dict[str, str] = {}
    for rel, cls in table.items():
        if cls != "KEEP" or not rel.endswith(".py"):
            continue
        path = _WORKSPACE / rel
        if not path.is_file():
            # A KEEP file missing from disk is a separate invariant
            # owned by the audit/consistency tests; silently skip here.
            continue
        try:
            contents[rel] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    assert contents, (
        "No KEEP .py files could be read from the workspace; cannot "
        "verify Property 9."
    )
    return contents


# Module-level caches: loaded once per test session to keep the
# parametrized cases cheap.
_TERMINAL_KEYS: List[Tuple[str, ...]] = _load_terminal_keys()
_KEEP_PY_CONTENTS: Dict[str, str] = _load_keep_py_contents()


# ---------------------------------------------------------------------------
# Pattern construction
# ---------------------------------------------------------------------------

def _search_patterns(path_tuple: Tuple[str, ...]) -> List[str]:
    """Return the five search patterns for a terminal key.

    ``path_tuple = ('a', 'b', 'c')`` →
      ['a.b.c', "'c'", '"c"', "['c']", '["c"]']
    """
    leaf = path_tuple[-1]
    dotted = ".".join(path_tuple)
    return [
        dotted,
        f"'{leaf}'",
        f'"{leaf}"',
        f"['{leaf}']",
        f'["{leaf}"]',
    ]


# ---------------------------------------------------------------------------
# Property 9 — parametrized property test
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize(
    "dotted_path",
    [".".join(p) for p in _TERMINAL_KEYS],
    ids=[".".join(p) for p in _TERMINAL_KEYS],
)
def test_terminal_key_is_read_by_at_least_one_keep_py(
    dotted_path: str,
) -> None:
    """Property 9 — every terminal YAML key has a reading in a KEEP .py.

    For the terminal key identified by ``dotted_path``, at least one of
    the five patterns (full dotted path, ``'leaf'``, ``"leaf"``,
    ``['leaf']``, ``["leaf"]``) must appear as a case-sensitive
    substring of at least one KEEP ``.py`` file in the workspace.

    **Validates: Requirements 11.6**
    """
    path_tuple = tuple(dotted_path.split("."))
    patterns = _search_patterns(path_tuple)

    hits: Dict[str, List[str]] = {}
    for rel, source in _KEEP_PY_CONTENTS.items():
        matched = [p for p in patterns if p in source]
        if matched:
            hits[rel] = matched

    if not hits:
        pytest.fail(
            "Property 9 violation — terminal YAML key "
            f"'{dotted_path}' has no textual reading in any KEEP .py file.\n"
            f"Searched patterns (case-sensitive substring): {patterns}\n"
            f"KEEP .py files scanned: {len(_KEEP_PY_CONTENTS)}\n"
            "Req 11.6 requires at least one occurrence among the "
            "dotted-path, single/double-quoted literal, or dict-style "
            "forms."
        )


# ---------------------------------------------------------------------------
# Sanity checks — guard against scaffolding bugs masking a real failure
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_helper_flattens_nested_dicts() -> None:
    """``_iter_terminal_keys`` must produce dotted paths for leaves only."""
    sample = {
        "a": {"b": {"c": 1, "d": [1, 2, 3]}},
        "e": "scalar",
        "f": [1, 2, 3],
    }
    paths = set(_iter_terminal_keys(sample))
    assert paths == {
        ("a", "b", "c"),
        ("a", "b", "d"),  # list value → d is terminal, not descended
        ("e",),
        ("f",),  # list value → f is terminal
    }


@pytest.mark.unit
def test_helper_search_patterns_shape() -> None:
    """``_search_patterns`` must return exactly the five documented forms."""
    patterns = _search_patterns(("input", "kmbox_net", "ip"))
    assert patterns == [
        "input.kmbox_net.ip",
        "'ip'",
        '"ip"',
        "['ip']",
        '["ip"]',
    ]


@pytest.mark.unit
def test_terminal_key_set_is_non_empty_and_includes_target_keys() -> None:
    """Smoke check: the Target_Configuration keys are terminal keys."""
    dotted = {".".join(p) for p in _TERMINAL_KEYS}
    expected = {
        "general.architecture",
        "capture.backend",
        "general.primary_engine",
        "input.driver",
    }
    missing = expected - dotted
    assert not missing, (
        "config.yaml is missing Target_Configuration terminal keys: "
        f"{sorted(missing)}"
    )


@pytest.mark.unit
def test_keep_py_corpus_is_non_empty() -> None:
    """Smoke check: at least one KEEP .py file was loaded from disk."""
    assert _KEEP_PY_CONTENTS, (
        "No KEEP .py files loaded; the property test cannot discriminate."
    )
