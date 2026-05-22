"""Integration tests for the refactored ``input/`` package.

Task 3.3 of the ``single-config-streamlining`` spec verifies that the
``input/`` package has been reduced to the Target_Configuration surface:
only the ``kmbox_net`` driver and its supporting humanization / 240 Hz
output scheduler are exposed.

Updated by ``aim-pipeline-simplification`` task 3.9 (req 2.14, 4.7,
4.8): ``input/aim_output.py`` (the 240 Hz blender) and
``input/humanizer.py`` (every helper had zero live callers
post-simplification) are deleted. Their entries are moved from KEEP to
REMOVED, and their re-exports are dropped from ``input.__all__``.

All legacy single-PC drivers (DD, Interception, WinAPI, MAKCU
serial/socket, KmBox serial, EFI) must be physically removed and must
raise ``ImportError`` when referenced by name from the package.

Validates Requirements 3.1, 3.2, 3.3, 3.4, 3.5 and 3.6 (single-config
streamlining) plus aim-pipeline-simplification req 2.14 / 4.7 / 4.8.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


# --- Workspace layout -----------------------------------------------------

_WORKSPACE = Path(__file__).resolve().parents[2]
_INPUT_DIR = _WORKSPACE / "input"

# Files that must NOT exist in ``input/`` after the refactoring.
# ``efi_channel.py`` is included because the Audit_Document resolved it
# to ``REMOVE`` (Requirement 3.4). ``aim_output.py`` and ``humanizer.py``
# were removed by aim-pipeline-simplification task 3.8 (req 2.14, 4.7,
# 4.8): the 240 Hz blender collapsed into ``aim/pipeline.py::aim_step``
# and the canonical sub-pixel layer ``BaseMouse.calculate_move_amount``;
# every humanizer helper had zero live callers.
_REMOVED_FILES = (
    "dd_driver.py",
    "interception_driver.py",
    "winapi_mouse.py",
    "kmbox_serial_driver.py",
    "makcu_driver.py",
    "makcu_socket_driver.py",
    "efi_channel.py",
    "aim_output.py",
    "humanizer.py",
)

# Files that must exist in ``input/`` after the refactoring.
_KEPT_FILES = (
    "kmbox_net_driver.py",
    "base_mouse.py",
)

# Target ``__all__`` set per Requirement 3.5, narrowed by
# aim-pipeline-simplification task 3.8: ``AimOutput``, ``bezier_move``,
# ``calculate_reaction_delay``, ``add_micro_jitter``,
# ``calculate_smooth_factor``, ``calculate_shot_timing``, and
# ``humanize_mouse_movement`` are no longer re-exported because their
# host modules have been removed.
_EXPECTED_ALL = frozenset(
    {
        "ConnectionStatus",
        "KmBoxNetDriver",
        "BaseMouse",
    }
)

# Legacy symbols that must raise ``ImportError`` on ``from input import X``
# per Requirement 3.6.
_LEGACY_SYMBOLS = (
    "DDDriver",
    "InterceptionMouse",
    "WinAPIMouse",
    "MakcuSocketMouse",
    "MakcuDriver",
    "KmBoxSerialDriver",
)


# --- Filesystem invariants (Requirements 3.1, 3.2, 3.3, 3.4) --------------


@pytest.mark.integration
@pytest.mark.parametrize("filename", _REMOVED_FILES)
def test_removed_input_file_does_not_exist(filename: str) -> None:
    """Each legacy input driver file has been deleted.

    Validates: Requirements 3.1, 3.4.
    """
    path = _INPUT_DIR / filename
    assert not path.exists(), (
        f"Legacy input driver file {path} must be removed by task 3.1"
    )


@pytest.mark.integration
@pytest.mark.parametrize("filename", _KEPT_FILES)
def test_kept_input_file_exists(filename: str) -> None:
    """Each required input file is present in the refactored package.

    Validates: Requirements 3.2, 3.3.
    """
    path = _INPUT_DIR / filename
    assert path.is_file(), (
        f"Required input module {path} must be present in the "
        f"Refactored_Codebase"
    )
    assert path.stat().st_size > 0, (
        f"Required input module {path} must have non-zero size"
    )


# --- ``__all__`` invariant (Requirement 3.5) ------------------------------


@pytest.mark.integration
def test_input_package_all_matches_target_set() -> None:
    """``input.__all__`` equals the Target_Configuration symbol set.

    Validates: Requirement 3.5.
    """
    # Force a fresh import so any in-memory stale version is refreshed.
    import input as input_pkg

    input_pkg = importlib.reload(input_pkg)

    assert hasattr(input_pkg, "__all__"), (
        "input/__init__.py must define __all__"
    )
    actual = frozenset(input_pkg.__all__)
    assert actual == _EXPECTED_ALL, (
        f"input.__all__ must equal the target set.\n"
        f"  missing: {sorted(_EXPECTED_ALL - actual)}\n"
        f"  unexpected: {sorted(actual - _EXPECTED_ALL)}"
    )


# --- ImportError for legacy symbols (Requirement 3.6) ---------------------


@pytest.mark.integration
@pytest.mark.parametrize("symbol", _LEGACY_SYMBOLS)
def test_legacy_symbol_import_raises_import_error(symbol: str) -> None:
    """Importing legacy driver symbols from ``input`` raises ``ImportError``.

    Validates: Requirement 3.6.
    """
    # Ensure we import from a fresh module state so the failure is
    # observable rather than masked by module-level caching.
    import input as input_pkg  # noqa: F401  (imported for side effects)

    importlib.reload(input_pkg)

    with pytest.raises(ImportError):
        # Use ``exec`` so the static ``from ... import X`` statement runs
        # at test-time rather than at module collection. A failure must
        # surface as ``ImportError`` (not ``AttributeError`` or similar).
        exec(f"from input import {symbol}", {})


# --- Positive import path (Requirements 3.2, 3.3, 3.5) --------------------


@pytest.mark.integration
def test_target_symbols_are_importable() -> None:
    """The target driver and its supports import cleanly from ``input``.

    Validates: Requirements 3.2, 3.3, 3.5.
    """
    from input import BaseMouse, KmBoxNetDriver

    # Sanity-check that the imported names resolve to classes rather
    # than stubs, which would indicate a broken re-export.
    assert isinstance(KmBoxNetDriver, type), (
        "KmBoxNetDriver must be a class re-exported from input"
    )
    assert isinstance(BaseMouse, type), (
        "BaseMouse must be a class re-exported from input"
    )
