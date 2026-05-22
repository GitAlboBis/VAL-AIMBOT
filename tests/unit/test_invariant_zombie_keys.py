"""
Baseline Zombie_Config_Key coverage test (Property 3).

Property 3: Zombie_Config_Key absence — widget registry is a subset of
engine consumers.
Validates: Requirements 4.1, 4.5, 40.5 (audit-remediation spec).

Design link: ``.kiro/specs/audit-remediation/design.md`` — Property 3:
""For any `(section, key)` pair that any GUI widget mutates via
`update_config` or `update_config_section`, at least one engine module
under `engines/`, `capture/`, `input/`, or `utils/` SHALL reference
`(section, key)` via a config-read expression.""

Methodology
-----------
1. Parse every ``.py`` file under ``gui/`` (recursively, sans
   ``__pycache__`` and the ``error_handler_example.py`` scaffolding
   scheduled for deletion by Task 13) with ``ast`` and collect every
   ``(section, key)`` pair appearing as a ``(section, key, ...)``
   positional-literal argument list to ``update_config`` or
   ``_update_config_validated``. These are the two widget-registration
   entry points enumerated by Requirement 4.1. ``update_config_section``
   is intentionally NOT scanned from GUI code because its only call
   sites live in ``gui/config_manager.py``, where it forwards a
   pre-validated config dict on preset load — it is not a per-widget
   registration.

2. For each ``(section, key)`` pair, search every ``.py`` under
   ``engines/``, ``capture/``, ``input/``, ``utils/`` and ``main.py``
   for at least one of two tiers of reader patterns:

   Tier 1 (section-scoped, high-precision):
     * ``cfg["<section>"]["<key>"]`` / ``config["<section>"]["<key>"]``
     * ``.get("<section>", {}).get("<key>"`` (both quote styles)
     * dotted-path literal ``"<section>.<key>"`` / ``'<section>.<key>'``

   Tier 2 (section-scoped + key subscript, medium precision):
     A file that (a) contains the section name as a quoted string
     literal AND (b) contains any of ``.get("<key>"``, ``.get('<key>'``,
     ``["<key>"]``, ``['<key>']`` is treated as a consumer. This
     catches the "slice-and-get" idiom used by the engines, where the
     caller slices ``config["<section>"]`` into a local and the engine
     class then reads ``cfg.get("<key>", ...)``. In this codebase the
     slice is typically a few lines away from the ``get`` call
     (see ``main.py::DetectionFramework.__init__`` → ``ai_engine`` slice
     → ``AIVisionEngine(ai_cfg)`` → ``config.get('headshot_bias', ...)``
     inside ``engines/ai_engine.py``). Because this pattern spans
     files, Tier 2 considers the **same file** evidence only; the
     main.py slice therefore satisfies it for any key whose section
     is sliced in main.py and whose quoted-key access exists anywhere
     in main.py's scope.

3. Pairs marked in the R4.2 known-zombie set (per
   ``Requirement 4.2``) are wrapped with ``@pytest.mark.xfail(strict=
   True)``: they fail today because they have no reader, and Task 5.3
   flips the xfail off by removing the widget + schema + rules entry.

4. Non-R4.2 pairs that are ALSO unwired at Wave 0 baseline (observed
   empirically — ``visuals.*`` widgets have no ``visuals`` section in
   ``config.yaml`` and no engine consumer; ``general.debug_mode`` is
   a GUI-only state key) are wrapped with a distinct ``xfail`` so
   the baseline stays green without masking R4.2 intent.

5. Any newly-introduced widget pair that is neither listed in R4.2
   nor in the baseline-unwired set SHALL fail this test outright —
   that's the enforcement direction of R40.5 (no new Zombie_Config_Key
   may be introduced after Wave 0).

Limitations
-----------
The reader scan is substring-based, not a full data-flow analysis.
It will report false negatives when an engine reads a key through
an alias variable whose name is only visible across module
boundaries (e.g., a dict passed positionally into a constructor).
That false-negative rate motivated the ``_CURRENTLY_UNWIRED_BASELINE``
set: it records pairs the scan cannot confidently classify as wired
today without hand-auditing the call graph. Task 5.3 flips R4.2
zombies off; later tasks (or a stronger cross-file reader) may flip
the baseline-unwired markers off as each consumer is either wired or
removed.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pytest


# ---------------------------------------------------------------------------
# Workspace layout
# ---------------------------------------------------------------------------

_WORKSPACE: Path = Path(__file__).resolve().parents[2]

_GUI_DIR: Path = _WORKSPACE / "gui"
_ENGINE_SIDE_DIRS: Tuple[Path, ...] = (
    _WORKSPACE / "engines",
    _WORKSPACE / "capture",
    _WORKSPACE / "input",
    _WORKSPACE / "utils",
)
_MAIN_PY: Path = _WORKSPACE / "main.py"

# Widget-registration call names. The first two positional arguments are
# ``(section, key)``. Both the gui/app.py internal helper and the
# ``SharedState`` method form are scanned.
_WIDGET_FUNCS: Set[str] = {
    "_update_config_validated",
    "update_config",
}

# Non-production GUI files whose residual widget-literal calls are
# scaffolding (they will be deleted by Task 13 / Requirement 11).
_GUI_SKIP_NAMES: Set[str] = {
    "error_handler_example.py",
}


# ---------------------------------------------------------------------------
# Known-zombie set (Requirement 4.2)
# ---------------------------------------------------------------------------

# Wildcard sections: any widget pair with this section is R4.2.
_WILDCARD_ZOMBIE_SECTIONS: Set[str] = {
    "close_aim",
    "weapon",
    "radar",
    "world",
}

# Specific pairs listed by R4.2 under sections that are NOT wholesale
# removed.
_SPECIFIC_ZOMBIES: Set[Tuple[str, str]] = {
    ("aim", "distance"),
    ("aim", "fov_size"),
    ("aim", "smoothing"),
    ("aim", "prediction"),
    ("aim", "ignore_knocked"),
    ("aim", "visible_check"),
    ("aim", "auto_aim"),
    ("misc", "no_recoil"),
    ("misc", "rapid_fire"),
}


def _expand_known_zombies(
    widget_pairs: Set[Tuple[str, str]],
) -> Set[Tuple[str, str]]:
    """Expand wildcard sections against the observed widget registry."""
    expanded: Set[Tuple[str, str]] = set(_SPECIFIC_ZOMBIES)
    for section, key in widget_pairs:
        if section in _WILDCARD_ZOMBIE_SECTIONS:
            expanded.add((section, key))
    return expanded


# ---------------------------------------------------------------------------
# Non-R4.2 baseline-unwired set
# ---------------------------------------------------------------------------
#
# These pairs are exposed by widgets TODAY but have no engine-side reader
# visible to the substring scanner at Wave 0 baseline. They are NOT listed
# in Requirement 4.2, so Task 5.3's xfail-flip is scoped to the R4.2 set
# and leaves these entries in place. They are tracked here with an
# explicit xfail marker so that:
#   * the Wave 0 test suite stays green;
#   * any newly-introduced widget pair outside this set still fails the
#     test (R40.5);
#   * a later task (widening R4 or a targeted follow-up) flips these
#     off as each key is either wired to a real consumer or removed.
#
# Each entry's note records the reason the pair is unwired today.
_CURRENTLY_UNWIRED_BASELINE: Set[Tuple[str, str]] = {
    # `visuals.*`: the entire `visuals` section is missing from
    # config.yaml (no schema at all). Widgets exist under the Visuals
    # tab but no engine consumes them. Not listed in R4.2.
    ("visuals", "box_esp"),
    ("visuals", "skeleton"),
    ("visuals", "health_bar"),
    ("visuals", "name_tag"),
    ("visuals", "distance_tag"),
    # `general.debug_mode`: read only via `SharedState.get_state(
    # 'general.debug_mode')` inside gui/ and tests; no engine/main.py
    # reader of the config-dict form. It is a SharedState-observed flag
    # rather than an engine config key.
    ("general", "debug_mode"),
    # `ai_engine.confidence` and `ai_engine.iou_threshold`: the engine
    # reads them via `config.get('confidence', ...)` inside
    # `engines/ai_engine.py` after main.py slices `self.config[
    # 'ai_engine']` into `ai_cfg` (main.py:268). The section literal
    # `'ai_engine'` appears in main.py but the key literals
    # `'confidence'` / `'iou_threshold'` appear only in ai_engine.py,
    # and the scanner is per-file. Tracked here rather than weakened
    # because strengthening the scanner to cross files would risk
    # false positives on every shared key name.
    ("ai_engine", "confidence"),
    ("ai_engine", "iou_threshold"),
}


# ---------------------------------------------------------------------------
# Widget registry: AST walk of gui/*.py
# ---------------------------------------------------------------------------

def _iter_py_files(root: Path) -> List[Path]:
    """Return every ``.py`` file under ``root`` (sorted, pycache skipped)."""
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def _extract_widget_pairs(path: Path) -> Set[Tuple[str, str]]:
    """Parse one ``.py`` file and return literal ``(section, key)`` pairs."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return set()

    pairs: Set[Tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name: str | None = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name not in _WIDGET_FUNCS:
            continue
        if len(node.args) < 2:
            continue
        a0, a1 = node.args[0], node.args[1]
        if not (isinstance(a0, ast.Constant) and isinstance(a1, ast.Constant)):
            continue
        if not (isinstance(a0.value, str) and isinstance(a1.value, str)):
            continue
        pairs.add((a0.value, a1.value))
    return pairs


def _collect_widget_pairs() -> Set[Tuple[str, str]]:
    """Union of literal widget-registration pairs across every GUI file."""
    pairs: Set[Tuple[str, str]] = set()
    for path in _iter_py_files(_GUI_DIR):
        if path.name in _GUI_SKIP_NAMES:
            continue
        pairs |= _extract_widget_pairs(path)
    return pairs


# ---------------------------------------------------------------------------
# Engine-side consumer scan (two-tier substring)
# ---------------------------------------------------------------------------

def _load_engine_side_sources() -> Dict[Path, str]:
    """Return ``{path: source}`` for every engine-side ``.py`` file."""
    sources: Dict[Path, str] = {}
    for root in _ENGINE_SIDE_DIRS:
        for path in _iter_py_files(root):
            try:
                sources[path] = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
    if _MAIN_PY.is_file():
        try:
            sources[_MAIN_PY] = _MAIN_PY.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass
    return sources


def _tier1_patterns(section: str, key: str) -> List[str]:
    """Fully-qualified section.key reader patterns (high precision)."""
    return [
        f'["{section}"]["{key}"]',
        f"['{section}']['{key}']",
        f'.get("{section}", {{}}).get("{key}"',
        f".get('{section}', {{}}).get('{key}'",
        f'"{section}.{key}"',
        f"'{section}.{key}'",
    ]


def _tier2_key_subscripts(key: str) -> List[str]:
    """Section-agnostic key-subscript patterns (medium precision)."""
    return [
        f'.get("{key}"',
        f".get('{key}'",
        f'["{key}"]',
        f"['{key}']",
    ]


def _section_literal_regex(section: str) -> "re.Pattern[str]":
    """Compile a quoted-string-literal regex for the section name."""
    return re.compile(r"""['"]""" + re.escape(section) + r"""['"]""")


def _has_engine_reader(
    section: str,
    key: str,
    sources: Dict[Path, str],
) -> bool:
    """Return True if any engine-side file shows tier-1 or tier-2 evidence."""
    t1 = _tier1_patterns(section, key)
    section_re = _section_literal_regex(section)
    t2_keys = _tier2_key_subscripts(key)
    for text in sources.values():
        if any(pat in text for pat in t1):
            return True
        if section_re.search(text) and any(pat in text for pat in t2_keys):
            return True
    return False


# ---------------------------------------------------------------------------
# Test-time collection (module-level caches)
# ---------------------------------------------------------------------------

_WIDGET_PAIRS: Set[Tuple[str, str]] = _collect_widget_pairs()
_KNOWN_ZOMBIES: Set[Tuple[str, str]] = _expand_known_zombies(_WIDGET_PAIRS)
_ENGINE_SOURCES: Dict[Path, str] = _load_engine_side_sources()


def _pair_id(pair: Tuple[str, str]) -> str:
    return f"{pair[0]}.{pair[1]}"


_SORTED_PAIRS: List[Tuple[str, str]] = sorted(_WIDGET_PAIRS)


def _param_marks(pair: Tuple[str, str]):
    """Attach the correct ``xfail`` marker (if any) for a widget pair."""
    if pair in _KNOWN_ZOMBIES:
        return [
            pytest.mark.xfail(
                strict=True,
                reason=(
                    "R4.2 baseline — zombie key currently exposed by GUI "
                    "with no engine reader. Task 5 will delete the widget, "
                    "the schema entry, and the VALIDATION_RULES entry; "
                    "Task 5.3 will drop this xfail."
                ),
            )
        ]
    if pair in _CURRENTLY_UNWIRED_BASELINE:
        return [
            pytest.mark.xfail(
                strict=True,
                reason=(
                    "Non-R4.2 baseline — widget pair is unwired in Wave 0 "
                    "but is NOT listed in Requirement 4.2. Either the key "
                    "is GUI-only (SharedState-observed) or its section is "
                    "missing from config.yaml. A later audit-remediation "
                    "task SHALL either wire it to a consumer or remove it; "
                    "when that happens, drop this entry from "
                    "``_CURRENTLY_UNWIRED_BASELINE``."
                ),
            )
        ]
    return []


# ---------------------------------------------------------------------------
# Property 3 — parametrized coverage test
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "pair",
    [
        pytest.param(p, marks=_param_marks(p), id=_pair_id(p))
        for p in _SORTED_PAIRS
    ],
)
def test_every_widget_pair_has_engine_reader(
    pair: Tuple[str, str],
) -> None:
    """Property 3 — every widget ``(section, key)`` has an engine reader.

    The test is parametrized over every ``(section, key)`` pair
    collected from GUI widget-registration literals. For each pair, at
    least one file under ``engines/``, ``capture/``, ``input/``,
    ``utils/``, or ``main.py`` must contain a tier-1 (section-scoped)
    or tier-2 (section-literal + key-subscript) reader pattern.

    Pairs listed in Requirement 4.2 are wrapped with ``xfail(strict=
    True)``; Task 5.3 flips them off. Pairs listed in
    ``_CURRENTLY_UNWIRED_BASELINE`` are wrapped with a distinct
    ``xfail(strict=True)`` so that newly-introduced widget pairs fail
    this test immediately (R40.5).

    **Validates: Requirements 4.1, 4.5, 40.5**
    """
    section, key = pair
    assert _ENGINE_SOURCES, (
        "No engine-side sources were loaded; cannot evaluate Property 3."
    )
    if _has_engine_reader(section, key, _ENGINE_SOURCES):
        return
    t1 = _tier1_patterns(section, key)
    t2 = _tier2_key_subscripts(key)
    pytest.fail(
        "Property 3 violation — widget-exposed config key "
        f"'{section}.{key}' has no engine-side reader.\n"
        f"Tier-1 patterns (section-scoped): {t1}\n"
        f"Tier-2 key subscripts (require section literal in same file): "
        f"{t2}\n"
        f"Engine-side files scanned: {len(_ENGINE_SOURCES)}\n"
        "Requirement 4.1 requires at least one engine/capture/input/utils "
        "reader for every widget-registered key; Requirement 4.5 demands "
        "the regression suite enforce this invariant. If this is a newly-"
        "added key, either add a consumer OR remove the widget; if this "
        "is a legitimate GUI-only state key, add it to "
        "``_CURRENTLY_UNWIRED_BASELINE`` with a justification."
    )


