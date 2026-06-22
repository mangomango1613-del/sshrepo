"""
ui/terminal_widget.py

VT100/xterm terminal emulator widget using pyte for screen emulation.

CURSOR APPROACH (third rewrite, this one actually works reliably):
  Previous attempts:
    1. Monkey-patching viewport.paintEvent = fn  → unreliable in PySide6,
       Qt's C++ paint pipeline ignores Python instance attribute overrides
    2. _CursorOverlay QWidget child of viewport  → correct approach but
       setHtml() after every redraw recreates internal Qt child widgets and
       pushes our overlay to the back; raise_() after setHtml() helps but
       still flickers because the overlay parent (viewport) gets repainted
       WITHOUT the overlay rendered in the correct Z-order on some frames

  FINAL SOLUTION: Use a QWidget overlay that is a child of the TERMINAL
  WIDGET ITSELF (not the viewport), positioned over the viewport area.
  Since it is NOT a child of the viewport, setHtml() cannot disturb its
  Z-order. We set WA_TransparentForMouseEvents so it doesn't steal clicks.
  The overlay is sized to exactly one char cell and repositioned every
  redraw tick. Its own paintEvent (genuine QWidget subclass override) fills
  the cell with a solid white block and draws the char on top in dark.

KEYBOARD CONVENTIONS (Termius/PuTTY/standard terminal):
  Ctrl+C → SIGINT (0x03) unless there is a text selection (then copies)
  Ctrl+Shift+C → always copy
  Ctrl+V / right-click → paste
  Select with mouse → auto-copies to clipboard on mouse release (PuTTY)
  Ctrl+D → EOF (0x04), Ctrl+L → clear (0x0c), Ctrl+A → bol (0x01)
  Ctrl+W → delete word (0x17), Ctrl+Z → suspend (0x1a)
  Arrows/F-keys/Home/End/PgUp/PgDn/Delete → correct VT100 escape sequences
"""

import html
import threading
import time

import pyte
from PySide6.QtCore import Qt, QTimer, QRect, QRectF, Signal, QObject
from PySide6.QtGui import (
    QFont, QFontMetrics, QKeyEvent, QTextOption,
    QPainter, QColor, QTextCursor
)
from PySide6.QtWidgets import (
    QTextEdit, QWidget, QVBoxLayout, QApplication
)


# ---------------------------------------------------------------------------
# Terminal colour palette (VS Code dark+)
# ---------------------------------------------------------------------------
ANSI_PALETTE = {
    "black":         "#000000",
    "red":           "#cd3131",
    "green":         "#0dbc79",
    "brown":         "#e5e510",
    "yellow":        "#e5e510",
    "blue":          "#2472c8",
    "magenta":       "#bc3fbc",
    "cyan":          "#11a8cd",
    "white":         "#e5e5e5",
    "brightblack":   "#666666",
    "brightred":     "#f14c4c",
    "brightgreen":   "#23d18b",
    "brightyellow":  "#f5f543",
    "brightblue":    "#3b8eea",
    "brightmagenta": "#d670d6",
    "brightcyan":    "#29b8db",
    "brightwhite":   "#ffffff",
}
DEFAULT_FG   = "#d4d4d4"
DEFAULT_BG   = "#0d1117"    # slightly blue-tinted dark – looks more like a
                             # real terminal than #1e1e1e
CURSOR_BG    = "#f0f0f0"    # solid white-ish block
CURSOR_FG    = "#0d1117"    # character drawn on top of cursor block


def _resolve(name: str, default: str) -> str:
    if not name or name == "default":
        return default
    if name in ANSI_PALETTE:
        return ANSI_PALETTE[name]
    if len(name) == 6 and all(c in "0123456789abcdefABCDEF" for c in name):
        return f"#{name}"
    return default


# ---------------------------------------------------------------------------
# Cursor overlay widget
# ---------------------------------------------------------------------------
class _CursorBlock(QWidget):
    """
    Paints a solid block cursor over the terminal text.
    This widget is a direct child of the TerminalWidget (NOT of the
    QTextEdit viewport) so QTextEdit.setHtml() can never disturb its
    Z-order.
    """
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.char = ""
        self._font = None

    def paintEvent(self, _event):
        p = QPainter(self)
        # 1. Solid bright block
        p.fillRect(self.rect(), QColor(CURSOR_BG))
        # 2. Re-draw the character on top so it stays readable
        if self.char and self._font:
            p.setFont(self._font)
            p.setPen(QColor(CURSOR_FG))
            p.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, self.char)
        p.end()


