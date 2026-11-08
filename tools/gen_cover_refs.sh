#!/usr/bin/env bash
# Generate coefficient dumps and transcodes with the reference libjpeg build.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BIN=${REF_COEF:-"$ROOT/.reference/ref_coef"}
cd "$ROOT/testdata"
for f in cover_*.jpg; do
  case "$f" in
    *.ref.trans.jpg) continue ;;
  esac
  stem=${f%.jpg}
  "$BIN" dump "$f" "$stem.ref.dump"
  "$BIN" trans "$f" "$stem.ref.trans.jpg"
  echo "$f ok"
done
