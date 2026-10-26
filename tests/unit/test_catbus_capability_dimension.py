"""The engine dimension: 平台 × 引擎 × 功能, read out of the adapter's manifest.

The Selenium half of the matrix is static and was tested before this dimension existed. What is new
here is that CatBus's half is **materialised from the manifest** — a mode CatBus alone offers gets a
form, a handler and a cell verdict without a line added to ``CAPABILITIES`` — and that every answer
the panel renders (engine availability, a function's runnable pair, the accepted parameters) comes
from the same data. Nothing here describes a real site: the manifest below is a shape, and the
real one is exercised by the adapter's own tests and the real-CLI tier.
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import crawl_capabilities as capabilities
from crawlers import catbus as catbus_module
from services import catbus_bridge as bridge

pytestmark = pytest.mark.unit


def _mode(status='available', **over):
    base = {
        'status': status,
        'catbus': [],
        'params': [],
        'columns': [],
        'auth': 'required',
    }
    base.update(over)
    return base


MANIFEST = {
    'schema': 1,
    'backend': 'catbus',
    'label': 'CatBus',
    'endpoint': 'web',
    'platforms': {
        'bilibili': {
            'catbus_platform': 'bilibili',
            'label': 'B站',
            'modes': {
                'posts': _mode(
                    handler='posts',
                    command='item search',
                    args=[],
                    optional={},
                    paged=True,
                    output='Item',
                    params=['keyword', 'target_count', 'catbus_account'],
                    columns=['链接'],
                    identity=['链接'],
                ),
                'hot': _mode(
                    'unavailable',
                    command='feed list',
                    reason='CatBus 没有热榜命令',
                ),
                'user.followers': _mode(
                    command='user followers',
                    args=['user'],
                    optional={'user': 'me'},
                    paged=True,
                    output='User',
                    params=['author', 'target_count', 'catbus_account'],
                    columns=['平台', '用户ID'],
                    identity=['平台', '用户ID'],
                ),
            },
        },
        'kuaishou': {
            'catbus_platform': 'kuaishou',
            'label': '快手',
            'modes': {
                'user.followers': _mode(
                    command='user followers',
                    args=['user'],
                    optional={'user': 'me'},
                    paged=True,
                    output='User',
                    params=['author', 'target_count', 'catbus_account'],
                    columns=['平台', '用户ID'],
                    identity=['平台', '用户ID'],
                ),
            },
        },
    },
    'requirements': {},
    'deployment': {'server': True, 'desktop': False},
}


@pytest.fixture
def manifest(monkeypatch):
    """The bridge answers as if this manifest were the adapter's own answer."""
    cells = {}
    for platform, entry in MANIFEST['platforms'].items():
        for mode, cell in entry['modes'].items():
            cells[f'{platform}.{mode}'] = {
                'status': cell['status'],
                'runnable': cell['status'] in ('available', 'partial'),
                'auth': cell.get('auth', 'required'),
                'reason': cell.get('reason', ''),
            }

    def state(platform, mode):
        cell = (MANIFEST['platforms'].get(platform, {}).get('modes') or {}).get(mode) or {}
        return str(cell.get('status') or 'unavailable'), str(cell.get('reason') or '')

    monkeypatch.setattr(bridge, 'probe', lambda force=False: SimpleNamespace(available=True, manifest=MANIFEST))
    monkeypatch.setattr(bridge, 'manifest_platforms', lambda: MANIFEST['platforms'])
    monkeypatch.setattr(
        bridge,
        'status_payload',
        lambda: {'available': True, 'reasonKey': '', 'panelKey': '', 'cells': cells},
    )
    monkeypatch.setattr(bridge, 'mode_state', state)
    monkeypatch.setattr(bridge, 'supports', lambda platform, mode: state(platform, mode)[0] in ('available', 'partial'))
    monkeypatch.setattr(
        bridge,
        'declared_params',
        lambda platform, mode: tuple(
            (MANIFEST['platforms'].get(platform, {}).get('modes') or {}).get(mode, {}).get('params') or ()
        ),
    )
    monkeypatch.setattr(
        bridge,
        'identity_for',
        lambda platform, mode: tuple(
            (MANIFEST['platforms'].get(platform, {}).get('modes') or {}).get(mode, {}).get('identity') or ()
        ),
    )
    monkeypatch.setattr(bridge, 'columns_for', lambda platform, mode: ())
    return MANIFEST


