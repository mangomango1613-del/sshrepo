"""
ui/sftp_browser.py
SFTP file browser "pane": lists a remote directory, supports navigation,
upload/download, mkdir/rename/delete/chmod, and (new) transferring selected
items directly to another SFTPBrowser pane (remote -> remote), all without
blocking the UI thread.

Each blocking SFTP call runs via ui.progress.run_with_progress, which moves
the work to a background QThread and shows a small modal progress dialog.
"""

import os
import stat as statmod
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QFileDialog, QMessageBox, QHeaderView,
    QInputDialog, QLabel, QMenu
)

from ui.progress import run_with_progress


# Extensions we'll offer to open in the text editor (covers common config,
# code, and script files). Anything else falls back to download/binary.
TEXT_EXTENSIONS = {
    ".txt", ".md", ".log", ".conf", ".cfg", ".ini", ".yaml", ".yml",
    ".json", ".xml", ".toml", ".env", ".ini", ".service", ".sh", ".bash",
    ".zsh", ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss",
    ".php", ".rb", ".go", ".rs", ".c", ".h", ".cpp", ".hpp", ".java", ".sql",
    ".gitignore", ".dockerfile", ".nginx", ".htaccess",
}


def _is_probably_text(filename):
    name = filename.lower()
    _, ext = os.path.splitext(name)
    if ext in TEXT_EXTENSIONS:
        return True
    if name in ("dockerfile", "makefile", "readme", "license"):
        return True
    if "." not in name:
        return True  # extensionless config files are common (e.g. "hosts")
    return False


def _human_size(num_bytes):
    if num_bytes is None:
        return ""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.0f} {unit}" if unit == "B" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} PB"


# Color-code entries by type/extension, similar to `ls --color` / modern
# file managers, so directory contents are scannable at a glance.
_COLOR_DIR = "#4fc1ff"          # directories - bright blue
_COLOR_EXECUTABLE = "#89e051"   # executable bit set - green
_COLOR_SYMLINK = "#56c7e0"      # symlinks - cyan
_COLOR_ARCHIVE = "#e0a256"      # archives - orange
_COLOR_CODE = "#dcdcaa"         # source/script files - yellow
_COLOR_CONFIG = "#c586c0"       # config/markup - purple/pink
_COLOR_IMAGE = "#ce9178"        # images/media - tan
_COLOR_DEFAULT = "#d4d4d4"      # everything else - default text

_ARCHIVE_EXT = {".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".tgz"}
_CODE_EXT = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".c", ".h",
             ".cpp", ".hpp", ".java", ".rb", ".php", ".sh", ".bash", ".zsh",
             ".sql", ".pl"}
_CONFIG_EXT = {".conf", ".cfg", ".ini", ".yaml", ".yml", ".json", ".xml",
                ".toml", ".env", ".html", ".css", ".scss", ".md"}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico",
               ".mp4", ".mp3", ".wav", ".mov", ".avi"}


def _color_for_entry(entry):
    if entry["is_dir"]:
        return _COLOR_DIR
    if statmod.S_ISLNK(entry.get("mode", 0)):
        return _COLOR_SYMLINK
    name = entry["name"].lower()
    _, ext = os.path.splitext(name)
    if entry.get("mode", 0) & 0o111:  # any execute bit
        return _COLOR_EXECUTABLE
    if ext in _ARCHIVE_EXT:
        return _COLOR_ARCHIVE
    if ext in _CODE_EXT:
        return _COLOR_CODE
    if ext in _CONFIG_EXT:
        return _COLOR_CONFIG
    if ext in _IMAGE_EXT:
        return _COLOR_IMAGE
    return _COLOR_DEFAULT


