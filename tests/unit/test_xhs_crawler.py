"""Xiaohongshu's navigations, and what a driver that never settles has to do.

Measured failure, twice in one hour on the same tier and the same file
(``tests/live_site/test_live_xiaohongshu.py``): the crawl came back red with
``TimeoutException: Timed out receiving message from renderer: -0.001`` raised out of a
bare ``self.driver.get(url)`` — the search page's first navigation, and once the note
page's. The message is the point: the document was still building, which is the exact
state this crawler already answers honestly with ``crawl.xhs.page_timeout`` (keep polling,
and zero cards is a legitimate outcome). It never got the chance, because the navigation
itself threw and took the node down with a driver stack trace.

The fix is to enter the page the way every other platform does — through
``Crawler.open``, which survives the timeout, dismisses the site's first-run dialog and
records the request. These tests hold that line with a fake driver, including the two
things ``open`` must not turn into: a slow page is not a wall, and a lost note is not a
failed crawl.
"""

import pytest
from selenium.common.exceptions import NoSuchElementException, TimeoutException

import crawlers.base as base_module
from crawlers.base import UNDER_TARGET, Crawler
from crawlers.xiaohongshu import XiaohongshuCrawler as Xhs
from i18n import t

pytestmark = pytest.mark.unit

SEARCH = 'https://www.xiaohongshu.com/search_result?keyword=%E4%B8%89%E4%BA%9A&type=51'
NOTE = 'https://www.xiaohongshu.com/explore/abcdef?xsec_token=xyz'
RENDERER_TIMEOUT = 'timeout: Timed out receiving message from renderer: -0.001'


class _TextElement:
    """The one shape :meth:`Crawler._node_text` falls back to: an element with text."""

    def __init__(self, text):
        self.text = text


class SlowDriver:
    """A browser whose pages never finish loading, which is a real state on xhs.

    ``get`` raises the driver's own words and ``find_element`` keeps answering the way a
    building document does (``no such element``, not a crash), so nothing here pretends
    the page arrived. ``body_text`` is the refusal xhs serves INSTEAD of a slow grid:
    the search URL stays and the page becomes 安全验证 — measured 2026-09-25 on a
    session the site had stopped trusting mid-run.
    """

    def __init__(self, url=SEARCH, get_error=True, body_text=''):
        self.current_url = url
        self.visited = []
        self.get_error = get_error
        self.body_text = body_text

    def get(self, url):
        self.visited.append(url)
        # A renderer timeout means the document never swapped: the address bar keeps
        # showing whatever was there before. Re-modelling that is the whole point of
        # the stuck-on-new-tab case below — the real measured browser stayed on
        # ``chrome://new-tab-page`` while ``get`` was already throwing.
        if not self.get_error:
            self.current_url = url
        if self.get_error:
            raise TimeoutException(RENDERER_TIMEOUT)

    def find_element(self, by, selector):
        if selector == 'body' and self.body_text:
            return _TextElement(self.body_text)
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        return []

    def execute_script(self, script, *args):
        # A real page answers innerText here, and a refusal page has to be able to hand
        # over ITS text: ``_node_text`` only falls back to ``element.text`` when the
        # script throws, so a script that returns nothing would show the wall
        # classifier a blank page and hide the very refusal this fake is built to prove.
        for arg in args:
            text = getattr(arg, 'text', None)
            if text:
                return text
        return ''

    def quit(self):
        pass


class _GridCard:
    """One search-grid card, in the shape ``_harvest_cards`` reads: a tokenised link, title, author, like."""

    def __init__(self, link, title='标题', author='作者', like='5'):
        self._kids = {
            'a.cover': _TextElement(''),  # present so ``.cover`` resolves; the href is on the child below
            '.footer .title': _TextElement(title),
            '.author .name': _TextElement(author),
            '.like-wrapper .count': _TextElement(like),
        }
        self._kids['a.cover'] = _LinkElement(link, title)
        self.link = link

    def find_element(self, by, selector):
        if selector in self._kids:
            return self._kids[selector]
        raise NoSuchElementException(selector)


class _LinkElement(_TextElement):
    """The ``a.cover`` anchor: has text AND an ``href`` (what ``_card_link`` reads)."""

    def __init__(self, href, text=''):
        super().__init__(text)
        self._href = href

    def get_attribute(self, name):
        return self._href if name == 'href' else ''


