import logging
import re
import time
from urllib.parse import quote

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from i18n import t

from .base import Crawler

logger = logging.getLogger(__name__)


class ZhihuCrawler(Crawler):
    domain = 'www.zhihu.com'
    login_url = 'https://www.zhihu.com/signin'

    def search(self, keyword: str, target_count: int = 200, **_kwargs):
        encoded = quote(keyword)
        url = f'https://www.zhihu.com/search?q={encoded}&type=content'
        logger.info(t('crawl.zhihu.start', kw=keyword, n=target_count))
        logger.info(t('crawl.zhihu.url', url=url))
        self.driver.get(url)
        self.wait_for_element('.SearchResult-Card')
        logger.info(t('crawl.zhihu.loaded'))

        cards = self._scroll_to_load(target_count)
        logger.info(t('crawl.zhihu.cards', n=len(cards)))

        results = []
        for idx, card in enumerate(cards, 1):
            try:
                item = self._scrape_card(card)
                if item.get('作者') or item.get('正文'):
                    results.append(item)
                    logger.info(t('crawl.zhihu.processed', i=idx, n=len(results)))
                else:
                    logger.debug(t('crawl.zhihu.skipped', i=idx))
            except Exception as e:
                logger.error(t('crawl.zhihu.process_error', i=idx, err=e))

        logger.info(t('crawl.zhihu.finished', n=len(results), total=target_count))
        return results

    def _scroll_to_load(self, target_count: int, max_scrolls: int = 150):
        last_count = 0
        stuck_count = 0
        for i in range(1, max_scrolls + 1):
            self.scroll_to_bottom()
            logger.info(t('crawl.zhihu.scrolling', i=i))
            time.sleep(2)

            try:
                nm = self.driver.find_element(By.CSS_SELECTOR, '.css-7hmi9v')
                if '没有更多了' in nm.text:
                    logger.info(t('crawl.zhihu.no_more', i=i))
                    break
            except NoSuchElementException:
                pass

            cards = self.driver.find_elements(
                By.CSS_SELECTOR, '.SearchResult-Card[role="listitem"][data-za-detail-view-path-module="PostItem"]'
            )
            count = len(cards)
            logger.info(t('crawl.zhihu.scroll_round', i=i, n=count, total=target_count))

            if count >= target_count:
                logger.info(t('crawl.zhihu.target_reached', n=target_count))
                break

            if count == last_count:
                stuck_count += 1
                if stuck_count >= 3:
                    logger.info(t('crawl.zhihu.stuck', n=stuck_count))
                    break
                logger.info(t('crawl.zhihu.no_growth', n=stuck_count))
                self.scroll_to_bottom()
                time.sleep(2)
                cur = len(self.driver.find_elements(By.CSS_SELECTOR, '.SearchResult-Card'))
                if cur == last_count:
                    logger.info(t('crawl.zhihu.confirmed', n=last_count))
                    break
            else:
                stuck_count = 0

            last_count = count

        logger.info(t('crawl.zhihu.phase_done', n=len(cards)))
        return cards

    def _scrape_card(self, card):
        self._expand_full_text(card)
        return {
            '作者': self._get_author(card),
            '标题': self._get_title(card),
            '正文': self._get_content(card),
            '赞同数': self._get_vote_count(card),
            '评论数': self._get_comment_count(card),
            '发布时间': self._get_publish_time(card),
        }

    def _expand_full_text(self, card):
        try:
            btn = card.find_element(By.CSS_SELECTOR, 'button.ContentItem-more')
            self.driver.execute_script('arguments[0].scrollIntoView({block: "center"});', btn)
            btn.click()
            time.sleep(1)
        except NoSuchElementException:
            pass

    def _get_author(self, card):
        for sel in ['.AuthorInfo-name .UserLink-link', '.AuthorInfo-name']:
            try:
                return card.find_element(By.CSS_SELECTOR, sel).text.strip()
            except NoSuchElementException:
                pass
        return ''

    def _get_title(self, card):
        try:
            return card.find_element(By.CSS_SELECTOR, '.ContentItem-title a').text.strip()
        except NoSuchElementException:
            return ''

    def _get_content(self, card):
        try:
            el = card.find_element(By.CSS_SELECTOR, '.RichContent-inner .RichText')
            return self.driver.execute_script('return arguments[0].innerText', el).strip()
        except NoSuchElementException:
            return ''

    # NB: never name a local ``t`` in here — that is the i18n helper these
    # modules import, and shadowing it silently breaks any later t('…') call.
    def _get_vote_count(self, card):
        try:
            label_text = card.find_element(By.CSS_SELECTOR, '.VoteButton').text.strip()
            if '赞同' in label_text:
                m = re.search(r'(\d+(?:,\d+)*)', label_text.replace(',', ''))
                return int(m.group(1)) if m else 0
        except NoSuchElementException:
            pass
        return 0

    def _get_comment_count(self, card):
        try:
            label_text = card.find_element(By.CSS_SELECTOR, 'button[aria-label*="评论"]').text.strip()
            if '条评论' in label_text:
                m = re.search(r'(\d+(?:,\d+)*)', label_text.replace(',', ''))
                return int(m.group(1)) if m else 0
        except NoSuchElementException:
            pass
        return 0

    def _get_publish_time(self, card):
        try:
            return card.find_element(By.CSS_SELECTOR, '.ContentItem-time a, .ContentItem-time div').text.strip()
        except NoSuchElementException:
            return ''

    def get_detail(self, url: str) -> dict | None:
        self.driver.get(url)
        if not self.wait_for_element('.ContentItem-title, .QuestionHeader-title'):
            return None
        return {
            '标题': self._get_title(self.driver),
            '正文': self._get_content(self.driver),
            '赞同数': self._get_vote_count(self.driver),
            '评论数': self._get_comment_count(self.driver),
        }
