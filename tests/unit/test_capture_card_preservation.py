"""
Preservation property tests for Bug 4 (codebase-bug-fixes spec).

Property 2: Preservation - Successful DSHOW Path, Return Semantics, Total-Failure
Path, and Exception Containment Unchanged.

These tests encode the baseline behavior that the Bug 4 fix in
``capture/capture_card.py::CaptureCardCapture.initialize()`` MUST preserve.
They follow the observation-first methodology from ``design.md`` and
``tasks.md`` Task 11: every property was derived by observing the behavior of
the UNFIXED ``CaptureCardCapture.initialize()``, and every property MUST PASS
on the unfixed code.

**Validates: Requirements 3.4, 5.1**

The properties from Task 11 are:

1. For every invocation where DSHOW ``isOpened()`` is ``True``, the mock
   records zero ``release()`` calls during ``initialize()`` and exactly one
   ``VideoCapture(device_index, cv2.CAP_DSHOW)`` construction. ``initialize()``
   returns ``True``. ``self._cap`` is the DSHOW handle. ``self._running`` is
   ``True``. The background thread is started (stubbed).

2. Success/failure signalling matches the observed baseline across the
   combinatorial cases {DSHOW_opened ∈ {True, False}} × {fallback_opened ∈
   {True, False}}. ``True`` on DSHOW-opened success. ``True`` on the
   DSHOW-fails-but-fallback-succeeds path (this is the happy path of the
   reassignment; on unfixed code the DSHOW handle is leaked BUT the function
   still returns ``True`` and captures via the fallback — this is acceptable
   baseline behavior; the fix must preserve the ``True`` return). On total
   failure (neither constructor produces an opened handle) the post-R5.1
   contract is to raise :class:`CaptureException` with a descriptive message
   naming the ``device_index`` instead of returning ``False`` — the audit-
   remediation spec promoted the silent ``return False`` into a structured
   signal so callers can branch on exception type.

3. ``initialize()`` never lets an exception other than
   :class:`CaptureException` escape on any code path — the outer ``except``
   in the current implementation still catches driver failures so a
   misbehaving ``isOpened()`` does not escalate into an unrelated crash,
   and ``CaptureException`` is the only structured signal.

4. Log-message preservation: on total failure the logger emits
   ``"Cannot open capture card at device index {device_index}"`` at ``ERROR``
   level, then ``CaptureException`` is raised with a matching message.

5. The ``self._running`` flag reflects success vs. failure: ``True`` after a
   successful ``initialize()`` (so the capture loop can run), ``False`` (or
   still ``False``) after failure (whether that failure is a ``False``
   return or a raised ``CaptureException``).

These tests share the mock infrastructure with
``tests/unit/test_capture_card_dshow_leak.py`` via
``tests/unit/_capture_card_mocks.py`` (``_MockHandle``,
``_VideoCaptureFactory``, ``_StubThread``, and ``_run_initialize_with_mocks``).
"""

from __future__ import annotations

import logging
from typing import List

import pytest

from exceptions import CaptureException
from tests.unit._capture_card_mocks import (
    _MockHandle,
    _run_initialize_with_mocks,
)


