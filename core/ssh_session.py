"""
core/ssh_session.py
Core SSH connection logic: single-hop and multi-hop (jump host / chained) connections,
interactive shell channels, exec, and keepalive.
"""

import io
import socket
import threading
import paramiko


class HostConfig:
    """Plain data object describing one hop's connection parameters."""

    def __init__(self, hostname, port=22, username=None,
                 password=None, private_key_pem=None, passphrase=None,
                 terminal_type="xterm-256color", keepalive=30,
                 host_key_policy="auto_add"):
        self.hostname = hostname
        self.port = port or 22
        self.username = username
        self.password = password
        self.private_key_pem = private_key_pem
        self.passphrase = passphrase
        self.terminal_type = terminal_type
        self.keepalive = keepalive
        self.host_key_policy = host_key_policy  # 'auto_add' | 'reject' | 'warn'

    def load_pkey(self):
        """Try to load a private key from PEM text, trying common key types."""
        if not self.private_key_pem:
            return None
        key_classes = [
            paramiko.Ed25519Key,
            paramiko.RSAKey,
            paramiko.ECDSAKey,
            paramiko.DSSKey,
        ]
        last_err = None
        for cls in key_classes:
            try:
                return cls.from_private_key(io.StringIO(self.private_key_pem), password=self.passphrase or None)
            except Exception as e:
                last_err = e
                continue
        raise ValueError(f"Could not load private key with any supported type: {last_err}")


def _policy_for(host_key_policy: str):
    if host_key_policy == "reject":
        return paramiko.RejectPolicy()
    if host_key_policy == "warn":
        return paramiko.WarningPolicy()
    return paramiko.AutoAddPolicy()


def connect_chain(hop_configs):
    """
    Connect through a chain of hosts.

    hop_configs: list[HostConfig], ordered from the entry hop (first) to the
                 final target host (last). Minimum length 1.

    Returns: (final_client: paramiko.SSHClient, intermediate_clients: list[paramiko.SSHClient])
             Caller is responsible for closing all returned clients
             (close intermediates AFTER final client is done).
    """
    if not hop_configs:
        raise ValueError("hop_configs must contain at least one host")

    clients = []
    sock = None

    for i, cfg in enumerate(hop_configs):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(_policy_for(cfg.host_key_policy))
        client.load_system_host_keys()

        pkey = cfg.load_pkey()

        connect_kwargs = dict(
            hostname=cfg.hostname,
            port=cfg.port,
            username=cfg.username,
            timeout=15,
        )
        if pkey is not None:
            connect_kwargs["pkey"] = pkey
        if cfg.password:
            connect_kwargs["password"] = cfg.password
        if sock is not None:
            connect_kwargs["sock"] = sock

        client.connect(**connect_kwargs)

        transport = client.get_transport()
        if cfg.keepalive:
            transport.set_keepalive(cfg.keepalive)

        clients.append(client)

        # If there's a next hop, open a direct-tcpip channel through this transport
        if i < len(hop_configs) - 1:
            next_cfg = hop_configs[i + 1]
            sock = transport.open_channel(
                "direct-tcpip",
                (next_cfg.hostname, next_cfg.port),
                ("127.0.0.1", 0),
            )

    final_client = clients[-1]
    intermediates = clients[:-1]
    return final_client, intermediates


class SSHSession:
    """
    Wraps a connected paramiko SSHClient (possibly via a chain) and exposes
    an interactive shell channel suitable for a terminal widget.
    """

    def __init__(self, hop_configs):
        self.hop_configs = hop_configs
        self.client = None
        self.intermediates = []
        self.channel = None
        self._closed = False

    def open(self, term="xterm-256color", width=80, height=24):
        self.client, self.intermediates = connect_chain(self.hop_configs)
        self.channel = self.client.invoke_shell(term=term, width=width, height=height)
        self.channel.settimeout(0.0)  # non-blocking for read loops
        return self.channel

    def resize_pty(self, width, height):
        if self.channel:
            self.channel.resize_pty(width=width, height=height)

    def send(self, data: bytes):
        if self.channel:
            self.channel.send(data)

    def recv(self, nbytes=4096):
        """Non-blocking receive; returns b'' if nothing available."""
        if not self.channel:
            return b""
        try:
            if self.channel.recv_ready():
                return self.channel.recv(nbytes)
        except Exception:
            pass
        return b""

    def exec_command(self, command, timeout=30):
        """Run a one-off command (used for snippets) on the final host."""
        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return out, err

    def open_sftp(self):
        return self.client.open_sftp()

    def get_transport(self, hop_index=-1):
        """
        Return the paramiko Transport for a given hop in the chain.
        hop_index=-1 (default) -> final/target host's transport.
        hop_index=0 -> entry hop's transport.
        Useful for port forwarding "through" an intermediate jump host
        rather than only the final target.
        """
        all_clients = self.intermediates + [self.client]
        if not all_clients:
            return None
        try:
            return all_clients[hop_index].get_transport()
        except IndexError:
            return self.client.get_transport()

    def hop_count(self):
        return len(self.intermediates) + (1 if self.client else 0)

    def is_active(self):
        return bool(self.client and self.client.get_transport() and self.client.get_transport().is_active())

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.channel:
                self.channel.close()
        except Exception:
            pass
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass
        for c in reversed(self.intermediates):
            try:
                c.close()
            except Exception:
                pass


def resolve_chain(host, db_session, vault):
    """
    Walk a Host's proxy_host_id chain (from outermost jump host to target)
    and build a list[HostConfig] for connect_chain.

    host: db.models.Host instance (the target host)
    db_session: SQLAlchemy session
    vault: core.crypto.Vault for decrypting credentials

    Returns: list[HostConfig] ordered entry-hop-first, target-last
    """
    chain_hosts = []
    current = host
    visited_ids = set()
    while current is not None:
        if current.id in visited_ids:
            raise ValueError("Cycle detected in proxy host chain")
        visited_ids.add(current.id)
        chain_hosts.append(current)
        current = current.proxy_host

    chain_hosts.reverse()  # entry hop first, target last

    hop_configs = []
    for h in chain_hosts:
        identity = h.identity
        username = h.username or (identity.username if identity else None)
        password = None
        private_key_pem = None
        passphrase = None

        if identity:
            if identity.enc_password:
                password = vault.decrypt(identity.enc_password)
            if identity.enc_private_key:
                private_key_pem = vault.decrypt(identity.enc_private_key)
            elif identity.private_key_path:
                with open(identity.private_key_path, "r") as f:
                    private_key_pem = f.read()
            if identity.enc_passphrase:
                passphrase = vault.decrypt(identity.enc_passphrase)

        hop_configs.append(HostConfig(
            hostname=h.hostname,
            port=h.port,
            username=username,
            password=password,
            private_key_pem=private_key_pem,
            passphrase=passphrase,
            terminal_type=h.terminal_type,
            keepalive=h.keepalive_interval,
        ))

    return hop_configs
