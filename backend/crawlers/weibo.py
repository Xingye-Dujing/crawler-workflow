import logging
import re
import time
from datetime import datetime, timedelta
from urllib.parse import quote

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from .base import Crawler

logger = logging.getLogger(__name__)


class WeiboCrawler(Crawler):
    domain = 'weibo.com'
    login_url = 'https://passport.weibo.com/sso/signin?entry=miniblog'

    def search(self, keyword: str, start_time: str = None, end_time: str = None, **_kwargs):
        if start_time and end_time:
            s = datetime.strptime(start_time, '%Y-%m-%d')
            e = datetime.strptime(end_time, '%Y-%m-%d')
            urls = self._generate_hourly_urls(keyword, s, e)
            logger.info('关键词: %s', keyword)
            logger.info('时间范围: %s 至 %s', s.strftime('%Y-%m-%d'), e.strftime('%Y-%m-%d'))
            logger.info('共生成 %s 个搜索链接（每小时1个）', len(urls))
        else:
            encoded = quote(keyword)
            urls = [f'https://s.weibo.com/weibo?q={encoded}&typeall=1&suball=1&Refer=g']
            logger.info('关键词: %s（无时间范围，单链接搜索）', keyword)

        total_urls = len(urls)
        all_data = []
        for idx, url in enumerate(urls, start=1):
            logger.info('')
            logger.info('=' * 80)
            logger.info('正在处理第 %s/%s 个搜索链接', idx, total_urls)
            logger.info('URL: %s', url)
            logger.info('=' * 80)

            page_data = self._scrape_single_search(url)
            logger.info('第 %s 个链接爬取完成，获取 %s 条数据', idx, len(page_data))
            all_data.extend(page_data)
            logger.info('当前累计数据: %s 条', len(all_data))

            if idx < total_urls:
                time.sleep(0.5)

        return all_data

    def _generate_hourly_urls(self, keyword: str, start: datetime, end: datetime):
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
            logger.info('访问搜索链接: %s', base_url)

            try:
                no_result = self.driver.find_element(By.CSS_SELECTOR, '.card-no-result')
                if no_result:
                    logger.info('该时间段无搜索结果，跳过')
                    return []
            except NoSuchElementException:
                pass

            logger.info('等待页面加载...')
            WebDriverWait(self.driver, 10).until(ec.presence_of_element_located((By.CSS_SELECTOR, '.card-wrap')))
            logger.info('页面加载完成')

            total_pages = self._get_total_pages()
            logger.info('检测到总页数: %s', total_pages)

            url_pattern = re.sub(r'[?&]page=\d+', '', base_url)
            sep = '&' if '?' in url_pattern else '?'
            url_pattern = f'{url_pattern}{sep}page='

            all_data = []
            for page_num in range(1, total_pages + 1):
                page_url = f'{url_pattern}{page_num}'
                logger.info('  正在爬取第 %s/%s 页...', page_num, total_pages)
                page_data = self._scrape_page_by_url(page_url)
                if not page_data:
                    logger.warning('  第 %s 页无有效卡片，跳过', page_num)
                    continue
                all_data.extend(page_data)
                logger.info('  第 %s 页爬取完成，共 %s 条，累计 %s 条', page_num, len(page_data), len(all_data))
                time.sleep(0.3)

            return all_data

        except Exception as e:
            logger.error('处理搜索链接时出错: %s', e, exc_info=True)
            return []

    def _scrape_page_by_url(self, page_url: str):
        self.driver.get(page_url)
        logger.info('    访问分页: %s', page_url)
        try:
            WebDriverWait(self.driver, 10).until(ec.presence_of_element_located((By.CSS_SELECTOR, '.card-wrap')))
        except TimeoutException:
            logger.warning('    页面加载超时，可能无内容')
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
                logger.debug('未找到页码列表，可能只有一页')
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
            logger.info('最大页码: %s', max_page)
            return max_page
        except TimeoutException:
            logger.debug('未检测到分页按钮，只有一页')
            return 1
        except Exception as e:
            logger.error('获取总页数失败: %s', e)
            return 1

    def _scrape_page(self):
        cards = self.driver.find_elements(By.CSS_SELECTOR, '.card-wrap')
        logger.info('    本页共发现 %s 个卡片', len(cards))
        page_data = []
        for idx, card in enumerate(cards, start=1):
            try:
                author = self._extract_text(card, '.name')
                if not author:
                    logger.debug('    卡片 %s: 跳过（无发布者）', idx)
                    continue
                logger.debug('    卡片 %s: 发布者="%s"', idx, author)

                publish_time = self._get_publish_time(card)
                logger.debug('    卡片 %s: 发布时间="%s"', idx, publish_time)

                text = self._get_full_text(card)
                logger.debug('    卡片 %s: 正文长度=%s', idx, len(text))

                forward = self._extract_number(self._extract_text(card, '[action-type="feed_list_forward"]'))
                comment = self._extract_number(self._extract_text(card, '[action-type="feed_list_comment"]'))
                like = self._extract_number(self._extract_text(card, '.woo-like-count'))
                logger.debug('    卡片 %s: 转发=%s 评论=%s 点赞=%s', idx, forward, comment, like)

                images = self._get_images(card)
                logger.debug('    卡片 %s: 图片=%s张', idx, len(images.split(' | ')) if images else 0)

                page_data.append(
                    {
                        '发布者': author,
                        '发布时间': publish_time,
                        '正文': text,
                        '转发数': forward,
                        '评论数': comment,
                        '点赞数': like,
                        '图片链接': images,
                    }
                )
            except Exception:
                logger.warning('    卡片 %s: 处理出错，已跳过', idx, exc_info=True)
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
