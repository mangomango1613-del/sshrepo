"""
ui/host_picker_dialog.py
Small dialog to pick a saved host - used when opening the second pane of
the dual SFTP view.
"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QComboBox, QDialogButtonBox, QLabel

from db.repository import all_hosts_flat


class HostPickerDialog(QDialog):
    def __init__(self, db_session, title="Select Host", exclude_host_id=None, parent=None):
        super().__init__(parent)
        self.db = db_session
        self.setWindowTitle(title)
        self.selected_host_id = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Connect the other pane to:"))

        self.combo = QComboBox()
        for h in all_hosts_flat(self.db):
            if h.id == exclude_host_id:
                continue
            self.combo.addItem(f"{h.label}  ({h.hostname})", h.id)
        layout.addWidget(self.combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        self.selected_host_id = self.combo.currentData()
        self.accept()
