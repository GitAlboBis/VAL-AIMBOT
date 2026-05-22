"""
Property test — Task 3.2 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 16: Encryption round-trip
#   identity.

**Property 16: Encryption round-trip identity**

    *For any* 128-byte plaintext block ``p`` and any 16-byte key derived
    from a 32-bit MAC value, the round-trip
    ``PacketEncryptor(mac).decrypt(PacketEncryptor(mac).encrypt(p))``
    SHALL return exactly the same bytes as ``p``.

**Validates: Requirements 9.3**

Implementation notes
--------------------

``PacketEncryptor`` is a direct port of the XXTEA-style transform from
``c++_demo/NetConfig/my_enc.cpp`` of https://github.com/kvmaibox/kmboxnet
(Protocol Sources entry 3 in design.md). The encrypted send length is a
fixed 128 bytes per ``c++_demo/NetConfig/kmboxNet.cpp`` (every
``kmNet_enc_*`` function calls
``sendto(..., (const char*)&tx_enc, 128, ...)``), which is also the
canonical block size of the cipher. Inputs of any length are normalized
to exactly 128 bytes before the transform — they are right-padded with
zero bytes if shorter and truncated if longer.

The 16-byte key is derived from the 32-bit device MAC: bytes 0..3 hold
the MAC in big-endian order (per ``kmboxNet.cpp:kmNet_init``) and
bytes 4..15 are zero. Generating the MAC as a Hypothesis 32-bit
unsigned integer therefore samples every distinct key the driver can
ever produce.

The property is constrained to the canonical 128-byte block per the
task brief — it is the only block size the wire layer ever passes
through ``encrypt`` / ``decrypt`` (see ``_dispatch_call`` in design.md
"Send-path sequence"). For inputs that already match the block size,
``_normalize`` is the identity, so the round-trip exactly recovers ``p``
without any padding-vs-truncation ambiguity.

This test does not import the driver class, the UDP socket, or any
other layer — ``PacketEncryptor`` is a pure-functional component that
only depends on ``struct`` from the stdlib, so the test stays focused
on the algebraic identity ``decrypt ∘ encrypt = id``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the ``input`` package importable when pytest is launched from the
# repository root or any sub-directory. The driver ships as
# ``input/kmbox_net_driver.py`` at the project root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hypothesis import given, settings
from hypothesis import strategies as st

from input.kmbox_net_driver import PacketEncryptor


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# 32-bit unsigned MAC value — the full input space of
# ``StrToHex(uuid[:8], 4)`` (see ``kmboxNet.cpp:kmNet_init``).
_st_mac = st.integers(min_value=0, max_value=2**32 - 1)

# 128-byte plaintext block — the canonical encrypted-packet length per
# ``c++_demo/NetConfig/kmboxNet.cpp``.
_st_block = st.binary(
    min_size=PacketEncryptor.BLOCK_SIZE_BYTES,
    max_size=PacketEncryptor.BLOCK_SIZE_BYTES,
)


# ---------------------------------------------------------------------------
# Property 16
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(mac=_st_mac, plaintext=_st_block)
def test_encryption_round_trip_identity(mac: int, plaintext: bytes) -> None:
    """``decrypt(encrypt(p)) == p`` for every 128-byte block and every MAC.

    Validates: Requirements 9.3.
    """
    encryptor = PacketEncryptor(mac)
    ciphertext = encryptor.encrypt(plaintext)

    # Encrypted output is always exactly 128 bytes per the upstream
    # ``sendto`` length contract.
    assert len(ciphertext) == PacketEncryptor.BLOCK_SIZE_BYTES

    recovered = encryptor.decrypt(ciphertext)
    assert recovered == plaintext
