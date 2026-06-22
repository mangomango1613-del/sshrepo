"""
ui/dual_sftp_view.py
A dual-pane SFTP view: two independent SFTPBrowser panes side by side,
each connected to its own host. Files/folders can be sent directly from
one pane to the other (remote -> remote, streamed through this process)
via right-click "Send -> other pane", without an intermediate local copy.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QSplitter

from ui.sftp_browser import SFTPBrowser


class DualSFTPView(QWidget):
    def __init__(self, sftp_manager_left, label_left, sftp_manager_right, label_right, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.left = SFTPBrowser(sftp_manager_left, title=label_left)
        self.right = SFTPBrowser(sftp_manager_right, title=label_right)

        # Wire each pane to know about its sibling, enabling
        # "Send -> other pane" transfers.
        self.left.peer = self.right
        self.right.peer = self.left

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.left)
        splitter.addWidget(self.right)
        splitter.setSizes([1, 1])

        layout.addWidget(splitter)

    def close_all(self):
        for pane in (self.left, self.right):
            try:
                pane.sftp.close()
            except Exception:
                pass

    def set_focus(self):
        self.left.set_focus()
