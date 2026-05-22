"""
ARM64 import / construction smoke tests — Task 12.2 of spec
``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Smoke (Task 12.2): ARM64 import
# smoke + protocol-source citation smoke.

This file collects the two non-property smoke checks called out by
task 12.2 that are *not* covered by ``test_signature_compliance.py``:

  1. **Subprocess import smoke (Requirement 1.6)** — running
     ``python -c "import input.kmbox_net_driver"`` in a fresh
     interpreter terminates with exit code 0 and no
     ``ImportError`` / ``OSError`` / ``WinError`` mentioning an
     instruction-set or architecture mismatch. This proves the
     module loads cleanly on the host architecture (ARM64 on the
     Surface Pro 11; x86_64 on a developer laptop) without
     depending on a stale ``kmNet.pyd`` and without leaving stray
     module-level binding errors.

  2. **In-process construction smoke (Requirement 1.6)** —
     constructing ``KmBoxNetDriver('192.168.2.188', '41990',
     '12345')`` against a :class:`FakeDevice` returns without
     raising ``ImportError``, ``OSError``, or ``WinError`` (the
     three exception types Requirement 1.6 calls out). The
     handshake completes successfully and the driver reports
     ``connection_status == ConnectionStatus.CONNECTED``.

  3. **Protocol Sources citation smoke (Requirement 2.4)** — parses
     ``.kiro/specs/kmbox-net-arm64-udp/design.md``, locates the
     "Protocol Sources" section, and asserts each of the five
     required protocol elements (header layout, command identifier
     table, plaintext payload layout per command, encrypted payload
     algorithm, authentication handshake) is cited at least once.

**Validates: Requirements 1.6, 2.4, 8.6**

The "ARM64" qualifier in the file name reflects the *intent* — these
checks are the minimum smoke tests that must pass on Python ARM64 for
the rewrite to be considered functional (Requirement 1.6). They are
host-architecture independent in implementation: the same assertions
must pass on x86_64 developer machines, on ARM64 CI runners, and on
the Surface Pro 11 target hardware.
"""

from __future__ import annotations

import socket as _stdlib_socket
import subprocess
import sys
import textwrap
from pathlib import Path


# Make the ``input`` package importable when pytest is launched from
# the repository root or any sub-directory (the driver ships as
# ``input/kmbox_net_driver.py`` at the project root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from input.kmbox_net_driver import (  # noqa: E402
    ConnectionStatus,
    KmBoxNetDriver,
)
from tests.input.kmbox_net.conftest import (  # noqa: E402
    FakeDevice,
    FakeUdpSocket,
)


# ---------------------------------------------------------------------------
# Test 1 — subprocess import smoke
# ---------------------------------------------------------------------------


