#!/usr/bin/env python3
"""Cross-validate the Python stego core against the C jphide/jpseek binaries.

For every (cover, payload, passphrase) case:

* C hide output must be byte-identical to Python hide output.
* C seek and Python seek must agree on the hidden output: both recover the
  payload, or both report that the file is not completely recoverable (a
  genuine upstream limitation on very small carriers).

Run from the repository root (WSL), with PYTHONPATH=src.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from jphs.jpeg import parse_jpeg
from jphs.stego import NotEnoughSpaceError, hide, seek

ROOT = Path(__file__).resolve().parent.parent
TESTDATA = ROOT / "testdata"
REF_DIR = Path(os.environ.get("JPHS_REF_DIR", "/tmp/jphs-upstream"))
PTY_RUN = ROOT / "tools" / "pty_run.py"

COVERS = [
    "cover_420.jpg",
    "cover_420_arith.jpg",
    "cover_420_arith_prog.jpg",
    "cover_422.jpg",
    "cover_444.jpg",
    "cover_444_arith.jpg",
    "cover_640_444.jpg",
    "cover_big.jpg",
    "cover_big_arith.jpg",
    "cover_big_prog.jpg",
    "cover_odd.jpg",
    "cover_odd_arith.jpg",
    "cover_odd_arith_prog.jpg",
    "cover_odd_prog.jpg",
    "cover_prog.jpg",
    "cover_small.jpg",
    "cover_420_rst.jpg",
    "cover_420_rst_prog.jpg",
    "cover_420_arith_rst.jpg",
    "cover_420_arith_rst_prog.jpg",
    "cover_odd_rst.jpg",
    "cover_odd_rst_prog.jpg",
    "cover_odd_arith_rst.jpg",
    "cover_odd_arith_rst_prog.jpg",
]
PAYLOADS = [
    "payload_empty.bin",
    "payload_16.bin",
    "payload_256.bin",
    "payload.bin",
]
PASSPHRASES = ["testpass", "a", "x" * 120]


def run_pty(binary, args, passphrase):
    env = dict(os.environ)
    env["JPHS_PASS"] = passphrase
    return subprocess.run(
        [sys.executable, str(PTY_RUN), str(binary), *map(str, args)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode


def py_seek(path, passphrase):
    try:
        return seek(parse_jpeg(path.read_bytes()), passphrase.encode())
    except Exception as exc:  # noqa: BLE001 - parity check wants any failure
        return exc


def check_case(tmpdir, cover, payload_name, passphrase, outcomes):
    label = f"{cover} {payload_name} pass={passphrase[:8]!r}"
    cover_path = TESTDATA / cover
    payload_path = TESTDATA / payload_name
    payload = payload_path.read_bytes()
    py_out = tmpdir / "py.jpg"
    c_out = tmpdir / "c.jpg"
    c_rec = tmpdir / "c_rec.bin"

    try:
        py_bytes = hide(parse_jpeg(cover_path.read_bytes()), payload,
                        passphrase.encode())
    except NotEnoughSpaceError:
        rc = run_pty(REF_DIR / "jphide_full",
                     [cover_path, c_out, payload_path], passphrase)
        if rc == 0:
            outcomes.append(f"FAIL {label}: python says no space, C ok")
        else:
            outcomes.append(f"OK   {label}: both reject (no space)")
        return
    except Exception as exc:  # noqa: BLE001
        outcomes.append(f"FAIL {label}: python hide error {exc}")
        return

    for p in (c_out, c_rec):
        if p.exists():
            p.unlink()
    py_out.write_bytes(py_bytes)

    rc = run_pty(REF_DIR / "jphide_full", [cover_path, c_out, payload_path],
                 passphrase)
    if rc != 0:
        outcomes.append(f"FAIL {label}: C hide rc={rc}")
        return
    c_bytes = c_out.read_bytes()
    if py_bytes != c_bytes:
        diff = next((i for i, (a, b) in enumerate(zip(py_bytes, c_bytes))
                     if a != b), min(len(py_bytes), len(c_bytes)))
        outcomes.append(f"FAIL {label}: hide bytes differ at {diff} "
                        f"({len(py_bytes)} vs {len(c_bytes)})")
        return

    c_rc = run_pty(REF_DIR / "jpseek_full", [c_out, c_rec], passphrase)
    if c_rc == 0:
        # jpseek calls open(O_CREAT) without a mode argument, so the output
        # file lands with garbage permissions.  Fix it up before reading.
        os.chmod(c_rec, 0o600)
        c_result = c_rec.read_bytes()
    else:
        c_result = None

    py_result = py_seek(c_out, passphrase)

    if c_result is None:
        if isinstance(py_result, Exception):
            outcomes.append(f"OK   {label}: both cannot recover "
                            f"(upstream limitation)")
        else:
            outcomes.append(f"FAIL {label}: C cannot recover, python can")
        return

    if isinstance(py_result, Exception):
        outcomes.append(f"FAIL {label}: python seek {py_result}")
        return
    if c_result != payload:
        outcomes.append(f"FAIL {label}: C seek payload mismatch")
        return
    if py_result != payload:
        outcomes.append(f"FAIL {label}: python seek payload mismatch")
        return
    outcomes.append(f"OK   {label}")


def main():
    outcomes = []
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for cover in COVERS:
            for payload_name in PAYLOADS:
                for passphrase in PASSPHRASES:
                    check_case(tmpdir, cover, payload_name, passphrase,
                               outcomes)

        # A payload large enough to span several carrier planes, and the
        # 12000-byte fixture that should overflow every cover.
        for cover in ("cover_big.jpg", "cover_big_prog.jpg", "cover_big_arith.jpg"):
            for payload_name in ("payload_4000.bin", "payload_big.bin"):
                for passphrase in ("testpass", "bigger payload"):
                    if not (TESTDATA / payload_name).exists():
                        continue
                    check_case(tmpdir, cover, payload_name, passphrase,
                               outcomes)

    for line in outcomes:
        print(line)
    failures = sum(1 for line in outcomes if line.startswith("FAIL"))
    limits = sum(1 for line in outcomes if "upstream limitation" in line)
    print(f"\n{len(outcomes)} cases, {failures} failures, "
          f"{limits} upstream limitations")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
