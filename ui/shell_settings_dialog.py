"""
ui/shell_settings_dialog.py

Local terminal shell settings dialog.
On Windows: shows BusyBox bundled environment status, download button,
OpenSSH detection, and optional shell override.
On Linux/macOS: simple shell picker.

This is the equivalent of MobaXterm's "Local terminal" settings panel.
"""

import json
import os

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QDialogButtonBox,
    QGroupBox, QFormLayout, QPushButton, QProgressBar, QMessageBox, QWidget
)

from db.models import AppMeta
from core.local_session import get_local_shell_argv

APP_META_KEY_SHELL = "local_shell_argv"


def load_shell_argv(db_session):
    """
    Return the saved shell argv, or None if nothing is saved OR the saved
    executable no longer exists on disk (e.g. BusyBox was deleted by
    antivirus, or the user uninstalled WSL/Git Bash since saving).
    Validating here prevents the app from trying to launch a shell that
    no longer exists and crashing with a cryptic error.
    """
    import os
    meta = db_session.query(AppMeta).filter(AppMeta.key == APP_META_KEY_SHELL).first()
    if meta and meta.value:
        try:
            argv = json.loads(meta.value)
            if isinstance(argv, list) and argv:
                exe = argv[0]
                # wsl.exe / cmd.exe / powershell.exe are resolved via PATH
                # at launch time, not a fixed path - always trust those.
                # Anything else (BusyBox, Git Bash, MSYS2) must exist now.
                if exe.lower() in ("wsl.exe", "wsl", "cmd.exe", "powershell.exe", "pwsh.exe"):
                    return argv
                if os.path.isfile(exe):
                    return argv
                # Saved shell no longer exists - forget it so we fall back
                # to auto-detection instead of repeatedly failing.
                return None
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def save_shell_argv(db_session, argv):
    meta = db_session.query(AppMeta).filter(AppMeta.key == APP_META_KEY_SHELL).first()
    if not meta:
        meta = AppMeta(key=APP_META_KEY_SHELL, value="")
        db_session.add(meta)
    meta.value = json.dumps(argv) if argv else ""
    db_session.commit()


def get_shell_argv(db_session):
    """Return the effective shell argv (saved or auto-detected)."""
    return get_local_shell_argv(db_session)


class DownloadWorker(QThread):
    progress = Signal(int, int)   # downloaded, total
    finished = Signal(str)        # busybox path
    error = Signal(str)

    def run(self):
        try:
            from core.bundled_env import ensure_busybox
            path = ensure_busybox(
                progress_callback=lambda d, t: self.progress.emit(d, t)
            )
            self.finished.emit(str(path))
        except Exception as e:
            self.error.emit(str(e))


