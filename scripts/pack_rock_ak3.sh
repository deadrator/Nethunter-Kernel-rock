#!/bin/sh
# Repack an author AnyKernel zip for rock:
#   - kernel payload is gzip only (Image.gz). Image and Image.lz4 are removed
#     so magiskboot cannot recompress the kernel as lz4.
#   - anykernel.sh is the rock installer (gzip kernel, stock ramdisk bytes).
# Usage: pack_rock_ak3.sh <author.zip> <anykernel.sh> <out.zip>
set -eu

IN=${1:?author zip}
AK=${2:?anykernel.sh}
OUT=${3:?out zip}

# zip runs after cd, so relative outs would land in the temp dir.
case "$IN" in /*) ;; *) IN="$PWD/$IN" ;; esac
case "$AK" in /*) ;; *) AK="$PWD/$AK" ;; esac
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac

[ -f "$IN" ] || { echo "FATAL: missing $IN" >&2; exit 1; }
[ -f "$AK" ] || { echo "FATAL: missing $AK" >&2; exit 1; }
# The installer is parsed on device by a POSIX shell. Catch a broken file here.
sh -n "$AK"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
unzip -q "$IN" -d "$WORK"

if [ ! -f "$WORK/Image" ] && [ ! -f "$WORK/Image.gz" ]; then
  echo "FATAL: author zip has no Image" >&2
  exit 1
fi

if [ -f "$WORK/Image" ]; then
  # -n: no timestamp in the header. Magic stays 1f 8b.
  gzip -n -9 -c "$WORK/Image" > "$WORK/Image.gz"
  rm -f "$WORK/Image"
fi
rm -f "$WORK/Image.lz4" "$WORK/Image.lz4-dtb" "$WORK/Image.lzma" "$WORK/Image.xz"

python3 - "$WORK/Image.gz" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
b = p.read_bytes()[:4]
if b[:2] != b"\x1f\x8b":
    raise SystemExit(f"FATAL: Image.gz is not gzip ({b.hex()})")
if b[:4] in (b"\x02\x21\x4c\x18", b"\x04\x22\x4d\x18"):
    raise SystemExit("FATAL: Image.gz is lz4")
print(f"Image.gz gzip ok ({p.stat().st_size} bytes)")
PY

cp "$AK" "$WORK/anykernel.sh"
# properties() lines must be unindented or AK3's file_getprop misses them.
grep -q '^do.modules=0$' "$WORK/anykernel.sh"
grep -q 'unpack -n' "$WORK/anykernel.sh"
grep -q 'Refusing lz4' "$WORK/anykernel.sh"

rm -f "$OUT"
(
  cd "$WORK"
  zip -r9 -q "$OUT" .
)

# The zip that gets flashed must not still contain an lz4 or raw kernel.
unzip -l "$OUT" | awk '{print $4}' | grep -E '(^|/)Image(\.lz4)?$' && {
  echo "FATAL: raw or lz4 kernel still in $OUT" >&2
  exit 1
}
unzip -l "$OUT" | grep -q 'Image.gz'
echo "packed $OUT"
