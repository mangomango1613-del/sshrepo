"""
db/models.py
SQLAlchemy models for the local SQLite store.
All sensitive fields (passwords, private key contents, passphrases) are stored
ENCRYPTED (ciphertext strings produced by core.crypto.Vault).
"""

from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey, Boolean, DateTime, func
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey("groups.id"), nullable=True)

    children = relationship("Group", backref="parent", remote_side=[id])
    hosts = relationship("Host", back_populates="group")


class Identity(Base):
    """Stores SSH credentials: key pair and/or password, encrypted."""
    __tablename__ = "identities"

    id = Column(Integer, primary_key=True)
    label = Column(String, nullable=False)
    username = Column(String, nullable=True)

    auth_type = Column(String, default="password")  # 'password' | 'key' | 'agent'

    # Encrypted blobs (ciphertext); empty string if unused
    enc_password = Column(Text, default="")
    enc_private_key = Column(Text, default="")     # PEM contents
    enc_passphrase = Column(Text, default="")      # private key passphrase

    private_key_path = Column(String, default="")  # optional: path on disk instead of storing contents

    hosts = relationship("Host", back_populates="identity")


class Host(Base):
    __tablename__ = "hosts"

    id = Column(Integer, primary_key=True)
    label = Column(String, nullable=False)
    hostname = Column(String, nullable=False)
    port = Column(Integer, default=22)
    username = Column(String, nullable=True)  # overrides identity username if set

    identity_id = Column(Integer, ForeignKey("identities.id"), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)

    # SSH chaining / jump host: points to another Host row used as proxy/jump
    proxy_host_id = Column(Integer, ForeignKey("hosts.id"), nullable=True)

    # Terminal / connection options
    terminal_type = Column(String, default="xterm-256color")
    startup_snippet_id = Column(Integer, ForeignKey("snippets.id"), nullable=True)
    color_tag = Column(String, default="")
    keepalive_interval = Column(Integer, default=30)

    # known_hosts fingerprint pinning (optional, stored as text)
    host_key_fingerprint = Column(String, default="")

    created_at = Column(DateTime, server_default=func.now())

    identity = relationship("Identity", back_populates="hosts")
    group = relationship("Group", back_populates="hosts")
    proxy_host = relationship("Host", remote_side=[id])
    port_forwards = relationship("PortForward", back_populates="host", cascade="all, delete-orphan")
    startup_snippet = relationship("Snippet", foreign_keys=[startup_snippet_id])


class Snippet(Base):
    """Reusable shell scripts/snippets, can be run on connect or on demand."""
    __tablename__ = "snippets"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    content = Column(Text, default="")
    description = Column(Text, default="")


class PortForward(Base):
    """Local / Remote / Dynamic (SOCKS) port forwarding rules tied to a host."""
    __tablename__ = "port_forwards"

    id = Column(Integer, primary_key=True)
    host_id = Column(Integer, ForeignKey("hosts.id"), nullable=False)

    type = Column(String, default="local")  # 'local' | 'remote' | 'dynamic'
    label = Column(String, default="")

    bind_address = Column(String, default="127.0.0.1")
    bind_port = Column(Integer, nullable=False)

    dest_address = Column(String, default="")  # not used for 'dynamic'
    dest_port = Column(Integer, nullable=True)

    auto_start = Column(Boolean, default=False)

    # Which hop in the connection chain to tunnel through.
    # -1 = final/target host (default, most common).
    #  0 = entry/first jump host, 1 = second hop, etc.
    via_hop_index = Column(Integer, default=-1)

    host = relationship("Host", back_populates="port_forwards")


class KnownHost(Base):
    """Local known_hosts equivalent for host key verification."""
    __tablename__ = "known_hosts"

    id = Column(Integer, primary_key=True)
    hostname = Column(String, nullable=False)
    port = Column(Integer, default=22)
    key_type = Column(String, nullable=False)
    fingerprint = Column(String, nullable=False)
    public_key_blob = Column(Text, nullable=False)


class SessionLog(Base):
    """Optional terminal session logging metadata (log files stored on disk)."""
    __tablename__ = "session_logs"

    id = Column(Integer, primary_key=True)
    host_id = Column(Integer, ForeignKey("hosts.id"), nullable=True)
    started_at = Column(DateTime, server_default=func.now())
    ended_at = Column(DateTime, nullable=True)
    log_file_path = Column(String, nullable=False)


class AppMeta(Base):
    """Single-row table for app-level metadata, e.g. master password hash."""
    __tablename__ = "app_meta"

    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(Text, default="")
