"""The exit plumbing Chrome cannot do alone: credentials, and the leak switches.

A no-auth exit is two launch flags. A credentialed one is a loopback relay, and the reason
it exists is the test below: the upstream sees ``Proxy-Authorization`` while the browser (and
therefore the process listing) only ever sees ``127.0.0.1``. The refusal for a shaped shape
it cannot carry is also pinned — silently going direct would expose the address the exit is
there to hide.
"""

import base64
import contextlib
import socket
import threading
import time

import pytest

from crawlers.core import proxy

#: The relay case binds a loopback socket on purpose: it proves that the credential reaches
#: the upstream, which no string assertion can. The rest of the file is pure.
pytestmark = [pytest.mark.unit, pytest.mark.enable_socket]


def test_a_plain_exit_is_two_flags_and_no_relay():
    args, relay = proxy.chrome_arguments({'scheme': 'http', 'host': '10.0.0.1', 'port': 8080})
    assert relay is None
    assert '--proxy-server=http://10.0.0.1:8080' in args
    assert '--force-webrtc-ip-handling-policy=disable_non_proxied_udp' in args


def test_an_authenticated_socks5_exit_is_refused_by_name():
    with pytest.raises(ValueError) as caught:
        proxy.chrome_arguments({'scheme': 'socks5', 'host': '10.0.0.1', 'port': 1080, 'username': 'u', 'password': 'p'})
    assert 'authenticated' in str(caught.value)


def test_no_proxy_means_no_switches():
    assert proxy.chrome_arguments({}) == ([], None)
    assert proxy.chrome_arguments({'unavailable': True}) == ([], None)


class _Upstream:
    """A one-shot proxy that records the CONNECT head and echoes what follows it."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.head = b''
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        client, _addr = self.sock.accept()
        with client:
            data = b''
            while b'\r\n\r\n' not in data:
                chunk = client.recv(4096)
                if not chunk:
                    return
                data += chunk
            self.head = data
            client.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    return
                client.sendall(chunk)

    def stop(self):
        with contextlib.suppress(OSError):
            self.sock.close()


def test_the_relay_adds_the_credential_the_browser_never_sees():
    upstream = _Upstream()
    args, relay = proxy.chrome_arguments(
        {
            'scheme': 'http',
            'host': '127.0.0.1',
            'port': upstream.port,
            'username': 'user',
            'password': 'pass',
        }
    )
    try:
        assert relay is not None
        # The browser is pointed at loopback, not at the upstream: the credential is not in
        # the argument list, so it cannot appear in a process listing.
        assert any(f'--proxy-server=http://127.0.0.1:{relay.port}' == arg for arg in args), args
        assert not any('user' in arg or 'pass' in arg for arg in args), args

        client = socket.create_connection(('127.0.0.1', relay.port), timeout=10)
        try:
            client.sendall(b'CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n')
            answer = client.recv(4096)
            assert b'200' in answer.split(b'\r\n', 1)[0]
            expected = 'Basic ' + base64.b64encode(b'user:pass').decode('ascii')
            deadline = 0
            while expected.encode() not in upstream.head and deadline < 50:
                time.sleep(0.02)
                deadline += 1
            assert expected.encode() in upstream.head, upstream.head
            client.sendall(b'ping')
            assert client.recv(4) == b'ping'
        finally:
            client.close()
    finally:
        if relay is not None:
            relay.stop()
        upstream.stop()
