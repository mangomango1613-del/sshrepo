"""
ui/quick_connect_dialog.py
Lightweight dialog for connecting to a host manually without saving it
to the host list (an empty/quick terminal, like typing `ssh user@host`).
"""

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QSpinBox, QComboBox, QDialogButtonBox,
    QTextEdit, QPushButton, QFileDialog, QHBoxLayout, QWidget, QVBoxLayout, QLabel
)

from core.ssh_session import HostConfig


class QuickConnectDialog(QDialog):
    """Collects connection details and returns a HostConfig via self.host_config."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quick Connect")
        self.setMinimumWidth(420)
        self.host_config = None

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.hostname_edit = QLineEdit()
        self.hostname_edit.setPlaceholderText("e.g. 192.168.1.10 or example.com")

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)

        self.username_edit = QLineEdit()

        self.auth_combo = QComboBox()
        self.auth_combo.addItems(["password", "key"])
        self.auth_combo.currentTextChanged.connect(self._toggle_auth_fields)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)

        self.key_path_edit = QLineEdit()
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_path_edit)
        key_row.addWidget(browse_btn)

        self.key_text_edit = QTextEdit()
        self.key_text_edit.setPlaceholderText("Or paste private key PEM here")
        self.key_text_edit.setFixedHeight(70)

        self.passphrase_edit = QLineEdit()
        self.passphrase_edit.setEchoMode(QLineEdit.Password)

        form.addRow("Hostname / IP:", self.hostname_edit)
        form.addRow("Port:", self.port_spin)
        form.addRow("Username:", self.username_edit)
        form.addRow("Auth Type:", self.auth_combo)
        form.addRow("Password:", self.password_edit)
        form.addRow("Private Key File:", key_row)
        form.addRow("Private Key (paste):", self.key_text_edit)
        form.addRow("Key Passphrase:", self.passphrase_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._toggle_auth_fields("password")

    def _toggle_auth_fields(self, auth_type):
        is_key = auth_type == "key"
        self.password_edit.setEnabled(not is_key)
        self.key_path_edit.setEnabled(is_key)
        self.key_text_edit.setEnabled(is_key)
        self.passphrase_edit.setEnabled(is_key)

    def _browse_key(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Private Key")
        if path:
            self.key_path_edit.setText(path)

    def _on_accept(self):
        hostname = self.hostname_edit.text().strip()
        if not hostname:
            self.hostname_edit.setFocus()
            return

        private_key_pem = None
        if self.auth_combo.currentText() == "key":
            pasted = self.key_text_edit.toPlainText().strip()
            if pasted:
                private_key_pem = pasted
            elif self.key_path_edit.text().strip():
                with open(self.key_path_edit.text().strip(), "r") as f:
                    private_key_pem = f.read()

        self.host_config = HostConfig(
            hostname=hostname,
            port=self.port_spin.value(),
            username=self.username_edit.text().strip() or None,
            password=self.password_edit.text() or None,
            private_key_pem=private_key_pem,
            passphrase=self.passphrase_edit.text() or None,
        )
        self.accept()
