"""Every (platform, mode) pair of the crawl matrix, driven to its crawler method.

`crawl_capabilities.CAPABILITIES` is the only answer to "what can this platform collect", and 21
pairs ride on it. Until now every fake crawler in the suite defined ``search`` and nothing else, so
the five 「某作者的作品」 modes and the 热榜 mode had never been *dispatched* anywhere: a node that
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
*that* engine with their own links and never touch the crawler. The third test then checks, for all
20 pairs, that the name the matrix points at exists where the executor will look for it.

Everything is offline: the crawler is a scripted recorder, no browser and no network.
"""

import pytest

import crawl_capabilities as capabilities

pytestmark = pytest.mark.api

#: A value that survives each platform's own parser, per field key + platform.
_SAMPLES = {
    ('author', 'zhihu'): 'https://www.zhihu.com/people/abc',
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
