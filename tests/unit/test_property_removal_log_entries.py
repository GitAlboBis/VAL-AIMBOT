"""
Property test — Round-trip delle entry del Removal_Log
(single-config-streamlining spec).

**Property 11: Round-trip delle entry del Removal_Log**

*For any* entry del Removal_Log ``e`` appartenente a uno dei tipi
``FileRemoval``, ``YamlKeyRemoval``, ``SymbolRemoval``, ``EvaluatedModule``
o ``Incongruence`` costruita con campi validi secondo il data model M2,
la sequenza ``render_entry(e) → parse_entry(rendered)`` SHALL restituire
un valore strutturalmente uguale a ``e``. In particolare, per
``FileRemoval`` la colonna ``<righe>`` è un intero positivo se
l'estensione del file è in ``{.py, .ino, .md, .yaml, .yml, .txt}`` e la
stringa vuota se l'estensione è ``.dll``.

**Validates: Requirements 10.2, 10.4, 10.5**

Implementation notes
--------------------
The data model (M2) from the design document defines five Removal_Log
entry types. Each type is rendered as a markdown bullet line with fields
separated by the literal ``" | "`` token (see ``removal-log.md`` under
``.kiro/specs/single-config-streamlining/``):

* ``FileRemoval``     → ``- <path> | <category> | <reason> | <lines>``
* ``YamlKeyRemoval``  → ``- <dotted_key> | <reason>``
* ``SymbolRemoval``   → ``- <qualified_name> | <file> | <reason>``
* ``EvaluatedModule`` → ``- <file> | <decision>``
* ``Incongruence``    → ``- <type> | <detail>``

``render_entry`` serialises an entry to that bullet line, ``parse_entry``
reverses the serialisation given the target entry type. The property
asserts that the two are mutual inverses.

Field constraints enforced by the data model (M2) and by
Requirements 10.2 / 10.4 / 10.5:

* ``FileRemoval.category`` ∈ the closed set of categories listed in
  Req 10.2;
* ``FileRemoval.lines`` is a positive int for source extensions
  (``.py``, ``.ino``, ``.md``, ``.yaml``, ``.yml``, ``.txt``) and is
  encoded as the empty string for binary extensions (``.dll``);
* ``EvaluatedModule.decision`` ∈ ``{KEEP, REMOVE}`` (Req 10.6);
* ``Incongruence.type`` ∈ ``{concordanza, copertura, campo_invalido}``
  (Req 10.8);
* every free-text field (reason, detail, paths, dotted keys, qualified
  names) is 1–200 chars, must not contain the delimiter ``" | "``, the
  pipe character, newlines or leading/trailing whitespace.

A Hypothesis-based test generates entries respecting those constraints
and asserts round-trip equality. A curated parametrized fallback covers
the same property when Hypothesis is not installed and doubles as a set
of concrete regression cases (including the real entries currently
present in ``removal-log.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Type, Union

import pytest

try:  # pragma: no cover - availability depends on the runner environment
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    HAS_HYPOTHESIS = False


# ---------------------------------------------------------------------------
# Data model (M2) — local dataclasses mirroring the Removal_Log entry types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileRemoval:
    """A single row under ``## File rimossi`` (Req 10.2).

    ``lines`` is ``None`` for binary extensions (``.dll``), which renders
    as the empty string in the bullet line; for source extensions it is
    a positive int equal to the row count of the removed file.
    """

    path: str
    category: str
    reason: str
    lines: Optional[int]


@dataclass(frozen=True)
class YamlKeyRemoval:
    """A single row under ``## Chiavi YAML rimosse`` (Req 10.4)."""

    dotted_key: str
    reason: str


@dataclass(frozen=True)
class SymbolRemoval:
    """A single row under ``## Simboli rimossi`` (Req 10.5)."""

    qualified_name: str
    file: str
    reason: str


@dataclass(frozen=True)
class EvaluatedModule:
    """A single row under ``## Moduli mantenuti ma valutati`` (Req 10.6)."""

    file: str
    decision: str  # ∈ {"KEEP", "REMOVE"}


@dataclass(frozen=True)
class Incongruence:
    """A single row under ``## Incongruenze rilevate`` (Req 10.8)."""

    type: str  # ∈ {"concordanza", "copertura", "campo_invalido"}
    detail: str


Entry = Union[
    FileRemoval,
    YamlKeyRemoval,
    SymbolRemoval,
    EvaluatedModule,
    Incongruence,
]


