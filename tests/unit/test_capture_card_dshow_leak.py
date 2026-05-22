"""
Bug condition exploration test for Bug 4 (codebase-bug-fixes spec).

Property 1: Bug Condition - ``cv2.VideoCapture`` DSHOW Handle Leak In
``CaptureCardCapture.initialize()``.

This test encodes the release-before-reassignment invariant for
``capture/capture_card.py::CaptureCardCapture.initialize()`` at approximately
lines 165-175, where the DSHOW fallback occurs::

    self._cap = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)

    if not self._cap.isOpened():
        # Fallback: try without explicit backend
        self._cap = cv2.VideoCapture(self.device_index)

**Validates: Requirements 1.4**

Expected outcome on UNFIXED code: test FAILS. The failure surfaces a
counterexample in the recorded call trace — ``fallback_ctor`` arrives directly
after ``DSHOW_isOpened`` with no ``DSHOW_release`` in between — which confirms
Bug 4 (the DSHOW handle is orphaned by the reassignment).

Expected outcome after the Bug 4 fix: test PASSES. The DSHOW handle's
``release()`` is invoked between the two constructor calls, and the release
is wrapped in ``try/except`` so even a driver whose ``isOpened()`` raises
still triggers cleanup.

The test is deterministic and scoped per the design's "Scoped PBT Approach"
for this bug: ``cv2.VideoCapture`` is patched in the ``capture.capture_card``
module namespace with a factory that tracks instances and records every
``isOpened``/``release``/``read`` call into a shared ordered trace.
"""

from __future__ import annotations

from typing import List

import pytest

from tests.unit._capture_card_mocks import (
    _MockHandle,
    _VideoCaptureFactory,
    _StubThread,
    _run_initialize_with_mocks,
    _events_between,
    capture_card,
    CaptureCardCapture,
)


