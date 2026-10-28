"""The executor's two backend branches, driven without a browser and without CatBus.

Two questions per leg, and the second half of each is the part a stubbed adapter cannot show: a node
that asked for the second backend must reach the adapter **without buying a Chrome** — no cookie
planted, no profile lock taken, no ``get_crawler`` call at all. A dispatch that merely "also worked"
would leave a browser starting for every CatBus node on a server that has no display, which is the
class of failure this app refuses by name elsewhere.

The adapter is answered at its own seam (``services.catbus_bridge``), so what is asserted here is
routing, arguments, and the ledger the rows are filed in — not CatBus's behaviour. The durable store
is the real one, because "the rows landed" is the thing under test and a stub would agree to
anything. ``app`` arrives through the ``app_module`` fixture rather than a module-level import: two
structural tests police that, because importing it boots the Flask app before conftest has moved
``data/`` and ``logs/`` into a temp root.
"""

import capabilities.registry as capabilities
import pytest

from services import catbus_bridge as bridge
from services.runs.store import RunStore

pytestmark = pytest.mark.api


def _source_plugin():
    from nodes.executors import source

    return source


@pytest.fixture(autouse=True)
def _forward_executor_seams(monkeypatch):
    """Existing patches of ``app.get_crawler``/``app.add_log`` still reach the source executor."""
    import app as app_module
    from executor_seams import forward
    from nodes.executors import source

    forward(monkeypatch, source, 'get_crawler', app_module)
    forward(monkeypatch, source, 'add_log', app_module)


_BILIBILI_LINK = 'https://www.bilibili.com/video/BV1xx411c7mD/'
_SECOND_LINK = 'https://www.bilibili.com/video/BV2yy411c7mE/'


class _NoBrowser:
    """Every argument list the browser factory ever took: a CatBus node may reach none of them."""

    def __init__(self, *_args, **_kwargs):
        raise AssertionError('a CatBus node must not construct a browser session')


class _Calls(list):
    """The recorded adapter calls, with the run store the cases file their rows into.

    A list subclass rather than a four-tuple fixture: every assertion reads ``adapter`` as the call
    log it is, and the store stays reachable without a second parameter on each test.
    """

    def __init__(self, store):
        super().__init__()
        self.store = store


@pytest.fixture
def adapter(app_module, monkeypatch, tmp_path):
    """The manifest says yes to everything, the rows are scripted, and no browser is allowed."""
    calls = _Calls(RunStore(str(tmp_path / 'catbus-dispatch.db')))
    monkeypatch.setattr(app_module, 'get_crawler', _NoBrowser)
    # The comment engine walks its links under `while execution_state['running']`; with the flag
    # cleared it returns an empty table without reaching a single adapter, which then reads as "the
    # site had nothing" rather than as a run that was never started. ``setitem`` so pytest restores
    # it — a leaked running=True makes the server look busy to every later test.
    monkeypatch.setitem(app_module.execution_state, 'running', True)
    monkeypatch.setattr(bridge, 'supports', lambda platform, mode: True)
    monkeypatch.setattr(bridge, 'mode_state', lambda platform, mode: ('available', ''))
    monkeypatch.setattr(bridge, 'columns_for', lambda platform, mode: ('标题', '链接', '评论ID', '文章URL'))
    monkeypatch.setattr(bridge, 'identity_for', lambda platform, mode: ('链接',))
    # The real manifest declares which arguments a cell consumes; the stub adapter must answer the
    # same question, or a keyword the scripted row set obviously used would be refused as an ignored
    # condition before the fake walk is reached.
    monkeypatch.setattr(bridge, 'declared_params', lambda platform, mode: ('keyword', 'target_count', 'catbus_account'))

    def fake_run(site, mode, params, **kw):
        first = (params.get('urls') or [''])[0]
        for index in (1, 2):
            kw['on_row'](
                {
                    '标题': f'条目{index}',
                    '链接': f'https://example.com/{index}',
                    '评论ID': str(index),
                    '文章URL': first,
                }
            )
        calls.append((site, mode, dict(params)))
        return bridge.Outcome(status='ok', rows=2)

    monkeypatch.setattr(bridge, 'run', fake_run)
    return calls


def _source_node(**params):
    base = {
        'platform': 'bilibili',
        'collect': 'posts',
        'keyword': '露营',
        'target_count': 2,
        # Fields every source node stores; none of them is an argument of the crawl.
        'account': 'work',
        'part_size': 500,
        'format': 'csv',
        'recrawl': False,
    }
    base.update(params)
    # The canvas stores the platform twice (the node's own field and the form's copy); a fixture that
    # updated only one would drive a different platform than the node claims to be.
    return {
        'id': 'node-1',
        'type': 'source',
        'title': '采集',
        'params': base,
        'platform': base['platform'],
    }


