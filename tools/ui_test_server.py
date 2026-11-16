"""Serve the app to the browser tier on a keep-alive HTTP/1.1 server.

This is a TEST SERVER, not a deployment path. The Werkzeug dev server that ``python app.py`` uses
hardcodes ``Connection: close`` (its own comment: Python's ``http.server`` cannot drain a request
stream before the next one). The workbench loads ~85 resources per navigation, so a long browser
session runs through tens of thousands of client sockets; on Windows the ephemeral-port range
(16,384) is what runs out first, and Chrome then answers ``status=0`` for the remaining scripts —
which the tier reports as a page that "never booted". Keep-alive brings that to ~6 sockets per page.

``wsgiref`` cannot do this either (its handler always answers HTTP/1.0 and closes), so this module
implements the small WSGI bridge ``ThreadingHTTPServer`` needs. It is deliberately minimal: the
tier serves static files and a handful of JSON endpoints, and stubs every other fetch in the page.

Usage: python tools/ui_test_server.py <port>
"""

from __future__ import annotations

import io
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'backend'))

from app import app, logger, start_background_services  # noqa: E402  (the path has to be set first)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'CixiUITest/1.0'

    def log_message(self, format, *args):
        # The tier asserts on the page, not on access logs; the switch exists so a debugging run can
        # still ask for them without a second handler.
        if os.environ.get('CIXI_UI_TEST_LOG'):
            super().log_message(format, *args)

    def do_GET(self):
        self._serve()

    def do_POST(self):
        self._serve()

    def _serve(self):
        parsed = urllib.parse.urlsplit(self.path)
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else b''
        environ = {
            'REQUEST_METHOD': self.command,
            'SCRIPT_NAME': '',
            'PATH_INFO': urllib.parse.unquote(parsed.path),
            'QUERY_STRING': parsed.query,
            'SERVER_NAME': '127.0.0.1',
            'SERVER_PORT': str(self.server.server_port),
            'SERVER_PROTOCOL': 'HTTP/1.1',
            'REMOTE_ADDR': self.client_address[0],
            'CONTENT_TYPE': self.headers.get('Content-Type') or '',
            'CONTENT_LENGTH': str(len(body)),
            'wsgi.version': (1, 0),
            'wsgi.url_scheme': 'http',
            'wsgi.input': io.BytesIO(body),
            'wsgi.errors': sys.stderr,
            'wsgi.multithread': True,
            'wsgi.multiprocess': False,
            'wsgi.run_once': False,
        }
        for name, value in self.headers.items():
            key = name.upper().replace('-', '_')
            if key in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
                continue
            environ['HTTP_' + key] = value
        captured = {}

        def start_response(status, headers, _exc_info=None):
            captured['status'] = status
            captured['headers'] = headers
            return lambda data: None

        try:
            result = app(environ, start_response)
            payload = b''.join(result)
            if hasattr(result, 'close'):
                result.close()
        except Exception as exc:  # a test server must answer, not drop the socket
            payload = f'ui test server: {type(exc).__name__}: {exc}'.encode()
            captured.setdefault('status', '500 Internal Server Error')
            captured.setdefault('headers', [('Content-Type', 'text/plain; charset=utf-8')])
        status = captured.get('status', '500 Internal Server Error')
        headers = captured.get('headers') or []
        code = int(status.split(' ', 1)[0])
        self.send_response_only(code, status.split(' ', 1)[1] if ' ' in status else '')
        names = {name.lower() for name, _value in headers}
        for name, value in headers:
            if name.lower() == 'connection':
                continue
            self.send_header(name, value)
        if 'content-length' not in names:
            self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(payload)

    def do_HEAD(self):
        self._serve()


def main() -> None:
    port = int(sys.argv[1])
    # The same startup facts ``python app.py`` writes: the console-reconnect case boots a page
    # against a server whose buffer already holds lines, and an empty buffer would make that test
    # measure nothing.
    from i18n import t

    logger.info(t('misc.server_starting', port=port))
    start_background_services()
    server = ThreadingHTTPServer(('127.0.0.1', port), _Handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == '__main__':
    main()
