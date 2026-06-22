"""
ui/master_password_dialog.py
Prompt for / set up the master password used to derive the encryption key
for stored credentials.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDialogButtonBox, QLabel, QMessageBox
)

from core.crypto import Vault
from db.models import AppMeta


class MasterPasswordDialog(QDialog):
    """
    On first run (or first use of a new vault file): ask the user to set a
    master password (stores its hash in AppMeta).
    On subsequent runs: ask for the password and verify against stored hash.
    Returns self.password on accept.
    """

    def __init__(self, db_session, salt_path, parent=None):
        super().__init__(parent)
        self.db = db_session
        self.salt_path = salt_path
        self.password = None

        self.meta = self.db.query(AppMeta).filter(AppMeta.key == "master_password_hash").first()
        first_run = self.meta is None

        self.setWindowTitle("Set Master Password" if first_run else "Unlock Vault")
        self.first_run = first_run

        layout = QVBoxLayout(self)

        if first_run:
            layout.addWidget(QLabel(
                "Create a master password to encrypt your saved SSH credentials.\n"
                "This password is NOT stored anywhere -- if you forget it, you\n"
                "will need to re-enter your saved passwords/keys.\n\n"
                "If you received this vault file from someone else, ask them\n"
                "for the password they set."
            ))
        else:
            layout.addWidget(QLabel("Enter the master password to unlock this vault."))

        form = QFormLayout()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Password:", self.password_edit)

        if first_run:
            self.confirm_edit = QLineEdit()
            self.confirm_edit.setEchoMode(QLineEdit.Password)
            form.addRow("Confirm:", self.confirm_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        pw = self.password_edit.text()
        if not pw:
            QMessageBox.warning(self, "Error", "Password cannot be empty.")
            return

        if self.first_run:
            confirm = self.confirm_edit.text()
            if pw != confirm:
                QMessageBox.warning(self, "Error", "Passwords do not match.")
                return
            pw_hash = Vault.hash_master_password(pw, self.salt_path)
            meta = AppMeta(key="master_password_hash", value=pw_hash)
            self.db.add(meta)
            self.db.commit()
        else:
            if not Vault.verify_master_password(pw, self.meta.value, self.salt_path):
                QMessageBox.warning(self, "Error", "Incorrect master password.")
                return

        self.password = pw
        self.accept()
