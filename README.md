# PyTermSSH

A modular SSH/SFTP client built to exceed Termius in functionality - local
SQLite storage (no cloud), shareable vault files, parallel connections,
dual-pane SFTP transfers, multi-hop port forwarding, syntax-highlighted
file editing, a command palette, and a professional dark UI.

## Feature Highlights

### Connections
- **Parallel, non-blocking connects** - fire off connections to many hosts
  at once; each opens its own tab immediately (status dot = connecting),
  filling in as it completes. No modal dialogs queue up and block the UI.
- **Connect All** - right-click (or double-click) a group in the sidebar to
  open a terminal for every host in it, in parallel. Also available for
  *all* hosts via the empty-area context menu.
- **SSH chaining / jump hosts** - unlimited hops, configured per-host via
  "Connect through" in the host editor.
- **Quick Connect** (`Ctrl+T`) - ad-hoc SSH session, type host/user/password
  or key, no saved host needed.
- **Local Terminal** (`Ctrl+Shift+T`) - a plain local shell tab (bash on
  Linux/macOS, PowerShell/cmd on Windows) for running local commands or
  manually typing `ssh user@host`.

### Tabs & Navigation (Cursor/VS Code-inspired)
- Always-visible close ("x") buttons on every tab.
- Live status dots: yellow (connecting), green (connected), red (error,
  with the error message in the tab tooltip).
- Auto-focus: switching tabs focuses the terminal/file list/editor in that
  tab automatically.
- **Command Palette** (`Ctrl+Shift+P`) - searchable list of every action,
  plus a "Connect: <host>" / "SFTP: <host>" entry for every saved host.
- Keyboard shortcuts: `Ctrl+W` close tab, `Ctrl+Tab` / `Ctrl+Shift+Tab`
  cycle tabs, `Ctrl+1`..`Ctrl+9` jump to tab N, `Ctrl+B` toggle sidebar,
  `Ctrl+F` focus host search, `Ctrl+S` save in file editor.

### SFTP
- **Color-coded file listing** (like `ls --color`): directories blue,
  executables green, symlinks cyan, archives orange, source/scripts
  yellow, config/markup purple, images/media tan.
- **Dual-pane transfers** - connect two hosts side by side and send
  files/folders directly between them (streamed through your machine, no
  local temp copy). Right-click a host -> "Open Dual-Pane SFTP (Transfer)".
- **In-place file editing with syntax highlighting** - double-click any
  text/config/script file to open it in a Pygments-highlighted editor tab;
  Ctrl+S saves it straight back over SFTP.
- Upload/download files & folders, rename, delete, chmod, mkdir,
  multi-select.

### Port Forwarding
- Local, remote, and dynamic (SOCKS4/5).
- **Tunnel through any hop** in a jump-host chain - the dialog shows the
  full connection chain and lets you pick which hop (via_hop_index) to
  forward through.
- Rules tracked by stable DB id, so they persist correctly across
  refreshes and reconnects.

### Vault (shareable SQLite database)
A vault = sshclient.db (hosts, groups, snippets, port-forward rules,
encrypted credentials) + vault.salt (encryption salt). On first launch,
Select Vault lets you:
1. Use my local vault (default, %APPDATA%\\PyTermSSH\\ or ~/.config/pytermssh/)
2. Open a shared vault file (.zip) - for receiving someone else's vault
3. Open/create vault at a custom location - USB drive, synced folder, etc.

To share your setup: File -> Export Vault produces a .zip. Send it plus
your master password (separately) to a teammate; they pick option 2 and
unlock it with that password to get every host/group/snippet you saved.

### Other
- Snippets library, run-on-connect and run-on-demand.
- Encrypted credential vault (PBKDF2 + Fernet/AES, master password never
  stored - only a verification hash).
- Background-threaded SFTP operations with progress dialogs (no UI freezes).
- Professional dark theme.
- Duplicate host (copies host + identity + port-forward rules).

## Project Structure

