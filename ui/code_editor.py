"""
ui/code_editor.py
A simple text editor widget with Pygments-based syntax highlighting,
selected automatically from the file's extension/name. Used for
double-click "Edit" on text files in the SFTP browser.
"""

from PySide6.QtGui import QFont, QTextCharFormat, QSyntaxHighlighter, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QPushButton, QLabel

try:
    from pygments.lexers import get_lexer_for_filename, TextLexer
    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False


# A compact "monokai-ish" palette that fits the app's dark theme
TOKEN_COLORS = {
    "Token.Keyword": "#c586c0",
    "Token.Keyword.Constant": "#569cd6",
    "Token.Keyword.Declaration": "#569cd6",
    "Token.Keyword.Namespace": "#c586c0",
    "Token.Name.Builtin": "#4ec9b0",
    "Token.Name.Function": "#dcdcaa",
    "Token.Name.Class": "#4ec9b0",
    "Token.Name.Decorator": "#dcdcaa",
    "Token.Name.Tag": "#569cd6",
    "Token.Name.Attribute": "#9cdcfe",
    "Token.Literal.String": "#ce9178",
    "Token.Literal.Number": "#b5cea8",
    "Token.Operator": "#d4d4d4",
    "Token.Punctuation": "#d4d4d4",
    "Token.Comment": "#6a9955",
    "Token.Comment.Single": "#6a9955",
    "Token.Comment.Multiline": "#6a9955",
    "Token.Error": "#f44747",
    "Token.Generic.Deleted": "#f44747",
    "Token.Generic.Inserted": "#b5cea8",
}


def _color_for_token(token_type):
    """Walk up the Pygments token hierarchy until a color is found."""
    s = str(token_type)
    while s:
        if s in TOKEN_COLORS:
            return TOKEN_COLORS[s]
        if "." not in s:
            break
        s = s.rsplit(".", 1)[0]
    return None


class PygmentsHighlighter(QSyntaxHighlighter):
    """
    Highlights document text per-block using a Pygments lexer applied to
    each block's text. Adequate for config files, scripts, and source
    files typically edited over SFTP.
    """

    def __init__(self, document, lexer):
        super().__init__(document)
        self.lexer = lexer

    def highlightBlock(self, text):
        if not PYGMENTS_AVAILABLE or self.lexer is None or not text:
            return
        try:
            tokens = list(self.lexer.get_tokens(text))
        except Exception:
            return

        pos = 0
        for token_type, value in tokens:
            length = len(value)
            color_hex = _color_for_token(token_type)
            if color_hex:
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(color_hex))
                ts = str(token_type)
                if "Comment" in ts:
                    fmt.setFontItalic(True)
                if "Keyword" in ts:
                    fmt.setFontWeight(QFont.Bold)
                self.setFormat(pos, length, fmt)
            pos += length


class CodeEditor(QWidget):
    """
    A text editor pane with syntax highlighting (best-effort, based on
    filename extension) and a Save action wired up by the caller via
    `on_save(content_text)`.
    """

    def __init__(self, filename, content, on_save=None, parent=None):
        super().__init__(parent)
        self.filename = filename
        self.on_save = on_save

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        toolbar = QHBoxLayout()
        self.title_label = QLabel(f"<b>{filename}</b>")
        save_btn = QPushButton("Save (Ctrl+S)")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save)
        toolbar.addWidget(self.title_label)
        toolbar.addStretch()
        toolbar.addWidget(save_btn)
        layout.addLayout(toolbar)

        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.setPlainText(content)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.editor)

        self.highlighter = None
        if PYGMENTS_AVAILABLE:
            try:
                lexer = get_lexer_for_filename(filename, stripnl=False)
            except Exception:
                lexer = TextLexer(stripnl=False)
            self.highlighter = PygmentsHighlighter(self.editor.document(), lexer)

        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._save)

    def _save(self):
        if self.on_save:
            self.on_save(self.editor.toPlainText())

    def set_focus(self):
        self.editor.setFocus()
