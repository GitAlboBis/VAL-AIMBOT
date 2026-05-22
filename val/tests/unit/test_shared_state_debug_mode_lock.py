"""
Bug condition exploration test for Bug 2 (codebase-bug-fixes spec).

Property 1: Bug Condition - ``debug_mode`` Read Outside ``self._config_lock``.

This test encodes the lock-discipline invariant for
``SharedState.update_config`` in ``gui/shared_state.py``: the
``self.get_state('general.debug_mode', False)`` read must be serialized with
the same lock that guards the preceding config mutation
(``self._config[section][key] = value``, ``self._config_modified = True``).

**Validates: Requirements 1.2**

Expected outcome on UNFIXED code: test FAILS. The failure surfaces the
counterexample of the lock-free ``debug_mode`` read sitting at the
top-level of ``update_config`` while the mutation it logs is nested inside a
``with self._config_lock:`` block.

Expected outcome after the Bug 2 fix: test PASSES. Either the read has been
relocated inside the lock block (Option A) or a justification comment + public
contract update documents the lock-free read (Option B, covered elsewhere).

The test is deterministic / AST-scoped per the design's "Scoped PBT Approach"
for this bug: the target file is fixed (``gui/shared_state.py``) and the
property is a structural invariant on its parse tree.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Optional, Tuple

import pytest


SHARED_STATE_PATH = (
    Path(__file__).resolve().parents[2] / "gui" / "shared_state.py"
)

# Approximate line positions cited by ``design.md`` / ``tasks.md`` Task 4.
# The first ``with self._config_lock:`` block inside ``update_config`` opens
# "near line 73" and the ``debug_mode`` read sits "near line 110". The file
# has evolved slightly (docstrings/comments shift lines), so allow drift.
EXPECTED_WITH_OPEN_LINE = 73
EXPECTED_GET_STATE_LINE = 110
LINE_TOLERANCE = 60


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _assign_parents(tree: ast.AST) -> None:
    """Attach a ``_parent`` attribute to every node so we can walk ancestry."""
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child._parent = node  # type: ignore[attr-defined]


def _load_update_config_function() -> Tuple[ast.FunctionDef, ast.Module]:
    """Parse the target module and return (``update_config`` FunctionDef, tree).

    Returns:
        A tuple ``(update_config_node, module_tree)``.

    Raises:
        AssertionError: if the file, class, or method cannot be located.
    """
    assert SHARED_STATE_PATH.is_file(), (
        f"Expected target file at {SHARED_STATE_PATH} but it was not found."
    )
    source = SHARED_STATE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SHARED_STATE_PATH))
    _assign_parents(tree)

    class_node: Optional[ast.ClassDef] = None
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SharedState":
            class_node = node
            break
    assert class_node is not None, (
        f"Could not locate class `SharedState` in {SHARED_STATE_PATH}"
    )

    method_node: Optional[ast.FunctionDef] = None
    for node in class_node.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "update_config"
        ):
            method_node = node  # type: ignore[assignment]
            break
    assert method_node is not None, (
        f"Could not locate method `SharedState.update_config` in "
        f"{SHARED_STATE_PATH}"
    )
    return method_node, tree


def _is_self_attr(expr: ast.AST, attr: str) -> bool:
    """Return True if ``expr`` is the attribute access ``self.<attr>``."""
    return (
        isinstance(expr, ast.Attribute)
        and expr.attr == attr
        and isinstance(expr.value, ast.Name)
        and expr.value.id == "self"
    )


def _with_guards_config_lock(with_node: ast.With) -> bool:
    """Return True if ``with_node`` opens ``with self._config_lock:``."""
    for item in with_node.items:
        if _is_self_attr(item.context_expr, "_config_lock"):
            return True
    return False


def _ancestor_with_blocks(
    node: ast.AST, boundary: ast.AST
) -> List[ast.With]:
    """Return every ``With`` ancestor of ``node`` up to (but not past) ``boundary``.

    Uses the ``_parent`` links attached by ``_assign_parents``. Stops when the
    boundary (typically the enclosing ``update_config`` FunctionDef) is reached.
    """
    withs: List[ast.With] = []
    current = getattr(node, "_parent", None)
    while current is not None and current is not boundary:
        if isinstance(current, ast.With):
            withs.append(current)
        current = getattr(current, "_parent", None)
    return withs


def _find_debug_mode_get_state_call(
    func: ast.FunctionDef,
) -> Optional[ast.Call]:
    """Locate ``self.get_state('general.debug_mode', False)`` inside ``func``.

    Returns:
        The ``ast.Call`` node for the documented debug-mode read, or ``None``
        if no such call exists.
    """
    for sub in ast.walk(func):
        if not isinstance(sub, ast.Call):
            continue
        func_expr = sub.func
        if not _is_self_attr(func_expr, "get_state"):
            continue
        if len(sub.args) < 2:
            continue
        first, second = sub.args[0], sub.args[1]
        if not (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and first.value == "general.debug_mode"
        ):
            continue
        if not (
            isinstance(second, ast.Constant)
            and second.value is False
        ):
            continue
        return sub
    return None


def _find_config_mutation_assign(
    func: ast.FunctionDef,
) -> Optional[ast.Assign]:
    """Locate ``self._config[section][key] = value`` inside ``func``.

    Returns the matching ``ast.Assign`` node or ``None``.
    """
    for sub in ast.walk(func):
        if not isinstance(sub, ast.Assign):
            continue
        if len(sub.targets) != 1:
            continue
        target = sub.targets[0]
        # Pattern: self._config[section][key]
        #   Subscript(value=Subscript(value=Attribute(value=Name('self'),
        #                                              attr='_config'),
        #                              slice=Name('section')),
        #             slice=Name('key'))
        if not isinstance(target, ast.Subscript):
            continue
        inner = target.value
        if not isinstance(inner, ast.Subscript):
            continue
        if not _is_self_attr(inner.value, "_config"):
            continue
        return sub
    return None


def _find_config_modified_assign(
    func: ast.FunctionDef,
) -> Optional[ast.Assign]:
    """Locate ``self._config_modified = True`` inside ``func``."""
    for sub in ast.walk(func):
        if not isinstance(sub, ast.Assign):
            continue
        if len(sub.targets) != 1:
            continue
        target = sub.targets[0]
        if not _is_self_attr(target, "_config_modified"):
            continue
        value = sub.value
        if isinstance(value, ast.Constant) and value.value is True:
            return sub
    return None


def _format_counterexample(
    method: ast.FunctionDef,
    call: Optional[ast.Call],
    mutation: Optional[ast.Assign],
    modified_assign: Optional[ast.Assign],
) -> str:
    """Build a human-readable counterexample describing the AST layout."""
    def line_of(node: Optional[ast.AST]) -> str:
        return "<missing>" if node is None else str(getattr(node, "lineno", "?"))

    call_parent_line: str = "<n/a>"
    if call is not None:
        parent = getattr(call, "_parent", None)
        # Climb until we hit a statement-level node (first parent with lineno
        # that is a child of update_config or one of its descendants).
        call_parent_line = str(getattr(parent, "lineno", "?"))

    mutation_with_lines: List[int] = []
    if mutation is not None:
        mutation_with_lines = [
            w.lineno for w in _ancestor_with_blocks(mutation, method)
            if _with_guards_config_lock(w)
        ]

    call_with_lines: List[int] = []
    if call is not None:
        call_with_lines = [
            w.lineno for w in _ancestor_with_blocks(call, method)
            if _with_guards_config_lock(w)
        ]

    return (
        f"Counterexample for Bug 2 (lock-free debug_mode read in "
        f"SharedState.update_config):\n"
        f"  file                                : {SHARED_STATE_PATH}\n"
        f"  update_config definition line       : {method.lineno}\n"
        f"  get_state('general.debug_mode') line: {line_of(call)}\n"
        f"  get_state call parent stmt line     : {call_parent_line}\n"
        f"  self._config[section][key] = value  : line {line_of(mutation)}\n"
        f"  self._config_modified = True        : line {line_of(modified_assign)}\n"
        f"  mutation is nested under these `with self._config_lock:` lines: "
        f"{mutation_with_lines}\n"
        f"  get_state call is nested under these `with self._config_lock:` "
        f"lines: {call_with_lines}\n"
        f"  => bug condition: mutation guarded by _config_lock but "
        f"debug_mode read is NOT\n"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBug2DebugModeLockDiscipline:
    """Property 1: lock-discipline invariant on ``SharedState.update_config``.

    The property encodes the bug condition from ``design.md`` Bug 2::

        isBugCondition(call_site) ==
          call_site.enclosing_function == "SharedState.update_config"
          AND call_site.expression == "self.get_state('general.debug_mode', False)"
          AND call_site.is_inside_block("with self._config_lock:") == false
          AND update_config.preceding_mutation_guarded_by("self._config_lock") == true

    The expected post-fix property (Option A) is the negation of that
    condition: both the mutation and the ``debug_mode`` read are nested under
    a ``with self._config_lock:`` block inside ``update_config``.
    """

    # ------------------------------------------------------------------
    # Structural sanity checks — these establish the preconditions named
    # in Task 4 so the main invariant can be evaluated meaningfully.
    # ------------------------------------------------------------------

    def test_update_config_defines_a_config_lock_with_block(self) -> None:
        """``update_config`` must contain at least one ``with self._config_lock:``.

        This corresponds to the Task 4 expectation that the method "opens a
        ``with self._config_lock:`` block near line 73".
        """
        method, _tree = _load_update_config_function()

        with_blocks = [
            node for node in ast.walk(method)
            if isinstance(node, ast.With) and _with_guards_config_lock(node)
        ]
        assert with_blocks, (
            "Expected `SharedState.update_config` to contain at least one "
            "`with self._config_lock:` block, found none. "
            f"File: {SHARED_STATE_PATH}"
        )
        # Check the expected approximate position of the mutation-guarding
        # block. The file has two such blocks; at least one should open near
        # the documented line.
        line_numbers = [w.lineno for w in with_blocks]
        assert any(
            abs(ln - EXPECTED_WITH_OPEN_LINE) <= LINE_TOLERANCE
            for ln in line_numbers
        ), (
            f"No `with self._config_lock:` block opens near line "
            f"{EXPECTED_WITH_OPEN_LINE} (tolerance {LINE_TOLERANCE}). "
            f"Observed line numbers: {line_numbers}"
        )

    def test_update_config_reads_debug_mode_via_get_state(self) -> None:
        """``update_config`` must contain the documented debug-mode read."""
        method, _tree = _load_update_config_function()
        call = _find_debug_mode_get_state_call(method)
        assert call is not None, (
            "Expected `self.get_state('general.debug_mode', False)` inside "
            f"`SharedState.update_config` in {SHARED_STATE_PATH}, but could "
            "not locate it."
        )
        assert abs(call.lineno - EXPECTED_GET_STATE_LINE) <= LINE_TOLERANCE, (
            f"`self.get_state('general.debug_mode', False)` expected near "
            f"line {EXPECTED_GET_STATE_LINE} (tolerance {LINE_TOLERANCE}), "
            f"found at line {call.lineno}."
        )

    def test_config_mutation_is_inside_config_lock(self) -> None:
        """The preceding mutation must be nested under ``self._config_lock``.

        This is the second half of the bug condition preconditions: the
        mutation ``self._config[section][key] = value`` (and
        ``self._config_modified = True``) IS inside a
        ``with self._config_lock:`` block.
        """
        method, _tree = _load_update_config_function()

        mutation = _find_config_mutation_assign(method)
        modified = _find_config_modified_assign(method)

        assert mutation is not None, (
            "Expected `self._config[section][key] = value` assignment inside "
            f"`SharedState.update_config` in {SHARED_STATE_PATH}."
        )
        assert modified is not None, (
            "Expected `self._config_modified = True` assignment inside "
            f"`SharedState.update_config` in {SHARED_STATE_PATH}."
        )

        mutation_guards = [
            w for w in _ancestor_with_blocks(mutation, method)
            if _with_guards_config_lock(w)
        ]
        modified_guards = [
            w for w in _ancestor_with_blocks(modified, method)
            if _with_guards_config_lock(w)
        ]

        assert mutation_guards, (
            "Expected `self._config[section][key] = value` to be nested "
            "under a `with self._config_lock:` block, but it is not. "
            f"Mutation line: {mutation.lineno}."
        )
        assert modified_guards, (
            "Expected `self._config_modified = True` to be nested under a "
            "`with self._config_lock:` block, but it is not. "
            f"Assignment line: {modified.lineno}."
        )

    # ------------------------------------------------------------------
    # The headline invariant — this is the assertion whose failure on
    # unfixed code confirms Bug 2 exists.
    # ------------------------------------------------------------------

    def test_debug_mode_read_is_inside_config_lock(self) -> None:
        """Assert the ``debug_mode`` read is nested under ``self._config_lock``.

        Post-fix (Option A) invariant: the ``ast.Call`` for
        ``self.get_state('general.debug_mode', False)`` has at least one
        ancestor ``With`` node (within ``update_config``) whose context
        expression is ``self._config_lock``.

        On the unfixed code this assertion FAILS because the read sits as a
        top-level statement of ``update_config`` after the mutation's
        ``with self._config_lock:`` block has exited — exactly the pattern
        called out in ``design.md`` Bug 2 ``isBugCondition``.
        """
        method, _tree = _load_update_config_function()
        call = _find_debug_mode_get_state_call(method)
        mutation = _find_config_mutation_assign(method)
        modified = _find_config_modified_assign(method)

        assert call is not None, (
            "Missing `self.get_state('general.debug_mode', False)` inside "
            "`SharedState.update_config`; the bug condition cannot be "
            "evaluated."
        )

        call_guards = [
            w for w in _ancestor_with_blocks(call, method)
            if _with_guards_config_lock(w)
        ]

        assert call_guards, _format_counterexample(
            method, call, mutation, modified
        )
