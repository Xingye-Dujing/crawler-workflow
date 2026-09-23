"""X (twitter) crawls against a fake driver — the virtualized-list contract.

The site hands a browser 13-21 ``<article>`` nodes no matter how far it has been
scrolled, while distinct tweets keep flowing through them (measured: 139 unique in
eight scrolls). That single fact decides four things this file pins:

* progress is measured by **rows kept**, so a walk that fell back to counting cards
  would call the timeline exhausted after three scrolls and return one screen;
* the resume point is the **set of status ids**, so a resumed run re-reads the
  current screen and the ledger refuses what it already stored;
* a refusal is loud: a login sheet (headless) or a 403 must raise, because zero
  rows from a blocked session and zero rows from a dead keyword are otherwise the
  same console line;
* one script call reads a card, not a dozen ``find_element`` round trips.

The card payloads are the shapes measured on the live page, including the
``/status/<id>/analytics`` link a promoted card carries.
"""

import pytest

import crawlers.base as base_module
from crawlers.base import Crawler
from crawlers.comments import OK, CommentSession, parse_twitter_replies
from crawlers.twitter import TwitterCrawler
from i18n import t

pytestmark = pytest.mark.unit

TWEET_A = '2102690087062348280'
TWEET_B = '2102690003470184537'
TWEET_C = '2102689852672331971'
GROUP = '5 replies, 18 reposts, 294 likes, 74 bookmarks, 16768 views'


class Card:
    """Stand-in for a Selenium element: identity only, the reader gets the dict."""

    def __init__(self, data):
        self.data = data


def card_data(tweet_id, text='a tweet', user='Lisa\n@devtrotter_fr\n·\n13s', **over):
    data = {
        'text': text,
        'user': user,
        'iso': '2026-09-23T09:22:37.000Z',
        'link': f'/devtrotter_fr/status/{tweet_id}/analytics',
        'tweetId': str(tweet_id),
        'images': [],
        'video': False,
        'quote': False,
        'card': False,
        'poll': False,
        'labels': {'group': GROUP},
    }
    data.update(over)
    return data


class FakeDriver:
    """A virtualized feed: the rendered window holds N cards and rotates its ids.

    ``screens`` is the timeline: each entry is the window the page shows after one
    scroll, so a walk that watches the *count* of cards sees nothing change while a
    walk that watches the ids on screen keeps collecting.
    """

    def __init__(self, screens, body='', url='https://x.com/'):
        self.screens = list(screens)
        self.body = body
        self.current_url = url
        self.visited = []
        self.scrolled = 0
        self.reads = 0
        self.locators = 0
        self.field_lookups = 0
        self.script_timeout = None

    def get(self, url):
        self.visited.append(url)
        self.current_url = url

    def find_element(self, by, selector):
        # The only single-node lookup a timeline walk may make is the ``body`` read
        # that classifies the page. Anything else is a per-field round trip.
        if selector != 'body':
            self.field_lookups += 1
        return type('El', (), {'text': self.body})()

    def find_elements(self, by, selector):
        self.locators += 1
        return self.screens[0] if self.screens else []

    def execute_script(self, script, *args):
        text = script.strip()
        if 'scrollBy' in script:
            self.scrolled += 1
            if len(self.screens) > 1:
                self.screens.pop(0)
            return None
        if text.startswith('var out'):
            # The window read: the ids currently on screen, as one string. It runs
            # inside the page (``document.querySelectorAll``), so unlike a
            # ``find_elements`` call it costs no round trip — hence not counted.
            return ','.join(card.data['tweetId'] for card in (self.screens[0] if self.screens else []))
        if text.startswith('var root'):
            # The card read — the one this harness counts. Classifying the page
            # also runs a script over the ``body`` node, and folding that into
            # ``reads`` would make "one call per card" depend on how many times
            # the crawler looked at the wall.
            self.reads += 1
            return args[0].data
        if len(args) == 1:
            return getattr(args[0], 'text', '') or ''
        return None

    def set_script_timeout(self, seconds):
        self.script_timeout = seconds

    def quit(self):
        pass


def screen(*ids):
    return [Card(card_data(i)) for i in ids]


@pytest.fixture
def make_crawler(monkeypatch):
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)

    def _make(driver):
        def fake_create(self, *args, **kwargs):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        return TwitterCrawler(headless=False)

    return _make