# ---------------------------------------------------------------------------
# Reader signals (emitted from background thread → main thread)
# ---------------------------------------------------------------------------
class _Signals(QObject):
    data        = Signal(bytes)
    disconnected = Signal(str)


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------
class TerminalWidget(QWidget):

    def __init__(self, ssh_session, cols: int = 120, rows: int = 32,
                 parent: QWidget = None):
        super().__init__(parent)
        self.ssh_session = ssh_session
        self.cols, self.rows = cols, rows

        # pyte screen
        self.screen = pyte.HistoryScreen(cols, rows, history=4000)
        self.screen.set_mode(pyte.modes.LNM)
        self.stream = pyte.ByteStream(self.screen)

        # monospace font
        self._font = QFont("Consolas", 11)
        self._font.setStyleHint(QFont.Monospace)
        self._font.setFixedPitch(True)
        fm = QFontMetrics(self._font)
        self._cw = fm.horizontalAdvance("M")   # char cell width
        self._ch = fm.height()                  # char cell height
        self._dm = 4                             # document margin (px)

        # read-only display widget
        self._te = QTextEdit(self)
        self._te.setReadOnly(True)
        self._te.setFont(self._font)
        self._te.setStyleSheet(
            f"QTextEdit {{ background:{DEFAULT_BG}; color:{DEFAULT_FG};"
            f" border:0; selection-background-color:#264f78; }}"
        )
        self._te.setLineWrapMode(QTextEdit.NoWrap)
        self._te.setWordWrapMode(QTextOption.NoWrap)
        self._te.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._te.setCursorWidth(0)            # hide Qt's own blinking cursor
        self._te.setContextMenuPolicy(Qt.NoContextMenu)
        self._te.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._te)

        # cursor block (child of self, NOT of the viewport)
        self._cur = _CursorBlock(self)
        self._cur._font = self._font
        self._cur.resize(self._cw, self._ch)
        self._cur.hide()

        # signals
        self._sig = _Signals()
        self._sig.data.connect(self._on_data)
        self._sig.disconnected.connect(self._on_disc)

        # state
        self._running  = False
        self._thread   = None
        self._last_html = None
        self._cur_vis   = True   # blink state

        # timers
        self._blink_t  = QTimer(self)
        self._blink_t.timeout.connect(self._blink)
        self._blink_t.start(530)

        self._draw_t = QTimer(self)
        self._draw_t.timeout.connect(self._redraw)
        self._draw_t.start(33)      # ~30 fps

        # event filters
        self._te.installEventFilter(self)
        self._te.viewport().installEventFilter(self)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, already_open: bool = False):
        if not already_open:
            self.ssh_session.open(
                term="xterm-256color", width=self.cols, height=self.rows
            )
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._blink_t.stop()
        self._draw_t.stop()
        try:
            self.ssh_session.close()
        except Exception:
            pass

    def set_focus(self):
        self._te.setFocus()

    def showEvent(self, e):
        super().showEvent(e)
        self.set_focus()

    # widget resize: keep cursor overlay within TerminalWidget bounds
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._reposition_cursor()

    # ------------------------------------------------------------------
    # Reader thread
    # ------------------------------------------------------------------

    def _reader(self):
        while self._running:
            try:
                data = self.ssh_session.recv(4096)
                if data:
                    self._sig.data.emit(data)
                else:
                    if not self.ssh_session.is_active():
                        self._sig.disconnected.emit("Connection closed")
                        return
                    time.sleep(0.02)
            except Exception as ex:
                self._sig.disconnected.emit(str(ex))
                return

    def _on_data(self, data: bytes):
        self.stream.feed(data)

    def _on_disc(self, reason: str):
        self._running = False
        self._cur.hide()
        self._te.append(
            f'<br><span style="color:#f14c4c">[Disconnected: {html.escape(reason)}]</span>'
        )

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _redraw(self):
        if not self._running:
            return

        # Build HTML only when screen has changed
        if not self.screen.dirty and self._last_html is not None:
            self._reposition_cursor()
            return

        lines = [self._line_html(self.screen.buffer[y])
                 for y in range(self.screen.lines)]
        body = "\n".join(lines)
        full = (
            f'<html><body style="background:{DEFAULT_BG};color:{DEFAULT_FG};'
            f'margin:0;padding:0;">'
            f'<pre style="margin:0;padding:{self._dm}px;'
            f'font-family:Consolas,monospace;font-size:11pt;white-space:pre;">'
            f'{body}</pre></body></html>'
        )

        if full == self._last_html:
            self.screen.dirty.clear()
            self._reposition_cursor()
            return
        self._last_html = full

        # Don't disrupt an active mouse selection
        if self._te.textCursor().hasSelection():
            self._reposition_cursor()
            return

        vb = self._te.verticalScrollBar()
        hb = self._te.horizontalScrollBar()
        at_bot = vb.value() >= vb.maximum() - 4
        ov, oh = vb.value(), hb.value()

        self._te.setHtml(full)

        vb.setValue(vb.maximum() if at_bot else ov)
        hb.setValue(oh)
        self.screen.dirty.clear()
        self._te.viewport().update()
        self._reposition_cursor()

    def _line_html(self, line) -> str:
        parts, run, style = [], [], None

        def flush():
            if run:
                txt = html.escape("".join(run))
                parts.append(f'<span style="{style}">{txt}</span>' if style else txt)

        for x in range(self.screen.columns):
            ch = line[x]
            s = self._char_style(ch)
            if s != style:
                flush(); run = []; style = s
            run.append(ch.data or " ")
        flush()
        return "".join(parts) or " "

    def _char_style(self, ch) -> str | None:
        fg = _resolve(ch.fg, DEFAULT_FG)
        bg = _resolve(ch.bg, None)
        if ch.reverse:
            fg, bg = bg or DEFAULT_BG, fg
        d = []
        if fg and fg != DEFAULT_FG:
            d.append(f"color:{fg}")
        if bg:
            d.append(f"background-color:{bg}")
        if ch.bold:
            d.append("font-weight:bold")
        if ch.italics:
            d.append("font-style:italic")
        ul = ch.underscore
        st = ch.strikethrough
        if ul and st:
            d.append("text-decoration:underline line-through")
        elif ul:
            d.append("text-decoration:underline")
        elif st:
            d.append("text-decoration:line-through")
        return ";".join(d) or None

    # ------------------------------------------------------------------
    # Cursor
    # ------------------------------------------------------------------

    def _blink(self):
        self._cur_vis = not self._cur_vis
        if self._running:
            if self._cur_vis:
                self._reposition_cursor()
            else:
                self._cur.hide()

    def _reposition_cursor(self):
        """
        Move _CursorBlock to the exact screen pixel of the pyte cursor.

        _CursorBlock is a child of TerminalWidget (self), so its
        coordinates are relative to self, not to the viewport.
        We compute the cursor's position in viewport space using
        documentLayout().blockBoundingRect(), then map to self's space
        by adding the viewport's offset within self.
        """
        if not self._running or not self._cur_vis:
            self._cur.hide()
            return

        cur = self.screen.cursor
        if cur.hidden:
            self._cur.hide()
            return

        doc   = self._te.document()
        block = doc.findBlockByLineNumber(cur.y)
        if not block.isValid():
            self._cur.hide()
            return

        # Position of this line within the document (document coordinates)
        br = doc.documentLayout().blockBoundingRect(block)

        # Subtract scroll offsets to get viewport coordinates
        vp_x = br.x() + cur.x * self._cw - self._te.horizontalScrollBar().value()
        vp_y = br.y()               - self._te.verticalScrollBar().value()

        # Cursor block is a child of self, not viewport.
        # Map viewport coords → self coords by adding the viewport's
        # top-left position relative to self.
        vp_pos = self._te.viewport().pos()          # viewport inside QTextEdit
        te_pos = self._te.pos()                      # QTextEdit inside self
        sx = int(vp_x) + vp_pos.x() + te_pos.x()
        sy = int(vp_y) + vp_pos.y() + te_pos.y()

        # Clip: hide cursor if it has scrolled off-screen
        vp = self._te.viewport()
        if not (0 <= int(vp_x) < vp.width() and 0 <= int(vp_y) < vp.height()):
            self._cur.hide()
            return

        # Update character drawn under cursor
        line = self.screen.buffer[cur.y]
        ch = line[cur.x]
        self._cur.char = ch.data if ch.data and ch.data.strip() else ""
        self._cur.move(sx, sy)
        self._cur.resize(self._cw, self._ch)
        self._cur.show()
        self._cur.raise_()       # always on top
        self._cur.update()

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        et = event.type()
        if et == event.Type.KeyPress:
            return self._key(event)
        if et == event.Type.MouseButtonPress:
            if event.button() == Qt.RightButton:
                self._paste()
                return True
        if et == event.Type.MouseButtonRelease:
            if event.button() == Qt.LeftButton:
                QTimer.singleShot(0, self._auto_copy)
        return super().eventFilter(obj, event)

    def _auto_copy(self):
        cur = self._te.textCursor()
        if cur.hasSelection():
            self.copy_selection()

    def _key(self, ev: QKeyEvent) -> bool:
        key  = ev.key()
        mods = ev.modifiers()
        ctrl  = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)
        sel   = self._te.textCursor().hasSelection()

        # Copy / paste
        if ctrl and key == Qt.Key_C:
            if shift or sel:
                self.copy_selection(); return True
            self._send(b"\x03"); return True    # SIGINT
        if ctrl and shift and key == Qt.Key_C:
            self.copy_selection(); return True
        if ctrl and key == Qt.Key_V:
            self._paste(); return True
        if ctrl and shift and key == Qt.Key_V:
            self._paste(); return True
        if ctrl and key == Qt.Key_Insert:
            self.copy_selection(); return True
        if shift and key == Qt.Key_Insert:
            self._paste(); return True

        # Special keys
        SPECIAL = {
            Qt.Key_Return:   b"\r",
            Qt.Key_Enter:    b"\r",
            Qt.Key_Backspace: b"\x7f",
            Qt.Key_Tab:      b"\t",
            Qt.Key_Escape:   b"\x1b",
            Qt.Key_Space:    b" ",
            Qt.Key_Up:       b"\x1b[A",
            Qt.Key_Down:     b"\x1b[B",
            Qt.Key_Right:    b"\x1b[C",
            Qt.Key_Left:     b"\x1b[D",
            Qt.Key_Home:     b"\x1b[H",
            Qt.Key_End:      b"\x1b[F",
            Qt.Key_Insert:   b"\x1b[2~",
            Qt.Key_Delete:   b"\x1b[3~",
            Qt.Key_PageUp:   b"\x1b[5~",
            Qt.Key_PageDown: b"\x1b[6~",
            Qt.Key_F1:       b"\x1bOP",
            Qt.Key_F2:       b"\x1bOQ",
            Qt.Key_F3:       b"\x1bOR",
            Qt.Key_F4:       b"\x1bOS",
            Qt.Key_F5:       b"\x1b[15~",
            Qt.Key_F6:       b"\x1b[17~",
            Qt.Key_F7:       b"\x1b[18~",
            Qt.Key_F8:       b"\x1b[19~",
            Qt.Key_F9:       b"\x1b[20~",
            Qt.Key_F10:      b"\x1b[21~",
            Qt.Key_F11:      b"\x1b[23~",
            Qt.Key_F12:      b"\x1b[24~",
        }
        if key in SPECIAL:
            self._send(SPECIAL[key]); return True

        # Ctrl+letter → control character (derived from key code, not text)
        if ctrl and not shift and Qt.Key_A <= key <= Qt.Key_Z:
            self._send(bytes([key - Qt.Key_A + 1])); return True

        # Ctrl+punctuation
        CPUNCT = {
            Qt.Key_BracketLeft:  b"\x1b",
            Qt.Key_Backslash:    b"\x1c",
            Qt.Key_BracketRight: b"\x1d",
            Qt.Key_AsciiCircum:  b"\x1e",
            Qt.Key_Underscore:   b"\x1f",
        }
        if ctrl and not shift and key in CPUNCT:
            self._send(CPUNCT[key]); return True

        # Plain text
        text = ev.text()
        if text and not ctrl:
            self._send(text.encode("utf-8", errors="ignore")); return True

        return False

    # ------------------------------------------------------------------
    # Send / clipboard
    # ------------------------------------------------------------------

    def _send(self, data: bytes):
        # Clear any selection so the user's typing resumes normally
        cur = self._te.textCursor()
        if cur.hasSelection():
            cur.clearSelection()
            self._te.setTextCursor(cur)
        self._last_html = None   # force next redraw
        try:
            self.ssh_session.send(data)
        except Exception:
            pass

    def copy_selection(self):
        cur = self._te.textCursor()
        if cur.hasSelection():
            QApplication.clipboard().setText(
                cur.selectedText().replace("\u2029", "\n")
            )

    def _paste(self):
        txt = QApplication.clipboard().text()
        if txt:
            self._send(txt.encode("utf-8", errors="ignore"))

    # ------------------------------------------------------------------
    # Resize PTY
    # ------------------------------------------------------------------

    def resize_terminal(self, cols: int, rows: int):
        self.cols, self.rows = cols, rows
        self.screen.resize(rows, cols)
        self._last_html = None
        try:
            self.ssh_session.resize_pty(cols, rows)
        except Exception:
            pass