"""平台 → 引擎 → 功能 in the generated Data Source panel.

The panel is built from ``/api/capabilities``, and this payload (not the live matrix) pins the three
things the engine dimension adds: the order of the controls, a function list that follows the
selected engine, and an offered-but-unrunnable pair that stays on screen with its own sentence.
The live payload's shape is pinned by ``test_crawl_capabilities``; this file is about what the page
DOES with it.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[3]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_capabilities.mjs'


def _field(key, control='text', default='', required=False):
    return {
        'key': key,
        'control': control,
        'labelKey': 'settings.' + key,
        'default': default,
        'hintKey': '',
        'options': [],
        'minimum': None,
        'maximum': None,
        'required': required,
        'coerce': 'number' if control == 'number' else 'text',
        'linksOf': '',
        'acceptsNames': False,
        'placeholder': '',
        'fedBy': '',
    }


def _cell(status='available', runnable=True, reason='', reason_key=''):
    return {
        'status': status,
        'runnable': runnable,
        'reason': reason,
        'reasonKey': reason_key,
        'columns': [],
        'identity': [],
    }


def _mode(key, engines, cells, fields, label_key):
    return {
        'key': key,
        'labelKey': label_key,
        'handler': 'posts',
        'rows': 'posts',
        'noteKey': '',
        'actionKey': '',
        'actionJs': '',
        'collects': 'fetch',
        'needsSession': True,
        'requires': '',
        'engines': engines,
        'cells': cells,
        'fields': fields,
    }


def _engine(key, available=True, modes=(), reason_key=''):
    return {
        'key': key,
        'labelKey': 'settings.backend' + ('Selenium' if key == 'selenium' else 'Catbus'),
        'available': available,
        'reasonKey': reason_key,
        'reason': '',
        'modes': list(modes),
    }


def _payload():
    p1 = {
        'platform': 'p1',
        'labelKey': 'platform.p1',
        'engines': [
            _engine('selenium', modes=['posts', 'hot', 'likes']),
            _engine('catbus', modes=['posts', 'author', 'hot']),
        ],
        'modes': [
            _mode(
                'posts',
                ['selenium', 'catbus'],
                {'selenium': _cell(), 'catbus': _cell()},
                [_field('keyword', required=True), _field('target_count', 'number', 50)],
                'settings.collectPosts',
            ),
            _mode(
                'author',
                ['catbus'],
                {'catbus': _cell()},
                [_field('author', required=True), _field('target_count', 'number', 50)],
                'settings.collectAuthor',
            ),
            _mode(
                'likes',
                ['selenium'],
                {'selenium': _cell()},
                [_field('target_count', 'number', 50)],
                'settings.collectPosts',
            ),
            _mode(
                'hot',
                ['selenium', 'catbus'],
                {
                    'selenium': _cell(),
                    'catbus': _cell('unavailable', False, reason='CatBus 没有热榜命令'),
                },
                [_field('target_count', 'number', 50)],
                'settings.collectHot',
            ),
        ],
        'profileRecommended': False,
        'region': 'cn',
        'serialOnly': False,
        'parallelRecommended': False,
    }
    p2 = {
        'platform': 'p2',
        'labelKey': 'platform.p2',
        'engines': [_engine('catbus', modes=['user.followers', 'user.following'])],
        'modes': [
            _mode(
                'user.followers',
                ['catbus'],
                {'catbus': _cell()},
                [_field('author', required=True), _field('target_count', 'number', 50)],
                'catbus.mode.userFollowers',
            ),
            _mode(
                'user.following',
                ['catbus'],
                {'catbus': _cell()},
                [_field('author', required=True), _field('target_count', 'number', 50)],
                'catbus.mode.userFollowing',
            ),
        ],
        'profileRecommended': False,
        'region': 'cn',
        'serialOnly': False,
        'parallelRecommended': False,
    }
    return {
        'platforms': [
            # A new source node is seeded on ``zhihu`` by canvas.js; every real payload has it, and a
            # fixture without it would fail before the panel under test is even opened.
            {
                'platform': 'zhihu',
                'labelKey': 'platform.zhihu',
                'engines': [_engine('selenium', modes=['posts'])],
                'modes': [
                    _mode(
                        'posts',
                        ['selenium'],
                        {'selenium': _cell()},
                        [_field('keyword', required=True), _field('target_count', 'number', 50)],
                        'settings.collectPosts',
                    )
                ],
                'profileRecommended': False,
                'region': 'cn',
                'serialOnly': False,
                'parallelRecommended': False,
            },
            p1,
            p2,
        ],
        'fileFields': [],
        'backends': {'catbus': {'available': True, 'reasonKey': '', 'panelKey': '', 'cells': {}}},
        'machine': {},
    }


@pytest.fixture(scope='module')
def panel(tmp_path_factory):
    matrix = _payload()
    scenarios = [
        {
            'id': 'order',
            'payload': matrix,
            'params': {'platform': 'p1', 'backend': 'selenium', 'collect': 'posts', 'keyword': 'k'},
        },
        {
            'id': 'catbus-functions',
            'payload': matrix,
            'params': {'platform': 'p1', 'backend': 'catbus', 'collect': 'posts', 'keyword': 'k'},
        },
        {
            'id': 'unusable-named',
            'payload': matrix,
            'params': {'platform': 'p1', 'backend': 'catbus', 'collect': 'hot'},
        },
        {
            'id': 'switch-moves-mode',
            'payload': matrix,
            'params': {'platform': 'p1', 'backend': 'selenium', 'collect': 'likes', 'keyword': 'k'},
            'switchBackend': 'catbus',
        },
        {
            'id': 'catbus-only-platform',
            'payload': matrix,
            'params': {'platform': 'p2', 'backend': 'catbus', 'collect': 'user.followers', 'author': 'me'},
        },
    ]
    file = tmp_path_factory.mktemp('engine-dimension') / 'scenarios.json'
    file.write_text(json.dumps(scenarios, ensure_ascii=False), encoding='utf-8')
    proc = run_node(str(HARNESS), str(JS_DIR / 'canvas.js'), str(JS_DIR / 'workflow.js'), str(file))
    assert proc.returncode == 0, f'harness failed: {proc.stderr[-2500:]} {proc.stdout[-800:]}'
    return json.loads(proc.stdout)


class TestTheControlOrder:
    def test_platform_then_engine_then_function(self, panel):
        html = panel['order']['html']
        assert html.count('settings.crawlEngine') >= 1
        assert html.index('settings.platform') < html.index('settings.crawlEngine') < html.index('settings.collect')

    def test_the_engine_select_lists_both_engines_with_this_platforms_state(self, panel):
        html = panel['order']['html']
        assert 'value="selenium"' in html and 'value="catbus"' in html
        assert '<option value="selenium" selected' in html, 'the stored engine is the visible one'


class TestTheFunctionListFollowsTheEngine:
    def test_a_catbus_only_function_is_offered_under_catbus(self, panel):
        html = panel['catbus-functions']['html']
        assert '<option value="author"' in html
        assert 'settings.collectAuthor' in html

    def test_a_browser_only_function_disappears_under_catbus(self, panel):
        html = panel['catbus-functions']['html']
        assert '<option value="likes"' not in html, 'Selenium-only functions do not leak into the CatBus list'

    def test_switching_engine_moves_the_stored_mode_to_one_it_offers(self, panel):
        made = panel['switch-moves-mode']
        assert made['afterBackend'] == 'catbus'
        assert made['afterMode'] == 'posts', 'the first runnable CatBus function, the same fallback the backend uses'
        assert made['afterErrors'] == [], made['afterErrors']


class TestAnOfferedCellThatCannotRun:
    def test_it_stays_listed_greyed_and_named(self, panel):
        html = panel['unusable-named']['html']
        marker = html.index('<option value="hot"')
        option = html[marker : html.index('</option>', marker)]
        assert 'disabled' in option, option
        assert 'CatBus 没有热榜命令' in option, 'the adapter owns the sentence, not the panel'

    def test_the_run_is_refused_before_it_is_paid_for(self, panel):
        errors = panel['unusable-named']['errors']
        assert any('validate.modeUnavailable' in error for error in errors), errors


class TestAPlatformOnlyCatBusCanCrawl:
    def test_it_has_one_engine_and_still_a_function_list(self, panel):
        made = panel['catbus-only-platform']
        html = made['html']
        assert 'value="selenium"' not in html, 'a CatBus-only platform never claims a browser engine'
        assert 'value="catbus"' in html
        assert 'catbus.mode.userFollowers' in html, 'with more than one function, the selector names them'

    def test_its_required_field_is_the_manifest_parameter(self, panel):
        made = panel['catbus-only-platform']
        assert made['errors'] == [], made['errors']
        assert 'settings.author' in made['html']
