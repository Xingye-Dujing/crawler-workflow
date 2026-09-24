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
from pathlib import Path

import pytest
from node_runner import run_node

from utils.helpers import platform_for

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_validate.mjs'


def _parse(msg: str) -> tuple:
    """'validate.key|Title|2|zhihu|{col}|{op}|{field}' → ('validate.key', {...})."""
    head, *fields = msg.split('|')
    names = ['title', 'n', 'plat', 'col', 'op', 'field']
    out = {}
    for name, value in zip(names, fields, strict=False):
        if not value.startswith('{'):  # unfilled placeholders stay literal
            out[name] = value
    return head, out


def _run_validate(tmp_path: Path, scenarios: list, matrix: Path | None = None) -> dict:
    sc_path = tmp_path / 'scenarios.json'
    sc_path.write_text(json.dumps(scenarios, ensure_ascii=False), encoding='utf-8')
    args = [str(HARNESS), str(JS_DIR / 'workflow.js'), str(sc_path)]
    if matrix is not None:
        args.append(str(matrix))
    proc = run_node(*args)
    assert proc.returncode == 0, f'harness failed: {proc.stderr}'
    return json.loads(proc.stdout)


def _node(nid, ntype, params, title='t'):
    return {'id': nid, 'type': ntype, 'title': title, 'params': params}


def _save(nid='out-1', filename='f'):
    return {'id': nid, 'type': 'output', 'title': '保存', 'params': {'operation': 'save', 'filename': filename}}


