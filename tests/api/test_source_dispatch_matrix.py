"""Every (platform, mode) pair of the crawl matrix, driven to its crawler method.

`crawl_capabilities.CAPABILITIES` is the only answer to "what can this platform collect", and 24
pairs ride on it. Until now every fake crawler in the suite defined ``search`` and nothing else, so
the six 「某作者的作品」 modes and the 热榜 mode had never been *dispatched* anywhere: a node that
called ``search()`` with the author dropped, or lost ``board=``, or sent the creator's handle under
a keyword key, would have passed the whole fast tier — the rows it fakes come back either way, and
an author crawl mistaken for a keyword crawl is a different answer with the same shape.

What is asserted is the routing and the arguments, per pair:

* the crawler METHOD executed is the one the matrix names (``mode.handler``),
* the kwargs that arrived are exactly the ones the matrix builds for that mode — no key renamed,
  dropped, or quietly defaulted at the executor,
* and the node still yields its rows, so a refusal (the fake raising) is not scored as success.

Two of those legs are not the same code path, and the file follows that: a ``comments`` mode is not
a crawler method at all — the executor routes it to ``_execute_comment_node``, which drives
``CommentSession.crawl_<platform>`` over the node's pasted links — so those pairs assert they reach
*that* engine with their own links and never touch the crawler. The third test then checks, for every
pair, that the name the matrix points at exists where the executor will look for it.

Four further sections close the holes that stayed open once every pair was dispatched at all. A node
with a stored cursor never reached an author or 热榜 handler; the fake always filled a select with its
FIRST option, so bilibili's ``board='ranking'`` got nowhere near the executor; a required field was
never checked for being *non-empty*, so an author platform added without a row in ``_SAMPLES`` would
have dispatched ``author=''`` and stayed green; and the two ways a hot mode differs from its own name
went unasserted — a site that publishes exactly one list must not be handed a ``board`` argument at
all, and the one board measured answering an anonymous browser must not make the canvas ask for a
cookie.

Everything is offline: the crawler is a scripted recorder, no browser and no network.
"""

import pytest

import crawl_capabilities as capabilities
from crawlers.base import as_index

pytestmark = pytest.mark.api

#: A value that survives each platform's own parser, per field key + platform.
_SAMPLES = {
    ('author', 'zhihu'): 'https://www.zhihu.com/people/abc',
    ('author', 'weibo'): 'https://weibo.com/u/6302837173',
    ('author', 'bilibili'): 'https://space.bilibili.com/546195',
    ('author', 'douyin'): 'MS4wLjABAAAAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
    ('author', 'youtube'): '@NASA',
    ('author', 'twitter'): '@NASA',
    ('urls', 'zhihu'): 'https://www.zhihu.com/question/1/answer/2',
    ('urls', 'weibo'): 'https://weibo.com/123/AbCdEf',
    ('urls', 'xiaohongshu'): 'https://www.xiaohongshu.com/explore/abc',
    ('urls', 'wechat'): 'https://mp.weixin.qq.com/s/xyz',
    ('urls', 'bilibili'): 'https://www.bilibili.com/video/BV1xx411c7mD',
    ('urls', 'douyin'): 'https://www.douyin.com/video/7665683746674183459',
    ('urls', 'youtube'): 'https://www.youtube.com/watch?v=abc',
    ('urls', 'twitter'): 'https://x.com/nasa/status/1234567890',
}

_ROWS = [{'标题': f'条目{i}', '链接': f'https://example.com/{i}'} for i in range(1, 4)]


class _NoBrowser:
    """Stand-in for the WebDriver the comment engine is handed.

    `CommentSession(driver)` is constructed before the first link is read, so
    without *any* attribute named `driver` the recorder would blow up inside the
    session's own constructor — and a real Chrome is exactly what this file
    promises not to start.
    """


class _RecordingCrawler:
    """Any handler the matrix points at is recorded; nothing is crawled for real.

    Every method answers the same way and the call log is class-level, so a test reads
    exactly one entry — and a node that quietly reached a *second* method is visible.
    """

    calls = []

    def __init__(self, *args, **kwargs):
        self._sink = None
        self.driver = _NoBrowser()

    def set_sink(self, sink):
        self._sink = sink

    def set_cursor_sink(self, sink):
        pass

    def seed(self, saved):
        pass

    def close(self):
        pass

    @property
    def login_wall(self):
        return False

    def _answer(self, name, kwargs):
        type(self).calls.append((name, dict(kwargs)))
        kept = []
        for item in _ROWS:
            if self._sink is None or self._sink(item):
                kept.append(item)
        return kept

    def search(self, *args, **kwargs):
        return self._answer('search', kwargs)

    def author(self, *args, **kwargs):
        return self._answer('author', kwargs)

    def hot(self, *args, **kwargs):
        return self._answer('hot', kwargs)

    def comments(self, *args, **kwargs):
        return self._answer('comments', kwargs)


