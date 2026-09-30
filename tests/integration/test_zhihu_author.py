"""zhihu's 某作者的作品 mode against a fake driver — the profile contract.

The mode reuses the search page's card readers, so what is genuinely new — and what
this file pins — is the profile's own behaviour, all of it measured 2026-09 on
``/people/<token>/answers``:

* the list is ``.List-item .ContentItem`` and **grows by scrolling** (39 → 79 rows),
  so the walk pages instead of stopping at one screen;
* a row's body is clamped behind 阅读全文 and expanding it is a state change on the
  same document (the search crawler must never click, because a column article's
  card navigates away and detaches every remaining handle);
* the author's name is **not markup** on a profile row — it lives in the row's
  ``data-zop`` tracking payload, which is also where the item's kind and id are;
* the publish time only exists behind a 发布于 / 编辑于 label, and the prefix is kept
  because the two words mean different moments;
* an empty tab is a fact about the account (nobody writes both kinds), not a failure.
"""

import pytest
from selenium.common.exceptions import NoSuchElementException

import crawlers.base as base_module
from crawlers.base import UNDER_TARGET, Crawler
from crawlers.zhihu import ZhihuCrawler

pytestmark = pytest.mark.unit

ANSWER = '2084336655389954504'
ARTICLE = '2084336655389954999'


class Node:
    """A leaf node: text for the readers that ask for it, attributes for the rest."""

    def __init__(self, text='', attrs=None):
        self.text = text
        self._attrs = dict(attrs or {})

    def get_attribute(self, name):
        return self._attrs.get(name, '')


class FakeElement:
    """A profile row: text by selector, plus the attributes the reader asks for."""

    def __init__(self, texts=None, zop='', buttons=(), hrefs=None, time_text=''):
        self.texts = dict(texts or {})
        self.zop = zop
        self.buttons = list(buttons)
        self.hrefs = dict(hrefs or {})
        self.time_text = time_text

    def find_element(self, by, selector):
        if selector in self.hrefs:
            return Node(self.texts.get(selector, ''), {'href': self.hrefs[selector]})
        if selector in self.texts:
            return Node(self.texts[selector])
        if selector in ('.ContentItem-time', '.ContentItem-footer time', 'time') and self.time_text:
            return Node(self.time_text, {'title': self.time_text})
        # The readers probe several selectors and catch this one; a different
        # exception would escape them and the test would measure the fake instead.
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        if selector in ('.ContentItem-actions button', '.ContentItem-actions a'):
            return [Node(label) for label in self.buttons]
        if selector == 'a[href]':
            return [Node('', {'href': href}) for href in self.hrefs.values() if href]
        return []

    def get_attribute(self, name):
        if name == 'data-zop':
            return self.zop
        if name == 'class':
            return 'ContentItem AnswerItem'
        return ''


def answer_row(index=1, title='老默为什么偏要杀老李', body='下过工地的人都知道。'):
    return FakeElement(
        texts={
            '.ContentItem-title a': title,
            '.RichContent-inner .RichText': body,
            '.VoteButton': f'赞同 {100 + index}',
        },
        zop=f'{{"authorName":"Zeta","itemId":"{ANSWER}","title":"{title}","type":"answer","questionId":"581727017"}}',
        buttons=[f'赞同 {100 + index}', f'{index} 条评论'],
        hrefs={'.ContentItem-title a': f'https://www.zhihu.com/question/581727017/answer/{ANSWER}'},
        time_text='编辑于2026-09-18 17:43',
    )


def article_row():
    return FakeElement(
        texts={
            '.ContentItem-title a': '三亚过冬清单',
            '.RichContent-inner .RichText': '海水温度舒适。',
            '.VoteButton': '赞同 7',
        },
        zop=f'{{"authorName":"Zeta","itemId":"{ARTICLE}","title":"三亚过冬清单","type":"article"}}',
        buttons=['赞同 7', '添加评论'],
        hrefs={'.ContentItem-title a': f'https://zhuanlan.zhihu.com/p/{ARTICLE}'},
        time_text='发布于2026-09-11 09:20',
    )