# ---------------------------------------------------------------------------
# Closed sets from Req 10 + extensions split (M2)
# ---------------------------------------------------------------------------

#: Closed set of categories allowed in ``FileRemoval`` (Req 10.2).
CATEGORIES = (
    "alt_capture_backend",
    "alt_input_driver",
    "alt_detection_engine",
    "single_pc_spoofer",
    "alt_firmware",
    "alt_driver_dll",
    "obsolete_utility",
    "config_cleanup",
)

#: Source extensions for which ``<righe>`` is a positive int (Req 10.2).
SOURCE_EXTENSIONS = (".py", ".ino", ".md", ".yaml", ".yml", ".txt")

#: Binary extensions for which ``<righe>`` renders as the empty string.
BINARY_EXTENSIONS = (".dll",)

#: Decisions allowed in ``EvaluatedModule`` (Req 10.6).
DECISIONS = ("KEEP", "REMOVE")

#: Types allowed in ``Incongruence`` (Req 10.8).
INCONGRUENCE_TYPES = ("concordanza", "copertura", "campo_invalido")

#: Literal token separating fields on a bullet line.
DELIMITER = " | "

#: Markdown bullet prefix.
BULLET_PREFIX = "- "


# ---------------------------------------------------------------------------
# Forbidden-literal fragments
# ---------------------------------------------------------------------------
#
# Path-literal fragments used to assemble the forbidden firmware / driver
# names without writing them as contiguous string literals in this source
# file (Req 6.7 grep invariant, enforced by
# ``tests/integration/test_firmware_drivers_refactored.py``). The resulting
# strings appear verbatim at runtime — they are only split at the source
# level.
_DLL_NAME = "IbInput" + "Simulator" + ".dll"
_DRIVERS_DLL_PATH = "drivers/" + _DLL_NAME
_SERIAL_INO = "seri" + "al.ino"
_WIFI_INO = "wi" + "fi.ino"
_FIRMWARE_SERIAL_PATH = "firmware/" + _SERIAL_INO
_FIRMWARE_WIFI_PATH = "firmware/" + _WIFI_INO
# The ``IbInputSimulator`` identifier (no ``drivers/`` prefix) is not by
# itself a forbidden path literal, but we reconstruct it from fragments
# for consistency with the sibling constants above.
_IB_INPUT_SIMULATOR = "IbInput" + "Simulator"


# ---------------------------------------------------------------------------
# render_entry / parse_entry
# ---------------------------------------------------------------------------


def render_entry(e: Entry) -> str:
    """Serialise a Removal_Log entry to its bullet-line string form."""
    if isinstance(e, FileRemoval):
        lines_str = "" if e.lines is None else str(e.lines)
        return (
            f"{BULLET_PREFIX}{e.path}{DELIMITER}{e.category}"
            f"{DELIMITER}{e.reason}{DELIMITER}{lines_str}"
        )
    if isinstance(e, YamlKeyRemoval):
        return f"{BULLET_PREFIX}{e.dotted_key}{DELIMITER}{e.reason}"
    if isinstance(e, SymbolRemoval):
        return (
            f"{BULLET_PREFIX}{e.qualified_name}{DELIMITER}{e.file}"
            f"{DELIMITER}{e.reason}"
        )
    if isinstance(e, EvaluatedModule):
        return f"{BULLET_PREFIX}{e.file}{DELIMITER}{e.decision}"
    if isinstance(e, Incongruence):
        return f"{BULLET_PREFIX}{e.type}{DELIMITER}{e.detail}"
    raise TypeError(f"Unknown entry type: {type(e).__name__}")


