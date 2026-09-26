#!/usr/bin/env python3
"""Prepare a clone of SuiKernel-GKI-Bulder for rock builds.

What it does, in order:
  1. config.sh: point KERNEL_REPO at the forked kernel source
     (AnyKernel repo/branch and the clang-r416183b tarball are already correct).
  2. build.sh: pin the kernel source to an exact commit (the author clones the
     branch tip; we fetch+checkout the pinned SHA right after the clone).
  3. build.sh: pin the SUSFS clone to the commit the author's known-booting
     releases were built from (predates the unvalidated upstream SUS_KSTAT
     type change of 2026-09-25).
  4. build.sh: disable the KernelSU-Next manager-APK fetch (artifact download
     requires a token; the section's own guards would let a 403 page through
     into unzip and kill the build).
  5. build.sh: for the "nethunter" variant, vendor aircrack-ng rtl8188eus into
     the kernel tree and build it in (CONFIG_RTL8188EU=y) with cfg80211.
     mac80211 and ath9k_htc stay off — those built-ins are what bootlooped
     rock. The USB ID 2357:010c is in the driver's table, so TL-WN722N v2/v3
     binds with no insmod.
  6. functions.sh: pin the KernelSU-Next checkout to an exact commit.
  7. functions.sh: neutralize the Telegram report functions (this fork has no
     bot secrets; no-ops keep the author's control flow intact).

Run from the workspace root:
  python3 scripts/prepare_builder.py --variant nethunter --builder builder \
      --kernel-pin SHA --susfs-pin SHA --ksu-pin SHA
"""

import argparse
from pathlib import Path


