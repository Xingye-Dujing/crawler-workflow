"""Real Chrome: a planted cookie really does live in the profile, and a re-plant really replaces it (#108).

The panel's 「把 Cookie 更新进 Profile」 rests on two claims that no offline test can make:

1. ``driver.add_cookie`` on a page whose host matches the cookie's domain writes into the
   **profile directory**, so the next browser built on that directory sees it — this is why
   "the profile owns its session" is a fact rather than a policy;
2. planting again **replaces** the value, which is exactly why the button asks first: a
   stale snapshot over a live session is the harm the import-once rule prevents, and the
   same mechanism is what makes an explicitly re-taken cookie arrive.

The local server is what makes either claim observable without touching a site: the cookie
domain has to match the document's host, and ``127.0.0.1`` is the only host this test may
serve. ``_load_cookies`` is exercised by unit tests with a planted-cookie driver that answers
in memory; what is proven here is the browser's half of the bargain.
"""

import http.server
import threading
import time

import pytest

from crawlers.base import Crawler

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

BODY = '<html><head><title>local</title></head><body>cookie host</body></html>'

#: Filled in by the ``local_server`` fixture, because the port is chosen by the OS.
_LOCAL_URL = ''


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _serve(self):
        payload = BODY.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


# ``BaseHTTPRequestHandler`` dispatches to ``do_GET`` by *name* at request time, and the name
# is not ours to choose. Assigning it here rather than writing the method that way keeps the
# repository free of lint suppressions, which is the only reason the two conventions clash.
Handler.do_GET = Handler._serve  # pylint: disable=invalid-name


class Probe(Crawler):
    """A platform with no site: the base class's profile and cookie plumbing, nothing else."""

    domain = '127.0.0.1'
    login_url = ''

    def search(self, keyword, **kwargs):
        return []

    def get_detail(self, url):
        return None


def _cookie(value: str, hours: int | None = 24) -> dict:
    """A cookie the way a real saved file has them.

    ``hours`` is not decoration: measured on this very harness, a planted cookie **without**
    an expiry is accepted, visible in that browser, and gone from the profile directory
    afterwards — persistent cookies are what Chrome writes to its store. The whole panel
    feature rests on the difference, so the fixture states it and one test below pins the
    negative case as well.
    """
    cookie = {'name': 'session_probe', 'value': value, 'domain': '127.0.0.1', 'path': '/'}
    if hours:
        cookie['expiry'] = int(time.time()) + hours * 3600
    return cookie


def _open(profile_dir=None):
    """A crawler on *profile_dir*, parked on the local page, or a skip if Chrome is missing."""
    try:
        crawler = Probe(headless=True, profile_dir=profile_dir)
    except Exception as exc:  # Chrome/chromedriver absent, or the binary refused to start
        pytest.skip(f'Chrome/chromedriver unavailable: {exc}')
    crawler.driver.get(_LOCAL_URL)
    return crawler


@pytest.fixture(scope='module')
def local_server():
    """Serves ``127.0.0.1`` so a cookie can carry a domain the document actually matches."""
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    url = f'http://127.0.0.1:{server.server_address[1]}/'
    globals()['_LOCAL_URL'] = url
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield url
    finally:
        server.shutdown()


@pytest.fixture
def profile(tmp_path):
    return str(tmp_path / 'chrome_profile')


class TestAPlantedCookieBelongsToTheProfile:
    def test_a_second_browser_on_the_same_directory_reads_it_back(self, local_server, profile):
        first = _open(profile_dir=profile)
        try:
            accepted, refused = first._plant([_cookie('v1')])
            assert accepted == 1 and not refused, f'the page host refused the cookie: {refused}'
        finally:
            first.close()

        second = _open(profile_dir=profile)
        try:
            names = {item['name']: item['value'] for item in second.driver.get_cookies()}
            assert names.get('session_probe') == 'v1', f'the profile did not keep what was planted into it: {names}'
        finally:
            second.close()

    def test_a_throwaway_directory_starts_empty(self, local_server, tmp_path):
        """The control: without a shared directory the same plant is seen by nobody, which is
        what makes "the profile owns the session" a property of the directory and not of the
        browser process."""
        crawler = _open(profile_dir=str(tmp_path / 'fresh'))
        try:
            assert {item['name'] for item in crawler.driver.get_cookies()} == set()
        finally:
            crawler.close()

    def test_replanting_replaces_the_value_the_profile_holds(self, local_server, profile):
        """The button's whole effect, and the reason it is behind a confirmation.

        Step 1 plants ``v1`` (the first import). Step 2 is what a crawl would normally never
        do — plant again — and it must win, because that is the only way a re-taken cookie
        reaches a device the site already knows.
        """
        first = _open(profile_dir=profile)
        try:
            first._plant([_cookie('v1')])
        finally:
            first.close()

        refreshed = _open(profile_dir=profile)
        try:
            before = {item['name']: item['value'] for item in refreshed.driver.get_cookies()}
            assert before.get('session_probe') == 'v1', before
            accepted, refused = refreshed._plant([_cookie('v2')])
            assert accepted == 1 and not refused, refused
            after = {item['name']: item['value'] for item in refreshed.driver.get_cookies()}
            assert after.get('session_probe') == 'v2', after
        finally:
            refreshed.close()

        again = _open(profile_dir=profile)
        try:
            settled = {item['name']: item['value'] for item in again.driver.get_cookies()}
            assert settled.get('session_probe') == 'v2', f'the refresh did not survive the browser: {settled}'
        finally:
            again.close()

    def test_a_cookie_without_an_expiry_is_planted_and_then_lost(self, local_server, tmp_path):
        """The limit of what 「更新进 Profile」 can promise, measured rather than assumed.

        Chrome writes persistent cookies to the profile store and keeps session cookies in
        memory, so an imported session cookie is live in the window that planted it and gone
        afterwards. The panel says how many of the saved entries are of that shape; this is
        the measurement that number is derived from.
        """
        directory = str(tmp_path / 'session-only')
        first = _open(profile_dir=directory)
        try:
            accepted, refused = first._plant([_cookie('v1', hours=None)])
            assert accepted == 1 and not refused
            assert {item['value'] for item in first.driver.get_cookies()} == {'v1'}, (
                'the plant itself did not take, so the claim below measures nothing'
            )
        finally:
            first.close()

        second = _open(profile_dir=directory)
        try:
            assert {item['name'] for item in second.driver.get_cookies()} == set(), (
                'a session cookie survived the profile after all — the panel warning is wrong'
            )
        finally:
            second.close()