# ---------------------------------------------------------------------------
# Sanity checks — catch scaffolding bugs that would mask real failures
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_widget_registry_is_non_empty() -> None:
    """Smoke: AST walk must discover the GUI widget registry.

    If this returns zero pairs, either the widget-function name set
    drifted away from the code or GUI files cannot be parsed — both
    would make the zombie-coverage test vacuously green.
    """
    assert _WIDGET_PAIRS, (
        "No widget (section, key) pairs were collected from gui/*.py. "
        "Either the widget-function name set drifted, or no GUI files "
        "could be parsed."
    )


@pytest.mark.unit
def test_engine_side_source_corpus_is_non_empty() -> None:
    """Smoke: at least one engine-side ``.py`` source was loaded.

    Without engine-side sources, every pair would trivially fail with
    a confusing ""no engine reader"" message. This test makes the
    loader failure explicit.
    """
    assert _ENGINE_SOURCES, (
        "No engine-side sources loaded; cannot verify Property 3."
    )


@pytest.mark.unit
def test_known_r4_2_zombies_are_detected_in_widget_registry() -> None:
    """Smoke: every specific R4.2 zombie is currently widget-exposed.

    If this fires, either the pair was already removed (drop it from
    ``_SPECIFIC_ZOMBIES``) or the AST walk missed it.
    """
    missing = _SPECIFIC_ZOMBIES - _WIDGET_PAIRS
    assert not missing, (
        "R4.2 specific zombie keys not found in widget registry: "
        f"{sorted(missing)}. Either they were already removed (good — "
        "drop them from ``_SPECIFIC_ZOMBIES``) or the AST walk missed "
        "them."
    )