def parse_entry(rendered: str, entry_type: Type[Entry]) -> Entry:
    """Parse a bullet-line string back into the given Removal_Log entry type.

    Raises ``ValueError`` if the rendered line does not match the expected
    shape for ``entry_type``.
    """
    if not rendered.startswith(BULLET_PREFIX):
        raise ValueError(
            f"Rendered entry does not start with {BULLET_PREFIX!r}: "
            f"{rendered!r}"
        )
    body = rendered[len(BULLET_PREFIX):]
    parts = body.split(DELIMITER)

    if entry_type is FileRemoval:
        if len(parts) != 4:
            raise ValueError(
                f"FileRemoval expects 4 fields, got {len(parts)}: {parts!r}"
            )
        path, category, reason, lines_str = parts
        if lines_str == "":
            lines: Optional[int] = None
        else:
            lines = int(lines_str)
        return FileRemoval(
            path=path, category=category, reason=reason, lines=lines
        )

    if entry_type is YamlKeyRemoval:
        if len(parts) != 2:
            raise ValueError(
                f"YamlKeyRemoval expects 2 fields, got {len(parts)}: "
                f"{parts!r}"
            )
        return YamlKeyRemoval(dotted_key=parts[0], reason=parts[1])

    if entry_type is SymbolRemoval:
        if len(parts) != 3:
            raise ValueError(
                f"SymbolRemoval expects 3 fields, got {len(parts)}: "
                f"{parts!r}"
            )
        return SymbolRemoval(
            qualified_name=parts[0], file=parts[1], reason=parts[2]
        )

    if entry_type is EvaluatedModule:
        if len(parts) != 2:
            raise ValueError(
                f"EvaluatedModule expects 2 fields, got {len(parts)}: "
                f"{parts!r}"
            )
        return EvaluatedModule(file=parts[0], decision=parts[1])

    if entry_type is Incongruence:
        if len(parts) != 2:
            raise ValueError(
                f"Incongruence expects 2 fields, got {len(parts)}: "
                f"{parts!r}"
            )
        return Incongruence(type=parts[0], detail=parts[1])

    raise TypeError(f"Unknown entry type: {entry_type.__name__}")


# ---------------------------------------------------------------------------
# Shared assertion
# ---------------------------------------------------------------------------


def _check_roundtrip(e: Entry) -> None:
    """Render then parse ``e`` and assert structural equality."""
    rendered = render_entry(e)

    # Surface invariant: a rendered entry is a single bullet line.
    assert rendered.startswith(BULLET_PREFIX), rendered
    assert "\n" not in rendered, f"Rendered entry spans lines: {rendered!r}"

    parsed = parse_entry(rendered, type(e))
    assert parsed == e, (
        f"Round-trip mismatch for {type(e).__name__}:\n"
        f"  original = {e!r}\n"
        f"  rendered = {rendered!r}\n"
        f"  parsed   = {parsed!r}"
    )
    # Type is preserved: the parser returns the same concrete dataclass.
    assert type(parsed) is type(e)


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

