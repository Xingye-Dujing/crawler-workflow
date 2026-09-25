import contextlib
import json
import logging
import random
import time
from abc import ABC, abstractmethod

import browser_profiles
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from config import Config
from i18n import t
from settings_store import get_setting

from .engine import feed, popup
from .engine.wall import bounced_to_root, classify

logger = logging.getLogger(__name__)

# Where a crawler has been pushed into a login page instead of the content it
# asked for is decided once, in :mod:`crawlers.engine.wall`; see that module for
# the measured shape of every platform's wall.


def as_index(value, default: int = 0) -> int:
    """A cursor field, coerced. Cursors are read back from JSON and may hold
    anything at all; a bad value must degrade to "start from the beginning"
    rather than crash the crawl that was supposed to save work."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


class CrawlerStopped(BaseException):
    """The user pressed 停止 and this crawl must end, keeping what it already paid for.

    Not an ``Exception`` subclass for one structural reason: this codebase reads a
    dead session, a missing card and a refused page as "keep going without it" in
    about sixty places, nearly all of them ``except Exception`` or
    ``contextlib.suppress(Exception)`` — a stop raised as an ordinary error would be
    swallowed into a silently short table, which is the opposite of what a stop is
    for. As a ``BaseException`` it walks out of every crawl loop unharmed and is
    caught once, by the node runner, which reports 被停止.

    It is also the difference between an honest short table and a dishonest one:
    measured, a killed driver makes an in-page ``fetch`` answer ``ERR …``, and
    ``engine/pagefetch.py`` folds that into "the site sent no more rows".
    """


class ProfileUnavailableError(RuntimeError):
    """The browser was never built because the platform's profile could not be taken.

    Its own type because "a Chrome is not installed" and "Chrome is installed but
    somebody still holds this profile" arrive through the same `Exception` — and the
    live tier answers the first by skipping (nothing to test here) while the second
    MUST stay red: it is this machine failing to serialize its own crawls, and a skip is
    how that becomes invisible.
    """


class Crawler(ABC):
    """Base class for all platform crawlers.

    Streams results instead of accumulating them. A crawl used to build a local
    list and return it at the end, so killing the run at item 900 of 1000 threw
    all 900 away. The runner installs a *sink* before searching, and every item
    is handed to it the moment it is scraped — the sink writes it to disk and
    answers whether it was new. Subclasses therefore call ``emit(item)`` rather
    than ``results.append(item)``, and return ``self.results()``.

    Resumption rests on two things, both owned by the sink:

    - the items already collected (the sink's own store), which also lets
      duplicate rows be dropped instead of re-added;
    - the *cursor* (``mark_position``), which says where the crawl got to —
      which URL of the list, which page, how many items are already in hand.
    """

    domain = ''
    login_url = ''
    # Extra hosts the saved cookies must be planted on before the crawl starts.
    # ``domain`` alone is not enough when a platform serves the crawlable pages
    # from a subdomain that never appears in the saved cookie list (weibo's
    # search lives on s.weibo.com, the cookies on .weibo.com).
    cookie_domains: tuple[str, ...] = ()

    # First-run dialogs this site shows. Empty for most platforms; a platform
    # that has one names it, so the wait for its auto-dismiss is never paid.
    prompts: tuple = ()

    # Whether the crawl needs images to actually load. Reading a URL out of an
    # ``img`` attribute does not, and blocking them is the largest per-navigation
    # saving available on a media-heavy site — so the default is off and a
    # platform that measures a real need opts in.
    needs_images = False

    #: "May this crawl stop?" — installed by the runner, defaulted on the class so a
    #: test double that subclasses Crawler without calling ``__init__`` still answers
    #: it (False) instead of raising AttributeError from inside ``emit``.
    _abort = None

    #: How many readings a suspected wall has to survive before it is believed.
    #: Measured on weibo: a logged-in visit to a search URL flashes the passport page
    #: and is bounced back to content about a second later, so a crawl that judged the
    #: flash latched ``login_wall`` for good — it stopped harvesting early and told the
    #: user to re-save a cookie that was fine. Bounded by poll count rather than by a
    #: clock, like every other wait here, so a fake driver settles instantly.
    WALL_PROOFS = 5
    WALL_POLL = 0.3

    def __init__(
        self,
        headless: bool = True,
        cookie_path: str | None = None,
        for_login: bool = False,
        profile_dir: str | None = None,
        abort=None,
    ):
        self.headless = headless
        self.cookie_path = cookie_path
        # A directory that outlives this browser, so the next run of this platform is
        # the same device to the site (see ``browser_profiles``). None is the old
        # behaviour: a throwaway profile plus whatever cookie file we plant into it.
        self.profile_dir = str(profile_dir or '') or None
        # Why THIS browser may not carry on: set by the executor to "the user stopped
        # the run", consulted in two places — queued on the profile lock, and at every
        # boundary of a crawl's own walk. A Stop that still had the wait outstanding
        # bought a browser for a run already declared over — or never reached its
        # finally at all, stranding the record on 运行中 and the queue behind it.
        self._abort = abort
        if for_login:
            # A window the user looks at is not a crawl. The login page's QR code is
            # an ``<img>``, so the content blocker that saves seconds on every
            # navigation would leave the one step a crawler cannot perform —
            # scanning to log in — impossible. Reported by a user re-saving a weibo
            # cookie, who got a page with no code to scan. The profile can already
            # hold a blocker a previous crawl left behind, so this must be an answer
            # and not an omission (see ``_content_prefs``).
            self.needs_images = True
        self.driver = None
        self._sink = None
        self._cursor_sink = None
        self._collected = []
        self._cursor = {}
        # URLs this session actually asked for, in order. Kept because the cost
        # model of a crawl *is* its request count: a mode that promises "one request
        # per page" has to be measurable promising it, and a test that only checks
        # the resulting table cannot tell that from a per-row walk.
        self.requests: list[str] = []
        # Set when a page turned out to be a login wall; the platform crawlers
        # stop their scroll/page walk on it and say so instead of reporting an
        # empty crawl.
        self.login_wall = False
        # Risk control answered, not a login problem: the session may be perfect
        # and the fix is to back off. Kept apart from ``login_wall`` so the
        # console never tells the user to re-save a cookie that is fine.
        self.risk_blocked = False
        self.cookies_loaded = 0
        self._profile_lock = self._claim_profile()
        try:
            self._create_driver()
        except Exception:
            # A browser that never came up must not leave the profile claimed: the
            # next run of this platform would wait out the timeout on a directory
            # nobody is using.
            self._release_profile()
            raise

    def _claim_profile(self):
        """Take exclusive use of this platform's profile directory, if there is one.

        chromedriver pre-writes the profile's ``Default/Preferences`` before Chrome
        starts, so two sessions created in one directory at the same moment cannot
        both come up — measured, and it surfaces as ``session not created: failed to
        write prefs file`` on whichever node loses. One profile is one device, so the
        answer is to wait for the other crawl rather than to hand out a second
        directory and throw the device identity away.
        """
        if not self.profile_dir:
            return None
        started = time.monotonic()
        lock = browser_profiles.acquire_profile(self.profile_dir, abort=self._abort)
        if lock is None:
            if self._abort is not None and self._abort():
                # Not a stuck profile — the user stopped this run while it queued.
                # Saying so matters: the other message blames a window that never
                # closed and sends the user hunting a browser that is not there.
                raise ProfileUnavailableError(t('crawl.profile_gave_up', dir=self.profile_dir))
            raise ProfileUnavailableError(
                t(
                    'crawl.profile_stuck',
                    dir=self.profile_dir,
                    seconds=round(Config.PROFILE_LOCK_TIMEOUT),
                )
            )
        waited = time.monotonic() - started
        if waited >= 0.2:
            # Said once, before the wait it describes. No heartbeat: a crawl behind
            # this line is already running and the console is not a progress bar.
            logger.info(t('crawl.profile_wait', seconds=round(waited), dir=self.profile_dir))
        return lock

    def _release_profile(self):
        lock, self._profile_lock = self._profile_lock, None
        browser_profiles.release_profile(lock)

    def may_stop(self) -> bool:
        """Whether the user asked this crawl to end, as of right now.

        The walk engines (:func:`engine.feed.walk_feed`, :func:`engine.pager.walk_pages`)
        already take a predicate here, and every one of them had it wired to the wall
        flags only — so a Stop left a scrolling crawl harvesting, page after page, in a
        browser the user believes is dead. Measured why the flag is needed even though
        the Stop also closes the browser: ``driver.quit()`` from another thread is an
        in-band command, queued *behind* the running one, so it neither interrupts a
        page load (40.0 s of ``page_load_timeout``) nor an in-page fetch (30.0 s of
        script timeout). Only killing the driver process returns the worker early.

        A crawl therefore stops at its own next boundary, which costs one round rather
        than one page, and the node reports 被停止 rather than "the site had no more".
        """
        abort = getattr(self, '_abort', None)
        return bool(abort is not None and abort())

    # ── streaming hooks (installed by the runner) ───────────────

    def set_sink(self, sink):
        """sink(item) -> bool — True to keep the item, False if the sink
        already has it. Called for every scraped item, in scrape order."""
        self._sink = sink

    def set_cursor_sink(self, sink):
        """sink(position: dict) -> None — called whenever the crawl advances,
        so the recorded position never lags behind the collected items."""
        self._cursor_sink = sink

    def emit(self, item) -> bool:
        """Hand one scraped item over. Returns whether it was kept.

        The stop is checked HERE rather than at each call site because every crawl in
        this project streams its rows through this one method — so a hand-rolled loop
        that never went through the shared walkers is interrupted at its next row too,
        and a platform added tomorrow inherits it without knowing. Raising rather than
        answering False is what keeps a stopped crawl from being reported as "the site
        had nothing more"; the rows already handed over are checkpointed and stay.
        """
        if self.may_stop():
            raise CrawlerStopped(t('crawl.stopped'))
        if item is None:
            return False
        if self._sink is None:
            self._collected.append(item)
            return True
        try:
            kept = self._sink(item)
        except Exception as e:
            # Persistence is best-effort: a broken sink must never abort the
            # crawl, and the item still travels in this run's results.
            logger.warning(t('crawl.sink_failed', err=e))
            kept = True
        if kept:
            self._collected.append(item)
        return kept

    def seed(self, rows):
        """Hand a resumed crawler the items the previous attempt collected.

        They are put straight into the collected list — not through ``emit``,
        since the sink already has them and would answer "not new" for every
        one. Restored to the crawler they are what makes ``collected()`` honest
        from the first item: a target of 200 with 180 already saved asks the
        page for 20 more, not 200.
        """
        if not rows:
            return
        self._collected.extend(rows)

    def mark_position(self, **position):
        """Record where the crawl has got to. Merged into the previous position
        rather than replacing it, so a caller only passes what changed."""
        self._cursor.update(position)
        if self._cursor_sink is not None:
            with contextlib.suppress(Exception):
                self._cursor_sink(dict(self._cursor))

    @property
    def position(self) -> dict:
        return dict(self._cursor)

    def results(self) -> list:
        """Everything collected so far, in scrape order."""
        return list(self._collected)

    def collected(self) -> int:
        return len(self._collected)

    @staticmethod
    def resume_of(kwargs: dict) -> dict:
        """The cursor handed back to a resumed crawl ({} on a fresh one)."""
        cursor = (kwargs or {}).get('resume')
        return cursor if isinstance(cursor, dict) else {}

    def _content_prefs(self) -> dict:
        """Chrome content preferences for this session — always an explicit answer.

        Both branches *write* a value, and that is the whole point. A crawl's blocker
        is persisted into the profile directory it ran on (measured: after one weibo
        crawl, ``data/chrome_profile/weibo/Default/Preferences`` carried
        ``managed_default_content_settings.images = 2``), so a later human-facing
        window that merely *omits* the preference inherits the block from the device
        it shares with that crawl — and the login page it shows has no QR code to
        scan, because a QR code is an ``<img>``. Saying 允许 explicitly is what makes
        「打开浏览器登录」 completable on a profile that has already crawled; the
        block itself stays the crawl default, since it is the largest per-navigation
        saving a text-and-attribute crawler has (see ``needs_images``).
        """
        return {'profile.managed_default_content_settings': {'images': 1 if self.needs_images else 2}}

    def _create_driver(self):
        opts = Options()
        if self.headless:
            opts.add_argument('--headless=new')
        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage')
        opts.add_argument('--disable-gpu')
        # A background or occluded window must behave exactly like a visible
        # one. Chrome's default backgrounding throttles timers and freezes
        # rendering of occluded windows, which makes virtualised/lazy pages
        # stop loading — the crawl then reads an empty page that is only empty
        # because the browser decided to nap. (Headless is unaffected either
        # way; this covers the login browser and headless=False crawls.)
        opts.add_argument('--disable-backgrounding-occluded-windows')
        opts.add_argument('--disable-background-timer-throttling')
        opts.add_argument('--disable-renderer-backgrounding')
        if self.profile_dir:
            # Chrome creates the user-data-dir itself, so a missing directory is the
            # normal first run and not an error to handle here.
            opts.add_argument(f'--user-data-dir={self.profile_dir}')
        # Machine-local choices (driver / browser / window) come from the
        # settings store, editable in the frontend 设置 panel.
        opts.add_argument(f'--window-size={get_setting("window_size")}')
        opts.add_argument('--lang=zh-CN')
        # Sites' risk control treats navigator.webdriver as proof of a bot and
        # hard-blocks content pages (search keeps working, which is why the block
        # looked selective). Hide the automation flag on both surfaces.
        opts.add_argument('--disable-blink-features=AutomationControlled')
        opts.add_experimental_option('excludeSwitches', ['enable-logging', 'automation'])
        # ``eager`` returns as soon as the DOM is parseable instead of waiting
        # for every image, font and analytics beacon. A crawler reads text and
        # attributes, so the wait buys nothing — and on douyin the full ``load``
        # event was measured to never arrive at all (a 40 s TimeoutException on
        # the very first navigation), which no amount of timeout tuning fixes.
        opts.page_load_strategy = 'eager'
        prefs = self._content_prefs()
        if prefs:
            opts.add_experimental_option('prefs', prefs)
        browser_binary = str(get_setting('browser_binary') or '').strip()
        if browser_binary:
            opts.binary_location = browser_binary
        service = Service(executable_path=get_setting('driver_path'))
        self.driver: webdriver.Chrome = webdriver.Chrome(options=opts, service=service)  # pylint: disable=not-callable
        # A timeout the driver rejects (bad value, dead session) must not kill
        # the session — the crawl can still run on the default timeout.
        with contextlib.suppress(Exception):
            self.driver.set_page_load_timeout(int(get_setting('page_load_timeout')))
        if self.cookie_path:
            self._load_cookies()

    # ─── navigation ─────────────────────────────────────────────

    def open(self, url: str) -> bool:
        """Navigate to *url*, clear any first-run dialog, and report a wall.

        Every platform's entry point goes through here so the three things that
        must happen on arrival happen once: the dialog that intercepts the next
        click is dismissed, the redirect target is judged (login wall, risk
        control, or the router dropping the request at the site root), and a slow
        renderer is survived. A timeout is not fatal — the document keeps
        building, and the caller's own poll is what decides whether the page is
        ready — but it must be *seen*, because "zero cards" after a timeout reads
        to the user as an empty search.
        """
        timed_out = False
        self.requests.append(str(url))
        try:
            self.driver.get(url)
        except Exception as e:
            timed_out = True
            logger.debug('navigation did not settle for %s: %s', url, e)
        if self.prompts:
            self._dismiss_prompts()
        self._judge_arrival(url)
        return not timed_out

    def _judge_arrival(self, request_url: str = '') -> str:
        """Classify the page this navigation landed on, believing only a lasting refusal.

        Called by :meth:`open` instead of ``check_intercept`` directly: the redirect chain
        of a single-page site is still moving when ``driver.get`` returns, and a wall
        flashed on the way through (weibo's passport hop) is not where the user arrived.
        A clean page is answered on the first reading, so this costs nothing unless a
        refusal is on screen.
        """
        verdict = self.verdict(request_url=request_url)
        for _ in range(max(0, self.WALL_PROOFS - 1)):
            if verdict == 'ok':
                return verdict
            time.sleep(self.WALL_POLL)
            verdict = self.verdict(request_url=request_url)
        if verdict == 'ok':
            return verdict
        # Still refused after the whole settle window: record it the way every caller
        # reads it. Latched from *this* reading rather than by calling check_intercept
        # again, because re-judging here would hand a flash one free escape and make the
        # window above unobservable from the tests.
        return self._record(verdict, where=request_url, request_url=request_url)

    def verdict(self, request_url: str = '') -> str:
        """The same judgement :meth:`check_intercept` makes, recorded nowhere.

        Split out so a refusal can be re-read without latching it on the first pass —
        ``login_wall`` is a one-way flag by design (it stops the harvest loop and turns a
        run into a resume), which is exactly why it must not be set by a page on its way
        somewhere else.
        """
        try:
            url = self.driver.current_url or ''
        except Exception:
            return 'ok'
        verdict = classify(url, self._body_text())
        if verdict == 'ok' and request_url and bounced_to_root(request_url, url, self.login_url):
            verdict = 'login'
        return verdict

    def _dismiss_prompts(self):
        """Click the site's own first-run dialog away, and say what was clicked."""
        for outcome in popup.dismiss(self.driver, self.prompts):
            if outcome.get('clicked'):
                logger.info(t('crawl.promptDismissed', label=self.domain, button=outcome['clicked']))
            elif outcome.get('matched'):
                # Recognised but no label matched: the site re-skinned itself and
                # the answer is in the table, not in a longer sleep.
                buttons = ', '.join(str(s) for s in outcome.get('seen') or [])
                logger.info(t('crawl.promptUnmatched', label=self.domain, buttons=buttons))

    def _load_cookies(self):
        """Plant the saved cookies on the hosts that need them.

        One host is enough when every stored cookie is written for a domain the
        first visit accepts (a ``.douyin.com`` cookie is valid on every subdomain),
        and each extra host costs a full page load — measured at 2.3 s apiece on
        douyin, one of which was a pure redirect. So the loop keeps going only for
        the cookies the current host *refused*, which is the weibo case the
        original code was written for (a cookie bound to one host is rejected on
        another) and is still covered.
        """
        try:
            with open(self.cookie_path, encoding='utf-8') as f:
                cookies = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(cookies, list) or not cookies:
            return
        hosts = [self.domain, *[d for d in self.cookie_domains if d and d != self.domain]]
        outstanding = list(cookies)
        for host in [h for h in hosts if h]:
            if not outstanding:
                break
            try:
                self.driver.get(f'https://{host}')
            except Exception as e:
                # A slow / blocked landing page must not kill the session before
                # the crawl even starts — the next host may still take cookies.
                logger.warning(t('crawl.cookies_failed', platform=host, err=e))
                continue
            applied, rejected = self._plant(outstanding)
            self.cookies_loaded = max(self.cookies_loaded, applied)
            logger.info(t('crawl.cookiesSeeded', host=host, n=applied, total=len(cookies)))
            outstanding = rejected

    def _plant(self, cookies: list) -> tuple:
        """Offer *cookies* to the page that is open; return (accepted, refused).

        A cookie whose domain does not match the current document raises, and an
        expired one raises too — both are kept for the next host rather than
        dropped, and neither aborts the rest of the list.
        """
        applied = 0
        rejected = []
        for raw in cookies:
            payload = self._cookie_payload(raw)
            if not payload:
                continue
            try:
                self.driver.add_cookie(payload)
            except Exception:
                rejected.append(raw)
                continue
            applied += 1
        return applied, rejected

    @staticmethod
    def _cookie_payload(raw):
        """The saveable subset of a stored cookie, or None if it has no name.

        ``save_cookies`` writes whatever the driver reported, including fields
        ``add_cookie`` refuses (``expiry`` as a float, an unparsable
        ``sameSite``), which used to make the whole reload silently no-op.
        """
        if not isinstance(raw, dict):
            return None
        name = str(raw.get('name') or '')
        if not name:
            return None
        payload = {'name': name, 'value': str(raw.get('value', ''))}
        for key in ('domain', 'path', 'secure', 'httpOnly'):
            if raw.get(key) is not None:
                payload[key] = raw[key]
        if raw.get('sameSite') in ('Strict', 'Lax', 'None'):
            payload['sameSite'] = raw['sameSite']
        try:
            if raw.get('expiry') is not None:
                payload['expiry'] = int(float(raw['expiry']))
        except (TypeError, ValueError):
            pass
        return payload

    # ── DOM / timing helpers shared by the platform crawlers ───────────

    def _text_of(self, element, selector: str, default: str = '') -> str:
        """innerText of a child, falling back to textContent.

        innerText is empty for nodes the virtualised lists have not laid out
        yet — precisely the cards a fast scroll leaves off-screen — so the
        text is there, the crawler just could not see it.
        """
        try:
            el = element.find_element('css selector', selector)
        except Exception:
            return default
        return self._node_text(el, default)

    def _element_or_none(self, selector: str):
        """The first node matching *selector*, or None — pages routinely lack
        an element and the caller's loop must keep running either way."""
        try:
            return self.driver.find_element('css selector', selector)
        except Exception:
            return None

    def _node_text(self, element, default: str = '') -> str:
        script = 'return arguments[0].innerText || arguments[0].textContent || ""'
        try:
            text = self.driver.execute_script(script, element)
        except Exception:
            try:
                text = element.text
            except Exception:
                return default
        text = (text or '').strip()
        return text if text else default

    def _current_url(self) -> str:
        """The address bar, or '' when the driver cannot answer.

        Every console line that names where a crawl stopped reads this, and a
        dead session must not turn a useful warning into an exception on top of
        the failure the user is already being told about.
        """
        try:
            return self.driver.current_url or ''
        except Exception:
            return ''

    def _body_text(self, limit: int = 400) -> str:
        """Visible text at the top of the page, used for login-wall detection."""
        try:
            return self._node_text(self.driver.find_element('css selector', 'body'))[:limit]
        except Exception:
            return ''

    # ─── cookie diagnostics ────────────────────────────────────

    def diagnose(self, url: str = '') -> dict:
        """Report what the stored cookie actually unlocks, as bare facts.

        A cookie file's existence proves nothing — the question is whether the
        platform still lets this session past its wall. Only facts come back
        from here: the cookie endpoint turns the keys into console and panel
        text, so every user-facing string stays in the message catalog. A
        platform with no login page (``login_url`` empty) reports no wall and
        visits nothing, which is how WeChat — crawled without any session —
        answers.
        """
        target = str(url or '') or self.login_url
        facts = {'platform': self.domain, 'url': '', 'login_wall': False}
        if not target:
            return facts
        self.driver.get(target)
        try:
            facts['url'] = self.driver.current_url or ''
        except Exception:
            facts['url'] = target
        facts['login_wall'] = self.check_login_wall(target)
        return facts

    def check_login_wall(self, where: str = '') -> bool:
        """Flag (once) that the browser was bounced to a login page.

        Defensive by design: a driver that cannot answer ``current_url`` (a
        dead session, a test double) must read as "no wall" rather than abort a
        crawl that is otherwise producing rows.
        """
        return self.check_intercept(where) == 'login'

    def check_intercept(self, where: str = '', request_url: str = '') -> str:
        """Classify the page the browser is actually on **and record it**:
        ``login`` / ``blocked`` / ``ok``.

        Two different refusals, because the user's next step differs — one needs
        a fresh cookie, the other needs to wait. ``blocked`` is recorded on
        :attr:`risk_blocked` and deliberately does *not* set ``login_wall``: a
        headless zhihu search answered by risk control (code 40362) is a real
        outcome of that mode, and calling it a dead cookie would send the user to
        re-save a session that is fine.

        ``request_url`` enables the bounce test: a profile URL that comes back at
        the site root with no content is a refusal even though nothing on the
        page says "login".

        This latches on the first reading. On a page that has only just been
        navigated to, go through :meth:`_judge_arrival` (what :meth:`open` calls)
        instead, which waits to see whether the refusal stays.
        """
        return self._record(self.verdict(request_url=request_url), where, request_url)

    def _record(self, verdict: str, where: str = '', request_url: str = '') -> str:
        """Write an already-taken judgement onto the flags that stop a crawl."""
        if verdict == 'login' and not self.login_wall:
            self.login_wall = True
            logger.warning(t('crawl.loginWall', platform=self.domain, where=self._refused_at(where, request_url)))
        if verdict == 'blocked' and not self.risk_blocked:
            self.risk_blocked = True
            logger.warning(t('crawl.riskBlocked', platform=self.domain, where=self._refused_at(where, request_url)))
        return verdict

    def _refused_at(self, where: str = '', request_url: str = '') -> str:
        """The address to name in a refusal line: where the browser actually is, and
        only when it cannot answer, what was asked for."""
        return self._current_url() or where or request_url

    def _wait_for_count(self, count_fn, target: int, timeout: float = 1.5, tick: float = 0.3) -> int:
        """Poll ``count_fn`` until it reaches ``target`` or ``timeout`` runs out.

        Replaces the fixed two-second sleep after a scroll: content that is
        already there costs one poll, content that is slow still gets its wait.
        Bounded by poll count rather than a clock so the wait stays a pure
        function of the page (and stays instant under a fake driver).
        """
        return feed.wait_for(count_fn, target, timeout=timeout, tick=tick)

    @staticmethod
    def _polite_pause(base: float = 1.0, spread: float = 0.4):
        """Jittered pause between rounds that hit the network.

        Anti-bot caution is a requirement, not a leftover: the jitter is what
        keeps a run of crawls from looking like a metronome.
        """
        time.sleep(max(0.2, base + random.uniform(-spread, spread)))

    @staticmethod
    def _as_text(value) -> str:
        return '' if value is None else str(value).strip()

    @staticmethod
    def _abs_url(base_href: str, prefix: str = 'https:') -> str:
        href = (base_href or '').strip()
        if href.startswith('//'):
            return prefix + href
        return href

    def save_cookies(self, path: str) -> int:
        """Write the session cookies to *path*; returns how many were saved."""
        cookies = self.driver.get_cookies()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        return len(cookies)

    def wait_for_element(self, selector: str, timeout: int | None = None):
        # Default wait comes from the settings panel (元素等待超时).
        if timeout is None:
            timeout = int(get_setting('element_timeout'))
        try:
            WebDriverWait(self.driver, timeout).until(lambda d: d.find_element('css selector', selector))
            return True
        except TimeoutException:
            return False

    def scroll_to_bottom(self, times: int = 1, wait: float = 0.1):
        for _ in range(times):
            self.driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
            time.sleep(wait)

    def scroll_down(self, steps: int = 3, wait: float = 0.12):
        """Walk the page down in viewport-sized steps, then land at the bottom.

        A single jump to ``scrollHeight`` skips the intersection observers hung
        off the intermediate sections of an infinite list, so nothing new is
        requested and the round is wasted; stepping feeds them.
        """
        for _ in range(max(1, steps)):
            self.driver.execute_script('window.scrollBy(0, Math.max(400, window.innerHeight * 0.9));')
            time.sleep(wait)
        self.driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(wait)

    @abstractmethod
    def search(self, keyword: str, **_kwargs):
        pass

    @abstractmethod
    def get_detail(self, url: str) -> dict | None:
        pass

    def close(self):
        # quit() on a dead session raises; callers close in a `finally`, where
        # an exception would mask the real result of the crawl.
        if self.driver:
            with contextlib.suppress(Exception):
                self.driver.quit()
            self.driver = None
        # Released after the browser is gone: the next crawl of this platform may
        # not be able to write its profile while this one still owns Chrome.
        self._release_profile()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
