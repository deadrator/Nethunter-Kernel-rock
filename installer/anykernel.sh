### AnyKernel3 Ramdisk Mod Script
## osm0sis @ xda-developers
## rock (Poco M5 / Redmi 11 Prime 5G, GKI android12-5.10)
##
## The bootloader on this device will not boot a kernel we compressed with
## lz4. Ship a gzip kernel and copy the stock ramdisk bytes through
## unchanged (they are lz4-legacy; recompressing them also bootloops).

## AnyKernel setup
# global properties
properties() { '
kernel.string=
do.devicecheck=0
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=
device.name2=
device.name3=
device.name4=
device.name5=
supported.versions=
supported.patchlevels=
supported.vendorpatchlevels=
'; } # end properties

# boot files attributes (no ramdisk edits)
boot_attributes() {
return 0;
} # end attributes

## AnyKernel install
## boot shell variables
BLOCK=boot;
IS_SLOT_DEVICE=auto;
RAMDISK_COMPRESSION=auto;
PATCH_VBMETA_FLAG=auto;

# import functions/variables and setup patching - see for reference (DO NOT REMOVE)
. tools/ak3-core.sh

ui_print " "
ui_print "SuiKernel rock"
ui_print "gzip kernel only - stock ramdisk untouched"
ui_print " "

cd "$AKHOME" || abort "Cannot enter AKHOME. Aborting...";

if [ ! -f Image.gz ]; then
  abort "No Image.gz in the zip (uncompressed/lz4 kernels are not flashed). Aborting...";
fi;
KSRCIMG="$AKHOME/Image.gz";
rm -f Image Image.lz4 Image.lz4-dtb Image.lzma Image.xz;

# 1f 8b = gzip. 02 21 4c 18 = lz4-legacy. 04 22 4d 18 = lz4 frame.
MAGIC=$("$BIN/busybox" od -An -tx1 -N4 "$KSRCIMG" | "$BIN/busybox" tr -d ' \n');
case "$MAGIC" in
  1f8b*) ui_print "kernel gzip ok";;
  02214c18*|04224d18*) abort "Refusing lz4 kernel ($MAGIC). Aborting...";;
  *) abort "Kernel is not gzip (magic $MAGIC). Aborting...";;
esac;

if [ ! -e "$BLOCK" ]; then
  abort "Invalid partition $BLOCK. Aborting...";
fi;
ui_print "$BLOCK";

rm -f boot.img boot-new.img;
dd if="$BLOCK" of="$AKHOME/boot.img" bs=1048576 || abort "Dumping image failed. Aborting...";

rm -rf "$AKHOME/split_img" "$AKHOME/verify-orig" "$AKHOME/verify-new";
mkdir -p "$AKHOME/split_img";
cd "$AKHOME/split_img" || abort "Cannot enter split_img. Aborting...";

# -n: do not decompress. Ramdisk stays the stock compressed blob so
# repack copies those bytes instead of recompressing them as lz4.
if ! "$BIN/magiskboot" unpack -n -h "$AKHOME/boot.img" > "$AKHOME/unpack.log" 2>&1; then
  abort "magiskboot unpack -n failed. Will not recompress ramdisk. Aborting...";
fi;

if [ ! -f ramdisk.cpio ]; then
  abort "No ramdisk in boot image. Aborting...";
fi;
RD=$("$BIN/busybox" od -An -tx1 -N6 ramdisk.cpio | "$BIN/busybox" tr -d ' \n');
case "$RD" in
  303730373031*) abort "Ramdisk was decompressed. Refusing lz4 recompress. Aborting...";;
esac;
ui_print "stock ramdisk preserved";

# Already-gzip kernel is written as-is. An uncompressed Image would be
# recompressed with the stock format, which is lz4 on this device.
cp -f "$KSRCIMG" kernel || abort "Failed to stage gzip kernel. Aborting...";
rm -f kernel.lz4 kernel.lz4_legacy kernel.gz;

"$BIN/magiskboot" repack "$AKHOME/boot.img" "$AKHOME/boot-new.img" || abort "Repacking image failed. Aborting...";
cd "$AKHOME" || abort "Cannot enter AKHOME. Aborting...";

# Confirm repack did not lz4 the kernel and did not rewrite the ramdisk.
mkdir -p "$AKHOME/verify-orig" "$AKHOME/verify-new";
( cd "$AKHOME/verify-orig" && "$BIN/magiskboot" unpack -n "$AKHOME/boot.img" >/dev/null 2>&1 ) || abort "Cannot re-read stock boot. Aborting...";
( cd "$AKHOME/verify-new" && "$BIN/magiskboot" unpack -n "$AKHOME/boot-new.img" >/dev/null 2>&1 ) || abort "Cannot re-read new boot. Aborting...";
"$BIN/busybox" cmp "$AKHOME/verify-orig/ramdisk.cpio" "$AKHOME/verify-new/ramdisk.cpio" || abort "Ramdisk bytes changed. Aborting...";
if [ -d "$AKHOME/verify-orig/vendor_ramdisk" ]; then
  for f in "$AKHOME/verify-orig/vendor_ramdisk"/*; do
    [ -f "$f" ] || continue;
    b=$("$BIN/busybox" basename "$f");
    "$BIN/busybox" cmp "$f" "$AKHOME/verify-new/vendor_ramdisk/$b" || abort "Vendor ramdisk $b changed. Aborting...";
  done;
fi;
NMAGIC=$("$BIN/busybox" od -An -tx1 -N4 "$AKHOME/verify-new/kernel" | "$BIN/busybox" tr -d ' \n');
case "$NMAGIC" in
  1f8b*) ui_print "packed kernel is gzip";;
  02214c18*|04224d18*) abort "Packed kernel is lz4 ($NMAGIC). Aborting...";;
  *) abort "Packed kernel is not gzip ($NMAGIC). Aborting...";;
esac;

ISZ=$("$BIN/busybox" wc -c < "$AKHOME/boot-new.img");
PSZ=$("$BIN/busybox" blockdev --getsize64 "$BLOCK" 2>/dev/null || true);
if [ -n "$PSZ" ] && [ "$ISZ" -gt "$PSZ" ]; then
  abort "New boot image ($ISZ) is larger than $BLOCK ($PSZ). Aborting...";
fi;

dd if="$AKHOME/boot-new.img" of="$BLOCK" bs=1048576 || abort "Writing boot failed. Aborting...";
"$BIN/busybox" sync;
ui_print "boot written (gzip kernel, stock ramdisk)";
ui_print " ";
