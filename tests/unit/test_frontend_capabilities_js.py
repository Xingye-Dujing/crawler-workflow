"""The generated Data Source panel: what it does with the answer it got.

``crawl_capabilities`` is now the only description of what a platform can
collect, and ``workflow.js`` renders that description. The half that used to be a
hand-written form is where new failure modes appear, and they are all about
*answers*: none, a nonsense one, a platform nobody declared, a field name that
is not a name. Each is a network response, so each is tested here against the
real renderer rather than argued about in a comment.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

import crawl_capabilities

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_capabilities.mjs'


def _run(tmp_path: Path, scenarios: list) -> dict:
    file = tmp_path / 'scenarios.json'
    file.write_text(json.dumps(scenarios, ensure_ascii=False), encoding='utf-8')
    proc = run_node(str(HARNESS), str(JS_DIR / 'canvas.js'), str(JS_DIR / 'workflow.js'), str(file))
    assert proc.returncode == 0, f'harness failed: {proc.stderr}'
    return json.loads(proc.stdout)


def _matrix() -> dict:
    return crawl_capabilities.as_dict()


@pytest.fixture(scope='module')
def panel(tmp_path_factory):
    """Four payloads, one run: loaded / never answered / garbage / declared-elsewhere."""
    tmp = tmp_path_factory.mktemp('caps-panel')
    zhihu = _matrix()
    hostile = _matrix()
    for cap in hostile['platforms']:
        if cap['platform'] != 'zhihu':
            continue
        # Addressed by mode key, never by position: a platform gaining a mode is a
        # normal edit, and an index here would then poison the wrong mode and the
        # panel would be tested against a payload the matrix never describes.
        modes = {mode['key']: mode for mode in cap['modes']}
        modes['posts']['fields'][0]['key'] = "keyword',alert(1)//"
        modes['comments']['noteKey'] = 'settings.wechatLimitsNote'
        modes['comments']['actionKey'] = 'settings.wechatLimitsBtn'
        modes['comments']['actionJs'] = 'noSuchFunctionAnywhere'
    return _run(
        tmp,
        [
            {'id': 'loaded', 'payload': zhihu, 'params': {'platform': 'zhihu', 'keyword': 'ai'}},
            {'id': 'unanswered', 'payload': None, 'params': {'platform': 'zhihu'}},
            {'id': 'malformed', 'payload': 'malformed', 'params': {'platform': 'zhihu'}},
            {'id': 'undeclared', 'payload': zhihu, 'params': {'platform': 'kuaishou'}},
            {'id': 'hostile', 'payload': hostile, 'params': {'platform': 'zhihu', 'collect': 'comments'}},
            {'id': 'wechat', 'payload': zhihu, 'params': {'platform': 'wechat'}},
        ],
    )


class TestLoadedPanel:
    def test_the_matrix_decides_which_fields_appear(self, panel):
        html = panel['loaded']['html']
        assert 'settings.platform' in html and 'settings.keyword' in html
        assert 'settings.targetCount' in html and 'settings.partSize' in html
        assert 'settings.urls' not in html, 'a keyword mode must not ask for links'

    def test_the_platform_select_offers_every_declared_platform(self, panel):
        html = panel['loaded']['html']
        for platform in crawl_capabilities.platform_ids():
            assert f'value="{platform}"' in html, f'{platform} never reached the select'

    def test_the_mode_select_is_a_choice_and_not_a_caption(self, panel):
        html = panel['loaded']['html']
        assert 'value="posts" selected' in html and 'value="comments"' in html

    def test_a_fresh_node_is_seeded_from_the_matrix(self, panel):
        defaults = panel['loaded']['defaults']
        expected = crawl_capabilities.declared_defaults('zhihu')
        expected.update({'platform': 'zhihu', 'collect': 'posts'})
        assert defaults == expected

    def test_the_modes_it_lists_are_the_modes_the_server_has(self, panel):
        assert panel['loaded']['modes'] == list(crawl_capabilities.mode_keys_for('zhihu'))


class TestUnanswerablePanel:
    def test_no_payload_is_said_so_rather_than_shown_as_an_empty_form(self, panel):
        for case in ('unanswered', 'malformed'):
            html = panel[case]['html']
            assert 'settings.capFailed' in html, f'{case} rendered a form out of nothing'
            assert 'btn.retry' in html, f'{case} gave the user no way out'
            assert 'settings.keyword' not in html, f'{case} offered fields the run cannot use'

    def test_a_platform_nobody_declared_refuses_in_the_panel(self, panel):
        html = panel['undeclared']['html']
        assert 'settings.capNoMode' in html
        assert 'settings.keyword' not in html and 'settings.urls' not in html

    def test_the_failure_is_not_reported_as_a_loaded_matrix(self, panel):
        assert panel['unanswered']['ready'] is False and panel['loaded']['ready'] is True


class TestHostilePayload:
    """The payload is a network response and the panel writes field names into
    inline handlers, so a name that is not a name has to be dropped whole."""

    def test_a_field_key_that_is_not_an_identifier_loses_its_control(self, panel):
        html = panel['hostile']['html']
        assert 'alert' not in html, 'a payload name reached executable position'
        assert "updateParam('n1','keyword'" not in html

    def test_a_button_the_page_cannot_service_is_not_drawn(self, panel):
        html = panel['hostile']['html']
        assert 'settings.wechatLimitsNote' in html, 'the note still belongs to the mode'
        assert 'noSuchFunctionAnywhere' not in html, 'a dead button was wired to a click'

    def test_the_real_wechat_note_keeps_its_reason(self, panel):
        html = panel['wechat']['html']
        assert 'settings.wechatLimitsNote' in html and 'explainWechatLimits()' in html

    def test_wechat_offers_no_mode_select_because_it_offers_one_mode(self, panel):
        html = panel['wechat']['html']
        assert 'settings.collect' not in html, 'a one-option select is a caption wearing a widget'
