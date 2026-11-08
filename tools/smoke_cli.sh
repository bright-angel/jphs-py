#!/usr/bin/env bash
# CLI behaviour parity: prompts, messages and exit codes vs. the C binaries.
set -u

ROOT=/mnt/c/Users/w/Downloads/jphs-py
TD=$ROOT/testdata
export PYTHONPATH=$ROOT/src
export PYTHONDONTWRITEBYTECODE=1
REF=${JPHS_REF_DIR:-/tmp/jphs-upstream}
PTY="python3 $ROOT/tools/pty_run.py"
PYCLI="python3 -m jphs"

cd "$TD" || exit 1
fail=0

run() { # name expected_rc command...
  local name=$1 want=$2
  shift 2
  "$@" >"/tmp/${name}.log" 2>&1
  local rc=$?
  if [ "$rc" -ne "$want" ]; then
    echo "FAIL $name: rc=$rc want=$want"
    fail=1
  else
    echo "OK   $name rc=$rc"
  fi
}

# 1. Normal hide/seek parity (bytes already covered by xcheck_stego.py).
rm -f cd_a.jpg cd_b.jpg
run c_hide 0 env JPHS_PASS=testpass $PTY "$REF/jphide_full" \
  cover_big.jpg cd_a.jpg payload_256.bin
run py_hide 0 env JPHS_PASS=testpass $PTY $PYCLI jphide \
  cover_big.jpg cd_b.jpg payload_256.bin
cmp -s cd_a.jpg cd_b.jpg && echo "OK   hide bytes identical" || {
  echo "FAIL hide bytes differ"; fail=1; }

# 2. Empty passphrase -> "Nothing done", exit 0, empty output file.
rm -f cd_empty.jpg
run c_empty 0 env JPHS_PASS= $PTY "$REF/jphide_full" \
  cover_big.jpg cd_empty.jpg payload_16.bin
grep -q "Nothing done" /tmp/c_empty.log || { echo "FAIL c_empty text"; fail=1; }
rm -f cd_empty.jpg
run py_empty 0 env JPHS_PASS= $PTY $PYCLI jphide \
  cover_big.jpg cd_empty.jpg payload_16.bin
grep -q "Nothing done" /tmp/py_empty.log || { echo "FAIL py_empty text"; fail=1; }
[ -f cd_empty.jpg ] && [ ! -s cd_empty.jpg ] && echo "OK   empty output file" || {
  echo "FAIL empty output file"; fail=1; }

# 3. Mismatched re-entry then success.
rm -f cd_mm.jpg
run c_mismatch 0 env JPHS_PASSES=testpass JPHS_REENTERS='wrong|testpass' \
  $PTY "$REF/jphide_full" cover_big.jpg cd_mm.jpg payload_16.bin
grep -q "Passphrases are different - try again" /tmp/c_mismatch.log || {
  echo "FAIL c_mismatch text"; fail=1; }
rm -f cd_mm.jpg
run py_mismatch 0 env JPHS_PASSES=testpass JPHS_REENTERS='wrong|testpass' \
  $PTY $PYCLI jphide cover_big.jpg cd_mm.jpg payload_16.bin
grep -q "Passphrases are different - try again" /tmp/py_mismatch.log || {
  echo "FAIL py_mismatch text"; fail=1; }

# 4. Passphrase longer than 120 characters is truncated identically.
LONG=$(printf 'k%.0s' $(seq 1 130))
rm -f cd_lc.jpg cd_lp.jpg
run c_long 0 env JPHS_PASS="$LONG" $PTY "$REF/jphide_full" \
  cover_big.jpg cd_lc.jpg payload_16.bin
grep -q "Truncated to 120 characters" /tmp/c_long.log || {
  echo "FAIL c_long text"; fail=1; }
run py_long 0 env JPHS_PASS="$LONG" $PTY $PYCLI jphide \
  cover_big.jpg cd_lp.jpg payload_16.bin
grep -q "Truncated to 120 characters" /tmp/py_long.log || {
  echo "FAIL py_long text"; fail=1; }
cmp -s cd_lc.jpg cd_lp.jpg && echo "OK   truncation bytes identical" || {
  echo "FAIL truncation bytes differ"; fail=1; }

# 5. Usage errors.
run c_usage 1 "$REF/jphide_full"
grep -q "jphide input-jpg-file output-jpg-file hide-file" /tmp/c_usage.log \
  || { echo "FAIL c_usage text"; fail=1; }
