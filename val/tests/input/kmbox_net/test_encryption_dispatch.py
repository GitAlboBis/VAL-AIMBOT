"""
Property test — Task 10.2 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 15: Encryption flag selects
#   construction in exactly one place (wire half).

**Property 15: Encryption flag selects construction in exactly one place**

    *For each* command in
    ``{move, left, right, middle, wheel, mouse, move_auto, move_beizer,
       keydown, keyup, monitor, reboot, setconfig, mask_mouse_left,
       unmask_all}``
    and *for each* tuple of valid arguments ``args(c)``:

      * when ``use_encryption == True`` the UDP packet bytes emitted
        for ``c(args)`` are NOT byte-equal to the plaintext layout
        produced by :class:`PacketBuilder` for the same ``(c, args)`` —
        in particular the emitted packet is exactly
        :data:`PacketEncryptor.BLOCK_SIZE_BYTES` (128 bytes) per the
        upstream ``sendto`` length contract, while every plaintext
        layout for these commands is shorter (16 / 18 / 28 / 72 bytes
        depending on the class), so the length itself proves the
        plaintext bytes were transformed;
      * when ``use_encryption == False`` the emitted bytes ARE
        byte-equal to the plaintext layout — they have the documented
        plaintext length per command-class
        (mouse-class = 72, keyboard-class = 28, header-only =
        16, ``setconfig`` = 18) and never coincide with the 128-byte
        encrypted block size.

**Validates: Requirements 9.1, 9.2, 9.4**

The companion AST scan in ``test_static.py`` (Task 10.2 second half)
asserts the structural invariant that ``self.use_encryption`` is read
in *exactly one* :class:`ast.FunctionDef` named ``_dispatch_call`` —
together the two tests pin the build-path selector both behaviourally
(this file) and structurally (``test_static.py``).

Implementation notes
--------------------

The test instantiates a real :class:`KmBoxNetDriver` so the
constructor exercises the full Init_Handshake send + recv path against
a :class:`FakeUdpSocket` and a :class:`FakeDevice` configured for a
successful reply (the handshake itself is plaintext per Requirement
9.6, so it never affects the encryption-flag arm under test). After
the handshake, every command method on the driver is invoked once
under each value of ``use_encryption`` and the resulting wire bytes
are inspected.

Length-based proof
~~~~~~~~~~~~~~~~~~

The task brief calls out a *length-based proxy* for the byte-equality
assertion: the encrypted packet is always exactly 128 bytes, while
every plaintext layout for the 15 commands is one of {16, 18, 28, 72}.
Since 128 ∉ {16, 18, 28, 72}, length alone is sufficient to prove

  * with ``use_encryption=True``  →  ``len(emitted) == 128``  ⇒
    ``emitted != plaintext`` (because every plaintext layout is
    shorter);
  * with ``use_encryption=False`` →  ``len(emitted) == L_c`` (the
    documented plaintext length for command ``c``)  ⇒  the emitted
    bytes follow the plaintext layout (they cannot coincide with the
    128-byte encrypted block).

The plaintext-arm test goes further: it also asserts that the emitted
bytes are *byte-equal* to a reference plaintext packet built directly
from the driver's :class:`PacketBuilder`. To make that comparison
deterministic in the face of randomized ``head.rand`` (for the
mouse / wheel / button / keyboard / reboot commands) and randomized
``head.indexpts``, the test:

  1. Resets the driver's ``PacketBuilder`` state so the next build
     produces a known ``head.indexpts == 1``;
  2. Re-seeds the builder's ``_rand_source`` with a fixed
     ``random.Random(0)`` instance so ``_random_rand()`` is
     reproducible;
  3. Builds a reference plaintext packet through the same
     :class:`PacketBuilder` API the driver uses;
  4. Then re-resets state and re-seeds before invoking the driver
     command, so the driver sends the *same* plaintext bytes to the
     wire.

For commands whose ``head.rand`` is deterministic
(``move_auto`` / ``move_beizer`` use ``ms``; ``monitor`` uses the port
encoding; ``setconfig`` uses ``inet_aton(ip)``; ``mask_mouse_left``
uses the ``mask_flag``; ``unmask_all`` uses ``0``; ``connect`` uses
``0``) the seeding is unnecessary but harmless — the byte-equality
assertion holds regardless.

For the encrypted arm we don't need byte-equality against a reference
ciphertext (the cipher is a one-way derivation under a fixed key); the
length-128 + ``not_equal_to_any_plaintext_layout`` checks are
sufficient and avoid coupling the test to the encryption transform's
internals.

Why no Hypothesis here
~~~~~~~~~~~~~~~~~~~~~~

This test is parameterised over a fixed *enumeration* of 15 commands —
a Hypothesis ``@given`` would generate one command per example and add
no real coverage over a deterministic loop. Each command is exercised
with one canonical valid argument tuple per the per-command range
contracts (``Requirement 4.x`` / ``5.x`` / ``6.x`` / ``7.x``); the
property's structural claim ("encryption flag determines wire bytes")
holds independent of *which* valid argument tuple is chosen, so a
single representative tuple per command is sufficient.
"""

