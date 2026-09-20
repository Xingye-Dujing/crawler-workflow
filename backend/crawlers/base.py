import contextlib
import json
import logging
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

    def __init__(self, headless: bool = True, cookie_path: str | None = None):
        self.headless = headless
        self.cookie_path = cookie_path
        self.driver = None
        self._sink = None
        self._cursor_sink = None
        self._collected = []
        self._cursor = {}
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
        # Machine-local choices (driver / browser / window) come from the
        # settings store, editable in the frontend 设置 panel.
        opts.add_argument(f'--window-size={get_setting("window_size")}')
        opts.add_argument('--lang=zh-CN')
        opts.add_experimental_option('excludeSwitches', ['enable-logging'])
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
        try:
            with open(self.cookie_path, encoding='utf-8') as f:
                cookies = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(cookies, list) or not cookies:
            return
        try:
            self.driver.get(f'https://{self.domain}')
            for c in cookies:
                # A cookie for another domain (or an expired one the driver
                # refuses) must not abort the rest of the list.
                with contextlib.suppress(Exception):
                    self.driver.add_cookie(c)
        except Exception as e:
            # A slow / blocked landing page must not kill the session before
            # the crawl even starts — but it is worth saying out loud, since
            # the run that follows may come back empty for lack of login.
            logger.warning(t('crawl.cookies_failed', platform=self.domain, err=e))

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