def replace_once(s: str, old: str, new: str, what: str) -> str:
    n = s.count(old)
    assert n == 1, f"{what}: expected exactly 1 anchor, found {n}"
    return s.replace(old, new, 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--builder", default="builder")
    ap.add_argument("--variant", choices=("safe", "nethunter"), required=True)
    ap.add_argument(
        "--kernel-repo",
        default="https://github.com/deadrator/SuiKernel-android12-5.10",
    )
    ap.add_argument("--kernel-pin", required=True)
    ap.add_argument("--susfs-pin", required=True)
    ap.add_argument("--ksu-pin", required=True)
    args = ap.parse_args()
    root = Path(args.builder)

    # ---- config.sh --------------------------------------------------------
    p = root / "config.sh"
    s = p.read_text()
    s = replace_once(
        s,
        'KERNEL_REPO="https://github.com/LoggingNewMemory/SuiKernel-android12-5.10"',
        f'KERNEL_REPO="{args.kernel_repo}"',
        "config.sh KERNEL_REPO",
    )
    # googlesource's +archive endpoint has been unreachable from GH runners
    # (killed runs #16n/#17/#18 with aria2c AND retrying curl); use the
    # GitHub mirror of the exact same clang-r416183b via the builder's own
    # git-clone path (CLANG_BRANCH set => git clone branch).
    s = replace_once(
        s,
        'CLANG_URL="https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/+archive/b669748458572622ed716407611633c5415da25c/clang-r416183b.tar.gz"',
        'CLANG_URL="https://github.com/crdroidandroid/android_prebuilts_clang_host_linux-x86_clang-r416183b"',
        "config.sh CLANG_URL",
    )
    s = replace_once(
        s,
        'CLANG_BRANCH=""',
        'CLANG_BRANCH="11.0"',
        "config.sh CLANG_BRANCH",
    )
    p.write_text(s)

    # ---- build.sh ---------------------------------------------------------
    p = root / "build.sh"
    s = p.read_text()

    # googlesource's +archive endpoint rejects aria2c's 16 parallel segments
    # (killed run #16 nethunter and both runs of #17); single-connection curl
    # with retries succeeded on the same runner class in run #16.
    old = (
        'aria2c -q -c -x16 -s32 -k8M --file-allocation=falloc '
        '--timeout=60 --retry-wait=5 -o tarball "$CLANG_URL"'
    )
    s = replace_once(
        s,
        old,
        'curl -fL --retry 5 --retry-delay 10 --retry-all-errors '
        '--connect-timeout 30 -o tarball "$CLANG_URL"',
        "clang download transport",
    )

    old = "git clone -q --depth=1 $KERNEL_REPO -b $KERNEL_BRANCH $KSRC"
    pin = (
        old
        + "\ngit -C $KSRC fetch -q origin "
        + args.kernel_pin
        + " && git -C $KSRC checkout -q FETCH_HEAD"
    )
    if args.variant == "nethunter":
        # Runs in the builder, after the kernel tree exists and before
        # defconfig. The driver Makefile is the in-tree kbuild half
        # (obj-$(CONFIG_RTL8188EU)); we only fix flags that break clang-12
        # GKI and force the cfg80211 ioctl path the I386 platform block
        # would otherwise have added.
        pin += r"""
log "Vendoring aircrack-ng rtl8188eus (built-in, USB 2357:010c)"
DRV="$KSRC/drivers/net/wireless/rtl8188eus"
rm -rf "$DRV"
git clone --depth=1 -q -b v5.3.9 https://github.com/aircrack-ng/rtl8188eus.git "$DRV"
grep -q '0x2357, 0x010c' "$DRV/os_dep/linux/usb_intf.c"
sed -i '/Wno-cast-function-type/d' "$DRV/Makefile"
sed -i 's/^CONFIG_PLATFORM_I386_PC = y/CONFIG_PLATFORM_I386_PC = n/' "$DRV/Makefile"
sed -i '1i EXTRA_CFLAGS += -Wno-error -DCONFIG_IOCTL_CFG80211 -DRTW_USE_CFG80211_STA_EVENT -DCONFIG_LITTLE_ENDIAN' "$DRV/Makefile"
grep -q 'CONFIG_IOCTL_CFG80211' "$DRV/Makefile"
! grep -q 'Wno-cast-function-type' "$DRV/Makefile"
WMF="$KSRC/drivers/net/wireless/Makefile"
grep -q 'rtl8188eus/' "$WMF" || printf '\n%s\n' 'obj-$(CONFIG_RTL8188EU) += rtl8188eus/' >> "$WMF"
KCFG="$KSRC/drivers/net/wireless/Kconfig"
if ! grep -q 'rtl8188eus/Kconfig' "$KCFG"; then
  SRC_LINE='source "drivers/net/wireless/rtl8188eus/Kconfig"'
  awk -v line="$SRC_LINE" '/^endif # WLAN$/ && !done { print line; print ""; done=1 } { print }' "$KCFG" > "$KCFG.new"
  mv "$KCFG.new" "$KCFG"
fi
grep -q 'rtl8188eus/Kconfig' "$KCFG"
"""
    s = replace_once(s, old, pin, "kernel clone pin")

    old = (
        'git clone --depth=1 -q https://gitlab.com/simonpunk/susfs4ksu '
        '-b gki-android12-5.10 "$workdir/susfs"'
    )
    s = replace_once(
        s,
        old,
        old
        + '\n  git -C "$workdir/susfs" fetch -q origin '
        + args.susfs_pin
        + ' && git -C "$workdir/susfs" checkout -q FETCH_HEAD',
        "susfs clone pin",
    )

    old = (
        'if [[ "$VARIANT" == *"KernelSU-Next"* ]]; then\n'
        '  log "Fetching latest KernelSU-Next Manager APKs from dev branch..."'
    )
    s = replace_once(
        s,
        old,
        "if false; then # manager APK fetch disabled on fork (artifact download needs a token); grab the manager from KernelSU-Next releases\n"
        '  log "Fetching latest KernelSU-Next Manager APKs from dev branch..."',
        "manager fetch block",
    )

    if args.variant == "nethunter":
        anchor = "config --enable CONFIG_KSU\n"
        wifi = (
            'log "NetHunter: built-in rtl8188eus + cfg80211 (no mac80211/ath9k)"\n'
            "config --enable CONFIG_WIRELESS\n"
            "config --enable CONFIG_CFG80211\n"
            "config --enable CONFIG_WLAN\n"
            "config --enable CONFIG_RTL8188EU\n"
            "config --disable CONFIG_MAC80211\n"
            "config --disable CONFIG_ATH9K\n"
            "config --disable CONFIG_ATH9K_HTC\n"
        )
        s = replace_once(s, anchor, wifi + anchor, "KSU config anchor")

        # The defconfig merge has dropped injected =y lines before (run #21).
        # Re-force the final out/.config and fail the build if 8188eu is not
        # actually linked in, or if mac80211/ath9k_htc came back built-in.
        anchor2 = "make $BUILD_FLAGS $KERNEL_DEFCONFIG\n"
        fixup = (
            'if [ -f drivers/net/wireless/rtl8188eus/Makefile ]; then # nethunter\n'
            '  log "Re-forcing rtl8188eus configs into final .config"\n'
            '  ./scripts/config --file out/.config \\\n'
            '    --enable CONFIG_WIRELESS \\\n'
            '    --enable CONFIG_CFG80211 \\\n'
            '    --enable CONFIG_WLAN \\\n'
            '    --enable CONFIG_RTL8188EU \\\n'
            '    --disable CONFIG_MAC80211 \\\n'
            '    --disable CONFIG_ATH9K \\\n'
            '    --disable CONFIG_ATH9K_HTC\n'
            '  make $BUILD_FLAGS olddefconfig\n'
            '  grep -q "^CONFIG_CFG80211=y" out/.config || '
            '{ log "FATAL: CONFIG_CFG80211 did not stick"; exit 1; }\n'
            '  grep -q "^CONFIG_RTL8188EU=y" out/.config || '
            '{ log "FATAL: CONFIG_RTL8188EU did not stick"; exit 1; }\n'
            '  if grep -q "^CONFIG_MAC80211=y" out/.config || '
            'grep -q "^CONFIG_ATH9K_HTC=y" out/.config; then\n'
            '    log "FATAL: mac80211/ath9k_htc built-in (bootloops rock)"\n'
            '    exit 1\n'
            '  fi\n'
            '  log "rtl8188eus config confirmed:"\n'
            '  grep -E "^CONFIG_(CFG80211|WLAN|RTL8188EU|MAC80211|ATH9K)=" out/.config || true\n'
            'fi\n'
        )
        s = replace_once(s, anchor2, anchor2 + fixup, "defconfig merge fixup")

        anchor3 = "make $BUILD_FLAGS Image modules\n"
        linked = (
            anchor3
            + 'if [ -f drivers/net/wireless/rtl8188eus/Makefile ]; then\n'
            + '  log "Checking rtl8188eus is linked into vmlinux"\n'
            + '  llvm-nm out/vmlinux | grep -q rtw_drv_entry || '
            + '{ log "FATAL: rtw_drv_entry missing from vmlinux"; exit 1; }\n'
            + 'fi\n'
        )
        s = replace_once(s, anchor3, linked, "vmlinux link check")

    p.write_text(s)

    # ---- functions.sh -----------------------------------------------------
    p = root / "functions.sh"
    s = p.read_text()

    old = 'bash ksu_setup.sh "$REF"'
    # setup.sh clones into KernelSU-Next (repo name); pin whatever dir it
    # actually created so the KSU checkout is reproducible.
    s = replace_once(
        s,
        old,
        old
        + '\n  for KSUD in KernelSU-Next KernelSU; do\n'
        + '    if [[ -d $KSUD/.git ]]; then\n'
        + f'      git -C $KSUD checkout -q {args.ksu_pin} 2>/dev/null || '
        + f'{{ git -C $KSUD fetch -q origin {args.ksu_pin}; '
        + 'git -C $KSUD checkout -q FETCH_HEAD; }\n'
        + '    fi\n'
        + '  done',
        "ksu setup call",
    )

    for name in ("upload_file", "reply_file", "send_msg", "reply_msg"):
        start = s.index(f"{name}() {{")
        end = s.index("\n}", start) + 2
        s = (
            s[:start]
            + f"{name}() {{ :; }}  # disabled (no Telegram secrets on fork)"
            + s[end:]
        )
    p.write_text(s)

    print(f"builder prepared for rock ({args.variant} variant)")


if __name__ == "__main__":
    main()