class _AdvancingCrawler(_RecordingCrawler):
    """A fake that reports where it got to, the way every real handler does.

    `Crawler.mark_position` merges what changed and pushes the whole position into
    the sink the executor installed (`_source_stream`'s cursor sink → the store).
    Copying that shape is what lets the resume test below read BOTH halves of the
    contract from one run: the position the last attempt stored must arrive as the
    ``resume`` argument, and the position this attempt reached must land back in the
    store so the next 继续 starts there. A recorder that swallowed the sink could
    only ever prove the first half.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cursor = {}
        self._cursor_sink = None

    def set_cursor_sink(self, sink):
        self._cursor_sink = sink

    def mark_position(self, **position):
        self._cursor.update(position)
        if self._cursor_sink is not None:
            self._cursor_sink(dict(self._cursor))

    def _answer(self, name, kwargs):
        kept = super()._answer(name, kwargs)
        # Real crawlers count ON from the position they were handed — `resume_of`
        # plus `as_index` in every platform module — so a fake that started from
        # zero would hide an ignored cursor instead of exposing it.
        start = as_index((kwargs.get('resume') or {}).get('item_index'))
        self.mark_position(item_index=start + len(kept), done=len(kept))
        return kept


@pytest.fixture
def recorder(app_module, monkeypatch):
    _RecordingCrawler.calls = []
    monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _RecordingCrawler())
    # The comment engine walks its links under `while execution_state['running']`, so
    # with the flag cleared it returns an empty table without reaching a single
    # adapter — and the test below would read that as "no rows" rather than as the
    # run having been stopped. `setitem` rather than a bare assignment: this module
    # never takes the `client` fixture, so nothing else would put the flag back, and
    # a leaked `running=True` makes the server look busy to every later test — which
    # is how one matrix test here cost 400 failures and a 5-minute hang downstream.
    monkeypatch.setitem(app_module.execution_state, 'running', True)
    return _RecordingCrawler.calls


@pytest.fixture
def advancing(app_module, recorder, monkeypatch):
    """The recorder again, but the fake reports its position too (see `_AdvancingCrawler`).

    Re-patching on top of `recorder` rather than replacing it: that fixture owns the
    `running` flag restore, and a source crawl that saw the flag cleared returns an
    empty table — which the resume test below would read as "the crawl produced
    nothing" instead of as the run having been stopped.
    """
    monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _AdvancingCrawler())
    return recorder


#: What an interrupted attempt left in `node_runs.cursor_json`. The shape is the
#: one `Crawler.mark_position` writes and every platform handler reads back.
_STORED_CURSOR = {'item_index': 42, 'done': 42}


@pytest.fixture
def stopped_run(tmp_path):
    """A real run record whose source node stopped at a stored position.

    The store is not a stub because the thing under test is the hand-off between two
    real components: `app.py` reads the cursor through `RunStore.get_cursor`, so a
    mock that answered the shape the test expected would also pass when the executor
    looked in the wrong column, for the wrong node, or not at all.
    """
    from services.run_store import RunStore

    store = RunStore(str(tmp_path / 'dispatch-resume.db'))
    store.start_run('r-dispatch', 'dispatch', 'fp-canvas', headless=True)
    store.begin_node('r-dispatch', 'node-1', 'source', title='采集', fingerprint='fp-node')
    store.save_cursor('r-dispatch', 'node-1', dict(_STORED_CURSOR))
    assert store.get_cursor('r-dispatch', 'node-1') == _STORED_CURSOR, 'the fixture must store what it claims'
    return store


def _pairs(handlers=None, exclude=None):
    """(platform, mode key) for the matrix's modes, split by which path they take.

    A ``comments`` mode is not a crawler method: `_execute_source_node` hands it to
    the comment engine (app.py's ``mode.handler == 'comments'`` branch), so it gets
    its own test below rather than a false expectation of a crawler call.
    """
    out = []
    for cap in capabilities.CAPABILITIES:
        for mode in cap.modes:
            if handlers is not None and mode.handler not in handlers:
                continue
            if exclude is not None and mode.handler in exclude:
                continue
            out.append(pytest.param(cap.platform, mode.key, id=f'{cap.platform}-{mode.key}'))
    return out


def _params_for(platform, mode):
    """What the panel would have stored: matrix defaults, the chosen mode, and a
    parseable value per field.

    ``collect`` is not decoration — without it the node asks for nothing and
    `mode_for` answers the platform's FIRST mode, which is precisely the fallback
    that makes an author node run a keyword search.
    """
    params = dict(capabilities.declared_defaults(platform))
    params[capabilities.MODE_KEY] = mode.key
    for field in mode.fields:
        sample = _SAMPLES.get((field.key, platform))
        if sample is not None:
            params[field.key] = sample
        elif field.key == 'keyword':
            params['keyword'] = '矩阵测试'
        elif field.control == 'select' and field.options:
            params[field.key] = field.options[0][0]
    return params


@pytest.mark.parametrize('platform,mode_key', _pairs(exclude={'comments'}))
def test_a_mode_reaches_the_handler_the_matrix_names(app_module, recorder, platform, mode_key):
    mode = capabilities.mode_for(platform, mode_key)
    assert mode is not None, f'{platform}/{mode_key} is in CAPABILITIES but not resolvable'
    params = _params_for(platform, mode)
    node = {'id': 'node-1', 'type': 'source', 'title': '采集', 'params': params, 'platform': platform}

    rows = app_module._execute_source_node(node, headless=True, ctx=None)

    assert rows, f'{platform}/{mode_key} produced nothing, so the dispatch below proves nothing'
    assert len(recorder) == 1, f'{platform}/{mode_key} reached {len(recorder)} crawler methods: {recorder}'
    called, kwargs = recorder[0]
    assert called == mode.handler, f'{platform}/{mode_key} must run {mode.handler}(), ran {called}()'

    expected = capabilities.crawl_kwargs(mode, params)
    missing = {k: v for k, v in expected.items() if k not in kwargs}
    assert not missing, f'{platform}/{mode_key} lost its arguments at the executor: {missing}'
    for key, value in expected.items():
        assert kwargs[key] == value, f'{platform}/{mode_key}: {key} arrived as {kwargs[key]!r}, not {value!r}'
    # `resume` is the executor's own addition — where the last attempt stopped.
    assert kwargs.get('resume') == {}, f'{platform}/{mode_key} sent a resume position unasked'
    extra = set(kwargs) - set(expected) - {'resume'}
    assert not extra, f'{platform}/{mode_key} was handed arguments the matrix never declared: {extra}'


@pytest.mark.parametrize('platform,mode_key', _pairs(handlers={'comments'}))
def test_a_comments_mode_reaches_the_comment_engine(app_module, recorder, monkeypatch, platform, mode_key):
    """「采集内容=评论」 is a different engine, not a crawler method.

    The node must hand its pasted links to the comment engine and yield what comes
    back: a comments mode that quietly fell through to the platform's article crawl
    would return rows shaped like posts and still look green here — which is the
    failure this matrix exists to catch.
    """
    import crawlers.comments as comments_module

    seen = []

    class _Session:
        """The engine's contract: one `crawl_<platform>(url, limit)` per platform.

        `_execute_comment_node` looks that adapter up by name and refuses when it is
        missing, so recording WHICH adapter answered is part of the assertion.
        """

        def __init__(self, driver, log=None, **kwargs):
            self._log = log

        def __getattr__(self, name):
            if not name.startswith('crawl_'):
                raise AttributeError(name)

            def crawl(url, limit):
                seen.append((name, url, limit))
                return [{'评论ID': 'c1', '评论内容': '很好', '文章URL': url}], 'ok'

            return crawl

    monkeypatch.setattr(comments_module, 'CommentSession', _Session)
    mode = capabilities.mode_for(platform, mode_key)
    params = _params_for(platform, mode)
    node = {'id': 'node-1', 'type': 'source', 'title': '评论', 'params': params, 'platform': platform}

    rows = app_module._execute_source_node(node, headless=True, ctx=None)

    assert rows, f'{platform}/{mode_key} returned no comment rows'
    assert recorder == [], f'{platform}/{mode_key} also ran a crawler method: {recorder}'
    assert seen, f'{platform}/{mode_key} never reached the comment engine'
    adapter, url, _limit = seen[0]
    assert adapter == f'crawl_{platform}', f'{platform} comments answered with {adapter}'
    assert url and url.strip() and platform in url.replace('x.com', 'twitter'), (
        f'{platform}/{mode_key} sent a link that is not its own: {url}'
    )


@pytest.mark.parametrize('platform,mode_key', _pairs())
def test_the_matrix_offers_no_mode_that_cannot_be_dispatched(platform, mode_key):
    """A handler the runtime cannot reach is a refusal at crawl time, not a fallback.

    Two names to look up, because a mode points at one of two places: a non-comment
    handler is a METHOD ON THE CRAWLER CLASS, while 「评论」 is an ADAPTER ON THE COMMENT
    ENGINE (`crawl_<platform>` on CommentSession). The second half matters more than
    the first: `utils.helpers.platform_for` routes a link by domain, so a platform
    added there — or to the matrix — without writing its reader used to hand every
    unlisted link to the Zhihu parser, reporting whatever came back as that site's
    comments. Now the executor raises `comment.noAdapter`; this test raises earlier,
    while nothing has been crawled.
    """
    from crawlers import CRAWLERS
    from crawlers.comments import CommentSession

    mode = capabilities.mode_for(platform, mode_key)
    if mode.handler == 'comments':
        target = getattr(CommentSession, f'crawl_{platform}', None)
        named = f'CommentSession.crawl_{platform}()'
    else:
        crawler_class = CRAWLERS.get(platform)
        assert crawler_class is not None, f'{platform} is in the matrix but not in the crawler registry'
        target = getattr(crawler_class, mode.handler, None)
        named = f'{crawler_class.__name__}.{mode.handler}()'
    assert callable(target), f'{named} — the matrix points at a handler that does not exist'


# ─── Resume: the stored cursor reaches every handler ────────────────────


@pytest.mark.parametrize('platform,mode_key', _pairs(exclude={'comments'}))
def test_a_resumed_pair_is_handed_the_cursor_the_run_stored(app_module, advancing, stopped_run, platform, mode_key):
    """``resume`` is the executor's own argument, and it is the whole point of 继续.

    Only ``search`` ever had this pinned (``tests/api/test_cookie_expiry.py`` drives a
    fake whose only method is search), so an author or 热榜 crawl that ignored the
    stored position would have re-crawled from item zero on every 继续 — re-paying for
    rows already in the table — and the fast tier would have said nothing. The pair
    list is the matrix's own, not a chosen sample: what keys a position holds is each
    site's business (X identifies a row by its status id, bilibili's board pages by
    the cursor the server sent), so what is asserted here is that the executor hands
    over the stored dict untouched and nothing else.
    """
    mode = capabilities.mode_for(platform, mode_key)
    params = _params_for(platform, mode)
    node = {'id': 'node-1', 'type': 'source', 'title': '采集', 'params': params, 'platform': platform}
    ctx = {
        'store': stopped_run,
        'run_id': 'r-dispatch',
        'resume': True,
        'fingerprints': {'node-1': 'fp-node'},
        'skipped_seen': {},
    }

    rows = app_module._execute_source_node(node, headless=True, ctx=ctx)

    assert rows, f'{platform}/{mode_key} produced nothing, so the cursor hand-off below proves nothing'
    assert len(advancing) == 1, f'{platform}/{mode_key} reached {len(advancing)} crawler methods: {advancing}'
    called, kwargs = advancing[0]
    assert called == mode.handler, f'{platform}/{mode_key} must run {mode.handler}(), ran {called}()'
    assert kwargs.get('resume') == _STORED_CURSOR, (
        f'{platform}/{mode_key} got resume={kwargs.get("resume")!r}, not the stored position '
        f'{_STORED_CURSOR!r} — 继续 would crawl this from the start'
    )
    # The user's own arguments still arrive beside it: a resume branch that rebuilt
    # the call would pass a "resume reaches the handler" check and still crawl the
    # wrong thing.
    for key, value in capabilities.crawl_kwargs(mode, params).items():
        assert kwargs[key] == value, f'{platform}/{mode_key}: {key} arrived as {kwargs[key]!r}, not {value!r}'
    # …and the position this attempt reached is stored for the NEXT one. Counting on
    # from 42 is the visible proof the handler really started there.
    assert stopped_run.get_cursor('r-dispatch', 'node-1') == {
        'item_index': _STORED_CURSOR['item_index'] + len(rows),
        'done': len(rows),
    }, f'{platform}/{mode_key} did not write its position back'
    assert stopped_run.row_count('r-dispatch', 'node-1') == len(rows)


# ─── The chosen option, not the first one ──────────────────────────────


def _select_cases():
    """(platform, mode, field, option value) for every option of every select the
    matrix hands to a crawler method.

    Enumerated from the matrix rather than written out, because the point is that
    *none* of them may be replaced on the way to the crawler — and a select added to
    a mode tomorrow has to be walked by this test without anyone remembering to add
    a case. ``format`` is deliberately absent: it is a FILE_FIELDS entry the
    executor reads for itself, never an argument of the crawl.
    """
    out = []
    for cap in capabilities.CAPABILITIES:
        for mode in cap.modes:
            if mode.handler == 'comments':
                continue
            for field in capabilities.crawler_fields(mode):
                for value, _label in field.options:
                    out.append(
                        pytest.param(
                            cap.platform,
                            mode.key,
                            field.key,
                            value,
                            id=f'{cap.platform}-{mode.key}-{field.key}={value}',
                        )
                    )
    return out


@pytest.mark.parametrize('platform,mode_key,field_key,option', _select_cases())
def test_the_option_the_user_picked_is_the_option_the_crawler_gets(
    app_module, recorder, platform, mode_key, field_key, option
):
    """A select filled by the fake with ``options[0][0]`` tests one option out of two.

    bilibili's 周排行榜 (``board='ranking'``) therefore never reached the executor
    anywhere in the fast tier: a dispatch that defaulting-rewrote the field, or read
    the field off the mode instead of the node, would have sent 「(popular)」。 The
    measured fact is that the two boards are different questions from the site — one
    is 热门, one is 排行榜 — so losing the choice is losing the crawl.
    """
    mode = capabilities.mode_for(platform, mode_key)
    params = _params_for(platform, mode)
    params[field_key] = option
    node = {'id': 'node-1', 'type': 'source', 'title': '采集', 'params': params, 'platform': platform}

    rows = app_module._execute_source_node(node, headless=True, ctx=None)

    assert rows, f'{platform}/{mode_key} produced nothing, so the argument below proves nothing'
    assert len(recorder) == 1, f'{platform}/{mode_key} reached {len(recorder)} crawler methods: {recorder}'
    called, kwargs = recorder[0]
    assert called == mode.handler, f'{platform}/{mode_key} must run {mode.handler}(), ran {called}()'
    assert field_key in kwargs, f'{platform}/{mode_key} lost {field_key} at the executor'
    assert kwargs[field_key] == option, (
        f'{platform}/{mode_key} sent {field_key}={kwargs[field_key]!r}, not the chosen {option!r}'
    )
    for key, value in capabilities.crawl_kwargs(mode, params).items():
        assert kwargs[key] == value, f'{platform}/{mode_key}: {key} arrived as {kwargs[key]!r}, not {value!r}'


# ─── A required field that arrives empty is a crawl nobody asked for ────


def _required_cases():
    """(platform, mode, field) for every required field of every crawler-mode."""
    out = []
    for cap in capabilities.CAPABILITIES:
        for mode in cap.modes:
            if mode.handler == 'comments':
                continue
            for field in mode.fields:
                if field.required:
                    out.append(
                        pytest.param(cap.platform, mode.key, field.key, id=f'{cap.platform}-{mode.key}-{field.key}')
                    )
    return out


@pytest.mark.parametrize('platform,mode_key,field_key', _required_cases())
def test_a_required_field_never_arrives_empty(app_module, recorder, platform, mode_key, field_key):
    """``required`` has to survive the trip, not just the panel.

    The fake handed every field whatever ``_SAMPLES`` happened to hold and nothing
    otherwise, so an author platform added to the matrix without a row there would
    have dispatched ``author=''`` — the same nothing a user gets told they may not
    submit — and every test here stayed green. ``mode_for``'s fallback makes that
    worse, not better: a node with no author still runs the author method. What is
    measured is therefore the value AT THE CRAWLER, and the pair list is derived from
    the matrix so the next required field is covered without an edit.
    """
    mode = capabilities.mode_for(platform, mode_key)
    params = _params_for(platform, mode)
    node = {'id': 'node-1', 'type': 'source', 'title': '采集', 'params': params, 'platform': platform}

    rows = app_module._execute_source_node(node, headless=True, ctx=None)

    assert rows, f'{platform}/{mode_key} produced nothing, so the argument below proves nothing'
    assert len(recorder) == 1, f'{platform}/{mode_key} reached {len(recorder)} crawler methods: {recorder}'
    called, kwargs = recorder[0]
    assert called == mode.handler, f'{platform}/{mode_key} must run {mode.handler}(), ran {called}()'
    value = kwargs.get(field_key)
    assert value not in (None, '', [], {}), (
        f'{platform}/{mode_key} dispatched the required {field_key} as {value!r} — '
        'the sample table has no value for it, so nothing could have been crawled'
    )
    if isinstance(value, str):
        assert value.strip(), f'{platform}/{mode_key} dispatched {field_key} as blank whitespace'
    if field_key == 'author':
        assert 'keyword' not in kwargs, f'{platform}/{mode_key} also carried a keyword: {kwargs}'


# ─── The two ways a 热榜 mode differs from its own name ────────────────


def _hot_modes(with_board: bool):
    """Every ``hot`` mode, split by whether the site really offers a choice of board.

    Split from the declaration rather than from a hard-coded pair list, because the
    two halves below assert different things about the SAME partition: if a mode
    moved between them the counts here would say so before any dispatch assertion
    quietly stopped applying to it.
    """
    out = []
    for cap in capabilities.CAPABILITIES:
        for mode in cap.modes:
            if mode.handler != 'hot':
                continue
            if any(field.key == 'board' for field in mode.fields) is not with_board:
                continue
            out.append(pytest.param(cap.platform, mode.key, id=f'{cap.platform}-{mode.key}'))
    return out


def test_only_one_site_actually_publishes_more_than_one_board():
    """``board`` is a choice, so it may exist only where the site has two answers.

    Measured: bilibili serves 热门 and 排行榜 out of one endpoint shape, while zhihu's
    ``hot-lists/total``, weibo's ``ajax/side/hotSearch`` and douyin's
    ``hot/search/list`` each publish exactly one list. Offering a control that changes
    nothing is the harm — the handler would
    carry a parameter it cannot honour, and a node saved under the other value would
    look like it asked for something it never did. ``crawl_kwargs`` is the answer the
    crawler is actually called with, so that — not the field tuple — is what has to
    come back without the key.
    """
    hot_with_board = {
        (cap.platform, mode.key)
        for cap in capabilities.CAPABILITIES
        for mode in cap.modes
        if (mode.handler == 'hot' and any(field.key == 'board' for field in mode.fields))
    }
    hot_without_board = {
        (cap.platform, mode.key)
        for cap in capabilities.CAPABILITIES
        for mode in cap.modes
        if (mode.handler == 'hot' and not any(field.key == 'board' for field in mode.fields))
    }
    assert hot_with_board == {('bilibili', 'hot')}, hot_with_board
    assert hot_without_board == {('weibo', 'hot'), ('zhihu', 'hot'), ('douyin', 'hot')}, hot_without_board
    # The whole grid: no mode besides bilibili's carries a board, hot or otherwise,
    # so nothing else can smuggle one into a call.
    declaring = [
        f'{cap.platform}/{mode.key}'
        for cap in capabilities.CAPABILITIES
        for mode in cap.modes
        if any(field.key == 'board' for field in mode.fields)
    ]
    assert declaring == ['bilibili/hot'], declaring

    for platform, mode_key in sorted(hot_without_board):
        mode = capabilities.mode_for(platform, mode_key)
        kwargs = capabilities.crawl_kwargs(mode, capabilities.declared_defaults(platform))
        assert 'board' not in kwargs, f'{platform}/{mode_key} is called with a board it cannot honour: {kwargs}'
        assert kwargs, f'{platform}/{mode_key} declares no crawler argument at all'


@pytest.mark.parametrize('platform,mode_key', _hot_modes(with_board=False))
def test_a_board_the_site_never_offered_is_not_sent_even_from_a_stale_node(app_module, recorder, platform, mode_key):
    """The argument is not merely absent from the matrix — it must not leak in.

    A canvas saved while its node still carried ``board`` (an old file, or one copied
    from a bilibili source) must not hand weibo or zhihu a choice they never
    published. The dispatch test above only ever feeds the executor parameters the
    matrix declared, so without this case an implementation that echoed any stray
    ``params['board']`` straight into the call would have looked correct.
    """
    mode = capabilities.mode_for(platform, mode_key)
    params = _params_for(platform, mode)
    params['board'] = 'ranking'
    node = {'id': 'node-1', 'type': 'source', 'title': '热榜', 'params': params, 'platform': platform}

    rows = app_module._execute_source_node(node, headless=True, ctx=None)

    assert rows, f'{platform}/{mode_key} produced nothing, so the argument list below proves nothing'
    assert len(recorder) == 1, f'{platform}/{mode_key} reached {len(recorder)} crawler methods: {recorder}'
    called, kwargs = recorder[0]
    assert called == mode.handler, f'{platform}/{mode_key} must run {mode.handler}(), ran {called}()'
    assert 'board' not in kwargs, f'{platform}/{mode_key} has no board to choose: {kwargs}'
    expected = capabilities.crawl_kwargs(mode, params)
    assert 'board' not in expected, f'the matrix itself declares a board for {platform}/{mode_key}'
    assert set(kwargs) - {'resume'} == set(expected), (
        f'{platform}/{mode_key} was called with '
        f'{sorted(set(kwargs) - set(expected) - {"resume"})} the matrix never declared, and lost '
        f'{sorted(set(expected) - set(kwargs))}'
    )


@pytest.mark.parametrize('platform,mode_key', _hot_modes(with_board=True))
def test_the_board_a_site_does_offer_reaches_the_crawler_as_a_value(app_module, recorder, platform, mode_key):
    """The other half of the partition: where a choice exists it is sent, as the
    site's own token rather than the panel's label.

    Pairing the two tests is what makes either failure visible. A dispatch that
    dropped ``board`` for every hot mode would pass the case above (nothing was sent,
    as promised) and fail here.
    """
    mode = capabilities.mode_for(platform, mode_key)
    params = _params_for(platform, mode)
    params['board'] = 'ranking'
    node = {'id': 'node-1', 'type': 'source', 'title': '热榜', 'params': params, 'platform': platform}

    rows = app_module._execute_source_node(node, headless=True, ctx=None)

    assert rows, f'{platform}/{mode_key} produced nothing, so the argument below proves nothing'
    assert len(recorder) == 1, f'{platform}/{mode_key} reached {len(recorder)} crawler methods: {recorder}'
    called, kwargs = recorder[0]
    assert called == mode.handler, f'{platform}/{mode_key} must run {mode.handler}(), ran {called}()'
    assert kwargs.get('board') == 'ranking', f'{platform}/{mode_key} sent board={kwargs.get("board")!r}'


def test_the_cookie_gate_is_asked_for_a_session_from_every_pair_but_two():
    """``needs_session`` decides what a canvas may run without a cookie, so it is
    answered pair by pair — never by "this platform is usually logged in".

    Measured: weibo's ``ajax/side/hotSearch`` gives the same board to an anonymous
    browser, while zhihu's ``hot-lists/total`` answers 401. The gate probes per
    PLATFORM, so one over-broad True refuses a board-only canvas for a cookie the
    site never wanted, and one over-broad False lets a crawl that does need a
    session start without one. This walks the whole grid and reports its size, so a
    newly exempt pair is a decision someone has to make out loud.
    """
    pairs = [(cap.platform, mode.key) for cap in capabilities.CAPABILITIES for mode in cap.modes]
    anonymous = [(platform, key) for platform, key in pairs if not capabilities.needs_session(platform, key)]
    # Two exemptions, for two different measured reasons: weibo's board answers an anonymous
    # browser, while wechat has no session to have at all (it has never been a cookie platform).
    assert anonymous == [('weibo', 'hot'), ('wechat', 'posts')], (
        f'of {len(pairs)} pairs these asked for no session: {anonymous}'
    )
    for platform, key in pairs:
        if (platform, key) in {('weibo', 'hot'), ('wechat', 'posts')}:
            continue
        assert capabilities.needs_session(platform, key) is True, f'{platform}/{key} quietly stopped needing a cookie'


def _crawler_pairs():
    """(platform, mode key) for every crawler-backed (non-comments) mode.

    A ``comments`` mode is out of scope here by construction, not by a skip: it is answered by the
    comment engine, which now honours the run's 无头 choice verbatim just like the source node — the
    old scrolled-panel window forcing was measured unnecessary and removed (pinned in
    ``test_workflow_api.py``'s ``TestACommentNodeHonoursHeadless``). There is no longer a
    ``never_headless`` or ``needs_window`` split to key on — #148 gave a headless Chrome a desktop
    fingerprint and measured every platform serving rows headless, so both executors honour the
    run's choice for all of them. This list is the whole grid that claim covers.
    """
    out = []
    for cap in capabilities.CAPABILITIES:
        for mode in cap.modes:
            if mode.handler == 'comments':
                continue
            out.append(pytest.param(cap.platform, mode.key, id=f'{cap.platform}-{mode.key}'))
    return out


@pytest.fixture
def browser_asked(app_module, recorder, monkeypatch):
    """The recorder again, keeping the arguments the executor handed to ``get_crawler``.

    ``recorder`` throws those away because the tests above only ask which method ran, and
    this test is about exactly one of them: whether the browser was asked to be headless.
    Layered on top of ``recorder`` rather than replacing it, because that fixture owns the
    ``running`` flag restore.
    """
    seen = {}

    def _make(platform, headless=True, **kwargs):
        seen['platform'] = platform
        seen['headless'] = headless
        seen['account'] = kwargs.get('account')
        return _RecordingCrawler()

    monkeypatch.setattr(app_module, 'get_crawler', _make)
    return seen


@pytest.mark.parametrize('platform,mode_key', _crawler_pairs())
def test_every_crawler_mode_is_built_headless_exactly_as_asked(app_module, browser_asked, platform, mode_key):
    """#148: a headless source run stays headless on every platform, douyin and X included.

    Each of these pairs used to be forced into a visible window by a captcha class or a
    per-mode ``needs_window``; both are gone now that headless carries a desktop
    fingerprint. So the executor must build every one with ``headless=True`` when asked —
    a window bought on a guess is exactly what this asserts cannot happen.
    """
    mode = capabilities.mode_for(platform, mode_key)
    node = {
        'id': 'node-1',
        'type': 'source',
        'title': '采集',
        'params': _params_for(platform, mode),
        'platform': platform,
    }

    rows = app_module._execute_source_node(node, headless=True, ctx=None)

    assert rows, f'{platform}/{mode_key} produced nothing, so the flag below proves nothing'
    assert browser_asked['headless'] is True, f'{platform}/{mode_key} opened a window nobody asked for'


def test_the_account_on_the_node_selects_the_browser(app_module, browser_asked):
    """Multi-account at the one seam that matters: the executor reads 账号 off the
    node and hands it to ``get_crawler``, so the crawl runs as that login's cookie and
    that account's profile — while the CRAWL METHOD never sees the parameter (it is
    ``_NOT_ARGS``-excluded, which the kwargs-equality tests above hold honest)."""
    mode = capabilities.mode_for('zhihu', 'posts')
    params = _params_for('zhihu', mode)
    params['account'] = 'work'
    node = {'id': 'node-1', 'type': 'source', 'title': '采集', 'params': params, 'platform': 'zhihu'}
    rows = app_module._execute_source_node(node, headless=True, ctx=None)
    assert rows
    assert browser_asked['account'] == 'work'
    # and the crawl method itself was NOT given the account
    assert 'account' not in capabilities.crawl_kwargs(mode, params)


# ─── Feed: an upstream table column becomes the link list ───────────────


def _patch_session(monkeypatch, seen, fail_url=None):
    """The comment engine's adapter seam: record (adapter, url, limit) per link.

    ``fail_url`` raises once — which is how the resume test below leaves a real
    stored cursor behind instead of pretending one exists.
    """
    import crawlers.comments as comments_module

    class _Session:
        def __init__(self, driver, log=None, **kwargs):
            self._log = log

        def __getattr__(self, name):
            if not name.startswith('crawl_'):
                raise AttributeError(name)

            def crawl(url, limit):
                seen.append((name, url, limit))
                if fail_url == url:
                    raise RuntimeError('wall at the fed article')
                return [{'评论ID': f'c-{url}', '评论内容': '很好', '文章URL': url}], 'ok'

            return crawl

    monkeypatch.setattr(comments_module, 'CommentSession', _Session)


def _comments_feed_node(platform, column='链接'):
    mode = capabilities.mode_for(platform, 'comments')
    params = _params_for(platform, mode)
    params['input_column'] = column
    return {'id': 'node-1', 'type': 'source', 'title': '评论', 'params': params, 'platform': platform}


@pytest.mark.parametrize('platform,mode_key', _pairs(handlers={'comments'}))
def test_a_fed_column_replaces_the_pasted_links(app_module, recorder, monkeypatch, platform, mode_key):
    """The feed is a REPLACEMENT, not an addition: the textarea the user overrode by
    naming a column must never crawl — merging would double-pay an article present in
    both lists and make the positional url_index cursor unrebuildable on 继续."""
    seen = []
    _patch_session(monkeypatch, seen)
    u1 = _SAMPLES[('urls', platform)]
    node = _comments_feed_node(platform)
    node['params']['urls'] = u1 + '-pasted'
    rows_out = app_module._execute_source_node(
        node,
        headless=True,
        ctx=None,
        upstream=[('node-0', [{'链接': u1}, {'链接': u1 + '1'}])],
    )
    crawled = [url for _a, url, _l in seen]
    assert crawled == [u1, u1 + '1'], f'{platform}: fed column did not drive the crawl: {crawled}'
    assert all('-pasted' not in url for url in crawled), f'{platform} still crawled the pasted box'
    assert len(rows_out) == 2, f'{platform}: rows must come back downstream, got {rows_out}'


def test_the_fed_column_hands_the_crawler_its_list_in_order_with_blanks_and_dups(app_module, recorder, monkeypatch):
    """Row order, blanks skipped (counted, not guessed), first-occurrence dedupe.

    The dedupe leg is the resume contract: the comment engine counts links BY POSITION,
    so a duplicate cell would consume a cursor slot and buy the same article twice.
    """
    from i18n import t

    seen = []
    _patch_session(monkeypatch, seen)
    logs = []
    monkeypatch.setattr(app_module, 'add_log', lambda m: logs.append(m))
    u1 = _SAMPLES[('urls', 'zhihu')]
    u2 = u1 + '2'
    node = _comments_feed_node('zhihu')
    node['params']['urls'] = ''
    parent = [{'链接': u1}, {'链接': None}, {'链接': u1}, {'链接': '  '}, {}, {'链接': u2}]
    app_module._execute_source_node(node, headless=True, ctx=None, upstream=[('node-0', parent)])
    assert [url for _a, url, _l in seen] == [u1, u2]
    assert t('source.feed_skipped', n=3) in logs, f'the skipped cells must be said, not silenced: {logs}'


def test_a_missing_fed_column_fails_by_name_not_with_an_empty_table(app_module, recorder, monkeypatch):
    seen = []
    _patch_session(monkeypatch, seen)
    node = _comments_feed_node('zhihu', column='不存在的列')
    node['params']['urls'] = ''
    u1 = _SAMPLES[('urls', 'zhihu')]
    with pytest.raises(ValueError) as exc:
        app_module._execute_source_node(node, headless=True, ctx=None, upstream=[('n0', [{'链接': u1}])])
    assert '不存在的列' in str(exc.value), exc.value
    assert seen == [], 'a refused feed must not crawl anything'


def test_an_all_blank_feed_refuses_rather_than_crawling_nothing(app_module, recorder, monkeypatch):
    seen = []
    _patch_session(monkeypatch, seen)
    node = _comments_feed_node('zhihu')
    node['params']['urls'] = ''
    with pytest.raises(ValueError) as exc:
        app_module._execute_source_node(
            node, headless=True, ctx=None, upstream=[('n0', [{'链接': None}, {'链接': ''}])]
        )
    assert seen == [], exc.value


def test_a_name_wire_alone_is_not_a_feed(app_module, recorder, monkeypatch):
    """``name → source`` is the labelling pattern this canvas has always had.

    A name node produces [] — an empty list is not a table. If "any input" meant
    "a feed", every labelled workflow would suddenly read a column that is not
    there and stop crawling its pasted links.
    """
    seen = []
    _patch_session(monkeypatch, seen)
    u1 = _SAMPLES[('urls', 'zhihu')]
    node = _comments_feed_node('zhihu')
    node['params']['urls'] = u1
    app_module._execute_source_node(node, headless=True, ctx=None, upstream=[('name-1', [])])
    assert [url for _a, url, _l in seen] == [u1], 'the pasted box still rules when the only wire is a name label'


def test_a_fed_wechat_column_reaches_the_article_reader(app_module, recorder):
    """The non-comment half of the feed: wechat's reader takes the LIST itself."""
    mode = capabilities.mode_for('wechat', 'posts')
    params = _params_for('wechat', mode)
    params['input_column'] = '链接'
    params['urls'] = ''
    node = {'id': 'node-1', 'type': 'source', 'title': '文章', 'params': params, 'platform': 'wechat'}
    u1 = _SAMPLES[('urls', 'wechat')]
    rows = app_module._execute_source_node(
        node, headless=True, ctx=None, upstream=[('node-0', [{'链接': u1}, {'链接': u1 + '2'}])]
    )
    assert rows
    called, kwargs = recorder[0]
    assert called == 'search'
    assert kwargs['urls'] == [u1, u1 + '2'], f'the fed column must be the crawler argument: {kwargs["urls"]}'
    assert 'input_column' not in kwargs, "the column name is the executor's, not the crawler's"


