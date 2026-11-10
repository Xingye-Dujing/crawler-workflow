"""wechat ``search`` cursor: a failed article must NOT be filed as proven (M1).

wechat's own comment says a link that failed once must not be silently skipped on every
resume — yet the loop advanced ``url_index`` even over a link whose ``get_detail`` returned
nothing, so 继续 re-fetched *nothing* for that hole (it started after it). The cursor now
pins at the first failed link: later links are still collected this pass, and the ledger
de-dupes a re-walk, so the resume costs requests, never duplicate rows.
"""

from crawlers.platforms.wechat.crawler import WechatCrawler

AAA = 'https://mp.weixin.qq.com/s/AAA'
BAD = 'https://mp.weixin.qq.com/s/BBB'
CCC = 'https://mp.weixin.qq.com/s/CCC'


def _bare(monkeypatch):
    crawler = WechatCrawler.__new__(WechatCrawler)
    crawler.driver = None
    crawler.headless = True
    crawler.login_wall = False
    crawler.risk_blocked = False
    crawler.unreachable = False
    crawler._collected = []
    crawler._cursor = {}
    crawler._sink = None
    crawler._cursor_sink = None
    monkeypatch.setattr(crawler, '_polite_pause', lambda *a, **k: None)
    # emit only needs to record the row and answer "new" — the ledger seam is not under test.
    monkeypatch.setattr(crawler, 'emit', lambda item: (crawler._collected.append(item), True)[1])
    return crawler


def test_the_cursor_pins_at_the_first_failed_article(monkeypatch):
    crawler = _bare(monkeypatch)
    answers = {AAA: {'标题': 'a', '公众号': 'x'}, BAD: None, CCC: {'标题': 'c', '公众号': 'x'}}
    monkeypatch.setattr(crawler, 'get_detail', answers.get)

    crawler.search(urls=[AAA, BAD, CCC])

    position = crawler.position
    assert position.get('url_index') == 1, f'the failed link BBB was crossed → 继续 skips it: {position}'
    assert crawler.collected() == 2, 'CCC after the hole is still collected this pass'
    assert position.get('url_total') == 3, 'the walk still records how many links there were'


def test_a_clean_walk_advances_the_cursor_to_the_end(monkeypatch):
    # Positive control: with no hole, every link proves and the cursor reaches the total.
    crawler = _bare(monkeypatch)
    answers = {AAA: {'标题': 'a', '公众号': 'x'}, BAD: {'标题': 'b', '公众号': 'x'}, CCC: {'标题': 'c', '公众号': 'x'}}
    monkeypatch.setattr(crawler, 'get_detail', answers.get)

    crawler.search(urls=[AAA, BAD, CCC])

    assert crawler.position.get('url_index') == 3, crawler.position


class TestThePublishTimeLineIsRecognised:
    """The meta line's stamp has to MATCH before ``times.absolute`` can resolve it.

    ``_DATE_RE`` admitted 小时/分钟 only, so an article published ``昨天`` — the most common
    "recent" wording on 公众号, and exactly the row a live event's time series needs — was skipped
    by the guard and came back as an empty 发布时间, even though the resolver handles it.
    """

    @staticmethod
    def _matches(text: str) -> bool:
        return bool(WechatCrawler._DATE_RE.search(text))

    def test_absolute_forms_still_match(self):
        assert self._matches('2026-08-04')
        assert self._matches('2026年8月4日')

    def test_the_relative_wordings_the_page_uses_also_match(self):
        for wording in ('3小时前', '20分钟前', '2天前', '1周前', '昨天', '前天 21:30', '刚刚'):
            assert self._matches(wording), wording

    def test_a_line_with_no_stamp_is_still_ignored(self):
        """The guard exists so the account name (also in that meta block) is not taken for a date."""
        assert not self._matches('旅行实验室')
        assert not self._matches('')
