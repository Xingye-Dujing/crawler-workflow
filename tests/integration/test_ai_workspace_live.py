"""The AI workspace's live line, measured in a real browser against the real local daemon.

Why this has to be a browser test and not another harness case: the claim is about **time**. The
node harness (``tests/unit/frontend/test_frontend_ai_js.py``) pins the *decision* — which wording, how
many seconds, whether the line is hidden after an ending event — with a pinned clock and a stubbed
``setInterval``. Only a real browser with a real stream can show that:

* the clock the page starts actually keeps running while the provider is silent (the defect that
  made an answer look cut was a line that never changed, and a clock that was written but never
  started);
* the line is present at *every* moment between the first byte and the ending, including under a
  finished paragraph;
* the line is gone once the answer ended, and pressing stop leaves its own sentence instead.

Every number below is computed from the run, never chosen: how many samples were read, whether any
sample in the middle was invisible, and whether the clock moved are all read back from the page.

``tools/ui_test_server.py`` serves the real app on a private port with ``CRAWLER_DATA_ROOT`` pointed
at a throwaway root, so this run writes nothing into the user's ``data/``. The prompts are short on
purpose: the point is the transport, the clock and the ending, not the prose.

Marked ``live_ollama`` because it needs the daemon and ``integration`` because it needs Chrome.
"""

import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from device_policy import REQUIRE_BROWSER_ENV, unavailable

pytestmark = [pytest.mark.live_ollama, pytest.mark.integration, pytest.mark.enable_socket]

REPO = Path(__file__).resolve().parents[2]

SHORT_PROMPT = '用三句话解释什么是主题模型。只输出这三句话。'
LONG_PROMPT = '写一段两百字左右的科普：什么是社区发现。'

#: How often the page is read while a turn runs. Under the 1 s clock on purpose, so a tick that
#: never happened cannot hide between two samples.
SAMPLE_SECONDS = 0.25

#: A turn that ends in under this long may legitimately finish before two ticks; the "the clock
#: moved" assertion is then not made (and the failure message says so), because a 0.4 s answer is
#: no evidence about a 1 s clock.
MIN_SECONDS_FOR_A_TICK = 2.5

STATE_JS = """
const live = document.querySelector('.ai-status');
const phase = live && live.querySelector('.ai-status-text');
const clock = live && live.querySelector('.ai-status-clock');
return {
  visible: !!(live && !live.hidden),
  /* The property is not the picture: a hidden row that still takes height would pass a `hidden`
     check and push the answer up. `display` is what the engine actually lays out with. */
  display: live ? window.getComputedStyle(live).display : '',
  height: live ? Math.round(live.getBoundingClientRect().height) : 0,
  phase: phase ? String(phase.textContent || '') : '',
  clock: clock ? String(clock.textContent || '') : '',
  words: ['ai.working', 'ai.waiting', 'ai.stillWaiting'].map((key) => I18n.t(key)),
  stoppedWord: I18n.t('ai.stopped'),
  notes: Array.from(document.querySelectorAll('#ai-chat .ai-note')).map((n) => String(n.textContent || '')),
  text: Array.from(document.querySelectorAll('#ai-chat .ai-text')).map((n) => String(n.textContent || '')).join(''),
  errors: Array.from(document.querySelectorAll('#ai-chat .ai-error-text')).map((n) => String(n.textContent || '')),
};
"""


@pytest.fixture(scope='module', autouse=True)
def daemon(ollama_host, ollama_chat_model):
    """The daemon is what this module is about: probe it before anything starts a browser.

    Autouse and module-scoped so it runs ahead of the other module fixtures, which means a machine
    without Ollama skips this file without paying for a Chrome launch. ``ollama_host`` honours
    ``CRAWLER_REQUIRE_OLLAMA``: an unavailable daemon is a skip by default and a failure in the run
    that asked for it.
    """
    return {'host': ollama_host, 'model': ollama_chat_model}