# ---------------------------------------------------------------------------
# Preservation Property 1: DSHOW-opened success path is untouched
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBug4PreservationSuccessfulDshowPath:
    """When DSHOW ``isOpened()`` is True, ``initialize()`` must use the DSHOW
    handle unchanged — no release calls, exactly one DSHOW constructor, and a
    ``True`` return. This is the behavior the Bug 4 fix must preserve.
    """

    def test_dshow_opened_zero_releases_during_initialize(self) -> None:
        """Preservation property 1: no ``release()`` is invoked during
        ``initialize()`` when DSHOW opens successfully, and exactly one
        DSHOW-backed constructor call is recorded.
        """
        trace: List[str] = []
        dshow_handle = _MockHandle(
            "DSHOW", trace, opened=True, read_ok=True
        )

        outcome = _run_initialize_with_mocks([dshow_handle], trace)

        # Exactly one DSHOW construction, zero fallback constructions.
        assert trace.count("DSHOW_ctor") == 1, (
            "Expected exactly one DSHOW constructor call on the happy path; "
            f"trace: {trace!r}"
        )
        assert trace.count("fallback_ctor") == 0, (
            "Fallback constructor must NOT be called when DSHOW is opened; "
            f"trace: {trace!r}"
        )

        # Zero release() calls during initialize() on the successful path.
        dshow_release_count = trace.count("DSHOW_release")
        assert dshow_release_count == 0, (
            "Preservation violated: DSHOW handle was released during "
            f"initialize() on the successful path. trace: {trace!r}"
        )
        assert dshow_handle.released is False, (
            "DSHOW handle reports it was released even though initialize() "
            "succeeded on the first attempt."
        )

        # Return value and instance state.
        assert outcome.result is True, (
            f"initialize() must return True when DSHOW opens; got {outcome.result!r}"
        )
        assert outcome.cap is dshow_handle, (
            "On the DSHOW-opened path self._cap must reference the DSHOW "
            f"handle; got {outcome.cap!r}"
        )
        assert outcome.running is True, (
            "self._running must be True after a successful initialize(); "
            f"got {outcome.running!r}"
        )
        assert outcome.instance.initialized is True, (
            "self.initialized must be True after a successful initialize()"
        )

    def test_dshow_opened_trace_ordering_observed_baseline(self) -> None:
        """Preservation sanity check: ordered event trace on the DSHOW-opened
        path matches the observed baseline — ``DSHOW_ctor`` precedes
        ``DSHOW_read`` and no fallback events appear.
        """
        trace: List[str] = []
        dshow_handle = _MockHandle(
            "DSHOW", trace, opened=True, read_ok=True
        )

        outcome = _run_initialize_with_mocks([dshow_handle], trace)

        assert outcome.result is True
        # DSHOW_ctor must appear exactly once and before DSHOW_read.
        assert "DSHOW_ctor" in trace
        assert "DSHOW_read" in trace
        assert trace.index("DSHOW_ctor") < trace.index("DSHOW_read"), (
            f"DSHOW_ctor must precede DSHOW_read; trace: {trace!r}"
        )
        # No fallback-labelled events whatsoever.
        assert not any(evt.startswith("fallback_") for evt in trace), (
            f"Unexpected fallback-labelled events on DSHOW-opened path: {trace!r}"
        )


# ---------------------------------------------------------------------------
# Preservation Property 2: Fallback happy path still returns True
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBug4PreservationFallbackHappyPath:
    """When DSHOW ``isOpened()`` is False but the fallback constructor
    produces an opened handle whose ``read()`` succeeds, ``initialize()``
    must return ``True`` and ``self._cap`` must be the fallback handle.

    On the UNFIXED code the DSHOW handle is leaked in this path (Bug 4) BUT
    the function nonetheless returns ``True`` and captures via the fallback.
    That ``True`` return is part of the contract the fix must preserve.
    """

    def test_fallback_opened_returns_true_and_uses_fallback_handle(self) -> None:
        trace: List[str] = []
        dshow_handle = _MockHandle(
            "DSHOW", trace, opened=False, read_ok=False
        )
        fallback_handle = _MockHandle(
            "fallback", trace, opened=True, read_ok=True
        )

        outcome = _run_initialize_with_mocks(
            [dshow_handle, fallback_handle], trace
        )

        # Return value and final handle reference.
        assert outcome.result is True, (
            "initialize() must return True when the fallback opens "
            "successfully (even though the DSHOW handle leaks on unfixed "
            f"code); got {outcome.result!r}"
        )
        assert outcome.cap is fallback_handle, (
            "After the fallback succeeds, self._cap must reference the "
            f"fallback handle; got {outcome.cap!r}"
        )
        assert outcome.running is True, (
            "self._running must be True after a successful fallback "
            f"initialize(); got {outcome.running!r}"
        )
        assert outcome.instance.initialized is True, (
            "self.initialized must be True after a successful fallback "
            "initialize()"
        )

        # Exactly one DSHOW ctor and exactly one fallback ctor.
        assert trace.count("DSHOW_ctor") == 1, (
            f"Expected one DSHOW constructor; trace: {trace!r}"
        )
        assert trace.count("fallback_ctor") == 1, (
            f"Expected one fallback constructor; trace: {trace!r}"
        )
        # DSHOW_ctor must precede fallback_ctor.
        assert trace.index("DSHOW_ctor") < trace.index("fallback_ctor"), (
            f"DSHOW_ctor must precede fallback_ctor; trace: {trace!r}"
        )
        # The fallback handle's read must have been exercised.
        assert "fallback_read" in trace, (
            "Fallback's test read must run when the fallback is opened; "
            f"trace: {trace!r}"
        )


