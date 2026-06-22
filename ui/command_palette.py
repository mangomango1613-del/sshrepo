"""
ui/command_palette.py
A Cursor/VS Code-style command palette: Ctrl+Shift+P opens a searchable
list of all available actions; typing filters, Enter runs the highlighted
command.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem
)


class CommandPaletteDialog(QDialog):
    """
    `commands` is a list of (label, callback) tuples. On Enter/click,
    the dialog closes and the selected callback is invoked by the caller
    (via `self.selected_callback`).
    """

    def __init__(self, commands, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Command Palette")
        self.setMinimumWidth(480)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.commands = commands
        self.selected_callback = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a command...")
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._activate_current)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.itemActivated.connect(self._activate_item)
        layout.addWidget(self.list)

        self._populate("")
        self.search.setFocus()

    def _populate(self, filter_text):
        self.list.clear()
        filter_text = filter_text.lower()
        for label, _ in self.commands:
            if filter_text in label.lower():
                self.list.addItem(QListWidgetItem(label))
        if self.list.count() > 0:
            self.list.setCurrentRow(0)

    def _filter(self, text):
        self._populate(text)

    def _activate_current(self):
        item = self.list.currentItem()
        if item:
            self._activate_item(item)

    def _activate_item(self, item):
        label = item.text()
        for cmd_label, callback in self.commands:
            if cmd_label == label:
                self.selected_callback = callback
                break
        self.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        if event.key() == Qt.Key_Down:
            row = min(self.list.currentRow() + 1, self.list.count() - 1)
            self.list.setCurrentRow(row)
            return
        if event.key() == Qt.Key_Up:
            row = max(self.list.currentRow() - 1, 0)
            self.list.setCurrentRow(row)
            return
        super().keyPressEvent(event)
