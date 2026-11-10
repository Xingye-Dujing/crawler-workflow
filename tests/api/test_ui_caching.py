"""The page must be revalidated on every load; the scripts already are.

Flask's own static route answers with ``no-cache`` (revalidate each time), but
``/`` is served by ``send_from_directory``, whose default freshness window is
Flask's 12 hours — a plain refresh can keep booting yesterday's document. For a
tool whose whole surface is one HTML file plus the scripts it references, a
stale document is a canvas that runs code from before the last fix. The
after_request hook in app.py closes that hole; this pins it stays closed.
"""

import pytest
from static_assets import STATIC

pytestmark = pytest.mark.api

# The document and every script/stylesheet the boot is made of.
BOOT_ASSETS = [
    '/',
    '/index.html',
    '/css/base.css',
    '/css/overlays.css',
    '/js/canvas.js',
    '/js/app.js',
    '/js/workflow.js',
]


class TestUiCaching:
    @pytest.mark.parametrize('path', BOOT_ASSETS)
    def test_boot_assets_forbid_freshness_without_revalidating(self, client, path):
        """`no-cache` allows storing but demands a revalidation; `no-store`
        would refetch the whole bundle on every navigation for nothing.

        The response is a file the server opened, so it is closed here rather than left
        for the garbage collector: an unclosed handle is a ResourceWarning, and this suite
        treats a warning as a test that noticed something and passed anyway.
        """
        with client.get(path) as resp:
            assert resp.status_code == 200, path
            assert resp.headers.get('Cache-Control') == 'no-cache', path

    def test_the_document_is_the_asset_this_hook_exists_for(self, client):
        """Without the hook this one answers 12 hours of freshness — the proof
        the whitelist is not decoration. (An asset Flask's static route already
        revalidates cannot show the difference, which is why this, not the
        scripts, is the pinned regression.)"""
        with client.get('/') as resp:
            assert 'max-age' not in (resp.headers.get('Cache-Control') or ''), resp.headers.get('Cache-Control')


class TestStudioFraming:
    """Framing is refused everywhere except the one document this app frames ITSELF.

    ``X-Frame-Options: DENY`` is a blanket refusal, not a cross-origin rule: a ``DENY``
    document may not be displayed in ANY frame, a same-origin one included. The Chart Studio is
    framed by the app — ``static/js/zenviz.js`` sets ``#studio-frame`` to
    ``/zenviz.html?embed=1`` — so when the hook was widened from the login page to every
    response, the studio panel became a blank overlay: the browser refused to connect, while
    ``iframe.load`` still fired, so the spinner was hidden and the status line waited forever for
    a bridge that was never loaded.

    The exemption is pinned by DISCOVERY (every ``*.html`` under ``static/``), so a second page
    that wants to be framable has to come here and say so, and the narrow ``SAMEORIGIN`` answer
    cannot quietly become ``ALLOWALL``.
    """

    FRAMED = 'zenviz.html'

    @pytest.mark.parametrize('name', sorted(path.name for path in STATIC.glob('*.html')))
    def test_only_the_studio_document_may_be_framed(self, client, name):
        expected = 'SAMEORIGIN' if name == self.FRAMED else 'DENY'
        with client.get('/' + name) as resp:
            assert resp.status_code == 200, name
            assert resp.headers.get('X-Frame-Options') == expected, name

    def test_the_studio_also_carries_the_modern_spelling(self, client):
        """Browsers that ignore ``X-Frame-Options`` in favour of CSP read the second header."""
        with client.get('/' + self.FRAMED) as resp:
            policy = resp.headers.get('Content-Security-Policy') or ''
            assert "frame-ancestors 'self'" in policy, policy

    @pytest.mark.parametrize('path', ['/', '/index.html', '/js/zenviz.js', '/css/overlays.css'])
    def test_boot_assets_and_scripts_refuse_framing(self, client, path):
        """The exemption is one DOCUMENT; the scripts that build the overlay keep ``DENY``."""
        with client.get(path) as resp:
            assert resp.status_code == 200, path
            assert resp.headers.get('X-Frame-Options') == 'DENY', path
