"""
ui/theme.py
Centralized application stylesheet.

Design language: a refined dark IDE theme (closer to JetBrains/Cursor than
generic "VS Code clone" defaults) with deliberate attention to the details
that separate a polished app from a default-Qt-widgets look:
  - Consistent 6/8/12px spacing rhythm instead of arbitrary padding values
  - Subtle borders (1px, low-contrast) instead of harsh white-on-black lines
  - A real accent color used sparingly (selection, focus ring, primary
    actions) rather than scattered blues
  - Rounded corners on every interactive surface (6px radius standard)
  - Hover/pressed/focus states on every control, not just buttons
  - A slightly warmer dark gray (#181a1f) instead of pure #1e1e1e, which
    reads as less "default Qt dark palette"
"""

# Core palette - referenced via comments for maintainability since Qt
# stylesheets don't support variables.
#   bg-base       #181a1f   main window / canvas background
#   bg-elevated   #20232a   panels, menus, dialogs (raised surfaces)
#   bg-input      #262931   text fields, comboboxes
#   bg-hover      #2a2e37   hover state
#   bg-selected   #2d3340   selected row/item background (not the accent)
#   border        #2f333d   subtle dividers
#   border-strong #3a3f4b   focused/emphasized borders
#   text-primary  #e6e6e6
#   text-secondary #9a9fa8
#   text-disabled #5a5f68
#   accent        #5b8def   primary accent (buttons, focus ring, links)
#   accent-hover  #6f9af2
#   accent-pressed #4a78d6
#   success       #3fb950
#   warning       #d7ba00
#   danger        #f14c4c

