"""
ui/vault_select_dialog.py
Startup dialog: choose to use the default local vault, open an existing
vault file (.zip exported by another user, or a raw .db), or create a new
vault at a custom location. This is what makes the SQLite database
"shareable" - a vault is a self-contained (db + salt) pair.
"""

import os
import shutil

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QMessageBox, QRadioButton, QButtonGroup, QLineEdit, QGroupBox
)

from db.database import (
    default_db_path, default_salt_path, salt_path_for_db, import_vault
)


class VaultSelectDialog(QDialog):
    """
    On accept, sets:
      self.db_path  - path to the sshclient.db to open
      self.salt_path - path to the matching vault.salt
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PyTermSSH - Select Vault")
        self.setMinimumWidth(480)
        self.db_path = None
        self.salt_path = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<b>Welcome to PyTermSSH</b><br>"
            "Choose how you'd like to start."
        ))

        # Option 1: default local vault
        default_box = QGroupBox("Use my local vault (recommended)")
        default_layout = QVBoxLayout(default_box)
        default_layout.addWidget(QLabel(f"Location: {default_db_path()}"))
        use_default_btn = QPushButton("Continue with Local Vault")
        use_default_btn.clicked.connect(self._use_default)
        default_layout.addWidget(use_default_btn)
        layout.addWidget(default_box)

        # Option 2: open a shared vault file (.zip)
        shared_box = QGroupBox("Open a shared vault file (.zip)")
        shared_layout = QVBoxLayout(shared_box)
        shared_layout.addWidget(QLabel(
            "Received a vault export from a teammate? Open it here.\n"
            "You'll be asked where to install it on this machine."
        ))
        open_shared_btn = QPushButton("Open Vault File...")
        open_shared_btn.clicked.connect(self._open_shared)
        shared_layout.addWidget(open_shared_btn)
        layout.addWidget(shared_box)

        # Option 3: custom location (portable mode)
        custom_box = QGroupBox("Open / create vault at a custom location")
        custom_layout = QVBoxLayout(custom_box)
        custom_layout.addWidget(QLabel(
            "Use a .db file on a USB drive, synced folder, etc."
        ))
        custom_btn = QPushButton("Choose .db Location...")
        custom_btn.clicked.connect(self._choose_custom)
        custom_layout.addWidget(custom_btn)
        layout.addWidget(custom_box)

    def _use_default(self):
        self.db_path = default_db_path()
        self.salt_path = default_salt_path()
        self.accept()

    def _open_shared(self):
        zip_path, _ = QFileDialog.getOpenFileName(
            self, "Open Vault Export", "", "Vault Files (*.zip);;All Files (*)"
        )
        if not zip_path:
            return

        dest_dir = QFileDialog.getExistingDirectory(
            self, "Choose where to install this vault on this computer"
        )
        if not dest_dir:
            return

        try:
            db_path, salt_path = import_vault(zip_path, dest_dir)
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Could not import vault:\n{e}")
            return

        if not os.path.exists(db_path):
            QMessageBox.critical(self, "Import Error", "Vault zip did not contain sshclient.db")
            return

        self.db_path = db_path
        self.salt_path = salt_path
        self.accept()

    def _choose_custom(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Choose / Create Vault Database",
            "sshclient.db", "SQLite Database (*.db)"
        )
        if not path:
            return

        self.db_path = path
        self.salt_path = salt_path_for_db(path)
        self.accept()
