import logging
import re
import time
from urllib.parse import quote, urljoin

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from i18n import t

from .base import Crawler, as_index

logger = logging.getLogger(__name__)


class XiaohongshuCrawler(Crawler):
    domain = 'www.xiaohongshu.com'
    login_url = 'https://www.xiaohongshu.com/login'

    def search(self, keyword: str, target_count: int = 50, **_kwargs):
        resume = self.resume_of(_kwargs)
        have = self.collected()
        if have:
            # Notes fetched before the interruption are already in hand; only
            # the shortfall is left to fetch.
            logger.info(t('crawl.resume_have', n=have))
        if have >= target_count:
            logger.info(t('crawl.xhs.target_reached', n=target_count))
            return self.results()

        stored = resume.get('links')
        links = [str(u) for u in stored] if isinstance(stored, list) and resume.get('keyword') == keyword else []
        if len(links) < target_count:
            # The link list is fetched when it is missing or short. On a resume
            # with a full list this whole stage is skipped — the detail pages
            # are the expensive part, and those are what the cursor protects.
            if links:
                logger.info(t('crawl.resume_links', n=len(links)))
            self._open_search(keyword, target_count)
            fresh = self._collect_links(target_count)
            known = set(links)
            links.extend(u for u in fresh if u not in known)
        logger.info(t('crawl.xhs.links', n=len(links)))

        start_index = as_index(resume.get('link_index'))
        self.mark_position(keyword=keyword, links=links, link_index=start_index, done=have)

        for idx, link in enumerate(links, start=1):
            if idx <= start_index:
                continue
            if self.collected() >= target_count:
                logger.info(t('crawl.xhs.target_reached', n=target_count))
                break
            logger.info(t('crawl.xhs.note_processing', i=idx, total=len(links), url=link))
            try:
                data = self._scrape_note(link)
                if data:
                    if self.emit(data):
                        title_preview = data['标题'][:30] if data['标题'] else t('crawl.xhs.untitled')
                        logger.info(t('crawl.xhs.note_ok', title=title_preview))
                    else:
                        logger.debug(t('crawl.xhs.note_dup', url=link))
                else:
                    logger.warning(t('crawl.xhs.note_fail', url=link))
            except Exception as e:
                logger.error(t('crawl.xhs.note_error', err=e), exc_info=True)
            # Index and item advance together, so a resumed crawl goes straight
            # to the first note it has not fetched.
            self.mark_position(link_index=idx, done=self.collected())
            time.sleep(0.1)

        logger.info(t('crawl.xhs.finished', n=self.collected()))
        return self.results()

    def _open_search(self, keyword: str, target_count: int):
        logger.info(t('crawl.xhs.start', kw=keyword, n=target_count))
        encoded = quote(keyword)
        url = f'https://www.xiaohongshu.com/search_result?keyword={encoded}&source=web_explore_feed&type=51'
        self.driver.get(url)
        logger.info(t('crawl.xhs.url', url=url))
        try:
            WebDriverWait(self.driver, 15).until(ec.presence_of_element_located((By.CSS_SELECTOR, '.note-item')))
            logger.info(t('crawl.xhs.page_ready'))
        except TimeoutException:
            logger.warning(t('crawl.xhs.page_timeout'))

    def _collect_links(self, target_count: int, max_scrolls: int = 100):
        logger.info(t('crawl.xhs.collect_start', n=target_count))
        all_links = set()
        last_count = 0

        for scroll_iter in range(max_scrolls):
            logger.info(t('crawl.xhs.scroll_round', i=scroll_iter + 1, total=max_scrolls))
            self.scroll_to_bottom()

            # (The old code wrapped a log call in try/except NoSuchElementException
            # and then broke unconditionally, so only the first screenful was ever
            # collected and target_count was ignored. End-of-list is detected by
            # the "no growth" branch below instead.)
            cards = self.driver.find_elements(By.CSS_SELECTOR, '.note-item')
            current_count = len(cards)
            logger.info(t('crawl.xhs.cards', n=current_count))

            for card in cards:
                try:
                    a = card.find_element(By.CSS_SELECTOR, '.cover.mask, .title a')
                    h = a.get_attribute('href')
                    if h:
                        all_links.add(urljoin('https://www.xiaohongshu.com', h))
                except NoSuchElementException:
                    pass

            logger.info(t('crawl.xhs.collected', n=len(all_links)))

            if len(all_links) >= target_count:
                logger.info(t('crawl.xhs.target_reached', n=target_count))
                break

            if current_count == last_count:
                logger.info(t('crawl.xhs.no_growth'))
                time.sleep(0.1)
                self.scroll_to_bottom()
                cur = len(self.driver.find_elements(By.CSS_SELECTOR, '.note-item'))
                if cur == last_count:
                    logger.info(t('crawl.xhs.exhausted'))
                    break

            last_count = current_count

        result = list(all_links)[:target_count]
        logger.info(t('crawl.xhs.collect_done', n=len(result)))
        return result

    def _scrape_note(self, url: str) -> dict | None:
        logger.info(t('crawl.xhs.detail_visit', url=url))
        self.driver.get(url)
        try:
            WebDriverWait(self.driver, 15).until(
                ec.presence_of_element_located((By.CSS_SELECTOR, '.title, #detail-title'))
            )
            logger.info(t('crawl.xhs.detail_ready'))
        except TimeoutException:
            logger.warning(t('crawl.xhs.detail_timeout'))
            return None
        time.sleep(0.1)

        title = ''
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, '#detail-title, .title')
            title = el.text.strip()
            preview = title[:40] + '...' if len(title) > 40 else title
            logger.info(t('crawl.xhs.title', title=preview))
        except NoSuchElementException:
            logger.debug(t('crawl.debug.title_missing'))

        content = ''
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, '#detail-desc .note-text, .desc .note-text')
            content = self.driver.execute_script(
                "return arguments[0].innerText || arguments[0].textContent || ''", el
            ).strip()
            logger.info(t('crawl.xhs.content_len', n=len(content)))
        except NoSuchElementException:
            logger.debug(t('crawl.debug.content_missing'))

        author = ''
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, '.author-container .name, .author .name')
            author = el.text.strip()
            logger.info(t('crawl.xhs.author', author=author))
        except NoSuchElementException:
            logger.debug(t('crawl.debug.author_missing'))

        pub_time = ''
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, '.date, .publish-time')
            pub_time = el.text.strip()
            logger.info(t('crawl.xhs.pub_time', time=pub_time))
        except NoSuchElementException:
            logger.debug(t('crawl.debug.time_missing'))

        like_count = self._extract_count('.like-wrapper .count, .engage-bar .like-wrapper .count')
        collect_count = self._extract_count('.collect-wrapper .count, .engage-bar .collect-wrapper .count')
        comment_count = self._extract_count('.chat-wrapper .count, .engage-bar .chat-wrapper .count')
        logger.info(t('crawl.xhs.metrics', likes=like_count, favs=collect_count, comments=comment_count))

        comments = self.extract_comments(max_comments=5)
        logger.info(t('crawl.xhs.comment_count', n=len(comments)))

        return {
            '笔记链接': url,
            '标题': title,
            '正文': content,
            '作者': author,
            '发布时间': pub_time,
            '点赞数': like_count,
            '收藏数': collect_count,
            '评论数': comment_count,
            '评论列表': comments,
        }

    def _extract_count(self, selector: str) -> int:
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, selector)
            text = el.text.strip()
            return self._extract_count_from_text(text)
        except NoSuchElementException:
            return 0

    @staticmethod
    def _extract_count_from_text(text: str) -> int:
        if not text:
            return 0
        text = text.strip()
        m = re.match(r'([\d.]+)(万|千)?', text)
        if m:
            num = float(m.group(1))
            unit = m.group(2)
            if unit == '万':
                num *= 10000
            elif unit == '千':
                num *= 1000
            return int(num)
        m = re.search(r'(\d+)', text)
        return int(m.group(1)) if m else 0

    def extract_comments(self, max_comments: int = 5):
        logger.info(t('crawl.xhs.comment_start', n=max_comments))
        comments = []
        try:
            comment_items = WebDriverWait(self.driver, 10).until(
                ec.presence_of_all_elements_located((By.CSS_SELECTOR, '.comment-item, .parent-comment'))
            )
            logger.info(t('crawl.xhs.comment_found', n=len(comment_items)))
        except TimeoutException:
            logger.debug(t('crawl.debug.comments_missing'))
            return comments

        for idx, item in enumerate(comment_items[:max_comments]):
            try:
                comment_author = ''
                try:
                    author_elem = item.find_element(By.CSS_SELECTOR, '.name')
                    comment_author = author_elem.text.strip()
                except NoSuchElementException:
                    pass

                comment_content = ''
                try:
                    content_elem = item.find_element(By.CSS_SELECTOR, '.content .note-text')
                    comment_content = self.driver.execute_script(
                        "return arguments[0].innerText || arguments[0].textContent || ''",
                        content_elem,
                    ).strip()
                except NoSuchElementException:
                    try:
                        content_elem = item.find_element(By.CSS_SELECTOR, '.content')
                        comment_content = self.driver.execute_script(
                            "return arguments[0].innerText || arguments[0].textContent || ''",
                            content_elem,
                        ).strip()
                    except NoSuchElementException:
                        pass

                like_count = 0
                try:
                    like_elem = item.find_element(By.CSS_SELECTOR, '.like .count')
                    like_count = self._extract_count_from_text(like_elem.text)
                except NoSuchElementException:
                    pass

                comment_time = ''
                try:
                    time_elem = item.find_element(By.CSS_SELECTOR, '.date')
                    comment_time = time_elem.text.strip()
                except NoSuchElementException:
                    pass

                if comment_content:
                    comments.append(
                        {
                            '评论者': comment_author,
                            '评论内容': comment_content,
                            '点赞数': like_count,
                            '评论时间': comment_time,
                        }
                    )
                    logger.debug(
                        t(
                            'crawl.debug.comment_item',
                            i=idx + 1,
                            author=comment_author,
                            text=comment_content[:20],
                        )
                    )
            except Exception as e:
                logger.error(t('crawl.xhs.comment_error', i=idx + 1, err=e))

        logger.info(t('crawl.xhs.comment_done', n=len(comments)))
        return comments

    def get_detail(self, url: str) -> dict | None:
        return self._scrape_note(url)
