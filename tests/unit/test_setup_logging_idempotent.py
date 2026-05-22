"""
Unit tests for ``main.setup_logging`` (Task 3.1 / Requirements 2.1, 2.2).

``setup_logging`` is the sole installer of the ``FileHandler`` for the
configured ``general.log_file`` path. These tests lock in the idempotency
and single-writer-for-this-path guarantees independently of the Wave 0
property test in ``test_invariant_single_writer.py`` (which is flipped out
of ``xfail`` by Task 3.3 after Task 3.2 removes the duplicate handler
from ``gui/error_handler.py``).

Scope of this file:
    * ``setup_logging`` called N times produces exactly one root-logger
      ``FileHandler`` targeting the configured path (Requirement 2.1).
    * The chosen ``FileHandler`` points at the configured path, regardless
      of whether callers pass relative vs. absolute variants (Requirement
      2.2 / ``_same_path`` casefold comparison).
    * The console ``StreamHandler`` is installed once and not duplicated
      on repeat calls (preserves pre-existing behaviour).
    * A pre-existing ``FileHandler`` targeting the log path is removed
      and closed before the fresh handler is installed.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _iter_all_loggers():
    yield logging.getLogger()
    for lg in list(logging.root.manager.loggerDict.values()):
        if isinstance(lg, logging.Logger):
            yield lg


def _purge_file_handlers() -> None:
    """Remove and close every ``FileHandler`` on every logger so Windows
    does not hold a lock on ``tmp_path`` during cleanup."""
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


def _file_handlers_for_path(log_path: str):
    """Return every ``FileHandler`` on the root logger whose ``baseFilename``
    resolves to the same path as ``log_path``."""
    target = os.path.normcase(os.path.abspath(log_path))
    return [
        h for h in list(logging.getLogger().handlers)
        if isinstance(h, logging.FileHandler)
        and os.path.normcase(os.path.abspath(h.baseFilename)) == target
    ]


def _stream_handlers_non_file():
    return [
        h for h in list(logging.getLogger().handlers)
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
    ]


@pytest.fixture
def clean_logging():
    _purge_file_handlers()
    try:
        yield
    finally:
        _purge_file_handlers()


def test_setup_logging_installs_one_file_handler(tmp_path, clean_logging):
    """A single call produces exactly one ``FileHandler`` on the root logger
    for the configured path (Requirement 2.1)."""
    import main

    log_file = tmp_path / "errors.log"
    main.setup_logging(
        {"general": {"log_file": str(log_file), "log_level": "INFO"}}
    )

    handlers = _file_handlers_for_path(str(log_file))
    assert len(handlers) == 1, (
        f"Expected exactly 1 FileHandler for {log_file}, got {len(handlers)}: "
        f"{handlers!r}"
    )


def test_setup_logging_is_idempotent_across_repeat_calls(tmp_path, clean_logging):
    """Calling ``setup_logging`` N times with the same config yields the same
    single-``FileHandler`` state as one call (Requirement 2.2).

    Also verifies the console ``StreamHandler`` is installed at most once —
    repeat calls must not duplicate stderr output."""
    import main

    log_file = tmp_path / "errors.log"
    cfg = {"general": {"log_file": str(log_file), "log_level": "INFO"}}

    # First call establishes the baseline console handler; subsequent calls
    # must not add more. Measure the delta rather than an absolute count so
    # the test is robust to pytest's own LogCaptureHandler, etc.
    main.setup_logging(cfg)
    baseline_streams = _stream_handlers_non_file()

    for _ in range(4):
        main.setup_logging(cfg)

    handlers = _file_handlers_for_path(str(log_file))
    assert len(handlers) == 1, (
        f"setup_logging not idempotent: {len(handlers)} FileHandlers after 5 "
        f"calls: {handlers!r}"
    )

    after_streams = _stream_handlers_non_file()
    assert len(after_streams) == len(baseline_streams), (
        f"Console StreamHandler duplicated across repeat calls: baseline="
        f"{baseline_streams!r} after={after_streams!r}"
    )


def test_setup_logging_removes_preexisting_filehandler_for_same_path(
    tmp_path, clean_logging
):
    """A pre-existing ``FileHandler`` targeting the configured path is
    removed and closed before the fresh handler is installed; the survivor
    is a different object (Requirement 2.2 / Single_Writer_Invariant)."""
    import main

    log_file = tmp_path / "errors.log"

    pre_existing = logging.FileHandler(str(log_file), encoding="utf-8")
    logging.getLogger().addHandler(pre_existing)
    assert pre_existing in logging.getLogger().handlers

    main.setup_logging(
        {"general": {"log_file": str(log_file), "log_level": "INFO"}}
    )

    handlers = _file_handlers_for_path(str(log_file))
    assert len(handlers) == 1, (
        f"Expected exactly 1 FileHandler after replacement; got {handlers!r}"
    )
    assert handlers[0] is not pre_existing, (
        "Pre-existing FileHandler should have been removed and replaced"
    )
    # The replaced handler must also be closed so the file descriptor is
    # released on Windows.
    assert getattr(pre_existing, "stream", None) is None or pre_existing.stream.closed


def test_setup_logging_matches_relative_and_absolute_variants(
    tmp_path, clean_logging, monkeypatch
):
    """``_same_path`` must treat a relative and absolute form of the same
    file as the same writer so repeated callers with different spellings
    of the path do not create duplicate handlers (Requirement 2.2)."""
    import main

    monkeypatch.chdir(tmp_path)
    (tmp_path / "errors.log").write_text("", encoding="utf-8")

    # First call with the relative form.
    main.setup_logging(
        {"general": {"log_file": "errors.log", "log_level": "INFO"}}
    )
    # Second call with the absolute form.
    main.setup_logging(
        {"general": {"log_file": str(tmp_path / "errors.log"), "log_level": "INFO"}}
    )

    handlers = _file_handlers_for_path(str(tmp_path / "errors.log"))
    assert len(handlers) == 1, (
        "Relative vs. absolute variants of the same path produced duplicate "
        f"FileHandlers: {handlers!r}"
    )