def _ctx(store, run_id='r-catbus'):
    store.start_run(run_id, 'catbus dispatch', 'fp-canvas', mode='serial', headless=True, lang='zh')
    store.begin_node(run_id, 'node-1', 'source', fingerprint='fp-node')
    return {
        'store': store,
        'run_id': run_id,
        'resume': False,
        'fingerprints': {'node-1': 'fp-node'},
        'skipped_seen': {},
        'use_profile': False,
    }


class TestTheSourceNodeChoosesItsBackend:
    def test_a_catbus_node_reaches_the_adapter_and_no_browser(self, app_module, adapter):
        rows = _source_plugin().execute_source_node(
            _source_node(backend=capabilities.BACKEND_CATBUS), headless=True, ctx=None
        )
        assert len(rows) == 2
        site, mode, params = adapter[0]
        assert (site, mode) == ('bilibili', 'posts')
        assert params['keyword'] == '露营' and params['target_count'] == 2

    def test_the_stored_form_travels_and_the_wrong_account_is_dropped_downstream(
        self, app_module, adapter, monkeypatch
    ):
        """Nothing is filtered on the way out, and the account that names the wrong session is.

        The manifest's argument list says what a cell *takes*, not what the user asked for, and
        dropping a stored condition over that difference yields a table that looks filtered. The
        adapter keeps and does not consume what it does not know, so forwarding costs noise while
        filtering costs a silent wrong answer. ``account`` is the one exception — it names a Selenium
        session — and it is dropped one layer down, in :func:`catbus_bridge._params_payload`, which
        this case reaches by calling that function instead of stubbing past it.
        """
        _source_plugin().execute_source_node(
            _source_node(backend='catbus', catbus_account='catbus-work'), headless=True, ctx=None
        )
        _site, _mode, params = adapter[0]
        assert params['catbus_account'] == 'catbus-work', 'the account the adapter can actually read'
        assert params['keyword'] == '露营', 'a stored condition is never dropped on the way out'
        assert params['target_count'] == 2, 'the argument this walk was called with wins the stored form'
        assert 'account' in params, 'the payload is not filtered here —'
        # — and the bridge is where the Selenium account leaves. Asserted on the real function, so a
        # change to either side shows up.
        from services.catbus_bridge import _params_payload

        assert 'account' not in _params_payload(params, 'catbus-work')

    def test_the_default_node_still_walks_the_browser_path(self, app_module, monkeypatch):
        """The other leg of the branch: nothing about a Selenium node moved.

        Recorded, not assumed — the dispatch is one ``if``, and an ``if`` whose else-branch is never
        driven is how a feature silently replaces the thing it was added beside.
        """
        asked = []

        class _Browser:
            def __init__(self, *_args, **kwargs):
                asked.append(kwargs)
                # Declared here so the stub keeps the real session's shape: the row sink is installed
                # right after construction, and an executor that stopped installing it would still
                # "work" against a stub whose attribute appears only on demand.
                self._sink = None

            def set_sink(self, sink):
                self._sink = sink

            def set_cursor_sink(self, sink):
                pass

            def search(self, keyword='', target_count=0, **_kwargs):
                return [{'标题': keyword}]

            def close(self):
                pass

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _Browser(**k))
        rows = _source_plugin().execute_source_node(_source_node(), headless=True, ctx=None)
        assert rows == [{'标题': '露营'}]
        assert asked and 'account' in asked[0], 'the browser kept the arguments it always took'

    def test_the_rows_are_filed_in_the_durable_ledger_like_any_crawl(self, app_module, adapter):
        """Not only returned: CatBus rows go through the same row sink, one transaction per row."""
        ctx = _ctx(adapter.store)
        rows = _source_plugin().execute_source_node(_source_node(backend='catbus'), headless=True, ctx=ctx)
        assert len(rows) == 2
        assert len(adapter.store.load_rows(ctx['run_id'], 'node-1')) == 2, 'the ledger holds what the node yielded'

    def test_an_unsupported_cell_refuses_before_any_process_or_browser(self, app_module, adapter, monkeypatch):
        monkeypatch.setattr(bridge, 'supports', lambda platform, mode: False)
        monkeypatch.setattr(bridge, 'mode_state', lambda platform, mode: ('planned', '列映射尚未实现'))
        adapter.clear()
        with pytest.raises(ValueError) as raised:
            _source_plugin().execute_source_node(
                _source_node(platform='weibo', backend='catbus'), headless=True, ctx=None
            )
        assert '列映射尚未实现' in str(raised.value)
        assert adapter == [], 'a cell the manifest refuses must not start a child process'

    def test_a_catbus_only_function_runs_through_the_generic_walk(self, app_module, adapter, monkeypatch):
        """A platform CatBus alone offers, through a function Selenium never had.

        The executor's dispatch is one ``getattr(crawler, mode.handler)``; the CatBus-only form names
        ``catbus`` as its handler and carries the command as ``mode_key``, so no per-platform branch is
        added anywhere. ``kuaishou`` has no Selenium crawler class at all, which is the point.
        """
        manifest = {
            'kuaishou': {
                'catbus_platform': 'kuaishou',
                'label': '快手',
                'modes': {
                    'user.followers': {
                        'status': 'available',
                        'command': 'user followers',
                        'args': ['user'],
                        'optional': {'user': 'me'},
                        'paged': True,
                        'output': 'User',
                        'params': ['author', 'target_count', 'catbus_account'],
                        'columns': ['平台', '用户ID'],
                        'identity': ['平台', '用户ID'],
                        'auth': 'required',
                    }
                },
            }
        }
        monkeypatch.setattr(bridge, 'manifest_platforms', lambda: manifest)
        monkeypatch.setattr(bridge, 'supports', lambda platform, mode: True)
        monkeypatch.setattr(bridge, 'mode_state', lambda platform, mode: ('available', ''))
        monkeypatch.setattr(
            bridge, 'declared_params', lambda platform, mode: ('author', 'target_count', 'catbus_account')
        )
        monkeypatch.setattr(bridge, 'identity_for', lambda platform, mode: ('平台', '用户ID'))
        rows = _source_plugin().execute_source_node(
            _source_node(
                platform='kuaishou',
                collect='user.followers',
                author='me',
                # The base fixture carries a keyword for the search form; this cell takes an author,
                # and a keyword it does not consume is exactly what the refusal tests cover elsewhere.
                keyword='',
                backend='catbus',
            ),
            headless=True,
            ctx=None,
        )
        assert len(rows) == 2
        site, mode, params = adapter[0]
        assert (site, mode) == ('kuaishou', 'user.followers'), 'the manifest cell is the command that ran'
        assert params['author'] == 'me' and params['target_count'] == 2