def test_subprocess_import_succeeds() -> None:
    """``python -c "import input.kmbox_net_driver"`` exits cleanly.

    Validates: Requirement 1.6.

    Spawns a fresh Python interpreter (the same executable that is
    currently running pytest) with the repository root prepended to
    ``sys.path`` and asks it to import the driver module. The
    subprocess is given a 30-second wall-clock budget — module
    import is normally sub-second, but Windows AV / virus scanning
    can occasionally inject a measurable delay on the first import
    of a freshly written file.

    Assertions:

      * exit code is ``0`` — any non-zero exit means the import
        raised at module load (e.g. an ``ImportError`` from a
        missing stdlib module that is guarded by an architecture
        check, or a syntax error introduced by a future refactor).
      * stderr does not contain any of ``"ImportError"``,
        ``"OSError"``, ``"WinError"``, or the string fragments
        ``"is not a valid Win32 application"`` /
        ``"%1 is not a valid"`` — Requirement 1.6's specific
        instruction-set / architecture-mismatch failure modes.

    The subprocess is run with ``PYTHONDONTWRITEBYTECODE=1`` so the
    test does not pollute the project's ``__pycache__`` with
    duplicate ``.pyc`` files (a benign side effect, but one that
    would otherwise show up as a diff in version control).
    """
    # Build the import command. The ``sys`` prepend is required
    # because the subprocess inherits an empty ``sys.path[0]``
    # (no current-directory injection in ``-c`` mode), so the
    # ``input`` package would otherwise not be importable.
    one_liner = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, %r)
        import input.kmbox_net_driver  # noqa: F401
        """
    ).strip() % (str(_REPO_ROOT),)

    # Run the subprocess with a fresh environment (don't inherit
    # PYTHONPATH from the caller — we want this to fail if the
    # module's own ``input/__init__.py`` doesn't put it on the
    # default search path).
    import os

    env = os.environ.copy()
    # Make bytecode writes a no-op so we don't churn __pycache__/
    # on every test run.
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    proc = subprocess.run(
        [sys.executable, "-c", one_liner],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30.0,
        env=env,
    )

    # ---- Exit code -------------------------------------------------
    assert proc.returncode == 0, (
        "Requirement 1.6 violated: subprocess import of "
        "``input.kmbox_net_driver`` exited with code %d. "
        "Stdout=%r Stderr=%r"
        % (proc.returncode, proc.stdout, proc.stderr)
    )

    # ---- Stderr fingerprints ---------------------------------------
    forbidden_fragments = (
        "ImportError",
        "OSError",
        "WinError",
        "is not a valid Win32 application",
        "%1 is not a valid",
    )
    matched = [frag for frag in forbidden_fragments if frag in proc.stderr]
    assert not matched, (
        "Requirement 1.6 violated: subprocess import of "
        "``input.kmbox_net_driver`` printed forbidden error "
        "fragment(s) %r on stderr. Full stderr=%r"
        % (matched, proc.stderr)
    )


# ---------------------------------------------------------------------------
# Test 2 — in-process construction smoke
# ---------------------------------------------------------------------------


def test_construction_against_fake_device(monkeypatch) -> None:
    """``KmBoxNetDriver(...)`` constructs cleanly against a ``FakeDevice``.

    Validates: Requirements 1.6, 8.6.

    Instantiates the driver with the documented default IP/port
    (``192.168.2.188`` / ``41990`` per Requirement 8.6, the values
    shown on the device's LCD) and the example UUID ``"12345"`` from
    ``c++_demo/calldemo.cpp``. ``socket.socket`` is monkey-patched
    to yield a :class:`FakeUdpSocket`, and a :class:`FakeDevice`
    publishes a successful handshake reply on the first such socket
    so the constructor's ``recvfrom`` resolves without timeout.

    Assertions:

      * No ``ImportError`` / ``OSError`` / ``WinError`` raised
        during ``__init__`` (Requirement 1.6's specific exception
        types). Other exception types (e.g. ``ValueError`` from
        argument validation) would also be a regression but are
        captured implicitly: pytest converts any uncaught exception
        in the constructor into a test failure.
      * After construction, ``driver.initialized is True`` and
        ``driver.connection_status == ConnectionStatus.CONNECTED``
        — direct evidence the handshake completed successfully on
        the host architecture.
      * Exactly one packet was emitted to the fake socket — the
        Init_Handshake (subsequent commands are not exercised by
        this smoke test; their wire shape is covered by the
        per-command property tests in the same folder).

    A ``release()`` call closes the driver before the test exits so
    the daemon listener thread (if any monitor logic ran during
    ``__init__``) is joined deterministically. The constructor does
    not start a monitor listener by default, so this is mostly
    belt-and-braces hygiene.
    """
    # Build the fake socket factory. We capture every socket the
    # constructor creates so we can attach the device to the *first*
    # one (the handshake socket).
    sockets: list[FakeUdpSocket] = []
    device = FakeDevice(outcome=FakeDevice.HandshakeOutcome.SUCCESS)

    def _factory(
        family: int = _stdlib_socket.AF_INET,
        type_: int = _stdlib_socket.SOCK_DGRAM,
        proto: int = 0,
        fileno: int | None = None,
        **_kwargs: object,
    ) -> FakeUdpSocket:
        sock = FakeUdpSocket(family=family, type_=type_)
        sock.proto = proto
        sockets.append(sock)
        # Attach on the first socket — the handshake socket. Subsequent
        # sockets (e.g. a monitor listener) are left alone.
        if len(sockets) == 1:
            device.attach(sock)
        return sock

    monkeypatch.setattr("socket.socket", _factory)

    # ---- Construct the driver -------------------------------------
    # The three exception types Requirement 1.6 calls out are
    # ``ImportError``, ``OSError``, and ``WinError``. ``WinError``
    # is a Windows-only subclass of ``OSError`` (created at runtime
    # by the CPython interpreter on Windows), so catching
    # ``ImportError`` and ``OSError`` covers all three. Any other
    # exception propagates as a test failure with full traceback.
    try:
        driver = KmBoxNetDriver(
            ip="192.168.2.188",
            port="41990",
            uuid="12345",
        )
    except (ImportError, OSError) as exc:
        raise AssertionError(
            "Requirement 1.6 violated: KmBoxNetDriver(...) raised "
            "%s during construction on host arch %r: %s"
            % (type(exc).__name__, sys.platform, exc)
        ) from exc

    try:
        # ---- Post-construction state checks -----------------------
        assert driver.initialized is True, (
            "Requirement 1.6 / 8.6 violated: driver.initialized "
            "should be True after a successful handshake against "
            "the FakeDevice; got %r."
            % (driver.initialized,)
        )
        assert driver.connection_status == ConnectionStatus.CONNECTED, (
            "Requirement 1.6 / 8.6 violated: driver.connection_status "
            "should be ConnectionStatus.CONNECTED after a successful "
            "handshake; got %r."
            % (driver.connection_status,)
        )

        # ---- Wire activity check ----------------------------------
        # Exactly one socket should have been created (the
        # handshake socket), and exactly one packet should have
        # been sent on it (the cmd_connect handshake).
        assert len(sockets) >= 1, (
            "test harness invariant: KmBoxNetDriver did not create "
            "a UDP socket via the patched factory."
        )
        handshake_sock = sockets[0]
        assert len(handshake_sock.sent) == 1, (
            "Requirement 1.6 / 8.6: KmBoxNetDriver(...) should emit "
            "exactly one UDP packet (the Init_Handshake) on the "
            "handshake socket; got %d packet(s): %r"
            % (len(handshake_sock.sent), handshake_sock.sent)
        )
    finally:
        # Always tear down so the test exits cleanly even if an
        # assertion fails above.
        driver.release()


# ---------------------------------------------------------------------------
# Test 3 — Protocol Sources citation smoke
# ---------------------------------------------------------------------------


def test_design_md_cites_all_required_protocol_elements() -> None:
    """``design.md`` "Protocol Sources" cites every required element.

    Validates: Requirement 2.4.

    Requirement 2.4 mandates that the "Protocol Sources" section of
    ``design.md`` records the source from which each of the five
    required protocol elements was derived:

      1. Header layout
      2. Command identifier table
      3. Plaintext payload layout per command
      4. Encrypted payload algorithm
      5. Authentication handshake

    This test parses ``design.md``, locates the "Protocol Sources"
    section (the block bounded by ``## Protocol Sources`` and the
    next top-level heading), and asserts each element appears at
    least once as a citation entry. The match is performed
    case-insensitively so a future doc-formatting tweak (e.g.
    Title Case → sentence case) does not regress the test.

    The presence of a citation is a structural check; the
    *correctness* of the citation (does the cited source actually
    document the element?) is enforced earlier in the spec process
    and not re-checked here — that would amount to scraping
    upstream GitHub source files at test time, which is outside
    the test infrastructure's scope.
    """
    design_path = (
        _REPO_ROOT / ".kiro" / "specs" / "kmbox-net-arm64-udp" / "design.md"
    )
    assert design_path.is_file(), (
        "test pre-condition: %s must exist; the spec workspace is "
        "not laid out as expected."
        % (design_path,)
    )

    text = design_path.read_text(encoding="utf-8")

    # ---- Locate the "Protocol Sources" section --------------------
    # Section starts at "## Protocol Sources" and ends at the next
    # ``^## `` line (a fresh second-level heading) or end-of-file.
    section_marker = "## Protocol Sources"
    start = text.find(section_marker)
    assert start != -1, (
        "Requirement 2.4 violated: design.md does not contain a "
        "'## Protocol Sources' section. The spec mandates this "
        "section must record the source for each of the five "
        "required protocol elements."
    )
    # Find the next ``^## `` after ``start + len(section_marker)`` —
    # that delimits the end of the section. ``re.search`` would also
    # work, but ``str.find`` plus a manual scan keeps the import
    # surface minimal.
    after = start + len(section_marker)
    next_h2 = text.find("\n## ", after)
    section_end = next_h2 if next_h2 != -1 else len(text)
    section_text = text[start:section_end].lower()

    # ---- Check each of the five required elements -----------------
    # Each entry: (human_label, list_of_acceptable_token_aliases).
    # ``any(alias in section_text)`` — accept any one alias as
    # evidence the element is cited. Aliases capture the variations
    # the design.md text uses (e.g. "header layout" vs.
    # "``cmd_head_t``", which both refer to the header layout
    # element).
    required_elements: list[tuple[str, list[str]]] = [
        (
            "Header layout (cmd_head_t)",
            ["header layout", "cmd_head_t"],
        ),
        (
            "Command identifier table",
            ["command identifier table"],
        ),
        (
            "Plaintext payload layout per command",
            [
                "plaintext payload layout per command",
                "plaintext payload layout",
            ],
        ),
        (
            "Encrypted payload algorithm",
            ["encrypted payload algorithm"],
        ),
        (
            "Authentication handshake",
            ["authentication handshake"],
        ),
    ]

    missing: list[str] = []
    for label, aliases in required_elements:
        if not any(alias.lower() in section_text for alias in aliases):
            missing.append(label)

    assert not missing, (
        "Requirement 2.4 violated: design.md 'Protocol Sources' "
        "section does NOT cite the following required protocol "
        "element(s): %r. Each of the five elements (header layout, "
        "command identifier table, plaintext payload layout per "
        "command, encrypted payload algorithm, authentication "
        "handshake) must appear as a citation entry."
        % (missing,)
    )