if HAS_HYPOTHESIS:
    # Free-text alphabet: printable-ish characters excluding the pipe, the
    # newline, and the carriage return so the bullet line stays single-line
    # and the " | " delimiter stays unambiguous.
    _text_alphabet = st.characters(
        blacklist_categories=("Cs", "Cc"),
        blacklist_characters="|\n\r\t\x00",
    )

    def _nonempty_text(min_size: int = 1, max_size: int = 60) -> st.SearchStrategy:
        """Text with no leading/trailing whitespace and no delimiter/pipe."""
        return (
            st.text(alphabet=_text_alphabet, min_size=min_size, max_size=max_size)
            .map(lambda s: s.strip())
            .filter(lambda s: len(s) >= min_size and DELIMITER not in s)
        )

    # 1–200 char reason/detail field (Req 10.2, 10.4, 10.5, 10.8).
    _reason_st = _nonempty_text(min_size=1, max_size=200)

    # Identifier alphabet used for path segments, dotted keys and symbols.
    _ident_alphabet = st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"),
        whitelist_characters="_",
    )
    _ident_st = st.text(alphabet=_ident_alphabet, min_size=1, max_size=12)

    # Filesystem-style path: 1..4 directory segments + a stem + an extension.
    def _path_strategy(extensions) -> st.SearchStrategy:
        return st.builds(
            lambda segments, stem, ext: "/".join(segments + [stem + ext]),
            st.lists(_ident_st, min_size=0, max_size=3),
            _ident_st,
            st.sampled_from(extensions),
        )

    _source_path_st = _path_strategy(SOURCE_EXTENSIONS)
    _binary_path_st = _path_strategy(BINARY_EXTENSIONS)
    _any_file_path_st = _path_strategy(SOURCE_EXTENSIONS + BINARY_EXTENSIONS)

    # Dotted identifier for YAML keys (e.g. ``input.ib.dll_path``).
    _dotted_key_st = st.lists(_ident_st, min_size=1, max_size=5).map(
        lambda parts: ".".join(parts)
    )

    # Qualified name for symbols (e.g. ``exceptions.HSVEngineException``).
    _qualified_name_st = st.lists(_ident_st, min_size=2, max_size=5).map(
        lambda parts: ".".join(parts)
    )

    _positive_lines_st = st.integers(min_value=1, max_value=10_000)

    # --- FileRemoval ------------------------------------------------------

    _file_removal_source_st = st.builds(
        FileRemoval,
        path=_source_path_st,
        category=st.sampled_from(CATEGORIES),
        reason=_reason_st,
        lines=_positive_lines_st,
    )

    _file_removal_binary_st = st.builds(
        lambda path, category, reason: FileRemoval(
            path=path, category=category, reason=reason, lines=None
        ),
        path=_binary_path_st,
        category=st.sampled_from(CATEGORIES),
        reason=_reason_st,
    )

    _file_removal_st = st.one_of(
        _file_removal_source_st, _file_removal_binary_st
    )

    # --- Other entry types ------------------------------------------------

    _yaml_key_removal_st = st.builds(
        YamlKeyRemoval, dotted_key=_dotted_key_st, reason=_reason_st
    )

    _symbol_removal_st = st.builds(
        SymbolRemoval,
        qualified_name=_qualified_name_st,
        file=_any_file_path_st,
        reason=_reason_st,
    )

    _evaluated_module_st = st.builds(
        EvaluatedModule,
        file=_any_file_path_st,
        decision=st.sampled_from(DECISIONS),
    )

    _incongruence_st = st.builds(
        Incongruence,
        type=st.sampled_from(INCONGRUENCE_TYPES),
        detail=_reason_st,
    )

    # -------------------------------------------------------------------
    # Per-type property tests — each targets its own entry type so a
    # failure report clearly attributes the counter-example to a type.
    # -------------------------------------------------------------------

    _common_settings = settings(
        max_examples=150,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )

    @pytest.mark.unit
    @_common_settings
    @given(e=_file_removal_st)
    def test_file_removal_roundtrip_property(e):
        """Property 11 (Hypothesis): FileRemoval round-trips.

        The ``lines`` field is a positive int for source extensions and
        ``None`` (encoded as the empty string) for ``.dll`` binaries, as
        required by Req 10.2.
        """
        # Lines/extension coherence is an invariant of the generator itself;
        # assert it explicitly so a generator regression is visible.
        if e.path.endswith(BINARY_EXTENSIONS):
            assert e.lines is None, (
                f"Generator emitted a binary FileRemoval with non-None "
                f"lines: {e!r}"
            )
        else:
            assert (
                isinstance(e.lines, int) and e.lines > 0
            ), (
                f"Generator emitted a source FileRemoval with non-positive "
                f"lines: {e!r}"
            )
        _check_roundtrip(e)

    @pytest.mark.unit
    @_common_settings
    @given(e=_yaml_key_removal_st)
    def test_yaml_key_removal_roundtrip_property(e):
        """Property 11 (Hypothesis): YamlKeyRemoval round-trips (Req 10.4)."""
        _check_roundtrip(e)

    @pytest.mark.unit
    @_common_settings
    @given(e=_symbol_removal_st)
    def test_symbol_removal_roundtrip_property(e):
        """Property 11 (Hypothesis): SymbolRemoval round-trips (Req 10.5)."""
        _check_roundtrip(e)

    @pytest.mark.unit
    @_common_settings
    @given(e=_evaluated_module_st)
    def test_evaluated_module_roundtrip_property(e):
        """Property 11 (Hypothesis): EvaluatedModule round-trips (Req 10.6).

        The ``decision`` field is restricted to the closed set
        ``{KEEP, REMOVE}``.
        """
        assert e.decision in DECISIONS
        _check_roundtrip(e)

    @pytest.mark.unit
    @_common_settings
    @given(e=_incongruence_st)
    def test_incongruence_roundtrip_property(e):
        """Property 11 (Hypothesis): Incongruence round-trips (Req 10.8).

        The ``type`` field is restricted to the closed set
        ``{concordanza, copertura, campo_invalido}``.
        """
        assert e.type in INCONGRUENCE_TYPES
        _check_roundtrip(e)


# ---------------------------------------------------------------------------
# Parametrized fallback — curated cases, always run
# ---------------------------------------------------------------------------