class ShellSettingsDialog(QDialog):
    def __init__(self, db_session, parent=None):
        super().__init__(parent)
        self.db = db_session
        self.setWindowTitle("Local Terminal Settings")
        self.setMinimumWidth(500)
        self._worker = None

        layout = QVBoxLayout(self)

        if os.name == "nt":
            layout.addWidget(self._build_windows_panel())
        else:
            layout.addWidget(self._build_unix_panel())

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ---------------------------------------------------------------- Windows

    def _build_windows_panel(self):
        from core.bundled_env import environment_status
        status = environment_status()

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- BusyBox status ---
        bb_box = QGroupBox("Bundled Unix Environment (BusyBox)")
        bb_layout = QFormLayout(bb_box)

        if status["busybox_available"]:
            bb_status = QLabel(
                f"✅  Ready  ({status['busybox_size_kb']} KB)\n"
                f"    {status['busybox_path']}"
            )
            bb_status.setStyleSheet("color: #3fb950;")
        else:
            bb_status = QLabel(
                "⚠  Not downloaded yet.\n"
                "   Download once (~1.2 MB) to get ls, grep, cat, find,\n"
                "   vi, ssh, and 300+ Unix commands — no install required."
            )
            bb_status.setStyleSheet("color: #d7ba00;")

        bb_layout.addRow("Status:", bb_status)

        # Download button + progress bar
        dl_row = QHBoxLayout()
        self.dl_btn = QPushButton(
            "Re-download" if status["busybox_available"] else "Download BusyBox (1.2 MB)"
        )
        self.dl_btn.setObjectName("PrimaryButton")
        self.dl_btn.clicked.connect(self._download_busybox)
        dl_row.addWidget(self.dl_btn)
        dl_row.addStretch()
        bb_layout.addRow(dl_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        bb_layout.addRow(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #8a8a8a; font-size: 11px;")
        bb_layout.addRow(self.status_label)

        layout.addWidget(bb_box)

        # --- OpenSSH status ---
        ssh_box = QGroupBox("SSH Client")
        ssh_layout = QFormLayout(ssh_box)

        if status["ssh_available"]:
            ssh_lbl = QLabel(f"✅  Found: {status['ssh_path']}")
            ssh_lbl.setStyleSheet("color: #3fb950;")
        else:
            ssh_lbl = QLabel(
                "⚠  Not found. Enable via:\n"
                "   Settings → Apps → Optional Features → Add → OpenSSH Client"
            )
            ssh_lbl.setStyleSheet("color: #d7ba00;")

        ssh_layout.addRow("Status:", ssh_lbl)
        layout.addWidget(ssh_box)

        # --- Shell override ---
        override_box = QGroupBox("Shell Override (Advanced)")
        override_layout = QFormLayout(override_box)
        override_layout.addRow(QLabel(
            "Leave at 'Auto' to use the BusyBox environment above.\n"
            "Override only if you have a specific shell preference\n"
            "(e.g. WSL, Git Bash, PowerShell)."
        ))

        self.override_combo = QComboBox()
        self.override_combo.addItem("Auto (BusyBox bundled environment)", None)
        self.override_combo.addItem("PowerShell", ["powershell.exe", "-NoLogo", "-NoExit"])
        self.override_combo.addItem("PowerShell 7 (pwsh)", ["pwsh.exe", "-NoLogo", "-NoExit"])
        self.override_combo.addItem("Command Prompt (cmd.exe)", ["cmd.exe"])

        import shutil
        for label, path in [
            ("WSL (Linux subsystem)", "wsl.exe"),
            ("Git Bash", r"C:\Program Files\Git\bin\bash.exe"),
            ("MSYS2 Bash", r"C:\msys64\usr\bin\bash.exe"),
        ]:
            resolved = shutil.which(path) or (path if os.path.isfile(os.path.expandvars(path)) else None)
            if resolved:
                argv = [resolved, "--login", "-i"] if "bash" in path.lower() else [resolved]
                self.override_combo.addItem(f"{label} ({resolved})", argv)

        current = load_shell_argv(self.db)
        if current:
            for i in range(self.override_combo.count()):
                if self.override_combo.itemData(i) == current:
                    self.override_combo.setCurrentIndex(i)
                    break

        self.override_combo.currentIndexChanged.connect(self._update_resolved_label)
        override_layout.addRow("Shell:", self.override_combo)

        self.resolved_lbl = QLabel("")
        self.resolved_lbl.setStyleSheet("color: #8a8a8a; font-size: 11px;")
        override_layout.addRow("Resolved cmd:", self.resolved_lbl)
        self._update_resolved_label()
        layout.addWidget(override_box)

        return container

    def _build_unix_panel(self):
        """Simple panel for Linux/macOS."""
        import shutil
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        box = QGroupBox("Local terminal shell")
        form = QFormLayout(box)
        form.addRow(QLabel("Choose the shell for local terminal tabs:"))

        self.unix_combo = QComboBox()
        self.unix_combo.addItem("Auto ($SHELL env var)", None)
        for shell in ["/bin/bash", "/bin/zsh", "/bin/fish", "/bin/sh", "/usr/bin/fish"]:
            if os.path.isfile(shell):
                self.unix_combo.addItem(shell, [shell])
        layout.addWidget(box)

        current = load_shell_argv(self.db)
        if current:
            for i in range(self.unix_combo.count()):
                if self.unix_combo.itemData(i) == current:
                    self.unix_combo.setCurrentIndex(i)
                    break
        return container

    def _update_resolved_label(self):
        if not hasattr(self, "resolved_lbl"):
            return
        argv = self.override_combo.currentData()
        if argv is None:
            from core.bundled_env import get_shell_argv as _bb_argv, busybox_available
            if busybox_available():
                argv = _bb_argv()
            else:
                argv = ["(BusyBox not downloaded yet)"]
        self.resolved_lbl.setText(" ".join(str(a) for a in argv))

    # ---------------------------------------------------------- download

    def _download_busybox(self):
        self.dl_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.status_label.setText("Downloading BusyBox (~1.2 MB)...")

        self._worker = DownloadWorker()
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_download_done)
        self._worker.error.connect(self._on_download_error)
        self._worker.start()

    def _on_progress(self, downloaded, total):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(downloaded)
            kb = downloaded // 1024
            self.status_label.setText(f"Downloading... {kb} KB")
        else:
            self.progress_bar.setRange(0, 0)

    def _on_download_done(self, path):
        self.progress_bar.setVisible(False)
        self.dl_btn.setEnabled(True)
        self.status_label.setText(f"✅ Downloaded: {path}")
        self.dl_btn.setText("Re-download")
        self._update_resolved_label()
        QMessageBox.information(
            self, "Ready",
            "BusyBox downloaded successfully!\n\n"
            "Your local terminal now has ls, grep, cat, find, vi, ssh,\n"
            "and 300+ Unix commands — no install required.\n\n"
            "Open a new local terminal tab to start using it."
        )

    def _on_download_error(self, msg):
        self.progress_bar.setVisible(False)
        self.dl_btn.setEnabled(True)
        self.status_label.setText(f"Download failed: {msg}")
        QMessageBox.critical(
            self, "Download Failed",
            f"Could not download BusyBox:\n{msg}\n\n"
            "Check your internet connection and try again."
        )

    # ----------------------------------------------------------------- save

    def _on_save(self):
        if os.name == "nt":
            argv = self.override_combo.currentData()
        else:
            argv = self.unix_combo.currentData()

        save_shell_argv(self.db, argv)
        self.accept()