"""
ui/progress.py
A simple modal "Connecting..." progress dialog, plus a QThread-based worker
that runs a blocking callable (e.g. SSH connect, SFTP open) off the UI thread
so the application doesn't freeze.
"""

from PySide6.QtCore import QThread, Signal, QObject, Qt
from PySide6.QtWidgets import QProgressDialog


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


def run_with_progress(parent, label_text, fn, on_success, on_error, *args, **kwargs):
    """
    Shows a modal "Connecting..." dialog while `fn` runs in a background
    thread, then calls on_success(result) or on_error(error_message) on the
    UI thread once done.

    Returns the worker thread (keep a reference alive until finished).
    """
    progress = QProgressDialog(label_text, None, 0, 0, parent)
    progress.setWindowModality(Qt.WindowModal)
    progress.setWindowTitle("Please wait")
    progress.setMinimumDuration(0)
    progress.setCancelButton(None)
    progress.show()

    worker = CallableWorker(fn, *args, **kwargs)

    def _on_finished(result):
        progress.close()
        on_success(result)

    def _on_error(msg):
        progress.close()
        on_error(msg)

    worker.signals.finished.connect(_on_finished)
    worker.signals.error.connect(_on_error)
    worker.start()

    return worker