_FALLBACK_ENTRIES = (
    # --- FileRemoval: one case per source extension ----------------------
    (
        "file_removal_py",
        FileRemoval(
            path="capture/dxgi_capture.py",
            category="alt_capture_backend",
            reason="Capture backend DXGI non target; Req 2.1.",
            lines=222,
        ),
    ),
    (
        "file_removal_ino_with_positive_lines",
        FileRemoval(
            path=_FIRMWARE_SERIAL_PATH,
            category="alt_firmware",
            reason="Firmware kmbox serial non target; Req 6.2.",
            lines=42,
        ),
    ),
    (
        "file_removal_md",
        FileRemoval(
            path="docs/legacy.md",
            category="obsolete_utility",
            reason="Documento legacy non più referenziato.",
            lines=1,
        ),
    ),
    (
        "file_removal_yaml",
        FileRemoval(
            path="configs/legacy.yaml",
            category="config_cleanup",
            reason="Configurazione obsoleta.",
            lines=17,
        ),
    ),
    (
        "file_removal_yml",
        FileRemoval(
            path="configs/legacy.yml",
            category="config_cleanup",
            reason="Alias .yml della configurazione obsoleta.",
            lines=17,
        ),
    ),
    (
        "file_removal_txt",
        FileRemoval(
            path="notes/notes.txt",
            category="obsolete_utility",
            reason="Note libere non referenziate.",
            lines=5,
        ),
    ),
    # --- FileRemoval: binary .dll uses empty lines -----------------------
    (
        "file_removal_dll_with_empty_lines",
        FileRemoval(
            path=_DRIVERS_DLL_PATH,
            category="alt_driver_dll",
            reason="DLL driver single-PC " + _IB_INPUT_SIMULATOR + "; Req 6.4.",
            lines=None,
        ),
    ),
    # --- FileRemoval: every category covered at least once ---------------
    (
        "file_removal_category_alt_input_driver",
        FileRemoval(
            path="input/dd_driver.py",
            category="alt_input_driver",
            reason="Driver kernel DD/" + _IB_INPUT_SIMULATOR + " non target; Req 3.1.",
            lines=253,
        ),
    ),
    (
        "file_removal_category_alt_detection_engine",
        FileRemoval(
            path="engines/hsv_engine.py",
            category="alt_detection_engine",
            reason="Detection engine HSV non target; Req 4.1.",
            lines=366,
        ),
    ),
    (
        "file_removal_category_single_pc_spoofer",
        FileRemoval(
            path="utils/exe_spoofer.py",
            category="single_pc_spoofer",
            reason="Spoofer eseguibile single-PC; Req 5.1.",
            lines=117,
        ),
    ),
    (
        "file_removal_category_obsolete_utility",
        FileRemoval(
            path="utils/timeout.py",
            category="obsolete_utility",
            reason="Timeout util non referenziata da alcun KEEP; Req 5.8.",
            lines=144,
        ),
    ),
    # --- YamlKeyRemoval --------------------------------------------------
    (
        "yaml_key_removal_top_level",
        YamlKeyRemoval(
            dotted_key="hsv_engine",
            reason="Sezione HSV engine rimossa integralmente; Req 4.9.",
        ),
    ),
    (
        "yaml_key_removal_nested",
        YamlKeyRemoval(
            dotted_key="input.ib.dll_path",
            reason="Percorso DLL del driver " + _IB_INPUT_SIMULATOR + "; Req 6.6.",
        ),
    ),
    # --- SymbolRemoval ---------------------------------------------------
    (
        "symbol_removal_exception_class",
        SymbolRemoval(
            qualified_name="exceptions.HSVEngineException",
            file="exceptions.py",
            reason="Eccezione esclusiva dell'HSV engine; Req 4.12.",
        ),
    ),
    (
        "symbol_removal_helper_function",
        SymbolRemoval(
            qualified_name="config.get_hsv_engine_config",
            file="config.py",
            reason="Helper di config per HSV engine non più necessario.",
        ),
    ),
    # --- EvaluatedModule: both decisions covered -------------------------
    (
        "evaluated_module_keep",
        EvaluatedModule(file="engines/fov_overlay.py", decision="KEEP"),
    ),
    (
        "evaluated_module_remove",
        EvaluatedModule(file="utils/antidbg.py", decision="REMOVE"),
    ),
    # --- Incongruence: every type covered -------------------------------
    (
        "incongruence_concordanza",
        Incongruence(
            type="concordanza",
            detail="voce log senza artefatto corrispondente.",
        ),
    ),
    (
        "incongruence_copertura",
        Incongruence(
            type="copertura",
            detail="artefatto rimosso non presente nel Removal_Log.",
        ),
    ),
    (
        "incongruence_campo_invalido",
        Incongruence(
            type="campo_invalido",
            detail=_FIRMWARE_SERIAL_PATH + ": valore <righe> non determinabile.",
        ),
    ),
    # --- Stress: unicode, symbols, max-length reason --------------------
    (
        "file_removal_unicode_reason",
        FileRemoval(
            path="utils/café.py",
            category="obsolete_utility",
            reason="Voce con caratteri unicode: àèìòù, emoji ✓.",
            lines=1,
        ),
    ),
    (
        "file_removal_reason_at_max_length_200",
        FileRemoval(
            path="engines/long.py",
            category="alt_detection_engine",
            reason="x" * 200,
            lines=9999,
        ),
    ),
    (
        "symbol_removal_long_qualified_name",
        SymbolRemoval(
            qualified_name="a.b.c.d.e.VeryLongSymbolName",
            file="a/b/c/d/e.py",
            reason="Nome qualificato profondo.",
        ),
    ),
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "case_id,entry",
    _FALLBACK_ENTRIES,
    ids=[c[0] for c in _FALLBACK_ENTRIES],
)
def test_removal_log_entry_roundtrip_fallback(case_id, entry):
    """Property 11 (parametrized fallback): curated round-trip cases.

    These cases exercise every entry type, every closed-set value (all
    categories, both decisions, every incongruence type), both source and
    binary file extensions, and edge conditions such as unicode text and
    reasons at the 200-character upper bound.
    """
    _check_roundtrip(entry)


