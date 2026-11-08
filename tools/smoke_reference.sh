#!/usr/bin/env bash
set -u
cd /mnt/c/Users/w/Downloads/jphs-py/testdata
for p in payload_16.bin payload_256.bin payload.bin; do
  rm -f c_out.jpg c_seek.bin
  JPHS_PASS=testpass python3 /mnt/c/Users/w/Downloads/jphs-py/tools/pty_run.py \
    /tmp/jphs-upstream/jphide_ijg cover_big.jpg c_out.jpg "$p" >/tmp/hide.log 2>&1
  he=$?
  JPHS_PASS=testpass python3 /mnt/c/Users/w/Downloads/jphs-py/tools/pty_run.py \
    /tmp/jphs-upstream/jpseek_ijg c_out.jpg c_seek.bin >/tmp/seek.log 2>&1
  se=$?
  if cmp -s "$p" c_seek.bin; then m=MATCH; else m=DIFF; fi
  echo "$p hide=$he seek=$se $m out=$(stat -c%s c_out.jpg) $(tail -1 /tmp/hide.log)"
done
