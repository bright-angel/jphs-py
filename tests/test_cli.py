"""CLI behaviour tests (prompts, messages, exit codes)."""

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jphs import cli  # noqa: E402

TESTDATA = ROOT / "testdata"


def run(func, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = func(argv)
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_roundtrip_and_intro(self):
        hidden = self.tmp / "hidden.jpg"
        recovered = self.tmp / "recovered.bin"
        payload = TESTDATA / "payload_256.bin"

        with mock.patch.object(cli, "_getpass",
                               side_effect=[b"pw", b"pw"]):
            code, out, err = run(
                cli.jphide,
                [str(TESTDATA / "cover_420.jpg"), str(hidden), str(payload)],
            )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("jphide, version 0.3", out)

        with mock.patch.object(cli, "_getpass", side_effect=[b"pw"]):
            code, out, err = run(
                cli.jpseek, [str(hidden), str(recovered)]
            )
        self.assertEqual(code, 0)
        self.assertIn("jpseek, version 0.3", out)
        self.assertEqual(recovered.read_bytes(), payload.read_bytes())

    def test_empty_passphrase_creates_empty_output(self):
        hidden = self.tmp / "hidden.jpg"
        with mock.patch.object(cli, "_getpass", side_effect=[b""]):
            code, _out, err = run(
                cli.jphide,
                [str(TESTDATA / "cover_420.jpg"), str(hidden),
                 str(TESTDATA / "payload_16.bin")],
            )
        self.assertEqual(code, 0)
        self.assertIn("Nothing done", err)
        self.assertTrue(hidden.exists())
        self.assertEqual(hidden.stat().st_size, 0)

    def test_mismatched_reentry_retries(self):
        hidden = self.tmp / "hidden.jpg"
        responses = [b"one", b"two", b"three", b"three"]
        with mock.patch.object(cli, "_getpass", side_effect=responses):
            code, _out, err = run(
                cli.jphide,
                [str(TESTDATA / "cover_420.jpg"), str(hidden),
                 str(TESTDATA / "payload_16.bin")],
            )
        self.assertEqual(code, 0)
        self.assertIn("Passphrases are different - try again", err)

        recovered = self.tmp / "recovered.bin"
        with mock.patch.object(cli, "_getpass", side_effect=[b"three"]):
            code, _out, _err = run(
                cli.jpseek, [str(hidden), str(recovered)]
            )
        self.assertEqual(code, 0)
        self.assertEqual(recovered.read_bytes(),
                         (TESTDATA / "payload_16.bin").read_bytes())

    def test_long_passphrase_truncated_to_120(self):
        hidden_long = self.tmp / "long.jpg"
        long_pass = b"k" * 130
        with mock.patch.object(cli, "_getpass",
                               side_effect=[long_pass, long_pass]):
            code, _out, err = run(
                cli.jphide,
                [str(TESTDATA / "cover_420.jpg"), str(hidden_long),
                 str(TESTDATA / "payload_16.bin")],
            )
        self.assertEqual(code, 0)
        self.assertIn("Truncated to 120 characters", err)

        hidden_short = self.tmp / "short.jpg"
        short_pass = b"k" * 120
        with mock.patch.object(cli, "_getpass",
                               side_effect=[short_pass, short_pass]):
            code, _out, err = run(
                cli.jphide,
                [str(TESTDATA / "cover_420.jpg"), str(hidden_short),
                 str(TESTDATA / "payload_16.bin")],
            )
        self.assertEqual(code, 0)
        self.assertEqual(hidden_long.read_bytes(), hidden_short.read_bytes())

    def test_usage(self):
        code, out, err = run(cli.jphide, [])
        self.assertEqual(code, 1)
        self.assertIn("jphide input-jpg-file output-jpg-file hide-file", err)
        self.assertIn("version 0.3", out)

        code, _out, err = run(cli.jpseek, [])
        self.assertEqual(code, 1)
        self.assertIn("jpseek input-file seek-file", err)

    def test_missing_files(self):
        code, _out, err = run(
            cli.jphide,
            [str(TESTDATA / "cover_420.jpg"), str(self.tmp / "x.jpg"),
             str(self.tmp / "missing.bin")],
        )
        self.assertEqual(code, 1)
        self.assertIn("Can't open hide file", err)

        code, _out, err = run(
            cli.jpseek, [str(self.tmp / "missing.jpg"),
                         str(self.tmp / "x.bin")],
        )
        self.assertEqual(code, 1)
        self.assertIn("Can't open input file", err)

    def test_grayscale_rejected(self):
        code, _out, err = run(
            cli.jphide,
            [str(TESTDATA / "cover_gray.jpg"), str(self.tmp / "x.jpg"),
             str(TESTDATA / "payload_16.bin")],
        )
        self.assertEqual(code, 1)
        self.assertIn("Unsuitable input jpeg file: No of components = 1", err)

    def test_not_enough_space(self):
        with mock.patch.object(cli, "_getpass", side_effect=[b"pw", b"pw"]):
            code, _out, err = run(
                cli.jphide,
                [str(TESTDATA / "cover_small.jpg"), str(self.tmp / "x.jpg"),
                 str(TESTDATA / "payload_big.bin")],
            )
        self.assertEqual(code, 1)
        self.assertIn("File not completely stored", err)

    def test_unrecoverable_image(self):
        hidden = self.tmp / "tiny.jpg"
        with mock.patch.object(cli, "_getpass", side_effect=[b"pw", b"pw"]):
            code, _out, _err = run(
                cli.jphide,
                [str(TESTDATA / "cover_odd.jpg"), str(hidden),
                 str(TESTDATA / "payload_empty.bin")],
            )
        self.assertEqual(code, 0)
        with mock.patch.object(cli, "_getpass", side_effect=[b"pw"]):
            code, _out, err = run(
                cli.jpseek, [str(hidden), str(self.tmp / "x.bin")]
            )
        self.assertEqual(code, 1)
        self.assertIn("File not completely recovered", err)


if __name__ == "__main__":
    unittest.main()
