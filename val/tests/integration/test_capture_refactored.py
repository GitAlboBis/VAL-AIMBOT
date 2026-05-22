"""Integration tests for the ``capture/`` package after refactoring.

Task 2.3 of the ``single-config-streamlining`` spec verifies that the
capture package exposes exactly one capture backend
(``CaptureCardCapture``) and that the alternative backends have been
removed from the workspace.

The tests assert, for Requirements 2.1, 2.2, 2.3, 2.4 and 2.5:

* ``capture/dxgi_capture.py`` and ``capture/mss_capture.py`` do not exist
  on disk (Req 2.1, 2.2).
* ``capture/capture_card.py`` exists on disk (Req 2.3).
* ``capture/__init__.py`` declares ``__all__ == ["CaptureCardCapture"]``
  (Req 2.4).
* ``from capture import DXGICapture`` and ``from capture import MSSCapture``
  raise ``ImportError`` (Req 2.4, 2.5).
* ``from capture import CaptureCardCapture`` succeeds; if the optional
  runtime dependency ``cv2`` is missing the test tolerates the
  resulting ``ImportError`` (Req 2.3).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

# Workspace root: ``<repo>/tests/integration/test_capture_refactored.py``
# -> parents[2] == ``<repo>``.
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
CAPTURE_DIR = WORKSPACE_ROOT / "capture"


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Filesystem invariants (Req 2.1, 2.2, 2.3)
# ---------------------------------------------------------------------------


def test_dxgi_capture_module_is_absent() -> None:
    """``capture/dxgi_capture.py`` must not exist (Req 2.1)."""
    dxgi_path = CAPTURE_DIR / "dxgi_capture.py"
    assert not dxgi_path.exists(), (
        f"Expected {dxgi_path} to have been removed by the refactoring, "
        "but it still exists on disk."
    )


def test_mss_capture_module_is_absent() -> None:
    """``capture/mss_capture.py`` must not exist (Req 2.2)."""
    mss_path = CAPTURE_DIR / "mss_capture.py"
    assert not mss_path.exists(), (
        f"Expected {mss_path} to have been removed by the refactoring, "
        "but it still exists on disk."
    )


def test_capture_card_module_is_present() -> None:
    """``capture/capture_card.py`` must exist and be a regular file (Req 2.3)."""
    capture_card_path = CAPTURE_DIR / "capture_card.py"
    assert capture_card_path.exists(), (
        f"Expected {capture_card_path} to exist (single supported capture "
        "backend), but it was not found."
    )
    assert capture_card_path.is_file(), (
        f"Expected {capture_card_path} to be a regular file, "
        f"got something else."
    )


# ---------------------------------------------------------------------------
# Package-level invariants (Req 2.4)
# ---------------------------------------------------------------------------


def _fresh_capture_module():
    """Import ``capture`` in isolation, removing any cached entries first.

    This avoids cross-test interference from a prior partial import.
    """
    for cached in [name for name in sys.modules if name == "capture" or name.startswith("capture.")]:
        del sys.modules[cached]
    return importlib.import_module("capture")


def test_capture_all_contains_only_capture_card_capture() -> None:
    """``capture/__init__.py`` must declare ``__all__ == ["CaptureCardCapture"]`` (Req 2.4).

    The test tolerates ``ImportError`` originating from a missing optional
    runtime dependency (``cv2``/``numpy``) by falling back to parsing the
    ``__init__.py`` source with ``ast`` so that the invariant can still be
    checked in environments without the full capture stack installed.
    """
    try:
        capture_module = _fresh_capture_module()
    except ImportError as exc:
        # Fallback: parse ``__all__`` directly from the source file.
        import ast

        missing = str(exc)
        init_path = CAPTURE_DIR / "__init__.py"
        tree = ast.parse(init_path.read_text(encoding="utf-8"))
        all_value: list[str] | None = None
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        all_value = [
                            elt.value
                            for elt in node.value.elts  # type: ignore[attr-defined]
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        ]
        assert all_value == ["CaptureCardCapture"], (
            f"Expected __all__ == ['CaptureCardCapture'] in {init_path}, "
            f"got {all_value!r} (fallback parse triggered by ImportError: {missing})."
        )
        return

    assert hasattr(capture_module, "__all__"), (
        "capture/__init__.py must declare an __all__ attribute (Req 2.4)."
    )
    assert list(capture_module.__all__) == ["CaptureCardCapture"], (
        f"Expected capture.__all__ == ['CaptureCardCapture'], "
        f"got {list(capture_module.__all__)!r}."
    )


# ---------------------------------------------------------------------------
# Import-surface invariants (Req 2.4, 2.5)
# ---------------------------------------------------------------------------


def test_importing_dxgi_capture_raises_import_error() -> None:
    """``from capture import DXGICapture`` must raise ``ImportError`` (Req 2.4)."""
    # Ensure the package is imported fresh so previously-bound names do not leak.
    try:
        _fresh_capture_module()
    except ImportError:
        # If the package itself cannot import due to an optional dependency,
        # the symbol cannot be exposed either; the invariant holds trivially.
        pass

    with pytest.raises(ImportError):
        # ``importlib.import_module`` does not support ``from X import Y``
        # syntax directly; ``exec`` keeps the semantics explicit and visible.
        exec("from capture import DXGICapture", {})


def test_importing_mss_capture_raises_import_error() -> None:
    """``from capture import MSSCapture`` must raise ``ImportError`` (Req 2.4)."""
    try:
        _fresh_capture_module()
    except ImportError:
        pass

    with pytest.raises(ImportError):
        exec("from capture import MSSCapture", {})


def test_importing_capture_card_capture_succeeds_or_requires_cv2() -> None:
    """``from capture import CaptureCardCapture`` must work when cv2 is available (Req 2.3).

    If the optional runtime dependency ``cv2`` (OpenCV) is not installed in
    the current environment, the import is expected to fail with
    ``ImportError`` mentioning ``cv2``; that is an acceptable outcome for
    this test (the symbol is still declared in ``__all__``, which is checked
    by ``test_capture_all_contains_only_capture_card_capture``).
    """
    # Start from a clean slate.
    for cached in [name for name in sys.modules if name == "capture" or name.startswith("capture.")]:
        del sys.modules[cached]

    try:
        from capture import CaptureCardCapture  # noqa: F401 — imported for side effect/verification
    except ImportError as exc:
        message = str(exc).lower()
        assert "cv2" in message or "opencv" in message or "numpy" in message, (
            "ImportError while importing CaptureCardCapture must be caused by a "
            f"missing optional dependency (cv2/opencv/numpy); got: {exc!r}."
        )
        pytest.skip(f"Optional capture dependency unavailable: {exc}")
    else:
        # When the import succeeds the symbol must resolve to a class object
        # so that downstream callers can instantiate it.
        assert isinstance(CaptureCardCapture, type), (
            f"Expected CaptureCardCapture to be a class, got {type(CaptureCardCapture)!r}."
        )
