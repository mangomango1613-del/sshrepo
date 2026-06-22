"""
core/bundled_env.py

Manages the bundled BusyBox Unix environment for Windows local terminals.

BusyBox-w32 provides 300+ Unix commands (ls, grep, ssh, cat, awk, sed,
find, vi, wget, ping, nc, tar, gzip, ...) in a single ~1.2MB exe.
It's bundled directly into our application so users get a MobaXterm-style
local terminal with zero additional install requirements.

Location priority (where we look for busybox.exe):
  1. <exe_dir>/bundled_env/busybox.exe        ← Nuitka bundle (primary)
  2. <exe_dir>/busybox.exe                    ← flat layout fallback
  3. %APPDATA%/PyTermSSH/env/busybox.exe      ← runtime download cache

The first two are populated at build time by tools/download_busybox.py
and included via Nuitka's --include-data-dir flag in build_nuitka.bat.

For users running from source (python main.py), BusyBox is downloaded
on first use into %APPDATA%/PyTermSSH/env/ and cached there permanently.
"""

import os
import sys
import shutil
import urllib.request
from pathlib import Path


BUSYBOX_URL = "https://frippery.org/files/busybox/busybox64.exe"
BUSYBOX_FILENAME = "busybox.exe"
OPENSSH_DIRS = [
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "OpenSSH"),
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "OpenSSH"),
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "OpenSSH-Win64"),
]


def _exe_dir() -> Path:
    """Directory containing our executable (or main.py when running from source)."""
    if getattr(sys, "frozen", False):
        # Nuitka/PyInstaller: sys.executable is the .exe
        return Path(sys.executable).parent
    # Running from source
    return Path(__file__).parent.parent


def _appdata_env_dir() -> Path:
    base = os.environ.get("APPDATA", os.path.expanduser("~"))
    path = Path(base) / "PyTermSSH" / "env"
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_busybox() -> Path | None:
    """
    Find busybox.exe. Checks bundled locations first (exe dir), then the
    user's AppData cache. Returns None if not found anywhere.
    """
    candidates = [
        _exe_dir() / "bundled_env" / BUSYBOX_FILENAME,
        _exe_dir() / BUSYBOX_FILENAME,
        _appdata_env_dir() / BUSYBOX_FILENAME,
    ]
    for p in candidates:
        if p.exists() and p.stat().st_size > 100_000:
            return p
    return None


def busybox_available() -> bool:
    return find_busybox() is not None


def get_openssh_path() -> str | None:
    """Find ssh.exe on Windows (built-in OpenSSH client)."""
    for d in OPENSSH_DIRS:
        p = Path(d) / "ssh.exe"
        if p.exists():
            return str(p)
    return shutil.which("ssh.exe") or shutil.which("ssh")


def ensure_busybox(progress_callback=None) -> Path:
    """
    Ensure busybox.exe is available. If not bundled, downloads it to the
    AppData cache (~1.2 MB, one-time). Returns the path.
    """
    existing = find_busybox()
    if existing:
        return existing

    dest = _appdata_env_dir() / BUSYBOX_FILENAME
    tmp = dest.with_suffix(".tmp")

    def _hook(count, block, total):
        if progress_callback and total > 0:
            progress_callback(min(count * block, total), total)

    try:
        urllib.request.urlretrieve(BUSYBOX_URL, str(tmp), reporthook=_hook)
        tmp.replace(dest)
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"Failed to download BusyBox: {e}") from e

    return dest


def _write_profile(env_dir: Path, bb_path: Path, ssh_path: str | None) -> Path:
    """
    Write a .profile that makes every BusyBox command available by name,
    sets up /c/ /d/ etc. drive aliases (Cygwin-style), and configures the
    prompt. This is sourced by `busybox sh --login`.
    """
    bb = str(bb_path).replace("\\", "/")
    userprofile = os.environ.get("USERPROFILE", r"C:\Users\User")
    unix_home = "/" + userprofile[0].lower() + userprofile[2:].replace("\\", "/")

    ssh_lines = ""
    if ssh_path:
        ssh_safe = ssh_path.replace("\\", "/")
        ssh_lines = f'alias ssh=\'"{ssh_safe}"\'\nalias scp=\'"{ssh_safe.replace("ssh.exe","scp.exe")}"\'\n'
    else:
        ssh_lines = "# OpenSSH not found. Enable via Windows Optional Features > OpenSSH Client\n"

    profile = f"""# PyTermSSH local terminal profile
export HOME="{unix_home}"
export TERM=xterm-256color
export LANG=en_US.UTF-8
export HISTFILE="$HOME/.bash_history"
export PS1='\\[\\033[1;32m\\]\\u@\\h\\[\\033[0m\\]:\\[\\033[1;34m\\]\\w\\[\\033[0m\\]\\$ '

BB="{bb}"

# Register every BusyBox applet as a shell alias so you can type
# ls, grep, cat, find, vi, wget, tar, awk, sed etc. directly.
for _cmd in $("{bb}" --list 2>/dev/null); do
    alias "$_cmd"='"{bb}" '"$_cmd"
done
unset _cmd

# Cygwin-style /c/ /d/ ... drive paths (cd /c/Users/YourName works)
for _drv in c d e f g h i j k l m n o p q r s t u v w x y z; do
    _win="${{_drv^^}}:\\\\"
    if [ -d "$_win" ] 2>/dev/null; then
        mkdir -p "/$_drv" 2>/dev/null
        # Mount via USERPROFILE-relative symlink trick is not possible in sh,
        # so we use a function that cd's properly:
        eval "$_drv () {{ cd /$_drv; }}"
    fi
done
unset _drv _win

# SSH aliases from Windows built-in OpenSSH
{ssh_lines}
cd "$HOME" 2>/dev/null || cd /

clear
printf '\\033[1;32m PyTermSSH Local Terminal\\033[0m\\n'
printf ' Shell: BusyBox sh  |  Type: ssh user@host  |  Drives: /c/ /d/ ...\\n'
printf ' Commands: ls grep cat find vi wget tar awk sed ping nc ...\\n\\n'
"""

    profile_path = env_dir / ".profile"
    profile_path.write_text(profile, encoding="utf-8")
    return profile_path


def get_shell_argv() -> list[str]:
    """
    Return the argv list for launching the BusyBox shell session.
    Raises RuntimeError if BusyBox is not available (call ensure_busybox first).
    """
    bb = find_busybox()
    if bb is None:
        raise RuntimeError("BusyBox not found. Call ensure_busybox() first.")

    env_dir = bb.parent
    ssh_path = get_openssh_path()
    _write_profile(env_dir, bb, ssh_path)

    profile = str(env_dir / ".profile").replace("\\", "/")
    # Use busybox sh with --login to source .profile
    return [str(bb), "sh", "--rcfile", str(env_dir / ".profile"), "-i"]


def get_busybox_shell_argv(env_dir=None) -> list[str]:
    """Compatibility alias used by shell_settings_dialog."""
    return get_shell_argv()


def environment_status() -> dict:
    bb = find_busybox()
    ssh = get_openssh_path()
    return {
        "busybox_available": bb is not None,
        "busybox_path": str(bb) if bb else None,
        "busybox_size_kb": int(bb.stat().st_size / 1024) if bb else 0,
        "busybox_bundled": bb is not None and bb.parent != _appdata_env_dir(),
        "ssh_available": ssh is not None,
        "ssh_path": ssh,
        "env_dir": str(bb.parent if bb else _appdata_env_dir()),
    }
