import logging
import re
import time

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from i18n import t

from .base import Crawler

logger = logging.getLogger(__name__)


class WechatCrawler(Crawler):
    """WeChat official account article crawler.

    Scrapes public WeChat article pages for title, author, publish time,
    content, read count, like count, and reward count.
    """

    domain = 'mp.weixin.qq.com'
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

        results = []
        total = len(urls)
        logger.info('=' * 70)
        logger.info(t('crawl.wechat.batch_start', n=total))
        logger.info('=' * 70)

        for idx, url in enumerate(urls, start=1):
            logger.info('')
            logger.info(t('crawl.wechat.processing', i=idx, total=total))
            logger.info(t('crawl.wechat.url', url=url))

            data = self.get_detail(url)
            if data:
                results.append(data)
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
                logger.warning(t('crawl.wechat.failed', i=idx, total=total))

            if idx < total:
                logger.info(t('crawl.wechat.wait'))
                time.sleep(0.1)

        logger.info('')
        logger.info('=' * 70)
        logger.info(t('crawl.wechat.batch_done', n=len(results), total=total))
        logger.info('=' * 70)
        return results

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
            logger.warning(t('crawl.wechat.timeout', url=url))
            return None

        # Scroll to bottom to trigger lazy-loaded elements (read counts, etc.)
        logger.info(t('crawl.wechat.scroll'))
        self.driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(0.1)
        logger.info(t('crawl.wechat.scroll_done'))

        # ---- Extract fields ----
        logger.info(t('crawl.wechat.extracting'))

        title = self.get_article_title()
        logger.info(t('crawl.wechat.title', title=title or '(empty)'))

        author = self.get_author()
        logger.info(t('crawl.wechat.author', author=author or '(empty)'))

        pub_time = self.get_publish_time()
        logger.info(t('crawl.wechat.pub_time', time=pub_time or '(empty)'))

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
            '正文': content[:5000] + ('...' if len(content) > 5000 else ''),
            '阅读数': read_num,
            '在看数': like_num,
            '赞赏数': reward_num,
            '链接': url,
        }

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
        try:
            sub = element.find_element(By.CSS_SELECTOR, selector)
            return sub.text.strip()
        except NoSuchElementException:
            return default

    def get_article_title(self) -> str:
        """Extract article title from #activity-name."""
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, '#activity-name')
            return el.text.strip()
        except NoSuchElementException:
            logger.debug('Title element not found.')
            return ''

    def get_author(self) -> str:
        """Extract the official account name (公众号)."""
        selectors = ['#js_name', '#profileBt a', '.rich_media_meta_nickname a']
        for sel in selectors:
            try:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    text = els[0].text.strip()
                    if text:
                        return text
            except Exception:
                continue
        logger.debug('Author element not found with any selector.')
        return ''

    def get_publish_time(self) -> str:
        """Extract the article publish time."""
        selectors = ['#publish_time', '#meta_content .rich_media_meta_text']
        for sel in selectors:
            try:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    text = el.text.strip()
                    # Only return text that looks like a date
                    if re.search(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', text):
                        return text
            except Exception:
                continue
        logger.debug('Publish time element not found.')
        return ''

    def get_content(self) -> str:
        """Extract the article body text from .rich_media_content."""
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, '.rich_media_content')
            text = self.driver.execute_script(
                "return arguments[0].innerText || arguments[0].textContent || ''",
                el,
            ).strip()
            text = re.sub(r'\n\s*\n', '\n', text)
            if text:
                return text
        except NoSuchElementException:
            logger.debug('Content element not found on first attempt.')

        # Retry once after a short wait
        logger.debug('Retrying content extraction after 2 s...')
        time.sleep(0.1)
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, '.rich_media_content')
            text = self.driver.execute_script(
                "return arguments[0].innerText || arguments[0].textContent || ''",
                el,
            ).strip()
            text = re.sub(r'\n\s*\n', '\n', text)
            return text
        except NoSuchElementException:
            logger.warning(t('crawl.wechat.no_content'))
            return ''

    def get_read_count(self) -> int:
        """Extract the read count (阅读数)."""
        selectors = ['#read_num', '.read_num', 'span[class*="read"]']
        count = self._extract_number(selectors)
        if count > 0:
            return count

        # Fallback: try clicking a "read more" button to reveal hidden stats
        try:
            read_btn = self.driver.find_element(By.CSS_SELECTOR, '.read_more')
            logger.debug('Clicking .read_more to reveal read count...')
            self.driver.execute_script('arguments[0].scrollIntoView();', read_btn)
            read_btn.click()
            time.sleep(0.1)
            count = self._extract_number(selectors)
            if count > 0:
                return count
        except Exception:
            pass

        logger.debug('Read count not found.')
        return 0

    def get_like_count(self) -> int:
        """Extract the like / 在看 count."""
        selectors = ['#like_num', '.like_num', 'span[class*="like"]']
        count = self._extract_number(selectors)
        if count == 0:
            logger.debug('Like count not found.')
        return count

    def get_reward_count(self) -> int:
        """Extract the reward / tip count (赞赏数)."""
        count = self._extract_number(['.reward_num'])
        if count == 0:
            logger.debug('Reward count not found.')
        return count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_number(self, selectors) -> int:
        """Search for a numeric value using the provided list of CSS selectors."""
        for sel in selectors:
            try:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    text = els[0].text.strip()
                    match = re.search(r'(\d+)', text.replace(',', ''))
                    if match:
                        return int(match.group(1))
            except Exception:
                continue
        return 0
