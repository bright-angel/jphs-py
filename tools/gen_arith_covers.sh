#!/usr/bin/env bash
# Transcode selected covers to arithmetic-coded JPEGs (SOF9/SOF10).
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BIN=${JPEGTRAN:-"$ROOT/.reference/jpegtran_ijg"}
cd "$ROOT/testdata"

for c in cover_420 cover_444 cover_odd cover_big; do
  "$BIN" -arithmetic -outfile "${c}_arith.jpg" "${c}.jpg"
  echo "${c}_arith.jpg"
done

for c in cover_420 cover_odd; do
  "$BIN" -arithmetic -progressive -outfile "${c}_arith_prog.jpg" "${c}.jpg"
  echo "${c}_arith_prog.jpg"
done
