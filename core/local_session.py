"""
core/local_session.py

A local terminal session that gives the user a real Unix-like shell
on Windows — identical in feel to MobaXterm's local terminal — without
requiring Git Bash, WSL, Cygwin, or any other install.

How it works on Windows:
  - Uses BusyBox-w32 (bundled, ~1.2MB, downloaded once on first launch)
    as the shell. BusyBox provides sh, ls, grep, cat, awk, sed, find,
    vi, wget, ping, and 300+ other Unix commands.
  - Uses the Windows built-in OpenSSH client (ssh.exe) for SSH connections
    (already installed on Windows 10 1809+ / Windows 11 by default).
  - Sets up Cygwin-style /c/ /d/ drive paths so `cd /c/Users/Suresh`
    and `ls -la /c/Users` just work.
  - PTY support via pywinpty (bundled with Nuitka build) for full
    terminal emulation (colors, arrow keys, vim, htop, etc.)

How it works on Linux/macOS:
  - Uses the system $SHELL (bash/zsh/fish etc.) via the standard pty module.
  - No extra setup needed.

Interface: same as core.ssh_session.SSHSession (open/send/recv/
resize_pty/is_active/close) so TerminalWidget works with both.
"""

import os
import signal
import subprocess
import sys


def _is_windows() -> bool:
    return os.name == "nt"


def get_local_shell_argv(db_session=None) -> list[str]:
    """
    Determine the best shell argv for this platform.

    Priority on Windows:
      1. User-saved preference from DB (Tools → Local Shell Settings)
      2. BusyBox bundled environment (MobaXterm-style, auto-downloads 1.2MB)
      3. System OpenSSH + PowerShell fallback
      4. plain cmd.exe (last resort)

    On Linux/macOS:
      1. User-saved preference from DB
      2. $SHELL env var
      3. /bin/bash
    """
    # Check saved preference first
    if db_session is not None:
        try:
            from ui.shell_settings_dialog import load_shell_argv
            saved = load_shell_argv(db_session)
            if saved:
                return saved
        except ImportError:
            pass

    if not _is_windows():
        shell = os.environ.get("SHELL", "/bin/bash")
        return [shell]

    # Windows: try BusyBox bundled environment
    try:
        from core.bundled_env import busybox_available, get_shell_argv as _bb_argv
        if busybox_available():
            return _bb_argv()
    except (ImportError, RuntimeError):
        pass

    # Fallback chain for Windows
    import shutil
    fallbacks = [
        ["powershell.exe", "-NoLogo", "-NoExit"],
        ["pwsh.exe", "-NoLogo", "-NoExit"],
        [os.environ.get("COMSPEC", "cmd.exe")],
    ]
    for argv in fallbacks:
        if shutil.which(argv[0]):
            return argv
    return ["cmd.exe"]


class LocalSession:
    """
    Local shell session. On Windows uses BusyBox (bundled, MobaXterm-style).
    On Linux/macOS uses the system $SHELL via pty.
    Exposes the same interface as SSHSession so TerminalWidget works with both.
    """

    def __init__(self, shell_argv: list[str] = None, db_session=None):
        self.shell_argv = shell_argv or get_local_shell_argv(db_session)
        self._closed = False

        # Unix pty state
        self._master_fd = None
        self._pid = None

        # Windows winpty state
        self._winpty = None
        self._proc = None

    # ------------------------------------------------------------------ open

    def open(self, term: str = "xterm-256color", width: int = 80, height: int = 24):
        env = dict(os.environ)
        env["TERM"] = term
        env.setdefault("LANG", "en_US.UTF-8")

        if _is_windows():
            self._open_windows(env, width, height)
        else:
            self._open_unix(env, width, height)

    def _open_unix(self, env, width, height):
        import pty
        pid, master_fd = pty.fork()
        if pid == 0:
            # Child: exec the shell
            try:
                os.execvpe(self.shell_argv[0], self.shell_argv, env)
            except Exception:
                pass
            os._exit(1)
        self._pid = pid
        self._master_fd = master_fd
        self._set_pty_size(width, height)

    def _set_pty_size(self, width, height):
        if self._master_fd is None:
            return
        import fcntl, struct, termios
        fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ,
                    struct.pack("HHHH", height, width, 0, 0))

    def _open_windows(self, env, width, height):
        # pywinpty gives us a real Windows Console PTY - full ANSI/color
        # support, arrow keys, vim, etc. (same as what Windows Terminal uses)
        try:
            from winpty import PtyProcess
            cmdline = " ".join(
                f'"{a}"' if " " in a else a for a in self.shell_argv
            )
            self._winpty = PtyProcess.spawn(
                cmdline, dimensions=(height, width), env=env
            )
            return
        except ImportError:
            pass

        # Fallback: subprocess pipe (no full PTY, limited interactivity)
        self._proc = subprocess.Popen(
            self.shell_argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            bufsize=0,
        )

    # ------------------------------------------------------------------ I/O

    def send(self, data: bytes):
        if self._winpty:
            try:
                self._winpty.write(data.decode("utf-8", errors="replace"))
            except Exception:
                pass
        elif self._proc:
            try:
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
            except Exception:
                pass
        elif self._master_fd is not None:
            try:
                os.write(self._master_fd, data)
            except OSError:
                pass

    def recv(self, nbytes: int = 4096) -> bytes:
        if self._winpty:
            try:
                if self._winpty.isalive():
                    data = self._winpty.read(nbytes)
                    if isinstance(data, str):
                        return data.encode("utf-8", errors="replace")
                    return data
            except Exception:
                pass
            return b""

        if self._proc:
            try:
                import select
                r, _, _ = select.select([self._proc.stdout], [], [], 0)
                if r:
                    return self._proc.stdout.read1(nbytes)
            except Exception:
                pass
            return b""

        if self._master_fd is not None:
            try:
                import select
                r, _, _ = select.select([self._master_fd], [], [], 0)
                if r:
                    return os.read(self._master_fd, nbytes)
            except OSError:
                pass
        return b""

    def resize_pty(self, width: int, height: int):
        if self._winpty:
            try:
                self._winpty.setwinsize(height, width)
            except Exception:
                pass
        elif self._master_fd is not None:
            self._set_pty_size(width, height)

    # ---------------------------------------------------------------- status

    def is_active(self) -> bool:
        if self._closed:
            return False
        if self._winpty:
            return self._winpty.isalive()
        if self._proc:
            return self._proc.poll() is None
        if self._master_fd is not None and self._pid is not None:
            try:
                pid, _ = os.waitpid(self._pid, os.WNOHANG)
                return pid == 0
            except ChildProcessError:
                return False
        return False

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._winpty:
            try:
                self._winpty.close()
            except Exception:
                pass
        elif self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass
        elif self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            if self._pid:
                try:
                    os.kill(self._pid, signal.SIGHUP)
                except ProcessLookupError:
                    pass

    # ------------------------------------------------- SSHSession shims

    def get_transport(self, hop_index=-1):
        return None

    def hop_count(self) -> int:
        return 1

    def open_sftp(self):
        raise NotImplementedError("Local sessions do not support SFTP")