run py_usage 1 $PYCLI jphide
grep -q "jphide input-jpg-file output-jpg-file hide-file" /tmp/py_usage.log \
  || { echo "FAIL py_usage text"; fail=1; }
run c_usage_seek 1 "$REF/jpseek_full"
run py_usage_seek 1 $PYCLI jpseek

# 6. Missing files.
run c_nohide 1 env JPHS_PASS=x $PTY "$REF/jphide_full" \
  cover_big.jpg /tmp/x.jpg /tmp/does-not-exist.bin
grep -q "Can't open hide file" /tmp/c_nohide.log || {
  echo "FAIL c_nohide text"; fail=1; }
run py_nohide 1 env JPHS_PASS=x $PTY $PYCLI jphide \
  cover_big.jpg /tmp/x.jpg /tmp/does-not-exist.bin
grep -q "Can't open hide file" /tmp/py_nohide.log || {
  echo "FAIL py_nohide text"; fail=1; }
run c_noseekin 1 env JPHS_PASS=x $PTY "$REF/jpseek_full" /tmp/nope.jpg /tmp/x.bin
grep -q "Can't open input file" /tmp/c_noseekin.log || {
  echo "FAIL c_noseekin text"; fail=1; }
run py_noseekin 1 env JPHS_PASS=x $PTY $PYCLI jpseek /tmp/nope.jpg /tmp/x.bin
grep -q "Can't open input file" /tmp/py_noseekin.log || {
  echo "FAIL py_noseekin text"; fail=1; }

# 7. Not enough space.
run c_nospace 1 env JPHS_PASS=testpass $PTY "$REF/jphide_full" \
  cover_big.jpg /tmp/ns_c.jpg payload_big.bin
grep -q "File not completely stored" /tmp/c_nospace.log || {
  echo "FAIL c_nospace text"; fail=1; }
run py_nospace 1 env JPHS_PASS=testpass $PTY $PYCLI jphide \
  cover_big.jpg /tmp/ns_p.jpg payload_big.bin
grep -q "File not completely stored" /tmp/py_nospace.log || {
  echo "FAIL py_nospace text"; fail=1; }

# 8. Grayscale cover rejected with the upstream component message.
run c_gray 1 env JPHS_PASS=testpass $PTY "$REF/jphide_full" \
  cover_gray.jpg /tmp/gray_c.jpg payload_16.bin
grep -q "Unsuitable input jpeg file: No of components = 1" /tmp/c_gray.log || {
  echo "FAIL c_gray text"; fail=1; }
run py_gray 1 env JPHS_PASS=testpass $PTY $PYCLI jphide \
  cover_gray.jpg /tmp/gray_p.jpg payload_16.bin
grep -q "Unsuitable input jpeg file: No of components = 1" /tmp/py_gray.log || {
  echo "FAIL py_gray text"; fail=1; }

# 9. Unrecoverable tiny carrier (upstream limitation) fails identically.
rm -f /tmp/tiny_c.jpg /tmp/tiny_p.jpg
run c_tinyhide 0 env JPHS_PASS=testpass $PTY "$REF/jphide_full" \
  cover_odd.jpg /tmp/tiny_c.jpg payload_empty.bin
run py_tinyhide 0 env JPHS_PASS=testpass $PTY $PYCLI jphide \
  cover_odd.jpg /tmp/tiny_p.jpg payload_empty.bin
cmp -s /tmp/tiny_c.jpg /tmp/tiny_p.jpg || { echo "FAIL tiny bytes"; fail=1; }
# jpseek leaves recoverable-output files with unusable permissions; remove
# stale files so O_CREAT does not fail with EACCES.
rm -f /tmp/tiny_c.bin /tmp/tiny_p.bin
run c_tinyseek 1 env JPHS_PASS=testpass $PTY "$REF/jpseek_full" \
  /tmp/tiny_c.jpg /tmp/tiny_c.bin
grep -q "File not completely recovered" /tmp/c_tinyseek.log || {
  echo "FAIL c_tinyseek text"; fail=1; }
run py_tinyseek 1 env JPHS_PASS=testpass $PTY $PYCLI jpseek \
  /tmp/tiny_c.jpg /tmp/tiny_p.bin
grep -q "File not completely recovered" /tmp/py_tinyseek.log || {
  echo "FAIL py_tinyseek text"; fail=1; }

echo
[ "$fail" -eq 0 ] && echo "CLI smoke: all checks passed" || echo "CLI smoke: FAILURES"
exit "$fail"
