"""
core/sftp_manager.py
SFTP file browsing and transfer operations on top of an open SSHSession.
"""

import os
import stat


class SFTPManager:
    def __init__(self, ssh_session):
        """ssh_session: an open core.ssh_session.SSHSession"""
        self.session = ssh_session
        self.sftp = ssh_session.open_sftp()

    def listdir(self, remote_path="."):
        """Return list of dicts: name, is_dir, size, mtime, mode."""
        entries = []
        for attr in self.sftp.listdir_attr(remote_path):
            entries.append({
                "name": attr.filename,
                "is_dir": stat.S_ISDIR(attr.st_mode),
                "size": attr.st_size,
                "mtime": attr.st_mtime,
                "mode": attr.st_mode,
            })
        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        return entries

    def mkdir(self, remote_path, mode=0o755):
        self.sftp.mkdir(remote_path, mode)

    def rmdir(self, remote_path):
        self.sftp.rmdir(remote_path)

    def remove(self, remote_path):
        self.sftp.remove(remote_path)

    def rename(self, old_path, new_path):
        self.sftp.rename(old_path, new_path)

    def chmod(self, remote_path, mode):
        self.sftp.chmod(remote_path, mode)

    def stat(self, remote_path):
        return self.sftp.stat(remote_path)

    def getcwd(self):
        return self.sftp.getcwd() or "."

    def chdir(self, path):
        self.sftp.chdir(path)

    def download_file(self, remote_path, local_path, progress_callback=None):
        def cb(transferred, total):
            if progress_callback:
                progress_callback(transferred, total)
        self.sftp.get(remote_path, local_path, callback=cb)

    def upload_file(self, local_path, remote_path, progress_callback=None):
        def cb(transferred, total):
            if progress_callback:
                progress_callback(transferred, total)
        self.sftp.put(local_path, remote_path, callback=cb)

    def download_dir(self, remote_dir, local_dir, progress_callback=None):
        """Recursively download a remote directory."""
        os.makedirs(local_dir, exist_ok=True)
        for entry in self.listdir(remote_dir):
            r_path = f"{remote_dir.rstrip('/')}/{entry['name']}"
            l_path = os.path.join(local_dir, entry["name"])
            if entry["is_dir"]:
                self.download_dir(r_path, l_path, progress_callback)
            else:
                self.download_file(r_path, l_path, progress_callback)

    def upload_dir(self, local_dir, remote_dir, progress_callback=None):
        """Recursively upload a local directory."""
        try:
            self.sftp.stat(remote_dir)
        except FileNotFoundError:
            self.mkdir(remote_dir)

        for item in os.listdir(local_dir):
            l_path = os.path.join(local_dir, item)
            r_path = f"{remote_dir.rstrip('/')}/{item}"
            if os.path.isdir(l_path):
                self.upload_dir(l_path, r_path, progress_callback)
            else:
                self.upload_file(l_path, r_path, progress_callback)

    def transfer_to(self, remote_path, other_manager, other_remote_path, progress_callback=None):
        """
        Stream a file from this SFTP connection to another SFTP connection
        (remote -> remote, via this process as a relay). Used for dual-pane
        "move/copy between two hosts" functionality.
        """
        total = self.stat(remote_path).st_size
        transferred = 0
        with self.sftp.open(remote_path, "rb") as src, \
                other_manager.sftp.open(other_remote_path, "wb") as dst:
            src.prefetch()
            while True:
                chunk = src.read(32768)
                if not chunk:
                    break
                dst.write(chunk)
                transferred += len(chunk)
                if progress_callback:
                    progress_callback(transferred, total)

    def transfer_dir_to(self, remote_dir, other_manager, other_remote_dir, progress_callback=None):
        """Recursively copy a remote directory to another remote host."""
        try:
            other_manager.stat(other_remote_dir)
        except (FileNotFoundError, IOError):
            other_manager.mkdir(other_remote_dir)

        for entry in self.listdir(remote_dir):
            r_path = f"{remote_dir.rstrip('/')}/{entry['name']}"
            o_path = f"{other_remote_dir.rstrip('/')}/{entry['name']}"
            if entry["is_dir"]:
                self.transfer_dir_to(r_path, other_manager, o_path, progress_callback)
            else:
                self.transfer_to(r_path, other_manager, o_path, progress_callback)

    def close(self):
        try:
            self.sftp.close()
        except Exception:
            pass
