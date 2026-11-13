"""The update card: its own logic under node, and the two rules only the stylesheet can break.

Two halves, and neither is visible to the other.

* ``harness_update.mjs`` drives the REAL ``update.js`` (with the real ``app.js`` catalogue): a
  prompt with both answers, 稍后 remembered for a day per version (it lived in ``sessionStorage``,
  which a desktop window forgets the moment it closes), 不再提示此版本, a download that repaints
  from the server job, the restart hand-off, a page loaded mid-download reattaching instead of
  offering the download again, the "use the installer" state, a named failure with 重试, cancel,
  and the language repaint of the one sentence the card formats itself.
* The stylesheet is where "it covers the menu" and "it is not OMM-ZEN" used to live: the card must
  sit below ``--menuH`` (menu strip) with a z-index under the menu's, and it must read the shared
  design tokens rather than inventing a pill with a black shadow.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from frontend_catalogue import with_catalogue, with_companions
from node_runner import run_node
from static_assets import js_text

REPO = Path(__file__).resolve().parents[3]
JS_DIR = REPO / 'backend' / 'static' / 'js'
STATIC_DIR = REPO / 'backend' / 'static'
HARNESS = Path(__file__).resolve().parents[2] / 'frontend' / 'harness_update.mjs'

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]


def strip_comments(text: str) -> str:
    """Prose is not a declaration: a comment may NAME the anti-pattern a gate refuses."""
    without_block = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'(?m)^\s*//.*$', '', without_block)


@pytest.fixture(scope='module')
def results():
    # app.js merges js/i18n/*.js at load: a harness that boots it without them sees every t() echo
    # its own key, and a sentence asserted against that echo proves nothing.
    proc = run_node(
        str(HARNESS),
        *with_catalogue(
            with_companions(
                [
                    JS_DIR / 'workflow.js',
                    JS_DIR / 'app.js',
                    JS_DIR / 'update.js',
                ]
            )
        ),
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# ─── The prompt ───


class TestThePrompt:
    def test_it_offers_both_answers_without_asking_anything_first(self, results):
        ready = results['ready']
        assert ready['hidden'] is False
        assert ready['label'] == '更新'
        assert ready['version'] == '2026.12.1.1'
        assert ready['text'] == '发现新版本 2026.12.1.1'
        assert ready['now'] == '立即更新'
        assert ready['later'] == '稍后', 'the prompt itself must carry 稍后, not only the dialog'
        assert ready['cancel'] is None
        assert ready['progress'] is None
        assert results['readyCalls'] == {'posts': 0, 'dialogs': 0}, 'the prompt asks nothing yet'

    def test_a_version_this_install_cannot_apply_says_so_and_offers_no_download(self, results):
        unsupported = results['unsupported']
        assert unsupported['now'] is None, 'a download that ends in a refusal must not be offered'
        assert unsupported['later'] == '稍后'
        assert '安装器' in unsupported['text']
        assert '2026.12.3.1' in unsupported['text']


class TestPostponing:
    def test_later_remembers_the_version_for_a_day(self, results):
        assert results['afterLater']['hidden'] is True
        snooze = results['snooze']
        assert snooze['version'] == '2026.12.1.1'
        assert snooze['skip'] is False
        assert 23 <= results['snoozeHours'] <= 24, 'a day of quiet, not the rest of the session'

    def test_the_same_version_stays_quiet_on_the_next_check(self, results):
        assert results['snoozedAgain']['hidden'] is True

    def test_a_newer_version_speaks_up_again(self, results):
        assert results['newerVersion']['hidden'] is False
        assert results['newerVersion']['version'] == '2026.12.2.1'

    def test_do_not_ask_again_is_about_that_version_only(self, results):
        assert results['skip']['skip'] is True
        assert results['skip']['version'] == '2026.12.2.1'
        assert results['afterSkip']['hidden'] is False, 'a later release must still be offered'
        assert results['afterSkip']['version'] == '2026.12.2.2'


class TestTheDownload:
    def test_starting_posts_once_and_follows_the_job(self, results):
        assert results['downloadPosts'] == ['/api/update/download']
        downloading = results['downloading']
        assert downloading['now'] is None, 'no second 立即更新 while the first one runs'
        assert downloading['cancel'] == '取消'
        assert downloading['progress'] == '0%'
        assert '正在下载更新' in downloading['text']

    def test_a_reload_reattaches_to_the_running_job(self, results):
        reattached = results['reattached']
        assert reattached['hidden'] is False
        assert reattached['progress'] == '42%'
        assert '42%' in reattached['text']
        assert reattached['now'] is None

    def test_the_finished_download_offers_the_restart(self, results):
        staged = results['staged']
        assert staged['text'] == '更新 2026.12.2.2 已就绪，重启即可完成'
        assert staged['now'] == '重启并完成更新'
        assert staged['progress'] is None
        assert results['pollingStopped'] is True, 'a finished download must stop polling'

    def test_the_restart_is_one_post_and_then_the_page_is_patient(self, results):
        assert results['restartPosts'][-1] == '/api/update/restart'
        applying = results['applying']
        assert applying['text'] == '正在重启并完成更新…'
        assert applying['now'] is None and applying['later'] is None

    def test_cancel_leaves_nothing_behind(self, results):
        assert results['cancelled']['hidden'] is True

    def test_a_failure_is_a_named_reason_with_a_retry(self, results):
        failed = results['failed']
        assert failed['hidden'] is False
        assert '更新失败' in failed['text']
        assert '摘要不符' in failed['text'], 'the machine sentence is kept beside the translated code'
        assert 'SHA-256' in failed['text']
        assert failed['now'] == '重试'


class TestTheLanguageSwitch:
    def test_the_sentence_is_repainted_not_re_requested(self, results):
        assert results['chinese']['label'] == '更新'
        assert results['chinese']['text'] == '发现新版本 2026.12.5.1'
        assert results['english']['label'] == 'Update'
        assert results['english']['text'] == 'Version 2026.12.5.1 is available'
        assert results['english']['now'] == 'Update now'
        assert results['english']['later'] == 'Later'


class TestTheManualCheck:
    """The settings-menu button: the same request the boot timer makes, with an answer."""

    def test_a_press_is_not_silenced_by_a_snooze(self, results):
        manual = results['manualCheck']
        assert manual['hidden'] is False
        assert manual['version'] == '2026.12.6.1'
        assert manual['now'] == 'Update now'
        assert '2026.12.6.1' in results['manualToast']

    def test_nothing_to_offer_still_gets_an_answer(self, results):
        assert results['manualLatest']['hidden'] is True
        assert '2026.11.11.2' in results['manualLatestToast']

    def test_a_host_with_no_feed_names_why(self, results):
        assert results['manualNoChannel']['hidden'] is True
        assert 'installer' in results['manualNoChannelToast']


# ─── The stylesheet ───


class TestTheCardSitsBelowTheMenu:
    CSS = strip_comments((STATIC_DIR / 'css' / 'update.css').read_text(encoding='utf-8'))
    MENU = strip_comments((STATIC_DIR / 'css' / 'menu.css').read_text(encoding='utf-8'))

    def test_it_starts_below_the_menu_strip(self):
        """The old card was at top:18px over a 48px menu bar; it hid the only navigation."""
        assert 'top: calc(var(--menuH)' in self.CSS
        assert re.search(r'top:\s*18px', self.CSS) is None

    def test_it_cannot_paint_over_the_menu(self):
        banner = int(re.search(r'#update-banner\s*\{[^}]*z-index:\s*(\d+)', self.CSS).group(1))
        menu = int(re.search(r'#top-menu\s*\{[^}]*z-index:\s*(\d+)', self.MENU).group(1))
        assert banner < menu, 'a notice must never cover the menu'


class TestTheCardIsOmmZen:
    CSS = strip_comments((STATIC_DIR / 'css' / 'update.css').read_text(encoding='utf-8'))

    def test_it_reads_the_shared_tokens(self):
        for token in ('var(--paper)', 'var(--line)', 'var(--radius)', 'var(--shadow-soft)', 'var(--text)'):
            assert token in self.CSS, token

    def test_no_page_local_palette_or_pill(self):
        assert '999px' not in self.CSS, 'every corner in this app comes from --radius'
        assert '#fff' not in self.CSS
        assert 'rgba(' not in self.CSS
        assert 'box-shadow: 0 10px 30px' not in self.CSS

    def test_the_progress_is_a_hairline_of_ink(self):
        assert 'var(--ink)' in self.CSS
        assert 'height: 2px' in self.CSS


class TestThePanelCode:
    def test_the_snooze_is_remembered_not_forgotten(self):
        source = strip_comments(js_text('update.js'))
        assert 'sessionStorage' not in source, 'a desktop window forgets sessionStorage on close'
        assert 'localStorage' in source
        assert "'update-snooze'" in source

    def test_every_route_it_calls_exists(self):
        source = strip_comments(js_text('update.js'))
        api = (STATIC_DIR / '..' / 'api' / 'update.py').resolve()
        server = api.read_text(encoding='utf-8')
        for route in (
            '/api/update/check',
            '/api/update/download',
            '/api/update/status',
            '/api/update/restart',
            '/api/update/cancel',
        ):
            assert route in source, route
            assert route in server, route