class TestTheCommentNodeChoosesItsBackend:
    @pytest.fixture
    def comment_exec(self):
        from nodes.executors import comment

        return comment

    def _node(self, urls, **params):
        base = {'urls': urls, 'comment_limit': 20, 'backend': 'catbus', 'account': 'work'}
        base.update(params)
        return {'id': 'node-1', 'type': 'comment', 'title': '评论', 'params': base}

    def test_one_link_one_adapter_call_and_no_session_browser(self, comment_exec, adapter):
        rows = comment_exec.execute_comment_node(
            self._node(f'{_BILIBILI_LINK}\n{_SECOND_LINK}'), headless=True, ctx=None
        )
        assert len(rows) == 4, 'two links, two calls, both sets of rows kept'
        assert [call[1] for call in adapter] == ['comments', 'comments']
        assert [call[2]['urls'] for call in adapter] == [[_BILIBILI_LINK], [_SECOND_LINK]]
        assert adapter[0][2]['comment_limit'] == 20

    def test_the_engine_owns_the_cursor_and_the_node_never_buys_a_profile(self, comment_exec, adapter):
        """With a run context the same engine advances ``url_index`` over proven links.

        CatBus supplies rows; the position, the dedupe ledger and the settlement stay the comment
        engine's, which is what makes 继续 mean the same thing on both backends.
        """
        ctx = _ctx(adapter.store)
        rows = comment_exec.execute_comment_node(self._node(_BILIBILI_LINK), headless=True, ctx=ctx)
        assert len(rows) == 2
        assert len(adapter.store.load_rows(ctx['run_id'], 'node-1')) == 2
        assert adapter.store.get_cursor(ctx['run_id'], 'node-1'), 'the walked link advanced the position'

    def test_a_walled_link_refuses_naming_the_adapters_own_command(
        self, app_module, comment_exec, adapter, monkeypatch
    ):
        """The engine's BLOCKED path is a cookie sentence, so this backend may not enter it."""

        def fake_run(site, mode, params, **kw):
            return bridge.Outcome(
                status='error', rows=0, message='user items 需要登录', hint='catbus bilibili auth login'
            )

        # The assertion below is "THIS refusal did not raise the flag", so the flag must start
        # clean rather than inherit whatever an earlier wall test left on the shared state.
        monkeypatch.setitem(app_module.execution_state, 'cookie_expired', False)
        monkeypatch.setattr(bridge, 'run', fake_run)
        with pytest.raises(ValueError) as raised:
            comment_exec.execute_comment_node(self._node(_BILIBILI_LINK), headless=True, ctx=None)
        assert 'catbus bilibili auth login' in str(raised.value)
        assert app_module.execution_state.get('cookie_expired') is not True, (
            'a CatBus wall is not a dead cookie, and the toast may not say otherwise'
        )
