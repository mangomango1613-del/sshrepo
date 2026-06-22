"""
ui/connection_manager.py
Manages multiple concurrent connection attempts WITHOUT blocking the UI.

Previously, ui.progress.run_with_progress showed a Qt.WindowModal
QProgressDialog per connection - firing several connects in a row stacked
modal dialogs and effectively forced the user to wait for each one before
interacting with the app again.

This module instead runs each connection on its own QThread and reports
progress via a small non-modal "Connections" panel (a list showing
"Connecting...", "Connected", or "Failed: <reason>" per attempt). The user
can keep working (open more tabs, browse the host tree, etc.) while several
connections are establishing in parallel.
"""

from PySide6.QtCore import QThread, Signal, QObject, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QToolButton
)


class _WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)


class CallableWorker(QThread):
    """Runs `fn(*args, **kwargs)` in a background thread."""

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = _WorkerSignals()

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))


class ConnectionPanel(QWidget):
    """
    A small non-modal panel listing in-flight and recent connection
    attempts. Lives at the bottom of the main window and never blocks
    input - multiple connects show up as separate rows and resolve
    independently.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumHeight(140)
        self._rows = {}  # item key -> QListWidgetItem

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Connections</b>"))
        header.addStretch()
        self.clear_btn = QToolButton()
        self.clear_btn.setText("Clear finished")
        self.clear_btn.clicked.connect(self.clear_finished)
        header.addWidget(self.clear_btn)
        hide_btn = QToolButton()
        hide_btn.setText("\u00d7")
        hide_btn.setToolTip("Hide panel")
        hide_btn.clicked.connect(lambda: self.setVisible(False))
        header.addWidget(hide_btn)
        layout.addLayout(header)

        self.list = QListWidget()
        layout.addWidget(self.list)

        self.setVisible(False)

    def add_item(self, key, label):
        item = QListWidgetItem(f"\u23f3 Connecting: {label}")
        item.setForeground(Qt.yellow)
        self.list.addItem(item)
        self._rows[key] = item
        self.setVisible(True)
        return item

    def mark_success(self, key, label):
        item = self._rows.get(key)
        if item:
            item.setText(f"\u2705 Connected: {label}")
            item.setForeground(Qt.green)

    def mark_error(self, key, label, error_msg):
        item = self._rows.get(key)
        if item:
            item.setText(f"\u274c Failed: {label} - {error_msg}")
            item.setForeground(Qt.red)

    def clear_finished(self):
        for row in range(self.list.count() - 1, -1, -1):
            text = self.list.item(row).text()
            if text.startswith("\u2705") or text.startswith("\u274c"):
                self.list.takeItem(row)
        if self.list.count() == 0:
            self.setVisible(False)


class ConnectionManager:
    """
    Owns the ConnectionPanel and dispatches connection tasks. Many connects
    can be in flight at once; each gets its own QThread and its own row in
    the panel. Callbacks (on_success/on_error) fire on the Qt main thread
    via signals, so it's safe to manipulate widgets/tabs from them.
    """

    _counter = 0

    def __init__(self, panel: ConnectionPanel):
        self.panel = panel
        self._workers = []  # keep references alive

    def connect(self, label, task_fn, on_success, on_error):
        ConnectionManager._counter += 1
        key = ConnectionManager._counter

        self.panel.add_item(key, label)

        worker = CallableWorker(task_fn)

        def _on_finished(result):
            self.panel.mark_success(key, label)
            on_success(result)
            self._cleanup(worker)

        def _on_error(msg):
            self.panel.mark_error(key, label, msg)
            on_error(msg)
            self._cleanup(worker)

        worker.signals.finished.connect(_on_finished)
        worker.signals.error.connect(_on_error)
        self._workers.append(worker)
        worker.start()
        return worker

    def _cleanup(self, worker):
        if worker in self._workers:
            self._workers.remove(worker)
