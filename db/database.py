"""
db/database.py
SQLite database initialization and session factory.

Supports two modes:
  - Default mode: DB lives in the user's app-data directory (persists
    across runs automatically).
  - Portable mode: caller supplies an explicit .db path (e.g. a vault file
    the user opens via "Open Vault"). The matching "<name>.salt" file (used
    for credential encryption) sits next to it - see export_vault/import_vault.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base

DB_FILENAME = "sshclient.db"
SALT_FILENAME = "vault.salt"


def get_app_dir() -> str:
    """Return a per-user app config/data directory (cross-platform)."""
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        path = os.path.join(base, "PyTermSSH")
    else:
        base = os.path.expanduser("~/.config")
        path = os.path.join(base, "pytermssh")
    os.makedirs(path, exist_ok=True)
    return path


def default_db_path() -> str:
    return os.path.join(get_app_dir(), DB_FILENAME)


def default_salt_path() -> str:
    return os.path.join(get_app_dir(), SALT_FILENAME)


def salt_path_for_db(db_path: str) -> str:
    """A vault.salt file lives alongside the .db file with the same stem."""
    base, _ = os.path.splitext(db_path)
    return base + ".salt"


# ---------------------------------------------------------------------------
# Remembering the last-used vault so the app doesn't ask "which vault?"
# on every single launch. Stored as a tiny JSON file in the app dir -
# deliberately separate from the encrypted vault.db itself.
# ---------------------------------------------------------------------------

LAST_VAULT_FILENAME = "last_vault.json"


def _last_vault_pointer_path() -> str:
    return os.path.join(get_app_dir(), LAST_VAULT_FILENAME)


def load_last_vault():
    """Return (db_path, salt_path) of the last-used vault, or None if this
    is a first run or the remembered vault no longer exists on disk."""
    import json
    pointer = _last_vault_pointer_path()
    if not os.path.exists(pointer):
        return None
    try:
        with open(pointer, "r", encoding="utf-8") as f:
            data = json.load(f)
        db_path = data.get("db_path")
        salt_path = data.get("salt_path")
        if db_path and salt_path and os.path.exists(db_path) and os.path.exists(salt_path):
            return db_path, salt_path
    except (json.JSONDecodeError, OSError):
        pass
    return None


def save_last_vault(db_path: str, salt_path: str):
    """Remember this vault so next launch skips the picker dialog."""
    import json
    pointer = _last_vault_pointer_path()
    try:
        with open(pointer, "w", encoding="utf-8") as f:
            json.dump({"db_path": db_path, "salt_path": salt_path}, f)
    except OSError:
        pass


def clear_last_vault():
    """Forget the remembered vault (used by 'Switch Vault' in the app)."""
    pointer = _last_vault_pointer_path()
    if os.path.exists(pointer):
        try:
            os.remove(pointer)
        except OSError:
            pass


def get_engine(db_path: str = None):
    if db_path is None:
        db_path = default_db_path()
    engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)
    engine._db_path = db_path  # stash for convenience
    return engine


def init_db(engine=None):
    if engine is None:
        engine = get_engine()
    Base.metadata.create_all(engine)
    return engine


def get_session(engine=None):
    if engine is None:
        engine = get_engine()
    init_db(engine)
    Session = sessionmaker(bind=engine, future=True)
    return Session()


def export_vault(db_path: str, salt_path: str, dest_zip: str) -> str:
    """
    Bundle the .db and .salt files into a single .zip the user can hand off.
    `dest_zip` is the full path to the output .zip file.
    """
    import zipfile
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(db_path, arcname=DB_FILENAME)
        if os.path.exists(salt_path):
            zf.write(salt_path, arcname=SALT_FILENAME)
    return dest_zip


def import_vault(zip_path: str, dest_dir: str):
    """
    Extract a vault zip into dest_dir. Returns (db_path, salt_path).
    """
    import zipfile
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)
    return (
        os.path.join(dest_dir, DB_FILENAME),
        os.path.join(dest_dir, SALT_FILENAME),
    )