import logging
import re
import time
from urllib.parse import quote, urljoin

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from .base import Crawler

logger = logging.getLogger(__name__)


class XiaohongshuCrawler(Crawler):
    domain = 'www.xiaohongshu.com'
    login_url = 'https://www.xiaohongshu.com/login'

    def search(self, keyword: str, target_count: int = 50, **_kwargs):
        logger.info('[小红书搜索] 开始搜索关键词: "%s", 目标数量: %s', keyword, target_count)
        encoded = quote(keyword)
        url = f'https://www.xiaohongshu.com/search_result?keyword={encoded}&source=web_explore_feed&type=51'
        self.driver.get(url)
        logger.info('[小红书搜索] 已访问搜索URL: %s', url)
        try:
            WebDriverWait(self.driver, 15).until(ec.presence_of_element_located((By.CSS_SELECTOR, '.note-item')))
            logger.info('[小红书搜索] 初始搜索结果页加载完成')
        except TimeoutException:
            logger.warning('[小红书搜索] 初始内容加载超时，可能没有搜索结果，将继续尝试滚动')

        links = self._collect_links(target_count)
        logger.info('[小红书搜索] 共收集到 %s 条笔记链接', len(links))

        results = []
        for idx, link in enumerate(links, 1):
            logger.info('[小红书搜索] 正在处理第 %s/%s 条笔记: %s', idx, len(links), link)
            try:
                data = self._scrape_note(link)
                if data:
                    results.append(data)
                    title_preview = data['标题'][:30] if data['标题'] else '无标题'
                    logger.info('[小红书搜索] 成功提取: %s...', title_preview)
                else:
                    logger.warning('[小红书搜索] 提取失败: %s', link)
            except Exception as e:
                logger.error('[小红书搜索] 处理笔记时出错: %s', e, exc_info=True)
            time.sleep(0.1)

        logger.info('[小红书搜索] 搜索完成，共获取 %s 条有效笔记数据', len(results))
        return results

    def _collect_links(self, target_count: int, max_scrolls: int = 100):
        logger.info('[收集链接] 开始滚动收集笔记链接，目标: %s 条', target_count)
        all_links = set()
        last_count = 0

        for scroll_iter in range(max_scrolls):
            logger.info('[收集链接] 第 %s/%s 次滚动', scroll_iter + 1, max_scrolls)
            self.scroll_to_bottom()

            try:
                logger.info('[收集链接] 检测到"没有更多了"，停止加载')
                break
            except NoSuchElementException:
                pass

            cards = self.driver.find_elements(By.CSS_SELECTOR, '.note-item')
            current_count = len(cards)
            logger.info('[收集链接] 滚动后卡片数量: %s', current_count)

            for card in cards:
                try:
                    a = card.find_element(By.CSS_SELECTOR, '.cover.mask, .title a')
                    h = a.get_attribute('href')
                    if h:
                        all_links.add(urljoin('https://www.xiaohongshu.com', h))
                except NoSuchElementException:
                    pass

            logger.info('[收集链接] 当前已收集链接数: %s', len(all_links))

            if len(all_links) >= target_count:
                logger.info('[收集链接] 已达到目标数量 %s，停止加载', target_count)
                break

            if current_count == last_count:
                logger.info('[收集链接] 卡片数量未增加，尝试再次滚动...')
                time.sleep(0.1)
                self.scroll_to_bottom()
                cur = len(self.driver.find_elements(By.CSS_SELECTOR, '.note-item'))
                if cur == last_count:
                    logger.info('[收集链接] 页面已无更多内容，停止加载')
                    break

            last_count = current_count

        result = list(all_links)[:target_count]
        logger.info('[收集链接] 收集完成，共 %s 条链接', len(result))
        return result

    def _scrape_note(self, url: str) -> dict | None:
        logger.info('[爬取详情] 正在访问详情页: %s', url)
        self.driver.get(url)
        try:
            WebDriverWait(self.driver, 15).until(
                ec.presence_of_element_located((By.CSS_SELECTOR, '.title, #detail-title'))
            )
            logger.info('[爬取详情] 详情页加载完成')
        except TimeoutException:
            logger.warning('[爬取详情] 详情页加载超时')
            return None
        time.sleep(0.1)

        title = ''
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, '#detail-title, .title')
            title = el.text.strip()
            preview = title[:40] + '...' if len(title) > 40 else title
            logger.info('[爬取详情] 标题: %s', preview)
        except NoSuchElementException:
            logger.debug('[爬取详情] 未找到标题元素')

        content = ''
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, '#detail-desc .note-text, .desc .note-text')
            content = self.driver.execute_script(
                "return arguments[0].innerText || arguments[0].textContent || ''", el
            ).strip()
            logger.info('[爬取详情] 正文长度: %s 字', len(content))
        except NoSuchElementException:
            logger.debug('[爬取详情] 未找到正文元素')

        author = ''
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, '.author-container .name, .author .name')
            author = el.text.strip()
            logger.info('[爬取详情] 作者: %s', author)
        except NoSuchElementException:
            logger.debug('[爬取详情] 未找到作者元素')

        pub_time = ''
        try:
            el = self.driver.find_element(By.CSS_SELECTOR, '.date, .publish-time')
            pub_time = el.text.strip()
            logger.info('[爬取详情] 发布时间: %s', pub_time)
        except NoSuchElementException:
            logger.debug('[爬取详情] 未找到发布时间元素')

        like_count = self._extract_count('.like-wrapper .count, .engage-bar .like-wrapper .count')
        collect_count = self._extract_count('.collect-wrapper .count, .engage-bar .collect-wrapper .count')
        comment_count = self._extract_count('.chat-wrapper .count, .engage-bar .chat-wrapper .count')
        logger.info(
            '[爬取详情] 互动数据 - 点赞: %s, 收藏: %s, 评论数: %s',
            like_count,
            collect_count,
            comment_count,
        )

        comments = self.extract_comments(max_comments=5)
        logger.info('[爬取详情] 评论列表: %s 条', len(comments))

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
        logger.info('[提取评论] 开始提取评论，最多 %s 条', max_comments)
        comments = []
        try:
            comment_items = WebDriverWait(self.driver, 10).until(
                ec.presence_of_all_elements_located((By.CSS_SELECTOR, '.comment-item, .parent-comment'))
            )
            logger.info('[提取评论] 共找到 %s 个评论元素', len(comment_items))
        except TimeoutException:
            logger.debug('[提取评论] 评论区域未加载或不存在')
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
                        '[提取评论] 第 %s 条: %s - %s...',
                        idx + 1,
                        comment_author,
                        comment_content[:20],
                    )
            except Exception as e:
                logger.error('[提取评论] 提取第 %s 条评论时出错: %s', idx + 1, e)

        logger.info('[提取评论] 共提取 %s 条评论', len(comments))
        return comments

    def get_detail(self, url: str) -> dict | None:
        return self._scrape_note(url)
