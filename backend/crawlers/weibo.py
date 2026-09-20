import logging
import re
import time
from datetime import datetime, timedelta
from urllib.parse import quote

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from i18n import t

from .base import Crawler, as_index

logger = logging.getLogger(__name__)


class WeiboCrawler(Crawler):
    domain = 'weibo.com'
    login_url = 'https://passport.weibo.com/sso/signin?entry=miniblog'

    # An hourly-window crawl loads one page per hour of the range, so two years
    # would be ~17 500 page loads — a run that never ends. Past this many
    # windows the range is refused instead of started.
    MAX_HOURLY_WINDOWS = 720

    @staticmethod
    def _parse_date(value: str) -> datetime:
        try:
            return datetime.strptime(str(value).strip(), '%Y-%m-%d')
        except ValueError as e:
            # The field is free text ("2026-01-01"); a typo used to crash the
            # node with a bare strptime error.
            raise ValueError(t('crawl.weibo.bad_date', value=value)) from e

    def search(self, keyword: str, start_time: str = None, end_time: str = None, **_kwargs):
        resume = self.resume_of(_kwargs)
        stored = resume.get('urls')
        # This crawl is a walk over a URL list, so the list plus the index into
        # it *is* the resume point. It is reused when the keyword still matches;
        # otherwise it is rebuilt from the (validated) dates.
        if isinstance(stored, list) and stored and resume.get('keyword') == keyword:
            urls = [str(u) for u in stored]
            logger.info(t('crawl.resume_urls', n=len(urls)))
        else:
            urls = self._build_urls(keyword, start_time, end_time)

        have = self.collected()
        if have:
            logger.info(t('crawl.resume_have', n=have))

        start_index = as_index(resume.get('url_index'))
        total_urls = len(urls)
        self.mark_position(keyword=keyword, urls=urls, url_index=start_index, url_total=total_urls, done=have)

        for idx, url in enumerate(urls, start=1):
            if idx <= start_index:
                continue
            logger.info('')
            logger.info('=' * 80)
            logger.info(t('crawl.weibo.processing', i=idx, total=total_urls))
            logger.info(t('crawl.weibo.url', url=url))
            logger.info('=' * 80)

            page_data = self._scrape_single_search(url)
            logger.info(t('crawl.weibo.link_done', i=idx, n=len(page_data)))
            logger.info(t('crawl.weibo.accumulated', n=self.collected()))
            # Position after each window: a kill here costs at most the window
            # in flight, never the windows already walked.
            self.mark_position(url_index=idx, done=self.collected())

            if idx < total_urls:
                time.sleep(0.5)

        return self.results()

    def _build_urls(self, keyword: str, start_time: str, end_time: str) -> list:
        if start_time or end_time:
            # One bound alone used to be ignored silently, which quietly ran a
            # completely different (unbounded) search.
            if not (start_time and end_time):
                raise ValueError(t('crawl.weibo.need_both_dates'))
            start = self._parse_date(start_time)
            end = self._parse_date(end_time)
            if end <= start:
                raise ValueError(t('crawl.weibo.bad_range', start=start_time, end=end_time))
            urls = self._generate_hourly_urls(keyword, start, end)
            logger.info(t('crawl.weibo.keyword', kw=keyword))
            logger.info(t('crawl.weibo.range', start=start.strftime('%Y-%m-%d'), end=end.strftime('%Y-%m-%d')))
            logger.info(t('crawl.weibo.links', n=len(urls)))
            return urls
        encoded = quote(keyword)
        logger.info(t('crawl.weibo.keyword_plain', kw=keyword))
        return [f'https://s.weibo.com/weibo?q={encoded}&typeall=1&suball=1&Refer=g']

    def _generate_hourly_urls(self, keyword: str, start: datetime, end: datetime):
        windows = int((end - start).total_seconds() // 3600) + 1
        if windows > self.MAX_HOURLY_WINDOWS:
            raise ValueError(t('crawl.weibo.range_too_wide', n=windows, max=self.MAX_HOURLY_WINDOWS))
        urls = []
        cur = start
        while cur < end:
            nxt = min(cur + timedelta(hours=1), end)
            ss = cur.strftime('%Y-%m-%d-%H')
            es = nxt.strftime('%Y-%m-%d-%H')
            encoded = quote(keyword)
            urls.append(
                f'https://s.weibo.com/weibo?q={encoded}&typeall=1&suball=1&timescope=custom%3A{ss}%3A{es}&Refer=g'
            )
            cur = nxt
        return urls

    def _scrape_single_search(self, base_url: str):
        try:
            self.driver.get(base_url)
            logger.info(t('crawl.weibo.visiting', url=base_url))

            try:
                no_result = self.driver.find_element(By.CSS_SELECTOR, '.card-no-result')
                if no_result:
                    logger.info(t('crawl.weibo.no_result'))
                    return []
            except NoSuchElementException:
                pass

            logger.info(t('crawl.weibo.waiting'))
            WebDriverWait(self.driver, 10).until(ec.presence_of_element_located((By.CSS_SELECTOR, '.card-wrap')))
            logger.info(t('crawl.weibo.page_loaded'))

            total_pages = self._get_total_pages()
            logger.info(t('crawl.weibo.total_pages', n=total_pages))

            url_pattern = re.sub(r'[?&]page=\d+', '', base_url)
            sep = '&' if '?' in url_pattern else '?'
            url_pattern = f'{url_pattern}{sep}page='

            all_data = []
            for page_num in range(1, total_pages + 1):
                page_url = f'{url_pattern}{page_num}'
                logger.info(t('crawl.weibo.page_crawling', i=page_num, total=total_pages))
                page_data = self._scrape_page_by_url(page_url)
                if not page_data:
                    logger.warning(t('crawl.weibo.page_empty', i=page_num))
                    continue
                all_data.extend(page_data)
                logger.info(t('crawl.weibo.page_done', i=page_num, n=len(page_data), total=len(all_data)))
                time.sleep(0.3)

            return all_data

        except Exception as e:
            logger.error(t('crawl.weibo.link_error', err=e), exc_info=True)
            return []

    def _scrape_page_by_url(self, page_url: str):
        self.driver.get(page_url)
        logger.info(t('crawl.weibo.page_visit', url=page_url))
        try:
            WebDriverWait(self.driver, 10).until(ec.presence_of_element_located((By.CSS_SELECTOR, '.card-wrap')))
        except TimeoutException:
            logger.warning(t('crawl.weibo.page_timeout'))
            return []
        self.driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(0.3)
        return self._scrape_page()

    def _get_total_pages(self):
        try:
            page_more_btn = WebDriverWait(self.driver, 1).until(
                ec.presence_of_element_located((By.CSS_SELECTOR, 'a[action-type="feed_list_page_more"]'))
            )
            self.driver.execute_script('arguments[0].scrollIntoView();', page_more_btn)
            time.sleep(0.3)
            page_more_btn.click()
            time.sleep(0.5)

            page_list = self.driver.find_elements(By.CSS_SELECTOR, 'ul[node-type="feed_list_page_morelist"] li a')
            if not page_list:
                logger.debug(t('crawl.debug.page_list_missing'))
                return 1

            max_page = 1
            for link in page_list:
                href = link.get_attribute('href')
                if href and 'page=' in href:
                    try:
                        p = int(href.split('page=')[-1].split('&')[0])
                        max_page = max(max_page, p)
                    except ValueError:
                        pass
            page_more_btn.click()
            logger.info(t('crawl.weibo.max_page', n=max_page))
            return max_page
        except TimeoutException:
            logger.debug(t('crawl.debug.pager_missing'))
            return 1
        except Exception as e:
            logger.error(t('crawl.weibo.pages_fail', err=e))
            return 1

    def _scrape_page(self):
        cards = self.driver.find_elements(By.CSS_SELECTOR, '.card-wrap')
        logger.info(t('crawl.weibo.page_cards', n=len(cards)))
        page_data = []
        for idx, card in enumerate(cards, start=1):
            try:
                author = self._extract_text(card, '.name')
                if not author:
                    logger.debug(t('crawl.debug.card_skip', i=idx))
                    continue
                logger.debug(t('crawl.debug.card_author', i=idx, v=author))

                publish_time = self._get_publish_time(card)
                logger.debug(t('crawl.debug.card_time', i=idx, v=publish_time))

                text = self._get_full_text(card)
                logger.debug(t('crawl.debug.card_len', i=idx, v=len(text)))

                forward = self._extract_number(self._extract_text(card, '[action-type="feed_list_forward"]'))
                comment = self._extract_number(self._extract_text(card, '[action-type="feed_list_comment"]'))
                like = self._extract_number(self._extract_text(card, '.woo-like-count'))
                logger.debug(t('crawl.debug.card_metrics', i=idx, f=forward, c=comment, l=like))

                images = self._get_images(card)
                logger.debug(t('crawl.debug.card_images', i=idx, n=len(images.split(' | ')) if images else 0))

                item = {
                    '发布者': author,
                    '发布时间': publish_time,
                    '正文': text,
                    '转发数': forward,
                    '评论数': comment,
                    '点赞数': like,
                    '图片链接': images,
                }
                page_data.append(item)
                # Handed over the moment it is scraped: this page's items are on
                # disk before the next card is even looked at.
                self.emit(item)
            except Exception:
                logger.warning(t('crawl.weibo.card_error', i=idx), exc_info=True)
                continue
        return page_data

    def _extract_text(self, el, sel, default=''):
        try:
            return el.find_element(By.CSS_SELECTOR, sel).text.strip()
        except Exception:
            return default

    def _extract_number(self, text):
        if not text:
            return 0
        m = re.search(r'(\d+(?:,\d+)*)', text.replace(',', ''))
        return int(m.group(1)) if m else 0

    def _get_publish_time(self, card):
        try:
            return card.find_element(By.CSS_SELECTOR, '.from a').text.strip()
        except Exception:
            return ''

    def _get_full_text(self, card):
        for sel in ['[node-type="feed_list_content_full"]', '[node-type="feed_list_content"]']:
            try:
                els = card.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    t = self.driver.execute_script(
                        'return arguments[0].innerText || arguments[0].textContent || ""',
                        els[0],
                    ).strip()
                    if t:
                        return t
            except Exception:
                continue
        try:
            return card.find_element(By.CSS_SELECTOR, '.content > div').text.strip()
        except Exception:
            return ''

    def _get_images(self, card):
        urls = []
        try:
            for img in card.find_elements(By.CSS_SELECTOR, '.media-piclist img'):
                src = img.get_attribute('src')
                if src:
                    urls.append(src)
        except Exception:
            pass
        return ' | '.join(urls)

    def get_detail(self, url: str) -> dict | None:
        return None