DARK_STYLESHEET = """
* {
    font-family: "Segoe UI", "SF Pro Text", "Cantarell", "Helvetica Neue", sans-serif;
    font-size: 13px;
    outline: none;
}

QWidget {
    background-color: #181a1f;
    color: #e6e6e6;
}

QMainWindow, QDialog {
    background-color: #181a1f;
}

/* --- Menu bar --- */
QMenuBar {
    background-color: #1c1f26;
    color: #c4c8cf;
    border-bottom: 1px solid #2f333d;
    padding: 3px 4px;
}
QMenuBar::item {
    background: transparent;
    padding: 5px 12px;
    border-radius: 5px;
    margin: 0 1px;
}
QMenuBar::item:selected {
    background-color: #2a2e37;
    color: #ffffff;
}
QMenu {
    background-color: #20232a;
    border: 1px solid #2f333d;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    padding: 7px 28px 7px 14px;
    border-radius: 5px;
    margin: 1px 0;
}
QMenu::item:selected {
    background-color: #5b8def;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #5a5f68;
}
QMenu::separator {
    height: 1px;
    background: #2f333d;
    margin: 6px 10px;
}

/* --- Tabs --- */
QTabWidget::pane {
    border: 1px solid #2f333d;
    background-color: #181a1f;
    border-radius: 0 0 8px 8px;
    top: -1px;
}
QTabBar {
    background: #1c1f26;
}
QTabBar::tab {
    background-color: transparent;
    color: #9a9fa8;
    padding: 8px 14px;
    border: none;
    border-bottom: 2px solid transparent;
    min-width: 100px;
    margin-right: 1px;
}
QTabBar::tab:selected {
    background-color: #20232a;
    color: #ffffff;
    border-bottom: 2px solid #5b8def;
}
QTabBar::tab:hover:!selected {
    background-color: #20232a;
    color: #c4c8cf;
}

/* --- Buttons --- */
QPushButton {
    background-color: #262931;
    color: #e6e6e6;
    border: 1px solid #3a3f4b;
    border-radius: 6px;
    padding: 7px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #2e323c;
    border-color: #4a505e;
}
QPushButton:pressed {
    background-color: #20232a;
}
QPushButton:disabled {
    color: #5a5f68;
    background-color: #1c1f26;
    border-color: #2f333d;
}

QPushButton#PrimaryButton {
    background-color: #5b8def;
    border-color: #5b8def;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover {
    background-color: #6f9af2;
    border-color: #6f9af2;
}
QPushButton#PrimaryButton:pressed {
    background-color: #4a78d6;
}

/* --- Inputs --- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background-color: #262931;
    color: #f0f0f0;
    border: 1px solid #3a3f4b;
    border-radius: 6px;
    padding: 6px 9px;
    selection-background-color: #5b8def;
    selection-color: #ffffff;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1.5px solid #5b8def;
}
QLineEdit:disabled, QComboBox:disabled {
    color: #5a5f68;
    background-color: #1c1f26;
}
QLineEdit::placeholder {
    color: #5a5f68;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox::down-arrow {
    width: 10px;
    height: 10px;
}
QComboBox QAbstractItemView {
    background-color: #20232a;
    border: 1px solid #3a3f4b;
    border-radius: 6px;
    selection-background-color: #5b8def;
    padding: 4px;
}

/* --- Trees / tables --- */
QTreeWidget, QTableWidget, QListWidget {
    background-color: #181a1f;
    border: 1px solid #2f333d;
    border-radius: 8px;
    gridline-color: #2f333d;
    alternate-background-color: #1c1f26;
    padding: 2px;
}
QTreeWidget::item, QTableWidget::item, QListWidget::item {
    padding: 5px 4px;
    border-radius: 4px;
}
QTreeWidget::item:hover, QTableWidget::item:hover, QListWidget::item:hover {
    background-color: #20232a;
}
QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected {
    background-color: #2d3340;
    color: #ffffff;
}
QTreeWidget::branch {
    background: transparent;
}
QHeaderView::section {
    background-color: #1c1f26;
    color: #9a9fa8;
    padding: 7px;
    border: none;
    border-right: 1px solid #2f333d;
    border-bottom: 1px solid #2f333d;
    font-weight: 600;
}
QHeaderView::section:first {
    border-top-left-radius: 6px;
}

/* --- Group boxes --- */
QGroupBox {
    border: 1px solid #2f333d;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 14px;
    font-weight: 600;
    color: #c4c8cf;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #e6e6e6;
}

/* --- Scrollbars --- */
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 2px 0;
}
QScrollBar::handle:vertical {
    background: #3a3f4b;
    border-radius: 5px;
    min-height: 28px;
    margin: 0 3px;
}
QScrollBar::handle:vertical:hover {
    background: #4a505e;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
}
QScrollBar::handle:horizontal {
    background: #3a3f4b;
    border-radius: 5px;
    min-width: 28px;
    margin: 3px 0;
}
QScrollBar::handle:horizontal:hover {
    background: #4a505e;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* --- Splitter --- */
QSplitter::handle {
    background-color: #181a1f;
    width: 3px;
}
QSplitter::handle:hover {
    background-color: #5b8def;
}

/* --- Status / labels --- */
QLabel {
    color: #c4c8cf;
}
QLabel#SectionTitle {
    color: #ffffff;
    font-weight: 600;
    font-size: 14px;
    padding: 2px 0;
}
QStatusBar {
    background-color: #1c1f26;
    border-top: 1px solid #2f333d;
    color: #9a9fa8;
}
QStatusBar::item {
    border: none;
}

/* --- Progress --- */
QProgressDialog {
    background-color: #20232a;
}
QProgressBar {
    background-color: #262931;
    border: 1px solid #3a3f4b;
    border-radius: 6px;
    text-align: center;
    color: #ffffff;
    min-height: 18px;
}
QProgressBar::chunk {
    background-color: #5b8def;
    border-radius: 5px;
}

/* --- Tooltips --- */
QToolTip {
    background-color: #20232a;
    color: #e6e6e6;
    border: 1px solid #3a3f4b;
    border-radius: 6px;
    padding: 6px 9px;
}

/* --- ToolButton (used for tab close/+, sidebar toggle, etc.) --- */
QToolButton {
    background: transparent;
    border: none;
    border-radius: 5px;
    padding: 4px;
    color: #c4c8cf;
}
QToolButton:hover {
    background-color: #2a2e37;
    color: #ffffff;
}
QToolButton:pressed {
    background-color: #20232a;
}

/* --- Checkboxes / radio buttons --- */
QCheckBox, QRadioButton {
    color: #e6e6e6;
    spacing: 8px;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 1.5px solid #4a505e;
    border-radius: 4px;
    background-color: #262931;
}
QRadioButton::indicator {
    border-radius: 8px;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: #5b8def;
    border-color: #5b8def;
}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {
    border-color: #5b8def;
}

/* --- Message boxes --- */
QMessageBox {
    background-color: #20232a;
}

/* --- Dialog title bars (where Qt draws them) --- */
QDialog QLabel {
    color: #e6e6e6;
}
"""


def apply_theme(app):
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLESHEET)