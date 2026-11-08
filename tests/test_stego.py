"""Steganography round-trip and error-behaviour tests."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jphs.jpeg import parse_jpeg  # noqa: E402
from jphs.stego import (  # noqa: E402
    NotEnoughSpaceError,
    RecoveryError,
    StegoError,
    hide,
    seek,
)

TESTDATA = ROOT / "testdata"
COVERS = [
    "cover_420.jpg",
    "cover_420_arith.jpg",
    "cover_420_arith_prog.jpg",
    "cover_422.jpg",
    "cover_444.jpg",
    "cover_big.jpg",
    "cover_big_prog.jpg",
    "cover_prog.jpg",
    "cover_small.jpg",
]
PAYLOADS = [
    b"",
    b"A",
    bytes(range(16)),
    bytes(range(256)),
]
PASSPHRASES = [b"testpass", b"a", b"x" * 120]


class RoundTrip(unittest.TestCase):
    def test_roundtrip(self):
        for name in COVERS:
            data = (TESTDATA / name).read_bytes()
            for payload in PAYLOADS:
                for passphrase in PASSPHRASES:
                    with self.subTest(cover=name, size=len(payload),
                                      passphrase=len(passphrase)):
                        hidden = hide(parse_jpeg(data), payload, passphrase)
                        recovered = seek(parse_jpeg(hidden), passphrase)
                        self.assertEqual(recovered, payload)

    def test_wrong_passphrase_does_not_recover(self):
        data = (TESTDATA / "cover_420.jpg").read_bytes()
        payload = (TESTDATA / "payload_256.bin").read_bytes()
        hidden = hide(parse_jpeg(data), payload, b"testpass")
        try:
            recovered = seek(parse_jpeg(hidden), b"wrong")
        except StegoError:
            return
        self.assertNotEqual(recovered, payload)

    def test_not_enough_space(self):
        data = (TESTDATA / "cover_small.jpg").read_bytes()
        with self.assertRaises(NotEnoughSpaceError):
            hide(parse_jpeg(data), b"z" * 4096, b"testpass")

    def test_requires_three_components(self):
        data = (TESTDATA / "cover_gray.jpg").read_bytes()
        with self.assertRaisesRegex(
            StegoError,
            "Unsuitable input jpeg file: No of components = 1",
        ):
            hide(parse_jpeg(data), b"x", b"testpass")
        with self.assertRaisesRegex(
            StegoError,
            "Unsuitable input jpeg file: No of components = 1",
        ):
            seek(parse_jpeg(data), b"testpass")

    def test_truncated_carrier_raises_recovery_error(self):
        # A tiny image cannot even carry the header; upstream fails too.
        data = (TESTDATA / "cover_odd.jpg").read_bytes()
        hidden = hide(parse_jpeg(data), b"", b"testpass")
        with self.assertRaises(RecoveryError):
            seek(parse_jpeg(hidden), b"testpass")


if __name__ == "__main__":
    unittest.main()
