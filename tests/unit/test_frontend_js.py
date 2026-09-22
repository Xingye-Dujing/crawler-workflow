"""Behaviour tests for the REAL frontend JS, run through node (no npm).

The browser validates a canvas BEFORE the server is ever asked to run it
(workflow.js:validate), routes comment links by domain (urlPlatform) and
normalises platform switches (selectSourcePlatform). Those decisions change
what a run produces, so they are product logic — and product logic lives under
test. Each harness loads the untouched file from backend/static/js and prints
what it computed; this module asserts on that.

Requirements: plain `node` on PATH (already needed for the canvas harness).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from utils.helpers import platform_for

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_validate.mjs'


def _parse(msg: str) -> tuple:
    """'validate.key|Title|2|zhihu|{col}|{op}' → ('validate.key', {...})."""
    head, *fields = msg.split('|')
    names = ['title', 'n', 'plat', 'col', 'op']
    out = {}
    for name, value in zip(names, fields, strict=False):
        if not value.startswith('{'):  # unfilled placeholders stay literal
            out[name] = value
    return head, out


def _run_validate(tmp_path: Path, scenarios: list) -> dict:
    sc_path = tmp_path / 'scenarios.json'
    sc_path.write_text(json.dumps(scenarios, ensure_ascii=False), encoding='utf-8')
    proc = subprocess.run(
        ['node', str(HARNESS), str(JS_DIR / 'workflow.js'), str(sc_path)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=60,
    )
    assert proc.returncode == 0, f'harness failed: {proc.stderr}'
    return json.loads(proc.stdout)


def _node(nid, ntype, params, title='t'):
    return {'id': nid, 'type': ntype, 'title': title, 'params': params}


def _save(nid='out-1', filename='f'):
    return {'id': nid, 'type': 'output', 'title': '保存', 'params': {'operation': 'save', 'filename': filename}}


@pytest.fixture(scope='module')
def results(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('js-validate')
    scenarios = [
        {
            'id': 'clean',
            'nodes': [_node('n1', 'source', {'platform': 'weibo', 'keyword': 'k'}), _save()],
            'connections': [{'from': 'n1', 'to': 'out-1'}],
        },
        {
            'id': 'comments_mismatch',
            'nodes': [
                _node(
                    'n1',
                    'source',
                    {
                        'platform': 'zhihu',
                        'collect': 'comments',
                        'urls': 'https://www.zhihu.com/question/1\nhttps://weibo.com/1/a\njunk',
                    },
                ),
                _save(),
            ],
            'connections': [{'from': 'n1', 'to': 'out-1'}],
        },
        {
            'id': 'comments_ok',
            'nodes': [
                _node(
                    'n1',
                    'source',
                    {
                        'platform': 'zhihu',
                        'collect': 'comments',
                        'urls': 'https://www.zhihu.com/question/1, https://www.zhihu.com/question/2',
                    },
                ),
                _save(),
            ],
            'connections': [{'from': 'n1', 'to': 'out-1'}],
        },
        {
            'id': 'comments_empty',
            'nodes': [
                _node('n1', 'source', {'platform': 'zhihu', 'collect': 'comments', 'urls': '   '}, title=''),
                _save(),
            ],
            'connections': [{'from': 'n1', 'to': 'out-1'}],
        },
        {
            'id': 'wechat_stale_comments',
            'nodes': [
                _node(
                    'n1',
                    'source',
                    {'platform': 'wechat', 'collect': 'comments', 'urls': 'https://mp.weixin.qq.com/s/abc'},
                ),
                _save(),
            ],
            'connections': [{'from': 'n1', 'to': 'out-1'}],
        },
        {
            'id': 'no_terminal',
            'nodes': [_node('n1', 'source', {'platform': 'zhihu', 'keyword': 'k'})],
            'connections': [],
        },
        {'id': 'empty', 'nodes': [], 'connections': []},
        {
            'id': 'titleless',
            'nodes': [
                {'id': 'n1', 'type': 'source', 'title': None, 'params': {'platform': 'zhihu', 'keyword': ''}},
                _save(),
            ],
            'connections': [{'from': 'n1', 'to': 'out-1'}],
        },
        # ── settings-panel renders (node = openSettings target, HTML captured) ──
        *(
            {'id': pid, 'node': _node('n1', ntype, params)}
            for pid, ntype, params in (
                ('panel_zhihu_comments', 'source', {'platform': 'zhihu', 'collect': 'comments', 'urls': ''}),
                (
                    'panel_weibo_comments',
                    'source',
                    {'platform': 'weibo', 'collect': 'comments', 'urls': 'https://weibo.com/1/a'},
                ),
                ('panel_xhs_comments', 'source', {'platform': 'xiaohongshu', 'collect': 'comments', 'urls': ''}),
                (
                    'panel_wechat_stale',
                    'source',
                    {'platform': 'wechat', 'collect': 'comments', 'urls': 'https://mp.weixin.qq.com/s/x'},
                ),
                ('panel_zhihu_posts', 'source', {'platform': 'zhihu', 'collect': 'posts', 'keyword': 'k'}),
                ('panel_legacy_comment', 'comment', {'urls': ''}),
            )
        ),
    ]
    return _run_validate(tmp, scenarios)


class TestValidateGate:
    def test_a_wired_clean_canvas_passes(self, results):
        assert results['validate']['clean'] == []

    def test_foreign_platform_links_are_flagged_with_count_and_platform(self, results):
        parsed = [_parse(m) for m in results['validate']['comments_mismatch']]
        assert len(parsed) == 1
        key, fields = parsed[0]
        assert key == 'validate.sourceCommentPlat'
        # two of the three lines are not zhihu links — the message says exactly that
        assert fields['n'] == '2'
        assert fields['plat'] == 'zhihu'
        assert fields['title'] == 't'

    def test_comma_separated_links_are_split_like_the_backend(self, results):
        # The backend's split_urls accepts commas; the validator must not flag
        # what the executor will happily crawl.
        assert results['validate']['comments_ok'] == []

    def test_comments_mode_without_urls_names_the_urls_rule(self, results):
        key, fields = _parse(results['validate']['comments_empty'][0])
        assert key == 'validate.sourceCommentUrls'

    def test_wechat_with_a_stale_comments_flag_validates_as_article_crawl(self, results):
        # collect='comments' + wechat is the panel's old leak; both ends now
        # read it as the URL-driven article crawl it is — no comments error.
        assert results['validate']['wechat_stale_comments'] == []

    def test_an_unwired_source_is_reported_twice_reasonably(self, results):
        keys = [_parse(m)[0] for m in results['validate']['no_terminal']]
        assert keys == ['validate.sourceDownstream', 'validate.noTerminal']

    def test_an_empty_canvas_short_circuits(self, results):
        keys = [_parse(m)[0] for m in results['validate']['empty']]
        assert keys == ['validate.empty']

    def test_a_titleless_node_never_prints_undefined(self, results):
        # title=None must fall back to the type label — 'Source', not 'null'.
        parsed = [_parse(m) for m in results['validate']['titleless']]
        keywords = [k for k, _ in parsed]
        assert 'validate.sourceKeyword' in keywords
        got = next(f for k, f in parsed if k == 'validate.sourceKeyword')
        assert got['title'] == 'Source'


class TestSettingsPanel:
    """The panel HTML a user sees when they click a node — produced by the
    REAL openSettings(). The per-platform placeholder rule (the user's exact
    complaint: '平台选知乎就只能知乎') is pinned here end to end."""

    def test_zhihu_comments_panel_offers_only_zhihu_links(self, results):
        html = results['settings']['panel_zhihu_comments']
        assert 'https://www.zhihu.com/question/' in html
        assert 'weibo.com' not in html
        assert 'xiaohongshu.com' not in html
        assert 'settings.commentUrlsHintPlat' in html  # the selected-platform hint

    def test_weibo_comments_panel_offers_only_weibo_links(self, results):
        html = results['settings']['panel_weibo_comments']
        assert 'https://weibo.com/' in html
        assert 'zhihu.com' not in html
        assert 'xiaohongshu.com' not in html
        # comments mode has no time range — weibo's start/end fields stay hidden
        assert 'start_time' not in html

    def test_xiaohongshu_comments_panel_offers_only_xhs_links(self, results):
        html = results['settings']['panel_xhs_comments']
        assert 'xiaohongshu.com/explore/' in html
        assert 'zhihu.com' not in html
        assert 'weibo.com' not in html

    def test_wechat_ignores_a_stale_comments_flag_and_keeps_article_links(self, results):
        html = results['settings']['panel_wechat_stale']
        # no collect selector at all for WeChat, no comments textarea
        assert 'settings.collect' not in html
        assert 'settings.commentUrls' not in html
        # and the WeChat article-URL block IS there
        assert 'mp.weixin.qq.com/s/' in html

    def test_posts_mode_panel_offers_keyword_and_the_mode_selector(self, results):
        html = results['settings']['panel_zhihu_posts']
        assert 'settings.keyword' in html
        assert 'settings.collect' in html
        assert 'settings.commentUrls' not in html

    def test_legacy_comment_node_states_the_mix_is_deliberate(self, results):
        # The old standalone Comment node still crawls mixed links (each routed
        # by domain), so its panel must NOT pretend one platform is selected.
        html = results['settings']['panel_legacy_comment']
        assert 'settings.commentUrlsHintMixed' in html
        assert 'zhihu.com' in html and 'weibo.com' in html and 'xiaohongshu.com' in html


class TestUrlRoutingContract:
    """urlPlatform is a JS copy of the Python router — pin them equal."""

    def test_js_and_python_agree_on_every_link_shape(self, results):
        for url, js_platform in results['url']:
            assert js_platform == platform_for(url), f'routing disagreement on {url}'

    def test_placeholder_shows_only_the_selected_platform(self, results):
        marker = {
            'zhihu': 'zhihu.com',
            'weibo': 'weibo.com',
            'xiaohongshu': 'xiaohongshu.com',
            'bilibili': 'bilibili.com',
            'douyin': 'douyin.com',
        }
        for platform, domain in marker.items():
            ph = results['placeholder'][platform]
            assert domain in ph, f'{platform} placeholder must show its own domain'
            for other, other_domain in marker.items():
                if other != platform:
                    assert other_domain not in ph, f'{platform} placeholder must not leak {other}'


class TestPlatformSwitch:
    def test_moving_to_wechat_resets_the_comments_mode(self, results):
        # WeChat has no comment adapter; leaving collect='comments' behind
        # would route article links into the comment engine and drop them all.
        assert results['platformSwitch']['zhihu_to_wechat'] == 'posts'

    def test_moving_between_crawl_platforms_keeps_the_mode(self, results):
        assert results['platformSwitch']['zhihu_to_weibo'] == 'comments'
        assert results['platformSwitch']['wechat_to_zhihu'] == 'comments'


APP_HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_app.mjs'

# (scenario id, panels opened BEFORE the click, click ancestry, expectation:
#  which of dashboard/history must STILL be open after the click)
_POPUP_CASES = [
    ('canvas-click-closes-all', ['dashboard-panel', 'history-panel'], ['#workspace'], set()),
    (
        'inside-history-keeps-both',
        ['dashboard-panel', 'history-panel'],
        ['#history-panel'],
        {'dashboard-panel', 'history-panel'},
    ),
    (
        'inside-dashboard-keeps-both',
        ['dashboard-panel', 'history-panel'],
        ['#dashboard-panel'],
        {'dashboard-panel', 'history-panel'},
    ),
    (
        'custom-select-menu-keeps-both',
        ['dashboard-panel', 'history-panel'],
        ['.cselect-menu'],
        {'dashboard-panel', 'history-panel'},
    ),
    ('suggestion-menu-keeps-history', ['history-panel'], ['.cand-menu'], {'history-panel'}),
    ('modal-dialog-keeps-history', ['history-panel'], ['#dialog-overlay'], {'history-panel'}),
    ('cookie-dialog-keeps-dashboard', ['dashboard-panel'], ['#cookie-dialog'], {'dashboard-panel'}),
    ('settings-panel-is-outside', ['dashboard-panel'], ['#node-settings'], set()),
    ('nothing-open-is-harmless', [], ['#workspace'], set()),
]

_POPUP_SCENARIOS = [
    {'id': 'i18n-runtime'},
    *({'id': cid, 'open': opened, 'ancestors': anc} for cid, opened, anc, _ in _POPUP_CASES),
]


@pytest.fixture(scope='module')
def popup_results(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('js-popup')
    sc_path = tmp / 'scenarios.json'
    sc_path.write_text(json.dumps(_POPUP_SCENARIOS, ensure_ascii=False), encoding='utf-8')
    proc = subprocess.run(
        ['node', str(APP_HARNESS), str(JS_DIR), str(sc_path)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=60,
    )
    assert proc.returncode == 0, f'popup harness failed: {proc.stderr}'
    return json.loads(proc.stdout)


class TestPopupOutsideClick:
    """The dashboard and history popups are floating windows: a click back
    into the workspace must dismiss them, but working INSIDE either popup —
    including its option menus, which render outside the panel DOM — may
    never discard anything (the user asked for exactly this pair)."""

    @pytest.mark.parametrize('case, _opened, _ancestors, expect', _POPUP_CASES, ids=[c[0] for c in _POPUP_CASES])
    def test_click_outcome(self, popup_results, case, _opened, _ancestors, expect):
        report = popup_results[case]
        for panel in ('dashboard-panel', 'history-panel'):
            assert report[panel] == (panel in expect), f'{panel} wrong for {case}'


class TestI18nRuntime:
    """The catalog itself, loaded from app.js and exercised — not regexed."""

    def test_the_two_languages_define_the_same_keys(self, popup_results):
        r = popup_results['i18n-runtime']
        assert r['onlyEn'] == [], 'keys defined only in EN'
        assert r['onlyZh'] == [], 'keys defined only in ZH'
        assert r['enCount'] > 100 and r['zhCount'] == r['enCount']

    def test_each_language_renders_its_own_words(self, popup_results):
        r = popup_results['i18n-runtime']
        assert r['enUpload'] != r['zhUpload']
        assert 'Upload' in r['enUpload']

    def test_an_unknown_language_falls_back_instead_of_crashing(self, popup_results):
        # 'de' ships no dictionary: the reader must still get English, and a
        # truly unknown key must echo itself (never a half-substituted mess).
        r = popup_results['i18n-runtime']
        assert r['fallback'] == r['enUpload']
        assert r['echo'] == 'totally.missing.key'


RUNSMGR_HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_runsmgr.mjs'


@pytest.fixture(scope='module')
def runsmgr(tmp_path_factory):
    runs = {
        'runs': [
            {
                'run_id': 'abc123',
                'workflow_name': '获取微博<script>',
                'status': 'interrupted',
                'resumable': True,
                'node_done': 2,
                'node_total': 3,
                'rows_kept': 17,
                'started_at': '2026-09-01 10:00',
            },
            {
                'run_id': 'def456',
                'workflow_name': '',
                'status': 'completed',
                'resumable': False,
                'node_done': 3,
                'node_total': 3,
                'rows_kept': 5,
                'started_at': '',
            },
        ],
    }
    tmp = tmp_path_factory.mktemp('js-runsmgr')
    sc = tmp / 'runs.json'
    sc.write_text(json.dumps(runs, ensure_ascii=False), encoding='utf-8')
    proc = subprocess.run(
        ['node', str(RUNSMGR_HARNESS), str(JS_DIR / 'workflow.js'), str(sc)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=60,
    )
    assert proc.returncode == 0, f'runsmgr harness failed: {proc.stderr}'
    return json.loads(proc.stdout)


class TestRunRecordsPanel:
    """The 运行记录 table is the resume funnel: wrong buttons here either
    discard paid-for data or pretend a dead run is alive."""

    def test_resumable_run_offers_continue_and_restart(self, runsmgr):
        html = runsmgr['html']
        assert "runsManager.continueRun('abc123')" in html
        assert "runsManager.restart('abc123')" in html

    def test_a_finished_run_offers_neither(self, runsmgr):
        # Split rows so the assertions can't borrow each other's buttons.
        rows = runsmgr['html'].split('<tr>')
        finished = next(r for r in rows if 'def456' in r)
        assert 'continueRun' not in finished
        assert 'restart' not in finished

    def test_progress_and_row_counts_read_honestly(self, runsmgr):
        rows = runsmgr['html'].split('<tr>')
        interrupted = next(r for r in rows if 'abc123' in r)
        assert '2/3' in interrupted, 'node progress must be done/total'
        assert '>17<' in interrupted, 'kept rows must show'

    def test_status_labels_map_every_known_state(self, runsmgr):
        assert 'interrupted' in runsmgr['html']
        assert 'completed' in runsmgr['html']

    def test_a_workflow_name_is_escaped_not_executed(self, runsmgr):
        # The name is user data straight from runs.db — markup must not live.
        assert '<script>' not in runsmgr['html']
        assert '&lt;script&gt;' in runsmgr['html']

    def test_an_unnamed_run_still_has_a_label_and_empty_count_hidden(self, runsmgr):
        assert runsmgr['count'] == '(2)'
        assert 'unnamed' in runsmgr['html'], 'a blank name must fall back to a label'
