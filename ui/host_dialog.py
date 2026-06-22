"""
ui/host_dialog.py
Dialog for creating/editing a Host and its associated Identity.
"""

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QSpinBox, QComboBox, QPushButton,
    QDialogButtonBox, QTextEdit, QVBoxLayout, QLabel, QFileDialog, QWidget,
    QTabWidget, QHBoxLayout, QCheckBox
)

from db.models import Host, Identity, Group


class HostDialog(QDialog):
    def __init__(self, db_session, vault, host_id=None, default_group_id=None, parent=None):
        super().__init__(parent)
        self.db = db_session
        self.vault = vault
        self.host_id = host_id
        self.setWindowTitle("Edit Host" if host_id else "New Host")
        self.setMinimumWidth(420)

        self.host = None
        self.identity = None
        if host_id:
            self.host = self.db.query(Host).get(host_id)
            self.identity = self.host.identity

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(default_group_id), "General")
        tabs.addTab(self._build_auth_tab(), "Authentication")
        tabs.addTab(self._build_proxy_tab(), "Jump Host / Chain")
        tabs.addTab(self._build_advanced_tab(), "Advanced")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

        self._load_existing()

    # --- Tabs ---

    def _build_general_tab(self, default_group_id):
        w = QWidget()
        form = QFormLayout(w)

        self.label_edit = QLineEdit()
        self.hostname_edit = QLineEdit()
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)
        self.username_edit = QLineEdit()

        self.group_combo = QComboBox()
        self.group_combo.addItem("(none)", None)
        for g in self.db.query(Group).all():
            self.group_combo.addItem(g.name, g.id)
        if default_group_id:
            idx = self.group_combo.findData(default_group_id)
            if idx >= 0:
                self.group_combo.setCurrentIndex(idx)

        form.addRow("Label:", self.label_edit)
        form.addRow("Hostname / IP:", self.hostname_edit)
        form.addRow("Port:", self.port_spin)
        form.addRow("Username (override):", self.username_edit)
        form.addRow("Group:", self.group_combo)
        return w

    def _build_auth_tab(self):
        w = QWidget()
        form = QFormLayout(w)

        self.identity_label_edit = QLineEdit()
        self.auth_type_combo = QComboBox()
        self.auth_type_combo.addItems(["password", "key", "agent"])
        self.identity_username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)

        self.private_key_path_edit = QLineEdit()
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_private_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.private_key_path_edit)
        key_row.addWidget(browse_btn)

        self.private_key_text = QTextEdit()
        self.private_key_text.setPlaceholderText("Paste private key PEM here (alternative to file path)")
        self.private_key_text.setFixedHeight(80)

        self.passphrase_edit = QLineEdit()
        self.passphrase_edit.setEchoMode(QLineEdit.Password)

        form.addRow("Identity Label:", self.identity_label_edit)
        form.addRow("Auth Type:", self.auth_type_combo)
        form.addRow("Identity Username:", self.identity_username_edit)
        form.addRow("Password:", self.password_edit)
        form.addRow("Private Key File:", key_row)
        form.addRow("Private Key (paste):", self.private_key_text)
        form.addRow("Key Passphrase:", self.passphrase_edit)
        return w

    def _build_proxy_tab(self):
        w = QWidget()
        form = QFormLayout(w)

        self.proxy_combo = QComboBox()
        self.proxy_combo.addItem("(none - direct connection)", None)
        for h in self.db.query(Host).all():
            if h.id != self.host_id:
                self.proxy_combo.addItem(f"{h.label} ({h.hostname})", h.id)

        form.addRow("Connect through (jump host):", self.proxy_combo)
        info = QLabel(
            "Select a previously-saved host to use as a jump/proxy.\n"
            "Chains of multiple jump hosts work automatically: just set\n"
            "each host's proxy to the previous hop."
        )
        info.setWordWrap(True)
        form.addRow(info)
        return w

    def _build_advanced_tab(self):
        w = QWidget()
        form = QFormLayout(w)

        self.terminal_type_edit = QLineEdit("xterm-256color")
        self.keepalive_spin = QSpinBox()
        self.keepalive_spin.setRange(0, 600)
        self.keepalive_spin.setValue(30)
        self.color_tag_edit = QLineEdit()

        form.addRow("Terminal Type:", self.terminal_type_edit)
        form.addRow("Keepalive (sec):", self.keepalive_spin)
        form.addRow("Color Tag:", self.color_tag_edit)
        return w

    # --- Data binding ---

    def _browse_private_key(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Private Key")
        if path:
            self.private_key_path_edit.setText(path)

    def _load_existing(self):
        if not self.host:
            return
        h = self.host
        self.label_edit.setText(h.label or "")
        self.hostname_edit.setText(h.hostname or "")
        self.port_spin.setValue(h.port or 22)
        self.username_edit.setText(h.username or "")

        if h.group_id:
            idx = self.group_combo.findData(h.group_id)
            if idx >= 0:
                self.group_combo.setCurrentIndex(idx)

        if h.proxy_host_id:
            idx = self.proxy_combo.findData(h.proxy_host_id)
            if idx >= 0:
                self.proxy_combo.setCurrentIndex(idx)

        self.terminal_type_edit.setText(h.terminal_type or "xterm-256color")
        self.keepalive_spin.setValue(h.keepalive_interval or 30)
        self.color_tag_edit.setText(h.color_tag or "")

        if self.identity:
            i = self.identity
            self.identity_label_edit.setText(i.label or "")
            idx = self.auth_type_combo.findText(i.auth_type or "password")
            if idx >= 0:
                self.auth_type_combo.setCurrentIndex(idx)
            self.identity_username_edit.setText(i.username or "")
            if i.enc_password:
                self.password_edit.setText(self.vault.decrypt(i.enc_password))
            if i.enc_private_key:
                self.private_key_text.setPlainText(self.vault.decrypt(i.enc_private_key))
            self.private_key_path_edit.setText(i.private_key_path or "")
            if i.enc_passphrase:
                self.passphrase_edit.setText(self.vault.decrypt(i.enc_passphrase))

    def save(self):
        if not self.host:
            self.host = Host()
            self.db.add(self.host)

        h = self.host
        h.label = self.label_edit.text().strip() or self.hostname_edit.text().strip()
        h.hostname = self.hostname_edit.text().strip()
        h.port = self.port_spin.value()
        h.username = self.username_edit.text().strip() or None
        h.group_id = self.group_combo.currentData()
        h.proxy_host_id = self.proxy_combo.currentData()
        h.terminal_type = self.terminal_type_edit.text().strip() or "xterm-256color"
        h.keepalive_interval = self.keepalive_spin.value()
        h.color_tag = self.color_tag_edit.text().strip()

        # Identity
        if not self.identity:
            self.identity = Identity()
            self.db.add(self.identity)
            h.identity = self.identity

        i = self.identity
        i.label = self.identity_label_edit.text().strip() or h.label
        i.auth_type = self.auth_type_combo.currentText()
        i.username = self.identity_username_edit.text().strip() or None

        password = self.password_edit.text()
        i.enc_password = self.vault.encrypt(password) if password else ""

        key_text = self.private_key_text.toPlainText().strip()
        i.enc_private_key = self.vault.encrypt(key_text) if key_text else ""

        i.private_key_path = self.private_key_path_edit.text().strip()

        passphrase = self.passphrase_edit.text()
        i.enc_passphrase = self.vault.encrypt(passphrase) if passphrase else ""

        self.db.commit()
        self.accept()
