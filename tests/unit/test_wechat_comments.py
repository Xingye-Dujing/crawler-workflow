"""WeChat comment adapter: the parsers, the request, and the three outcomes.

The live question — will the site answer a browser at all — is measured and
documented in ``crawl_wechat`` (answer: no, it replies with its 验证 page), so
what matters here is that each shape is classified distinctly: a refused session
must never look like an article without comments, and a JSON answer must flatten
into the same columns the other three platforms emit.
"""

import json
import time

import pytest

from crawlers.comments import BLOCKED, DEAD, OK, CommentSession, parse_wechat_comments, wechat_comment_js
from utils.helpers import platform_for

pytestmark = pytest.mark.unit


class FakeDriver:
    """Answers the credential script, the entry-count script, the DOM query and
    the in-page fetch, each by which script was asked for."""

    def __init__(self, creds=None, answers=None, body='', counts=None, rendered=()):
        self.creds = creds or {}
        self.answers = list(answers or [])
        self.body = body
        self.counts = counts or {}
        self.rendered = list(rendered)
        self.visited = []
        self.fetched = []
        self._current = 'https://mp.weixin.qq.com/s/abc'

    def get(self, url):
        self.visited.append(url)

    @property
    def current_url(self):
        return self._current

    def set_script_timeout(self, _seconds):
        pass

    def execute_script(self, script, *_args):
        if 'labels' in script:  # the 阅读/赞/在看 probe
            return dict(self.counts)
        return dict(self.creds)

    def find_elements(self, by, selector):
        if selector == '.discuss_list .item':
            return [type('E', (), {'text': text})() for text in self.rendered]
        return []

    def find_element(self, by, selector):
        if selector == 'body':
            return type('E', (), {'text': self.body})()
        raise KeyError(selector)

    def execute_async_script(self, _script):
        self.fetched.append(_script)
        if not self.answers:
            raise AssertionError('the adapter asked the endpoint more times than scripted')
        return self.answers.pop(0)


CREDS = {
    'biz': 'MzI2NTYwNTMwMg==',
    'comment_id': '4700855047839252482',
    'mid': '2247492426',
    'idx': '1',
    'sn': '48ubXezOGo5GLqzwNk8AjQ',
    'key': 'K-abc',
    'pass_ticket': 'abc/def+ghi=',
    'appmsg_token': '',
    'uin': '',
}

REFUSAL = '<!DOCTYPE HTML><html><head><title>验证</title></head><body><p>请在微信客户端打开链接。</p></body></html>'

PAYLOAD = {
    'base_resp': {'ret': 0},
    'comment_count': 2,
    'elected_comment': [
        {
            'comment_id': '1',
            'author': '读者甲',
            'content': '写得很清楚<br/>收藏了',
            'create_time': 1758009600,
            'like_num': 12,
            'location': 'IP: 浙江',
            'reply': {
                'reply': [
                    {'author': '公众号名称', 'content': '谢谢支持', 'create_time': 1758013200, 'is_star': 1},
                    {'author': '读者乙', 'content': '同问', 'create_time': 1758013800},
                ]
            },
        },
        {'comment_id': '2', 'author': '读者丙', 'content': '第二条评论', 'publish_time': 1758020000},
    ],
}


def _session(**kwargs):
    logs = []
    driver = FakeDriver(**kwargs)
    return CommentSession(driver, log=logs.append, nap=lambda _s: None), logs


class TestRouting:
    def test_an_article_link_now_routes_to_the_wechat_adapter(self):
        assert platform_for('https://mp.weixin.qq.com/s/48ubXezOGo5GLqzwNk8AjQ') == 'wechat'

    def test_a_non_article_wechat_host_is_not_claimed(self):
        assert platform_for('https://weixin.qq.com/download') == ''


class TestRequest:
    def test_the_request_carries_the_pages_own_tokens(self):
        url = wechat_comment_js(CREDS, offset=20)
        assert url.startswith('https://mp.weixin.qq.com/mp/appmsg_comment?action=getcomment')
        assert 'comment_id=4700855047839252482' in url
        assert 'offset=20' in url
        assert '__biz=MzI2NTYwNTMwMg%3D%3D' in url

    def test_tokens_that_contain_url_delimiters_are_escaped(self):
        """pass_ticket is base64-ish: an unescaped '/' or '=' would corrupt every
        parameter after it."""
        url = wechat_comment_js(CREDS)
        assert 'pass_ticket=abc%2Fdef%2Bghi%3D' in url

    def test_a_missing_token_yields_an_empty_parameter_not_the_word_none(self):
        url = wechat_comment_js({'biz': 'B'})
        assert 'comment_id=&' in url and 'None' not in url


