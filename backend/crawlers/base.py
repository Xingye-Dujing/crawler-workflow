import contextlib
import json
import logging
import random
import re
import time
from abc import ABC, abstractmethod

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from i18n import t
from settings_store import get_setting

logger = logging.getLogger(__name__)

# Where a crawler has been pushed into a login page instead of the content it
# asked for. Every platform parks its QR wall on ``passport``/``login`` hosts,
# so one shared detector beats three platform-specific guesses at "why is this
# page empty?".
_WALL_MARKERS = (
    'passport.weibo.com/sso',
    'passport.zhihu.com',
    '/login?',
    '/signin',
    'accounts.google.com',
)
_WALL_TEXTS = ('扫描二维码登录', '手机号登录', '请先登录', '登录后查看', '扫码登录', '暂时限制', '当前请求存在异常')


def looks_like_login_page(url: str, body_text: str = '') -> bool:
    """True when a page is a login wall rather than the requested content.

    Crawlers used to read such a page as "no results" and log an empty crawl,
    which sent the user off to re-save cookies that were fine all along.
    """
    lowered = (url or '').lower()
    if any(marker in lowered for marker in _WALL_MARKERS):
        return True
    text = body_text or ''
    # Only the head of the page is examined: the marker strings are short and
    # a wall puts them at the top, while an article that merely mentions
    # "登录" in its body must not read as a wall.
    head = text[:400]
    return sum(1 for marker in _WALL_TEXTS if marker in head) >= 2


def as_index(value, default: int = 0) -> int:
    """A cursor field, coerced. Cursors are read back from JSON and may hold
    anything at all; a bad value must degrade to "start from the beginning"
    rather than crash the crawl that was supposed to save work."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


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

    def __init__(self, headless: bool = True, cookie_path: str | None = None):
        self.headless = headless
        self.cookie_path = cookie_path
        self.driver = None
        self._sink = None
        self._cursor_sink = None
        self._collected = []
        self._cursor = {}
        # Set when a page turned out to be a login wall; the platform crawlers
        # stop their scroll/page walk on it and say so instead of reporting an
        # empty crawl.
        self.login_wall = False
        self.cookies_loaded = 0
        self._create_driver()

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
        """Hand one scraped item over. Returns whether it was kept."""
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
        # Machine-local choices (driver / browser / window) come from the
        # settings store, editable in the frontend 设置 panel.
        opts.add_argument(f'--window-size={get_setting("window_size")}')
        opts.add_argument('--lang=zh-CN')
        # Sites' risk control treats navigator.webdriver as proof of a bot and
        # hard-blocks content pages (search keeps working, which is why the block
        # looked selective). Hide the automation flag on both surfaces.
        opts.add_argument('--disable-blink-features=AutomationControlled')
        opts.add_experimental_option('excludeSwitches', ['enable-logging', 'automation'])
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

    def _load_cookies(self):
        """Plant the saved cookies on every host the crawl will visit.

        One host is not enough: a cookie exported from ``weibo.com`` is accepted
        there and silently rejected on the search host, which is where the wall
        actually appears. Each host is visited in turn and the whole list is
        offered to it — the entries that do not belong raise and are skipped.
        """
        try:
            with open(self.cookie_path, encoding='utf-8') as f:
                cookies = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(cookies, list) or not cookies:
            return
        hosts = [self.domain, *[d for d in self.cookie_domains if d and d != self.domain]]
        for host in [h for h in hosts if h]:
            try:
                self.driver.get(f'https://{host}')
            except Exception as e:
                # A slow / blocked landing page must not kill the session before
                # the crawl even starts — the next host may still take cookies.
                logger.warning(t('crawl.cookies_failed', platform=host, err=e))
                continue
            applied = 0
            for raw in cookies:
                payload = self._cookie_payload(raw)
                if not payload:
                    continue
                # A cookie for another domain (or an expired one the driver
                # refuses) must not abort the rest of the list.
                with contextlib.suppress(Exception):
                    self.driver.add_cookie(payload)
                    applied += 1
            self.cookies_loaded = max(self.cookies_loaded, applied)
            logger.info(t('crawl.cookiesSeeded', host=host, n=applied, total=len(cookies)))

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

    def _body_text(self, limit: int = 400) -> str:
        """Visible text at the top of the page, used for login-wall detection."""
        try:
            return self._node_text(self.driver.find_element('css selector', 'body'))[:limit]
        except Exception:
            return ''

    def check_login_wall(self, where: str = '') -> bool:
        """Flag (once) that the browser was bounced to a login page.

        Defensive by design: a driver that cannot answer ``current_url`` (a
        dead session, a test double) must read as "no wall" rather than abort a
        crawl that is otherwise producing rows.
        """
        try:
            url = self.driver.current_url or ''
        except Exception:
            return False
        if not looks_like_login_page(url, self._body_text()):
            return False
        if not self.login_wall:
            self.login_wall = True
            logger.warning(t('crawl.loginWall', platform=self.domain, where=where or url))
        return True

    def _wait_for_count(self, count_fn, target: int, timeout: float = 1.5, tick: float = 0.3) -> int:
        """Poll ``count_fn`` until it reaches ``target`` or ``timeout`` runs out.

        Replaces the fixed two-second sleep after a scroll: content that is
        already there costs one poll, content that is slow still gets its wait.
        Bounded by poll count rather than a clock so the wait stays a pure
        function of the page (and stays instant under a fake driver).
        """
        seen = count_fn()
        for _ in range(max(1, int(timeout / tick))):
            if seen >= target:
                break
            time.sleep(tick)
            seen = count_fn()
        return seen

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

    @staticmethod
    def _number_in(text: str) -> int:
        """First integer in a label, honouring the Chinese units 万/千."""
        if not text:
            return 0
        cleaned = str(text).replace(',', '').replace(' ', '')
        m = re.search(r'(\d+(?:\.\d+)?)(万|千)?', cleaned)
        if not m:
            return 0
        value = float(m.group(1))
        if m.group(2) == '万':
            value *= 10000
        elif m.group(2) == '千':
            value *= 1000
        return int(value)

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

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