class TestTimelineWalk:
    def test_a_window_that_does_not_grow_still_yields_new_rows(self, make_crawler):
        """The measured shape: three screens, each ~3 cards, ids rotating.

        A walk that watches the card count would stop after the first screen — the
        count never rises — and hand back 3 rows as if the search had ended.
        """
        driver = FakeDriver([screen(TWEET_A, TWEET_B), screen(TWEET_B, TWEET_C), screen(TWEET_C)])
        crawler = make_crawler(driver)
        rows = crawler.search('openai', target_count=3)
        assert [row['推文ID'] for row in rows] == [TWEET_A, TWEET_B, TWEET_C]
        assert driver.scrolled >= 1

    def test_one_script_call_per_card_and_no_locator_storm(self, make_crawler):
        driver = FakeDriver([screen(TWEET_A, TWEET_B)])
        crawler = make_crawler(driver)
        crawler.search('openai', target_count=2)
        assert driver.reads == 2, f'expected one read per card, got {driver.reads}'
        # Two list queries for one screen: waiting for it to mount, then reading it.
        # Twelve per card is the old shape of this crawl and it costs a minute on
        # a 50-row run.
        assert driver.locators <= 3, f'the walk went back to the locators, {driver.locators} queries'
        assert driver.field_lookups == 0, f'a field was scraped by its own locator, {driver.field_lookups} times'

    def test_the_analytics_link_never_becomes_the_rows_permalink(self, make_crawler):
        driver = FakeDriver([screen(TWEET_A)])
        crawler = make_crawler(driver)
        row = crawler.search('openai', target_count=1)[0]
        assert row['链接'] == f'https://x.com/devtrotter_fr/status/{TWEET_A}'

    def test_the_target_stops_the_walk_mid_screen(self, make_crawler):
        driver = FakeDriver([screen(TWEET_A, TWEET_B, TWEET_C)])
        crawler = make_crawler(driver)
        assert len(crawler.search('openai', target_count=2)) == 2

    def test_a_resumed_run_does_not_recollect_what_its_stored_rows_already_hold(self, make_crawler):
        """A resume is handed the rows the previous attempt stored, and that is the
        whole resume point: the second screen re-shows 2102…537, which the crawl
        must skip because it already *has* it — not because an id list said so."""
        driver = FakeDriver([screen(TWEET_A, TWEET_B), screen(TWEET_B, TWEET_C)])
        crawler = make_crawler(driver)
        saved = {'推文ID': TWEET_A, '链接': f'https://x.com/devtrotter_fr/status/{TWEET_A}', '正文': 'x'}
        crawler.seed([saved])
        rows = crawler.search('openai', target_count=5)
        assert [row['推文ID'] for row in rows] == [TWEET_A, TWEET_B, TWEET_C]

    def test_an_old_cursor_holding_an_id_list_is_ignored_not_misread(self, make_crawler):
        """Cursors written before this change carried ``ids``; a run resumed with
        one must still dedupe by the rows it was given rather than by a list that
        no longer reflects what is stored."""
        driver = FakeDriver([screen(TWEET_A, TWEET_B), screen(TWEET_B, TWEET_C)])
        crawler = make_crawler(driver)
        saved = {'推文ID': TWEET_A, '链接': f'https://x.com/devtrotter_fr/status/{TWEET_A}', '正文': 'x'}
        crawler.seed([saved])
        rows = crawler.search('openai', target_count=5, resume={'ids': [TWEET_B]})
        assert [row['推文ID'] for row in rows] == [TWEET_A, TWEET_B, TWEET_C]

    def test_the_cursor_says_which_search_it_was_without_rewriting_the_collected_ids(self, make_crawler):
        marked = []
        driver = FakeDriver([screen(TWEET_A)])
        crawler = make_crawler(driver)
        crawler.set_cursor_sink(marked.append)
        crawler.set_sink(lambda row: True)
        crawler.search('openai', target_count=5)
        assert marked[-1]['keyword'] == 'openai'
        assert marked[-1]['done'] == 1
        assert marked[-1]['scanned'] >= 1
        # The payload the cursor carries must not grow with the crawl: writing the
        # collected id list after every card cost one serialisation of the whole
        # table per row, which is the quadratic cost the rows themselves make
        # unnecessary.
        assert 'ids' not in marked[-1], 'the cursor is a position, not a copy of the result'

    def test_a_login_sheet_is_refused_rather_than_reported_as_no_results(self, make_crawler):
        driver = FakeDriver([], body="See what's happening\nContinue with phone\nForgot password?")
        driver.current_url = 'https://x.com/i/flow/login'
        crawler = make_crawler(driver)
        with pytest.raises(RuntimeError):
            crawler.search('openai', target_count=5)
        assert crawler.login_wall is True

    def test_a_403_page_is_a_refusal_not_an_empty_timeline(self, make_crawler):
        denied = "Access to x.com was denied\nYou don't have authorization to view this page.\nHTTP ERROR 403"
        driver = FakeDriver([], body=denied)
        crawler = make_crawler(driver)
        with pytest.raises(RuntimeError):
            crawler.author('OpenAI', target_count=5)
        assert crawler.risk_blocked is True and crawler.login_wall is False

    def test_an_empty_timeline_without_a_wall_is_a_zero_row_success(self, make_crawler):
        # A keyword nobody posted is a real answer; raising on it would send the
        # user off chasing a session that is fine.
        driver = FakeDriver([[]])
        crawler = make_crawler(driver)
        assert crawler.search('zzzqqq', target_count=5) == []
        assert crawler.login_wall is False

    def test_the_author_mode_uses_the_profile_of_the_handle_it_was_given(self, make_crawler):
        driver = FakeDriver([screen(TWEET_A)])
        crawler = make_crawler(driver)
        rows = crawler.author('@OpenAI', target_count=1)
        assert rows and driver.visited == ['https://x.com/OpenAI']

    def test_an_author_field_that_is_empty_costs_no_browser_time(self, make_crawler):
        driver = FakeDriver([screen(TWEET_A)])
        crawler = make_crawler(driver)
        with pytest.raises(ValueError):
            crawler.author('   ', target_count=5)
        assert driver.visited == []


