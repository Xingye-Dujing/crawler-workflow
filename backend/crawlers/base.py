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


class Crawler(ABC):
    """Base class for all platform crawlers."""

    domain = ''
    login_url = ''

    def __init__(self, headless: bool = True, cookie_path: str | None = None):
        self.headless = headless
        self.cookie_path = cookie_path
        self.driver = None
        self._create_driver()

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
