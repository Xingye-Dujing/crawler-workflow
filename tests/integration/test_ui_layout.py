"""Real-browser layout proofs for the 'no horizontal scrollbar' requirement.

CSS overflow cannot be seen from Python asserts — only a real engine lays out
the labels and measures pixels. This tier boots the actual Flask app, opens
the wide top-menu panels (设置 / AI) in BOTH UI languages, and requires every
one to lay its content inside its own box (scrollWidth == clientWidth), plus
the page itself to never grow a horizontal bar. Marked ``integration`` so it
runs with ``-m integration`` on a machine that has Chrome.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def app_url():
    """Boot the real server on a private port; tear it down after the module."""
    import urllib.error
    import urllib.request

    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    env = {**os.environ, 'PORT': str(port)}
    (REPO / 'logs').mkdir(exist_ok=True)
    log_path = REPO / 'logs' / '_ui_layout_server.log'
    with log_path.open('w', encoding='utf-8') as log:
        proc = subprocess.Popen(
            [sys.executable, 'app.py'],
            cwd=str(REPO / 'backend'),
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
        )
        url = f'http://127.0.0.1:{port}'
        deadline = time.time() + 40
        try:
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(url + '/', timeout=2) as resp:
                        if resp.status == 200:
                            break
                except (urllib.error.URLError, ConnectionError, TimeoutError):
                    if proc.poll() is not None:
                        msg = log_path.read_text(errors='replace')[-2000:]
                        pytest.fail(f'server exited early; log:\n{msg}')
                    time.sleep(0.5)
            else:
                pytest.fail('server did not come up within 40s')
            yield url
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.fixture(scope='module')
def driver():
    """A headless Chrome borrowed from the crawler stack (its driver factory
    already honours the configured chromedriver/binary/window settings)."""
    from crawlers.wechat import WechatCrawler

    try:
        crawler = WechatCrawler(headless=True)
    except Exception as e:
        pytest.skip(f'Chrome/chromedriver unavailable: {e}')
    try:
        yield crawler.driver
    finally:
        crawler.close()


_MENU_JS = """
const menu = document.getElementById(arguments[0]);
menu.classList.add('open');
const bad = [];
menu.querySelectorAll('*').forEach((el) => {
    if (el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX !== 'auto'
        && getComputedStyle(el).overflowX !== 'scroll') {
        bad.push(el.className + ':' + el.scrollWidth + '>' + el.clientWidth);
    }
});
return {
    menuScroll: [menu.scrollWidth, menu.clientWidth],
    overflowing: bad.slice(0, 8),
    pageScroll: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
};
"""


@pytest.mark.parametrize('menu_id', ['settings-menu', 'ai-menu'])
@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_wide_menu_has_no_horizontal_overflow(app_url, driver, menu_id, lang):
    driver.get(app_url + '/')
    # apply() re-reads the language from the body dataset — that is the real
    # switch path (TopMenu's Lang button does the same).
    driver.execute_script(f"document.body.dataset.lang = '{lang}'; I18n.apply();")
    result = driver.execute_script(_MENU_JS, [menu_id])
    sw, cw = result['menuScroll']
    assert sw <= cw + 1, f'#{menu_id} scrolls horizontally in {lang}: {result["overflowing"]}'
    psw, pcw = result['pageScroll']
    assert psw <= pcw + 1, f'the page itself scrolls horizontally in {lang}'


_CLICK_JS = """
const el = document.getElementById(arguments[0]) || document.getElementById('workspace');
el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
return ['dashboard-panel', 'history-panel'].map(
    (id) => document.getElementById(id).classList.contains('open'));
"""


def test_popups_close_on_outside_and_survive_inside_clicks(app_url, driver):
    """The real browser, with every document-level handler active (TopMenu,
    node-settings, the popup guards themselves): opening both floating panels
    and clicking back into the canvas must close them; a click inside one must
    close nothing."""
    driver.get(app_url + '/')
    driver.execute_script(
        "document.getElementById('dashboard-panel').classList.add('open');"
        "document.getElementById('history-panel').classList.add('open');"
    )
    inside = driver.execute_script(_CLICK_JS, ['dashboard-panel'])
    assert inside == [True, True], 'a click inside the dashboard killed a popup'

    driver.execute_script(
        "document.getElementById('dashboard-panel').classList.add('open');"
        "document.getElementById('history-panel').classList.add('open');"
    )
    outside = driver.execute_script(_CLICK_JS, [None])
    assert outside == [False, False], 'a click on the canvas left a floating popup open'
