"""
ui/main_window.py
Main application window.

Key UX features (Termius/Cursor-inspired):
  - Collapsible host tree sidebar (Ctrl+Shift+B)
  - Tabs with always-visible close buttons and live status dots
    (connecting / connected / error) via ClosableTabWidget
  - PARALLEL, non-blocking connections: firing 5 connects in a row no
    longer queues behind modal dialogs - each runs on its own thread and
    reports into a small non-modal "Connections" panel
  - Auto-focus: switching tabs focuses the terminal/file list in that tab
  - Keyboard shortcuts: Ctrl+Shift+N quick connect, Ctrl+Shift+T local
    terminal, Ctrl+Shift+W close tab, Ctrl+Tab / Ctrl+Shift+Tab cycle tabs,
    Alt+1..9 jump to tab N, Ctrl+Shift+P command palette, Ctrl+Shift+F
    focus host search, Ctrl+Shift+B toggle sidebar. App shortcuts
    deliberately avoid Ctrl+T/Ctrl+W/Ctrl+B/Ctrl+A/Ctrl+L/Ctrl+C/etc. so
    those keep their standard shell/readline/tmux meanings inside terminals.
  - Local terminal session (manual shell, no SSH)
  - "Connect All" for a group (or all hosts) - opens N terminals in
    parallel, double-click a group to do the same
  - SFTP file editing with syntax highlighting (double-click text files)

Design notes (for future maintainers):
  - `open_sessions` is the single source of truth for what's open in each
    tab; close_tab() tears down resources and re-keys indices.
  - Host CRUD logic that's reusable (duplicate, chain resolution) lives in
    db.repository, not duplicated here.
  - Connection setup uses ui.connection_manager.ConnectionManager (NOT
    ui.progress, which remains for short file operations inside SFTP).
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter,
    QMessageBox, QInputDialog, QFileDialog, QToolButton, QLabel
)

from db.models import Host, Group
from db.repository import duplicate_host
from db.database import export_vault, salt_path_for_db
from core.ssh_session import SSHSession, resolve_chain, HostConfig
from core.local_session import LocalSession
from core.sftp_manager import SFTPManager

from ui.host_tree import HostTree
from ui.host_dialog import HostDialog
from ui.terminal_widget import TerminalWidget
from ui.sftp_browser import SFTPBrowser
from ui.dual_sftp_view import DualSFTPView
from ui.snippet_manager import SnippetManagerDialog
from ui.port_forward_dialog import PortForwardDialog
from ui.quick_connect_dialog import QuickConnectDialog
from ui.host_picker_dialog import HostPickerDialog
from ui.closable_tab_widget import ClosableTabWidget
from ui.connection_manager import ConnectionManager, ConnectionPanel
from ui.command_palette import CommandPaletteDialog
from ui.code_editor import CodeEditor
from ui.shortcuts import apply_shortcuts, ShortcutSettingsDialog
from ui.shell_settings_dialog import ShellSettingsDialog


class MainWindow(QMainWindow):
    def __init__(self, db_session, vault, db_path):
        super().__init__()
        self.db = db_session
        self.vault = vault
        self.db_path = db_path

        self.setWindowTitle("PyTermSSH - SSH / SFTP Client")
        self.resize(1280, 800)

        # --- Sidebar (collapsible) ---
        self.host_tree = HostTree(self.db)
        self.host_tree.connect_requested.connect(self.open_terminal_for_host)
        self.host_tree.sftp_requested.connect(self.open_sftp_for_host)
        self.host_tree.dual_sftp_requested.connect(self.open_dual_sftp_for_host)
        self.host_tree.edit_host_requested.connect(self.edit_host)
        self.host_tree.duplicate_host_requested.connect(self.duplicate_host)
        self.host_tree.new_host_requested.connect(self.new_host)
        self.host_tree.new_group_requested.connect(self.new_group)
        self.host_tree.delete_host_requested.connect(self.delete_host)
        self.host_tree.delete_group_requested.connect(self.delete_group)
        self.host_tree.connect_all_requested.connect(self.connect_all_hosts)

        self.sidebar_container = QWidget()
        sidebar_layout = QVBoxLayout(self.sidebar_container)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        sidebar_layout.addWidget(self.host_tree)

        # --- Tabs (custom widget: visible close buttons + status dots) ---
        self.tabs = ClosableTabWidget()
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.new_tab_requested.connect(self.quick_connect)
        self.tabs.tab_duplicate_requested.connect(self.duplicate_tab)
        self.tabs.close_others_requested.connect(self.close_other_tabs)
        self.tabs.close_all_requested.connect(self.close_all_tabs)

        # Toggle sidebar button lives in the tab corner so it's always visible
        self.toggle_sidebar_btn = QToolButton()
        self.toggle_sidebar_btn.setText("\u00ab")
        self.toggle_sidebar_btn.setToolTip("Hide sidebar (Ctrl+Shift+B)")
        self.toggle_sidebar_btn.clicked.connect(self.toggle_sidebar)
        self.tabs.setCornerWidget(self.toggle_sidebar_btn, Qt.TopLeftCorner)

        # --- Connections panel (non-blocking, parallel connects) ---
        self.connection_panel = ConnectionPanel()
        self.connection_manager = ConnectionManager(self.connection_panel)

        right_side = QWidget()
        right_layout = QVBoxLayout(right_side)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.tabs)
        right_layout.addWidget(self.connection_panel)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.sidebar_container)
        self.splitter.addWidget(right_side)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([280, 1000])
        self._sidebar_width = 280
        self._sidebar_visible = True

        self.setCentralWidget(self.splitter)

        self._build_menu()
        self._build_status_bar()
        self._build_shortcuts()

        # tab_index -> dict with keys depending on type:
        #   terminal:  type, ssh_session, host_id, widget, label
        #   sftp:      type, ssh_session, sftp, host_id, widget, label
        #   dual_sftp: type, sessions=[...], sftps=[...], widget, label
        #   editor:    type, widget, label
        #   local:     type, ssh_session(LocalSession), host_id=None, widget, label
        self.open_sessions = {}

        # Open a local shell by default, like opening a terminal app -
        # gives an immediate "empty terminal" without any menu interaction.
        self.open_local_terminal()

    # ------------------------------------------------------------------
    # Menu / status bar / shortcuts
    # ------------------------------------------------------------------

    def _build_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        file_menu.addAction("Quick Connect (Manual SSH)...\tCtrl+Shift+N", self.quick_connect)
        file_menu.addAction("New Local Terminal\tCtrl+Shift+T", self.open_local_terminal)
        file_menu.addSeparator()
        file_menu.addAction("New Host...", lambda: self.new_host(None))
        file_menu.addAction("New Group...", lambda: self.new_group(None))
        file_menu.addSeparator()

        export_action = QAction("Export Vault (share with someone)...", self)
        export_action.triggered.connect(self.export_vault)
        file_menu.addAction(export_action)

        switch_vault_action = QAction("Switch Vault...", self)
        switch_vault_action.triggered.connect(self.switch_vault)
        file_menu.addAction(switch_vault_action)

        file_menu.addSeparator()
        toggle_action = QAction("Toggle Sidebar\tCtrl+Shift+B", self)
        toggle_action.triggered.connect(self.toggle_sidebar)
        file_menu.addAction(toggle_action)

        file_menu.addSeparator()
        file_menu.addAction("Close Tab\tCtrl+Shift+W", self.close_current_tab)
        file_menu.addAction("Exit", self.close)

        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction("Command Palette...\tCtrl+Shift+P", self.open_command_palette)
        tools_menu.addAction("Snippet Manager...", self.open_snippet_manager)
        tools_menu.addAction("Port Forwarding (active tab)...", self.open_port_forwarding)
        tools_menu.addSeparator()
        tools_menu.addAction("Customize Shortcuts...", self.open_shortcut_settings)
        tools_menu.addAction("Local Shell Settings...", self.open_shell_settings)

        view_menu = menubar.addMenu("&View")
        view_menu.addAction("Next Tab\tCtrl+Tab", self.next_tab)
        view_menu.addAction("Previous Tab\tCtrl+Shift+Tab", self.previous_tab)
        view_menu.addAction("Focus Host Search\tCtrl+Shift+F", self.focus_host_search)

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction("Keyboard Shortcuts", self._show_shortcuts)
        help_menu.addAction("About", self._show_about)

    def _build_status_bar(self):
        sb = self.statusBar()
        self.db_path_label = QLabel(f"Vault: {self.db_path}")
        self.db_path_label.setStyleSheet("color: #8a8a8a; padding-left: 6px;")
        sb.addPermanentWidget(self.db_path_label)

    def _build_shortcuts(self):
        # Customizable app-chrome shortcuts (Tools -> Customize Shortcuts).
        # NOTE: Ctrl+T/Ctrl+W/Ctrl+B/etc. are real readline/tmux control
        # sequences that terminals must receive when focused, so defaults
        # use Ctrl+Shift+<key> and the customization dialog blocks reserved
        # combos. See ui/shortcuts.py.
        apply_shortcuts(self, self.db)

        # Jump to tab N (Alt+1..9) - fixed, not user-customizable since it's
        # a simple numeric range and Alt+digit rarely collides with shells.
        for i in range(1, 10):
            QShortcut(QKeySequence(f"Alt+{i}"), self).activated.connect(
                lambda idx=i - 1: self._jump_to_tab(idx)
            )

    def _show_about(self):
        QMessageBox.information(
            self, "About",
            "PyTermSSH\n\nModular SSH/SFTP client with local SQLite storage,\n"
            "SSH chaining (jump hosts), parallel connections, port\n"
            "forwarding, snippets, dual-pane SFTP transfers, syntax-\n"
            "highlighted file editing, and a command palette.\n\n"
            "Vaults (database + encryption salt) can be exported and shared:\n"
            "File -> Export Vault."
        )

    def _show_shortcuts(self):
        QMessageBox.information(
            self, "Keyboard Shortcuts",
            "Ctrl+Shift+N    Quick Connect (manual SSH)\n"
            "Ctrl+Shift+T    New Local Terminal\n"
            "Ctrl+Shift+W    Close current tab\n"
            "Ctrl+Tab        Next tab\n"
            "Ctrl+Shift+Tab  Previous tab\n"
            "Alt+1..9        Jump to tab 1-9\n"
            "Ctrl+Shift+B    Toggle sidebar\n"
            "Ctrl+Shift+F    Focus host search\n"
            "Ctrl+Shift+P    Command palette\n"
            "Ctrl+S          Save file (in file editor tabs)\n"
            "\n"
            "In the terminal (standard shell/readline behavior):\n"
            "  Ctrl+C          Copy selection if text is selected,\n"
            "                  otherwise send SIGINT (interrupt)\n"
            "  Ctrl+Shift+C    Always copy selection\n"
            "  Ctrl+V          Paste\n"
            "  Ctrl+D          Send EOF\n"
            "  Ctrl+L          Clear screen\n"
            "  Ctrl+A / Ctrl+E Beginning / end of line\n"
            "  Ctrl+W          Delete word backward\n"
            "  Ctrl+B          tmux prefix (or backward-char)\n"
            "  Ctrl+R          Reverse history search\n"
            "\n"
            "Double-click a group in the sidebar to connect to every host\n"
            "in it at once (in parallel). Right-click a tab to Duplicate,\n"
            "Close Others, or Close All. Click '+' to start a new connection."
        )

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------

    def toggle_sidebar(self):
        if self._sidebar_visible:
            sizes = self.splitter.sizes()
            self._sidebar_width = max(sizes[0], 150)
            self.sidebar_container.setVisible(False)
            self.toggle_sidebar_btn.setText("\u00bb")
            self.toggle_sidebar_btn.setToolTip("Show sidebar (Ctrl+Shift+B)")
        else:
            self.sidebar_container.setVisible(True)
            total = sum(self.splitter.sizes()) or 1280
            self.splitter.setSizes([self._sidebar_width, max(total - self._sidebar_width, 200)])
            self.toggle_sidebar_btn.setText("\u00ab")
            self.toggle_sidebar_btn.setToolTip("Hide sidebar (Ctrl+Shift+B)")
        self._sidebar_visible = not self._sidebar_visible

    def focus_host_search(self):
        if not self._sidebar_visible:
            self.toggle_sidebar()
        self.host_tree.search_box.setFocus()
        self.host_tree.search_box.selectAll()

    # ------------------------------------------------------------------
    # Host / Group CRUD
    # ------------------------------------------------------------------

    def new_host(self, group_id):
        dlg = HostDialog(self.db, self.vault, default_group_id=group_id, parent=self)
        if dlg.exec():
            self.host_tree.refresh()

    def edit_host(self, host_id):
        dlg = HostDialog(self.db, self.vault, host_id=host_id, parent=self)
        if dlg.exec():
            self.host_tree.refresh()

    def duplicate_host(self, host_id):
        try:
            new_host = duplicate_host(self.db, host_id)
        except Exception as e:
            QMessageBox.critical(self, "Duplicate Error", str(e))
            return
        self.host_tree.refresh()
        self.edit_host(new_host.id)

    def delete_host(self, host_id):
        host = self.db.query(Host).get(host_id)
        if not host:
            return
        confirm = QMessageBox.question(
            self, "Delete Host", f"Delete host '{host.label}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.db.delete(host)
            self.db.commit()
            self.host_tree.refresh()

    def new_group(self, parent_group_id):
        name, ok = QInputDialog.getText(self, "New Group", "Group name:")
        if ok and name:
            g = Group(name=name, parent_id=parent_group_id)
            self.db.add(g)
            self.db.commit()
            self.host_tree.refresh()

    def delete_group(self, group_id):
        group = self.db.query(Group).get(group_id)
        if not group:
            return
        confirm = QMessageBox.question(
            self, "Delete Group",
            f"Delete group '{group.name}' and ungroup its hosts?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            for h in self.db.query(Host).filter(Host.group_id == group_id).all():
                h.group_id = None
            self.db.delete(group)
            self.db.commit()
            self.host_tree.refresh()

    # ------------------------------------------------------------------
    # Vault export
    # ------------------------------------------------------------------

    def export_vault(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Vault", "PyTermSSH_Vault.zip", "Vault Archive (*.zip)"
        )
        if not path:
            return
        salt_path = salt_path_for_db(self.db_path)
        try:
            export_vault(self.db_path, salt_path, path)
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))
            return
        QMessageBox.information(
            self, "Vault Exported",
            f"Vault exported to:\n{path}\n\n"
            "Share this file along with your master password (sent "
            "separately) - the recipient should pick 'Open a shared "
            "vault file' on the startup screen and enter that password "
            "to unlock it with every host you saved."
        )

    def switch_vault(self):
        """Forget the remembered vault and restart so the picker dialog
        appears again. Used to switch between multiple vaults (e.g. work
        vs personal, or a USB-drive portable vault)."""
        confirm = QMessageBox.question(
            self, "Switch Vault",
            "This will close PyTermSSH and ask you to choose a vault "
            "the next time it starts.\n\n"
            "Your current vault and all saved hosts remain untouched - "
            "you can switch back to it anytime via the same picker.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        from db.database import clear_last_vault
        clear_last_vault()

        QMessageBox.information(
            self, "Restart Required",
            "PyTermSSH will now close. Start it again to choose a vault."
        )
        self.close()

    # ------------------------------------------------------------------
    # Connection helpers (parallel, non-blocking)
    # ------------------------------------------------------------------

    def _build_session(self, host_id):
        host = self.db.query(Host).get(host_id)
        if not host:
            raise ValueError("Host not found")
        hop_configs = resolve_chain(host, self.db, self.vault)
        session = SSHSession(hop_configs)
        return host, session

    def open_terminal_for_host(self, host_id):
        try:
            host, session = self._build_session(host_id)
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))
            return

        # Reserve a tab immediately so the user sees something is happening
        # (status dot starts as "connecting") - this is what makes parallel
        # connects feel responsive: tabs appear instantly, fill in as each
        # connection completes.
        placeholder = QWidget()
        idx = self.tabs.addTab(placeholder, f"SSH: {host.label}")
        self.tabs.set_tab_status(idx, "connecting")
        self.tabs.setCurrentIndex(idx)

        def connect_task():
            session.open(term=host.terminal_type, width=120, height=32)
            return session

        def on_success(_session):
            real_idx = self._index_of_widget(placeholder)
            if real_idx is None:
                _session.close()
                return

            term_widget = TerminalWidget(_session, cols=120, rows=32)
            term_widget.start(already_open=True)

            if host.startup_snippet_id:
                try:
                    snippet = host.startup_snippet
                    if snippet and snippet.content:
                        _session.send((snippet.content + "\n").encode("utf-8"))
                except Exception:
                    pass

            self.tabs.removeTab(real_idx)
            new_idx = self.tabs.insertTab(real_idx, term_widget, f"SSH: {host.label}")
            self.tabs.set_tab_status(new_idx, "connected")
            self.open_sessions[new_idx] = {
                "type": "terminal", "ssh_session": _session,
                "host_id": host_id, "widget": term_widget, "label": host.label
            }
            if self.tabs.currentIndex() == new_idx:
                term_widget.set_focus()

        def on_error(msg):
            real_idx = self._index_of_widget(placeholder)
            if real_idx is not None:
                self.tabs.set_tab_status(real_idx, "error")
                self.tabs.setTabToolTip(real_idx, f"Connection failed: {msg}")
            QMessageBox.critical(self, "Connection Error", f"Could not connect to {host.label}:\n{msg}")

        self.connection_manager.connect(f"{host.label} (SSH)", connect_task, on_success, on_error)

    def open_sftp_for_host(self, host_id):
        try:
            host, session = self._build_session(host_id)
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))
            return

        placeholder = QWidget()
        idx = self.tabs.addTab(placeholder, f"SFTP: {host.label}")
        self.tabs.set_tab_status(idx, "connecting")
        self.tabs.setCurrentIndex(idx)

        def connect_task():
            session.open(term=host.terminal_type, width=80, height=24)
            sftp = SFTPManager(session)
            return session, sftp

        def on_success(result):
            _session, sftp = result
            real_idx = self._index_of_widget(placeholder)
            if real_idx is None:
                sftp.close()
                _session.close()
                return

            browser = SFTPBrowser(sftp, title=host.label)
            browser.edit_file_requested.connect(self._open_file_editor)

            self.tabs.removeTab(real_idx)
            new_idx = self.tabs.insertTab(real_idx, browser, f"SFTP: {host.label}")
            self.tabs.set_tab_status(new_idx, "connected")
            self.open_sessions[new_idx] = {
                "type": "sftp", "ssh_session": _session, "sftp": sftp,
                "host_id": host_id, "widget": browser, "label": host.label
            }
            if self.tabs.currentIndex() == new_idx:
                browser.set_focus()

        def on_error(msg):
            real_idx = self._index_of_widget(placeholder)
            if real_idx is not None:
                self.tabs.set_tab_status(real_idx, "error")
                self.tabs.setTabToolTip(real_idx, f"Connection failed: {msg}")
            QMessageBox.critical(self, "Connection Error", f"Could not open SFTP on {host.label}:\n{msg}")

        self.connection_manager.connect(f"{host.label} (SFTP)", connect_task, on_success, on_error)

    def open_dual_sftp_for_host(self, host_id):
        """Open the dual-pane SFTP transfer view, with the left pane set to
        the chosen host. The user then picks a second host for the right
        pane."""
        picker = HostPickerDialog(self.db, title="Choose second host for transfer", exclude_host_id=host_id, parent=self)
        if not picker.exec() or picker.selected_host_id is None:
            return
        other_host_id = picker.selected_host_id

        try:
            host_a, session_a = self._build_session(host_id)
            host_b, session_b = self._build_session(other_host_id)
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))
            return

        placeholder = QWidget()
        idx = self.tabs.addTab(placeholder, f"Transfer: {host_a.label} \u2194 {host_b.label}")
        self.tabs.set_tab_status(idx, "connecting")
        self.tabs.setCurrentIndex(idx)

        def connect_task():
            session_a.open(term=host_a.terminal_type, width=80, height=24)
            session_b.open(term=host_b.terminal_type, width=80, height=24)
            sftp_a = SFTPManager(session_a)
            sftp_b = SFTPManager(session_b)
            return (session_a, sftp_a, host_a), (session_b, sftp_b, host_b)

        def on_success(result):
            (sa, fa, ha), (sb, fb, hb) = result
            real_idx = self._index_of_widget(placeholder)
            if real_idx is None:
                for s in (sa, sb):
                    s.close()
                return

            view = DualSFTPView(fa, ha.label, fb, hb.label)
            view.left.edit_file_requested.connect(self._open_file_editor)
            view.right.edit_file_requested.connect(self._open_file_editor)

            label = f"Transfer: {ha.label} \u2194 {hb.label}"
            self.tabs.removeTab(real_idx)
            new_idx = self.tabs.insertTab(real_idx, view, label)
            self.tabs.set_tab_status(new_idx, "connected")
            self.open_sessions[new_idx] = {
                "type": "dual_sftp",
                "sessions": [sa, sb],
                "sftps": [fa, fb],
                "widget": view,
                "label": label,
            }
            if self.tabs.currentIndex() == new_idx:
                view.set_focus()

        def on_error(msg):
            real_idx = self._index_of_widget(placeholder)
            if real_idx is not None:
                self.tabs.set_tab_status(real_idx, "error")
                self.tabs.setTabToolTip(real_idx, f"Connection failed: {msg}")
            QMessageBox.critical(self, "Connection Error", f"Could not open dual SFTP view:\n{msg}")

        self.connection_manager.connect(
            f"{host_a.label} \u2194 {host_b.label} (Transfer)", connect_task, on_success, on_error
        )

    def quick_connect(self):
        dlg = QuickConnectDialog(parent=self)
        if not dlg.exec() or not dlg.host_config:
            return

        host_config: HostConfig = dlg.host_config
        session = SSHSession([host_config])

        placeholder = QWidget()
        idx = self.tabs.addTab(placeholder, f"SSH: {host_config.hostname}")
        self.tabs.set_tab_status(idx, "connecting")
        self.tabs.setCurrentIndex(idx)

        def connect_task():
            session.open(term="xterm-256color", width=120, height=32)
            return session

        def on_success(_session):
            real_idx = self._index_of_widget(placeholder)
            if real_idx is None:
                _session.close()
                return
            term_widget = TerminalWidget(_session, cols=120, rows=32)
            term_widget.start(already_open=True)

            self.tabs.removeTab(real_idx)
            new_idx = self.tabs.insertTab(real_idx, term_widget, f"SSH: {host_config.hostname}")
            self.tabs.set_tab_status(new_idx, "connected")
            self.open_sessions[new_idx] = {
                "type": "terminal", "ssh_session": _session,
                "host_id": None, "widget": term_widget, "label": host_config.hostname
            }
            if self.tabs.currentIndex() == new_idx:
                term_widget.set_focus()

        def on_error(msg):
            real_idx = self._index_of_widget(placeholder)
            if real_idx is not None:
                self.tabs.set_tab_status(real_idx, "error")
                self.tabs.setTabToolTip(real_idx, f"Connection failed: {msg}")
            QMessageBox.critical(self, "Connection Error", f"Could not connect:\n{msg}")

        self.connection_manager.connect(
            f"{host_config.hostname} (Quick Connect)", connect_task, on_success, on_error
        )

    def open_local_terminal(self):
        """
        Open a local terminal tab - MobaXterm-style.

        On Windows: uses the bundled BusyBox environment (ls, grep, ssh,
        vi, find, etc. all work out of the box). If BusyBox hasn't been
        downloaded yet, offers to download it first (~1.2 MB, one time).
        Falls back to PowerShell/cmd if user declines.

        On Linux/macOS: uses the system $SHELL (bash/zsh/etc.).
        """
        import os

        # Windows first-launch: check if BusyBox is ready
        if os.name == "nt":
            try:
                from core.bundled_env import busybox_available
                if not busybox_available():
                    reply = QMessageBox.question(
                        self,
                        "Set Up Local Terminal",
                        "PyTermSSH bundles a self-contained Unix environment\n"
                        "(similar to MobaXterm's local terminal) that gives you:\n\n"
                        "  • ls, grep, cat, find, awk, sed, vi, wget\n"
                        "  • ssh user@hostname  (connect to any server)\n"
                        "  • cd /c/Users/YourName  (Windows drives as /c/ /d/)\n"
                        "  • 300+ Unix commands — no install required\n\n"
                        "This requires a one-time download of ~1.2 MB (BusyBox).\n"
                        "Download now?",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply == QMessageBox.Yes:
                        self.open_shell_settings()
                        # After dialog closes, re-check
                        if not busybox_available():
                            # User closed without downloading, fall through
                            # to PowerShell fallback
                            pass
            except ImportError:
                pass

        from ui.shell_settings_dialog import get_shell_argv
        shell_argv = get_shell_argv(self.db)
        session = LocalSession(shell_argv=shell_argv)
        try:
            session.open(term="xterm-256color", width=120, height=32)
        except Exception as e:
            # The configured shell failed to start (e.g. BusyBox was
            # deleted by antivirus, WSL was uninstalled, etc.). Don't just
            # show an error and leave the user stuck - fall back to a
            # shell that's always present on Windows.
            fallback_argv = ["powershell.exe", "-NoLogo", "-NoExit"] if os.name == "nt" else ["/bin/sh"]
            try:
                session = LocalSession(shell_argv=fallback_argv)
                session.open(term="xterm-256color", width=120, height=32)
                shell_argv = fallback_argv
                QMessageBox.warning(
                    self, "Switched to Fallback Shell",
                    f"Your configured local shell could not start:\n{e}\n\n"
                    "Opened PowerShell instead. Go to Tools → Local Shell "
                    "Settings to fix or re-download your preferred shell."
                )
            except Exception as e2:
                QMessageBox.critical(self, "Error",
                    f"Could not start any local shell:\n{e2}\n\n"
                    "Try Tools → Local Shell Settings.")
                return

        # Label shows which shell we're using
        exe_name = shell_argv[0].split("\\")[-1].split("/")[-1] if shell_argv else "Shell"
        if "busybox" in exe_name.lower():
            label = "Local Terminal"
        else:
            label = f"Local: {exe_name}"

        term_widget = TerminalWidget(session, cols=120, rows=32)
        term_widget.start(already_open=True)

        idx = self.tabs.addTab(term_widget, label)
        self.tabs.set_tab_status(idx, "connected")
        self.tabs.setCurrentIndex(idx)
        self.open_sessions[idx] = {
            "type": "local", "ssh_session": session,
            "host_id": None, "widget": term_widget, "label": label
        }
        term_widget.set_focus()

    def connect_all_hosts(self, host_ids):
        """Open a terminal for every host id in the list, all in parallel.
        Used by 'Connect All' on a group or the whole host list, and by
        double-clicking a group in the sidebar."""
        if not host_ids:
            return
        if len(host_ids) > 1:
            confirm = QMessageBox.question(
                self, "Connect All",
                f"Open {len(host_ids)} SSH connections in parallel?",
                QMessageBox.Yes | QMessageBox.No
            )
            if confirm != QMessageBox.Yes:
                return
        for host_id in host_ids:
            self.open_terminal_for_host(host_id)

    # ------------------------------------------------------------------
    # File editor (from SFTP double-click)
    # ------------------------------------------------------------------

    def _open_file_editor(self, title, content, save_callback):
        editor = CodeEditor(title, content, on_save=save_callback)
        idx = self.tabs.addTab(editor, f"Edit: {title}")
        self.tabs.set_tab_status(idx, "connected")
        self.tabs.setCurrentIndex(idx)
        self.open_sessions[idx] = {
            "type": "editor", "widget": editor, "label": title
        }
        editor.set_focus()

    # ------------------------------------------------------------------
    # Tab / focus management
    # ------------------------------------------------------------------

    def _index_of_widget(self, widget):
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) is widget:
                return i
        return None

    def _on_tab_changed(self, index):
        info = self.open_sessions.get(index)
        if info and "widget" in info:
            widget = info["widget"]
            if hasattr(widget, "set_focus"):
                QTimer.singleShot(0, widget.set_focus)

    def next_tab(self):
        if self.tabs.count() == 0:
            return
        idx = (self.tabs.currentIndex() + 1) % self.tabs.count()
        self.tabs.setCurrentIndex(idx)

    def previous_tab(self):
        if self.tabs.count() == 0:
            return
        idx = (self.tabs.currentIndex() - 1) % self.tabs.count()
        self.tabs.setCurrentIndex(idx)

    def _jump_to_tab(self, index):
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)

    def close_current_tab(self):
        idx = self.tabs.currentIndex()
        if idx >= 0:
            self.close_tab(idx)

    def close_other_tabs(self, keep_index):
        # Close from the end inward so indices above keep_index don't shift
        # underneath us; recompute keep_index as we go.
        for idx in reversed(range(self.tabs.count())):
            if idx == keep_index:
                continue
            self.close_tab(idx)
            if idx < keep_index:
                keep_index -= 1

    def close_all_tabs(self):
        for idx in reversed(range(self.tabs.count())):
            self.close_tab(idx)

    def duplicate_tab(self, index):
        """Open a new tab that reconnects with the same parameters as the
        tab at `index` (right-click -> Duplicate Tab)."""
        info = self.open_sessions.get(index)
        if not info:
            return
        t = info["type"]
        if t == "terminal" and info.get("host_id") is not None:
            self.open_terminal_for_host(info["host_id"])
        elif t == "sftp" and info.get("host_id") is not None:
            self.open_sftp_for_host(info["host_id"])
        elif t == "local":
            self.open_local_terminal()
        elif t == "dual_sftp":
            QMessageBox.information(
                self, "Duplicate",
                "Dual-pane transfer tabs can't be duplicated automatically - "
                "open a new one via 'Open Dual-Pane SFTP (Transfer)'."
            )
        else:
            QMessageBox.information(self, "Duplicate", "This tab type can't be duplicated.")

    def close_tab(self, index):
        session_info = self.open_sessions.pop(index, None)
        if session_info:
            try:
                t = session_info["type"]
                if t in ("terminal", "local"):
                    session_info["widget"].stop()
                elif t == "sftp":
                    session_info["sftp"].close()
                    session_info["ssh_session"].close()
                elif t == "dual_sftp":
                    session_info["widget"].close_all()
                    for s in session_info["sessions"]:
                        s.close()
                # "editor" tabs hold no external resources
            except Exception:
                pass

        self.tabs.removeTab(index)

        # re-key open_sessions after removal (indices shift)
        new_sessions = {}
        for old_idx, info in self.open_sessions.items():
            new_idx = old_idx - 1 if old_idx > index else old_idx
            new_sessions[new_idx] = info
        self.open_sessions = new_sessions

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def open_snippet_manager(self):
        current_idx = self.tabs.currentIndex()
        session_info = self.open_sessions.get(current_idx)
        ssh_session = None
        if session_info and session_info["type"] in ("terminal", "local"):
            ssh_session = session_info["ssh_session"]
        dlg = SnippetManagerDialog(self.db, ssh_session=ssh_session, parent=self)
        dlg.exec()

    def open_port_forwarding(self):
        current_idx = self.tabs.currentIndex()
        session_info = self.open_sessions.get(current_idx)
        if not session_info or session_info.get("host_id") is None:
            QMessageBox.information(
                self, "Info",
                "Open a connection tab for a saved host first (Quick Connect "
                "and Local Terminal sessions don't support port-forward rules)."
            )
            return
        host = self.db.query(Host).get(session_info["host_id"])
        dlg = PortForwardDialog(self.db, host, ssh_session=session_info["ssh_session"], parent=self)
        dlg.exec()

    def open_shortcut_settings(self):
        dlg = ShortcutSettingsDialog(self.db, parent=self)
        if dlg.exec():
            # Rebuild shortcuts with new bindings immediately
            apply_shortcuts(self, self.db)
            QMessageBox.information(self, "Shortcuts Updated",
                "Keyboard shortcuts have been updated and are active now.")

    def open_shell_settings(self):
        dlg = ShellSettingsDialog(self.db, parent=self)
        dlg.exec()

    def open_command_palette(self):
        commands = self._build_command_list()
        dlg = CommandPaletteDialog(commands, parent=self)
        if dlg.exec() and dlg.selected_callback:
            dlg.selected_callback()

    def _build_command_list(self):
        commands = [
            ("Quick Connect (Manual SSH)", self.quick_connect),
            ("New Local Terminal", self.open_local_terminal),
            ("New Host...", lambda: self.new_host(None)),
            ("New Group...", lambda: self.new_group(None)),
            ("Toggle Sidebar", self.toggle_sidebar),
            ("Close Current Tab", self.close_current_tab),
            ("Next Tab", self.next_tab),
            ("Previous Tab", self.previous_tab),
            ("Snippet Manager", self.open_snippet_manager),
            ("Port Forwarding (active tab)", self.open_port_forwarding),
            ("Export Vault", self.export_vault),
            ("Focus Host Search", self.focus_host_search),
        ]
        for host in self.db.query(Host).order_by(Host.label).all():
            commands.append((
                f"Connect: {host.label} ({host.hostname})",
                lambda hid=host.id: self.open_terminal_for_host(hid)
            ))
            commands.append((
                f"SFTP: {host.label} ({host.hostname})",
                lambda hid=host.id: self.open_sftp_for_host(hid)
            ))
        return commands

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        for info in self.open_sessions.values():
            try:
                t = info["type"]
                if t in ("terminal", "local"):
                    info["widget"].stop()
                elif t == "sftp":
                    info["sftp"].close()
                    info["ssh_session"].close()
                elif t == "dual_sftp":
                    info["widget"].close_all()
                    for s in info["sessions"]:
                        s.close()
            except Exception:
                pass
        super().closeEvent(event)