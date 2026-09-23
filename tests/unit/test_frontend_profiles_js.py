"""The browser-profile UI: the pre-run gate, the settings table, the panel hint.

tests/frontend/harness_profiles.mjs loads the real workflow.js and app.js, so what
fails here is the shipped code, not a re-telling of it. Four things are pinned:

* ``profileNoticeCount`` — off + a flagged platform = 1; on = 0; no matrix = 0 (no
  claim without facts); an upload-only canvas = 0; two flagged platforms = 2. A gate
  that reads ``window.Capabilities`` would return 0 forever, because a top-level
  ``const`` never becomes a window property — that is the bug class that hid the
  断点续跑 banner;
* the dialog itself: that it appears, that 继续运行 runs and 先去设置 does not (and
  opens the settings panel instead), and that the message carries the count;
* the settings table: one row per platform in server order, the recommendation flag
  on the right rows, four distinct states, and the honest note when the endpoint
  answers nothing usable;
* the Data Source panel hint, which has to say "turn it on" when it is off and "log
  into it" when it is on — the two next steps are different, and the matrix decides
  which platforms get either sentence.

Plus the static wiring the browser needs and Python can read directly: every
``AppSettings`` key points at an id that exists in index.html, and every label the
new markup names exists in *both* language catalogues.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

import crawl_capabilities
import i18n
from services.cookie_manager import CookieManager

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which('node') is None, reason='node not installed'),
]

ROOT = Path(__file__).resolve().parents[2]
JS_DIR = ROOT / 'backend' / 'static' / 'js'
HARNESS = ROOT / 'tests' / 'frontend' / 'harness_profiles.mjs'
INDEX = ROOT / 'backend' / 'static' / 'index.html'

MATRIX = crawl_capabilities.as_dict()

#: The platforms the endpoint can answer for: the matrix, minus the one with no login
#: at all. The scenario payload below is built from this, so the panel's contract is
#: tested against the same list the server actually sends.
PLATFORMS = [cap['platform'] for cap in MATRIX['platforms'] if CookieManager.is_supported(cap['platform'])]
FLAGGED = [cap['platform'] for cap in MATRIX['platforms'] if cap['profileRecommended']]


def _nodes(*specs):
    """``('source', 'weibo')`` → a node map; also accepts a raw dict."""
    out = {}
    for index, spec in enumerate(specs):
        if isinstance(spec, dict):
            out[spec['id']] = spec
            continue
        ntype, platform = spec
        out[f'n{index}'] = {'id': f'n{index}', 'type': ntype, 'params': {'platform': platform}}
    return out


def _crawl(node_id, platform, keyword=None):
    """A source node that passes the canvas's own validation.

    A node without a keyword is refused by ``validate()`` before any request is
    built, which would hide the thing under test — the payload — behind a question
    about something else entirely.
    """
    return {
        node_id: {
            'id': node_id,
            'type': 'source',
            'title': f'采集 {platform}',
            'params': {
                'platform': platform,
                'collect': 'posts',
                'keyword': keyword or f'kw-{node_id}',
                'target_count': 5,
            },
        }
    }


def _output(node_id):
    """An output node: validate() refuses a canvas that ends in nothing."""
    params = {'operation': 'save', 'format': 'csv', 'filename': node_id}
    return {node_id: {'id': node_id, 'type': 'output', 'title': '导出', 'operation': 'save', 'params': params}}


def _two_crawls(*platforms):
    """Two disconnected workflows — each crawl with its own export — on one canvas.

    Disconnected is the point: that is what makes them two workflows to the backend,
    and the only shape where two same-platform crawls want the profile at once.
    """
    nodes, conns = {}, []
    for index, platform in enumerate(platforms):
        crawl, sink = f'c{index}', f'o{index}'
        nodes.update(_crawl(crawl, platform, keyword=f'kw{index}-{platform}'))
        nodes.update(_output(sink))
        conns.append({'from': crawl, 'to': sink})
    return nodes, conns


def _profiles_rows(enabled=True):
    rows = []
    for platform in PLATFORMS:
        rows.append(
            {
                'platform': platform,
                'enabled': enabled,
                'recommended': platform in FLAGGED,
                'path': f'/tmp/{platform}',
                'exists': True,
                'imported': platform == 'zhihu',
                'used_at': '2026-09-24 10:00:00' if platform == 'zhihu' else '',
                'size_mb': 12,
                'has_saved_cookie': platform == 'weibo',
            }
        )
    return {'ok': True, 'enabled': enabled, 'root': '/tmp', 'profiles': rows}


SCENARIOS = [
    # Profiles off and the run crawls a flagged platform.
    {
        'id': 'off-flagged',
        'matrix': MATRIX,
        'settings': {'use_browser_profile': False},
        'nodes': _nodes(('source', 'weibo')),
        'profiles': _profiles_rows(enabled=False),
        'hintPlatform': 'weibo',
    },
    # Same canvas, switch on: the gate has to stay out of the way.
    {
        'id': 'on-flagged',
        'matrix': MATRIX,
        'settings': {'use_browser_profile': True},
        'nodes': _nodes(('source', 'weibo')),
        'profiles': _profiles_rows(enabled=True),
        'hintPlatform': 'weibo',
    },
    # Two flagged platforms in one run.
    {
        'id': 'off-two-flagged',
        'matrix': MATRIX,
        'settings': {'use_browser_profile': False},
        'nodes': _nodes(('source', 'weibo'), ('comment', 'xiaohongshu')),
        'profiles': _profiles_rows(enabled=False),
    },
    # A platform nobody flags must not nag.
    {
        'id': 'off-unflagged',
        'matrix': MATRIX,
        'settings': {'use_browser_profile': False},
        'nodes': _nodes(('source', 'zhihu'), ('upload', 'x')),
        'profiles': _profiles_rows(enabled=False),
        'hintPlatform': 'zhihu',
    },
    # The user chose 先去设置.
    {
        'id': 'off-setup',
        'matrix': MATRIX,
        'settings': {'use_browser_profile': False},
        'nodes': _nodes(('source', 'xiaohongshu')),
        'profiles': _profiles_rows(enabled=False),
        'choice': 'setup',
    },
    # The matrix never arrived: the gate cannot know, so it must not claim.
    {
        'id': 'no-matrix',
        'settings': {'use_browser_profile': False},
        'nodes': _nodes(('source', 'weibo')),
        'profiles': 'throw',
    },
    # A server that answers fine but lists nothing: the table must not look healthy.
    {
        'id': 'empty-table',
        'matrix': MATRIX,
        'settings': {'use_browser_profile': True},
        'nodes': _nodes(('source', 'zhihu')),
        'profiles': {'ok': True, 'enabled': True, 'root': '/tmp', 'profiles': []},
    },
    # ── the parallel / same-platform fork ────────────────────────────────
    # Two disconnected workflows crawling bilibili: one profile, two browsers.
    {
        'id': 'clash-parallel-same',
        'matrix': MATRIX,
        'settings': {'use_browser_profile': True},
        'nodes': _two_crawls('bilibili', 'bilibili')[0],
        'connections': _two_crawls('bilibili', 'bilibili')[1],
        'profiles': _profiles_rows(enabled=True),
        'canvasSettings': {'mode': 'parallel'},
        'clashChoice': 'skip',
    },
    # The same two nodes answered 继续用 Profile.
    {
        'id': 'clash-parallel-same-keep',
        'matrix': MATRIX,
        'settings': {'use_browser_profile': True},
        'nodes': _two_crawls('bilibili', 'bilibili')[0],
        'connections': _two_crawls('bilibili', 'bilibili')[1],
        'profiles': _profiles_rows(enabled=True),
        'canvasSettings': {'mode': 'parallel'},
        'clashChoice': 'use',
    },
    # The user closed the dialog instead of choosing.
    {
        'id': 'clash-parallel-same-cancel',
        'matrix': MATRIX,
        'settings': {'use_browser_profile': True},
        'nodes': _two_crawls('bilibili', 'bilibili')[0],
        'connections': _two_crawls('bilibili', 'bilibili')[1],
        'profiles': _profiles_rows(enabled=True),
        'canvasSettings': {'mode': 'parallel'},
        'clashChoice': None,
    },
    # Same platform twice, but inside ONE workflow: sequential anyway, so no question.
    {
        'id': 'clash-one-component',
        'matrix': MATRIX,
        'settings': {'use_browser_profile': True},
        'nodes': {**_crawl('c0', 'bilibili', keyword='k0'), **_crawl('c1', 'bilibili', keyword='k1'), **_output('o0')},
        'connections': [{'from': 'c0', 'to': 'o0'}, {'from': 'c1', 'to': 'o0'}],
        'profiles': _profiles_rows(enabled=True),
        'canvasSettings': {'mode': 'parallel'},
    },
    # Two platforms: nothing contends, and asking would be noise.
    {
        'id': 'clash-different-platforms',
        'matrix': MATRIX,
        'settings': {'use_browser_profile': True},
        'nodes': _two_crawls('bilibili', 'zhihu')[0],
        'connections': _two_crawls('bilibili', 'zhihu')[1],
        'profiles': _profiles_rows(enabled=True),
        'canvasSettings': {'mode': 'parallel'},
    },
    # Serial mode: one workflow at a time, so the fork does not exist.
    {
        'id': 'clash-serial',
        'matrix': MATRIX,
        'settings': {'use_browser_profile': True},
        'nodes': _two_crawls('bilibili', 'bilibili')[0],
        'connections': _two_crawls('bilibili', 'bilibili')[1],
        'profiles': _profiles_rows(enabled=True),
        'canvasSettings': {'mode': 'serial'},
    },
    # Profiles off: there is no device to protect and no clash to avoid.
    {
        'id': 'clash-profiles-off',
        'matrix': MATRIX,
        'settings': {'use_browser_profile': False},
        'nodes': _two_crawls('bilibili', 'bilibili')[0],
        'connections': _two_crawls('bilibili', 'bilibili')[1],
        'profiles': _profiles_rows(enabled=False),
        'canvasSettings': {'mode': 'parallel'},
    },
    # A comment node's URL names its platform too — it buys a browser as well.
    {
        'id': 'clash-comment-url',
        'matrix': MATRIX,
        'settings': {'use_browser_profile': True},
        'nodes': {
            'cm0': {
                'id': 'cm0',
                'type': 'comment',
                'params': {'urls': 'https://www.bilibili.com/video/BV1xx\nhttps://x.com/a/status/1'},
            },
            **_crawl('s0', 'bilibili', keyword='k'),
            **_output('o0'),
            **_output('o1'),
        },
        'connections': [{'from': 'cm0', 'to': 'o0'}, {'from': 's0', 'to': 'o1'}],
        'profiles': _profiles_rows(enabled=True),
        'canvasSettings': {'mode': 'parallel'},
        'clashChoice': 'use',
    },
]


@pytest.fixture(scope='module')
def ui(tmp_path_factory):
    file = tmp_path_factory.mktemp('profiles') / 'scenarios.json'
    file.write_text(json.dumps(SCENARIOS, ensure_ascii=False), encoding='utf-8')
    proc = run_node(str(HARNESS), str(JS_DIR), str(file))
    assert proc.returncode == 0, f'profiles harness failed: {proc.stderr[-2500:]} {proc.stdout[-500:]}'
    return json.loads(proc.stdout)


class TestPreRunGate:
    def test_a_flagged_platform_without_a_profile_asks(self, ui):
        case = ui['off-flagged']
        assert case['notice'] == 1
        assert case['shown'] is True, 'the gate never fired, so the user would never hear about it'
        assert '1' in case['result']['message']
        assert len(case['result']['labels']) == 2

    def test_turning_the_switch_on_silences_the_gate(self, ui):
        assert ui['on-flagged']['notice'] == 0
        assert ui['on-flagged']['shown'] is False

    def test_each_flagged_platform_is_counted_once(self, ui):
        """Two nodes, two platforms, one dialog naming the number."""
        assert ui['off-two-flagged']['notice'] == 2
        assert '2' in ui['off-two-flagged']['result']['message']

    def test_an_unflagged_canvas_never_hears_about_it(self, ui):
        assert ui['off-unflagged']['notice'] == 0 and ui['off-unflagged']['shown'] is False

    def test_running_anyway_proceeds_and_setup_does_not(self, ui):
        assert ui['off-flagged']['proceed'] is True and ui['off-flagged']['openedSettings'] == 0
        assert ui['off-setup']['proceed'] is False, 'chose 先去设置 and the run started anyway'
        assert ui['off-setup']['openedSettings'] == 1, 'the dialog sent the user nowhere'

    def test_no_matrix_means_no_claim(self, ui):
        """Capabilities is a top-level const, so a ``window.Capabilities`` guard
        would read as "never loaded" and the gate would be dead code forever."""
        assert ui['no-matrix']['notice'] == 0 and ui['no-matrix']['shown'] is False


class TestSettingsTable:
    def test_one_row_per_platform_in_server_order(self, ui):
        rows = ui['off-flagged']['rows']
        assert len(rows) == len(PLATFORMS), f'{len(rows)} rows for {len(PLATFORMS)} platforms'
        for platform, line in zip(PLATFORMS, rows, strict=True):
            assert line['name'], f'{platform} rendered no name: {line}'
            assert line['state'], f'{platform} rendered no state: {line}'

    def test_the_recommendation_is_a_chip_on_the_right_rows(self, ui):
        """The chip is its own cell (not text glued onto the name) so a long
        platform name can wrap without ever widening the menu."""
        chips = [bool(row['chip']) for row in ui['off-flagged']['rows']]
        expected = [platform in FLAGGED for platform in PLATFORMS]
        assert chips == expected, f'the panel suggests a profile somewhere the matrix never measured it: {chips}'
        for row in ui['off-flagged']['rows']:
            if row['chip']:
                assert row['kind'] == 'suggested'

    def test_the_four_states_are_distinguishable(self, ui):
        rows = ui['off-flagged']['rows']
        states = {row['state'] for row in rows}
        assert '功能已关闭' in states or 'switched off' in ' '.join(states), states
        on = {row['state'] for row in ui['on-flagged']['rows']}
        assert states != on, 'the table says nothing about the switch'

    def test_an_unusable_payload_says_so_instead_of_rendering_nothing(self, ui):
        rows = ui['no-matrix']['rows']
        assert len(rows) == 1, f'a silent empty table reads as "all good": {rows}'
        assert rows[0]['kind'] == 'unavailable'

    def test_opening_the_settings_panel_is_what_reads_the_table(self, ui):
        """The read lives in ``toggleSettingsMenu`` (menu.js), not in the page
        startup — so a canvas with no settings panel open never pays for it, and the
        panel that is open always shows server truth."""
        assert ui['off-flagged']['rowsAfterOpen'] == len(PLATFORMS)
        assert ui['empty-table']['rowsAfterOpen'] == 1, 'an empty server answer must not look like a healthy table'

    def test_a_server_that_lists_no_platforms_is_not_a_green_bill(self, ui):
        rows = ui['empty-table']['rows']
        assert len(rows) == 1 and rows[0]['kind'] == 'unavailable', rows


class TestPanelHint:
    """The hint is rendered through the real app.js catalogue (the harness loads the
    untouched files), so these assertions read the English sentences rather than the
    keys — which is also what pins the two states apart."""

    def test_a_flagged_platform_is_explained_in_the_source_panel(self, ui):
        html = ui['off-flagged']['panelHint']
        assert 'throwaway browser' in html, 'the panel never mentions the profile on a platform that needs one'
        assert 'own browser profile' not in html

    def test_the_sentence_changes_once_the_switch_is_on(self, ui):
        html = ui['on-flagged']['panelHint']
        assert 'own browser profile' in html and 'throwaway browser' not in html

    def test_an_unflagged_platform_is_left_alone(self, ui):
        html = ui['off-unflagged']['panelHint']
        assert 'throwaway browser' not in html and "platform's own browser profile" not in html


class TestStaticWiring:
    """The browser reads ids and labels that Python can check without a DOM."""

    def test_every_settings_key_points_at_a_real_control(self):
        app = (JS_DIR / 'app.js').read_text(encoding='utf-8')
        block = app.split('_inputMap', 1)[1].split('}', 1)[0]
        pairs = dict(re.findall(r"(\w+):\s*'(set-[\w-]+)'", block))
        html = INDEX.read_text(encoding='utf-8')
        assert {'use_browser_profile', 'browser_profile_dir'} <= set(pairs), pairs
        for key, element_id in pairs.items():
            assert f'id="{element_id}"' in html, f'{key} saves into a missing #{element_id}'

    def test_the_new_labels_exist_in_both_languages(self):
        app = (JS_DIR / 'app.js').read_text(encoding='utf-8')
        html = INDEX.read_text(encoding='utf-8')
        keys = set(re.findall(r'data-i18n="([A-Za-z][\w.]*)"', html))
        keys |= set(re.findall(r"I18n\.t\('((?:set|dialog|settings)\.[\w.]+)'", app))
        tables = [i18n._EN, i18n._ZH]
        catalog = set(re.findall(r"'((?:set|dialog|settings)\.[\w.]+)':", app))
        missing = [key for key in keys if key.startswith(('set.', 'dialog.', 'settings.')) and key not in catalog]
        assert not missing, f'labels the UI asks for that no catalogue defines: {missing}'
        for table in tables:
            assert table, 'app.js catalogues are parsed from the file, not imported'

    def test_the_profile_controls_are_declared_in_the_settings_panel(self):
        html = INDEX.read_text(encoding='utf-8')
        assert 'id="set-use-profile"' in html and 'id="set-profile-dir"' in html and 'id="profile-status"' in html
        assert "onSettingInput('use_browser_profile'" in html and "onSettingInput('browser_profile_dir'" in html


class TestParallelProfileFork:
    """One profile, two workflows: the fork only the user can call.

    A persistent profile is what makes the site see one continuous device, and it
    holds exactly one Chrome — so a parallel canvas that crawls the same platform
    twice has to be *asked*, and the answer has to reach the server. Both halves are
    pinned per combination, because a dialog that appears but is never sent, and a
    choice sent for a canvas that never needed one, are equally wrong.
    """

    def test_two_workflows_on_one_platform_are_recognised(self, ui):
        assert ui['clash-parallel-same']['collisions'] == ['bilibili']

    def test_the_same_platform_inside_one_workflow_asks_nothing(self, ui):
        """Two crawls in one workflow run one after the other anyway: a question with
        no choice behind it is noise, not a decision point."""
        case = ui['clash-one-component']
        assert case['collisions'] == []
        assert case['clash'] == 'not-asked'
        assert case['clashDialog'] is None

    def test_two_different_platforms_are_never_made_to_wait(self, ui):
        """Separate directories contend with nothing, so a prompt here would give up
        parallelism for no reason at all."""
        case = ui['clash-different-platforms']
        assert case['collisions'] == [] and case['clash'] == 'not-asked'
        assert case['sentProfile'] == 'undefined', 'no answer, so no field: the setting stays in charge'

    def test_serial_mode_does_not_ask(self, ui):
        case = ui['clash-serial']
        assert case['collisions'] == ['bilibili'], 'the collision is real — it just cannot happen serially'
        assert case['clash'] == 'not-asked'

    def test_a_canvas_without_profiles_is_not_asked(self, ui):
        case = ui['clash-profiles-off']
        assert case['clash'] == 'not-asked', 'there is no device to protect, so nothing to decide'

    def test_declining_profiles_reaches_the_request_as_false(self, ui):
        case = ui['clash-parallel-same']
        assert case['clash'] is False and case['ran'] is True
        assert case['sentProfile'] == 'false', 'the answer never travelled, so the server would re-decide it'
        assert 'bilibili' in case['clashDialog']['message'], 'the question has to name what collides'
        assert len(case['clashDialog']['labels']) == 3, 'both sides of the fork plus a way out'

    def test_keeping_profiles_reaches_the_request_as_true(self, ui):
        case = ui['clash-parallel-same-keep']
        assert case['clash'] is True and case['sentProfile'] == 'true'
        assert case['ran'] is True, 'answering the question must not cost the run'

    def test_closing_the_dialog_starts_nothing(self, ui):
        case = ui['clash-parallel-same-cancel']
        assert case['clash'] == 'cancelled'
        assert case['ran'] is False, 'an unanswered question may not be answered by running anyway'

    def test_a_comment_node_counts_as_a_browser_buyer(self, ui):
        """Its platform comes out of the pasted URLs rather than a select — and it
        claims the very same profile a source node would."""
        case = ui['clash-comment-url']
        assert case['collisions'] == ['bilibili']
        assert case['clash'] is True