class FakeDriver:
    """Serves the profile tabs, and grows the answers list once per scroll round.

    ``meta`` carries the profile page's own self-published totals (the ``zhihu:answerCount`` /
    ``zhihu:articlesCount`` ``<meta itemprop>`` tags the ``_author_total`` denominator reads); absent
    keys raise so ``_author_total`` returns ``-1`` (no denominator) and the walk keeps the old
    end_reason=None behavior — the shape most existing author tests run under.
    """

    def __init__(self, tabs, grow_after=1, meta=None):
        self.tabs = tabs
        self.visited = []
        self.current_url = 'https://www.zhihu.com/'
        self.scrolls = 0
        self.expansions = 0
        self.grow_after = grow_after
        self._grew = False
        self.meta = dict(meta or {})

    def get(self, url):
        self.visited.append(url)
        self.current_url = url

    def find_element(self, by, selector):
        # ``_author_total`` probes ``meta[itemprop="zhihu:answerCount"]`` etc. Serve them from the
        # optional meta map; anything absent raises so the caller falls through to ``-1`` (no denominator).
        if selector.startswith('meta[itemprop="') and selector.endswith('"]'):
            prop = selector[len('meta[itemprop="') : -2]
            if prop in self.meta:
                return Node(text='', attrs={'content': str(self.meta[prop])})
        raise KeyError(selector)

    def _rows(self):
        tab = self.current_url.rsplit('/', 1)[-1]
        rows = list(self.tabs.get(tab, []))
        if tab == 'answers' and self._grew:
            rows = rows + list(self.tabs.get('grown', []))
        return rows

    def find_elements(self, by, selector):
        if selector == ZhihuCrawler.PROFILE_ITEM:
            return self._rows()
        return []

    def execute_script(self, script, *args):
        if 'scrollBy' in script or 'scroll' in script:
            self.scrolls += 1
            if self.scrolls >= self.grow_after:
                self._grew = True
            return None
        if '阅读全文' in script:
            self.expansions += 1
            return 1
        if 'innerText' in script and args:
            return getattr(args[0], 'text', '')
        return None

    def quit(self):
        pass


@pytest.fixture
def make_crawler(monkeypatch):
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)

    def _make(driver):
        def fake_create(self, *args, **kwargs):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        return ZhihuCrawler(headless=True)

    return _make


