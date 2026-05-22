/*
 * xxtea_native.c — Native C acceleration for KmBox XXTEA packet encryption.
 *
 * Replaces the pure-Python PacketEncryptor.encrypt() hot path:
 *   Python: 6 rounds × 32 blocks × ~6 ops = ~192 bitwise ops → ~0.5ms
 *   C:      same logic compiled ARM64/x64 → ~0.005ms (100x faster)
 *
 * Build (MSVC, from Developer Command Prompt):
 *   cl /LD /O2 /DNDEBUG xxtea_native.c /Fe:xxtea_native.dll
 *
 * Build (clang-cl / ARM64):
 *   clang-cl /LD /O2 /DNDEBUG xxtea_native.c /Fe:xxtea_native.dll
 *
 * Build (GCC / MinGW cross-compile):
 *   gcc -shared -O2 -o xxtea_native.dll xxtea_native.c
 *
 * The DLL exports two functions:
 *   xxtea_encrypt(uint32_t *v, int n, const uint32_t *k)
 *   xxtea_decrypt(uint32_t *v, int n, const uint32_t *k)
 *
 * Both operate in-place on the v[] array (32 uint32 words = 128 bytes).
 */

#include <stdint.h>

#ifdef _MSC_VER
  #define EXPORT __declspec(dllexport)
#else
  #define EXPORT __attribute__((visibility("default")))
#endif

#define DELTA 0x9E3779B9u

static inline uint32_t mx(uint32_t z, uint32_t y, uint32_t sum,
                          const uint32_t *k, int p, uint32_t e) {
    return (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4)))
         ^ ((sum ^ y) + (k[(p & 3) ^ e] ^ z));
}

EXPORT void xxtea_encrypt(uint32_t *v, int n, const uint32_t *k) {
    uint32_t z, y, sum = 0, e;
    int p;
    int rounds = 6 + 52 / n;

    z = v[n - 1];
    while (rounds-- > 0) {
        sum += DELTA;
        e = (sum >> 2) & 3;
        for (p = 0; p < n - 1; p++) {
            y = v[p + 1];
            v[p] += mx(z, y, sum, k, p, e);
            z = v[p];
        }
        y = v[0];
        v[n - 1] += mx(z, y, sum, k, n - 1, e);
        z = v[n - 1];
    }
}

EXPORT void xxtea_decrypt(uint32_t *v, int n, const uint32_t *k) {
    uint32_t z, y, sum, e;
    int p;
    int rounds = 6 + 52 / n;

    sum = (uint32_t)rounds * DELTA;
    y = v[0];
    while (rounds-- > 0) {
        e = (sum >> 2) & 3;
        for (p = n - 1; p > 0; p--) {
            z = v[p - 1];
            v[p] -= mx(z, y, sum, k, p, e);
            y = v[p];
        }
        z = v[n - 1];
        v[0] -= mx(z, y, sum, k, 0, e);
        y = v[0];
        sum -= DELTA;
    }
}
