"""Blowfish (Bruce Schneier), big-endian block convention.

This mirrors Olaf Titz's public-domain ``bf.c`` as bundled with jphs: key
expansion from the digits of pi, and the standard big-endian data path.
"""

from __future__ import annotations

from ._tables import BLOWFISH_INIT_KEY

_MASK = 0xFFFFFFFF


def _f(s: list[int], x: int) -> int:
    return (
        ((s[x >> 24] + s[256 + ((x >> 16) & 0xFF)]) ^ s[512 + ((x >> 8) & 0xFF)])
        + s[768 + (x & 0xFF)]
    ) & _MASK


def _encrypt_words(p: list[int], s: list[int], l: int, r: int) -> tuple[int, int]:
    l ^= p[0]
    for i in range(1, 17, 2):
        r ^= p[i] ^ _f(s, l)
        l ^= p[i + 1] ^ _f(s, r)
    return r ^ p[17], l


def _decrypt_words(p: list[int], s: list[int], l: int, r: int) -> tuple[int, int]:
    l ^= p[17]
    for i in range(16, 0, -2):
        r ^= p[i] ^ _f(s, l)
        l ^= p[i - 1] ^ _f(s, r)
    return r ^ p[0], l


class Blowfish:
    """Expanded Blowfish key (18 P words + 4 x 256 S words)."""

    __slots__ = ("p", "s")

    def __init__(self, key: bytes) -> None:
        if not key:
            raise ValueError("empty Blowfish key")
        p = list(BLOWFISH_INIT_KEY[:18])
        s = list(BLOWFISH_INIT_KEY[18:])
        n = len(key)
        j = 0
        for i in range(18):
            u = 0
            for _ in range(4):
                u = (u << 8) | key[j]
                j += 1
                if j >= n:
                    j = 0
            p[i] ^= u

        l = r = 0
        for i in range(0, 1042, 2):
            l, r = _encrypt_words(p, s, l, r)
            if i < 18:
                p[i] = l
                p[i + 1] = r
            else:
                s[i - 18] = l
                s[i - 17] = r

        self.p = p
        self.s = s

    def encrypt_block(self, block: bytes) -> bytes:
        """Encrypt one 8-byte block; bytes are read/written big-endian."""
        if len(block) != 8:
            raise ValueError("Blowfish block must be 8 bytes")
        l, r = _encrypt_words(
            self.p,
            self.s,
            int.from_bytes(block[:4], "big"),
            int.from_bytes(block[4:], "big"),
        )
        return l.to_bytes(4, "big") + r.to_bytes(4, "big")

    def decrypt_block(self, block: bytes) -> bytes:
        """Decrypt one 8-byte block (inverse of :meth:`encrypt_block`)."""
        if len(block) != 8:
            raise ValueError("Blowfish block must be 8 bytes")
        l, r = _decrypt_words(
            self.p,
            self.s,
            int.from_bytes(block[:4], "big"),
            int.from_bytes(block[4:], "big"),
        )
        return l.to_bytes(4, "big") + r.to_bytes(4, "big")
