"""Integration tests for the Removal_Log structure.

Task 16.2 of the ``single-config-streamlining`` spec verifies that
``.kiro/specs/single-config-streamlining/removal-log.md`` satisfies the
structural invariants required by Requirements 10.1, 10.3, 10.6 and
10.7:

* **10.1** — The file exists and contains exactly six ``##`` top-level
  sections in the exact order:
  ``File rimossi``, ``Chiavi YAML rimosse``, ``Simboli rimossi``,
  ``Moduli mantenuti ma valutati``, ``Dead_Reference risolti``,
  ``Incongruenze rilevate``. Empty sections contain the literal string
  ``_Nessuna voce._``.
* **10.3** — Entries under ``## Incongruenze rilevate`` use the
  ``- <tipo> | <dettaglio>`` form with ``<tipo>`` in the closed set
  ``{concordanza, copertura, campo_invalido}``.
* **10.6** — Entries under ``## Moduli mantenuti ma valutati`` use the
  ``- <file> | <decisione>`` form with ``<decisione>`` in
  ``{KEEP, REMOVE}``.
* **10.7** — ``## Dead_Reference risolti`` contains ``### <file>``
  sub-sections whose bullets match ``- linea <N>: <descrizione>``.

Additionally — as required by task 16.2 — the bullet format of each
other section is validated against the shapes prescribed by
Requirements 10.2, 10.4 and 10.5:

* ``## File rimossi`` — ``- <path> | <categoria> | <motivo> | <righe>``
  with ``<categoria>`` in the closed set
  ``{alt_capture_backend, alt_input_driver, alt_detection_engine,
  single_pc_spoofer, alt_firmware, alt_driver_dll, obsolete_utility,
  config_cleanup}``; ``<righe>`` is an integer for
  ``.py/.ino/.md/.yaml/.yml/.txt`` files and empty for ``.dll``.
* ``## Chiavi YAML rimosse`` — ``- <dotted.key> | <motivo>``.
* ``## Simboli rimossi`` — ``- <modulo.Simbolo> | <file> | <motivo>``.

The tests only parse the Removal_Log via regex; they do not modify the
filesystem and do not depend on any application code beyond ``pytest``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

import pytest


pytestmark = pytest.mark.integration


# --- Workspace layout -----------------------------------------------------

_WORKSPACE = Path(__file__).resolve().parents[2]
_REMOVAL_LOG_PATH = (
    _WORKSPACE
    / ".kiro"
    / "specs"
    / "single-config-streamlining"
    / "removal-log.md"
)

# Exact section headers, in the order required by Req 10.1.
_EXPECTED_SECTIONS: Tuple[str, ...] = (
    "File rimossi",
    "Chiavi YAML rimosse",
    "Simboli rimossi",
    "Moduli mantenuti ma valutati",
    "Dead_Reference risolti",
    "Incongruenze rilevate",
)

# Literal placeholder required for empty sections (Req 10.1).
_EMPTY_PLACEHOLDER = "_Nessuna voce._"

# Allowed category values for ``## File rimossi`` (Req 10.2).
_ALLOWED_CATEGORIES = frozenset(
    {
        "alt_capture_backend",
        "alt_input_driver",
        "alt_detection_engine",
        "single_pc_spoofer",
        "alt_firmware",
        "alt_driver_dll",
        "obsolete_utility",
        "config_cleanup",
    }
)

# Allowed decisione values for ``## Moduli mantenuti ma valutati`` (Req 10.6).
_ALLOWED_DECISIONS = frozenset({"KEEP", "REMOVE"})

# Allowed tipo values for ``## Incongruenze rilevate`` (Req 10.3 / 10.8).
_ALLOWED_INCONGRUENZA_TYPES = frozenset(
    {"concordanza", "copertura", "campo_invalido"}
)

# Extensions that must carry an explicit line count in ``<righe>`` (Req 10.2).
_TEXT_EXTENSIONS = (".py", ".ino", ".md", ".yaml", ".yml", ".txt")


# --- Helpers --------------------------------------------------------------


def _split_pipe_fields(bullet_body: str) -> List[str]:
    """Split a bullet body on the `` | `` separator (space-pipe-space).

    The Removal_Log uses `` | `` as the column separator within bullets.
    We split without stripping the individual fields so that callers can
    explicitly validate leading/trailing whitespace when needed.
    """
    return bullet_body.split(" | ")


def _iter_section_bullets(body: str) -> List[str]:
    """Return the list of top-level bullet lines in a section body.

    Top-level bullets are lines that start with ``- `` (two characters,
    hyphen + space) at column zero. Indented bullets, if any, are
    ignored here — the Dead_Reference section handles its own parsing
    because it is structured as ``### <file>`` sub-sections with bullets
    underneath.
    """
    return [line for line in body.splitlines() if line.startswith("- ")]


# --- Fixtures -------------------------------------------------------------


@pytest.fixture(scope="module")
def removal_log_text() -> str:
    """Load the Removal_Log as UTF-8 text, asserting its existence.

    Req 10.1 mandates that the file exists at the canonical path and is
    UTF-8 encoded. We read with ``encoding='utf-8'`` and ``strict``
    error handling so that any non-UTF-8 byte surfaces as a test
    failure.
    """
    assert _REMOVAL_LOG_PATH.is_file(), (
        f"Removal_Log not found at {_REMOVAL_LOG_PATH}"
    )
    return _REMOVAL_LOG_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sections(removal_log_text: str) -> Dict[str, str]:
    """Parse the Removal_Log into a mapping ``header -> section body``.

    The body of a section is everything between its ``## <header>`` line
    and the next ``## `` header (or end of file). Sub-section ``###``
    headers inside a section are preserved in the body.
    """
    # Match ``## <title>`` captures the title; we use a finditer-based
    # splitter so that the order of sections is available as well.
    pattern = re.compile(r"^##\s+(.+?)\s*$", flags=re.MULTILINE)
    matches = list(pattern.finditer(removal_log_text))
    assert matches, "Removal_Log contains no ``##`` sections"

    result: Dict[str, str] = {}
    for idx, match in enumerate(matches):
        title = match.group(1)
        body_start = match.end()
        body_end = (
            matches[idx + 1].start() if idx + 1 < len(matches) else len(
                removal_log_text
            )
        )
        result[title] = removal_log_text[body_start:body_end]
    return result


@pytest.fixture(scope="module")
def section_order(removal_log_text: str) -> List[str]:
    """Return the ``##`` section titles in document order."""
    pattern = re.compile(r"^##\s+(.+?)\s*$", flags=re.MULTILINE)
    return [m.group(1) for m in pattern.finditer(removal_log_text)]


