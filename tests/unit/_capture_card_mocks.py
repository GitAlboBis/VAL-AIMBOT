"""
Shared mock infrastructure for ``capture.capture_card`` tests.

This module is a non-test helper (leading underscore in the filename so pytest
does not collect it). It centralises the mock primitives introduced for the
Bug 4 exploration test in :mod:`tests.unit.test_capture_card_dshow_leak` so
additional bug-condition / preservation test modules can reuse the exact same
scaffolding.

Contents
--------

``_MockHandle``
    Lightweight stand-in for a :class:`cv2.VideoCapture` instance. Records
    every observed method call into a shared trace list so tests can assert
    the *ordering* of events, not just their counts.

``_VideoCaptureFactory``
    Callable that mirrors ``cv2.VideoCapture(...)`` construction. Dispenses
    pre-scripted :class:`_MockHandle` objects in order and records each
    constructor call into the shared trace.

``_StubThread``
    Stand-in for :class:`threading.Thread`. Implements the subset of the API
    the capture-card code uses (``start``, ``is_alive``, ``join``) without
    actually spawning a background loop, which keeps tests deterministic.

``_run_initialize_with_mocks``
    Patches ``cv2.VideoCapture`` and ``threading.Thread`` inside the
    ``capture.capture_card`` module namespace and drives
    :meth:`CaptureCardCapture.initialize`. Returns the call result, the
    factory, and the post-call state of the ``CaptureCardCapture`` instance.

``_events_between``
    Small helper for extracting the ordered sub-trace between two anchor
    events.

These helpers are intentionally dependency-free (only ``numpy``, stdlib, and
the project's own ``capture.capture_card`` module) so any test file can import
them cheaply.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import List
from unittest.mock import patch

import numpy as np


# ---------------------------------------------------------------------------
# Target module — imported once so every helper patches the same namespace.
# ---------------------------------------------------------------------------

capture_card = importlib.import_module("capture.capture_card")
CaptureCardCapture = capture_card.CaptureCardCapture


# ---------------------------------------------------------------------------
# Mock cv2.VideoCapture handle
# ---------------------------------------------------------------------------


class _MockHandle:
    """Scripted stand-in for a ``cv2.VideoCapture`` object.

    Every method call that :meth:`CaptureCardCapture.initialize` invokes is
    recorded into the shared ``trace`` list with a label prefix (``DSHOW`` or
    ``fallback``) so the test can assert the ordering of events rather than
    just their counts.
    """

    def __init__(
        self,
        label: str,
        trace: List[str],
        *,
        opened: bool,
        is_opened_raises: bool = False,
        read_ok: bool = False,
    ) -> None:
        self._label = label
        self._trace = trace
        self._opened = opened
        self._is_opened_raises = is_opened_raises
        self._read_ok = read_ok
        self._released = False

    # -- methods the real code under test calls -----------------------------

    def isOpened(self) -> bool:  # noqa: N802 — mirrors cv2 API
        self._trace.append(f"{self._label}_isOpened")
        if self._is_opened_raises:
            raise RuntimeError(
                f"Simulated driver failure during isOpened() on {self._label}"
            )
        return self._opened

    def release(self) -> None:
        self._trace.append(f"{self._label}_release")
        self._released = True

    def set(self, prop_id: int, value: float) -> bool:  # noqa: A003, ARG002
        # Capture-card code sets BUFFERSIZE, FOURCC, FRAME_WIDTH/HEIGHT, FPS.
        # Accept and ignore; ordering tests do not depend on these.
        return True

    def get(self, prop_id: int) -> float:  # noqa: ARG002
        # The real code reads CAP_PROP_FOURCC for format verification and
        # CAP_PROP_FRAME_WIDTH/HEIGHT for the resolution log line. Return a
        # plausible YUY2 fourcc (0x32595559) and a generic numeric for
        # dimensions so the success path progresses to the test read.
        return float(0x32595559)  # 'YUY2' in little-endian fourcc encoding

    def read(self):
        self._trace.append(f"{self._label}_read")
        if self._read_ok:
            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            return True, frame
        return False, None

    # -- introspection helpers for the test --------------------------------

    @property
    def label(self) -> str:
        return self._label

    @property
    def released(self) -> bool:
        return self._released


# ---------------------------------------------------------------------------
# Mock cv2.VideoCapture factory
# ---------------------------------------------------------------------------


class _VideoCaptureFactory:
    """Callable that mirrors ``cv2.VideoCapture(...)`` construction.

    The factory records every constructor invocation (including its argument
    shape) into the shared trace and returns a pre-scripted
    :class:`_MockHandle` so individual tests can control the DSHOW vs.
    fallback outcomes without touching real hardware.
    """

    def __init__(self, handles: List[_MockHandle], trace: List[str]) -> None:
        self._handles = list(handles)
        self._trace = trace
        self._next_index = 0
        # Expose the constructed handles so the test can inspect them after
        # initialize() has returned.
        self.constructed: List[_MockHandle] = []

    def __call__(self, *args, **kwargs) -> _MockHandle:
        # The capture-card code calls either
        #   cv2.VideoCapture(device_index, cv2.CAP_DSHOW)
        # or
        #   cv2.VideoCapture(device_index)
        # The argument arity is the signal for which call we're serving.
        if len(args) >= 2 or "apiPreference" in kwargs:
            label_hint = "DSHOW"
        else:
            label_hint = "fallback"

        handle = self._handles[self._next_index]
        self._next_index += 1

        # Verify the label the test author expected matches the call shape.
        assert handle.label == label_hint, (
            f"Mock script drift: handle #{self._next_index - 1} is labelled "
            f"{handle.label!r} but the call shape suggests {label_hint!r} "
            f"(args={args!r}, kwargs={kwargs!r})."
        )

        self._trace.append(f"{handle.label}_ctor")
        self.constructed.append(handle)
        return handle


# ---------------------------------------------------------------------------
# Mock threading.Thread
# ---------------------------------------------------------------------------


class _StubThread:
    """Stand-in for ``threading.Thread`` used during ``initialize()`` tests.

    The real capture loop runs in a daemon thread and would otherwise call
    the mock handles' ``read()`` / ``isOpened()`` methods after the test body
    has already made its assertions, producing confusing late writes into the
    shared trace. This stub matches the subset of the ``Thread`` API the
    capture-card code invokes (``__init__``, ``start``, ``is_alive``,
    ``join``) without spawning anything.
    """

    def __init__(self, *args, **kwargs) -> None:  # noqa: ARG002
        self._started = False
        self.daemon = kwargs.get("daemon", False)
        self.name = kwargs.get("name", "stub")

    def start(self) -> None:
        self._started = True

    def is_alive(self) -> bool:
        return False

    def join(self, timeout: float | None = None) -> None:  # noqa: ARG002
        return None


# ---------------------------------------------------------------------------
# High-level driver helper
# ---------------------------------------------------------------------------


def _run_initialize_with_mocks(
    handles: List[_MockHandle],
    trace: List[str],
    *,
    device_index: int = 0,
    fourcc: str = "YUY2",
    width: int = 1920,
    height: int = 1080,
    target_fps: int = 60,
) -> SimpleNamespace:
    """Patch ``cv2.VideoCapture`` / ``threading.Thread`` and run ``initialize``.

    Returns a ``SimpleNamespace`` with:
        ``result``      — the value ``initialize()`` returned.
        ``factory``     — the factory so the test can inspect constructed handles.
        ``cap``         — the instance's ``_cap`` after the call.
        ``running``     — whether the background thread is still flagged to run.
        ``instance``    — the ``CaptureCardCapture`` instance itself.
    """
    factory = _VideoCaptureFactory(handles, trace)

    capture = CaptureCardCapture(
        device_index=device_index,
        fourcc=fourcc,
        width=width,
        height=height,
    )

    with patch.object(capture_card.cv2, "VideoCapture", factory), \
         patch.object(capture_card.threading, "Thread", _StubThread):
        result = capture.initialize(target_fps=target_fps)

    return SimpleNamespace(
        result=result,
        factory=factory,
        cap=capture._cap,
        running=capture._running,
        instance=capture,
    )


# ---------------------------------------------------------------------------
# Trace inspection utility
# ---------------------------------------------------------------------------


def _events_between(trace: List[str], start: str, end: str) -> List[str]:
    """Return the sublist of ``trace`` strictly between the first ``start``
    occurrence and the first subsequent ``end`` occurrence.

    If either anchor is missing or they appear in the wrong order, an empty
    list is returned — the calling assertion is responsible for reporting
    the richer diagnostic (it already prints the full trace).
    """
    try:
        start_idx = trace.index(start)
    except ValueError:
        return []
    try:
        end_idx = trace.index(end, start_idx + 1)
    except ValueError:
        return []
    return trace[start_idx + 1 : end_idx]


__all__ = [
    "capture_card",
    "CaptureCardCapture",
    "_MockHandle",
    "_VideoCaptureFactory",
    "_StubThread",
    "_run_initialize_with_mocks",
    "_events_between",
]
