"""
core/port_forward.py
Local, remote, and dynamic (SOCKS) port forwarding over a paramiko transport.
Each forwarder runs in background threads and can be stopped via .stop().
"""

import select
import socket
import threading

import paramiko


class ForwardServer(socket.socket):
    """Threading TCP server replacement using plain sockets (no socketserver
    dependency issues across platforms)."""
    pass


class LocalPortForward(threading.Thread):
    """
    Forwards connections to bind_address:bind_port -> (via SSH transport) -> dest_address:dest_port
    """

    def __init__(self, transport, bind_address, bind_port, dest_address, dest_port):
        super().__init__(daemon=True)
        self.transport = transport
        self.bind_address = bind_address
        self.bind_port = bind_port
        self.dest_address = dest_address
        self.dest_port = dest_port
        self._stop_event = threading.Event()
        self._server_sock = None

    def run(self):
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.bind_address, self.bind_port))
        self._server_sock.listen(100)
        self._server_sock.settimeout(1.0)

        while not self._stop_event.is_set():
            try:
                client_sock, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._handle_client, args=(client_sock,), daemon=True
            ).start()

        try:
            self._server_sock.close()
        except Exception:
            pass

    def _handle_client(self, client_sock):
        try:
            chan = self.transport.open_channel(
                "direct-tcpip",
                (self.dest_address, self.dest_port),
                client_sock.getpeername(),
            )
        except Exception:
            client_sock.close()
            return
        if chan is None:
            client_sock.close()
            return

        self._pump(client_sock, chan)

    def _pump(self, sock, chan):
        while not self._stop_event.is_set():
            r, _, _ = select.select([sock, chan], [], [], 1.0)
            if sock in r:
                data = sock.recv(4096)
                if not data:
                    break
                chan.send(data)
            if chan in r:
                data = chan.recv(4096)
                if not data:
                    break
                sock.send(data)
        chan.close()
        sock.close()

    def stop(self):
        self._stop_event.set()
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass


class RemotePortForward:
    """
    Forwards connections arriving on the REMOTE host's bind_port back to a
    local (client-side) dest_address:dest_port. Uses transport.request_port_forward.
    """

    def __init__(self, transport, bind_address, bind_port, dest_address, dest_port):
        self.transport = transport
        self.bind_address = bind_address
        self.bind_port = bind_port
        self.dest_address = dest_address
        self.dest_port = dest_port
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        self.transport.request_port_forward(self.bind_address, self.bind_port, self._handler)

    def _handler(self, chan, src_addr, dst_addr):
        try:
            local_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            local_sock.connect((self.dest_address, self.dest_port))
        except Exception:
            chan.close()
            return

        def pump():
            while not self._stop_event.is_set():
                r, _, _ = select.select([local_sock, chan], [], [], 1.0)
                if local_sock in r:
                    data = local_sock.recv(4096)
                    if not data:
                        break
                    chan.send(data)
                if chan in r:
                    data = chan.recv(4096)
                    if not data:
                        break
                    local_sock.send(data)
            chan.close()
            local_sock.close()

        threading.Thread(target=pump, daemon=True).start()

    def stop(self):
        self._stop_event.set()
        try:
            self.transport.cancel_port_forward(self.bind_address, self.bind_port)
        except Exception:
            pass


# --- Minimal SOCKS4/5 dynamic forwarding ---

SOCKS_VERSION_5 = 5
SOCKS_VERSION_4 = 4