class GridDriver:
    """A xiaohongshu search grid that actually loads — the counterpart to SlowDriver.

    ``get`` settles (the page arrives), ``find_elements`` hands back the current cards, and ``execute_script``
    returns a node's text so ``_scrape_card`` reads real values. ``cards`` is mutable so a test can hand the
    same note back with a fresh token on the next scroll and watch whether dedupe catches it.
    """

    def __init__(self, cards=None, url=SEARCH):
        self.cards = list(cards or [])
        self.current_url = url
        self.visited = []

    def get(self, url):
        self.visited.append(url)
        self.current_url = url

    def find_element(self, by, selector):
        if selector == 'body':
            return _TextElement('')
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        if selector == Xhs.CARD_SELECTOR:
            return list(self.cards)
        return []

    def execute_script(self, script, *args):
        for arg in args:
            text = getattr(arg, 'text', None)
            if text:
                return text
        return ''

    def quit(self):
        pass


class RecoverDriver:
    """A cold-launch browser whose FIRST navigation never commits, then does.

    The measured ``spins forever until I press Enter`` shape, in BOTH its halves: the
    first ``get`` leaves the window parked on ``chrome://new-tab-page`` AND throws the
    renderer timeout — the document never swapped in, so nothing reached the site. The
    second ``get`` — the re-drive :meth:`Crawler.open` now issues — commits the search
    page without throwing, exactly what a manual Enter does. ``body_text`` after the
    commit is ordinary grid chrome, not a wall, so the crawl continues rather than
    latching a false 风控 off a page the browser wrote for itself.
    """

    def __init__(self, commit_after=1):
        self.current_url = 'chrome://new-tab-page/'
        self.visited = []
        self.commit_after = commit_after

    def get(self, url):
        self.visited.append(url)
        # A navigation that never committed keeps the address bar on the previous page
        # and raises the driver's own renderer timeout — the shape that used to fall
        # through to ``_plant``/``classify`` as if the site had refused.
        if len(self.visited) <= self.commit_after:
            raise TimeoutException(RENDERER_TIMEOUT)
        self.current_url = url

    def find_element(self, by, selector):
        if selector == 'body' and not self.current_url.startswith('chrome://'):
            return _TextElement('笔记 / 最热 / 最新')
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        return []

    def execute_script(self, script, *args):
        for arg in args:
            text = getattr(arg, 'text', None)
            if text:
                return text
        return ''

    def quit(self):
        pass


class _NoteDriver:
    """A browser for the note-detail seam: ``get`` commits the URL, ``body`` hands back its text.

    The detail page's identity is what the body says — a stripped/expired ``xsec_token`` swaps it
    for 安全验证, so the whole question Fix B asks (is this link dead, or the session?) is answered
    from the page text the classifier reads, without a real tab.
    """

    def __init__(self, url=NOTE, body=''):
        self.current_url = url
        self.body = body
        self.visited = []

    def get(self, url):
        self.visited.append(url)
        self.current_url = url

    def find_element(self, by, selector):
        if selector == 'body':
            return _TextElement(self.body)
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        return []

    def execute_script(self, script, *args):
        for arg in args:
            text = getattr(arg, 'text', None)
            if text:
                return text
        return ''

    def quit(self):
        pass


class RecyclingGridDriver:
    """A virtualised feed: a FLAT number of mounted cards whose identities rotate on scroll.

    This is what a real xiaohongshu search does (measured 2026-09-29: the count held at ~8
    while new 笔记ID scrolled in and old ones left the DOM). The point of the fake is that the
    mounted COUNT never grows, so a walk that pages on ``_card_count`` growth reads one screen
    and calls it the bottom — while a walk that pages on distinct-note growth keeps collecting.
    """

    def __init__(self, notes=None, page=8, url=SEARCH):
        self.notes = list(notes or [])
        self.page = page
        self.window_start = 0
        self.current_url = url
        self.visited = []
        self.max_mounted = 0

    def get(self, url):
        self.visited.append(url)
        self.current_url = url

    def advance(self):
        """One ``scroll_down``: the feed fetches the next batch, the DOM size holds steady."""
        if self.window_start + self.page < len(self.notes):
            self.window_start += self.page

    def find_element(self, by, selector):
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        if selector == Xhs.CARD_SELECTOR:
            window = self.notes[self.window_start : self.window_start + self.page]
            self.max_mounted = max(self.max_mounted, len(window))
            return [_GridCard(u) for u in window]
        return []

    def execute_script(self, script, *args):
        for arg in args:
            text = getattr(arg, 'text', None)
            if text:
                return text
        return ''

    def quit(self):
        pass