# ---------------------------------------------------------------------------
# Property 1a: DSHOW handle is released before the fallback constructor runs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBug4DshowHandleLeak:
    """Ordered-trace assertions encoding design Bug 4 ``isBugCondition``.

    Per the design's pseudocode, after ``initialize()`` returns, the following
    must hold between the first and second ``cv2.VideoCapture`` constructor
    calls::

        first_cap_created   AND NOT first_not_opened_skipped
        AND released_between == True (i.e. self._cap.release() was called
                                       on the DSHOW handle before the
                                       fallback ctor runs)

    On UNFIXED code, ``released_between`` is ``False`` and the assertions
    below fail — that failure is the success case of this exploration test.
    """

    def test_dshow_release_recorded_before_fallback_ctor(self) -> None:
        """Happy-path bug-condition check: isOpened() returns False cleanly.

        Scripts the DSHOW handle to return ``isOpened() == False`` and the
        fallback handle to return ``isOpened() == True``. The critical
        assertion is that the ordered trace contains ``DSHOW_release`` before
        ``fallback_ctor``.
        """
        trace: List[str] = []
        dshow_handle = _MockHandle(
            "DSHOW", trace, opened=False, read_ok=False
        )
        fallback_handle = _MockHandle(
            # The fallback is configured to return ``read() -> (False, None)``
            # so ``initialize()`` short-circuits before spawning a thread,
            # keeping the test deterministic even without the thread stub.
            "fallback", trace, opened=True, read_ok=False,
        )

        outcome = _run_initialize_with_mocks(
            [dshow_handle, fallback_handle], trace
        )

        # Both constructors must have been called exactly once each.
        assert trace.count("DSHOW_ctor") == 1, (
            f"Expected exactly one DSHOW constructor call; trace: {trace!r}"
        )
        assert trace.count("fallback_ctor") == 1, (
            f"Expected exactly one fallback constructor call; trace: {trace!r}"
        )

        # The headline property: DSHOW_release must appear between the two
        # constructor calls.
        dshow_ctor_idx = trace.index("DSHOW_ctor")
        fallback_ctor_idx = trace.index("fallback_ctor")
        assert fallback_ctor_idx > dshow_ctor_idx, (
            f"Fallback constructor should come after DSHOW; trace: {trace!r}"
        )
        between = trace[dshow_ctor_idx + 1 : fallback_ctor_idx]
        assert "DSHOW_release" in between, (
            "Bug 4 reproduced: DSHOW handle is orphaned by reassignment "
            "without release().\n"
            f"  full trace           : {trace!r}\n"
            f"  events between ctors : {between!r}\n"
            "  expected contract    : DSHOW_release must appear between "
            "DSHOW_ctor and fallback_ctor\n"
            "  expected ordering    : [DSHOW_ctor, DSHOW_isOpened, "
            "DSHOW_release, fallback_ctor, ...]"
        )

        # And the DSHOW handle itself must report having been released.
        assert dshow_handle.released, (
            "DSHOW handle reports it was never released before the fallback "
            "constructor ran; Bug 4 reproduced. "
            f"trace: {trace!r}"
        )

        # Sanity: initialize() never raised and the instance ended up
        # tracking the fallback handle (regardless of whether the overall
        # initialization ultimately succeeded).
        assert outcome.cap is fallback_handle, (
            "After the DSHOW fallback, self._cap must reference the "
            "fallback handle."
        )

    def test_dshow_release_recorded_when_is_opened_raises(self) -> None:
        """Robustness variant: ``isOpened()`` raises on the DSHOW handle.

        Per design Bug 4 ``Preservation Requirements``:
            "No new exceptions SHALL escape ``initialize()``; the cleanup
            SHALL be guarded (e.g., try/except around ``release()``) so a
            misbehaving driver cannot convert a recoverable failure into
            a crash."

        This variant scripts the DSHOW handle so ``isOpened()`` raises. After
        the fix, ``initialize()`` must still call ``release()`` on the DSHOW
        handle (wrapped in ``try/except``) and then either attempt the
        fallback or return ``False`` — but without leaking the DSHOW handle
        and without letting the driver's exception escape.

        Expected outcome on UNFIXED code: FAILS. The outer ``except`` in
        ``initialize()`` swallows the exception and the DSHOW handle is
        never released.
        """
        trace: List[str] = []
        dshow_handle = _MockHandle(
            "DSHOW", trace, opened=False, is_opened_raises=True
        )
        # Provide a fallback handle so, if the fix chooses to attempt the
        # fallback after the raising isOpened(), the mock has something to
        # return. If the fix instead returns False without attempting the
        # fallback, the factory is simply never called a second time.
        fallback_handle = _MockHandle(
            "fallback", trace, opened=True, read_ok=False,
        )

        outcome = _run_initialize_with_mocks(
            [dshow_handle, fallback_handle], trace
        )

        # The exception raised by the mock driver MUST NOT escape initialize().
        # ``_run_initialize_with_mocks`` would have propagated any uncaught
        # exception; reaching this point proves containment.
        assert outcome.result in (True, False), (
            f"initialize() must return a boolean, got: {outcome.result!r}"
        )

        # The DSHOW handle must have been released despite the raising
        # isOpened(). This is the core of the Bug 4 cleanup contract.
        assert "DSHOW_release" in trace, (
            "Bug 4 reproduced (variant: isOpened raises): DSHOW handle "
            "was never released after its isOpened() raised.\n"
            f"  full trace         : {trace!r}\n"
            "  expected ordering  : DSHOW_release must appear in the trace\n"
            "  expected contract  : the cleanup MUST be wrapped in "
            "try/except so driver failures cannot leak the native handle."
        )
        assert dshow_handle.released, (
            "DSHOW mock handle reports it was never released even though "
            "isOpened() raised; the cleanup is missing. "
            f"trace: {trace!r}"
        )

        # If initialize() proceeded to the fallback after releasing the
        # DSHOW handle, the ordered trace must still have DSHOW_release
        # appear BEFORE fallback_ctor. If it did not attempt the fallback,
        # there simply is no fallback_ctor in the trace — also acceptable.
        if "fallback_ctor" in trace:
            dshow_release_idx = trace.index("DSHOW_release")
            fallback_ctor_idx = trace.index("fallback_ctor")
            assert dshow_release_idx < fallback_ctor_idx, (
                "When the fallback is attempted, DSHOW_release must precede "
                "fallback_ctor. "
                f"trace: {trace!r}"
            )