# ---------------------------------------------------------------------------
# Preservation Property 3: Total-failure return value and log message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBug4PreservationTotalFailure:
    """When neither constructor produces an opened handle, ``initialize()``
    must raise :class:`CaptureException` with a descriptive message naming
    the ``device_index``, emit the documented error log, and leave the
    instance in its non-running, non-initialized state.

    Pre-R5.1 the method silently returned ``False``; the audit-remediation
    promoted that signal to a structured exception (Requirement 5.1) so the
    rest of the framework can branch on exception type instead of a bare
    boolean.
    """

    def test_both_unopened_raises_capture_exception(self, caplog) -> None:
        trace: List[str] = []
        dshow_handle = _MockHandle(
            "DSHOW", trace, opened=False, read_ok=False
        )
        fallback_handle = _MockHandle(
            "fallback", trace, opened=False, read_ok=False
        )

        with caplog.at_level(logging.ERROR, logger="capture.capture_card"), \
                pytest.raises(CaptureException) as exc_info:
            _run_initialize_with_mocks(
                [dshow_handle, fallback_handle], trace
            )

        # The exception message must name the failing device_index (R5.1 —
        # "with a descriptive message").
        assert "0" in str(exc_info.value), (
            "CaptureException message must identify the failing device "
            f"index; got {exc_info.value!r}"
        )

        # Both constructors must have been called exactly once.
        assert trace.count("DSHOW_ctor") == 1
        assert trace.count("fallback_ctor") == 1

        # The device-index error message is emitted at ERROR level on the
        # capture.capture_card logger. The observed format uses the instance's
        # device_index (0 in this fixture).
        expected_message = "Cannot open capture card at device index 0"
        matching_records = [
            rec for rec in caplog.records
            if rec.levelno == logging.ERROR
            and rec.name == "capture.capture_card"
            and expected_message in rec.getMessage()
        ]
        assert matching_records, (
            "Expected the documented total-failure error log "
            f"{expected_message!r} at ERROR level on 'capture.capture_card'. "
            f"Observed records: {[(r.name, r.levelname, r.getMessage()) for r in caplog.records]!r}"
        )