class TestModesComeFromTheManifest:
    def test_a_catbus_only_mode_becomes_an_ordinary_mode_with_a_form(self, manifest):
        modes = {m.key: m for m in capabilities.modes_for('bilibili', capabilities.BACKEND_CATBUS)}
        assert {'posts', 'hot', 'user.followers'} <= set(modes)
        followers = modes['user.followers']
        assert followers.handler == 'catbus', 'its handler is the generic CatBus walk'
        assert [f.key for f in followers.fields][:5] == ['author', 'target_count', 'catbus_account', 'recrawl']
        assert followers.needs_session is False, 'CatBus keeps its own account files'
        # A shared key reuses the browser declaration, so both engines show one form.
        assert modes['posts'] is capabilities.mode_for('bilibili', 'posts', capabilities.BACKEND_SELENIUM)

    def test_the_node_reads_its_mode_with_the_engine_it_stored(self, manifest):
        node = {'platform': 'bilibili', 'params': {'backend': 'catbus', 'collect': 'user.followers'}}
        mode = capabilities.mode_of_node(node)
        assert mode is not None and mode.key == 'user.followers'
        kwargs = capabilities.crawl_kwargs(mode, node['params'])
        assert kwargs['mode_key'] == 'user.followers', 'the generic walk is told which command to run'
        assert 'keyword' not in kwargs

    def test_a_stored_key_the_engine_does_not_offer_falls_to_a_cell_it_can_run(self, manifest):
        # ``author`` is a browser mode the fake manifest does not list at all; the first runnable
        # CatBus mode is posts. A key the engine DOES list (``hot``) stays exact and is refused later
        # by its own cell reason, so the panel shows what the node holds.
        mode = capabilities.mode_for('bilibili', 'author', capabilities.BACKEND_CATBUS)
        assert mode is not None and mode.key == 'posts'
        assert capabilities.mode_for('bilibili', 'hot', capabilities.BACKEND_CATBUS).key == 'hot'

    def test_an_unavailable_cell_refuses_by_the_adapters_own_words(self, manifest):
        assert capabilities.catbus_run_errors('bilibili', 'posts') == []
        errors = capabilities.catbus_run_errors('bilibili', 'hot')
        assert errors == ['CatBus 没有热榜命令']

    def test_a_missing_adapter_is_named_as_the_engine_not_as_an_unknown_platform(self, monkeypatch):
        monkeypatch.setattr(
            bridge,
            'probe',
            lambda force=False: SimpleNamespace(
                available=False,
                reason_key='catbus.noCli',
                reason_params={},
                manifest={},
            ),
        )
        errors = capabilities.catbus_run_errors('bilibili', 'posts')
        assert errors and 'CatBus' in errors[0]


class TestEnginesAndCellsInThePayload:
    def test_a_catbus_only_platform_has_only_the_catbus_engine(self, manifest):
        payload = capabilities.as_dict()
        kuaishou = next(p for p in payload['platforms'] if p['platform'] == 'kuaishou')
        assert [e['key'] for e in kuaishou['engines']] == ['catbus']
        assert kuaishou['labelKey'] == 'platform.kuaishou'
        assert [m['key'] for m in kuaishou['modes']] == ['user.followers']
        assert kuaishou['modes'][0]['engines'] == ['catbus']

    def test_every_mode_carries_its_engine_list_and_cell_verdict(self, manifest):
        payload = capabilities.as_dict()
        bili = next(p for p in payload['platforms'] if p['platform'] == 'bilibili')
        modes = {m['key']: m for m in bili['modes']}
        assert modes['posts']['engines'] == ['selenium', 'catbus']
        assert modes['posts']['cells']['catbus']['runnable'] is True
        assert modes['hot']['cells']['catbus'] == {
            'status': 'unavailable',
            'runnable': False,
            'reason': 'CatBus 没有热榜命令',
            'reasonKey': '',
            'columns': [],
            'identity': [],
        }
        assert modes['user.followers']['engines'] == ['catbus']
        assert modes['user.followers']['labelKey'] == 'catbus.mode.userFollowers'

    def test_an_unavailable_adapter_still_lists_the_engine_with_its_reason(self, monkeypatch):
        monkeypatch.setattr(
            bridge,
            'status_payload',
            lambda: {
                'available': False,
                'reasonKey': 'catbus.noNode',
                'panelKey': 'settings.backendNoNode',
                'cells': {},
            },
        )
        monkeypatch.setattr(bridge, 'manifest_platforms', lambda: {})
        payload = capabilities.as_dict()
        bili = next(p for p in payload['platforms'] if p['platform'] == 'bilibili')
        catbus = next(e for e in bili['engines'] if e['key'] == 'catbus')
        assert catbus['available'] is False
        assert catbus['reasonKey'] == 'settings.backendNoNode'
        # Shared functions still carry a CatBus cell, greyed with the server's key, so a saved
        # CatBus node shows what it holds instead of silently becoming a browser node.
        posts = next(m for m in bili['modes'] if m['key'] == 'posts')
        assert posts['cells']['catbus']['reasonKey'] == 'settings.backendNoNode'
        assert posts['cells']['catbus']['runnable'] is False