# --- Tests: file existence & section order (Req 10.1) ---------------------


class TestFileAndSectionOrder:
    """Verify Req 10.1 — file existence, section count and order."""

    def test_file_exists(self) -> None:
        assert _REMOVAL_LOG_PATH.is_file(), (
            f"Removal_Log must exist at {_REMOVAL_LOG_PATH}"
        )

    def test_section_order_matches_specification(
        self, section_order: List[str]
    ) -> None:
        assert section_order == list(_EXPECTED_SECTIONS), (
            "The six ``##`` sections must appear in the exact order "
            f"{_EXPECTED_SECTIONS}; found {section_order}"
        )

    def test_no_extra_sections(self, section_order: List[str]) -> None:
        assert len(section_order) == len(_EXPECTED_SECTIONS), (
            "Removal_Log must contain exactly six ``##`` sections; "
            f"found {len(section_order)}: {section_order}"
        )


# --- Tests: empty-section placeholder (Req 10.1) --------------------------


class TestEmptySectionPlaceholder:
    """Sections with no bullets must contain ``_Nessuna voce._``."""

    def test_empty_sections_use_literal_placeholder(
        self, sections: Dict[str, str]
    ) -> None:
        for header in _EXPECTED_SECTIONS:
            body = sections[header]
            has_top_bullet = any(
                line.startswith("- ") for line in body.splitlines()
            )
            has_subsection = any(
                line.startswith("### ") for line in body.splitlines()
            )
            if has_top_bullet or has_subsection:
                continue
            assert _EMPTY_PLACEHOLDER in body, (
                f"Section ``## {header}`` has no entries and therefore "
                f"must contain the literal string ``{_EMPTY_PLACEHOLDER}``"
            )


