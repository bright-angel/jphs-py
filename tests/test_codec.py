"""JPEG codec parity against libjpeg reference dumps and transcodes."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import xcheck_codec  # noqa: E402

TESTDATA = ROOT / "testdata"


def covers():
    return sorted(
        path
        for path in TESTDATA.glob("cover_*.jpg")
        if not path.name.endswith(".ref.trans.jpg")
    )


class CodecParity(unittest.TestCase):
    def test_reference_coefficients_and_transcode(self):
        cases = covers()
        self.assertTrue(cases, "no cover fixtures found")
        for cover in cases:
            with self.subTest(cover=cover.name):
                ref_stem = Path(str(cover.with_suffix("")) + ".ref")
                self.assertTrue(
                    Path(str(ref_stem) + ".dump").exists(),
                    f"missing reference dump for {cover.name}",
                )
                self.assertTrue(
                    Path(str(ref_stem) + ".trans.jpg").exists(),
                    f"missing reference transcode for {cover.name}",
                )
                errors, _actual, _expected = xcheck_codec.check(ref_stem, cover)
                self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
