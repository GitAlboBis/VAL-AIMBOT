"""
Wave 0 invariant test — Single_Writer_Invariant for ``errors.log``.

This test arms the Single_Writer_Invariant BEFORE any behavioural changes are
landed by later waves of the audit-remediation spec. It captures the current
dual-writer baseline and will be flipped out of ``xfail`` by Task 3.3 once
Requirement 2 is implemented.

Baseline (pre-remediation):
    * ``main.setup_logging`` installs a ``logging.FileHandler`` on the root
      logger that targets the configured ``general.log_file`` path.
    * ``gui.error_handler.ErrorHandler._setup_file_logging`` installs a second
      ``logging.FileHandler`` on the ``gui.error_handler`` module logger that
      targets the same path (records propagate to root, so a single emission
      produces two lines).
    * ``gui.error_handler.ErrorHandler._log_to_file`` additionally opens the
      same path via ``open(..., 'a')`` as a raw file writer.

The Single_Writer_Invariant requires that exactly one ``FileHandler`` targets
the Errors_Log path at steady state and that ``gui/error_handler.py`` contains
no raw ``open(..., 'a')`` writer against that path.

**Property 2: Single_Writer_Invariant — N records produce N lines**

**Validates: Requirements 2.1, 2.2, 40.1**
"""

from __future__ import annotations

import ast
import logging
import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ERROR_HANDLER_PATH = PROJECT_ROOT / "gui" / "error_handler.py"

# Ensure project root is on sys.path for ``import main``.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Logging helpers (introspection + teardown)
# ---------------------------------------------------------------------------


def _iter_all_loggers():
    """Yield the root logger and every named logger known to the manager."""
    yield logging.getLogger()
    for lg in list(logging.root.manager.loggerDict.values()):
        if isinstance(lg, logging.Logger):
            yield lg


def _file_handlers_for_path(log_path: str):
    """Return every ``FileHandler`` (across all loggers) whose ``baseFilename``
    resolves to the same filesystem path as ``log_path``."""
    target = os.path.normcase(os.path.abspath(log_path))
    found = []
    for lg in _iter_all_loggers():
        for h in list(lg.handlers):
            if isinstance(h, logging.FileHandler):
                base = getattr(h, "baseFilename", None)
                if base and os.path.normcase(os.path.abspath(base)) == target:
                    found.append(h)
    return found


def _purge_file_handlers() -> None:
    """Remove and close every ``FileHandler`` on every logger. Required on
    Windows so ``tmp_path`` can be cleaned up without a locked-file error."""
    for lg in _iter_all_loggers():
        for h in list(lg.handlers):
            if isinstance(h, logging.FileHandler):
                try:
                    lg.removeHandler(h)
                finally:
                    try:
                        h.close()
                    except Exception:
                        pass


@pytest.fixture
def clean_logging():
    """Guarantee a clean FileHandler slate before and after the test so
    cross-test handler leaks do not taint the assertion and Windows does not
    block ``tmp_path`` removal."""
    _purge_file_handlers()
    try:
        yield
    finally:
        _purge_file_handlers()


# ---------------------------------------------------------------------------
# Part A — exactly one FileHandler targets the configured log_file
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="R2 baseline — current tree has duplicate writers; Task 3.3 flips this off",
    strict=True,
)
def test_single_file_handler_targets_log_file(tmp_path, monkeypatch, clean_logging):
    """After ``main.setup_logging`` + ``ErrorHandler`` init, exactly one
    ``FileHandler`` across all loggers targets the configured Errors_Log path.

    The startup path exercised here mirrors the application: ``setup_logging``
    runs first, then ``ErrorHandler`` is constructed with a ``SharedState``.
    Today ``ErrorHandler._setup_file_logging`` attaches a second handler on the
    module logger, so this assertion fails (xfail). Task 3.3 removes that
    attachment and flips the marker off.

    **Validates: Requirements 2.1, 2.2, 40.1**
    """
    log_file = tmp_path / "errors.log"

    # Align ErrorHandler's hard-coded path with the configured path so that
    # any duplicate FileHandler is visible as a same-path collision.
    import gui.error_handler as error_handler_module

    monkeypatch.setattr(error_handler_module, "ERROR_LOG_FILE", str(log_file))

    # Drive the production setup path.
    import main

    main.setup_logging(
        {"general": {"log_file": str(log_file), "log_level": "INFO"}}
    )

    from gui.shared_state import SharedState

    shared_state = SharedState(error_handler=None)
    _ = error_handler_module.ErrorHandler(shared_state)

    handlers = _file_handlers_for_path(str(log_file))
    descriptions = [
        f"logger={lg.name!r} handler={h!r}"
        for lg in _iter_all_loggers()
        for h in lg.handlers
        if h in handlers
    ]
    assert len(handlers) == 1, (
        f"Single_Writer_Invariant violated: {len(handlers)} FileHandlers "
        f"target {log_file}.\n  " + "\n  ".join(descriptions)
    )


# ---------------------------------------------------------------------------
# Part B — no raw open(..., 'a') writer in gui/error_handler.py
# ---------------------------------------------------------------------------


def _collect_append_open_calls(source: str):
    """Return ``[(lineno, snippet), ...]`` for every ``open(..., mode)`` call
    in ``source`` whose mode string contains ``'a'``."""
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_open = (
            (isinstance(func, ast.Name) and func.id == "open")
            or (isinstance(func, ast.Attribute) and func.attr == "open")
        )
        if not is_open:
            continue

        mode = None
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            mode = node.args[1].value
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = kw.value.value

        if isinstance(mode, str) and "a" in mode:
            try:
                snippet = ast.unparse(node)
            except AttributeError:  # pragma: no cover — Python < 3.9
                snippet = f"<call at line {node.lineno}>"
            offenders.append((node.lineno, snippet))
    return offenders


@pytest.mark.xfail(
    reason="R2 baseline — current tree has duplicate writers; Task 3.3 flips this off",
    strict=True,
)
def test_no_raw_append_open_in_error_handler():
    """``gui/error_handler.py`` SHALL NOT contain any ``open(..., 'a')`` call.

    The raw append writer at ``_log_to_file`` bypasses the logging subsystem
    and therefore violates the Single_Writer_Invariant. Task 3.2 removes the
    raw writer; this assertion flips out of xfail in Task 3.3.

    **Validates: Requirements 2.4, 40.1**
    """
    source = ERROR_HANDLER_PATH.read_text(encoding="utf-8")
    offenders = _collect_append_open_calls(source)

    rendered = "\n  ".join(f"line {ln}: {s}" for ln, s in offenders)
    assert not offenders, (
        "gui/error_handler.py contains raw append open() calls that bypass "
        f"the Single_Writer_Invariant:\n  {rendered}"
    )