# --- Tests: ``## File rimossi`` format ------------------------------------

# ``<path>`` — no whitespace, no pipe; forward slash allowed.
_PATH_RE = re.compile(r"^[^\s|]+$")
# ``<righe>`` — either an integer or empty for ``.dll`` files.
_RIGHE_RE = re.compile(r"^\d*$")


class TestFileRimossiFormat:
    """Req 10.2 — ``- <path> | <categoria> | <motivo> | <righe>``."""

    def test_bullets_have_four_fields(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(sections["File rimossi"]):
            fields = _split_pipe_fields(bullet[2:])
            assert len(fields) == 4, (
                f"File rimossi bullet must expose 4 ``|``-separated fields; "
                f"got {len(fields)} in {bullet!r}"
            )

    def test_path_uses_forward_slash_and_no_pipe(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(sections["File rimossi"]):
            path = _split_pipe_fields(bullet[2:])[0].strip()
            assert _PATH_RE.match(path), (
                f"File rimossi path must have no whitespace/pipe: {path!r}"
            )
            assert "\\" not in path, (
                f"File rimossi path must use ``/`` as separator: {path!r}"
            )

    def test_categoria_in_allowed_set(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(sections["File rimossi"]):
            categoria = _split_pipe_fields(bullet[2:])[1].strip()
            assert categoria in _ALLOWED_CATEGORIES, (
                f"``categoria``={categoria!r} not in {_ALLOWED_CATEGORIES}; "
                f"bullet: {bullet!r}"
            )

    def test_motivo_length_between_1_and_200(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(sections["File rimossi"]):
            motivo = _split_pipe_fields(bullet[2:])[2].strip()
            assert 1 <= len(motivo) <= 200, (
                f"``motivo`` length {len(motivo)} out of range [1,200] "
                f"in bullet {bullet!r}"
            )

    def test_righe_integer_for_text_empty_for_dll(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(sections["File rimossi"]):
            fields = _split_pipe_fields(bullet[2:])
            path = fields[0].strip()
            righe = fields[3].strip()
            assert _RIGHE_RE.match(righe), (
                f"``righe`` must be an integer or empty; got {righe!r} "
                f"in bullet {bullet!r}"
            )
            if path.lower().endswith(".dll"):
                assert righe == "", (
                    f"``.dll`` files must have empty ``<righe>`` "
                    f"(Req 10.2); bullet: {bullet!r}"
                )
            elif path.lower().endswith(_TEXT_EXTENSIONS):
                assert righe != "" and righe.isdigit(), (
                    f"Text file {path} must have an integer ``<righe>``; "
                    f"got {righe!r}"
                )


# --- Tests: ``## Chiavi YAML rimosse`` format (Req 10.4) ------------------

# ``<dotted.key>``: one or more dot-separated segments of [A-Za-z0-9_].
_DOTTED_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


class TestChiaviYamlRimosseFormat:
    """Req 10.4 — ``- <dotted.key> | <motivo>``."""

    def test_bullets_have_two_fields(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(sections["Chiavi YAML rimosse"]):
            fields = _split_pipe_fields(bullet[2:])
            assert len(fields) == 2, (
                f"Chiavi YAML rimosse bullet must expose 2 fields; got "
                f"{len(fields)} in {bullet!r}"
            )

    def test_dotted_key_is_well_formed(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(sections["Chiavi YAML rimosse"]):
            dotted = _split_pipe_fields(bullet[2:])[0].strip()
            assert _DOTTED_KEY_RE.match(dotted), (
                f"``<dotted.key>`` must match identifier.identifier...; "
                f"got {dotted!r} in bullet {bullet!r}"
            )

    def test_motivo_length_between_1_and_200(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(sections["Chiavi YAML rimosse"]):
            motivo = _split_pipe_fields(bullet[2:])[1].strip()
            assert 1 <= len(motivo) <= 200, (
                f"``motivo`` length {len(motivo)} out of range [1,200] "
                f"in bullet {bullet!r}"
            )


# --- Tests: ``## Simboli rimossi`` format (Req 10.5) ----------------------

# ``<modulo.Simbolo>``: at least two dot-separated identifier segments.
_QUALIFIED_SYMBOL_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$"
)
# ``<file>``: no whitespace/pipe; typically a ``.py`` path.
_FILE_RE = re.compile(r"^[^\s|]+$")


class TestSimboliRimossiFormat:
    """Req 10.5 — ``- <modulo.Simbolo> | <file> | <motivo>``."""

    def test_bullets_have_three_fields(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(sections["Simboli rimossi"]):
            fields = _split_pipe_fields(bullet[2:])
            assert len(fields) == 3, (
                f"Simboli rimossi bullet must expose 3 fields; got "
                f"{len(fields)} in {bullet!r}"
            )

    def test_qualified_symbol_is_well_formed(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(sections["Simboli rimossi"]):
            qualified = _split_pipe_fields(bullet[2:])[0].strip()
            assert _QUALIFIED_SYMBOL_RE.match(qualified), (
                f"``<modulo.Simbolo>`` must be a dotted qualified name; "
                f"got {qualified!r} in bullet {bullet!r}"
            )

    def test_file_has_no_whitespace_or_pipe(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(sections["Simboli rimossi"]):
            file_field = _split_pipe_fields(bullet[2:])[1].strip()
            assert _FILE_RE.match(file_field), (
                f"``<file>`` must have no whitespace/pipe; got "
                f"{file_field!r} in bullet {bullet!r}"
            )
            assert "\\" not in file_field, (
                f"``<file>`` must use ``/`` as separator: {file_field!r}"
            )

    def test_motivo_length_between_1_and_200(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(sections["Simboli rimossi"]):
            motivo = _split_pipe_fields(bullet[2:])[2].strip()
            assert 1 <= len(motivo) <= 200, (
                f"``motivo`` length {len(motivo)} out of range [1,200] "
                f"in bullet {bullet!r}"
            )


# --- Tests: ``## Moduli mantenuti ma valutati`` format (Req 10.6) ---------


class TestModuliMantenutiFormat:
    """Req 10.6 — ``- <file> | <decisione>`` with decisione ∈ {KEEP, REMOVE}."""

    def test_bullets_have_two_fields(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(
            sections["Moduli mantenuti ma valutati"]
        ):
            fields = _split_pipe_fields(bullet[2:])
            assert len(fields) == 2, (
                f"Moduli mantenuti bullet must expose 2 fields; got "
                f"{len(fields)} in {bullet!r}"
            )

    def test_file_has_no_whitespace_or_pipe(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(
            sections["Moduli mantenuti ma valutati"]
        ):
            file_field = _split_pipe_fields(bullet[2:])[0].strip()
            assert _FILE_RE.match(file_field), (
                f"``<file>`` must have no whitespace/pipe; got "
                f"{file_field!r} in bullet {bullet!r}"
            )
            assert "\\" not in file_field, (
                f"``<file>`` must use ``/`` as separator: {file_field!r}"
            )

    def test_decisione_in_allowed_set(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(
            sections["Moduli mantenuti ma valutati"]
        ):
            decisione = _split_pipe_fields(bullet[2:])[1].strip()
            assert decisione in _ALLOWED_DECISIONS, (
                f"``decisione``={decisione!r} not in {_ALLOWED_DECISIONS}; "
                f"bullet: {bullet!r}"
            )


# --- Tests: ``## Dead_Reference risolti`` structure (Req 10.7) ------------

# ``- linea <N>: <descrizione>`` where ``N`` is a positive integer.
_DEAD_REF_BULLET_RE = re.compile(r"^- linea (\d+):\s+(.+)$")


class TestDeadReferenceRisoltiStructure:
    """Req 10.7 — ``### <file>`` sub-sections with ``- linea <N>: ...``."""

    def test_subsections_and_bullets_are_well_formed(
        self, sections: Dict[str, str]
    ) -> None:
        body = sections["Dead_Reference risolti"].strip()

        # Section is allowed to be empty-with-placeholder, in which case
        # no further structural checks apply.
        if _EMPTY_PLACEHOLDER in body and "### " not in body:
            return

        # The body must group bullets under ``### <file>`` sub-sections.
        assert re.search(r"^###\s+\S+\s*$", body, flags=re.MULTILINE), (
            "Dead_Reference risolti must contain at least one "
            "``### <file>`` sub-section (or the empty placeholder)"
        )

        # Split the section body on ``### `` headers to inspect each
        # sub-section individually.
        subsection_pattern = re.compile(
            r"^###\s+(.+?)\s*$", flags=re.MULTILINE
        )
        matches = list(subsection_pattern.finditer(body))

        for idx, match in enumerate(matches):
            file_header = match.group(1).strip()

            # ``<file>`` header must look like a relative path.
            assert _FILE_RE.match(file_header), (
                f"``### <file>`` header must have no whitespace/pipe; "
                f"got {file_header!r}"
            )
            assert "\\" not in file_header, (
                f"``### <file>`` header must use ``/`` as separator: "
                f"{file_header!r}"
            )

            sub_start = match.end()
            sub_end = (
                matches[idx + 1].start() if idx + 1 < len(matches) else len(
                    body
                )
            )
            sub_body = body[sub_start:sub_end]

            bullets = [
                line
                for line in sub_body.splitlines()
                if line.startswith("- ")
            ]
            assert bullets, (
                f"Sub-section ``### {file_header}`` must contain at least "
                "one ``- linea <N>: <descrizione>`` bullet"
            )

            for bullet in bullets:
                bullet_match = _DEAD_REF_BULLET_RE.match(bullet)
                assert bullet_match, (
                    "Dead_Reference bullet must match "
                    f"``- linea <N>: <descrizione>``; got {bullet!r}"
                )
                line_no = int(bullet_match.group(1))
                assert line_no >= 1, (
                    f"``linea`` must be a positive integer; got {line_no} "
                    f"in bullet {bullet!r}"
                )
                descrizione = bullet_match.group(2).strip()
                assert descrizione, (
                    f"Dead_Reference bullet must have a non-empty "
                    f"``<descrizione>``; got {bullet!r}"
                )


# --- Tests: ``## Incongruenze rilevate`` format (Req 10.3 / 10.8) ---------


class TestIncongruenzeRilevateFormat:
    """Req 10.3 — ``- <tipo> | <dettaglio>`` with tipo ∈ allowed set."""

    def test_bullets_have_two_fields(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(sections["Incongruenze rilevate"]):
            fields = _split_pipe_fields(bullet[2:])
            assert len(fields) == 2, (
                f"Incongruenze rilevate bullet must expose 2 fields; got "
                f"{len(fields)} in {bullet!r}"
            )

    def test_tipo_in_allowed_set(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(sections["Incongruenze rilevate"]):
            tipo = _split_pipe_fields(bullet[2:])[0].strip()
            assert tipo in _ALLOWED_INCONGRUENZA_TYPES, (
                f"``tipo``={tipo!r} not in {_ALLOWED_INCONGRUENZA_TYPES}; "
                f"bullet: {bullet!r}"
            )

    def test_dettaglio_is_non_empty(
        self, sections: Dict[str, str]
    ) -> None:
        for bullet in _iter_section_bullets(sections["Incongruenze rilevate"]):
            dettaglio = _split_pipe_fields(bullet[2:])[1].strip()
            assert dettaglio, (
                f"``<dettaglio>`` must be a non-empty string; bullet: "
                f"{bullet!r}"
            )
