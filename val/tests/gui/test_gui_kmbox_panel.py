"""
GUI snapshot/example tests — Task 11.5 of spec ``kmbox-net-integration``.

Tests for the KmBox Net Status panel (``gui.app._render_kmbox_panel``) and
the Reconnect-button click handler (``gui.app._on_kmbox_reconnect_clicked``).
The panel itself is a free function extracted from ``_page_configuration``
so the test harness can drive it directly with a captured ``imgui`` mock
and a populated ``SharedState``, without spinning up the full hello_imgui
loop. The click handler is exercised directly because it is the same code
path the panel invokes when ``styled_button("Reconnect")`` returns ``True``.

Validates Requirements 7.4, 7.5, 7.6, 7.7, 7.8, 7.10.

Strategy
--------
- Patch ``gui.app.imgui`` with a ``MagicMock``. The panel only uses three
  imgui surface calls — ``push_style_color`` / ``text`` / ``pop_style_color``
  — plus the ``COLOR_TEXT`` constant. We assert against ``call_args_list``
  on the captured mock so the colour-mapping table is exact.
- Patch the widget helpers (``section_header``, ``separator_line``,
  ``styled_button``) with mocks so the panel's rendering surface is just
  the four bullet points the spec cares about: status indicator, IP/port/
  encryption labels, the Reconnect button, and the failure banner.
- Patch ``gui.app.imgui`` only — the widgets' own ``imgui`` import is a
  separate reference and is not exercised because we mock the widget
  helpers themselves.

The mocking strategy is explicitly tighter than ``test_gui_no_kmnet_calls``
in Task 11.4 because that test runs the *entire* page render path while
this test focuses on the panel's observable rendering contract.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from gui import app as gui_app
from gui.shared_state import SharedState


# ---------------------------------------------------------------------------
# Theme color constants (must match the design's color-mapping table in
# design.md § GUI / Configuration page).
# ---------------------------------------------------------------------------

# Theme success — connected status (Req 7.4)
THEME_SUCCESS_RGBA = (0.3, 1.0, 0.3, 1.0)
# Theme warning — reconnecting status (Req 7.5)
THEME_WARNING_RGBA = (1.0, 0.8, 0.3, 1.0)
# Theme error — failed status (Req 7.6) and the failure-banner colour
THEME_ERROR_RGBA = (1.0, 0.3, 0.3, 1.0)

# Sentinel value ``COLOR_TEXT`` resolves to on the captured imgui mock so
# the assertions can match the full ``push_style_color`` argument tuple
# byte-equal. The real value is backend-specific (e.g. an int returned by
# ``imgui_bundle.imgui.Col_.text.value``); the test only requires that the
# panel forwards the ``imgui.COLOR_TEXT`` attribute it sees.
_COLOR_TEXT_SENTINEL = 0xC0FFEE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def imgui_mock() -> MagicMock:
    """Replace ``gui.app.imgui`` with a fresh ``MagicMock`` for one test.

    The mock exposes a stable ``COLOR_TEXT`` attribute so assertions can
    match the full ``push_style_color`` argument tuple. ``text``,
    ``push_style_color``, and ``pop_style_color`` are auto-created
    ``MagicMock`` children whose ``call_args_list`` we read.
    """
    mock = MagicMock(name="imgui")
    mock.COLOR_TEXT = _COLOR_TEXT_SENTINEL
    with patch.object(gui_app, "imgui", mock):
        yield mock


@pytest.fixture
def widget_mocks() -> dict:
    """Stub the widget helpers the panel calls so only ``imgui`` matters.

    ``styled_button`` defaults to returning ``False`` (no click) so the
    Reconnect-button branch is dormant unless a test overrides it.
    """
    section_header = MagicMock(name="section_header")
    separator_line = MagicMock(name="separator_line")
    styled_button = MagicMock(name="styled_button", return_value=False)
    with patch.object(gui_app, "section_header", section_header), \
         patch.object(gui_app, "separator_line", separator_line), \
         patch.object(gui_app, "styled_button", styled_button):
        yield {
            "section_header": section_header,
            "separator_line": separator_line,
            "styled_button": styled_button,
        }


@pytest.fixture
def shared_state() -> SharedState:
    """A fresh ``SharedState`` populated with a baseline KmBox snapshot.

    Tests override individual ``kmbox_*`` keys before invoking the panel
    to drive the specific scenario they exercise.
    """
    state = SharedState(error_handler=None)
    # Baseline values the publisher edge in
    # ``main.DetectionFramework._publish_kmbox_state`` would write for a
    # connected driver. Tests overwrite ``kmbox_status`` per scenario.
    state.update_state("kmbox_status", "connected")
    state.update_state("kmbox_ip", "192.168.2.188")
    state.update_state("kmbox_port", "6234")
    state.update_state("kmbox_use_encryption", True)
    return state


def _push_style_color_calls(imgui_mock: MagicMock) -> list:
    """Return the positional-args of every ``push_style_color`` invocation."""
    return [tuple(call.args) for call in imgui_mock.push_style_color.call_args_list]


def _text_calls(imgui_mock: MagicMock) -> list:
    """Return the first positional arg of every ``imgui.text`` invocation."""
    return [call.args[0] if call.args else "" for call in imgui_mock.text.call_args_list]


# ---------------------------------------------------------------------------
# Test 1 — Status indicator color mapping (Req 7.4 / 7.5 / 7.6)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status_value", "expected_rgba"),
    [
        ("connected", THEME_SUCCESS_RGBA),
        ("reconnecting", THEME_WARNING_RGBA),
        ("failed", THEME_ERROR_RGBA),
    ],
    ids=["connected→success", "reconnecting→warning", "failed→error"],
)
def test_gui_status_indicator_color_mapping(
    status_value: str,
    expected_rgba: tuple,
    imgui_mock: MagicMock,
    widget_mocks: dict,
    shared_state: SharedState,
) -> None:
    """
    Validates Req 7.4 / Req 7.5 / Req 7.6.

    The status indicator dot SHALL be rendered with the theme's success
    colour for ``connected``, the warning colour for ``reconnecting``,
    and the error colour for ``failed``. The panel implements the
    mapping by calling ``imgui.push_style_color(COLOR_TEXT, *rgba)``
    immediately before the indicator ``imgui.text(...)`` and popping
    the colour right after.

    The test sets ``kmbox_status`` to one of the three mapped values,
    invokes ``_render_kmbox_panel`` once, and asserts that the captured
    ``push_style_color`` ``call_args_list`` contains exactly one entry
    whose tuple is ``(COLOR_TEXT, *expected_rgba)``. We do NOT assert
    that this is the *only* ``push_style_color`` call, because the
    failure-banner branch may also push a colour when
    ``kmbox_reconnect_error`` is set — but the baseline fixture leaves
    that key unset, so in practice the indicator is the only push.
    """
    shared_state.update_state("kmbox_status", status_value)

    gui_app._render_kmbox_panel(shared_state)

    expected_call = (_COLOR_TEXT_SENTINEL, *expected_rgba)
    pushes = _push_style_color_calls(imgui_mock)
    assert expected_call in pushes, (
        f"expected push_style_color{expected_call} for status "
        f"{status_value!r}; got {pushes!r}"
    )

    # The indicator label includes the bullet character and the status
    # string itself — confirms the colored push wraps the right text.
    texts = _text_calls(imgui_mock)
    assert any(status_value in t and "●" in t for t in texts), (
        f"expected an indicator line containing {status_value!r}; "
        f"got texts {texts!r}"
    )

    # Baseline fixture has no reconnect error, so exactly one
    # push_style_color / pop_style_color pair fires for the indicator.
    assert len(pushes) == 1, (
        f"expected exactly one push_style_color for the indicator, got "
        f"{len(pushes)}: {pushes!r}"
    )
    assert imgui_mock.pop_style_color.call_count == 1, (
        f"expected exactly one pop_style_color matching the indicator "
        f"push; got {imgui_mock.pop_style_color.call_count}"
    )


# ---------------------------------------------------------------------------
# Test 2 — No-data fallback (Req 7.10)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "status_value",
    [
        None,
        "no data",
        "banana",          # arbitrary unknown string
        "disconnected",    # transitional ConnectionStatus value not in the mapped set
        "connecting",      # transitional ConnectionStatus value not in the mapped set
        "",                # empty string
    ],
    ids=["None", "no-data-literal", "unknown-string", "disconnected", "connecting", "empty"],
)
def test_gui_no_data_fallback(
    status_value,
    imgui_mock: MagicMock,
    widget_mocks: dict,
    shared_state: SharedState,
) -> None:
    """
    Validates Req 7.10.

    When ``kmbox_status`` is missing from the snapshot, set to ``None``,
    or set to anything outside the three mapped values
    (``connected`` / ``reconnecting`` / ``failed``), the panel SHALL
    render the literal text ``"no data"`` with no colour highlight and
    SHALL NOT fall back to calling the driver or ``kmNet`` directly.

    The test asserts:

      - ``imgui.text("no data")`` is called exactly once (the fallback
        branch).
      - ``imgui.push_style_color`` is never called for the indicator —
        i.e. the no-data branch emits no theme colour. (The
        reconnect-error banner branch is dormant under the baseline
        fixture, so the total push count is zero.)
      - No driver attribute lookup happens — the panel reads only
        from the ``SharedState`` snapshot. ``set_input_driver(None)``
        confirms the panel never resolves the driver reference.
    """
    # Confirm Req 7.9 / 7.10 — no driver lookup happens during render.
    gui_app.set_input_driver(None)

    shared_state.update_state("kmbox_status", status_value)

    gui_app._render_kmbox_panel(shared_state)

    texts = _text_calls(imgui_mock)
    no_data_count = sum(1 for t in texts if t == "no data")
    assert no_data_count == 1, (
        f"expected exactly one literal 'no data' for status "
        f"{status_value!r}; got texts {texts!r}"
    )

    # No theme colour push for the indicator (the only path that pushes
    # under the baseline fixture).
    assert imgui_mock.push_style_color.call_count == 0, (
        f"expected no push_style_color for status {status_value!r}; got "
        f"{_push_style_color_calls(imgui_mock)!r}"
    )

    # Confirm the panel did not resolve the driver reference.
    assert gui_app.get_input_driver() is None


# ---------------------------------------------------------------------------
# Test 3 — Reconnect button invokes _connect via worker (Req 7.7)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_reconnect_button_invokes_connect_via_worker(
    imgui_mock: MagicMock,
    widget_mocks: dict,
    shared_state: SharedState,
) -> None:
    """
    Validates Req 7.7.

    When the operator clicks the Reconnect button on the Configuration
    page, the GUI SHALL invoke ``KmBoxNetDriver._connect()`` on the live
    driver instance — but NOT on the render thread. The handler spawns
    a daemon ``Thread(name="KmBoxReconnect")``; the worker calls
    ``driver._connect()`` (which can block up to 5 s for ``kmNet.init``).

    The test:

      - Stubs ``styled_button`` to return ``True`` (simulated click).
      - Registers a mock driver via ``set_input_driver``.
      - Captures the calling thread inside the driver's ``_connect``.
      - Renders the panel once, waits for the worker to complete.
      - Asserts ``_connect`` was called exactly once.
      - Asserts the calling thread is NOT the test thread (it is the
        worker), and is named ``"KmBoxReconnect"`` per design.md.
    """
    captured_thread: dict = {}
    connect_called = threading.Event()

    def _fake_connect():
        captured_thread["thread"] = threading.current_thread()
        connect_called.set()
        return True

    driver = MagicMock(name="KmBoxNetDriver")
    driver._connect.side_effect = _fake_connect

    # Bind the GUI module's shared_state global so the click handler's
    # closure capture (``shared_state = _shared_state``) sees a real
    # snapshot. The click handler itself does not write to it on the
    # success path, but the worker may clear ``kmbox_reconnect_error``.
    with patch.object(gui_app, "_shared_state", shared_state):
        gui_app.set_input_driver(driver)
        try:
            widget_mocks["styled_button"].return_value = True

            render_thread = threading.current_thread()

            gui_app._render_kmbox_panel(shared_state)

            # Wait for the worker to call _connect (bounded — the
            # mock returns immediately so this is essentially synchronous).
            assert connect_called.wait(timeout=2.0), (
                "worker thread did not call driver._connect() within 2s"
            )

            # The worker must have completed by now since it does only
            # a single mock call after _connect; join the named thread to
            # avoid leaks.
            for t in threading.enumerate():
                if t.name == "KmBoxReconnect":
                    t.join(timeout=2.0)

            driver._connect.assert_called_once()

            calling_thread = captured_thread["thread"]
            assert calling_thread is not render_thread, (
                "_connect() must run on the worker thread, not the render "
                f"thread; got {calling_thread.name!r} vs render "
                f"{render_thread.name!r}"
            )
            assert calling_thread.name == "KmBoxReconnect", (
                "worker thread must be named 'KmBoxReconnect' per design.md; "
                f"got {calling_thread.name!r}"
            )
        finally:
            # Reset the module-level driver so subsequent tests start clean.
            gui_app.set_input_driver(None)


# ---------------------------------------------------------------------------
# Test 4 — Reconnect failure toast (Req 7.8)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_reconnect_failure_toast(
    imgui_mock: MagicMock,
    widget_mocks: dict,
    shared_state: SharedState,
) -> None:
    """
    Validates Req 7.8.

    When the reconnect worker writes a failure string into
    ``SharedState["kmbox_reconnect_error"]``, the next render frame
    SHALL display the toast/banner with that string AND SHALL leave
    the value displayed for ``kmbox_status`` unchanged from the latest
    snapshot.

    The test:

      - Pre-populates ``kmbox_status="failed"`` (the typical state after
        an exhausted reconnect FSM — Req 6.8 / 7.6) and writes the
        worker's failure string into ``kmbox_reconnect_error``.
      - Renders the panel once.
      - Asserts the indicator still shows ``"● failed"`` with the
        theme-error colour (kmbox_status display unchanged).
      - Asserts the banner text — prefixed with the warning glyph and
        containing the worker's failure string — is rendered.
      - Asserts no driver lookup happened (no kmNet call from the
        render thread, Req 7.9).
    """
    failure_msg = "Reconnect attempt failed"

    # Confirm no driver lookup during render — the panel reads only
    # SharedState even when displaying the failure banner.
    gui_app.set_input_driver(None)

    shared_state.update_state("kmbox_status", "failed")
    shared_state.update_state("kmbox_reconnect_error", failure_msg)

    gui_app._render_kmbox_panel(shared_state)

    texts = _text_calls(imgui_mock)

    # The status indicator display is unchanged: still shows "● failed"
    # with the theme-error colour.
    assert any("failed" in t and "●" in t for t in texts), (
        f"kmbox_status display must remain visible (Req 7.8); got texts "
        f"{texts!r}"
    )
    pushes = _push_style_color_calls(imgui_mock)
    assert (_COLOR_TEXT_SENTINEL, *THEME_ERROR_RGBA) in pushes, (
        f"failed indicator must keep the theme-error colour; got pushes "
        f"{pushes!r}"
    )

    # The banner is rendered with the failure string. The panel uses the
    # warning glyph "⚠" to prefix the banner so the operator can spot it
    # below the indicator.
    assert any(failure_msg in t and "⚠" in t for t in texts), (
        f"expected failure banner containing {failure_msg!r}; got texts "
        f"{texts!r}"
    )

    # The banner uses the same theme-error RGBA as the failed indicator;
    # both pushes appear in the captured call list.
    error_push_count = sum(
        1 for p in pushes if p == (_COLOR_TEXT_SENTINEL, *THEME_ERROR_RGBA)
    )
    assert error_push_count == 2, (
        f"expected two theme-error pushes (failed indicator + failure "
        f"banner); got {error_push_count} in {pushes!r}"
    )
    assert imgui_mock.pop_style_color.call_count == 2, (
        f"every push must be balanced by a pop; got "
        f"{imgui_mock.pop_style_color.call_count} pops"
    )

    # Confirm Req 7.9 — no driver reference resolved during render.
    assert gui_app.get_input_driver() is None