from __future__ import annotations

import random
import socket as _stdlib_socket
import struct
import sys
from pathlib import Path
from typing import Callable, Dict, List, Tuple

# Make the ``input`` package importable when pytest is launched from
# the repository root or any sub-directory (the driver ships as
# ``input/kmbox_net_driver.py`` at the project root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402

from input.kmbox_net_driver import (  # noqa: E402
    CMD_HEAD_SIZE,
    ConnectionStatus,
    KmBoxNetDriver,
    PacketBuilder,
    PacketEncryptor,
    SOFT_KEYBOARD_SIZE,
    SOFT_MOUSE_SIZE,
)
from tests.input.kmbox_net.conftest import (  # noqa: E402
    FakeDevice,
    FakeUdpSocket,
)


# ---------------------------------------------------------------------------
# Plaintext lengths per command class (design.md "Per-command payload encoding")
# ---------------------------------------------------------------------------

# Mouse-class commands: 16-byte header + 56-byte ``soft_mouse_t`` payload.
_MOUSE_LEN = CMD_HEAD_SIZE + SOFT_MOUSE_SIZE  # 72
# Keyboard-class commands: 16-byte header + 12-byte ``soft_keyboard_t``.
_KEYBOARD_LEN = CMD_HEAD_SIZE + SOFT_KEYBOARD_SIZE  # 28
# Header-only commands.
_HEADER_ONLY_LEN = CMD_HEAD_SIZE  # 16
# ``setconfig`` carries a 2-byte big-endian port payload after the header.
_SETCONFIG_LEN = CMD_HEAD_SIZE + 2  # 18

# Encrypted block size (the upstream ``sendto`` length contract for
# every ``kmNet_enc_*`` function in ``c++_demo/NetConfig/kmboxNet.cpp``).
_ENCRYPTED_LEN = PacketEncryptor.BLOCK_SIZE_BYTES  # 128

# Sanity invariant: the four plaintext lengths must all differ from
# the encrypted length, which is the property's correctness guarantee
# under the length-based proxy.
assert _ENCRYPTED_LEN not in {
    _MOUSE_LEN,
    _KEYBOARD_LEN,
    _HEADER_ONLY_LEN,
    _SETCONFIG_LEN,
}, (
    "Property 15 length-based proxy depends on the encrypted block "
    "size (128) differing from every plaintext layout length; the "
    "test's correctness assumption has been violated."
)


# ---------------------------------------------------------------------------
# Per-command harness — (call_method, expected_plaintext_length)
# ---------------------------------------------------------------------------
#
# Each entry below describes one command from the Property 15 set.
# The call is performed against a freshly-built driver in CONNECTED
# state; the expected plaintext length is the documented layout length
# from design.md "Per-command payload encoding".
#
# The argument tuples are deliberately *valid* per the per-command
# range contracts (Requirements 4.x / 5.x / 6.x / 7.x) so that no
# command-side validation rejects the call before it reaches
# ``_dispatch_call`` — Property 15 is about the dispatcher's
# encryption-arm choice, not about argument validation.
# ---------------------------------------------------------------------------