@pytest.fixture
def make_crawler(monkeypatch):
    """Build a real :class:`Xhs` over a fake driver, with every wait instant."""
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)

    def _make(driver_cls=SlowDriver, **driver_attrs):
        driver = driver_cls(**driver_attrs)

        def fake_create(self, *args, **kwargs):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        crawler = Xhs(headless=True)
        return crawler, driver

    return _make


@pytest.fixture
def make_grid(monkeypatch):
    """A real :class:`Xhs` over a settling, card-yielding grid driver (the success path)."""
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)

    def _make(cards=None):
        driver = GridDriver(cards)

        def fake_create(self, *args, **kwargs):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        crawler = Xhs(headless=True)
        # The note detail is a separate navigation (a second tab); it is not what these tests are about,
        # so it is stubbed to the card's own scrape and the seam under test is the dedupe + cursor.
        crawler._read_note = lambda *a, **k: {}
        return crawler

    return _make


class TestSearchNavigation:
    def test_a_renderer_timeout_is_the_pages_own_answer_not_a_crash(self, make_crawler, caplog):
        crawler, _driver = make_crawler()
        with caplog.at_level('INFO'):
            rows = crawler.search('三亚', target_count=3)
        assert rows == [], 'a page that never settled cannot have produced notes'
        assert t('crawl.xhs.page_timeout') in [r.getMessage() for r in caplog.records], (
            'the crawl must say the page did not answer, in its own words'
        )

    def test_the_navigation_that_threw_is_still_paid_for(self, make_crawler):
        # ``requests`` is the cost ledger a mode's promise is tested against, and the
        # request reached the site — dropping it here would let a crawl look cheaper
        # than it was.
        crawler, driver = make_crawler()
        crawler.search('三亚', target_count=1)
        assert crawler.requests == driver.visited
        assert crawler.requests and '/search_result?keyword=' in crawler.requests[0]

    def test_a_slow_page_is_not_reported_as_a_dead_cookie(self, make_crawler):
        # The whole reason ``open`` judges only a persisted refusal: a search grid that
        # has not rendered is an empty document, not a login form, and the second verdict
        # would send the user off to re-save a session that works.
        crawler, _driver = make_crawler()
        crawler.search('三亚', target_count=1)
        assert crawler.login_wall is False


