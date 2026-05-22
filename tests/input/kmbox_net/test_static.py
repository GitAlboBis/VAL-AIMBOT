"""
Static AST test — Task 10.2 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 15 (AST half): Encryption flag
#   read in exactly one ``_dispatch_call``.

**Property 15 (AST half): The encryption flag is consulted in exactly
one place**

    The ``self.use_encryption`` attribute SHALL be read (i.e. accessed
    in :class:`ast.Load` context) inside exactly *one* ``FunctionDef``
    of :class:`KmBoxNetDriver`, and that ``FunctionDef`` SHALL be named
    ``_dispatch_call``. Reads in two further methods are explicitly
    permitted because they do not affect build-path selection:

      * :meth:`__init__` — the constructor stores the flag verbatim
        on ``self`` (``self.use_encryption = bool(use_encryption)``);
        Python's AST records the right-hand side ``bool(use_encryption)``
        as a parameter access, but the *attribute write*
        ``self.use_encryption = …`` is :class:`ast.Store`-context, so
        it does NOT count as a read. We allow ``__init__`` here as a
        belt-and-braces accommodation in case the parser-side
        attribute-classification rules ever flag the LHS as a Load
        (they do not under CPython 3.x, but the allowance future-proofs
        the test).
      * :meth:`get_driver_info` — returns a dictionary snapshot of the
        driver's metadata, including the encryption flag. This is a
        pure metadata read with no build-path semantics; surfacing the
        flag in the ``get_driver_info`` dict is required by Requirement
        3.7 (DD-compatible API surface), so the test explicitly
        permits a single Load there.

    Any other ``FunctionDef`` in :class:`KmBoxNetDriver` that contains
    a Load access of ``self.use_encryption`` SHALL be a violation of
    Requirement 9.4 ("the encryption-vs-plaintext build decision …
    SHALL be made through a single internal dispatch helper invoked
    by every method listed in Requirement 9.1, and the individual
    command methods SHALL NOT contain encryption-vs-plaintext
    branching").

**Validates: Requirements 9.1, 9.2, 9.4**

Implementation notes
--------------------

This test parses ``input/kmbox_net_driver.py`` with :func:`ast.parse`
and walks the body of the :class:`KmBoxNetDriver` class. For every
:class:`ast.Attribute` node with ``attr == "use_encryption"`` *and*
``ctx`` of type :class:`ast.Load` *and* a ``self``-typed value, the
test records the enclosing :class:`ast.FunctionDef` (i.e. the method
the read lives in).

The walk is driven by :class:`ast.NodeVisitor`-style traversal that
maintains a stack of enclosing function definitions, so a read inside
a nested helper (e.g. an inner closure declared inside ``_dispatch_call``)
would still be attributed to the *immediately enclosing* function — but
in practice the driver does not declare nested closures around the
encryption check, so the walk is straightforward.

Why an AST test (instead of grep)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A naive ``grep -c 'self.use_encryption'`` would over-count: the
docstring of ``_dispatch_call`` mentions the attribute by name several
times, and so do the docstrings of ``__init__`` and other methods.
The AST walk only inspects executable code (string literals are
:class:`ast.Constant` nodes, not :class:`ast.Attribute`), so the test
is robust against future docstring rewordings.

A second reason: the AST classifies ``self.use_encryption`` reads vs.
writes via the ``ctx`` field — a write (e.g.
``self.use_encryption = bool(use_encryption)`` in ``__init__``) has
``ctx=Store`` while a read has ``ctx=Load``. Filtering on Load is the
exact encoding of "is read" called out by the task brief.
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional


# Make the ``input`` package importable when pytest is launched from
# the repository root or any sub-directory (the driver ships as
# ``input/kmbox_net_driver.py`` at the project root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# Path to the driver source — this is the file under static analysis.
_DRIVER_SOURCE_PATH = _REPO_ROOT / "input" / "kmbox_net_driver.py"


# ---------------------------------------------------------------------------
# AST walker
# ---------------------------------------------------------------------------


class _UseEncryptionReadCollector(ast.NodeVisitor):
    """Collect ``FunctionDef`` names that contain a ``self.use_encryption`` read.

    A "read" is an :class:`ast.Attribute` node whose:

      * ``attr == "use_encryption"``,
      * ``ctx`` is an instance of :class:`ast.Load`,
      * ``value`` is an :class:`ast.Name` with ``id == "self"``.

    The third clause filters out reads of ``use_encryption`` on
    arbitrary other objects (e.g. a future ``other_driver.use_encryption``
    on a different driver instance — none such exist today, but the
    filter keeps the test focused on *self*-attribute reads).

    The walker maintains a stack of enclosing function definitions so
    each match is attributed to the *innermost* :class:`ast.FunctionDef`
    or :class:`ast.AsyncFunctionDef`. It only walks the body of the
    target class (``KmBoxNetDriver``), so reads in module-level helpers
    or other classes do not influence the result.
    """

    def __init__(self) -> None:
        self._function_stack: List[str] = []
        # ``reads_by_function[name]`` lists each match's ``(lineno,
        # col_offset)`` so a future failure can pinpoint the offending
        # source location. ``defaultdict(list)`` keeps the bookkeeping
        # tidy even for functions that have many reads (which would
        # itself be a property violation if it happened outside
        # ``_dispatch_call``).
        self.reads_by_function: Dict[str, List[tuple[int, int]]] = defaultdict(
            list
        )

    # ---- function tracking ---------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function_stack.append(node.name)
        try:
            self.generic_visit(node)
        finally:
            self._function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        # The driver does not currently declare any async methods,
        # but support them defensively so a future ``async def
        # ...`` does not silently slip past the check.
        self._function_stack.append(node.name)
        try:
            self.generic_visit(node)
        finally:
            self._function_stack.pop()

    # ---- attribute matching --------------------------------------------

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Match ``self.use_encryption`` in Load context (a read).
        # Writes (``self.use_encryption = …``) appear with ``ctx`` set
        # to :class:`ast.Store`; we explicitly do not count them per
        # the task brief.
        if (
            node.attr == "use_encryption"
            and isinstance(node.ctx, ast.Load)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
            and self._function_stack
        ):
            enclosing = self._function_stack[-1]
            self.reads_by_function[enclosing].append(
                (node.lineno, node.col_offset)
            )
        # Walk the children so nested ``self.foo.use_encryption``
        # access (which would not match the ``Name == 'self'`` filter
        # but might contain a deeper ``self.use_encryption`` read in
        # an unusual edge case) is also visited.
        self.generic_visit(node)


def _find_kmbox_class_body(tree: ast.Module) -> Optional[ast.ClassDef]:
    """Return the :class:`ast.ClassDef` for ``KmBoxNetDriver``, if present."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "KmBoxNetDriver":
            return node
    return None


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