# A "command spec" maps a logical command name to (caller, plain_len).
# ``caller`` takes the driver and invokes the matching command method
# with one canonical valid argument tuple.
CommandCaller = Callable[[KmBoxNetDriver], None]

_COMMAND_SPECS: Dict[str, Tuple[CommandCaller, int]] = {
    # ── mouse-class (72-byte plaintext) ─────────────────────────────
    "move":         (lambda d: d._move(7, -3),                _MOUSE_LEN),
    "left":         (lambda d: d._left(1),                    _MOUSE_LEN),
    "right":        (lambda d: d._right(1),                   _MOUSE_LEN),
    "middle":       (lambda d: d._middle(1),                  _MOUSE_LEN),
    "wheel":        (lambda d: d._wheel(3),                   _MOUSE_LEN),
    "mouse":        (lambda d: d._mouse(0x07, 5, -5, 1),      _MOUSE_LEN),
    "move_auto":    (lambda d: d._move_auto(10, -10, 50),     _MOUSE_LEN),
    "move_beizer":  (lambda d: d._move_beizer(
        20, -20, 100, 1, 2, 3, 4),                            _MOUSE_LEN),

    # ── keyboard-class (28-byte plaintext) ──────────────────────────
    # ``hid_code = 0x04`` ('a' on a standard HID keyboard) is a
    # non-modifier key so it occupies a slot in ``button[10]`` rather
    # than toggling a ``ctrl`` modifier bit; the matching ``keyup``
    # clears the same slot, leaving the ``KeyboardState`` unchanged
    # at the end of the test invocation (Requirement 5.4).
    "keydown":      (lambda d: d._keydown(0x04),              _KEYBOARD_LEN),
    "keyup":        (lambda d: d._keyup(0x04),                _KEYBOARD_LEN),

    # ── monitor (header-only 16-byte plaintext) ─────────────────────
    # ``port = 0`` selects the disable arm: the listener-spawn path
    # is skipped, so the test does not need to clean up a daemon
    # thread between iterations. ``head.rand`` is deterministic
    # (== 0) on this arm.
    "monitor":      (lambda d: d.monitor(0),                  _HEADER_ONLY_LEN),

    # ── reboot (header-only 16-byte plaintext) ──────────────────────
    # NB: the public ``reboot()`` method transitions
    # ``connection_status`` to ``DISCONNECTED`` after dispatch
    # (Requirement 7.7). To keep the harness uniform we restore the
    # status to ``CONNECTED`` after the call so the next iteration can
    # build its own driver from scratch — the per-iteration driver
    # construction makes this restoration unnecessary in practice, but
    # documenting the post-effect here makes the test self-explanatory.
    "reboot":       (lambda d: d.reboot(),                    _HEADER_ONLY_LEN),

    # ── setconfig (18-byte plaintext) ───────────────────────────────
    "setconfig":    (lambda d: d.setconfig("192.168.2.99", 41999),
                                                              _SETCONFIG_LEN),

    # ── mask_mouse_left (header-only 16-byte plaintext) ─────────────
    "mask_mouse_left": (lambda d: d.mask_mouse_left(1),       _HEADER_ONLY_LEN),

    # ── unmask_all (header-only 16-byte plaintext) ──────────────────
    "unmask_all":   (lambda d: d.unmask_all(),                _HEADER_ONLY_LEN),
}

# Sanity check at import time so a typo in the spec table is caught
# eagerly rather than during test execution.
assert set(_COMMAND_SPECS) == {
    "move", "left", "right", "middle", "wheel", "mouse",
    "move_auto", "move_beizer", "keydown", "keyup",
    "monitor", "reboot", "setconfig",
    "mask_mouse_left", "unmask_all",
}, "Property 15 command set drifted from the task spec"


# ---------------------------------------------------------------------------
# Driver-construction harness
# ---------------------------------------------------------------------------


