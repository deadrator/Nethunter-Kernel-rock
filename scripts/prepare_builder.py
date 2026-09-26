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
  5. build.sh: for the "nethunter" variant, inject the external Wi-Fi stack
     (cfg80211/mac80211/ath9k_htc built-in) right before the KSU/SUSFS config
     enable block, so the module symbols and CRCs land in the same kernel.
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
    s = replace_once(
        s,
        old,
        old
        + "\ngit -C $KSRC fetch -q origin "
        + args.kernel_pin
        + " && git -C $KSRC checkout -q FETCH_HEAD",
        "kernel clone pin",
    )

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
            'log "NetHunter external Wi-Fi stack: cfg80211/mac80211/ath9k_htc built-in"\n'
            "config --enable CONFIG_CFG80211\n"
            "config --enable CONFIG_MAC80211\n"
            "config --enable CONFIG_WLAN\n"
            "config --enable CONFIG_WLAN_VENDOR_ATH\n"
            "config --enable CONFIG_ATH9K_HTC\n"
        )
        s = replace_once(s, anchor, wifi + anchor, "KSU config anchor")

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
