"""Live Weibo author crawl — the 某作者的作品 mode against the mymblog endpoint.

The uid is **discovered during this run** from a real keyword search's 用户链接 (a
written-down uid rots, and a home timeline answering 200 with the same envelope is
exactly what the anchor check defends against). The endpoint is read from inside the
author's loaded profile page with the browser's own session — the shape that answers.

What is proven is the mode's two foundations and the tier's refusal contract:
* delivered rows → every one belongs to a real author the search named, the walk's
  cursor names that uid, ids are disjoint, and a row speaks the search mode's columns;
* a refusal the crawler NAMES (the per-session 403 throttle, or a session bounced to
  login) is the site's honest answer and passes — the walk said which way it died;
* an empty that names NOTHING is the silent shape this tier exists to catch and fails.

No skip, no xfail: the endpoint's mood is a fact the test reads off the crawler, and a
search that yielded an author link is the same precondition every author case demands.
The endpoint is throttle-prone on one account (docs), so this case is deliberately
OUTSIDE ``live_quick``: the quick tier would spend an author burst every run for an
answer that depends on the session's mood; the acceptance pass already pays it.
"""

import pytest

from crawlers.weibo import weibo_uid

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket]

KEYWORD = '人工智能'


def _discover_uid(live_crawler):
    """The numeric uid of an author the keyword search itself returned.

    Reuses the crawler's own ``weibo_uid`` (the search row is ``weibo.com/<uid>?refer_flag=…``,
    which that parser exists to read) rather than a second, narrower regex here. A search that
    yielded no such link means the crawl stopped working — a real red, not a skip.
    """
    crawler = live_crawler('weibo')
    try:
        rows = crawler.search(KEYWORD, target_count=5) or []
    finally:
        crawler.close()
    assert rows, f'the {KEYWORD} search returned nothing, so there is no author to ask'
    for row in rows:
        uid = weibo_uid(row.get('用户链接'))
        if uid:
            return uid
    pytest.fail(f'no author link with a numeric uid among {len(rows)} live rows: {[r.get("用户链接") for r in rows]}')


def test_one_authors_posts_are_collected_or_the_refusal_is_named(live_crawler):
    uid = _discover_uid(live_crawler)
    crawler = live_crawler('weibo')
    try:
        try:
            rows = crawler.author(uid, target_count=5)
            position = dict(crawler.position)
            refused = None
        except (ValueError, RuntimeError) as refusal:
            rows, position, refused = [], {}, str(refusal)
    finally:
        crawler.close()
    if refused is not None:
        # A named refusal (403 throttle / login bounce) is the site's honest answer.
        assert uid in refused, f'the refusal must name the uid it refused: {refused}'
        return
    assert rows, f'mymblog returned 0 rows for uid {uid} WITHOUT naming a refusal — the silent empty'
    assert position.get('uid') == uid, f'the cursor does not name the author it walked: {position}'
    assert position.get('page', 0) >= 1, f'a walk that produced rows left no page position: {position}'
    for row in rows:
        assert (row.get('正文') or '').strip(), f'an author row without body: {row}'
        assert (row.get('发布者') or '').strip(), f'an author row without the anchor author: {row}'
        assert '/detail/' in str(row['链接']), f'row without a post permalink: {row}'
    ids = [str(r['微博ID']) for r in rows]
    assert len(set(ids)) == len(ids), f'mymblog replayed the same post ids: {ids}'


def test_something_that_is_not_an_author_is_refused(live_crawler):
    crawler = live_crawler('weibo')
    try:
        with pytest.raises(ValueError):
            crawler.author('QPikapikaQ', target_count=2)
        with pytest.raises(ValueError):
            crawler.author('   ', target_count=2)
    finally:
        crawler.close()
