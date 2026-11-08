#!/usr/bin/env bash
# Transcode covers with restart markers to exercise DRI handling.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BIN=${JPEGTRAN:-"$ROOT/.reference/jpegtran_ijg"}
cd "$ROOT/testdata"

for c in cover_420 cover_odd; do
  "$BIN" -restart 2 -outfile "${c}_rst.jpg" "${c}.jpg"
  "$BIN" -restart 2 -progressive -outfile "${c}_rst_prog.jpg" "${c}.jpg"
  "$BIN" -restart 2 -arithmetic -outfile "${c}_arith_rst.jpg" "${c}.jpg"
  "$BIN" -restart 2 -arithmetic -progressive \
    -outfile "${c}_arith_rst_prog.jpg" "${c}.jpg"
  echo "$c restart variants"
done