def _build_connected_driver(use_encryption: bool) -> Tuple[
    KmBoxNetDriver, FakeUdpSocket
]:
    """Construct a ``KmBoxNetDriver`` in the ``CONNECTED`` state.

    Patches ``socket.socket`` for the duration of the constructor so
    the driver creates a :class:`FakeUdpSocket` instead of a real one,
    and attaches a successful :class:`FakeDevice` so the handshake
    ``recvfrom`` resolves to a zero-result-code reply. The patch is
    reverted before the function returns: subsequent ``sendto`` calls
    issued by the test body run on the same fake socket the driver
    captured during construction (the driver holds a direct reference
    to it via ``self.udp_socket._sock``), so reverting the patch does
    not break the test — and it ensures any *new* sockets the test
    might inadvertently create reach the real ``socket.socket`` (which
    would surface as a test failure if the driver tried to spawn a
    listener thread under the no-op ``monitor(0)`` arm).
    """
    sockets: List[FakeUdpSocket] = []
    device = FakeDevice(outcome=FakeDevice.HandshakeOutcome.SUCCESS)

    def _factory(family: int = _stdlib_socket.AF_INET,
                 type_: int = _stdlib_socket.SOCK_DGRAM,
                 proto: int = 0,
                 fileno: int | None = None,
                 **_kwargs) -> FakeUdpSocket:
        sock = FakeUdpSocket(family=family, type_=type_)
        sock.proto = proto
        sockets.append(sock)
        if len(sockets) == 1:
            device.attach(sock)
        return sock

    original = _stdlib_socket.socket
    _stdlib_socket.socket = _factory  # type: ignore[assignment]
    try:
        driver = KmBoxNetDriver(
            ip="192.168.2.188",
            port="41990",
            uuid="01FBC068",
            use_encryption=use_encryption,
        )
    finally:
        _stdlib_socket.socket = original  # type: ignore[assignment]

    if not sockets:
        raise RuntimeError(
            "test harness invariant violated: KmBoxNetDriver did not "
            "construct any UDP socket"
        )
    return driver, sockets[0]


def _restore_state_for_replay(driver: KmBoxNetDriver) -> None:
    """Reset the driver's per-packet randomization so a build can be replayed.

    The driver's :class:`PacketBuilder` holds two pieces of per-instance
    state that influence the wire bytes:

      * ``_indexpts`` — the monotonic counter incremented before every
        send. We reset it to ``0`` so the next ``next_indexpts`` call
        returns ``1`` (the same value the handshake used).
      * ``_rand_source`` — the per-instance ``random.Random`` used by
        ``_random_rand()``. We re-seed it with a fixed seed so the
        next sequence of ``randrange`` calls is reproducible.

    Resetting these between two consecutive invocations lets the test
    build a *reference* plaintext packet via the same :class:`PacketBuilder`
    API the driver uses, then reset again and let the driver build the
    packet for real — and assert byte-equality. The reference build is
    bit-for-bit identical to what the driver would emit on the
    ``use_encryption=False`` arm.
    """
    builder = driver._packet_builder
    builder._indexpts = 0
    builder._rand_source = random.Random(0)


