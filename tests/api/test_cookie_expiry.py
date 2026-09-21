"""The cookie-dies-mid-crawl flow, end to end and deterministically.

A long crawl eventually outlives its cookie. The contract this pins is the
whole promised recovery, driven through the real execute endpoint with a fake
crawler whose session dies on schedule:

1. the wall stops the crawl, but every row scraped BEFORE it is stored;
2. the node FAILS rather than "completes" short — so the run appears in the
   resume banner instead of hiding a silent gap;
3. /api/workflow/status carries ``cookie_expired`` for the browser's toast;
4. 继续 resume (new crawler = "fresh cookie", same run id) seeds the stored
   rows, picks up the crawler's cursor and collects the remainder — with the
   ledger making duplicates impossible.

Everything runs offline against the tmp-isolated store from the client
fixture; no browser, no network.
"""

import pytest

from crawlers.base import Crawler, as_index

pytestmark = [pytest.mark.api, pytest.mark.serial]


class SimCrawler(Crawler):
    """A crawl over a fixed card list through the REAL streaming contract.

    ``expire_after`` kills the session (login wall) once that many rows are
    collected; ``None`` crawls the rest of the page. The cursor is
    ``item_index`` — the same shape the platform crawlers persist, so resume
    exercises the app's cursor plumbing, not a mock's.
    """

    domain = 'zhihu'
    login_url = 'https://www.zhihu.com/'

    def __init__(self, page, expire_after=None):
        self._page = list(page)
        self._expire_after = expire_after
        super().__init__(headless=True)

    def _create_driver(self):
        self.driver = None

    def get_detail(self, url):
        # Abstract on Crawler; the card-stream simulation has no detail page.
        return None

    def search(self, keyword=None, target_count=None, urls=None, resume=None, **kw):
        cursor = self.resume_of({'resume': resume or {}})
        i = as_index(cursor.get('item_index'))
        goal = int(target_count or len(self._page))
        while i < len(self._page) and self.collected() < goal:
            item = self._page[i]
            i += 1
            self.emit(item)
            self.mark_position(item_index=i, done=self.collected())
            if self._expire_after is not None and self.collected() >= self._expire_after:
                self.login_wall = True
                break
        return self.results()


def _node(node_id, node_type, params):
    return {'id': node_id, 'type': node_type, 'title': node_type, 'params': params}


def _source_workflow(target=10):
    node = _node(
        'node-1',
        'source',
        {'platform': 'zhihu', 'keyword': '测试', 'target_count': target, 'headless': True},
    )
    return {'nodes': [node], 'connections': [], 'settings': {'mode': 'serial'}}


PAGE = [{'作者': f'a{i}', '正文': f'body {i}'} for i in range(10)]


@pytest.fixture
def sim(monkeypatch, app_module):
    """Steers which SimCrawler the executor builds. Yields (configure, made)."""
    plan = {'expire_after': None, 'page': PAGE}
    made = []

    def _configure(expire_after, page=None):
        plan['expire_after'] = expire_after
        if page is not None:
            plan['page'] = page

    def fake_get_crawler(platform, headless=True, cookie_dir=None):
        crawler = SimCrawler(plan['page'], plan['expire_after'])
        made.append(crawler)
        return crawler

    monkeypatch.setattr(app_module, 'get_crawler', fake_get_crawler)
    return _configure, made


def _wait(app_module, timeout=30.0):
    import time

    thread = app_module.execution_state.get('thread')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = thread is not None and thread.is_alive()
        if not app_module.execution_state['running'] and not alive:
            return True
        time.sleep(0.1)
    return False


class TestCookieExpiryMidCrawl:
    def test_wall_stops_run_keeps_rows_fails_node_and_flags_status(self, client, app_module, sim):
        configure, _made = sim
        configure(expire_after=4)
        started = client.post(
            '/api/workflow/execute', json={'workflow': _source_workflow(), 'workflow_name': 'expiry-stop'}
        )
        run_id = started.get_json()['run_id']
        assert _wait(app_module)

        status = client.get('/api/workflow/status').get_json()
        assert status['cookie_expired'] is True, 'the toast flag must ride on the status payload'
        assert any('login session looks expired' in line for line in status['logs'])

        store = app_module._RUN_STORE
        run = store.get_run(run_id)
        nodes = {node['node_id']: node for node in run['nodes']}
        # Short-of-target + wall = a broken node, never a clean 'done': a
        # completed run would vanish from the resume banner with a silent gap
        # inside. With rows already streamed it settles as 'partial'.
        assert run['status'] == 'failed'
        assert nodes['node-1']['status'] == 'partial'
        assert 'login session' in nodes['node-1']['error']
        # The rows the wall arrived with are the resume base — all still stored.
        assert store.row_count(run_id, 'node-1') == 4
        assert store.get_cursor(run_id, 'node-1')['item_index'] == 4

    def test_resume_after_fresh_cookie_completes_without_duplicates(self, client, app_module, sim):
        configure, made = sim
        configure(expire_after=4)
        workflow = _source_workflow()
        first = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': 'expiry-resume'})
        run_id = first.get_json()['run_id']
        assert _wait(app_module)
        assert app_module._RUN_STORE.row_count(run_id, 'node-1') == 4

        # "The user refreshes the cookie": the next attempt survives the wall.
        configure(expire_after=None)
        second = client.post(
            '/api/workflow/execute',
            json={'workflow': workflow, 'workflow_name': 'expiry-resume', 'resume_run_id': run_id},
        )
        assert second.get_json()['run_id'] == run_id, 'resume must reuse the run'
        assert _wait(app_module)

        store = app_module._RUN_STORE
        run = store.get_run(run_id)
        assert run['status'] == 'completed'
        rows = store.load_rows(run_id, 'node-1')
        # 4 kept + 6 collected = the whole page, exactly once each.
        assert len(rows) == 10, f'resume must finish the crawl, got {len(rows)}'
        assert {row['正文'] for row in rows} == {f'body {i}' for i in range(10)}
        # The resumed crawler really started from the stored 4 rows...
        assert made[1].position['item_index'] == 10
        # ...and the fresh run cleared the stale expiry flag.
        assert client.get('/api/workflow/status').get_json()['cookie_expired'] is False

    def test_wall_with_target_reached_is_not_a_failure(self, client, app_module, sim):
        # If the cookie dies exactly when the target is met, the crawl IS done.
        configure, _made = sim
        configure(expire_after=10)
        started = client.post(
            '/api/workflow/execute', json={'workflow': _source_workflow(), 'workflow_name': 'expiry-lucky'}
        )
        run_id = started.get_json()['run_id']
        assert _wait(app_module)
        run = app_module._RUN_STORE.get_run(run_id)
        assert run['status'] == 'completed'
        assert app_module._RUN_STORE.row_count(run_id, 'node-1') == 10

    def test_status_reports_no_expiry_without_a_run(self, client):
        assert client.get('/api/workflow/status').get_json()['cookie_expired'] is False
