"""The run-level matrix: parallel or serial × one platform or two × profile or not.

A browser profile holds one Chrome at a time (chromedriver pre-writes the profile's
preferences file, and two sessions created in it together cannot both come up —
measured, and it surfaces as ``session not created: failed to write prefs file``).
That collides head-on with 并行, so the user is asked which of the two they want for
this run. This module pins what the server then *does* with that answer, because every
other layer can claim a policy and mean nothing by it:

* parallel + one shared platform + **profile** → the crawls take turns: no overlap,
  both nodes still finish;
* parallel + one shared platform + **no profile** → they genuinely overlap, and the
  console says the deviation once;
* parallel + two different platforms → untouched: separate directories contend with
  nothing, so waiting there would be a cost invented out of nowhere;
* no answer sent → ``None`` reaches the factory, meaning "follow the setting".
  Absence must never read as a refusal, or one browser's dialog would become a global
  override for every caller.

The crawler is a fake, but it is a fake built on the real :class:`Crawler` profile
plumbing: it claims the directory exactly as a browser does, so what the test observes
is the lock rather than a mock's opinion about it. Overlap is read off recorded
time spans, which is the only thing the user actually feels.
"""

import threading
import time

import browser_profiles
import crawl_gate
import pytest
from run_wait import run_finished

from crawlers.base import Crawler

pytestmark = [pytest.mark.api, pytest.mark.serial]

PAGE = [{'作者': f'a{i}', '正文': f'b{i}'} for i in range(3)]

#: How long a fake crawl holds its browser. Long enough that two of them started
#: together must overlap unless something serialises them.
HOLD = 0.6

#: {platform: [(started, finished), …]} written by every fake crawl of the run.
SPANS: list = []
SPANS_LOCK = threading.Lock()


class _MatrixCrawler(Crawler):
    """A crawl that owns its profile for its whole life, then lets go."""

    def __init__(self, platform, profile_dir):
        self.platform = platform
        super().__init__(headless=True, profile_dir=profile_dir)

    def _create_driver(self):
        self.driver = None

    def get_detail(self, url):
        return None

    def search(self, keyword=None, target_count=None, resume=None, urls=None, **kw):
        started = time.monotonic()
        recorded = [started, None]
        with SPANS_LOCK:
            SPANS.append(recorded)
        # Tagged with this crawl's own keyword: the incremental ledger refuses items
        # this node has already stored, and two fakes emitting byte-identical rows
        # would test the ledger instead of the profile.
        for item in PAGE:
            self.emit({'关键词': keyword or '', **item})
            self.mark_position(item_index=self.collected())
        while time.monotonic() - started < HOLD:
            time.sleep(0.02)
        recorded[1] = time.monotonic()
        return self.results()


@pytest.fixture
def matrix(monkeypatch, app_module, tmp_path):
    """Replace the factory with the profile-claiming fake; record what it was asked."""
    values = {'use_browser_profile': True, 'browser_profile_dir': str(tmp_path / 'profiles')}
    monkeypatch.setattr(browser_profiles, 'get_setting', lambda key: values[key])
    # Both gate knobs, in one place a test can flip. The wait is a real one here — its
    # *length* is asserted in tests/unit/test_crawl_gate.py against a fake clock — so
    # this module shrinks it to keep the suite honest but fast.
    gate = {'same_platform_queue': True, 'same_platform_stagger': 0.05}
    monkeypatch.setattr(crawl_gate, 'get_setting', lambda key: gate[key])
    SPANS.clear()
    asked = []

    def _factory(platform, headless=True, cookie_dir=None, for_login=False, use_profile=None, abort=None):
        profile = browser_profiles.profile_dir_for(platform, enabled=use_profile)
        asked.append({'platform': platform, 'use_profile': use_profile, 'profile_dir': profile})
        return _MatrixCrawler(platform, profile)

    monkeypatch.setattr(app_module, 'get_crawler', _factory)
    return {'asked': asked, 'gate': gate}


def _source(node_id, platform, keyword=None):
    params = {'platform': platform, 'keyword': keyword or f'测试{node_id}', 'target_count': len(PAGE)}
    return {'id': node_id, 'type': 'source', 'title': f'采集 {platform}', 'params': params}


def _canvas(nodes, mode='parallel', **settings):
    return {'nodes': nodes, 'connections': [], 'settings': dict({'mode': mode, 'headless': True}, **settings)}


def _overlaps(spans=SPANS):
    """Pairs of crawls that were holding a browser at the same moment."""
    settled = [tuple(entry) for entry in spans if entry[1] is not None]
    return [(a, b) for index, a in enumerate(settled) for b in settled[index + 1 :] if a[0] < b[1] and b[0] < a[1]]


def _run(client, app_module, workflow):
    response = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'matrix'})
    body = response.get_json()
    assert body.get('ok'), body
    assert run_finished(app_module), 'the run never settled'
    return body['run_id']


def _stored_run(run_id):
    from app import get_run_store

    return get_run_store().get_run(run_id)


def _nodes(run_id):
    return {node['node_id']: node for node in _stored_run(run_id)['nodes']}