# ---------------------------------------------------------------------------
# Plaintext arm — bytes match the PacketBuilder reference layout
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cmd_name", sorted(_COMMAND_SPECS.keys()))
def test_plaintext_arm_bytes_equal_packet_builder_layout(cmd_name: str) -> None:
    """``use_encryption=False`` ⇒ wire bytes match :class:`PacketBuilder`.

    For each command the test:

      1. Builds a connected driver with ``use_encryption=False``.
      2. Resets the builder's ``_indexpts`` to 0 and re-seeds
         ``_rand_source`` with ``random.Random(0)``.
      3. Builds a *reference* plaintext packet via the same
         :class:`PacketBuilder` API the driver uses.
      4. Resets the builder state again so the driver's invocation
         produces an identical sequence of randomization values.
      5. Invokes the command method on the driver.
      6. Asserts the new packet on ``fake_sock.sent`` is byte-equal to
         the reference plaintext, and that its length matches the
         documented plaintext layout for the command's class
         (16 / 18 / 28 / 72 bytes).

    Validates: Requirements 9.1, 9.2, 9.4.
    """
    caller, expected_plaintext_len = _COMMAND_SPECS[cmd_name]

    driver, fake_sock = _build_connected_driver(use_encryption=False)
    try:
        # Pre-condition — the handshake succeeded and is the only
        # packet on the wire so far. Subsequent assertions reference
        # the index ``handshake_count`` for the command's emission.
        assert driver.connection_status == ConnectionStatus.CONNECTED, (
            "test pre-condition: handshake must succeed; got %r"
            % (driver.connection_status,)
        )
        assert driver.use_encryption is False
        handshake_count = len(fake_sock.sent)
        assert handshake_count == 1, (
            "test pre-condition: exactly one handshake packet should "
            "have been emitted before the command is invoked; got %d"
            % handshake_count
        )

        # ---- Build the reference plaintext via PacketBuilder ----
        # Reset state so the *next* build produces a deterministic
        # ``head.indexpts == 1`` and a reproducible ``_random_rand``
        # sequence. The reference build below mirrors what
        # ``_dispatch_call`` would route through ``PacketBuilder``
        # for the same logical command.
        _restore_state_for_replay(driver)
        reference_packet = _build_reference_plaintext(driver, cmd_name)
        # Sanity: the reference layout length must match the
        # per-command expectation; if this fails the test table is
        # out of sync with the driver.
        assert len(reference_packet) == expected_plaintext_len, (
            "test invariant: reference plaintext length for %r is %d, "
            "expected %d (documented in design.md "
            "'Per-command payload encoding')."
            % (cmd_name, len(reference_packet), expected_plaintext_len)
        )

        # Reset state again so the driver's next invocation produces
        # the *same* indexpts/rand sequence as the reference build.
        _restore_state_for_replay(driver)

        # ---- Invoke the command method on the driver ----
        # Some commands (notably ``mask_mouse_left`` / ``unmask_all``)
        # mutate ``PacketBuilder.mask_flag`` as part of building the
        # packet; that mutation is correctly reproduced by both the
        # reference build and the driver build because the resets
        # above leave ``mask_flag`` untouched and the logical command
        # carries the same state argument in both cases.
        caller(driver)

        # ---- Assert the wire bytes ----
        assert len(fake_sock.sent) == handshake_count + 1, (
            "Property 15 (plaintext arm, %r): expected exactly one "
            "additional UDP packet after the command call; got %d → %d."
            % (cmd_name, handshake_count, len(fake_sock.sent))
        )
        emitted_packet, _addr = fake_sock.sent[-1]

        # Length must equal the documented plaintext layout length —
        # NEVER 128 (the encrypted block size). This alone is a
        # length-based proxy for "byte-equal to plaintext" because
        # 128 ∉ {16, 18, 28, 72}.
        assert len(emitted_packet) == expected_plaintext_len, (
            "Property 15 (plaintext arm, %r): emitted packet length "
            "is %d, expected %d (the documented plaintext layout). "
            "A length of %d would indicate the encryption transform "
            "was applied despite use_encryption=False."
            % (
                cmd_name,
                len(emitted_packet),
                expected_plaintext_len,
                _ENCRYPTED_LEN,
            )
        )

        # Byte-equality against the reference plaintext build —
        # the strongest possible encoding of "byte-equal to the
        # plaintext layout produced by Packet_Builder for the same
        # ``(c, args)``" (Requirement 9.2).
        assert emitted_packet == reference_packet, (
            "Property 15 (plaintext arm, %r): emitted packet does not "
            "match the PacketBuilder reference layout byte-for-byte. "
            "Got %r; expected %r."
            % (cmd_name, emitted_packet, reference_packet)
        )
    finally:
        # Stop any spawned listener threads and close the socket so
        # parametrized iterations do not leak descriptors. ``release``
        # is idempotent and never raises.
        driver.release()