```
sshclient/
├── main.py                     # entry point (vault select -> unlock -> main window)
├── requirements.txt
├── build_exe.bat / .sh         # standalone builds (configurable name/icon)
├── icon.ico                     # place your app icon here (optional)
├── .github/workflows/build.yml  # CI build for Windows .exe
├── core/
│   ├── crypto.py                # vault encryption (explicit salt path)
│   ├── ssh_session.py           # SSH connection + chaining + per-hop transports
│   ├── local_session.py         # local shell session (mirrors SSHSession API)
│   ├── sftp_manager.py          # SFTP ops incl. remote->remote transfer
│   └── port_forward.py          # local/remote/dynamic forwarding
├── db/
│   ├── models.py                 # SQLAlchemy models (+ via_hop_index)
│   ├── database.py               # SQLite init + export/import vault
│   └── repository.py             # reusable CRUD: duplicate_host, get_chain_hosts
├── ui/
│   ├── theme.py                   # dark stylesheet
│   ├── main_window.py             # app shell, shortcuts, tab/session management
│   ├── closable_tab_widget.py     # tabs with close buttons + status dots
│   ├── connection_manager.py      # parallel, non-blocking connection dispatch
│   ├── command_palette.py         # Ctrl+Shift+P palette
│   ├── code_editor.py             # syntax-highlighted file editor (Pygments)
│   ├── host_tree.py               # sidebar tree, search, Connect All
│   ├── host_dialog.py
│   ├── host_picker_dialog.py
│   ├── terminal_widget.py         # pyte-based VT100 terminal
│   ├── sftp_browser.py            # color-coded file browser + editor hookup
│   ├── dual_sftp_view.py
│   ├── quick_connect_dialog.py
│   ├── snippet_manager.py
│   ├── port_forward_dialog.py
│   ├── vault_select_dialog.py
│   ├── master_password_dialog.py
│   └── progress.py                # background worker for SFTP file ops
└── config/
    └── app_config.py
```

## Running from source

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\\Scripts\\activate
pip install -r requirements.txt
python main.py
```

## Building a Standalone Executable (custom name + icon)

Edit APP_NAME and ICON_FILE at the top of build_exe.bat / build_exe.sh
(or the env: block in .github/workflows/build.yml), then:

### Windows
```cmd
build_exe.bat
```
Output: dist\\<APP_NAME>.exe

### Linux / macOS
```bash
chmod +x build_exe.sh
./build_exe.sh
```
Output: dist/<APP_NAME>

### GitHub Actions (build a Windows .exe from any OS)
Push to GitHub, then run the Build Windows EXE workflow (Actions tab ->
Run workflow). Download the <APP_NAME>-windows artifact when it completes.

To add a logo: drop an icon.ico (Windows) / icon.icns (macOS) in the repo
root - the build scripts pick it up automatically if present.

## Keyboard Shortcuts Reference

| Shortcut | Action |
|---|---|
| Ctrl+T | Quick Connect (manual SSH) |
| Ctrl+Shift+T | New Local Terminal |
| Ctrl+W | Close current tab |
| Ctrl+Tab / Ctrl+Shift+Tab | Next / previous tab |
| Ctrl+1..Ctrl+9 | Jump to tab 1-9 |
| Ctrl+B | Toggle sidebar |
| Ctrl+F | Focus host search |
| Ctrl+Shift+P | Command palette |
| Ctrl+S | Save (in file editor tabs) |
| Double-click group | Connect to every host in it (parallel) |

## Extending / Fixing Code

- **core/** - pure backend logic (no Qt), reusable/testable standalone
- **db/** - schema (models.py) and reusable business logic (repository.py)
- **ui/** - Qt widgets, one file per major component; theme.py centralizes
  styling
- **config/** - constants

To add a new tab type: create a widget in ui/ with a set_focus() method
(for auto-focus on tab switch), wire it into ui/main_window.py's
open_sessions dict (follow the dual_sftp pattern for multi-resource
tabs), and add any new model fields to db/models.py.

To add new connection types: use ui.connection_manager.ConnectionManager
(NOT ui.progress, which is for short SFTP file operations) so connects
remain parallel and non-blocking.
