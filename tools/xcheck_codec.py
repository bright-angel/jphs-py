#!/usr/bin/env python3
"""Compare the pure-Python JPEG codec against tools/ref_coef output.

Usage:
    python tools/xcheck_codec.py testdata/cover.jpg [more.jpg ...]

For each input, expects these files (produced by ref_coef):
    <stem>.dump         coefficient dump
    <stem>.trans.jpg    libjpeg transcode
and compares them with parse_jpeg/encode_jpeg.
"""

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jphs.jpeg import parse_jpeg, encode_jpeg  # noqa: E402

CS_NAMES = ["UNKNOWN", "GRAYSCALE", "RGB", "YCbCr", "CMYK", "YCCK"]


def read_dump(path):
    data = Path(path).read_bytes()
    assert data.startswith(b"JCOEF1\n")
    pos = 7
    vals = []

    def u32():
        nonlocal pos
        v = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        return v

    meta = {
        "width": u32(),
        "height": u32(),
        "ncomp": u32(),
        "precision": u32(),
        "colorspace": CS_NAMES[u32()],
        "saw_jfif": u32(),
        "jfif_major": u32(),
        "jfif_minor": u32(),
        "density_unit": u32(),
        "x_density": u32(),
        "y_density": u32(),
        "saw_adobe": u32(),
        "adobe_transform": u32(),
    }
    comps = []
    for _ in range(meta["ncomp"]):
        comps.append(
            {
                "id": u32(),
                "h": u32(),
                "v": u32(),
                "q": u32(),
                "wib": u32(),
                "hib": u32(),
            }
        )
    for c in comps:
        padded_w = -(-c["wib"] // c["h"]) * c["h"]
        padded_h = -(-c["hib"] // c["v"]) * c["v"]
        c["padded_w"] = padded_w
        c["padded_h"] = padded_h
        rows = []
        for _ in range(padded_h):
            row = list(struct.unpack_from("<%dh" % (padded_w * 64), data, pos))
            pos += padded_w * 128
            rows.append(row)
        c["rows"] = rows
    return meta, comps


def check(ref_stem, cover):
    meta, ref_comps = read_dump(str(ref_stem) + ".dump")
    image = parse_jpeg(Path(cover).read_bytes())
    errors = []
    if (image.width, image.height, len(image.components), image.precision) != (
        meta["width"],
        meta["height"],
        meta["ncomp"],
        meta["precision"],
    ):
        errors.append("frame mismatch")
    if image.colorspace != meta["colorspace"]:
        errors.append(f"colorspace {image.colorspace} != {meta['colorspace']}")
    for i, (ours, ref) in enumerate(zip(image.components, ref_comps)):
        if (ours.component_id, ours.h_samp, ours.v_samp, ours.quant_tbl_no) != (
            ref["id"],
            ref["h"],
            ref["v"],
            ref["q"],
        ):
            errors.append(f"comp{i} header mismatch")
        if (ours.width_in_blocks, ours.height_in_blocks) != (ref["wib"], ref["hib"]):
            errors.append(f"comp{i} block dims mismatch")
        for r, (orow, rrow) in enumerate(zip(ours.rows, ref["rows"])):
            if orow != rrow:
                for k, (a, b) in enumerate(zip(orow, rrow)):
                    if a != b:
                        errors.append(
                            f"comp{i} row{r} coef{k}: {a} != {b}"
                        )
                        break
                break
    expected = Path(str(ref_stem) + ".trans.jpg").read_bytes()
    actual = encode_jpeg(image)
    if actual != expected:
        # Locate first difference for debugging.
        n = min(len(actual), len(expected))
        at = next((i for i in range(n) if actual[i] != expected[i]), n)
        errors.append(
            f"transcode mismatch at {at} (len {len(actual)} vs {len(expected)})"
        )
    return errors, len(actual), len(expected)


def main(argv):
    failed = False
    for cover in argv:
        stem = Path(cover).with_suffix("")
        ref_stem = Path(str(stem) + ".ref")
        errors, alen, elen = check(ref_stem, cover)
        status = "OK" if not errors else "FAIL"
        print(f"{status} {cover} ({alen} bytes)")
        for e in errors[:10]:
            print("   ", e)
        failed = failed or bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