class TestTheLabelCatalogueCoversEveryManifestMode:
    def test_every_mode_the_manifest_can_produce_has_a_label_key(self, manifest):
        keys = {mode for entry in manifest['platforms'].values() for mode in entry['modes']}
        missing = sorted(k for k in keys if not capabilities.CATBUS_MODE_LABELS.get(k))
        assert missing == [], f'CatBus modes with no panel label: {missing}'

    def test_every_label_exists_in_both_browser_catalogues(self):
        source = (Path(__file__).resolve().parents[2] / 'backend' / 'static' / 'js' / 'app.js').read_text(
            encoding='utf-8'
        )
        for mode, key in capabilities.CATBUS_MODE_LABELS.items():
            occurrences = len(re.findall(rf"""['"]{re.escape(key)}['"]\s*:""", source))
            assert occurrences == 2, f'{mode} -> {key} appears {occurrences} times (want zh + en)'

    def test_the_engine_and_cell_words_exist_in_both_catalogues(self):
        source = (Path(__file__).resolve().parents[2] / 'backend' / 'static' / 'js' / 'app.js').read_text(
            encoding='utf-8'
        )
        for key in (
            'settings.crawlEngine',
            'settings.engineHint',
            'settings.backendNoPlatform',
            'settings.backendNoRunnable',
            'settings.backendNoSelenium',
            'settings.backendUnknown',
            'settings.catbusModeNote',
            'settings.catbusUrlsHint',
            'validate.modeUnavailable',
        ):
            assert len(re.findall(rf"""['"]{re.escape(key)}['"]\s*:""", source)) == 2, key


class TestTheCrawlerRefusesAnIgnoredCondition:
    def test_a_time_window_the_cell_does_not_consume_is_refused_before_the_walk(self, manifest, monkeypatch):
        calls = []
        monkeypatch.setattr(bridge, 'run', lambda *a, **k: calls.append(a) or SimpleNamespace())
        crawler = catbus_module.CatbusCrawler(
            platform='bilibili', params={'start_time': '2026-01-01', 'target_count': 3}
        )
        crawler.ledger = _Ledger()
        with pytest.raises(ValueError) as raised:
            crawler.search(keyword='k', target_count=3)
        assert 'start_time' in str(raised.value)
        assert calls == [], 'the refusal happens before a child process is bought'

    def test_a_seeded_default_is_not_a_condition_the_user_chose(self, manifest, monkeypatch):
        calls = []
        monkeypatch.setattr(
            bridge,
            'run',
            lambda *a, **k: (
                calls.append(a) or SimpleNamespace(status='ok', warnings=[], message='', hint='', exit_code=0, rows=[])
            ),
        )
        # ``board='popular'`` is seeded onto every bilibili node; a posts cell does not consume it,
        # but a value equal to the declared default is not a request the user made.
        crawler = catbus_module.CatbusCrawler(platform='bilibili', params={'board': 'popular'})
        crawler.ledger = _Ledger()
        crawler.search(keyword='k', target_count=1)
        assert calls, 'the walk still ran'


class _Ledger:
    def __init__(self):
        self.kept = []

    def __call__(self, row):
        self.kept.append(row)
        return True


def test_the_payload_is_still_json_ready_with_the_engine_dimension(manifest):
    json.dumps(capabilities.as_dict(), ensure_ascii=False)