class TestRiskControlStopsTheCrawl:
    """xhs walls a replayed session with a 风控 page, not a login redirect (docs red line).

    That refusal set ``risk_blocked`` but the search gate only tested ``check_login_wall``
    (verdict == 'login'), so the crawl fell through, scrolled a zero-card grid, and filed an
    empty table behind a ``page_timeout`` line — a silent "found nothing" that read as a
    finished crawl for a keyword that plainly has notes. The gate now stops on any refusal,
    the same rule zhihu and douyin already enforce.
    """

    def test_a_risk_control_answer_stops_the_walk_and_names_itself(self, make_crawler, caplog):
        crawler, _driver = make_crawler(body_text='安全验证，请完成验证后继续浏览')
        with caplog.at_level('INFO'):
            rows = crawler.search('三亚', target_count=3)
        assert rows == [], 'a refused page has no notes to file'
        assert crawler.risk_blocked is True, 'the refusal must be named as risk control, not swallowed'
        assert crawler.login_wall is False, 'a flagged session is not a dead cookie — the fix is to wait'
        messages = [r.getMessage() for r in caplog.records]
        assert t('crawl.xhs.page_timeout') not in messages, (
            'a named refusal must return at the gate, not fall through to the timeout-and-scroll '
            'path that produced the silent empty table'
        )

    def test_a_browser_that_never_left_its_own_page_is_a_named_refusal(self, make_crawler, caplog):
        """The 2026-09-25 visible-window shape: ``get`` threw mid-navigation and the
        address bar still reads chrome://new-tab-page — the site was never reached, so
        'ok' there would file an empty grid as a result. The internal page now classifies
        as a refusal the search gate stops on.
        """
        crawler, driver = make_crawler(url='chrome://new-tab-page/')
        crawler.search('三亚', target_count=3)
        assert crawler.risk_blocked is True, 'a browser parked on its own page never arrived'
        assert crawler.login_wall is False, 'nothing asked for a login; the user must not be sent to re-save a cookie'
        # The re-drive is BOUNDED: exactly ``NAV_RETRY`` extra attempts, no more. A loop
        # that kept driving while parked (``while not arrived``) would pass the two
        # assertions above just as happily and burn a browser on a dead session forever.
        assert len(driver.visited) == Crawler.NAV_RETRY + 1, 'the retry must stop at its bound, not spin'

    def test_the_parked_page_is_redriven_before_it_is_called_a_wall(self, make_crawler):
        """A first navigation that never committed is a launch hiccup, not 风控.

        The user's window: it opened on an empty spinning address bar (browser still on
        ``chrome://new-tab-page``) and only a manual Enter took it to the page. Reading
        that parked tab as a refusal filed a keyword that plainly has notes behind a false
        风控 line. :meth:`Crawler.open` now re-drives the URL while the browser is on its
        own page, so the committed grid is crawled and no refusal is latched. The commit
        is placed on the LAST allowed re-drive (``commit_after=NAV_RETRY``) so this cell
        fails if the bound is ever lowered below what the measurement supports.
        """
        crawler, driver = make_crawler(driver_cls=RecoverDriver, commit_after=Crawler.NAV_RETRY)
        crawler.search('三亚', target_count=3)
        assert crawler.risk_blocked is False, 'a navigation that committed on the redrive was never refused'
        assert crawler.login_wall is False, 'nothing asked for a login'
        assert crawler.navigation_settled is True, 'the re-drive committed, so the page is not "slow" either'
        assert len(driver.visited) == Crawler.NAV_RETRY + 1, 'exactly the bound of re-drives, no more'
        assert not driver.current_url.startswith('chrome://'), 'the browser reached the site before being judged'


class TestDeadNoteDetail:
    """A note behind 安全验证 is THIS link dead, not the session refused (U55's shape).

    The step-0 probe caught the old behavior: an expired/absent ``xsec_token`` swapped the detail
    page for 安全验证, the crawler scraped it as a blank row (正文 0) whose 标题 was literally the wall
    word, AND the session-wide ``open`` judged it a 风控 and latched ``risk_blocked`` — so one stale
    token could stop the harvest. The fix reads the note with the non-latching :meth:`verdict`, names
    it dead, and keeps the grid card row while the crawl goes on.
    """

    def test_a_walled_note_is_named_dead_and_does_not_abort_the_session(self, make_crawler, caplog):
        crawler, _d = make_crawler(driver_cls=_NoteDriver, url=NOTE, body='安全验证，请完成验证后继续')
        with caplog.at_level('INFO'):
            detail = crawler._scrape_note(NOTE)
        assert detail is None, 'a note behind 安全验证 must not become a blank row'
        assert crawler.risk_blocked is False, (
            'one walled note is not the session refused — the crawl must keep collecting'
        )
        assert crawler.login_wall is False, 'a per-note wall is not a dead cookie either'
        assert t('crawl.xhs.deadNote', url=NOTE) in [r.getMessage() for r in caplog.records], (
            'the dead note must be named, not silently dropped'
        )

    def test_a_healthy_note_is_not_named_dead(self, make_crawler, caplog):
        # No refusal wording on screen → the non-latching guard passes it through (it may still
        # time out in this fake, but it must not be skipped as a *walled* note).
        crawler, _d = make_crawler(driver_cls=_NoteDriver, url=NOTE, body='三亚 五天四晚 攻略 全文')
        with caplog.at_level('INFO'):
            crawler._scrape_note(NOTE)
        assert t('crawl.xhs.deadNote', url=NOTE) not in [r.getMessage() for r in caplog.records], (
            'a note with no refusal on screen must not be skipped as dead'
        )


