"""
main.py
Application entry point.

  1. Apply the professional dark theme.
  2. If a vault was used before, reopen it automatically (no dialog) -
     the vault picker only appears on first run or after "Switch Vault".
  3. Otherwise, let the user pick a vault (default local, shared import,
     or custom location).
  4. Initialize the DB at that location and prompt for the master password.
  5. Launch the main window.
"""

import sys

from PySide6.QtWidgets import QApplication

from db.database import (
    get_engine, init_db, get_session, salt_path_for_db,
    load_last_vault, save_last_vault,
)
from core.crypto import Vault
from ui.theme import apply_theme
from ui.vault_select_dialog import VaultSelectDialog
from ui.master_password_dialog import MasterPasswordDialog
from ui.main_window import MainWindow


def resolve_vault(force_picker: bool = False):
    """
    Return (db_path, salt_path) for the vault to open.
    Skips the picker dialog if a vault was used last time (remembered in
    %APPDATA%/PyTermSSH/last_vault.json) and still exists on disk.
    """
    if not force_picker:
        remembered = load_last_vault()
        if remembered:
            return remembered

    vault_dlg = VaultSelectDialog()
    if not vault_dlg.exec():
        return None

    db_path = vault_dlg.db_path
    salt_path = vault_dlg.salt_path or salt_path_for_db(db_path)
    save_last_vault(db_path, salt_path)
    return db_path, salt_path


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PyTermSSH")
    apply_theme(app)

    result = resolve_vault()
    if result is None:
        sys.exit(0)
    db_path, salt_path = result

    engine = get_engine(db_path)
    init_db(engine)
    db_session = get_session(engine)

    pw_dialog = MasterPasswordDialog(db_session, salt_path)
    if not pw_dialog.exec():
        sys.exit(0)

    vault = Vault(pw_dialog.password, salt_path)

    window = MainWindow(db_session, vault, db_path)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()