@pytest.mark.unit
def test_wildcard_zombie_sections_are_expanded_against_widget_registry() -> (
    None
):
    """Smoke: every R4.2 wildcard section contributes at least one pair.

    If a wildcard section contributes zero pairs, either every widget
    under that section has been removed (good — drop the section from
    ``_WILDCARD_ZOMBIE_SECTIONS``) or the widget scanner missed them.
    """
    covered = {section for section, _ in _KNOWN_ZOMBIES}
    missing_sections = _WILDCARD_ZOMBIE_SECTIONS - covered
    assert not missing_sections, (
        "R4.2 wildcard zombie sections contributed zero widget pairs: "
        f"{sorted(missing_sections)}. Either Task 5 already removed them "
        "(drop the section from ``_WILDCARD_ZOMBIE_SECTIONS``) or the "
        "widget scanner missed them."
    )


@pytest.mark.unit
def test_r4_2_and_baseline_unwired_sets_are_disjoint() -> None:
    """Smoke: the two xfail categories do not overlap.

    R4.2 zombies have a distinct semantics (""deleted by Task 5.3"")
    from the baseline-unwired set (""wired or removed by a later
    task""). Overlapping the two would hide which task is responsible
    for flipping the xfail off.
    """
    overlap = _KNOWN_ZOMBIES & _CURRENTLY_UNWIRED_BASELINE
    assert not overlap, (
        "R4.2 known zombies and baseline-unwired set overlap for: "
        f"{sorted(overlap)}. Move the entry to exactly one of the two "
        "sets based on which task resolves it."
    )


@pytest.mark.unit
def test_tier1_reader_patterns_shape() -> None:
    """``_tier1_patterns`` returns the documented substring set.

    Guards against silent drift of the patterns; if this test updates,
    the docstring of ``_tier1_patterns`` must update with it.
    """
    patterns = _tier1_patterns("aim", "speed")
    assert patterns == [
        '["aim"]["speed"]',
        "['aim']['speed']",
        '.get("aim", {}).get("speed"',
        ".get('aim', {}).get('speed'",
        '"aim.speed"',
        "'aim.speed'",
    ]


@pytest.mark.unit
def test_tier2_key_subscripts_shape() -> None:
    """``_tier2_key_subscripts`` returns the documented substring set."""
    assert _tier2_key_subscripts("speed") == [
        '.get("speed"',
        ".get('speed'",
        '["speed"]',
        "['speed']",
    ]