class TestVirtualisedFeed:
    """The search walk must page on 笔记ID growth, not the mounted card count (U3/U59).

    A real xiaohongshu grid recycles: the DOM holds ~8 cards and scrolling swaps which
    notes they are. A walk keyed on ``_card_count`` growth reads one screen, sees the count
    flat, and calls it the bottom — the silent under-collect (and the DOM-index skip meant
    it then read NOTHING). These pin the opposite: a flat-count feed that keeps handing new
    ids is harvested well past its first screen, and one that keeps handing the SAME ids
    stops without re-emitting a note.
    """

    def _crawler(self, make_crawler, monkeypatch, notes, page=8):
        monkeypatch.setattr('crawlers.xiaohongshu.time.sleep', lambda s: None)
        crawler, driver = make_crawler(driver_cls=RecyclingGridDriver, notes=notes, page=page)
        # ``scroll_down`` drives the fake's window; the detail read and the politeness beat
        # are not this seam — the grid recycle + ``seen`` dedupe is the unit under test.
        crawler.scroll_down = lambda **k: driver.advance()
        crawler._polite_pause = lambda *a, **k: None
        crawler._read_note = lambda *a, **k: {}
        return crawler, driver

    def test_a_recycling_grid_is_walked_past_its_first_screen(self, make_crawler, monkeypatch):
        notes = [f'https://www.xiaohongshu.com/explore/{i:020x}?xsec_token=T' for i in range(1, 30)]
        crawler, driver = self._crawler(make_crawler, monkeypatch, notes, page=8)
        rows = crawler.search('三亚', target_count=20)
        assert len(rows) >= 20, f'a flat-count feed was walked by card count again: only {len(rows)}'
        assert driver.max_mounted == 8, (
            'the feed never mounted past one screen — the walk could not have counted growth'
        )
        ids = [r['笔记ID'] for r in rows]
        assert len(ids) == len(set(ids)), 'a recycling feed must not emit the same note twice'

    def test_a_grid_that_repeats_the_same_notes_stops_without_overcollecting(self, make_crawler, monkeypatch):
        notes = [f'https://www.xiaohongshu.com/explore/{i:020x}?xsec_token=T' for i in range(1, 6)]
        crawler, _driver = self._crawler(make_crawler, monkeypatch, notes, page=8)
        rows = crawler.search('三亚', target_count=50)
        ids = [r['笔记ID'] for r in rows]
        assert ids and len(ids) == len(set(ids)), 'each distinct note once, no more'
        assert len(rows) < 50, 'the walk must stop when scrolling stops bringing new notes'


class TestUnderTargetWiring:
    """§6 U1 migration: xiaohongshu's grid publishes no total and no end marker, so a walk that
    stopped growing below the ask must be CONVICTED (``end_reason == UNDER_TARGET``) rather than
    left ``None`` — which the executor lets settle clean (the not-yet-migrated behaviour this
    migrates away from). But a run the user STOPPED, or one a wall/风控 answered, is settled
    upstream and must NOT be filed ``UNDER_TARGET`` here: that would report 「采得不足」 over
    「你按了停止」 or 风控, the exact mislabels the plan forbids.
    """

    def _short_feed(self, make_crawler, monkeypatch, notes, page=8):
        monkeypatch.setattr('crawlers.xiaohongshu.time.sleep', lambda s: None)
        crawler, driver = make_crawler(driver_cls=RecyclingGridDriver, notes=notes, page=page)
        crawler.scroll_down = lambda **k: driver.advance()
        crawler._polite_pause = lambda *a, **k: None
        crawler._read_note = lambda *a, **k: {}
        return crawler

    def test_a_grid_short_of_target_with_no_attested_end_is_convicted(self, make_crawler, monkeypatch):
        notes = [f'https://www.xiaohongshu.com/explore/{i:020x}?xsec_token=T' for i in range(1, 6)]
        crawler = self._short_feed(make_crawler, monkeypatch, notes)
        rows = crawler.search('三亚', target_count=50)
        assert len(rows) < 50, 'premise: the feed came back short'
        assert crawler.end_reason == UNDER_TARGET, (
            f'a short xhs walk must name itself short, not settle clean: end_reason={crawler.end_reason!r}'
        )
        # The funnel is reported only from numbers the walk actually measured (U2), never invented zeros.
        assert {'scanned', 'kept', 'refused'} <= set(crawler.walk_counts), crawler.walk_counts

    def test_a_walk_that_fills_its_target_is_not_convicted(self, make_crawler, monkeypatch):
        notes = [f'https://www.xiaohongshu.com/explore/{i:020x}?xsec_token=T' for i in range(1, 30)]
        crawler = self._short_feed(make_crawler, monkeypatch, notes)
        rows = crawler.search('三亚', target_count=20)
        assert len(rows) >= 20, 'premise: the feed filled the ask'
        assert crawler.end_reason is None, 'a walk that met its target files no shortfall'

    def test_a_user_stop_is_not_reported_as_under_target(self, make_crawler, monkeypatch):
        notes = [f'https://www.xiaohongshu.com/explore/{i:020x}?xsec_token=T' for i in range(1, 6)]
        crawler = self._short_feed(make_crawler, monkeypatch, notes)
        crawler.may_stop = lambda: True
        crawler.search('三亚', target_count=50)
        assert crawler.end_reason is None, 'a 停止 cut short is its own bucket, never 「采得不足」'

    def test_a_risk_block_is_not_reported_as_under_target(self, make_crawler, monkeypatch):
        notes = [f'https://www.xiaohongshu.com/explore/{i:020x}?xsec_token=T' for i in range(1, 6)]
        crawler = self._short_feed(make_crawler, monkeypatch, notes)
        crawler.risk_blocked = True
        crawler.search('三亚', target_count=50)
        assert crawler.end_reason is None, 'a 风控 short is named 风控 upstream, not double-convicted here'