class TestSamePlatformParallel:
    def test_with_profiles_the_two_crawls_take_turns(self, client, app_module, matrix):
        run_id = _run(client, app_module, _canvas([_source('s-1', 'bilibili'), _source('s-2', 'bilibili')]))
        assert len(SPANS) == 2, SPANS
        assert not _overlaps(), f'one profile held two browsers at once: {_overlaps()}'
        # Taking turns must not be achieved by one of them failing.
        nodes = _nodes(run_id)
        assert {node['status'] for node in nodes.values()} == {'done'}, nodes
        assert all(node['row_count'] == len(PAGE) for node in nodes.values()), nodes

    def test_the_queue_orders_one_platform_even_without_profiles(self, client, app_module, matrix):
        """「本次不用 Profile」buys a new device, not a second conversation.

        The two collisions are different events: two throwaway browsers can start
        together and still be answered a login wall, because the *account* behind
        them searched twice in one second (measured on weibo and zhihu). So one
        platform takes turns whether or not a profile is shared — which is the
        opposite of what this test asserted before 同平台排队 existed, when the only
        serialiser was the profile directory.
        """
        flow = _canvas([_source('s-1', 'bilibili'), _source('s-2', 'bilibili')], use_profile=False)
        run_id = _run(client, app_module, flow)
        assert len(SPANS) == 2, SPANS
        assert not _overlaps(), f'two crawls of one platform were let in together: {SPANS}'
        assert {entry['use_profile'] for entry in matrix['asked']} == {False}, 'each still got its own device'
        assert {node['status'] for node in _nodes(run_id).values()} == {'done'}, 'ordering must not cost a node'

    def test_a_crawl_that_queued_says_so_exactly_once(self, client, app_module, matrix):
        _run(client, app_module, _canvas([_source('s-1', 'bilibili'), _source('s-2', 'bilibili')]))
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        queued = [
            line for line in blob.splitlines() if 'Bilibili' in line and ('排队' in line or 'queue' in line.lower())
        ]
        assert len(queued) == 1, f'the wait belongs to the one crawl that waited, saw {queued}'

    def test_turning_the_queue_off_restores_true_overlap(self, client, app_module, matrix, monkeypatch):
        """Off is the user's own choice and must mean the old behaviour, not a weaker
        on: two crawls of one platform alive at the same moment, gaps and all."""
        monkeypatch.setattr(crawl_gate, 'get_setting', lambda key: False)
        _run(client, app_module, _canvas([_source('s-1', 'bilibili'), _source('s-2', 'bilibili')], use_profile=False))
        assert len(SPANS) == 2, SPANS
        assert _overlaps(), f'the queue is off and they still took turns: {SPANS}'

    def test_declining_profiles_is_said_exactly_once(self, client, app_module, matrix):
        flow = _canvas([_source('s-1', 'bilibili'), _source('s-2', 'bilibili')], use_profile=False)
        _run(client, app_module, flow)
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        said = sum(1 for line in blob.splitlines() if 'Profile' in line or 'profile' in line)
        assert said == 1, f'the deviation should be stated once, the console said it {said} times:\n{blob}'

    def test_keeping_profiles_queues_without_complaining(self, client, app_module, matrix):
        run_id = _run(client, app_module, _canvas([_source('s-1', 'bilibili'), _source('s-2', 'bilibili')]))
        record = _stored_run(run_id)
        assert record['status'] == 'completed', record
        assert record['wf_count'] == 2, 'two workflows, still one record'
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert 'run uses no browser profile' not in blob and '不使用' not in blob, (
            f'keeping the profile is not a deviation, so nothing should announce it:\n{blob}'
        )


class TestDifferentPlatformsParallel:
    def test_two_platforms_never_wait_for_each_other(self, client, app_module, matrix):
        _run(client, app_module, _canvas([_source('s-1', 'bilibili'), _source('s-2', 'zhihu')]))
        assert len(SPANS) == 2, SPANS
        assert _overlaps(), f'different directories share nothing, so this wait was invented: {SPANS}'
        assert sorted(entry['platform'] for entry in matrix['asked']) == ['bilibili', 'zhihu']


class TestSerialCanvas:
    def test_one_workflow_at_a_time_never_contends_even_with_profiles(self, client, app_module, matrix):
        flow = _canvas([_source('s-1', 'bilibili'), _source('s-2', 'bilibili')], mode='serial')
        _run(client, app_module, flow)
        assert len(SPANS) == 2, SPANS
        assert not _overlaps(), SPANS


class TestNoAnswerSent:
    def test_an_omitted_choice_follows_the_setting(self, client, app_module, matrix):
        _run(client, app_module, _canvas([_source('s-1', 'bilibili')]))
        asked = matrix['asked']
        assert len(asked) == 1 and asked[0]['use_profile'] is None, asked
        # None means "ask the setting", and the setting here is on — so the factory
        # resolved a real directory and the crawl ran inside it.
        assert asked[0]['profile_dir'] == browser_profiles.platform_dir('bilibili'), asked

    def test_a_declined_profile_resolves_no_directory(self, client, app_module, matrix):
        """A falsy answer is a choice, not an absence: it must land as False, never
        collapse into None and inherit the setting back."""
        flow = _canvas([_source('s-1', 'bilibili')], use_profile=False)
        _run(client, app_module, flow)
        assert matrix['asked'][0]['use_profile'] is False
        assert matrix['asked'][0]['profile_dir'] is None, matrix['asked']
