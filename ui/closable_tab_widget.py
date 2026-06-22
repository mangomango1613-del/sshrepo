"""
ui/closable_tab_widget.py
A QTabWidget subclass that guarantees visible close buttons on every tab,
shows a colored connection-status dot per tab, supports right-click
context menu (Duplicate / Close / Close Others / Close All), middle-click
to close, and an always-visible "+" new-tab button in the tab bar corner.
"""

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QIcon
from PySide6.QtWidgets import QTabWidget, QToolButton, QTabBar, QMenu


STATUS_COLORS = {
    "idle": "#5a5f68",
    "connecting": "#d7ba00",
    "connected": "#3fb950",
    "error": "#f14c4c",
}


class ClosableTabBar(QTabBar):
    """Tab bar that always shows a working close button on each tab, and
    supports middle-click-to-close + right-click context menu."""

    middle_clicked = Signal(int)
    context_menu_requested_for_tab = Signal(int, object)  # index, global_pos

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(False)  # we draw our own close buttons
        self.setExpanding(False)
        self.setElideMode(Qt.ElideRight)
        self.setMovable(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def tabSizeHint(self, index):
        size = super().tabSizeHint(index)
        return QSize(size.width() + 18, size.height())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            index = self.tabAt(event.pos())
            if index >= 0:
                self.middle_clicked.emit(index)
                return
        super().mouseReleaseEvent(event)

    def _on_context_menu(self, pos):
        index = self.tabAt(pos)
        if index >= 0:
            self.context_menu_requested_for_tab.emit(index, self.mapToGlobal(pos))


class ClosableTabWidget(QTabWidget):
    """
    Drop-in replacement for QTabWidget with:
      - A reliable close ("x") button on every tab.
      - A status dot (colored circle icon) settable via set_tab_status().
      - Middle-click to close.
      - Right-click context menu: Duplicate, Close, Close Others, Close All
        (connected via signals so MainWindow supplies the actual behavior).
      - An always-visible "+" button (new tab) in the corner, next to the
        sidebar-toggle button.
    """

    tab_duplicate_requested = Signal(int)
    new_tab_requested = Signal()
    close_others_requested = Signal(int)
    close_all_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bar = ClosableTabBar(self)
        self.setTabBar(self._bar)
        self.setTabsClosable(False)  # handled by our own buttons
        self.setMovable(True)
        self.setDocumentMode(True)

        self._bar.middle_clicked.connect(self.tabCloseRequested.emit)
        self._bar.context_menu_requested_for_tab.connect(self._show_tab_context_menu)

        # "+" new tab button, placed in the top-right corner of the bar
        self.new_tab_btn = QToolButton(self)
        self.new_tab_btn.setText("+")
        self.new_tab_btn.setToolTip("New connection (Ctrl+Shift+N)")
        self.new_tab_btn.setCursor(Qt.PointingHandCursor)
        self.new_tab_btn.setFixedSize(28, 28)
        self.new_tab_btn.setStyleSheet(
            "QToolButton {"
            "  font-size: 16px;"
            "  font-weight: 600;"
            "  border-radius: 6px;"
            "  color: #c4c8cf;"
            "  background: transparent;"
            "}"
            "QToolButton:hover {"
            "  background-color: #5b8def;"
            "  color: #ffffff;"
            "}"
            "QToolButton:pressed {"
            "  background-color: #4a78d6;"
            "}"
        )
        self.new_tab_btn.clicked.connect(self.new_tab_requested.emit)
        self.setCornerWidget(self.new_tab_btn, Qt.TopRightCorner)

    def addTab(self, widget, label):
        index = super().addTab(widget, label)
        self._install_close_button(index)
        return index

    def insertTab(self, index, widget, label):
        idx = super().insertTab(index, widget, label)
        self._install_close_button(idx)
        return idx

    def _install_close_button(self, index):
        btn = QToolButton(self)
        btn.setText("\u00d7")  # multiplication sign, looks like a clean "x"
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("Close tab")
        btn.setFixedSize(20, 20)
        btn.setStyleSheet(
            "QToolButton {"
            "  border: none;"
            "  border-radius: 6px;"
            "  background: transparent;"
            "  color: #9a9fa8;"
            "  font-weight: 600;"
            "  font-size: 14px;"
            "}"
            "QToolButton:hover {"
            "  background-color: #f14c4c;"
            "  color: #ffffff;"
            "}"
            "QToolButton:pressed {"
            "  background-color: #d63e3e;"
            "}"
        )
        btn.clicked.connect(lambda: self._close_by_button(btn))
        self.tabBar().setTabButton(index, QTabBar.RightSide, btn)

    def _close_by_button(self, btn):
        for i in range(self.tabBar().count()):
            if self.tabBar().tabButton(i, QTabBar.RightSide) is btn:
                self.tabCloseRequested.emit(i)
                return

    def _show_tab_context_menu(self, index, global_pos):
        menu = QMenu(self)
        menu.addAction("Duplicate Tab", lambda: self.tab_duplicate_requested.emit(index))
        menu.addSeparator()
        menu.addAction("Close", lambda: self.tabCloseRequested.emit(index))
        menu.addAction("Close Others", lambda: self.close_others_requested.emit(index))
        menu.addAction("Close All", self.close_all_requested.emit)
        menu.exec(global_pos)

    def set_tab_status(self, index, status: str):
        """status: 'idle' | 'connecting' | 'connected' | 'error'"""
        color = STATUS_COLORS.get(status, STATUS_COLORS["idle"])
        pix = QPixmap(10, 10)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(1, 1, 8, 8)
        painter.end()
        self.setTabIcon(index, QIcon(pix))
        self.setTabToolTip(index, f"Status: {status}")