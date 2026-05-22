"""
Build script for the native XXTEA accelerator DLL.

Usage:
    python build_xxtea.py

This uses Python's distutils/cffi to compile xxtea_native.c into a shared
library (DLL on Windows, .so on Linux) using whatever C compiler is
available on the system.

Works on:
  - Windows x64 (MSVC Build Tools)
  - Windows ARM64 (MSVC Build Tools for ARM64)
  - Linux (gcc/clang)
"""

import os
import sys
import subprocess
import shutil
import platform


def find_vcvarsall():
    """Find vcvarsall.bat for MSVC Build Tools."""
    candidates = [
        r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat",
        r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat",
        r"C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat",
        r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat",
        r"C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvarsall.bat",
        r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def build_msvc():
    """Build using MSVC cl.exe via vcvarsall.bat."""
    vcvarsall = find_vcvarsall()
    if vcvarsall is None:
        print("ERROR: vcvarsall.bat not found. Install Visual Studio Build Tools.")
        return False

    src = os.path.join("input", "xxtea_native.c")
    out_dll = os.path.join("input", "xxtea_native.dll")

    # Determine target architecture based on Python process, not OS
    # (Python x64 can run emulated on ARM64 Windows)
    if "ARM64" in sys.version:
        arch = "arm64"
    else:
        arch = "x64"

    # Build command: call vcvarsall.bat to set up environment, then compile
    cmd = (
        f'cmd /c ""{vcvarsall}" {arch} && '
        f'cl /LD /O2 /DNDEBUG "{src}" /Fe:"{out_dll}" /link /NOLOGO"'
    )

    print(f"Building for {arch}...")
    print(f"  Source: {src}")
    print(f"  Output: {out_dll}")
    print(f"  Command: {cmd}")

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"\n[OK] SUCCESS: {out_dll} built successfully!")
        # Clean up .obj and .lib files
        for ext in (".obj", ".lib", ".exp"):
            cleanup = os.path.join("input", f"xxtea_native{ext}")
            if os.path.exists(cleanup):
                os.remove(cleanup)
        return True
    else:
        print(f"\n[FAIL] FAILED (exit code {result.returncode})")
        if result.stdout:
            print("STDOUT:", result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        return False


def build_gcc():
    """Build using gcc or clang."""
    cc = shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if cc is None:
        print("ERROR: No C compiler found (gcc, clang, cc).")
        return False

    src = os.path.join("input", "xxtea_native.c")
    if sys.platform == "win32":
        out = os.path.join("input", "xxtea_native.dll")
        cmd = [cc, "-shared", "-O2", "-DNDEBUG", "-o", out, src]
    else:
        out = os.path.join("input", "libxxtea_native.so")
        cmd = [cc, "-shared", "-fPIC", "-O2", "-DNDEBUG", "-o", out, src]

    print(f"Building with {cc}...")
    print(f"  Source: {src}")
    print(f"  Output: {out}")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"\n[OK] SUCCESS: {out} built successfully!")
        return True
    else:
        print(f"\n[FAIL] FAILED (exit code {result.returncode})")
        if result.stdout:
            print("STDOUT:", result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        return False


def verify_dll():
    """Quick verification that the DLL loads and produces correct output."""
    print("\n--- Verification ---")
    try:
        # Add input/ to path so xxtea_accel can find the DLL
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "input"))
        from input.xxtea_accel import native_xxtea_encrypt, native_xxtea_decrypt

        if native_xxtea_encrypt is None:
            print("[WARN]  DLL loaded but functions not bound.")
            return False

        # Test: encrypt then decrypt should round-trip
        import struct
        test_data = bytes(range(128))  # 128 bytes of test data
        test_key = [0x12345678, 0, 0, 0]  # Simple test key

        encrypted = native_xxtea_encrypt(test_data, test_key)
        decrypted = native_xxtea_decrypt(encrypted, test_key)

        if decrypted == test_data:
            print("[OK] Round-trip test PASSED (encrypt -> decrypt = original)")
        else:
            print("[FAIL] Round-trip test FAILED!")
            return False

        # Benchmark
        import time
        iterations = 10000
        t0 = time.perf_counter()
        for _ in range(iterations):
            native_xxtea_encrypt(test_data, test_key)
        elapsed = time.perf_counter() - t0
        per_call_us = (elapsed / iterations) * 1_000_000

        print(f"[OK] Benchmark: {per_call_us:.1f} us per encrypt ({iterations} iterations)")
        print(f"   (Pure Python would be ~500 us = {500/per_call_us:.0f}x slower)")
        return True

    except Exception as e:
        print(f"[WARN]  Verification failed: {e}")
        return False


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print("=== XXTEA Native Accelerator Build ===")
    print(f"Platform: {platform.machine()} / {sys.platform}")
    print()

    success = False

    if sys.platform == "win32":
        # Try MSVC first, then gcc/clang
        success = build_msvc()
        if not success:
            print("\nMSVC failed, trying gcc/clang fallback...")
            success = build_gcc()
    else:
        success = build_gcc()

    if success:
        verify_dll()
    else:
        print("\n⚠️  Build failed. The project will still work using the pure-Python XXTEA fallback.")
        print("    To build manually, install Visual Studio Build Tools or gcc.")
