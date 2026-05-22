"""
xxtea_accel — ctypes wrapper for the native C XXTEA implementation.

Provides a drop-in accelerated ``encrypt`` / ``decrypt`` that the
``PacketEncryptor`` in ``kmbox_net_driver.py`` can use transparently.

Usage (from PacketEncryptor):
    from .xxtea_accel import native_xxtea_encrypt
    if native_xxtea_encrypt is not None:
        # Use the C-accelerated path
        ...

If the DLL is not found or fails to load, ``native_xxtea_encrypt`` and
``native_xxtea_decrypt`` are set to ``None`` and the pure-Python fallback
in PacketEncryptor.encrypt/decrypt remains active.
"""

from __future__ import annotations

import ctypes
import logging
import os
import struct
import sys
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# ─── DLL resolution ────────────────────────────────────────────────────
# Search order:
#   1. Same directory as this .py file  (input/xxtea_native.dll)
#   2. Project root                     (xxtea_native.dll)
#   3. System PATH

_LIB: Optional[ctypes.CDLL] = None
_SEARCH_NAMES = ("xxtea_native.dll", "xxtea_native.so", "libxxtea_native.so")

def _find_and_load() -> Optional[ctypes.CDLL]:
    """Attempt to load the native XXTEA shared library."""
    this_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(this_dir)

    search_dirs = [this_dir, project_root]

    for d in search_dirs:
        for name in _SEARCH_NAMES:
            path = os.path.join(d, name)
            if os.path.isfile(path):
                try:
                    lib = ctypes.CDLL(path)
                    logger.info("xxtea_accel: loaded native library from %s", path)
                    return lib
                except OSError as e:
                    logger.warning("xxtea_accel: found %s but failed to load: %s", path, e)

    # Last resort: try bare name (relies on system PATH / LD_LIBRARY_PATH)
    for name in _SEARCH_NAMES:
        try:
            lib = ctypes.CDLL(name)
            logger.info("xxtea_accel: loaded native library %s from system PATH", name)
            return lib
        except OSError:
            pass

    return None


_LIB = _find_and_load()


# ─── Function binding ──────────────────────────────────────────────────

# Type aliases for ctypes
_uint32_array_32 = ctypes.c_uint32 * 32   # v[32]
_uint32_array_4  = ctypes.c_uint32 * 4    # k[4]

native_xxtea_encrypt: Optional[Callable[[bytes, list], bytes]] = None
native_xxtea_decrypt: Optional[Callable[[bytes, list], bytes]] = None


def _bind_functions(lib: ctypes.CDLL) -> bool:
    """Bind and type-check the C exports."""
    try:
        # void xxtea_encrypt(uint32_t *v, int n, const uint32_t *k)
        lib.xxtea_encrypt.argtypes = [
            ctypes.POINTER(ctypes.c_uint32),  # v
            ctypes.c_int,                      # n
            ctypes.POINTER(ctypes.c_uint32),  # k
        ]
        lib.xxtea_encrypt.restype = None

        # void xxtea_decrypt(uint32_t *v, int n, const uint32_t *k)
        lib.xxtea_decrypt.argtypes = [
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        lib.xxtea_decrypt.restype = None
        return True
    except AttributeError as e:
        logger.warning("xxtea_accel: DLL missing expected exports: %s", e)
        return False


def _make_encrypt(lib: ctypes.CDLL):
    """Return a Python-callable encrypt(block_128bytes, key_4words) -> bytes."""

    def encrypt(block: bytes, key_words: list) -> bytes:
        """Encrypt a 128-byte block with a 4-word key using native C XXTEA.

        Args:
            block: Exactly 128 bytes (padded/normalized by caller).
            key_words: List of 4 uint32 key words.

        Returns:
            128 bytes of ciphertext.
        """
        # Unpack block into 32 uint32 words
        v = _uint32_array_32(*struct.unpack("<32I", block))
        k = _uint32_array_4(*key_words)

        lib.xxtea_encrypt(v, 32, k)

        return struct.pack("<32I", *v)

    return encrypt


def _make_decrypt(lib: ctypes.CDLL):
    """Return a Python-callable decrypt(block_128bytes, key_4words) -> bytes."""

    def decrypt(block: bytes, key_words: list) -> bytes:
        """Decrypt a 128-byte block with a 4-word key using native C XXTEA.

        Args:
            block: Exactly 128 bytes of ciphertext.
            key_words: List of 4 uint32 key words.

        Returns:
            128 bytes of plaintext.
        """
        v = _uint32_array_32(*struct.unpack("<32I", block))
        k = _uint32_array_4(*key_words)

        lib.xxtea_decrypt(v, 32, k)

        return struct.pack("<32I", *v)

    return decrypt


if _LIB is not None and _bind_functions(_LIB):
    native_xxtea_encrypt = _make_encrypt(_LIB)
    native_xxtea_decrypt = _make_decrypt(_LIB)
    logger.info("xxtea_accel: native encrypt/decrypt bound successfully")
else:
    logger.info(
        "xxtea_accel: native library not available; "
        "PacketEncryptor will use pure-Python fallback"
    )


__all__ = ["native_xxtea_encrypt", "native_xxtea_decrypt"]