class TestReplies:
    """``CommentSession.crawl_twitter`` — replies are the same walk, minus the root."""

    @pytest.fixture
    def session_maker(self, monkeypatch):
        monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)

        def _make(driver):
            def fake_create(self, *args, **kwargs):
                self.driver = driver

            monkeypatch.setattr(Crawler, '_create_driver', fake_create)
            crawler = TwitterCrawler(headless=False)
            logs: list[str] = []
            session = CommentSession(crawler.driver, log=logs.append, nap=lambda s: None)
            # Hanging the list off the session keeps every existing call site
            # ``session_maker(driver)`` while letting one test read what the crawl
            # told the console.
            session.logs = logs
            return session

        return _make

    def test_the_root_post_is_not_returned_as_a_reply(self, session_maker):
        root = card_data(TWEET_A, text='the post itself')
        driver = FakeDriver([[Card(root), Card(card_data(TWEET_B, text='first reply'))]])
        session = session_maker(driver)
        rows, status = session.crawl_twitter(f'https://x.com/devtrotter_fr/status/{TWEET_A}', limit=0)
        assert status == OK
        assert [row['评论ID'] for row in rows] == [TWEET_B]
        assert rows[0]['平台'] == 'twitter' and rows[0]['评论内容'] == 'first reply'

    def test_a_reply_page_is_walked_past_its_first_screen(self, session_maker):
        driver = FakeDriver(
            [
                [Card(card_data(TWEET_A, text='root')), Card(card_data(TWEET_B, text='r1'))],
                [Card(card_data(TWEET_A, text='root')), Card(card_data(TWEET_C, text='r2'))],
            ]
        )
        session = session_maker(driver)
        rows, status = session.crawl_twitter(f'https://x.com/devtrotter_fr/status/{TWEET_A}', limit=0)
        assert status == OK and [row['评论ID'] for row in rows] == [TWEET_B, TWEET_C]

    def test_a_link_with_no_status_id_is_dead_not_empty(self, session_maker):
        session = session_maker(FakeDriver([[]]))
        rows, status = session.crawl_twitter('https://x.com/OpenAI', limit=0)
        assert rows == [] and status == 'dead'

    def test_a_refused_reply_page_reports_blocked(self, session_maker):
        driver = FakeDriver([[]], body='Access to x.com was denied HTTP ERROR 403')
        session = session_maker(driver)
        rows, status = session.crawl_twitter(f'https://x.com/a/status/{TWEET_A}', limit=0)
        assert rows == [] and status == 'blocked'

    def test_a_post_that_renders_no_card_at_all_is_dead(self, session_maker):
        # Nothing mounted: the link is stale or the page was intercepted. Saying
        # "no replies" here would send the user off concluding nobody answered.
        driver = FakeDriver([[]])
        session = session_maker(driver)
        url = f'https://x.com/devtrotter_fr/status/{TWEET_A}'
        rows, status = session.crawl_twitter(url, limit=0)
        assert rows == [] and status == 'dead'
        assert t('comment.xNoList', url=url) in session.logs

    def test_a_post_with_its_replies_closed_is_an_empty_answer_not_a_failure(self, session_maker):
        # The permalink renders exactly one card — the post itself. That is the
        # same "nobody answered" the other platforms report, so it must reuse
        # their line rather than inventing a second one.
        driver = FakeDriver([[Card(card_data(TWEET_A, text='the post itself'))]])
        session = session_maker(driver)
        url = f'https://x.com/devtrotter_fr/status/{TWEET_A}'
        rows, status = session.crawl_twitter(url, limit=0)
        assert rows == [] and status == OK
        assert t('comment.commentsClosed', url=url) in session.logs

    def test_the_parser_skips_the_root_it_is_given(self):
        """The pure half, so the exclusion rule is not only tested through a driver."""
        cards = [card_data(TWEET_A), card_data(TWEET_B)]
        rows = parse_twitter_replies(cards, f'https://x.com/a/status/{TWEET_A}', TWEET_A)
        assert [row['评论ID'] for row in rows] == [TWEET_B]
