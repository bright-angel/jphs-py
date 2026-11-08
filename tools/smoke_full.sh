#!/usr/bin/env bash
set -u
cd /mnt/c/Users/w/Downloads/jphs-py/testdata
for c in cover_big.jpg cover_big_prog.jpg cover_640_444.jpg; do
  rm -f c_out.jpg c_seek.bin
  JPHS_PASS=testpass python3 /mnt/c/Users/w/Downloads/jphs-py/tools/pty_run.py \
    /tmp/jphs-upstream/jphide_full "$c" c_out.jpg payload_256.bin >/tmp/hide.log 2>&1
  he=$?
  JPHS_PASS=testpass python3 /mnt/c/Users/w/Downloads/jphs-py/tools/pty_run.py \
    /tmp/jphs-upstream/jpseek_full c_out.jpg c_seek.bin >/tmp/seek.log 2>&1
  se=$?
  if cmp -s payload_256.bin c_seek.bin; then m=MATCH; else m=DIFF; fi
  echo "$c hide=$he seek=$se $m out=$(stat -c%s c_out.jpg) err=$(tail -1 /tmp/hide.log)"
done
