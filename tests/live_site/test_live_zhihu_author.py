"""Live zhihu author crawl — the 某作者的作品 mode against the real profile page.

Visible window only, and no skip branch anywhere in this file: zhihu's day-by-day
headless risk control is a keyword-search problem (documented in the search file), and
turning a refusal into a skip is how a mode stops being tested while the suite stays
green.

The author is **discovered during this run** rather than written down: a ``/people/``
token is a site-internal slug, so a fixture token rots, and a crawl that silently finds
nothing on a dead profile still looks like a passing test. The question page a live
answer belongs to is where those links actually appear (measured: an answer permalink
carries no ``/people/`` link at all).
"""

import re

import pytest

pytestmark = [pytest.mark.live_site, pytest.mark.enable_socket]

KEYWORD = '三亚'
_LINK = re.compile(r'^https://(www\.zhihu\.com/question/\d+/answer/\d+|zhuanlan\.zhihu\.com/p/\d+)')
_PEOPLE = re.compile(r'/people/([^/?#]+)')
_TIME_PREFIXES = ('发布于', '编辑于')


def _discover_author(live_crawler):
    """A profile token taken off a live question page."""
    crawler = live_crawler('zhihu', headless=False)
    try:
        rows = crawler.search(KEYWORD, target_count=3)
        assert rows, 'the search crawl produced nothing, so there is no author to ask about'
        question = next((str(r.get('链接') or '') for r in rows if '/question/' in str(r.get('链接') or '')), '')
        assert question, f'no question-type result to read an author from: {rows}'
        qid = question.split('/question/', 1)[-1].split('/')[0]
        crawler.open(f'https://www.zhihu.com/question/{qid}')
        anchors = crawler.driver.find_elements('css selector', 'a[href*="/people/"]')
        hrefs = [a.get_attribute('href') or '' for a in anchors]
        tokens = [m.group(1) for href in hrefs if (m := _PEOPLE.search(href))]
        tokens = [t for t in tokens if t and t not in ('login', 'signup', 'setting')]
        assert tokens, 'the question page handed over no profile links to crawl'
        return tokens[0]
    finally:
        crawler.close()


def test_an_authors_own_answers_and_articles_are_collected(live_crawler):
    token = _discover_author(live_crawler)
    crawler = live_crawler('zhihu', headless=False)
    try:
        rows = crawler.author(token, target_count=3)
        visited = [crawler._current_url()]
    finally:
        crawler.close()
    assert len(rows) >= 2, f'expected at least 2 rows from {token}, got {len(rows)}'
    for row in rows:
        assert _LINK.match(str(row.get('链接') or '')), f'row without an openable address: {row}'
        assert isinstance(row.get('赞同数'), int), f'赞同数 must be a number: {row}'
        # 发布于 vs 编辑于 are different moments, and zhihu's own dateCreated equals
        # the *edited* one — a bare timestamp in this column would be a wrong figure
        # with a plausible name, so the row keeps whichever label the page shows.
        stamp = str(row.get('发布时间') or '')
        assert not stamp or stamp.startswith(_TIME_PREFIXES), f'发布时间 lost its label: {stamp!r}'
    names = {str(row.get('作者') or '') for row in rows}
    assert names == {next(iter(names))} and next(iter(names)), f'one profile page, several author names: {names}'
    assert any(len(str(row.get('正文') or '')) > 120 for row in rows), (
        'no row is longer than the clamped preview, so 阅读全文 was never expanded in place'
    )
    assert any(f'/people/{token}' in url for url in visited), f'the profile was never opened: {visited}'


def test_a_link_to_the_wrong_zhihu_page_is_refused_without_buying_a_visit(live_crawler):
    """An answer URL in the author field is a paste mistake, not a person: opening
    ``/people/https:`` would 404 and then read as "this author published nothing"."""
    crawler = live_crawler('zhihu', headless=False)
    try:
        with pytest.raises(ValueError):
            crawler.author('https://www.zhihu.com/question/123/answer/456', target_count=2)
        with pytest.raises(ValueError):
            crawler.author('   ', target_count=2)
    finally:
        crawler.close()
