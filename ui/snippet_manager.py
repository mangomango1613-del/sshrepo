"""
ui/snippet_manager.py
Manage reusable snippets (scripts) stored in SQLite, and run them
against the active SSH session.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QTextEdit, QPushButton,
    QLineEdit, QLabel, QMessageBox, QInputDialog
)

from db.models import Snippet


class SnippetManagerDialog(QDialog):
    def __init__(self, db_session, ssh_session=None, parent=None):
        super().__init__(parent)
        self.db = db_session
        self.ssh_session = ssh_session
        self.setWindowTitle("Snippets")
        self.setMinimumSize(600, 400)

        layout = QHBoxLayout(self)

        left = QVBoxLayout()
        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_select)
        left.addWidget(QLabel("Snippets"))
        left.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self._new_snippet)
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._delete_snippet)
        btn_row.addWidget(new_btn)
        btn_row.addWidget(del_btn)
        left.addLayout(btn_row)

        right = QVBoxLayout()
        self.name_edit = QLineEdit()
        self.content_edit = QTextEdit()
        self.content_edit.setFontFamily("Consolas")

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save_snippet)

        run_btn = QPushButton("Run on Active Session")
        run_btn.clicked.connect(self._run_snippet)
        run_btn.setEnabled(ssh_session is not None)

        right.addWidget(QLabel("Name"))
        right.addWidget(self.name_edit)
        right.addWidget(QLabel("Content"))
        right.addWidget(self.content_edit)
        row = QHBoxLayout()
        row.addWidget(save_btn)
        row.addWidget(run_btn)
        right.addLayout(row)

        layout.addLayout(left, 1)
        layout.addLayout(right, 2)

        self.refresh()

    def refresh(self):
        self.list_widget.clear()
        for s in self.db.query(Snippet).all():
            self.list_widget.addItem(s.name)

    def _current_snippet(self):
        item = self.list_widget.currentItem()
        if not item:
            return None
        return self.db.query(Snippet).filter(Snippet.name == item.text()).first()

    def _on_select(self, current, previous):
        snippet = self._current_snippet()
        if snippet:
            self.name_edit.setText(snippet.name)
            self.content_edit.setPlainText(snippet.content)
        else:
            self.name_edit.clear()
            self.content_edit.clear()

    def _new_snippet(self):
        name, ok = QInputDialog.getText(self, "New Snippet", "Name:")
        if ok and name:
            existing = self.db.query(Snippet).filter(Snippet.name == name).first()
            if existing:
                QMessageBox.warning(self, "Error", "A snippet with that name exists.")
                return
            s = Snippet(name=name, content="")
            self.db.add(s)
            self.db.commit()
            self.refresh()

    def _save_snippet(self):
        snippet = self._current_snippet()
        new_name = self.name_edit.text().strip()
        if not new_name:
            return
        if not snippet:
            snippet = Snippet(name=new_name)
            self.db.add(snippet)
        else:
            snippet.name = new_name
        snippet.content = self.content_edit.toPlainText()
        self.db.commit()
        self.refresh()

    def _delete_snippet(self):
        snippet = self._current_snippet()
        if not snippet:
            return
        confirm = QMessageBox.question(self, "Delete", f"Delete snippet '{snippet.name}'?")
        if confirm == QMessageBox.Yes:
            self.db.delete(snippet)
            self.db.commit()
            self.refresh()

    def _run_snippet(self):
        if not self.ssh_session:
            QMessageBox.warning(self, "Error", "No active SSH session.")
            return
        content = self.content_edit.toPlainText()
        try:
            out, err = self.ssh_session.exec_command(content)
            QMessageBox.information(self, "Output", out + ("\n--- STDERR ---\n" + err if err else ""))
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))
