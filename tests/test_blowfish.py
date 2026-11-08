"""Blowfish parity tests (vectors from the upstream bf.c self-test)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jphs.blowfish import Blowfish  # noqa: E402


class BlowfishVectors(unittest.TestCase):
    def test_reference_vectors(self):
        cases = [
            (
                b"abcdefghijklmnopqrstuvwxyz",
                bytes.fromhex("424c4f5746495348"),
                bytes.fromhex("324ed0fef413a203"),
            ),
            (
                b"Who is John Galt?",
                bytes.fromhex("fedcba9876543210"),
                bytes.fromhex("cc91732b8022f684"),
            ),
        ]
        for key, plain, cipher in cases:
            bf = Blowfish(key)
            self.assertEqual(bf.encrypt_block(plain), cipher)
            self.assertEqual(bf.decrypt_block(cipher), plain)

    def test_roundtrip_key_lengths(self):
        block = bytes(range(8))
        for length in (1, 2, 7, 8, 16, 55, 120):
            bf = Blowfish(b"k" * length)
            self.assertEqual(bf.decrypt_block(bf.encrypt_block(block)), block)


if __name__ == "__main__":
    unittest.main()
