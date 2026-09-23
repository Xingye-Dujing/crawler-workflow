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


# ─── the node card, over every platform × every mode ──────────────────────


def _identifier_fields(mode: dict) -> list:
    """The fields that say *what* is being collected, as the card defines it.

    A required text/textarea names the target (关键词 / 作者 / 链接), and a select is
    always named because a board the card never mentions would be a second guess
    about what will run. Optional text (微博's time window) is a refinement of the
    same crawl, and the card has two lines — so it belongs in the panel, not here.
    """
    return [
        f
        for f in mode['fields']
        if f['control'] == 'select' or (f['control'] in ('text', 'textarea') and f['required'])
    ]


def _filled(cap: dict, mode: dict) -> dict:
    params = {'platform': cap['platform'], 'collect': mode['key']}
    for field in mode['fields']:
        if field['coerce'] == 'urls':
            params[field['key']] = 'first link\nsecond link\nthird link'
        elif field['control'] == 'select':
            # The *second* option where there is one: a card that only ever echoes
            # the default could not tell a chosen board from an unchosen one.
            options = field['options']
            params[field['key']] = options[-1]['value'] if len(options) > 1 else field['default']
        elif field['control'] == 'text':
            params[field['key']] = f'V-{field["key"]}'
    return params


@pytest.fixture(scope='module')
def cards(tmp_path_factory):
    """Every declared platform and mode, one node harness run."""
    matrix = _matrix()
    scenarios, keys = [], []
    for cap in matrix['platforms']:
        for mode in cap['modes']:
            key = f'{cap["platform"]}-{mode["key"]}'
            keys.append(key)
            scenarios.append({'id': key, 'payload': matrix, 'params': _filled(cap, mode)})
    # The reported bug, spelled: a 热榜 node still holding the keyword the user
    # typed before they switched 采集内容. The card must not keep quoting it.
    stale = {
        'id': 'bilibili-stale',
        'payload': matrix,
        'params': {'platform': 'bilibili', 'collect': 'hot', 'keyword': 'CHATGPT-LEFTOVER'},
    }
    scenarios.append(stale)
    keys.append('bilibili-stale')
    # The same node on a cold page: the draft drew it before /api/capabilities
    # answered, so the card must claim nothing it cannot yet know.
    cold = {'id': 'cold-hot', 'payload': None, 'params': {'platform': 'bilibili', 'collect': 'hot', 'keyword': 'x'}}
    scenarios.append(cold)
    keys.append('cold-hot')
    refresh = {'id': 'redraw', 'payload': matrix, 'params': {'platform': 'zhihu', 'keyword': 'ai'}, 'refresh': True}
    scenarios.append(refresh)
    keys.append('redraw')
    tmp = tmp_path_factory.mktemp('caps-cards')
    results = _run(tmp, scenarios)
    return matrix, keys, results


def _pairs(matrix: dict, results: dict):
    """Yield ``(where, summary)`` for every declared platform × mode.

    `where` names the pair in the assertion message; the lookup is spelled once
    because four tests sweep the same table.
    """
    for cap in matrix['platforms']:
        for mode in cap['modes']:
            where = f'{cap["platform"]}/{mode["key"]}'
            yield where, results[f'{cap["platform"]}-{mode["key"]}']['summary'], mode


class TestNodeCardFollowsTheMatrix:
    """The card used to be two hard-coded branches plus a default of 关键词.

    Every mode outside those two — 某作者的作品 on the five platforms that have it,
    热榜, and 文章正文 on WeChat — therefore printed a keyword it never crawled, and
    a stale one at that. Nothing tested the card, so nothing noticed; this class is
    the missing coverage, and it is generated from the matrix so a new mode is
    covered by declaring it, not by adding a case here.
    """

    def test_every_mode_is_covered_by_this_sweep(self, cards):
        _matrix, keys, results = cards
        assert len(keys) >= 20, f'the sweep shrank to {len(keys)} platform×mode pairs'
        assert set(results) == set(keys)

    def test_the_card_names_the_collection_mode_it_shows(self, cards):
        matrix, _keys, results = cards
        for where, summary, mode in _pairs(matrix, results):
            assert mode['labelKey'] in summary, f'{where} card omits its own mode: {summary}'

    def test_the_card_prints_the_fields_the_mode_actually_has(self, cards):
        matrix, _keys, results = cards
        for where, summary, mode in _pairs(matrix, results):
            for field in _identifier_fields(mode):
                detail = f'{where} card omits {field["key"]}: {summary}'
                assert field['labelKey'] in summary, detail
                if field['control'] == 'text':
                    assert f'V-{field["key"]}' in summary, f'{where}: {field["key"]} value missing: {summary}'
                if field['control'] == 'select':
                    options = field['options']
                    chosen = (options[-1] if len(options) > 1 else options[0])['labelKey']
                    assert chosen in summary, f'{where}: {field["key"]} shows its default, not the choice'

    def test_a_mode_without_a_keyword_never_prints_one(self, cards):
        matrix, _keys, results = cards
        for where, summary, mode in _pairs(matrix, results):
            if any(f['key'] == 'keyword' for f in mode['fields']):
                continue
            assert 'settings.keyword' not in summary, f'{where} promises a keyword it never crawls: {summary}'

    def test_a_leftover_keyword_is_not_resurrected_after_switching_mode(self, cards):
        _matrix, _keys, results = cards
        summary = results['bilibili-stale']['summary']
        assert 'settings.keyword' not in summary and 'CHATGPT-LEFTOVER' not in summary, summary
        assert 'settings.collectHot' in summary and 'settings.hotBoard' in summary, summary

    def test_a_link_field_is_counted_rather_than_dumped(self, cards):
        matrix, _keys, results = cards
        checked = 0
        for cap in matrix['platforms']:
            for mode in cap['modes']:
                urls = [f for f in mode['fields'] if f['coerce'] == 'urls']
                if not urls:
                    continue
                summary = results[f'{cap["platform"]}-{mode["key"]}']['summary']
                checked += 1
                assert ': 3' in summary, f'{cap["platform"]}/{mode["key"]} does not count its links: {summary}'
                assert 'first link' not in summary, f'{cap["platform"]}/{mode["key"]} dumps the paste: {summary}'
        assert checked >= 5, f'only {checked} modes read links, so this assertion has gone vacuous'

    def test_a_card_drawn_before_the_matrix_arrives_claims_nothing(self, cards):
        """A restored draft paints its nodes on a cold page, and the matrix comes
        back a moment later. The honest interim card is the platform alone — a
        fallback to 关键词 here is the same wrong claim, only transient."""
        _matrix, _keys, results = cards
        summary = results['cold-hot']['summary']
        assert 'settings.keyword' not in summary and 'x' not in summary, summary
        assert 'platform.bilibili' in summary, summary

    def test_the_matrix_load_redraws_only_the_nodes_that_read_it(self, cards):
        """``Capabilities.load`` re-stamps the source cards (they are generated from
        its payload); a process/analysis/visualize card is untouched, because
        redrawing every node on a network answer would undo a rename mid-flight."""
        _matrix, _keys, results = cards
        # `n1` is the scenario's own source node, added before the spy was wired.
        assert sorted(results['redraw']['restamped']) == ['a_source', 'c_source', 'n1'], results['redraw']['restamped']
