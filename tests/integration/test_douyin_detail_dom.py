"""Real Chrome, local page: which ``/user/`` anchor is allowed to become a row's 作者?

:meth:`crawlers.douyin.DouyinCrawler._driver_facts` reads the creator out of the DOM with a small script,
and the first version of that reader took the **first** bare ``/user/<sec_uid>`` anchor on the document.
On the live site that is not the creator: measured 2026-09-28 (``backend/test_dy_dead_video.py``, payload
``scratchpad/dy_dead_video.json``), the video's own name sits on an anchor inside
``[data-e2e="user-info"]``, while the recommendation rail carries a dozen other sec_uid links — and on a
page still hydrating the header has not mounted, so the rail won and the row stored a stranger's shop
account as its author.

A wrong figure under a plausible column name is the harm this repo refuses elsewhere (there is no 播放数
column for exactly this reason), so the rule is now scoping, and only Chrome can grade a selector:

* the header wins even when a rail anchor comes **first** in document order;
* a page with no header yields ``''`` — no name at all, rather than somebody else's.
"""

import pytest

from crawlers import get_crawler

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

#: Long enough to clear the reader's ``{20,}`` sec_uid shape, so both anchors are candidates and only
#: their container can decide the answer.
HEAD = 'https://www.douyin.com/user/MS4wLjABAAAAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
RAIL = 'https://www.douyin.com/user/MS4wLjABAAAAbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'

PAGE = f"""<!doctype html>
<html><body>
<div data-e2e="related-video">
  <a href="{RAIL}">推荐位路人</a>
  <div>白水鉴心 |  | 粉丝4399获赞341.9万 |  | 关注</div>
</div>
<div data-e2e="user-info">
  <a href="{HEAD}"></a>
  <a href="{HEAD}">真作者</a>
</div>
<div data-e2e="detail-video-info">归墟第十二集\n5.9万</div>
<div data-e2e="detail-video-publish-time">发布时间：2026-08-04 16:32</div>
</body></html>
"""

#: The same document with the header removed: the shape a still-hydrating page presents.
NO_HEADER = PAGE.replace('data-e2e="user-info"', 'data-e2e="gone"')


def _crawler():
    try:
        return get_crawler('douyin', headless=True, use_profile=False)
    except Exception as exc:
        # Only a missing browser is an unavailable tool. This file's own bug (a bad call, a name that does
        # not exist) must not hide behind a skip — that is how a broken pin reads as a tier that declined
        # to answer, and the closure run reports it as green-ish.
        if not any(word in str(exc).lower() for word in ('chrome', 'driver', 'devtools')):
            raise
        pytest.skip(f'Chrome/chromedriver unavailable: {exc}')


@pytest.fixture
def facts():
    """``(crawler, page_loader)`` — one browser for the module, one page load per case."""
    crawler = _crawler()
    try:
        yield crawler
    finally:
        crawler.close()


def _open(crawler, tmp_path, html):
    page = tmp_path / 'douyin-detail.html'
    page.write_text(html, encoding='utf-8')
    crawler.driver.get(page.as_uri())
    return crawler._driver_facts()


def test_the_creator_block_beats_the_recommendation_rail(facts, tmp_path):
    found = _open(facts, tmp_path, PAGE)
    assert found['author'] == '真作者', (
        f'the rail anchor answered for a video somebody else posted: {found["author"]!r}'
    )


def test_a_page_without_its_header_names_nobody(facts, tmp_path):
    """No header is a blank column, not a guess.

    The blank is what the walk's identity gate reads the page as unfinished and refuses; a name lifted
    off the rail would have made the row look complete.
    """
    found = _open(facts, tmp_path, NO_HEADER)
    assert found['author'] == '', f'an author was invented from the rail: {found["author"]!r}'