# ---------------------------------------------------------------------------
# Encrypted arm — bytes are NOT byte-equal to the plaintext layout
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cmd_name", sorted(_COMMAND_SPECS.keys()))
def test_encrypted_arm_bytes_differ_from_packet_builder_layout(
    cmd_name: str,
) -> None:
    """``use_encryption=True`` ⇒ wire bytes are NOT the plaintext layout.

    For each command the test:

      1. Builds a connected driver with ``use_encryption=True``.
      2. Invokes the command method on the driver.
      3. Asserts the new packet on ``fake_sock.sent`` has length
         exactly :data:`PacketEncryptor.BLOCK_SIZE_BYTES` (128) — the
         upstream ``sendto`` length contract for every encrypted
         command.
      4. Asserts the new packet length differs from every plaintext
         layout length in {16, 18, 28, 72}, which is the length-based
         proxy for "not byte-equal to the plaintext layout produced by
         Packet_Builder for the same ``(c, args)``" (Requirement 9.1).

    Stronger: the test additionally constructs a reference *plaintext*
    packet via :class:`PacketBuilder` (with the same RNG-replay
    discipline as the plaintext-arm test) and asserts the emitted
    bytes are not byte-equal to it — directly encoding Requirement 9.1
    rather than relying solely on the length proxy.

    Validates: Requirements 9.1, 9.2, 9.4.
    """
    caller, expected_plaintext_len = _COMMAND_SPECS[cmd_name]

    driver, fake_sock = _build_connected_driver(use_encryption=True)
    try:
        # Pre-condition — handshake succeeded and is the only packet
        # on the wire so far. The handshake itself is plaintext per
        # Requirement 9.6 even with use_encryption=True, so it is not
        # an encrypted packet — but it is also not the packet under
        # test (we look at fake_sock.sent[-1] after the command call).
        assert driver.connection_status == ConnectionStatus.CONNECTED, (
            "test pre-condition: handshake must succeed; got %r"
            % (driver.connection_status,)
        )
        assert driver.use_encryption is True
        handshake_count = len(fake_sock.sent)
        assert handshake_count == 1, (
            "test pre-condition: exactly one handshake packet should "
            "have been emitted before the command is invoked; got %d"
            % handshake_count
        )
        # The handshake itself is plaintext (Requirement 9.6) so its
        # length is exactly CMD_HEAD_SIZE — a quick smoke check that
        # the test harness didn't accidentally encrypt the handshake.
        assert len(fake_sock.sent[0][0]) == CMD_HEAD_SIZE, (
            "test pre-condition: handshake must be plaintext "
            "(length %d) per Requirement 9.6, even with "
            "use_encryption=True; got length %d."
            % (CMD_HEAD_SIZE, len(fake_sock.sent[0][0]))
        )

        # ---- Build a reference plaintext via PacketBuilder for the
        # byte-inequality check. The reset/replay discipline mirrors
        # the plaintext-arm test so that the reference build matches
        # what the driver *would have* sent in plaintext — i.e. the
        # bytes the encrypted-arm packet must NOT equal.
        _restore_state_for_replay(driver)
        reference_plaintext = _build_reference_plaintext(driver, cmd_name)
        assert len(reference_plaintext) == expected_plaintext_len, (
            "test invariant: reference plaintext length for %r is %d, "
            "expected %d." % (
                cmd_name, len(reference_plaintext), expected_plaintext_len
            )
        )
        _restore_state_for_replay(driver)

        # ---- Invoke the command method on the driver ----
        caller(driver)

        # ---- Assert the wire bytes ----
        assert len(fake_sock.sent) == handshake_count + 1, (
            "Property 15 (encrypted arm, %r): expected exactly one "
            "additional UDP packet after the command call; got %d → %d."
            % (cmd_name, handshake_count, len(fake_sock.sent))
        )
        emitted_packet, _addr = fake_sock.sent[-1]

        # Length must equal the encrypted block size. Any other
        # length is direct evidence that the encryption transform was
        # not applied despite use_encryption=True.
        assert len(emitted_packet) == _ENCRYPTED_LEN, (
            "Property 15 (encrypted arm, %r): emitted packet length "
            "is %d, expected %d (PacketEncryptor.BLOCK_SIZE_BYTES). "
            "A length of %d would indicate the encryption transform "
            "was bypassed despite use_encryption=True."
            % (
                cmd_name,
                len(emitted_packet),
                _ENCRYPTED_LEN,
                expected_plaintext_len,
            )
        )

        # Length-based proxy: the emitted length must differ from
        # every plaintext layout length, which encodes "not byte-equal
        # to the plaintext layout" via the pigeonhole principle (no
        # 128-byte buffer can equal a 16/18/28/72-byte buffer).
        assert len(emitted_packet) not in (
            _MOUSE_LEN, _KEYBOARD_LEN, _HEADER_ONLY_LEN, _SETCONFIG_LEN
        ), (
            "Property 15 (encrypted arm, %r): emitted packet length "
            "%d coincides with a plaintext layout length — "
            "Requirement 9.1 forbids byte-equality to the plaintext "
            "layout."
            % (cmd_name, len(emitted_packet))
        )

        # Byte-inequality against the reference plaintext build —
        # the direct encoding of Requirement 9.1.
        assert emitted_packet != reference_plaintext, (
            "Property 15 (encrypted arm, %r): emitted packet bytes "
            "are byte-equal to the PacketBuilder plaintext reference "
            "— Requirement 9.1 forbids that. Got %r."
            % (cmd_name, emitted_packet)
        )
    finally:
        driver.release()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_reference_plaintext(driver: KmBoxNetDriver, cmd_name: str) -> bytes:
    """Build a reference plaintext packet via the driver's :class:`PacketBuilder`.

    Mirrors the per-command branch in
    :meth:`KmBoxNetDriver._dispatch_call`. ``cmd_name`` selects which
    ``build_*`` method to invoke and which canonical argument tuple to
    pass — the same tuple used by the matching ``_COMMAND_SPECS``
    entry for the command, decoded back to the per-builder argument
    contract.

    The driver-side ``_dispatch_call`` translates the
    ``isdown ∈ {0, 1}`` flag passed to ``_left/_right/_middle`` into a
    bit-mask for ``soft_mouse_t.button``; this helper applies the same
    translation so the reference packet matches what the driver
    actually emits.

    For the keyboard-class commands, the reference build needs to
    inspect the driver's persistent ``KeyboardState``: ``_keydown``
    mutates the state via :func:`keyboard_apply_down` *before*
    dispatching, so the reference packet must reflect the
    *post-mutation* state. The helper applies the same mutation to a
    fresh copy of the state to compute the reference, then restores
    the driver's state to its pre-call value — so the driver's own
    ``_keydown`` invocation produces a packet bit-for-bit identical
    to the reference.
    """
    builder = driver._packet_builder

    if cmd_name == "move":
        return builder.build_move(builder.next_indexpts(), 7, -3)
    if cmd_name == "left":
        # ``isdown=1`` for ``_left`` translates to bit0 of the
        # ``soft_mouse_t.button`` field per ``_dispatch_call``.
        # ``build_button`` updates the sticky ``softmouse.button``
        # bitfield in place per upstream semantics.
        return builder.build_button(
            builder.next_indexpts(),
            _CMD_MOUSE_LEFT,
            0x01,
            1,
        )
    if cmd_name == "right":
        return builder.build_button(
            builder.next_indexpts(),
            _CMD_MOUSE_RIGHT,
            0x02,
            1,
        )
    if cmd_name == "middle":
        return builder.build_button(
            builder.next_indexpts(),
            _CMD_MOUSE_MIDDLE,
            0x04,
            1,
        )
    if cmd_name == "wheel":
        return builder.build_wheel(builder.next_indexpts(), 3)
    if cmd_name == "mouse":
        return builder.build_mouse_all(
            builder.next_indexpts(), 0x07, 5, -5, 1
        )
    if cmd_name == "move_auto":
        return builder.build_move_auto(builder.next_indexpts(), 10, -10, 50)
    if cmd_name == "move_beizer":
        return builder.build_move_beizer(
            builder.next_indexpts(), 20, -20, 100, 1, 2, 3, 4
        )
    if cmd_name == "keydown":
        # ``_keydown`` first mutates the persistent KeyboardState
        # then dispatches with the post-mutation (ctrl, keys). To
        # build the reference packet we must apply the same mutation
        # against a snapshot of the state *and* restore the original
        # state after the reference build — otherwise the driver's
        # subsequent ``_keydown`` call would observe a state that
        # already has the key pressed and produce a no-op (or worse,
        # a different packet).
        return _build_reference_keyboard(driver, hid_code=0x04, down=True)
    if cmd_name == "keyup":
        return _build_reference_keyboard(driver, hid_code=0x04, down=False)
    if cmd_name == "monitor":
        return builder.build_monitor(builder.next_indexpts(), 0)
    if cmd_name == "reboot":
        return builder.build_reboot(builder.next_indexpts())
    if cmd_name == "setconfig":
        return builder.build_setconfig(
            builder.next_indexpts(), "192.168.2.99", 41999
        )
    if cmd_name == "mask_mouse_left":
        return builder.build_mask_mouse_left(builder.next_indexpts(), 1)
    if cmd_name == "unmask_all":
        return builder.build_unmask_all(builder.next_indexpts())

    raise AssertionError(
        "test invariant: unknown command in reference build: %r" % cmd_name
    )