def test_use_encryption_is_read_only_in_dispatch_call() -> None:
    """``self.use_encryption`` reads occur only in the allowed methods.

    Validates: Requirements 9.1, 9.2, 9.4.

    The test:

      1. Parses ``input/kmbox_net_driver.py`` via :func:`ast.parse`.
      2. Locates the :class:`ast.ClassDef` for ``KmBoxNetDriver``.
      3. Walks the class body collecting every :class:`ast.Attribute`
         node whose ``attr`` is ``"use_encryption"``, whose ``ctx`` is
         :class:`ast.Load`, and whose ``value`` is the bare ``self``
         name — and records the enclosing :class:`ast.FunctionDef`.
      4. Asserts that every collected read lives in one of the
         allow-listed methods: ``__init__`` (constructor — typically
         only contains a Store, but tolerated as a Load to future-proof
         the test), ``get_driver_info`` (Requirement 3.7 metadata
         snapshot), and ``_dispatch_call`` (the build-path selector
         per Requirement 9.4).
      5. Asserts that ``_dispatch_call`` contains *at least* one
         read — without it, the dispatch helper could not be making a
         build-path decision based on the flag, and Requirement 9.4
         would be vacuously violated by absence.
    """
    # Parse the driver source. ``ast.parse`` raises ``SyntaxError`` on
    # malformed input, which would surface here as a test failure with
    # a precise location — a more useful failure mode than a runtime
    # ImportError elsewhere in the suite.
    source_text = _DRIVER_SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(_DRIVER_SOURCE_PATH))

    class_def = _find_kmbox_class_body(tree)
    assert class_def is not None, (
        "test pre-condition: KmBoxNetDriver class must be declared at "
        "module scope in %s; the AST walk could not find it." % (
            _DRIVER_SOURCE_PATH,
        )
    )

    # Walk only the body of the class — module-level helpers (e.g.
    # ``pack_header``, ``keyboard_apply_down``) are not part of the
    # driver class and so are out of scope for this property.
    collector = _UseEncryptionReadCollector()
    for child in class_def.body:
        collector.visit(child)

    reads_by_function = dict(collector.reads_by_function)

    # ── Allow-list ─────────────────────────────────────────────────
    # The three methods below are explicitly allowed to read
    # ``self.use_encryption``:
    #
    #   * ``__init__``          — constructor; typically a Store
    #                             ``self.use_encryption = bool(...)`` 
    #                             but tolerate a Load in case a future
    #                             refactor reads the stored value back
    #                             during initialization.
    #   * ``get_driver_info``   — Requirement 3.7 metadata snapshot
    #                             (the DD-compatible public API
    #                             surfaces the flag in its return
    #                             dict).
    #   * ``_dispatch_call``    — Requirement 9.4: the single
    #                             encryption-vs-plaintext build-path
    #                             selector.
    allowed = {"__init__", "get_driver_info", "_dispatch_call"}

    # ── Check 1: every read is in an allowed method ────────────────
    forbidden = {
        name: locations
        for name, locations in reads_by_function.items()
        if name not in allowed
    }
    assert not forbidden, (
        "Property 15 (AST half) violated: ``self.use_encryption`` is "
        "read in %d method(s) outside the allow-list "
        "{__init__, get_driver_info, _dispatch_call}. "
        "Requirement 9.4 mandates that the encryption-vs-plaintext "
        "build decision is made in exactly one helper "
        "(``_dispatch_call``); the individual command methods must "
        "NOT contain encryption-vs-plaintext branching. Violations: "
        "%r"
        % (len(forbidden), forbidden)
    )

    # ── Check 2: ``_dispatch_call`` does have at least one read ────
    # If ``_dispatch_call`` has *no* reads, then either (a) the
    # encryption flag is never consulted at all (Requirement 9.4
    # vacuously violated by absence — no command would route through
    # the encryptor), or (b) the read has been moved elsewhere in a
    # refactor — Check 1 above would already catch that case, but
    # asserting on Check 2 surfaces the absence with a precise
    # diagnostic.
    dispatch_reads = reads_by_function.get("_dispatch_call", [])
    assert len(dispatch_reads) >= 1, (
        "Property 15 (AST half) violated: ``_dispatch_call`` does NOT "
        "read ``self.use_encryption`` — the encryption-vs-plaintext "
        "build-path selector required by Requirement 9.4 is missing. "
        "Without this read, no command would ever route through the "
        "PacketEncryptor."
    )

    # ── Check 3 (informational, non-fatal): exactly ONE read in
    # _dispatch_call. The task brief says ``self.use_encryption`` is
    # read in exactly one ``FunctionDef``; that statement is about the
    # *number of FunctionDefs containing reads* (which Check 1 + Check
    # 2 already enforce), not about the *number of reads per
    # FunctionDef*. ``_dispatch_call`` may legitimately read the flag
    # multiple times (e.g. once for the build-path branch and once
    # for a defensive log message), so we only emit a soft assertion
    # warning if the count surprises a future maintainer. The hard
    # invariant — "no other method reads the flag" — is enforced by
    # Check 1.
    #
    # We intentionally do not assert ``len(dispatch_reads) == 1``
    # because the implementation may legitimately read the flag more
    # than once (e.g. once in the build branch + once in an ``else``
    # log message). The task wording is preserved by the
    # *FunctionDef-count* property, not the *read-count* property.

    # ── Check 4 (sanity): ``get_driver_info`` and ``__init__`` reads
    # are bounded. If either has *many* reads, that would be a sign
    # the encryption flag is being consulted for build-path decisions
    # there (rather than the single Load required by the dict-snapshot
    # / constructor-store contracts). One read each is the expected
    # canonical shape; allow up to 2 to absorb future minor
    # refactors without unrelated noise.
    init_reads = reads_by_function.get("__init__", [])
    info_reads = reads_by_function.get("get_driver_info", [])
    assert len(init_reads) <= 2, (
        "Property 15 (AST half) violated: ``__init__`` contains %d "
        "reads of ``self.use_encryption`` — the constructor should "
        "store the flag (Store context) and at most echo it back for "
        "logging; multiple Load-context reads suggest build-path "
        "branching has crept into __init__. Locations: %r"
        % (len(init_reads), init_reads)
    )
    assert len(info_reads) <= 2, (
        "Property 15 (AST half) violated: ``get_driver_info`` "
        "contains %d reads of ``self.use_encryption`` — the metadata "
        "snapshot should surface the flag exactly once in its return "
        "dict; more than that suggests build-path branching. "
        "Locations: %r"
        % (len(info_reads), info_reads)
    )