class TestParser:
    def test_comments_and_their_replies_become_one_flat_table(self):
        rows = parse_wechat_comments(PAYLOAD, 'https://mp.weixin.qq.com/s/x')
        assert [row['评论内容'] for row in rows] == ['写得很清楚收藏了', '谢谢支持', '同问', '第二条评论']

    def test_column_names_match_the_other_platforms(self):
        rows = parse_wechat_comments(PAYLOAD, 'https://mp.weixin.qq.com/s/x')
        assert set(rows[0]) == {
            '平台',
            '文章URL',
            '评论者',
            '评论者主页',
            '评论内容',
            '评论时间',
            '点赞数',
            'IP归属地',
            '回复对象',
            '楼层',
        }
        assert {row['平台'] for row in rows} == {'wechat'}
        assert {row['文章URL'] for row in rows} == {'https://mp.weixin.qq.com/s/x'}

    def test_the_authors_own_answer_is_labelled(self):
        rows = parse_wechat_comments(PAYLOAD, 'u')
        assert rows[1]['回复对象'] == '作者回复'
        assert rows[2]['回复对象'] == '读者甲'

    def test_floor_numbers_increase_down_the_whole_table(self):
        rows = parse_wechat_comments(PAYLOAD, 'u')
        assert [row['楼层'] for row in rows] == [1, 2, 3, 4]

    def test_timestamps_become_readable_local_times(self):
        rows = parse_wechat_comments(PAYLOAD, 'u')
        expected = time.strftime('%Y-%m-%d %H:%M', time.localtime(1758009600))
        assert rows[0]['评论时间'] == expected

    def test_the_ip_region_prefix_is_dropped(self):
        assert parse_wechat_comments(PAYLOAD, 'u')[0]['IP归属地'] == '浙江'

    def test_an_empty_or_missing_list_is_no_rows(self):
        assert parse_wechat_comments({}, 'u') == []
        assert parse_wechat_comments({'elected_comment': []}, 'u') == []

    def test_a_malformed_entry_is_skipped_rather_than_raising(self):
        payload = {'elected_comment': ['not-a-dict', {'author': 'ok', 'content': 'row'}]}
        rows = parse_wechat_comments(payload, 'u')
        assert [row['评论者'] for row in rows] == ['ok']


class TestCrawl:
    """The classification the site owner's rule demands.

    An article that has no comments and a visit that never got in look identical
    (empty area, no counts) except when counts prove the visit worked. Reporting
    the ambiguous case as "0 comments" would quietly turn a failed crawl into
    usable-looking data, so it is reported as not-entered.
    """

    def test_elected_comments_from_the_endpoint_are_returned(self):
        session, _logs = _session(creds=CREDS, answers=[json.dumps(PAYLOAD)])
        rows, status = session.crawl_wechat('https://mp.weixin.qq.com/s/x', 0)
        assert status == OK
        assert [row['评论内容'] for row in rows] == ['写得很清楚收藏了', '谢谢支持', '同问', '第二条评论']

    def test_the_row_limit_is_respected_on_the_api_path(self):
        session, _logs = _session(creds=CREDS, answers=[json.dumps(PAYLOAD)])
        rows, status = session.crawl_wechat('https://mp.weixin.qq.com/s/x', 2)
        assert status == OK and len(rows) == 2

    def test_comments_rendered_in_the_dom_are_read_without_the_endpoint(self):
        session, _logs = _session(creds=CREDS, answers=[], rendered=['读者丁: 第四条'])
        rows, status = session.crawl_wechat('https://mp.weixin.qq.com/s/x', 5)
        assert status == OK
        assert rows[0]['评论内容'] == '读者丁: 第四条'
        assert session.driver.fetched == []

    def test_empty_area_and_visible_counts_means_the_article_has_no_comments(self):
        session, logs = _session(creds=CREDS, answers=[REFUSAL], counts={'阅读': '1.2万', '赞': '88'})
        rows, status = session.crawl_wechat('https://mp.weixin.qq.com/s/x', 5)
        assert (rows, status) == ([], OK)
        assert any('无留言' in line for line in logs)

    def test_empty_area_and_no_counts_is_not_entered_rather_than_empty(self):
        """The trap this guards: a refused visit also yields "no comments", and
        writing that into a dataset would look like a real, clean result."""
        session, logs = _session(creds=CREDS, answers=[REFUSAL], counts={})
        rows, status = session.crawl_wechat('https://mp.weixin.qq.com/s/x', 5)
        assert (rows, status) == ([], BLOCKED)
        assert any('没有正确进入' in line for line in logs)

    def test_a_deleted_or_revoked_article_is_dead(self):
        session, _logs = _session(creds=CREDS, body='该内容已被发布者删除', counts={'阅读': '5'})
        rows, status = session.crawl_wechat('https://mp.weixin.qq.com/s/x', 5)
        assert (rows, status) == ([], DEAD)

    def test_a_risk_control_page_is_blocked_before_any_request(self):
        session, _logs = _session(creds=CREDS, body='当前请求存在异常，暂时限制访问')
        rows, status = session.crawl_wechat('https://mp.weixin.qq.com/s/x', 5)
        assert (rows, status) == ([], BLOCKED)
        assert session.driver.fetched == []

    def test_no_comment_id_skips_the_endpoint_but_still_judges_entry(self):
        """Without an id there is nothing to ask for, yet the visit still has to
        be classified: counts visible → genuinely no comments; none → not entered."""
        bare = {'biz': 'B', 'comment_id': '', 'key': '', 'show_comment': '0'}
        with_counts, _logs = _session(creds=bare, counts={'在看': '3'})
        assert with_counts.crawl_wechat('https://mp.weixin.qq.com/s/x', 5)[1] == OK
        assert with_counts.driver.fetched == []
        blind, _logs2 = _session(creds=bare, counts={})
        assert blind.crawl_wechat('https://mp.weixin.qq.com/s/x', 5)[1] == BLOCKED