def _build_reference_keyboard(
    driver: KmBoxNetDriver, *, hid_code: int, down: bool
) -> bytes:
    """Reference build for ``_keydown`` / ``_keyup`` with state preservation.

    The driver's ``_keydown(hid_code)`` flow is:

        keyboard_apply_down(self._keyboard_state, hid_code)
        self._dispatch_call('keyboard',
                            self._keyboard_state.ctrl,
                            list(self._keyboard_state.keys))

    For the *reference* build we apply the same mutation, build the
    packet via :meth:`PacketBuilder.build_keyboard`, and then *undo*
    the mutation so the driver's own ``_keydown`` call (run after the
    state-replay reset) starts from the same baseline and produces
    bit-for-bit identical bytes.

    The undo is the inverse operation (``apply_up`` for the keydown
    case, ``apply_down`` for the keyup case). For a non-modifier HID
    code the inverse leaves the state byte-for-byte identical to its
    pre-mutation value (slot insertion + slot removal is a no-op when
    the same HID code is the only one in the buffer); for a modifier
    HID code the inverse toggles the same ``ctrl`` bit twice, also a
    no-op. The reference build is therefore safe regardless of the
    chosen HID code.
    """
    from input.kmbox_net_driver import (  # local import to keep top tidy
        KeyboardState,
        keyboard_apply_down,
        keyboard_apply_up,
    )

    builder = driver._packet_builder
    state = driver._keyboard_state

    # Snapshot the existing state for restoration — a defensive copy
    # so the reference build can mutate ``state`` without leaking
    # changes back to the driver.
    snapshot_ctrl = state.ctrl
    snapshot_keys = list(state.keys)

    if down:
        keyboard_apply_down(state, hid_code)
    else:
        keyboard_apply_up(state, hid_code)

    reference = builder.build_keyboard(
        builder.next_indexpts(), state.ctrl, list(state.keys)
    )

    # Restore the snapshot exactly so the driver's subsequent call
    # (in the test body) starts from the identical baseline.
    state.ctrl = snapshot_ctrl
    state.keys = list(snapshot_keys)

    return reference


# Local copies of the three button command identifiers used by
# ``_dispatch_call`` for the left/right/middle button arms. Imported
# at module scope below to keep the reference-build helper readable.
from input.kmbox_net_driver import (  # noqa: E402
    CMD_MOUSE_LEFT as _CMD_MOUSE_LEFT,
    CMD_MOUSE_MIDDLE as _CMD_MOUSE_MIDDLE,
    CMD_MOUSE_RIGHT as _CMD_MOUSE_RIGHT,
)