@pytest.fixture(scope='module')
def ai_server(tmp_path_factory):
    """The real app on a private port with its own data root (see the module docstring)."""
    import urllib.error
    import urllib.request

    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    root = tmp_path_factory.mktemp('ai_live_state')
    (root / 'logs').mkdir(exist_ok=True)
    env = {**os.environ, 'PORT': str(port), 'CRAWLER_DATA_ROOT': str(root)}
    log_path = root / 'logs' / '_ai_live_server.log'
    with log_path.open('w', encoding='utf-8') as log:
        proc = subprocess.Popen(
            [sys.executable, str(REPO / 'tools' / 'ui_test_server.py'), str(port)],
            cwd=str(REPO / 'backend'),
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
        )
        url = f'http://127.0.0.1:{port}'
        # One clock for both ends: a deadline read from the wall clock against an uptime counter never
        # expires on Windows (monotonic counts from boot), so a server that never answers would sit in
        # this loop until the suite's own timeout instead of failing with the log below.
        deadline = time.monotonic() + 40
        try:
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(url + '/api/ai/ws/bootstrap', timeout=2) as resp:
                        if resp.status == 200:
                            break
                except (urllib.error.URLError, ConnectionError, TimeoutError):
                    if proc.poll() is not None:
                        tail = log_path.read_text(errors='replace')[-2000:]
                        pytest.fail(f'the AI live server exited early; log:\n{tail}')
                    time.sleep(0.5)
            else:
                pytest.fail('the AI live server did not come up within 40s')
            yield url
        finally:
            proc.terminate()
            with contextlib.suppress(Exception):
                proc.wait(timeout=10)
            with contextlib.suppress(Exception):
                proc.kill()


@pytest.fixture(scope='module')
def ai_browser():
    """Headless Chrome borrowed from the crawler stack (it honours the configured driver)."""
    from crawlers.platforms.wechat.crawler import WechatCrawler

    try:
        crawler = WechatCrawler(headless=True)
    except Exception as exc:
        unavailable(f'Chrome/chromedriver unavailable: {exc}', REQUIRE_BROWSER_ENV)
    try:
        crawler.driver.set_script_timeout(60)
        yield crawler.driver
    finally:
        crawler.close()


PICKER_JS = """
return (async () => {
  const provider = document.getElementById('ai-ws-provider');
  provider.value = 'ollama';
  provider.dispatchEvent(new Event('change', {bubbles: true}));
  await AIWorkspace._refreshLocalModels();
  const select = document.getElementById('ai-ws-model');
  const wanted = __VALUE__;
  const options = Array.from(select.options || []).map((option) => option.value);
  if (!options.includes(wanted)) return {ok: false, options: options};
  select.value = wanted;
  select.dispatchEvent(new Event('change', {bubbles: true}));
  return {ok: AIWorkspace._model === wanted, model: AIWorkspace._model, options: options};
})();
"""

SEND_JS = """
const input = document.getElementById('ai-input');
input.value = __VALUE__;
input.dispatchEvent(new Event('input', {bubbles: true}));
AIWorkspace.send();
"""


def _js(template: str, value: str) -> str:
    """Fill a template slot with a JSON-encoded value (a safe literal in both languages)."""
    return template.replace('__VALUE__', json.dumps(str(value)))


