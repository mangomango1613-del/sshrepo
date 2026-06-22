#!/usr/bin/env python3
"""
tools/download_busybox.py

Downloads BusyBox-w32 into bundled_env/ so Nuitka/PyInstaller can include
it in the exe as a data file. Run this ONCE before building the exe.

Usage:
    python tools/download_busybox.py

BusyBox-w32 provides 300+ Unix commands (ls, grep, ssh, vi, awk, sed, find,
tar, wget, ping, nc, ...) in a single ~1.2MB exe. This is what gives our
app its MobaXterm-style local terminal — no Git Bash, WSL, or Cygwin needed.

License: BusyBox is GPL-2.0. By bundling it you must make source available
to users on request. The source is at https://frippery.org/busybox/ and the
upstream BusyBox project at https://busybox.net/. This is permissible for
distribution — MobaXterm, various Windows terminal tools, and Vagrant all
bundle BusyBox-w32.
"""

import os
import sys
import urllib.request
import hashlib
from pathlib import Path

BUSYBOX_URL = "https://frippery.org/files/busybox/busybox64.exe"
# SHA256 of a known-good release - update if upstream changes
# We verify the download to protect against MITM attacks on the exe.
BUSYBOX_SHA256 = None  # Set to None to skip verification (first run)

OUT_DIR = Path(__file__).parent.parent / "bundled_env"
OUT_FILE = OUT_DIR / "busybox.exe"


def download(url: str, dest: Path, sha256: str = None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    print(f"Downloading {url}")
    print(f"  → {dest}")

    downloaded = [0]
    last_pct = [-1]

    def progress(count, block, total):
        downloaded[0] = min(count * block, total)
        if total > 0:
            pct = int(downloaded[0] * 100 / total)
            if pct != last_pct[0] and pct % 10 == 0:
                print(f"  {pct}%  ({downloaded[0]//1024} KB / {total//1024} KB)")
                last_pct[0] = pct

    try:
        urllib.request.urlretrieve(url, str(tmp), reporthook=progress)
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        print(f"ERROR: Download failed: {e}")
        sys.exit(1)

    if sha256:
        digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
        if digest != sha256:
            tmp.unlink()
            print(f"ERROR: SHA256 mismatch! Expected {sha256}, got {digest}")
            sys.exit(1)
        print(f"  SHA256 verified ✓")

    tmp.replace(dest)
    size_kb = dest.stat().st_size // 1024
    print(f"  Done: {dest.name} ({size_kb} KB)")


def main():
    if OUT_FILE.exists():
        size_kb = OUT_FILE.stat().st_size // 1024
        print(f"BusyBox already downloaded: {OUT_FILE} ({size_kb} KB)")
        print("Delete it and re-run to refresh.")
        return

    download(BUSYBOX_URL, OUT_FILE, BUSYBOX_SHA256)
    print()
    print("BusyBox is ready to bundle.")
    print("Now run build_nuitka.bat (or build_nuitka.sh) to build the exe.")
    print("The bundled_env/ directory will be included automatically.")


if __name__ == "__main__":
    main()