class DynamicPortForward(threading.Thread):
    """
    A minimal SOCKS4/5 proxy server that tunnels CONNECT requests through
    the SSH transport (equivalent to `ssh -D`).
    """

    def __init__(self, transport, bind_address, bind_port):
        super().__init__(daemon=True)
        self.transport = transport
        self.bind_address = bind_address
        self.bind_port = bind_port
        self._stop_event = threading.Event()
        self._server_sock = None

    def run(self):
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.bind_address, self.bind_port))
        self._server_sock.listen(100)
        self._server_sock.settimeout(1.0)

        while not self._stop_event.is_set():
            try:
                client_sock, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(client_sock,), daemon=True).start()

        try:
            self._server_sock.close()
        except Exception:
            pass

    def _handle(self, sock):
        try:
            version = sock.recv(1)
            if version == bytes([SOCKS_VERSION_5]):
                self._handle_socks5(sock)
            elif version == bytes([SOCKS_VERSION_4]):
                self._handle_socks4(sock)
            else:
                sock.close()
        except Exception:
            sock.close()

    def _handle_socks5(self, sock):
        nmethods = ord(sock.recv(1))
        sock.recv(nmethods)  # ignore auth methods, no-auth only
        sock.sendall(b"\x05\x00")  # no auth required

        header = sock.recv(4)
        if len(header) < 4:
            sock.close()
            return
        ver, cmd, _, atyp = header[0], header[1], header[2], header[3]

        if atyp == 1:  # IPv4
            addr = socket.inet_ntoa(sock.recv(4))
        elif atyp == 3:  # domain name
            length = ord(sock.recv(1))
            addr = sock.recv(length).decode()
        elif atyp == 4:  # IPv6
            addr = socket.inet_ntop(socket.AF_INET6, sock.recv(16))
        else:
            sock.close()
            return

        port = int.from_bytes(sock.recv(2), "big")

        if cmd != 1:  # only CONNECT supported
            sock.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            sock.close()
            return

        try:
            chan = self.transport.open_channel("direct-tcpip", (addr, port), sock.getpeername())
        except Exception:
            sock.sendall(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
            sock.close()
            return

        if chan is None:
            sock.sendall(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
            sock.close()
            return

        sock.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        self._pump(sock, chan)

    def _handle_socks4(self, sock):
        rest = sock.recv(7)
        if len(rest) < 7:
            sock.close()
            return
        cmd = rest[0]
        port = int.from_bytes(rest[1:3], "big")
        addr = socket.inet_ntoa(rest[3:7])

        # read null-terminated user id
        userid = b""
        while True:
            b = sock.recv(1)
            if b == b"\x00" or not b:
                break
            userid += b

        if cmd != 1:
            sock.sendall(b"\x00\x5b\x00\x00\x00\x00\x00\x00")
            sock.close()
            return

        try:
            chan = self.transport.open_channel("direct-tcpip", (addr, port), sock.getpeername())
        except Exception:
            sock.sendall(b"\x00\x5b\x00\x00\x00\x00\x00\x00")
            sock.close()
            return

        sock.sendall(b"\x00\x5a\x00\x00\x00\x00\x00\x00")
        self._pump(sock, chan)

    def _pump(self, sock, chan):
        while not self._stop_event.is_set():
            r, _, _ = select.select([sock, chan], [], [], 1.0)
            if sock in r:
                data = sock.recv(4096)
                if not data:
                    break
                chan.send(data)
            if chan in r:
                data = chan.recv(4096)
                if not data:
                    break
                sock.send(data)
        chan.close()
        sock.close()

    def stop(self):
        self._stop_event.set()
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass


def start_forward(transport, forward_config):
    """
    forward_config: dict with keys type, bind_address, bind_port, dest_address, dest_port
    Returns a started forwarder object with .stop()
    """
    ftype = forward_config["type"]
    bind_address = forward_config.get("bind_address", "127.0.0.1")
    bind_port = forward_config["bind_port"]

    if ftype == "local":
        fwd = LocalPortForward(
            transport, bind_address, bind_port,
            forward_config["dest_address"], forward_config["dest_port"]
        )
        fwd.start()
        return fwd

    if ftype == "remote":
        fwd = RemotePortForward(
            transport, bind_address, bind_port,
            forward_config["dest_address"], forward_config["dest_port"]
        )
        fwd.start()
        return fwd

    if ftype == "dynamic":
        fwd = DynamicPortForward(transport, bind_address, bind_port)
        fwd.start()
        return fwd

    raise ValueError(f"Unknown forward type: {ftype}")