class SFTPBrowser(QWidget):
    # Emitted when the user wants to open a remote text file for editing.
    # Args: (display_title, content_str, save_callback)
    # save_callback(new_content_str) writes the file back over SFTP.
    edit_file_requested = Signal(str, str, object)

    def __init__(self, sftp_manager, title="SFTP", parent=None):
        super().__init__(parent)
        self.sftp = sftp_manager
        self.current_path = "."
        self._workers = []  # keep references to background threads alive

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title_label = QLabel(f"<b>{title}</b>")
        title_label.setStyleSheet("color: #9cdcfe; padding: 2px 0;")
        layout.addWidget(title_label)

        toolbar = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.returnPressed.connect(self._on_path_entered)
        up_btn = QPushButton("\u2191 Up")
        up_btn.clicked.connect(self._go_up)
        refresh_btn = QPushButton("\u27f3 Refresh")
        refresh_btn.clicked.connect(self.refresh)
        upload_btn = QPushButton("Upload")
        upload_btn.clicked.connect(self._upload_file)
        upload_dir_btn = QPushButton("Upload Folder")
        upload_dir_btn.clicked.connect(self._upload_dir)
        mkdir_btn = QPushButton("New Folder")
        mkdir_btn.clicked.connect(self._mkdir)

        toolbar.addWidget(self.path_edit)
        toolbar.addWidget(up_btn)
        toolbar.addWidget(refresh_btn)
        toolbar.addWidget(upload_btn)
        toolbar.addWidget(upload_dir_btn)
        toolbar.addWidget(mkdir_btn)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Size", "Modified", "Type"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.itemDoubleClicked.connect(self._on_double_click)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #8a8a8a; font-size: 11px;")
        layout.addWidget(self.status_label)

        # Will be set by the dual-pane container so "Send to other pane"
        # actions are available.
        self.peer = None

        try:
            self.current_path = self.sftp.getcwd()
        except Exception:
            self.current_path = "."
        self.refresh()

    # --- background-task helper ---

    def _run_bg(self, label, fn, on_success=None, on_error=None, *args, **kwargs):
        def _ok(result):
            if on_success:
                on_success(result)

        def _err(msg):
            if on_error:
                on_error(msg)
            else:
                QMessageBox.warning(self, "Error", msg)

        worker = run_with_progress(self, label, fn, _ok, _err, *args, **kwargs)
        self._workers.append(worker)
        # drop reference once finished to avoid unbounded growth
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)

    # --- navigation / listing ---

    def refresh(self):
        self.path_edit.setText(self.current_path)
        self.status_label.setText("Loading...")

        def list_dir():
            return self.sftp.listdir(self.current_path)

        def on_done(entries):
            self.table.setRowCount(0)
            for entry in entries:
                row = self.table.rowCount()
                self.table.insertRow(row)
                color = QColor(_color_for_entry(entry))

                name_item = QTableWidgetItem(entry["name"])
                name_item.setForeground(color)
                self.table.setItem(row, 0, name_item)

                size_str = "" if entry["is_dir"] else _human_size(entry["size"])
                size_item = QTableWidgetItem(size_str)
                size_item.setForeground(color)
                self.table.setItem(row, 1, size_item)

                mtime = datetime.fromtimestamp(entry["mtime"]).strftime("%Y-%m-%d %H:%M")
                mtime_item = QTableWidgetItem(mtime)
                mtime_item.setForeground(color)
                self.table.setItem(row, 2, mtime_item)

                type_str = "Folder" if entry["is_dir"] else "File"
                type_item = QTableWidgetItem(type_str)
                type_item.setForeground(color)
                self.table.setItem(row, 3, type_item)

                self.table.item(row, 0).setData(Qt.UserRole, entry)
            self.status_label.setText(f"{len(entries)} item(s)  -  {self.current_path}")

        def on_err(msg):
            self.status_label.setText("Error")
            QMessageBox.warning(self, "SFTP Error", msg)

        self._run_bg("Loading directory...", list_dir, on_done, on_err)

    def _join(self, name):
        base = self.current_path.rstrip("/")
        return f"{base}/{name}" if base else name

    def _on_path_entered(self):
        self.current_path = self.path_edit.text().strip() or "."
        self.refresh()

    def _go_up(self):
        if self.current_path in (".", "/", ""):
            return
        parent = "/".join(self.current_path.rstrip("/").split("/")[:-1])
        self.current_path = parent if parent else "/"
        self.refresh()

    def _on_double_click(self, item):
        row = item.row()
        entry = self.table.item(row, 0).data(Qt.UserRole)
        if entry["is_dir"]:
            self.current_path = self._join(entry["name"])
            self.refresh()
        else:
            remote_path = self._join(entry["name"])
            if _is_probably_text(entry["name"]) and entry["size"] <= 2 * 1024 * 1024:
                self._edit_file(remote_path, entry)
            else:
                self._download(remote_path, entry, is_dir=False)

    def _edit_file(self, remote_path, entry):
        """Read a small text file over SFTP and emit edit_file_requested so
        the main window can open it in a CodeEditor tab."""

        def task():
            with self.sftp.sftp.open(remote_path, "r") as f:
                data = f.read()
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")
            return data

        def on_done(content):
            def save_callback(new_content):
                self._write_file(remote_path, new_content)

            title = f"{entry['name']}"
            self.edit_file_requested.emit(title, content, save_callback)

        self._run_bg(f"Opening {entry['name']}...", task, on_done)

    def _write_file(self, remote_path, content):
        def task():
            with self.sftp.sftp.open(remote_path, "w") as f:
                f.write(content)

        def on_done(_):
            QMessageBox.information(self, "Saved", f"Saved {remote_path}")

        self._run_bg(f"Saving {remote_path}...", task, on_done)

    def _selected_entries(self):
        rows = sorted(set(i.row() for i in self.table.selectedItems()))
        return [self.table.item(r, 0).data(Qt.UserRole) for r in rows]

    def _selected_entry(self):
        entries = self._selected_entries()
        return entries[0] if entries else None

    # --- context menu ---

    def _show_context_menu(self, pos):
        entries = self._selected_entries()
        menu = QMenu(self)

        if entries:
            if len(entries) == 1:
                entry = entries[0]
                remote_path = self._join(entry["name"])
                if entry["is_dir"]:
                    menu.addAction("Download Folder", lambda: self._download(remote_path, entry, is_dir=True))
                else:
                    menu.addAction("Download File", lambda: self._download(remote_path, entry, is_dir=False))
                    if _is_probably_text(entry["name"]):
                        menu.addAction("Edit", lambda: self._edit_file(remote_path, entry))
                menu.addAction("Rename", lambda: self._rename(remote_path, entry))
                menu.addAction("Change Permissions", lambda: self._chmod(remote_path, entry))
                menu.addSeparator()

            if self.peer is not None:
                arrow = "\u2192"
                menu.addAction(f"Send {arrow} other pane", self._send_to_peer)
                menu.addSeparator()

            menu.addAction("Delete Selected", self._delete_selected)

        menu.addSeparator()
        menu.addAction("New Folder", self._mkdir)
        menu.addAction("Refresh", self.refresh)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # --- local upload / download ---

    def _upload_file(self):
        local_path, _ = QFileDialog.getOpenFileName(self, "Select file to upload")
        if not local_path:
            return
        remote_path = self._join(os.path.basename(local_path))

        def task():
            self.sftp.upload_file(local_path, remote_path)

        self._run_bg(f"Uploading {os.path.basename(local_path)}...", task, lambda _: self.refresh())

    def _upload_dir(self):
        local_dir = QFileDialog.getExistingDirectory(self, "Select folder to upload")
        if not local_dir:
            return
        remote_path = self._join(os.path.basename(local_dir.rstrip("/")))

        def task():
            self.sftp.upload_dir(local_dir, remote_path)

        self._run_bg("Uploading folder...", task, lambda _: self.refresh())

    def _download(self, remote_path, entry, is_dir):
        if is_dir:
            local_dir = QFileDialog.getExistingDirectory(self, "Select destination folder")
            if not local_dir:
                return
            dest = os.path.join(local_dir, entry["name"])

            def task():
                self.sftp.download_dir(remote_path, dest)

            self._run_bg(f"Downloading {entry['name']}/...", task)
        else:
            local_path, _ = QFileDialog.getSaveFileName(self, "Save As", entry["name"])
            if not local_path:
                return

            def task():
                self.sftp.download_file(remote_path, local_path)

            self._run_bg(f"Downloading {entry['name']}...", task)

    # --- remote -> remote transfer to peer pane ---

    def _send_to_peer(self):
        if self.peer is None:
            return
        entries = self._selected_entries()
        if not entries:
            return

        dest_dir = self.peer.current_path

        def task():
            for entry in entries:
                src_path = self._join(entry["name"])
                dst_path = f"{dest_dir.rstrip('/')}/{entry['name']}"
                if entry["is_dir"]:
                    self.sftp.transfer_dir_to(src_path, self.peer.sftp, dst_path)
                else:
                    self.sftp.transfer_to(src_path, self.peer.sftp, dst_path)

        names = ", ".join(e["name"] for e in entries)
        self._run_bg(f"Transferring {names}...", task, lambda _: self.peer.refresh())

    # --- mkdir / rename / delete / chmod ---

    def _rename(self, remote_path, entry):
        new_name, ok = QInputDialog.getText(self, "Rename", "New name:", text=entry["name"])
        if ok and new_name:
            new_path = self._join(new_name)

            def task():
                self.sftp.rename(remote_path, new_path)

            self._run_bg("Renaming...", task, lambda _: self.refresh())

    def _delete_selected(self):
        entries = self._selected_entries()
        if not entries:
            return
        names = ", ".join(e["name"] for e in entries)
        confirm = QMessageBox.question(
            self, "Delete", f"Delete {len(entries)} item(s)?\n{names}",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        def task():
            for entry in entries:
                path = self._join(entry["name"])
                if entry["is_dir"]:
                    self._rmdir_recursive(path)
                else:
                    self.sftp.remove(path)

        self._run_bg("Deleting...", task, lambda _: self.refresh())

    def _rmdir_recursive(self, path):
        for entry in self.sftp.listdir(path):
            sub = f"{path.rstrip('/')}/{entry['name']}"
            if entry["is_dir"]:
                self._rmdir_recursive(sub)
            else:
                self.sftp.remove(sub)
        self.sftp.rmdir(path)

    def _chmod(self, remote_path, entry):
        current_mode = statmod.S_IMODE(entry["mode"])
        mode_str, ok = QInputDialog.getText(
            self, "Change Permissions", "Octal mode (e.g. 755):", text=oct(current_mode)[-3:]
        )
        if ok and mode_str:
            def task():
                self.sftp.chmod(remote_path, int(mode_str, 8))

            self._run_bg("Updating permissions...", task, lambda _: self.refresh())

    def _mkdir(self):
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name:
            path = self._join(name)

            def task():
                self.sftp.mkdir(path)

            self._run_bg("Creating folder...", task, lambda _: self.refresh())

    def set_focus(self):
        self.table.setFocus()