@pytest.fixture(scope='module')
def results(tmp_path_factory, capabilities_matrix):
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
        # ── the matrix decides what a source needs, not workflow.js ──
        # These four modes exist in crawl_capabilities, are rendered by the panel and
        # run on the backend — and every one of them was unreachable from the UI,
        # because validate() knew only "comments→links, wechat→links, else keyword".
        {
            'id': 'author_bilibili',
            'nodes': [
                _node(
                    'n1',
                    'source',
                    {'platform': 'bilibili', 'collect': 'author', 'author': 'space.bilibili.com/546195'},
                ),
                _save(),
            ],
            'connections': [{'from': 'n1', 'to': 'out-1'}],
        },
        {
            'id': 'hot_bilibili',
            'nodes': [_node('n1', 'source', {'platform': 'bilibili', 'collect': 'hot', 'board': 'popular'}), _save()],
            'connections': [{'from': 'n1', 'to': 'out-1'}],
        },
        {
            'id': 'author_douyin_missing',
            'nodes': [_node('n1', 'source', {'platform': 'douyin', 'collect': 'author', 'author': ''}), _save()],
            'connections': [{'from': 'n1', 'to': 'out-1'}],
        },
        {
            'id': 'mode_the_platform_lacks',
            'nodes': [_node('n1', 'source', {'platform': 'weibo', 'collect': 'author', 'author': 'x'}), _save()],
            'connections': [{'from': 'n1', 'to': 'out-1'}],
        },
        {
            'id': 'keyword_still_required',
            'nodes': [_node('n1', 'source', {'platform': 'zhihu', 'keyword': '  '}), _save()],
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
                ('panel_xhs_posts', 'source', {'platform': 'xiaohongshu', 'collect': 'posts', 'keyword': 'k'}),
                ('panel_weibo_posts', 'source', {'platform': 'weibo', 'collect': 'posts', 'keyword': 'k'}),
                ('panel_legacy_comment', 'comment', {'urls': ''}),
                # Analysis ops: the panel is the only place these params are set,
                # so a field missing here is a parameter the user cannot reach.
                ('panel_drop_null', 'analysis', {'operation': 'drop_null', 'columns': 'a, b'}),
                ('panel_fill_null', 'analysis', {'operation': 'fill_null', 'columns': 'a', 'value': '0'}),
                (
                    'panel_bin_column',
                    'analysis',
                    {'operation': 'bin_column', 'column': 'score', 'bins': '0, 60, 100'},
                ),
                # Process ops: same rule — a parameter the backend reads must
                # have a field here, or it is unreachable.
                ('panel_ner_default', 'process', {'operation': 'ner'}),
                (
                    'panel_ner_llm',
                    'process',
                    {'operation': 'ner', 'mode': 'llm', 'entity_types': 'PERSON,DATE'},
                ),
                ('panel_emotion_ml', 'process', {'operation': 'emotion', 'mode': 'ml'}),
                ('panel_keyword', 'process', {'operation': 'keyword', 'topk': '5'}),
            )
        ),
    ]
    return _run_validate(tmp, scenarios, capabilities_matrix)


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

    def test_comments_mode_without_urls_names_the_field_the_matrix_declares(self, results):
        key, fields = _parse(results['validate']['comments_empty'][0])
        assert key == 'validate.sourceFieldMissing'
        # The field is named from the payload, so a field renamed in the matrix
        # cannot be contradicted by a wording hardcoded in tests.
        assert fields['field'].startswith('field.') or fields['field'].startswith('settings.'), fields

    def test_an_author_mode_node_validates_without_a_keyword(self, results):
        """「某作者的作品」 asks for a creator, never a keyword — and used to be refused for lacking one.

        The message the user got named a field the panel had not even shown them, and
        no request left the page, so a mode shipped in the matrix, rendered in the
        panel and executable by the backend was unreachable from the UI.
        """
        assert results['validate']['author_bilibili'] == [], results['validate']['author_bilibili']

    def test_a_hot_board_needs_nothing_at_all(self, results):
        # 热榜 is one pick: the matrix declares no required field for it, so a node
        # that selected the board must not be asked for a keyword or an author.
        assert results['validate']['hot_bilibili'] == [], results['validate']['hot_bilibili']

    def test_an_untouched_author_field_is_reported_as_that_field(self, results):
        key, fields = _parse(results['validate']['author_douyin_missing'][0])
        assert key == 'validate.sourceFieldMissing'
        assert 'author' in fields['field'], fields

    def test_a_mode_the_platform_does_not_offer_is_refused_by_name(self, results):
        """微博 has no author mode; saying 「缺少关键词」 there would be a lie twice over."""
        keys = [_parse(message)[0] for message in results['validate']['mode_the_platform_lacks']]
        assert keys == ['validate.sourceUnknownMode'], results['validate']['mode_the_platform_lacks']

    def test_a_blank_keyword_is_still_a_missing_field(self, results):
        """The gate did not get looser: the keyword mode still refuses an empty one."""
        keys = [_parse(message)[0] for message in results['validate']['keyword_still_required']]
        assert keys == ['validate.sourceFieldMissing'], results['validate']['keyword_still_required']

    def test_without_the_matrix_the_refusal_says_so_instead_of_guessing(self, tmp_path):
        """No payload → no invented answer.

        The old branch kept its own list of what each platform needs, so it could
        always "answer" — wrongly. Now the only honest response is that the required
        fields could not be checked, and the panel's own retry note says what to do.
        """
        scenarios = [
            {
                'id': 'no_matrix',
                'nodes': [_node('n1', 'source', {'platform': 'bilibili', 'collect': 'hot'}), _save()],
                'connections': [{'from': 'n1', 'to': 'out-1'}],
            }
        ]
        out = _run_validate(tmp_path, scenarios, None)
        keys = [_parse(message)[0] for message in out['validate']['no_matrix']]
        assert keys == ['validate.capUnavailable'], out['validate']['no_matrix']

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
        assert 'validate.sourceFieldMissing' in keywords
        got = next(f for k, f in parsed if k == 'validate.sourceFieldMissing')
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

    def test_drop_null_panel_offers_the_delete_condition(self, results):
        """``how`` decides whether one empty cell drops a row or all of them do.
        With no field for it the user's choice did not exist and every run used
        the default — so the select itself is the thing under test."""
        html = results['settings']['panel_drop_null']
        assert "updateParam('n1','how'" in html
        assert 'settings.dropHow' in html and 'settings.dropHowAny' in html and 'settings.dropHowAll' in html

    def test_fill_null_panel_offers_method_as_well_as_value(self, results):
        html = results['settings']['panel_fill_null']
        assert "updateParam('n1','value'" in html
        assert "updateParam('n1','method'" in html
        assert 'settings.fillMethod' in html and 'settings.fillMethodValue' in html

    def test_bin_column_panel_offers_edges_and_labels(self, results):
        html = results['settings']['panel_bin_column']
        assert "updateParam('n1','bins'" in html, 'a bin count/edge list cannot be set without this field'
        assert "updateParam('n1','bin_labels'" in html
        assert 'settings.binEdges' in html and 'settings.binLabels' in html

    def test_xiaohongshu_offers_a_comment_preview_count(self, results):
        """Only XHS carries per-note comments in its search rows, so only its
        panel may offer the knob — and clearing it must not mean 0: 0 is a real
        choice ("skip the panel"), while an empty box means the panel's own
        default, which is what the backend would have used anyway.
        """
        html = results['settings']['panel_xhs_posts']
        handler = "updateParam('n1','comment_preview',isNaN(parseInt(this.value,10)) ? 5 : parseInt(this.value,10))"
        assert handler in html
        assert 'settings.commentPreview' in html and 'settings.commentPreviewHint' in html
        assert 'type="number" min="0"' in html

    def test_other_platforms_do_not_offer_it(self, results):
        for panel in ('panel_zhihu_posts', 'panel_weibo_posts'):
            assert 'comment_preview' not in results['settings'][panel], f'{panel} has no comment preview to set'

    def test_ner_panel_offers_a_model_switch_and_the_category_filter(self, results):
        """Both fields are the only route to what the backend reads, and the
        default must stay on the rules: a workflow saved before the selector
        exists has no ``mode`` and must not start paying for a model."""
        default = results['settings']['panel_ner_default']
        assert "updateParam('n1','mode'" in default
        assert "updateParam('n1','entity_types'" in default
        assert 'settings.entityTypes' in default and 'settings.entityTypesHint' in default
        assert 'mode.regex' in default
        # An absent mode renders the rules option selected, not the model.
        assert '<option value="regex" selected>' in default
        assert '<option value="llm" selected>' not in default

    def test_ner_panel_shows_the_stored_choices(self, results):
        html = results['settings']['panel_ner_llm']
        assert '<option value="llm" selected>' in html
        assert 'value="PERSON,DATE"' in html

    def test_a_process_node_with_no_param_field_for_an_op_stays_honest(self, results):
        # keyword/cluster/emotion already had their fields; NER is the check that
        # an op with no parameters at all renders no leftovers.
        assert 'entity_types' not in results['settings']['panel_keyword']
        assert 'entity_types' not in results['settings']['panel_emotion_ml']


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
    proc = run_node(str(APP_HARNESS), str(JS_DIR), str(sc_path))
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
                'mode': 'serial',
                'wf_count': 1,
                'headless': 0,
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
                'mode': 'serial',
                'wf_count': 1,
                'headless': 1,
            },
            {
                'run_id': 'par789',
                'workflow_name': '热门榜 + 周排行榜',
                'status': 'completed',
                'resumable': False,
                'node_done': 6,
                'node_total': 6,
                'rows_kept': 40,
                'started_at': '2026-09-22 09:00',
                'mode': 'parallel',
                'wf_count': 2,
                'headless': 1,
            },
            {
                'run_id': 'ser790',
                'workflow_name': '热门榜 + 周排行榜',
                'status': 'completed',
                'resumable': False,
                'node_done': 6,
                'node_total': 6,
                'rows_kept': 40,
                'started_at': '2026-09-22 09:30',
                'mode': 'serial',
                'wf_count': 2,
                'headless': 1,
            },
        ],
        'queue': [
            {'id': 'q1', 'workflow_name': '夜间增量', 'nodes': 4, 'queued_at': '2026-09-22T18:00:00'},
            {'id': 'q2', 'workflow_name': '', 'nodes': 2, 'queued_at': '2026-09-22T18:01:00'},
        ],
    }
    tmp = tmp_path_factory.mktemp('js-runsmgr')
    sc = tmp / 'runs.json'
    sc.write_text(json.dumps(runs, ensure_ascii=False), encoding='utf-8')
    proc = run_node(str(RUNSMGR_HARNESS), str(JS_DIR / 'workflow.js'), str(sc))
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
        assert runsmgr['count'] == '(4)'
        assert 'unnamed' in runsmgr['html'], 'a blank name must fall back to a label'

    def test_a_parallel_record_shows_every_workflow_it_ran(self, runsmgr):
        """One record for several workflows is correct; showing one name out of
        two is what made the user look for the 'missing' second record."""
        rows = runsmgr['html'].split('<tr>')
        parallel = next(r for r in rows if 'par789' in r)
        assert '热门榜 + 周排行榜' in parallel
        assert 'PARALLEL(2)' in parallel, 'the chips are the only place ×N can be read'
        assert 'HEADLESS' in parallel
        single = next(r for r in rows if 'def456' in r)
        assert 'PARALLEL' not in single, 'a one-workflow run must not claim otherwise'
        assert 'HEADLESS' in single, 'the window mode is stored for every run, not just parallel ones'

    def test_the_chips_come_from_the_mode_not_from_the_count(self, runsmgr):
        """The count says how many workflows the canvas held; only the mode says
        whether they actually overlapped. Reading the count alone labelled a 串行 run
        ``并行 ×2`` — a concurrency that never happened, on the one screen a user reads
        a past run's shape from."""
        cases = runsmgr['tagCases']
        assert cases['parallelHeadless'] == ['PARALLEL(2)', 'HEADLESS']
        assert cases['parallelVisible'] == ['PARALLEL(3)', 'WINDOW']
        assert cases['serialHeadless'] == ['SERIAL(2)', 'HEADLESS']
        assert cases['singleParallel'] == ['HEADLESS'], 'one workflow is neither parallel nor serial'
        assert cases['singleSerial'] == ['WINDOW']

    def test_a_serial_record_with_two_workflows_says_serial(self, runsmgr):
        rows = runsmgr['html'].split('<tr>')
        parallel = next(r for r in rows if 'par789' in r)
        serial = next(r for r in rows if 'ser790' in r)
        assert '热门榜 + 周排行榜' in parallel and 'PARALLEL(2)' in parallel
        assert '热门榜 + 周排行榜' in serial, 'both spellings of the name are still one record'
        assert 'SERIAL(2)' in serial
        assert 'PARALLEL' not in serial, f'the panel claims a concurrency this run did not have: {serial}'

    def test_every_recorded_run_can_be_turned_into_a_report(self, runsmgr):
        """A stored run is reportable whether or not it finished: the tables the
        node settled are there either way, and a partial run is exactly when a
        written account of what was collected has value."""
        assert runsmgr['reports'] == 4
        assert "runsManager.report('abc123')" in runsmgr['html']
        assert "runsManager.report('def456')" in runsmgr['html']

    def test_a_workflow_name_never_travels_inside_an_onclick(self, runsmgr):
        # The name is user text; the button carries only the run id and looks the
        # name up from the rows the panel is holding.
        assert runsmgr['nameInHandler'] is False

    def test_the_waiting_list_is_drawn_above_the_finished_records(self, runsmgr):
        """Queue and history share one panel on purpose: 'what has not started'
        and 'what has run' are the same question asked at different times."""
        html = runsmgr['html']
        assert 'WAITING(2)' in html
        assert runsmgr['queueRows'] == 2
        assert '夜间增量' in html
        # An unnamed queued workflow still gets a row, with the fallback label —
        # a blank cell reads as a rendering bug.
        assert html.index('WAITING(2)') < html.index('abc123'), 'the queue must come first'

    def test_cancelling_a_queued_run_posts_its_queue_id(self, runsmgr):
        post = runsmgr['posts'][0]
        assert post['url'] == '/api/workflow/queue/cancel'
        assert post['body'] == {'id': 'q1'}
        assert runsmgr['toasts'] == ['REMOVED']

    def test_a_continue_is_never_parked_behind_another_run(self, runsmgr):
        """The banner names a record that retention can age out while it waits,
        and a continue that starts late is a cold re-crawl with a friendly name."""
        body = runsmgr['resumeBody']
        assert body['resume_run_id'] == 'r-int'
        assert body['queue'] is False, 'a 继续 must fail fast, not join the queue'

    def test_an_ordinary_run_still_queues_when_the_server_is_busy(self, runsmgr):
        body = runsmgr['plainBody']
        assert body['resume_run_id'] == ''
        assert body['queue'] is True, 'the queue is for ordinary presses only'

    def test_every_request_that_needs_rows_names_its_workflow(self, runsmgr):
        """A recorded run is looked up by workflow name after a restart, and
        ``node-2`` exists on every canvas — an unnamed request would have to be
        answered by guessing."""
        assert runsmgr['resumeBody']['workflow_name'] == '夜间增量'
        assert runsmgr['plainBody']['workflow_name'] == '夜间增量'
        preview = runsmgr['previewBody']
        assert preview['node_id'] == 'node-1', 'the preview reads the node it sits downstream of'
        assert preview['workflow_name'] == '夜间增量'

    def test_the_name_node_label_decides_what_a_run_is_called(self, runsmgr):
        """Same precedence the backend applies when it records the run: label,
        then the saved file name. Anything else and the two sides file the same
        work under two different names.

        ``runName`` is also what the request body carries, so the composed
        spelling and the record shown in the panel cannot disagree.
        """
        assert runsmgr['runName'] == {
            'fromNode': '周报表',
            'fromTwo': '周报表 + 明细表',
            'fromFile': '夜间增量',
            'none': '',
        }
        assert runsmgr['twoNodeBody']['workflow_name'] == '周报表 + 明细表'
        assert runsmgr['twoNodeToasts'] == [], f'a refused run would show as a missing POST: {runsmgr["twoNodeToasts"]}'