class TestNoteNavigation:
    def test_a_note_that_never_arrives_costs_its_row_and_not_the_crawl(self, make_crawler, monkeypatch):
        crawler, driver = make_crawler(get_error=False)

        class _Expired:
            def __init__(self, _driver, _timeout):
                pass

            def until(self, _condition):
                raise TimeoutException(RENDERER_TIMEOUT)

        monkeypatch.setattr('crawlers.xiaohongshu.WebDriverWait', _Expired)
        assert crawler._scrape_note(NOTE) is None
        assert crawler.requests == [NOTE], 'the detail visit is one of the crawl requests'


class TestResumeIdentityAndCursor:
    """§6 U5: the search cursor records POSITION, and the resume identity is 笔记ID, not the token link.

    The old code kept a ``links`` list in the cursor and keyed ``seen`` on the tokenised link. Two wrongs
    in one: a note re-promoted with a fresh token was treated as new and re-paid (the token is not the
    identity), and one failed note's link in the cursor meant it was silently skipped on every LATER
    resume — a permanent under-collect with no way back but 重新采集. The fix seeds ``seen`` from the
    stored rows' 笔记ID and keeps the cursor to the card index only.
    """

    ID_A = 'a' * 18
    ID_B = 'b' * 18

    @classmethod
    def _link(cls, note_id, token):
        return f'https://www.xiaohongshu.com/search_result/{note_id}?xsec_token={token}'

    def test_the_search_cursor_holds_position_only_never_a_link_list(self, make_grid):
        crawler = make_grid([_GridCard(self._link(self.ID_A, 't1')), _GridCard(self._link(self.ID_B, 't2'))])
        for card in crawler._mounted_cards():
            row = crawler._note_row(card, set())
            if row is not None:
                crawler._emit_note(row)
        assert crawler.collected() == 2, 'both notes were new and stored'
        position = crawler.position
        assert 'links' not in position, f'the cursor carries a link list again (U5 shape): {position}'
        smuggled = {k: v for k, v in position.items() if isinstance(v, (list, tuple, set))}
        assert not smuggled, f'the cursor stores content, not position (U5): {smuggled}'

    def test_a_repromoted_note_with_a_fresh_token_is_not_re_collected(self, make_grid):
        # The note the previous attempt stored, but handed back on this scroll with a DIFFERENT token.
        crawler = make_grid([])
        crawler.seed([{'笔记ID': self.ID_A, '笔记链接': self._link(self.ID_A, 'OLD'), '标题': 'A'}])
        seen = crawler._collected_ids()
        assert seen == {self.ID_A}, 'the resume skip-set is seeded from stored rows, not the cursor'
        crawler.driver.cards = [_GridCard(self._link(self.ID_A, 'NEW')), _GridCard(self._link(self.ID_B, 'NEW'))]
        for card in crawler._mounted_cards():
            row = crawler._note_row(card, seen)
            if row is not None:
                crawler._emit_note(row)
        ids = [row.get('笔记ID') for row in crawler.results()]
        assert ids.count(self.ID_A) == 1, f'A (new token) was re-collected — the token is not the identity: {ids}'
        assert self.ID_B in ids, 'a genuinely new note still gets collected'
        assert len(ids) == 2, f'expected the stored A plus new B, got {ids}'
