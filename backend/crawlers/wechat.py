import logging
import re
import time
from urllib.parse import parse_qs, urlparse

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from i18n import t

from .base import Crawler, as_index
from .comments import WECHAT_CREDENTIAL_FIELDS, WECHAT_CREDENTIAL_SCRIPT

logger = logging.getLogger(__name__)


def _safe_current_url(driver) -> str:
    """``current_url`` that never raises on a dead or test double driver."""
    try:
        return str(driver.current_url or '')
    except Exception:
        return ''


def _url_params(url: str) -> dict:
    """Query parameters of an article URL. A repeated key keeps all its values,
    because the comment tokens WeChat hands out are not always single-valued."""
    try:
        return parse_qs(urlparse(str(url or '')).query)
    except ValueError:
        return {}


class WechatCrawler(Crawler):
    """WeChat official account article crawler.

    Scrapes public WeChat article pages for title, author, publish time,
    content, read count, like count, and reward count.
    """

    domain = 'mp.weixin.qq.com'
    # Real URLS: they can be used during the test.
    # https://mp.weixin.qq.com/s/cAx1zGfT2MzqpwnhULmSQA
    # https://mp.weixin.qq.com/s/q59mL_dHixC97p19RpcfVQ
    # https://mp.weixin.qq.com/s/f_2nB7u7pQApgIoPsBKMQg
    login_url = 'https://mp.weixin.qq.com/'

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
                            reads=data.get('阅读数', '?'),
                            likes=data.get('在看数', '?'),
                            rewards=data.get('赞赏数', '?'),
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

        read_num = self.get_read_count()
        logger.info(t('crawl.wechat.reads', n=read_num))

        like_num = self.get_like_count()
        logger.info(t('crawl.wechat.likes', n=like_num))

        reward_num = self.get_reward_count()
        logger.info(t('crawl.wechat.rewards', n=reward_num))

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
            '正文': content[:5000] + ('...' if len(content) > 5000 else ''),
            '正文图片数': self.get_image_count(),
            '阅读数': read_num,
            '在看数': like_num,
            '赞赏数': reward_num,
            '链接': url,
        }

    # ------------------------------------------------------------------
    # Comment credentials (and why a browser usually has none)
    # ------------------------------------------------------------------

    #: The comment-call parameters the article page exposes. The script and its
    #: field list live in ``crawlers.comments`` next to the adapter that uses
    #: them, so the cookie diagnosis and the crawl can never disagree about what
    #: "reachable" means. ``key`` is the one that matters: the server embeds it
    #: only for a client-issued visit, and without it the comment list stays
    #: empty — "not permitted", never "no comments".
    _CREDENTIAL_SCRIPT = WECHAT_CREDENTIAL_SCRIPT

    def article_credentials(self) -> dict:
        """Read the comment-call parameters the current page exposes.

        Never raises: a page that cannot answer (still loading, verification
        interstitial, dead session) simply yields empty credentials, which the
        caller reports as "credential absent" rather than as a scrape error.
        """
        try:
            raw = self.driver.execute_script(self._CREDENTIAL_SCRIPT) or {}
        except Exception:
            raw = {}
        creds = {key: str(raw.get(key) or '') for key in WECHAT_CREDENTIAL_FIELDS}
        # Older article templates define none of those globals but always carry
        # the same tokens in the address, so the URL is the fallback source.
        params = _url_params(_safe_current_url(self.driver))
        for field, param in (
            ('__biz', 'biz'),
            ('mid', 'mid'),
            ('idx', 'idx'),
            ('sn', 'sn'),
            ('pass_ticket', 'pass_ticket'),
        ):
            if not creds[param] and params.get(field):
                creds[param] = str(params[field][0])
        return creds

    def rendered_comment_count(self) -> int:
        """How many comments this session can already see in the page.

        ``.discuss_list`` is the container WeChat fills; an empty one under
        ``discuss_data_empty`` is the shape of "not permitted", which has to be
        distinguishable from "the author turned comments off".
        """
        best = 0
        for selector in ('.discuss_list .item', '#js_cmt_area .appmsg_comment', '.discuss_list > li'):
            try:
                best = max(best, len(self.driver.find_elements(By.CSS_SELECTOR, selector)))
            except Exception:
                continue
        return best

    def diagnose(self, url: str = '') -> dict:
        """Two WeChat capabilities, checked separately, because they are gated
        by two different things: 文章搜索 needs an MP-admin session, 评论 needs a
        client-copied article link. One cookie file serves both, so the panel has
        to be able to say which of the two the user actually has.
        """
        facts = {'platform': self.domain, 'url': '', 'login_wall': False}
        # 1. The 公众平台 admin session: logged in, the login page redirects to
        # /cgi-bin/home with a token; logged out it stays on the QR page.
        self.driver.get(self.login_url)
        admin_url = _safe_current_url(self.driver)
        facts['mp_logged_in'] = 'token=' in admin_url
        facts['url'] = admin_url
        facts['login_wall'] = not facts['mp_logged_in']
        # 2. The article's comment credential, if an article link was supplied.
        article = str(url or '').strip()
        if article:
            self.driver.get(article)
            creds = self.article_credentials()
            facts['url'] = _safe_current_url(self.driver) or article
            facts['has_pass_ticket'] = bool(creds['pass_ticket'])
            facts['show_comment'] = creds['show_comment']
            facts['comment_key'] = creds['key']
            facts['comment_id'] = creds['comment_id']
            facts['comment_visible'] = self.rendered_comment_count()
            facts['body_readable'] = self._element_or_none('#rich_media_content, .rich_media_content') is not None
        return facts

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

    def get_read_count(self) -> int:
        """Extract the read count (阅读数)."""
        selectors = ['#read_num', '.read_num', 'span[class*="read"]']
        count = self._extract_number(selectors)
        if count > 0:
            return count

        # Fallback: try clicking a "read more" button to reveal hidden stats
        try:
            read_btn = self.driver.find_element(By.CSS_SELECTOR, '.read_more')
            logger.debug(t('crawl.debug.read_more'))
            self.driver.execute_script('arguments[0].scrollIntoView();', read_btn)
            read_btn.click()
            time.sleep(0.1)
            count = self._extract_number(selectors)
            if count > 0:
                return count
        except Exception:
            pass

        logger.debug(t('crawl.debug.reads_missing'))
        return 0

    def get_like_count(self) -> int:
        """Extract the like / 在看 count."""
        selectors = ['#like_num', '.like_num', 'span[class*="like"]']
        count = self._extract_number(selectors)
        if count == 0:
            logger.debug(t('crawl.debug.likes_missing'))
        return count

    def get_reward_count(self) -> int:
        """Extract the reward / tip count (赞赏数)."""
        count = self._extract_number(['.reward_num'])
        if count == 0:
            logger.debug(t('crawl.debug.rewards_missing'))
        return count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_number(self, selectors) -> int:
        """Search for a numeric value using the provided list of CSS selectors."""
        for sel in selectors:
            try:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
            except Exception:
                continue
            for el in els:
                text = self._node_text(el)
                match = re.search(r'(\d+(?:\.\d+)?)(万|w)?', text.replace(',', ''))
                if not match:
                    continue
                value = float(match.group(1))
                if match.group(2):
                    value *= 10000
                return int(value)
        return 0
