"""
Bug condition exploration test for Bug 1 (codebase-bug-fixes spec).

Property 1: Bug Condition - Duplicate `AIVisionEngine.get_health_status` Definition.

This test encodes the single-definition invariant for
`AIVisionEngine.get_health_status` and `AIVisionEngine.release` in
`engines/ai_engine.py`.

**Validates: Requirements 1.1**

Expected outcome on UNFIXED code: test FAILS (the failure surfaces the
counterexample of two `get_health_status` definitions straddling `release`).
Expected outcome after the Bug 1 fix: test PASSES (single definition).

The test is deterministic / AST-scoped per the design's "Scoped PBT Approach"
for this bug: the target file is fixed (`engines/ai_engine.py`) and the
property is a structural invariant on its parse tree.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import List

import pytest


AI_ENGINE_PATH = Path(__file__).resolve().parents[2] / "engines" / "ai_engine.py"

# Approximate line positions the bugfix.md/design.md specify for the two
# duplicate definitions and the intervening `release` method.
EXPECTED_FIRST_DEF_LINE = 471
EXPECTED_SECOND_DEF_LINE = 512
LINE_TOLERANCE = 25  # "≈" in the design — allow small drift as the file evolves

EXPECTED_HEALTH_KEYS = {
    "operational",
    "model_loaded",
    "backend",
    "avg_inference_ms",
    "enabled",
}


def _load_ai_vision_engine_class() -> ast.ClassDef:
    """Parse `engines/ai_engine.py` and return the `AIVisionEngine` ClassDef.

    Returns:
        The `ast.ClassDef` node for `AIVisionEngine`.

    Raises:
        AssertionError: if the file or class cannot be located.
    """
    assert AI_ENGINE_PATH.is_file(), (
        f"Expected target file at {AI_ENGINE_PATH} but it was not found."
    )
    source = AI_ENGINE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(AI_ENGINE_PATH))

    class_node: ast.ClassDef | None = None
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and node.name == "AIVisionEngine":
            class_node = node
            break

    assert class_node is not None, (
        f"Could not locate class `AIVisionEngine` in {AI_ENGINE_PATH}"
    )
    return class_node


def _methods_named(cls: ast.ClassDef, name: str) -> List[ast.FunctionDef]:
    """Return every method (sync or async) on `cls` whose name equals `name`."""
    return [
        node
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]


def _format_counterexample(
    name: str, defs: List[ast.FunctionDef], release_defs: List[ast.FunctionDef]
) -> str:
    """Build a human-readable counterexample for a failing assertion."""
    def_lines = [(d.lineno, getattr(d, "end_lineno", None)) for d in defs]
    rel_lines = [(d.lineno, getattr(d, "end_lineno", None)) for d in release_defs]
    return (
        f"Counterexample for Bug 1 (duplicate `{name}` on AIVisionEngine):\n"
        f"  file              : {AI_ENGINE_PATH}\n"
        f"  {name} count      : {len(defs)}\n"
        f"  {name} line ranges: {def_lines}\n"
        f"  release count     : {len(release_defs)}\n"
        f"  release line range: {rel_lines}\n"
    )


@pytest.mark.unit
class TestBug1DuplicateGetHealthStatus:
    """Property 1: single-definition invariant on `AIVisionEngine`.

    These assertions are the bug condition encoded from `design.md` Bug 1:

      isBugCondition(module) ==
        count(defs where class=="AIVisionEngine" AND name=="get_health_status") > 1
        AND EXISTS d1, d2, d1 != d2,
              d1.line_start ≈ 471 AND d2.line_start ≈ 512
        AND module.methods.any(m => m.name == "release"
                                    AND d1.line_end < m.line_start < d2.line_start)

    The expected post-fix property is the negation of that condition: exactly
    one `get_health_status` and exactly one `release`, with no duplicate def
    straddling `release`.
    """

    def test_exactly_one_get_health_status_on_ai_vision_engine(self) -> None:
        """Assert `AIVisionEngine.get_health_status` is defined exactly once."""
        cls = _load_ai_vision_engine_class()
        defs = _methods_named(cls, "get_health_status")
        release_defs = _methods_named(cls, "release")

        assert len(defs) == 1, _format_counterexample(
            "get_health_status", defs, release_defs
        )

    def test_exactly_one_release_on_ai_vision_engine(self) -> None:
        """Assert `AIVisionEngine.release` is defined exactly once."""
        cls = _load_ai_vision_engine_class()
        release_defs = _methods_named(cls, "release")
        health_defs = _methods_named(cls, "get_health_status")

        assert len(release_defs) == 1, _format_counterexample(
            "release", release_defs, health_defs
        )

    def test_no_duplicate_get_health_status_straddles_release(self) -> None:
        """Assert the specific design-cited duplicate pattern does not exist.

        Property (design Bug 1 isBugCondition, negated):
            NOT (EXISTS d1, d2 in get_health_status_defs, d1 != d2,
                 d1.line_start ≈ 471 AND d2.line_start ≈ 512
                 AND EXISTS release def r
                     with d1.line_end < r.line_start < d2.line_start).
        """
        cls = _load_ai_vision_engine_class()
        health_defs = _methods_named(cls, "get_health_status")
        release_defs = _methods_named(cls, "release")

        # If there is no duplicate, the straddle pattern cannot exist — this
        # branch keeps the failure message useful in either direction.
        if len(health_defs) < 2:
            # Nothing more to check; the other two tests cover single-def.
            return

        # Look for any (d1, d2, r) triple matching the design's bug pattern.
        offending_triples = []
        for i, d1 in enumerate(health_defs):
            for d2 in health_defs[i + 1 :]:
                # Order d1 before d2 by line_start to match the design spec.
                first, second = sorted((d1, d2), key=lambda n: n.lineno)
                first_end = getattr(first, "end_lineno", first.lineno)
                near_471 = abs(first.lineno - EXPECTED_FIRST_DEF_LINE) <= LINE_TOLERANCE
                near_512 = abs(second.lineno - EXPECTED_SECOND_DEF_LINE) <= LINE_TOLERANCE
                for r in release_defs:
                    between = first_end < r.lineno < second.lineno
                    if near_471 and near_512 and between:
                        offending_triples.append(
                            {
                                "first_def_line": first.lineno,
                                "first_def_end_line": first_end,
                                "release_line": r.lineno,
                                "second_def_line": second.lineno,
                            }
                        )

        assert not offending_triples, (
            "Duplicate `get_health_status` definitions straddle `release` "
            "on `AIVisionEngine` — Bug 1 reproduced.\n"
            f"  file              : {AI_ENGINE_PATH}\n"
            f"  offending triples : {offending_triples}\n"
            f"  expected pattern  : first≈{EXPECTED_FIRST_DEF_LINE}, "
            f"second≈{EXPECTED_SECOND_DEF_LINE}, release between them"
        )

    def test_both_duplicate_bodies_return_expected_health_keys(self) -> None:
        """Sanity check: each `get_health_status` returns the documented shape.

        This secondary assertion matches the design's counterexample
        description ("both returning a dict with keys operational,
        model_loaded, backend, avg_inference_ms, enabled"). It is intentionally
        lenient — it passes as long as at least one definition exists and every
        existing definition returns a dict literal with the expected keys.
        """
        cls = _load_ai_vision_engine_class()
        defs = _methods_named(cls, "get_health_status")
        assert defs, "Expected at least one `get_health_status` on AIVisionEngine"

        for d in defs:
            returns = [n for n in ast.walk(d) if isinstance(n, ast.Return)]
            dict_returns = [
                r for r in returns if isinstance(r.value, ast.Dict)
            ]
            assert dict_returns, (
                f"`get_health_status` at line {d.lineno} has no dict Return"
            )
            # Use the last dict-returning statement in the body.
            last_dict: ast.Dict = dict_returns[-1].value  # type: ignore[assignment]
            keys = {
                k.value
                for k in last_dict.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            assert keys == EXPECTED_HEALTH_KEYS, (
                f"`get_health_status` at line {d.lineno} returned keys "
                f"{keys!r}, expected {EXPECTED_HEALTH_KEYS!r}"
            )
