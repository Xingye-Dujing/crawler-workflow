import logging
import re
import time

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from config import Config
from i18n import t

from .base import Crawler, as_index

logger = logging.getLogger(__name__)


class WechatCrawler(Crawler):
    """WeChat official account article crawler.

    Scrapes public article pages for title, account, publish time, region,
    original marker, body text and image count. Needs no login and no cookie:
    the article page is served to anyone, which is why WeChat has no row in the
    cookie panel at all.

    What this platform deliberately does NOT collect, and why: 留言、点赞数、转发数
    (and 阅读数 for most sessions). WeChat serves those from a per-article
    credential that its server mints only for a recognised client session, so a
    browser — including this one — receives the article body and nothing else.
    Measured on real articles rather than assumed: the page reports
    ``show_comment=0``, carries no ``elected_comment`` data at all, and the
    comment endpoint answers an HTML page saying 请在微信客户端打开链接. Forging the
    client to defeat that gate is out of scope: it is circumventing another
    service's access control, and the credential is per-session anyway, so the
    shapes that could be faked (user agent, URL parameters, even a replayed
    cookie) are not the ones that are checked. An article genuinely without
    comments and a visit that was never allowed to see them are indistinguishable
    from a browser, which is exactly why nothing is reported as "0 comments".
    """

    domain = 'mp.weixin.qq.com'
    # No login_url on purpose: an article body is served to anyone, so this
    # platform has no cookie row in the panel and nothing here may claim a page
    # to sign in on. (The 公众号 backend was measured to unlock keyword search
    # only, and that feature was removed rather than shipped unverifiable.)
    # Real article URLs, usable by the live tests:
    # https://mp.weixin.qq.com/s/cAx1zGfT2MzqpwnhULmSQA
    # https://mp.weixin.qq.com/s/q59mL_dHixC97p19RpcfVQ
    # https://mp.weixin.qq.com/s/f_2nB7u7pQApgIoPsBKMQg

    # ------------------------------------------------------------------
    # Search / batch scrape
    # ------------------------------------------------------------------

    def search(self, keyword: str = None, urls: list = None, **_kwargs):
        """Scrape one or more WeChat articles by URL.

        Args:
            keyword: Ignored (kept for compatibility with base class).
            urls: List of article URLs to scrape.

        Returns:
            List of result dicts.
        """
        if not urls:
            logger.info(t('crawl.wechat.no_urls'))
            return []

        resume = self.resume_of(_kwargs)
        urls = [str(u).strip() for u in urls if str(u).strip()]
        start_index = as_index(resume.get('url_index'))
        have = self.collected()
        if have:
            # The articles already scraped are in hand; the run picks up at the
            # next link instead of fetching the same pages again.
            logger.info(t('crawl.resume_have', n=have))

        total = len(urls)
        logger.info('=' * 70)
        logger.info(t('crawl.wechat.batch_start', n=total))
        logger.info('=' * 70)
        self.mark_position(urls=urls, url_total=total, url_index=start_index, done=have)

        for idx, url in enumerate(urls, start=1):
            if idx <= start_index:
                continue
            logger.info('')
            logger.info(t('crawl.wechat.processing', i=idx, total=total))
            logger.info(t('crawl.wechat.url', url=url))

            data = self.get_detail(url)
            if data:
                if self.emit(data):
                    logger.info(
                        t(
                            'crawl.wechat.success',
                            i=idx,
                            total=total,
                            title=data.get('标题', '?'),
                            author=data.get('公众号', '?'),
                        )
                    )
                else:
                    logger.debug(t('crawl.wechat.duplicate', url=url))
            else:
                logger.warning(t('crawl.wechat.failed', i=idx, total=total))

            # The cursor moves with the article, so a kill here costs at most
            # the page in flight.
            self.mark_position(url_index=idx, done=self.collected())

            if idx < total:
                logger.info(t('crawl.wechat.wait'))
                # The log above promises a second, and a batch of articles is
                # exactly where WeChat's rate limiter bites — keep the promise.
                self._polite_pause(1.0, 0.3)

        logger.info('')
        logger.info('=' * 70)
        logger.info(t('crawl.wechat.batch_done', n=self.collected(), total=total))
        logger.info('=' * 70)
        return self.results()

    # ------------------------------------------------------------------
    # Single article detail
    # ------------------------------------------------------------------

    def get_detail(self, url: str) -> dict | None:
        """Scrape a single WeChat article and return structured data."""
        logger.info(t('crawl.wechat.navigating'))
        self.driver.get(url)

        logger.info(t('crawl.wechat.wait_title'))
        try:
            WebDriverWait(self.driver, 15).until(ec.presence_of_element_located((By.CSS_SELECTOR, '#activity-name')))
            logger.info(t('crawl.wechat.loaded'))
        except TimeoutException:
            if self.check_login_wall(url):
                return None
            logger.warning(t('crawl.wechat.timeout', url=url))
            return None

        # Scroll to bottom to trigger lazy-loaded elements (read counts, etc.)
        logger.info(t('crawl.wechat.scroll'))
        self.scroll_down(steps=2, wait=0.2)
        logger.info(t('crawl.wechat.scroll_done'))

        # ---- Extract fields ----
        logger.info(t('crawl.wechat.extracting'))

        title = self.get_article_title()
        logger.info(t('crawl.wechat.title', title=title or '(empty)'))

        author = self.get_author()
        logger.info(t('crawl.wechat.author', author=author or '(empty)'))

        pub_time = self.get_publish_time()
        logger.info(t('crawl.wechat.pub_time', time=pub_time or '(empty)'))

        region = self.get_ip_region()

        content = self.get_content()
        logger.info(t('crawl.wechat.content_len', n=len(content)))

        # Summarise extracted content (first 120 chars)
        content_preview = content[:120].replace('\n', ' ').strip()
        if len(content) > 120:
            content_preview += '...'
        logger.info(t('crawl.wechat.preview', preview=content_preview))

        return {
            '标题': title,
            '公众号': author,
            '发布时间': pub_time,
            '发布地区': region,
            '是否原创': '是' if self.is_original() else '',
            '正文': self._clip(content),
            '正文图片数': self.get_image_count(),
            '链接': url,
        }

    @staticmethod
    def _clip(content: str) -> str:
        """Apply the configured body ceiling, marking a cut instead of hiding it.

        The cap exists because one article can be longer than every row a run
        stores, but a silent cut is the real hazard: the text downstream reads
        would look complete. The trailing ``…`` is what says otherwise.
        """
        limit = int(getattr(Config, 'WECHAT_BODY_MAX_CHARS', 0) or 0)
        text = content or ''
        if not limit or len(text) <= limit:
            return text
        return text[:limit] + '…'

    # ------------------------------------------------------------------
    # Field extraction helpers
    # ------------------------------------------------------------------

    def extract_text(self, element, selector, default=''):
        """Extract text from a child element identified by CSS selector.

        Args:
            element: Parent WebElement.
            selector: CSS selector for the child element.
            default: Fallback value if the element is not found.

        Returns:
            Stripped text or default.
        """
        return self._text_of(element, selector, default) or default

    def get_article_title(self) -> str:
        """Extract article title from #activity-name."""
        title = self._text_of(self.driver, '#activity-name')
        if not title:
            logger.debug(t('crawl.debug.title_missing'))
        return ' '.join(title.split())

    def get_author(self) -> str:
        """Extract the official account name (公众号)."""
        selectors = ['#js_name', '#profileBt a', '.rich_media_meta_nickname a', '#js_author_name']
        for sel in selectors:
            try:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
            except Exception:
                continue
            for el in els:
                text = ' '.join(self._node_text(el).split())
                if text:
                    return text
        logger.debug(t('crawl.debug.author_missing'))
        return ''

    def get_publish_time(self) -> str:
        """Extract the article publish time.

        The page renders a Chinese date ('2026年9月15日 13:08'), not the ISO form
        the local fixture uses, so both spellings have to be recognised — the
        old ``\\d{4}-\\d{1,2}-\\d{1,2}`` test matched neither and the column came
        back empty on every real article.
        """
        selectors = ['#publish_time', '#meta_content .rich_media_meta_text']
        for sel in selectors:
            try:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
            except Exception:
                continue
            for el in els:
                text = self._node_text(el)
                if self._DATE_RE.search(text):
                    return text
        logger.debug(t('crawl.debug.time_missing'))
        return ''

    _DATE_RE = re.compile(r'\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}|\d{1,2}\s*小时前|\d{1,2}\s*分钟前')

    def get_ip_region(self) -> str:
        """The province the article was published from (发布地区).

        ``#js_ip_wording`` is that node on a live page. The fallback walks the
        ``.rich_media_meta_text`` spans — which also hold the date and, on some
        templates, the account name — so anything already used for another
        column is rejected rather than copied into this one.
        """
        direct = self._text_of(self.driver, '#js_ip_wording, .rich_media_meta_ip_wording')
        if direct:
            return direct
        try:
            els = self.driver.find_elements(By.CSS_SELECTOR, '.rich_media_meta_text')
        except Exception:
            return ''
        taken = {self.get_publish_time(), self.get_author()}
        for el in els:
            text = ' '.join(self._node_text(el).split())
            if not text or text in taken or self._DATE_RE.search(text):
                continue
            if re.fullmatch(r'[\u4e00-\u9fa5]{2,8}', text):
                return text
        return ''

    def is_original(self) -> bool:
        """Whether the article carries WeChat's 原创 mark."""
        try:
            meta = self._node_text(self.driver.find_element(By.CSS_SELECTOR, '#meta_content'))
        except Exception:
            return False
        return '原创' in meta

    def get_image_count(self) -> int:
        """How many pictures the body holds (正文图片数)."""
        try:
            return len(self.driver.find_elements(By.CSS_SELECTOR, '#js_content img, .rich_media_content img'))
        except Exception:
            return 0

    def get_content(self) -> str:
        """Extract the article body text from .rich_media_content."""
        text = re.sub(r'\n\s*\n', '\n', self._node_text(self._content_node()))
        if text:
            return text

        # Retry once after a short wait
        logger.debug(t('crawl.debug.content_retry'))
        time.sleep(0.1)
        text = re.sub(r'\n\s*\n', '\n', self._node_text(self._content_node()))
        if not text:
            logger.warning(t('crawl.wechat.no_content'))
        return text

    def _content_node(self):
        """#js_content is the real body container; .rich_media_content is the
        older spelling — both appear on live pages, in that order of trust."""
        for sel in ('#js_content', '.rich_media_content'):
            try:
                return self.driver.find_element(By.CSS_SELECTOR, sel)
            except Exception:
                continue
        logger.debug(t('crawl.debug.content_missing'))
        return None
