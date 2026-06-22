"""
ui/shortcuts.py
Customizable keyboard shortcuts.

App-level actions (close tab, new connection, etc.) are registered here
with a default key sequence. Users can remap any of them via
Tools -> Customize Shortcuts; the mapping is persisted in the AppMeta table
as JSON so it travels with the vault.

Terminal-internal key handling (Ctrl+C/Ctrl+D/arrows/etc. inside
TerminalWidget) is intentionally NOT part of this registry - those follow
fixed standard terminal/readline conventions so shells, tmux, vim etc.
keep working. Only app-chrome shortcuts (tab/window management) are
customizable here, and defaults deliberately avoid colliding with shell
control sequences (see terminal_widget.py's docstring).
"""

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLabel, QLineEdit, QPushButton,
    QDialogButtonBox, QMessageBox, QScrollArea, QWidget, QHBoxLayout
)

from db.models import AppMeta

APP_META_KEY = "custom_shortcuts"


# action_id -> (description, default_key_sequence)
# action_id is also the attribute name on MainWindow that the shortcut
# should call when activated.
DEFAULT_SHORTCUTS = {
    "quick_connect": ("Quick Connect (manual SSH)", "Ctrl+Shift+N"),
    "open_local_terminal": ("New Local Terminal", "Ctrl+Shift+T"),
    "close_current_tab": ("Close current tab", "Ctrl+Shift+W"),
    "next_tab": ("Next tab", "Ctrl+Tab"),
    "previous_tab": ("Previous tab", "Ctrl+Shift+Tab"),
    "toggle_sidebar": ("Toggle sidebar", "Ctrl+Shift+B"),
    "focus_host_search": ("Focus host search", "Ctrl+Shift+F"),
    "open_command_palette": ("Command palette", "Ctrl+Shift+P"),
}

# Reserved for standard terminal/shell/readline/tmux use - blocked from
# being assigned to app-level shortcuts.
RESERVED_SEQUENCES = {
    "Ctrl+C", "Ctrl+D", "Ctrl+W", "Ctrl+T", "Ctrl+B", "Ctrl+A",
    "Ctrl+L", "Ctrl+R", "Ctrl+E", "Ctrl+U", "Ctrl+K", "Ctrl+Z", "Ctrl+V",
}


def load_shortcuts(db_session):
    """Return a dict[action_id -> key_sequence_str], merging saved
    overrides on top of DEFAULT_SHORTCUTS."""
    result = {action_id: default_seq for action_id, (_, default_seq) in DEFAULT_SHORTCUTS.items()}

    meta = db_session.query(AppMeta).filter(AppMeta.key == APP_META_KEY).first()
    if meta and meta.value:
        try:
            overrides = json.loads(meta.value)
            for action_id, seq in overrides.items():
                if action_id in result:
                    result[action_id] = seq
        except (json.JSONDecodeError, TypeError):
            pass

    return result


def save_shortcuts(db_session, mapping: dict):
    meta = db_session.query(AppMeta).filter(AppMeta.key == APP_META_KEY).first()
    if not meta:
        meta = AppMeta(key=APP_META_KEY, value="")
        db_session.add(meta)
    meta.value = json.dumps(mapping)
    db_session.commit()


def apply_shortcuts(main_window, db_session):
    """
    (Re)create all app-level QShortcuts on `main_window` based on the
    current saved mapping. Safe to call again after the user changes
    bindings - old shortcuts from this registry are removed first.
    """
    for sc in getattr(main_window, "_custom_shortcuts", []):
        sc.setParent(None)
        sc.deleteLater()
    main_window._custom_shortcuts = []

    mapping = load_shortcuts(db_session)

    for action_id, seq_str in mapping.items():
        if not seq_str:
            continue  # empty = unbound
        seq = QKeySequence(seq_str)
        if seq.isEmpty():
            continue
        callback = getattr(main_window, action_id, None)
        if callback is None:
            continue
        sc = QShortcut(seq, main_window)
        sc.activated.connect(callback)
        main_window._custom_shortcuts.append(sc)

    return mapping


class ShortcutEdit(QLineEdit):
    """A QLineEdit that captures a single key-press combo and displays it
    as a QKeySequence string (e.g. 'Ctrl+Shift+N')."""

    def __init__(self, initial_seq_str="", parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Click and press a key combo...")
        self._seq_str = ""
        self.set_sequence(initial_seq_str)

    def set_sequence(self, seq_str):
        self._seq_str = seq_str or ""
        self.setText(self._seq_str)

    def sequence_str(self):
        return self._seq_str

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta):
            return
        if key in (Qt.Key_Backspace, Qt.Key_Delete):
            self.set_sequence("")
            return

        mods = int(event.modifiers())
        seq = QKeySequence(mods | key)
        self.set_sequence(seq.toString())


class ShortcutSettingsDialog(QDialog):
    """
    Tools -> Customize Shortcuts. Shows every customizable action with an
    editable key-sequence field (click the field, then press the desired
    key combo). Detects duplicate/reserved bindings before saving.
    """

    def __init__(self, db_session, parent=None):
        super().__init__(parent)
        self.db = db_session
        self.setWindowTitle("Customize Shortcuts")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Click a field and press the desired key combination.\n"
            "Press Backspace/Delete to clear (disable) a shortcut.\n\n"
            "Note: shortcuts that would collide with standard terminal\n"
            "keys (Ctrl+C, Ctrl+W, Ctrl+T, Ctrl+B, Ctrl+A, Ctrl+L, Ctrl+D,\n"
            "etc.) are blocked, since the terminal needs those for normal\n"
            "shell/tmux/readline use."
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        scroll.setWidget(form_widget)
        layout.addWidget(scroll)

        self.fields = {}
        current = load_shortcuts(self.db)
        for action_id, (description, default_seq) in DEFAULT_SHORTCUTS.items():
            field = ShortcutEdit(current.get(action_id, default_seq))
            self.fields[action_id] = field
            row = QHBoxLayout()
            row.addWidget(field)
            reset_btn = QPushButton("Reset")
            reset_btn.setFixedWidth(60)
            reset_btn.clicked.connect(lambda _, f=field, d=default_seq: f.set_sequence(d))
            row.addWidget(reset_btn)
            form.addRow(description, row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self):
        mapping = {action_id: field.sequence_str() for action_id, field in self.fields.items()}

        seen = {}
        for action_id, seq in mapping.items():
            if not seq:
                continue
            if seq in seen:
                QMessageBox.warning(
                    self, "Duplicate Shortcut",
                    f"'{seq}' is assigned to both "
                    f"'{DEFAULT_SHORTCUTS[seen[seq]][0]}' and "
                    f"'{DEFAULT_SHORTCUTS[action_id][0]}'.\n"
                    "Please use a unique key combination for each action."
                )
                return
            seen[seq] = action_id

            if seq in RESERVED_SEQUENCES:
                QMessageBox.warning(
                    self, "Reserved Shortcut",
                    f"'{seq}' is reserved for standard terminal/shell use "
                    f"and can't be assigned to '{DEFAULT_SHORTCUTS[action_id][0]}'."
                )
                return

        save_shortcuts(self.db, mapping)
        self.accept()
