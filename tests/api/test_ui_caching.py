"""The page must be revalidated on every load; the scripts already are.

Flask's own static route answers with ``no-cache`` (revalidate each time), but
``/`` is served by ``send_from_directory``, whose default freshness window is
Flask's 12 hours — a plain refresh can keep booting yesterday's document. For a
tool whose whole surface is one HTML file plus the scripts it references, a
stale document is a canvas that runs code from before the last fix. The
after_request hook in app.py closes that hole; this pins it stays closed.
"""

import pytest

pytestmark = pytest.mark.api

# The document and every script/stylesheet the boot is made of.
BOOT_ASSETS = ['/', '/index.html', '/css/style.css', '/js/canvas.js', '/js/app.js', '/js/workflow.js']


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