# ---------------------------------------------------------------------------
# Preservation Property 4: initialize() never raises uncaught exceptions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBug4PreservationExceptionContainment:
    """``initialize()`` must never let an *unrelated* exception escape. The
    current implementation's outer ``try/except Exception`` catches driver
    failures and returns ``False``; the Bug 4 fix must preserve that
    containment.

    The audit-remediation (R5.1) introduces a *structured* failure signal:
    when neither capture backend produces an opened handle,
    ``initialize()`` raises :class:`CaptureException` with a descriptive
    message. That is the only exception type that may escape
    ``initialize()`` — misbehaving drivers (``isOpened()`` raising, etc.)
    must still be contained and surfaced as ``return False``.
    """

    # The combinatorial observed-baseline matrix from Task 11 (updated for R5.1):
    #
    # (DSHOW_opened, fallback_opened, dshow_raises) → expected outcome
    # Case A:  True,   —,             False              → returns True
    # Case B:  False,  True,          False              → returns True
    # Case C:  False,  False,         False              → raises CaptureException (R5.1)
    # Case D:  —,      False,         True (dshow raise) → returns False (driver-misbehave containment)
    @pytest.mark.parametrize(
        ("dshow_opened", "dshow_read_ok", "fallback_opened", "fallback_read_ok",
         "dshow_raises", "expected_result", "expect_fallback_ctor"),
        [
            pytest.param(
                True, True, False, False, False, True, False,
                id="case_a_dshow_opens_and_reads",
            ),
            pytest.param(
                False, False, True, True, False, True, True,
                id="case_b_fallback_opens_and_reads",
            ),
            pytest.param(
                # R5.1: total failure now raises CaptureException instead
                # of returning False. The sentinel "raises" flags the case.
                False, False, False, False, False, "raises", True,
                id="case_c_both_unopened",
            ),
            pytest.param(
                False, False, False, False, True, False, False,
                id="case_d_dshow_isopened_raises",
            ),
        ],
    )
    def test_initialize_never_raises_and_returns_expected_bool(
        self,
        dshow_opened: bool,
        dshow_read_ok: bool,
        fallback_opened: bool,
        fallback_read_ok: bool,
        dshow_raises: bool,
        expected_result,
        expect_fallback_ctor: bool,
    ) -> None:
        trace: List[str] = []
        dshow_handle = _MockHandle(
            "DSHOW",
            trace,
            opened=dshow_opened,
            is_opened_raises=dshow_raises,
            read_ok=dshow_read_ok,
        )
        fallback_handle = _MockHandle(
            "fallback",
            trace,
            opened=fallback_opened,
            read_ok=fallback_read_ok,
        )

        if expected_result == "raises":
            # R5.1: total-failure path now signals via CaptureException.
            with pytest.raises(CaptureException):
                _run_initialize_with_mocks(
                    [dshow_handle, fallback_handle], trace
                )

            # Constructor trace expectations per case — even when we raise,
            # the fallback ctor must have been attempted first.
            assert trace.count("DSHOW_ctor") == 1, (
                f"Expected exactly one DSHOW constructor call; trace: {trace!r}"
            )
            if expect_fallback_ctor:
                assert trace.count("fallback_ctor") == 1, (
                    f"Expected one fallback constructor call; trace: {trace!r}"
                )
            else:
                assert trace.count("fallback_ctor") == 0, (
                    "Fallback constructor must NOT be called in this case; "
                    f"trace: {trace!r}"
                )
            return

        # ``_run_initialize_with_mocks`` would propagate any exception
        # escaping ``initialize()`` — reaching the assertions below proves
        # the containment contract holds for non-R5.1 paths.
        outcome = _run_initialize_with_mocks(
            [dshow_handle, fallback_handle], trace
        )

        assert outcome.result is expected_result, (
            f"Case mismatch: expected initialize() to return {expected_result!r}, "
            f"got {outcome.result!r}. trace: {trace!r}"
        )
        assert isinstance(outcome.result, bool), (
            f"initialize() must return a bool; got {type(outcome.result).__name__}"
        )

        # Running flag reflects success vs. failure.
        if expected_result is True:
            assert outcome.running is True, (
                "self._running must be True after a successful initialize()"
            )
            assert outcome.instance.initialized is True
        else:
            assert outcome.running is False, (
                "self._running must not be True after a failed initialize()"
            )
            assert outcome.instance.initialized is False

        # Constructor trace expectations per case.
        assert trace.count("DSHOW_ctor") == 1, (
            f"Expected exactly one DSHOW constructor call; trace: {trace!r}"
        )
        if expect_fallback_ctor:
            assert trace.count("fallback_ctor") == 1, (
                f"Expected one fallback constructor call; trace: {trace!r}"
            )
        else:
            assert trace.count("fallback_ctor") == 0, (
                "Fallback constructor must NOT be called in this case; "
                f"trace: {trace!r}"
            )