def _wait(browser, js, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if browser.execute_script(js):
            return True
        time.sleep(0.15)
    return False


def _state(browser):
    return browser.execute_script(STATE_JS)


def _open_local(browser, url, model):
    """Load the page, open the dock, and point it at the daemon through the real pickers."""
    browser.get(url + '/')
    assert _wait(browser, "return !!document.getElementById('ai-menu');", 60), 'the page never booted'
    browser.execute_script('AIWorkspace.open();')
    assert _wait(browser, "return document.querySelector('.ai-workspace').classList.contains('open');", 20)
    assert _wait(browser, 'return !!(AIWorkspace._bootstrap && AIWorkspace._bootstrap.providers.length);', 40)
    picked = browser.execute_script(_js(PICKER_JS, model))
    if not picked.get('ok'):
        pytest.fail(f'the local model {model!r} was not offered by the picker: {picked}')
    return picked


def _send(browser, prompt):
    browser.execute_script(_js(SEND_JS, prompt))


def _run_turn(browser, prompt, limit=180.0):
    """Sample the live line every 250 ms from the send to the ending; return the timeline."""
    _send(browser, prompt)
    timeline = []
    started = time.time()
    while time.time() - started < limit:
        row = _state(browser)
        row['t'] = round(time.time() - started, 2)
        timeline.append(row)
        if row['errors']:
            break
        if row['text'] and not browser.execute_script('return AIWorkspace._sending === true;'):
            time.sleep(0.5)
            tail = _state(browser)
            tail['t'] = round(time.time() - started, 2)
            timeline.append(tail)
            break
        time.sleep(SAMPLE_SECONDS)
    return timeline


class TestTheLiveLineOfARealAnswer:
    """One whole local answer, read every 250 ms."""

    def test_the_line_is_there_at_every_moment_until_the_ending(self, ai_browser, ai_server, daemon):
        picked = _open_local(ai_browser, ai_server, daemon['model'])
        timeline = _run_turn(ai_browser, SHORT_PROMPT)
        visible = [row for row in timeline if row['visible']]
        assert len(visible) >= 3, (
            f'measured {len(timeline)} samples (model {picked["model"]}) and only {len(visible)} showed the live line'
        )
        assert timeline and timeline[-1]['text'], f'the turn produced no answer text: {timeline[-1]}'

        # Every moment BETWEEN the first and the last visible sample must also be visible: that is
        # the whole point — a line that blinks off under a finished paragraph is the defect.
        first_at = timeline.index(visible[0])
        last_at = len(timeline) - 1 - timeline[::-1].index(visible[-1])
        gaps = [row['t'] for row in timeline[first_at : last_at + 1] if not row['visible']]
        assert gaps == [], f'the live line vanished mid-turn at t={gaps} of {len(timeline)} samples'

        words = set(visible[0]['words'])
        said = {row['phase'] for row in visible}
        assert said <= words and all(said), f'phase wording outside the catalogue: {said} vs {words}'
        assert all(row['clock'] for row in visible), (
            f'{len(visible)} visible samples and at least one showed no clock: {[row["clock"] for row in visible]}'
        )
        laid_out = {row['display'] for row in visible}
        assert 'none' not in laid_out, f'the live line was hidden while the turn was open: {laid_out}'
        assert any(row['height'] for row in visible), 'the live line was visible but took no space'

        elapsed = visible[-1]['t'] - visible[0]['t']
        if elapsed >= MIN_SECONDS_FOR_A_TICK:
            clocks = {row['clock'] for row in visible}
            assert len(clocks) >= 2, f'the turn ran {elapsed}s and the clock never moved: {clocks}'
        assert timeline[-1]['visible'] is False, 'the live line outlived the answer'
        # Hidden means GONE, not merely moved: `.ai-status` is `display:flex`, so the `hidden`
        # attribute alone would leave a row of empty space if the CSS rule were dropped.
        assert timeline[-1]['display'] == 'none', f'the ended turn still lays the line out: {timeline[-1]}'

    def test_stop_ends_the_line_and_says_so(self, ai_browser, ai_server, daemon):
        _open_local(ai_browser, ai_server, daemon['model'])
        _send(ai_browser, LONG_PROMPT)
        assert _wait(ai_browser, 'return AIWorkspace._sending === true;', 20), 'the turn never started'
        assert _wait(ai_browser, "const s = document.querySelector('.ai-status'); return !!(s && !s.hidden);", 20), (
            f'no live line while the turn streamed: {_state(ai_browser)}'
        )
        time.sleep(1.6)
        mid = _state(ai_browser)
        assert mid['visible'] and mid['clock'], f'the live line stopped proving life mid-answer: {mid}'

        ai_browser.execute_script('AIWorkspace.stop();')
        assert _wait(ai_browser, 'return AIWorkspace._sending === false;', 20), 'stop did not settle the turn'
        time.sleep(0.5)
        after = _state(ai_browser)
        assert after['visible'] is False, f'the live line stayed visible after stop: {after}'
        assert after['stoppedWord'] in after['notes'], f'stop left no sentence of its own: {after["notes"]}'
        assert not after['errors'], f'a stopped turn painted an error: {after["errors"]}'