def test_a_fed_resume_rebuilds_the_list_and_crawls_only_the_missing_one(app_module, recorder, monkeypatch, tmp_path):
    """The whole point of feeding: 继续 pays only for the articles the wall refused.

    A real RunStore sits under this because the thing under test is the hand-off —
    the list the second attempt rebuilds from the parent rows must be POSITIONALLY
    identical to the first one's, or the stored ``url_index`` skips the wrong link.
    """
    from services.run_store import RunStore

    u1 = _SAMPLES[('urls', 'zhihu')]
    u2 = u1 + '1'
    store = RunStore(str(tmp_path / 'feed-resume.db'))
    store.start_run('r-feed', 'feedwf', 'fp-canvas', headless=True)
    store.begin_node('r-feed', 'node-1', 'source', title='评论', fingerprint='fp-node')
    parent = [{'链接': u1}, {'链接': u2}]

    seen = []
    _patch_session(monkeypatch, seen, fail_url=u2)
    node = _comments_feed_node('zhihu')
    node['params']['urls'] = ''
    ctx = {'store': store, 'run_id': 'r-feed', 'fingerprints': {'node-1': 'fp-node'}, 'skipped_seen': {}}
    with pytest.raises(RuntimeError):
        app_module._execute_source_node(node, headless=True, ctx=ctx, upstream=[('node-0', parent)])
    assert [url for _a, url, _l in seen] == [u1, u2], 'the first attempt must have reached the wall'
    cursor = store.get_cursor('r-feed', 'node-1')
    assert cursor.get('url_index') == 1, f'the interrupted attempt must leave its position: {cursor}'

    # The wall is gone, the rows already paid are still stored, and the parent
    # table is the same — the resume must crawl u2 ONLY.
    seen2 = []
    _patch_session(monkeypatch, seen2)
    rows = app_module._execute_source_node(
        node, headless=True, ctx=dict(ctx, resume=True), upstream=[('node-0', parent)]
    )
    assert [url for _a, url, _l in seen2] == [u2], f'继续 re-paid for a settled article: {seen2}'
    assert len(rows) == 2, f'the resumed table must carry BOTH articles, got {rows}'