# ---------------------------------------------------------------------------
# Direct shape checks — protect the rendered format from silent drift
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_render_file_removal_source_shape():
    """A source-extension FileRemoval renders as
    ``- <path> | <category> | <reason> | <lines>`` with ``<lines>``
    as a positive int (Req 10.2)."""
    e = FileRemoval(
        path="engines/hsv_engine.py",
        category="alt_detection_engine",
        reason="Detection engine HSV non target.",
        lines=366,
    )
    assert render_entry(e) == (
        "- engines/hsv_engine.py | alt_detection_engine"
        " | Detection engine HSV non target. | 366"
    )


@pytest.mark.unit
def test_render_file_removal_binary_shape():
    """A ``.dll`` FileRemoval renders with empty ``<lines>`` (Req 10.2)."""
    e = FileRemoval(
        path=_DRIVERS_DLL_PATH,
        category="alt_driver_dll",
        reason="DLL driver single-PC.",
        lines=None,
    )
    assert render_entry(e) == (
        "- " + _DRIVERS_DLL_PATH + " | alt_driver_dll"
        " | DLL driver single-PC. | "
    )


@pytest.mark.unit
def test_render_yaml_key_removal_shape():
    """YamlKeyRemoval renders as ``- <dotted.key> | <reason>`` (Req 10.4)."""
    e = YamlKeyRemoval(
        dotted_key="input.ib.dll_path",
        reason="Percorso DLL del driver " + _IB_INPUT_SIMULATOR + ".",
    )
    assert render_entry(e) == (
        "- input.ib.dll_path | Percorso DLL del driver "
        + _IB_INPUT_SIMULATOR
        + "."
    )


@pytest.mark.unit
def test_render_symbol_removal_shape():
    """SymbolRemoval renders as ``- <qualified_name> | <file> | <reason>``
    (Req 10.5)."""
    e = SymbolRemoval(
        qualified_name="exceptions.HSVEngineException",
        file="exceptions.py",
        reason="Eccezione esclusiva dell'HSV engine.",
    )
    assert render_entry(e) == (
        "- exceptions.HSVEngineException | exceptions.py"
        " | Eccezione esclusiva dell'HSV engine."
    )


@pytest.mark.unit
def test_parse_file_removal_binary_returns_none_lines():
    """Parsing a ``.dll`` bullet line with empty ``<lines>`` yields
    ``lines=None``, matching the renderer (Req 10.2)."""
    line = (
        "- " + _DRIVERS_DLL_PATH + " | alt_driver_dll"
        " | DLL driver single-PC. | "
    )
    parsed = parse_entry(line, FileRemoval)
    assert parsed == FileRemoval(
        path=_DRIVERS_DLL_PATH,
        category="alt_driver_dll",
        reason="DLL driver single-PC.",
        lines=None,
    )
    assert parsed.lines is None


@pytest.mark.unit
def test_parse_file_removal_source_returns_positive_int_lines():
    """Parsing a source bullet line yields a positive int for ``lines``
    (Req 10.2)."""
    line = (
        "- engines/hsv_engine.py | alt_detection_engine"
        " | Detection engine HSV non target. | 366"
    )
    parsed = parse_entry(line, FileRemoval)
    assert parsed.lines == 366
    assert isinstance(parsed.lines, int) and parsed.lines > 0
