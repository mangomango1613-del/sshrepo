"""
core/crypto.py
Handles encryption/decryption of sensitive data (passwords, private keys,
passphrases) using a master-password-derived key (PBKDF2 + Fernet/AES).

The salt file path is now explicit (rather than derived from a fixed config
dir), so a vault (.db + .salt) can be opened from any location - enabling
portable / shareable vault files.
"""

import os
import base64
import hashlib
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITERATIONS = 200_000


def _get_salt(salt_path: str) -> bytes:
    if os.path.exists(salt_path):
        with open(salt_path, "rb") as f:
            return f.read()
    salt = os.urandom(16)
    os.makedirs(os.path.dirname(salt_path) or ".", exist_ok=True)
    with open(salt_path, "wb") as f:
        f.write(salt)
    return salt


def derive_key(master_password: str, salt_path: str) -> bytes:
    """Derive a Fernet-compatible key from the master password."""
    salt = _get_salt(salt_path)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=ITERATIONS,
    )
    key = kdf.derive(master_password.encode("utf-8"))
    return base64.urlsafe_b64encode(key)


class Vault:
    """Encrypts/decrypts strings using a derived Fernet key."""

    def __init__(self, master_password: str, salt_path: str):
        self.salt_path = salt_path
        self.key = derive_key(master_password, salt_path)
        self.fernet = Fernet(self.key)

    def encrypt(self, plaintext: str) -> str:
        if plaintext is None:
            return ""
        token = self.fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, token: str) -> str:
        if not token:
            return ""
        try:
            return self.fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except Exception as e:
            raise ValueError(f"Failed to decrypt value: {e}")

    @staticmethod
    def hash_master_password(master_password: str, salt_path: str) -> str:
        """Used to verify master password on next launch without storing it."""
        salt = _get_salt(salt_path)
        h = hashlib.pbkdf2_hmac("sha256", master_password.encode("utf-8"), salt, ITERATIONS)
        return base64.b64encode(h).decode("utf-8")

    @staticmethod
    def verify_master_password(master_password: str, stored_hash: str, salt_path: str) -> bool:
        return Vault.hash_master_password(master_password, salt_path) == stored_hash
