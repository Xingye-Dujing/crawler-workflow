"""Giving one browser a proxy exit, including the credentials Chrome will not take on argv.

Two shapes:

* **No authentication** — Chrome is pointed at the proxy directly
  (``--proxy-server=http://host:port``). Most residential pools authorise by source IP, and
  this is the shortest path to a working exit.
* **Username/password** — Chrome's ``--proxy-server`` has no syntax for credentials, and
  putting them in a URL or an argument would expose them to every process listing on the
  machine. Instead a loopback relay is started for this one browser; Chrome talks plain
  HTTP to ``127.0.0.1:<ephemeral>`` and the relay adds ``Proxy-Authorization`` on the way
  out. The relay dies with the driver (:func:`crawlers.core.browser.close_driver`).

A SOCKS5 exit with credentials is refused **by name**: it needs a SOCKS5 handshake the
relay does not speak, and silently connecting unauthenticated would look like a dead exit.
"""

import base64
import contextlib
import select
import socket
import threading

_HEADER_LIMIT = 64 * 1024
_PUMP_TIMEOUT = 30.0


def chrome_arguments(proxy: dict) -> tuple[list, object]:
    """``(chrome args, relay)`` for one proxy description.

    ``relay`` is ``None`` unless credentials are in play, and must be passed to
    :func:`crawlers.core.browser.close_driver` with the driver — an orphan relay would keep
    a port and an upstream connection for the life of the process.
    """
    if not proxy or proxy.get('unavailable'):
        return [], None
    scheme = str(proxy.get('scheme') or 'http').strip().lower()
    host = str(proxy.get('host') or '').strip()
    try:
        port = int(proxy.get('port') or 0)
    except (TypeError, ValueError):
        port = 0
    if not host or not 1 <= port <= 65535:
        raise ValueError('proxy address is invalid')
    username = str(proxy.get('username') or '')
    password = str(proxy.get('password') or '')
    relay = None
    if username or password:
        if scheme == 'socks5':
            raise ValueError('an authenticated SOCKS5 exit is not supported — use an HTTP exit or an IP allow-list')
        if scheme == 'https':
            raise ValueError('an authenticated HTTPS proxy is not supported — use an HTTP exit')
        relay = _AuthRelay(host, port, username, password)
        server = f'http://127.0.0.1:{relay.port}'
    else:
        server = f'{scheme}://{host}:{port}'
    # ``disable_non_proxied_udp`` closes the WebRTC hole: without it a page can learn the
    # host's own address over UDP while every HTTP request correctly leaves through the exit.
    return [f'--proxy-server={server}', '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'], relay


class _AuthRelay:
    """A loopback HTTP proxy that forwards to one upstream with Basic credentials."""

    def __init__(self, host: str, port: int, username: str, password: str):
        self._upstream = (host, int(port))
        token = base64.b64encode(f'{username}:{password}'.encode()).decode('ascii')
        self._auth = f'Proxy-Authorization: Basic {token}'
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(('127.0.0.1', 0))
        self._sock.listen(64)
        self.port = int(self._sock.getsockname()[1])
        threading.Thread(target=self._serve, name='proxy-relay', daemon=True).start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                client, _addr = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client) -> None:
        try:
            header = _read_headers(client)
            if not header:
                return
            line = header.split(b'\r\n', 1)[0].decode('latin-1')
            parts = line.split()
            if len(parts) < 3:
                return
            method, target = parts[0], parts[1]
            if method.upper() == 'CONNECT':
                self._tunnel(client, target)
            else:
                self._forward(client, header)
        except OSError:
            return
        finally:
            with contextlib.suppress(OSError):
                client.close()

    def _tunnel(self, client, target: str) -> None:
        upstream = socket.create_connection(self._upstream, timeout=_PUMP_TIMEOUT)
        with upstream:
            request = f'CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n{self._auth}\r\n\r\n'
            upstream.sendall(request.encode('latin-1'))
            response = _read_headers(upstream)
            if not response:
                return
            status = response.split(b'\r\n', 1)[0]
            if b' 200' not in status:
                # Forward the refusal so Chrome reports the upstream error, not a timeout.
                client.sendall(response + b'\r\n')
                return
            client.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            _pump(client, upstream)

    def _forward(self, client, header: bytes) -> None:
        """A plain-HTTP request: absolute URI, so the upstream is not asked to CONNECT."""
        head, _, tail = header.partition(b'\r\n\r\n')
        with socket.create_connection(self._upstream, timeout=_PUMP_TIMEOUT) as upstream:
            lines = head.split(b'\r\n')
            forwarded = b'\r\n'.join([lines[0], *lines[1:], self._auth.encode('latin-1')])
            upstream.sendall(forwarded + b'\r\n\r\n')
            if tail:
                upstream.sendall(tail)
            _pump(client, upstream)

    def stop(self) -> None:
        self._stop.set()
        with contextlib.suppress(OSError):
            self._sock.close()


def _read_headers(sock) -> bytes:
    """Read one request/response head, bounded; empty on EOF or an oversized head."""
    data = b''
    while b'\r\n\r\n' not in data:
        chunk = sock.recv(4096)
        if not chunk:
            return b''
        data += chunk
        if len(data) > _HEADER_LIMIT:
            return b''
    return data


def _pump(left, right) -> None:
    """Move bytes both ways until either side closes. A socket pair, not a protocol."""
    sockets = [left, right]
    while True:
        try:
            ready, _, _ = select.select(sockets, [], [], _PUMP_TIMEOUT)
        except (OSError, ValueError):
            return
        if not ready:
            return
        for source in ready:
            try:
                chunk = source.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            target = right if source is left else left
            try:
                target.sendall(chunk)
            except OSError:
                return


def describe(proxy: dict) -> str:
    """An exit as a log line: its name and address, never a credential."""
    if not proxy:
        return ''
    name = str(proxy.get('name') or '').strip()
    address = f'{proxy.get("host", "")}:{proxy.get("port", "")}'
    return f'{name} ({address})' if name and name != address else address
