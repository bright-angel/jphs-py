#!/usr/bin/env bash
# Build the unmodified upstream jphs C binaries inside WSL for cross-validation.
# Produces:
#   .reference/jphide_turbo  .reference/jpseek_turbo   (system libjpeg-turbo)
#   .reference/jphide_ijg    .reference/jpseek_ijg     (bundled IJG jpeg-8a)
set -euo pipefail

ROOT=/mnt/c/Users/w/Downloads/jphs-py
SRC="$ROOT/upstream"
OUT="$ROOT/.reference"
WORK=/tmp/jphs-upstream
IJG=/tmp/ijg-build

if [ ! -d "$SRC" ]; then
  git clone --depth 1 https://github.com/h3xx/jphs.git "$SRC"
fi

rm -rf "$WORK" "$IJG"
mkdir -p "$OUT" "$WORK" "$IJG"
cp -r "$SRC"/. "$WORK"/

# The bundled jpeg-8a tree ships no generated jconfig.h.
cat > "$WORK/jpeg-8a/jconfig.h" <<'EOF'
#define HAVE_PROTOTYPES
#define HAVE_UNSIGNED_CHAR
#define HAVE_UNSIGNED_SHORT
#define HAVE_STDDEF_H
#define HAVE_STDLIB_H
#define JPEG_LIB_VERSION 80
#define BITS_IN_JSAMPLE 8
#define D_ARITH_CODING_SUPPORTED
#define C_ARITH_CODING_SUPPORTED
#define D_MULTISCAN_FILES_SUPPORTED
#define C_MULTISCAN_FILES_SUPPORTED
EOF

cd "$WORK"
gcc -O2 -I./jpeg-8a -c jphide.c -o jphide.o
gcc -O2 -I./jpeg-8a -c jpseek.c -o jpseek.o
gcc -O2 -c bf.c -o bf.o

# Variant 1: what the upstream Makefile links on a normal Debian/Kali install.
gcc -o jphide_turbo jphide.o bf.o /usr/lib/x86_64-linux-gnu/libjpeg.so.62
gcc -o jpseek_turbo jpseek.o bf.o /usr/lib/x86_64-linux-gnu/libjpeg.so.62

# Variant 2: the bundled IJG jpeg-8a reference implementation, built static.
cd "$IJG"
cp "$WORK/jpeg-8a/jconfig.h" .
SOURCES="jaricom.c jcapimin.c jcapistd.c jcarith.c jccoefct.c jccolor.c jcdctmgr.c
jchuff.c jcinit.c jcmainct.c jcmarker.c jcmaster.c jcomapi.c jcparam.c jcprepct.c
jcsample.c jctrans.c jdapimin.c jdapistd.c jdarith.c jdatadst.c jdatasrc.c jdcoefct.c
jdcolor.c jddctmgr.c jdhuff.c jdinput.c jdmainct.c jdmarker.c jdmaster.c jdmerge.c
jdpostct.c jdsample.c jdtrans.c jerror.c jfdctflt.c jfdctfst.c jfdctint.c jidctflt.c
jidctfst.c jidctint.c jmemmgr.c jmemnobs.c jquant1.c jquant2.c jutils.c"
for f in $SOURCES; do
  gcc -O2 -I"$WORK/jpeg-8a" -c "$WORK/jpeg-8a/$f" -o "${f%.c}.o"
done
ar rcs libjpeg.a ./*.o
cd "$WORK"
gcc -o jphide_ijg jphide.o bf.o "$IJG/libjpeg.a"
gcc -o jpseek_ijg jpseek.o bf.o "$IJG/libjpeg.a"

# Reference transcode tool (dumps coefficients / re-encodes like jphide does).
gcc -O2 -I"$WORK/jpeg-8a" -o ref_coef "$ROOT/tools/ref_coef.c" "$IJG/libjpeg.a"

# IJG jpegtran with arithmetic support, used to generate arithmetic fixtures.
cd "$IJG"
gcc -O2 -I"$WORK/jpeg-8a" -c "$WORK/jpeg-8a/jpegtran.c" -o jpegtran.o
gcc -O2 -I"$WORK/jpeg-8a" -c "$WORK/jpeg-8a/cdjpeg.c" -o cdjpeg.o
gcc -O2 -I"$WORK/jpeg-8a" -c "$WORK/jpeg-8a/transupp.c" -o transupp.o
gcc -O2 -I"$WORK/jpeg-8a" -c "$WORK/jpeg-8a/rdswitch.c" -o rdswitch.o
gcc -o jpegtran jpegtran.o cdjpeg.o transupp.o rdswitch.o libjpeg.a
cd "$WORK"

cp jphide_turbo jpseek_turbo jphide_ijg jpseek_ijg "$OUT"/
cp jphide_ijg jphide_full
cp jpseek_ijg jpseek_full
cp jphide_full jpseek_full "$OUT"/
cp ref_coef "$OUT"/
cp "$IJG/jpegtran" "$OUT/jpegtran_ijg"
ls -l "$OUT"