class TestAuthorWalk:
    def test_the_profile_is_entered_through_the_token_it_was_given(self, make_crawler):
        driver = FakeDriver({'answers': [answer_row()], 'posts': []})
        crawler = make_crawler(driver)
        rows = crawler.author('https://www.zhihu.com/people/zshu-83/answers', target_count=1)
        assert rows and driver.visited[0] == 'https://www.zhihu.com/people/zshu-83/answers'

    def test_the_author_name_comes_from_the_rows_own_payload(self, make_crawler):
        """A profile row has no 「作者名：」 prefix in its text, so the search reader's
        author rule returns nothing here — the row's own tracking payload is the only
        place the name is data rather than markup."""
        crawler = make_crawler(FakeDriver({'answers': [answer_row()], 'posts': []}))
        row = crawler.author('zshu-83', target_count=1)[0]
        assert row['作者'] == 'Zeta' and row['分类'] == '回答'

    def test_a_clamped_row_is_expanded_before_its_body_is_read(self, make_crawler):
        driver = FakeDriver({'answers': [answer_row()], 'posts': []})
        crawler = make_crawler(driver)
        row = crawler.author('zshu-83', target_count=1)[0]
        assert driver.expansions >= 1, 'the row was harvested still clamped'
        assert row['正文'], 'the un-clamped body has to reach the row'

    def test_the_publish_label_is_kept_because_its_prefix_is_the_meaning(self, make_crawler):
        # dateCreated in the page's schema.org block equals the EDITED moment, so
        # storing it under 发布时间 would be a wrong figure in a plausible column.
        crawler = make_crawler(FakeDriver({'answers': [answer_row()], 'posts': []}))
        assert crawler.author('zshu-83', target_count=1)[0]['发布时间'] == '编辑于2026-09-18 17:43'

    def test_both_tabs_are_walked_and_an_empty_one_is_only_logged(self, make_crawler):
        driver = FakeDriver({'answers': [answer_row()], 'posts': [article_row()]})
        crawler = make_crawler(driver)
        rows = crawler.author('@zshu-83', target_count=5)
        assert [row['链接'] for row in rows] == [
            f'https://www.zhihu.com/question/581727017/answer/{ANSWER}',
            f'https://zhuanlan.zhihu.com/p/{ARTICLE}',
        ]
        assert 'https://www.zhihu.com/people/zshu-83/posts' in driver.visited

    def test_an_account_that_published_nothing_on_both_tabs_is_a_zero_not_an_error(self, make_crawler):
        crawler = make_crawler(FakeDriver({'answers': [], 'posts': []}))
        assert crawler.author('zshu-83', target_count=5) == []

    # ─── U1: the profile's own answerCount/articlesCount metas are the denominator ───

    def test_a_walk_short_of_the_authors_own_total_is_convicted(self, make_crawler):
        # The author published 661 answers + 47 articles (per the profile's own <meta> tags); the walk
        # stalled at one row with no 「没有更多」 marker. Without the total this is the thin/deep ambiguity
        # #6 warns about — WITH it, the site itself says there are 708 posts and we held 1, so convict.
        driver = FakeDriver(
            {'answers': [answer_row()], 'posts': []},
            meta={'zhihu:answerCount': '661', 'zhihu:articlesCount': '47'},
        )
        crawler = make_crawler(driver)
        rows = crawler.author('zshu-83', target_count=50)
        assert len(rows) < 50, 'premise: the walk came back short of the ask'
        assert crawler.end_reason == UNDER_TARGET, (
            f'1 of a self-reported 708 posts is a proven under-collect, not a clean settle: {crawler.end_reason}'
        )

    def test_a_walk_that_reached_the_authors_own_total_is_a_licensed_site_end(self, make_crawler):
        # Here the author only has 2 answers + 1 article; the walk collected all three and is still
        # below the 50 ask — but the SITE sized the feed at 3, so the short is attested, settled clean.
        driver = FakeDriver(
            {'answers': [answer_row(1), answer_row(2)], 'posts': [article_row()]},
            meta={'zhihu:answerCount': '2', 'zhihu:articlesCount': '1'},
        )
        crawler = make_crawler(driver)
        rows = crawler.author('zshu-83', target_count=50)
        assert len(rows) == 3, 'premise: all three published posts were read'
        assert crawler.end_reason == 'site_end', crawler.end_reason

    def test_an_unreadable_total_leaves_the_walk_unjudged_not_guilty(self, make_crawler):
        # No metas → total == -1 → "the page did not publish it", NOT "the author has nothing". The walk
        # keeps the old end_reason=None (settle clean) rather than convicting against a fabricated zero.
        driver = FakeDriver({'answers': [answer_row()], 'posts': []})  # meta omitted
        crawler = make_crawler(driver)
        crawler.author('zshu-83', target_count=50)
        assert crawler.end_reason is None, 'a missing denominator is refused, never guessed as 0'

    def test_a_stop_cut_short_is_not_reconvicted_as_under_target(self, make_crawler):
        # 停止 is its own bucket (the executor counts it in ``stopped_node_ids``, not 「采得不足」). A
        # user-pressed Stop flows through walk_feed (no raise, unlike a wall/风控 which _walk_profile_tab
        # refuses at the tab start), so the guard must see may_stop and leave the walk unjudged.
        driver = FakeDriver(
            {'answers': [answer_row()], 'posts': []},
            meta={'zhihu:answerCount': '661', 'zhihu:articlesCount': '47'},
        )
        crawler = make_crawler(driver)
        crawler.may_stop = lambda: True
        crawler.author('zshu-83', target_count=50)
        assert crawler.end_reason is None, 'a 停止 cut short must not be filed UNDER_TARGET'

    def test_the_list_pages_by_scrolling_rather_than_stopping_at_one_screen(self, make_crawler):
        driver = FakeDriver({'answers': [answer_row(1)], 'grown': [answer_row(2)], 'posts': []})
        crawler = make_crawler(driver)
        rows = crawler.author('zshu-83', target_count=2)
        assert len(rows) == 2, f'the walk stopped after one screen: {len(rows)} rows'
        assert driver.scrolls >= 1

    def test_the_cursor_names_the_author_and_the_tab_it_was_reading(self, make_crawler):
        marked = []
        driver = FakeDriver({'answers': [answer_row()], 'posts': []})
        crawler = make_crawler(driver)
        crawler.set_cursor_sink(marked.append)
        crawler.set_sink(lambda row: True)
        crawler.author('zshu-83', target_count=1)
        assert marked[-1]['author'] == 'zshu-83'
        assert marked[-1]['tab'] in ('answers', 'posts')
        assert marked[-1]['done'] >= 1
