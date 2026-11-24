"""``Cursor``/``LedgerKey``: the two durable values whose rules used to live in comments.

A cursor records the position a crawl PROVED (never the content it saw, never a prefix beyond the
batch it walked), and a ledger key is a crawled row's site identity (never its content). Both were
violated once, in ways 继续 could not see, so each case here states the rule as an assertion over
the type rather than over a caller's memory.
"""

import pytest

from crawlers.core.crawler import Crawler
from services.runs.store import LedgerKey, RunStore, item_key
from services.runs.store.values import PROVEN_INDEX, PROVEN_TOTAL, Cursor

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path):
    s = RunStore(str(tmp_path / 'runs.db'))
    yield s
    s.close()


class TestCursor:
    def test_a_cursor_reads_like_the_mapping_it_replaced(self):
        """Every resume path reads ``.get``/``in``/``dict()``; the type may not change that."""
        cursor = Cursor.at(keyword='三亚', page=2, done=40)

        assert cursor['page'] == 2
        assert cursor.get('keyword') == '三亚'
        assert cursor.get('missing', 'fallback') == 'fallback'
        assert 'done' in cursor and len(cursor) == 3
        assert dict(cursor) == {'keyword': '三亚', 'page': 2, 'done': 40}
        assert cursor.as_dict() == dict(cursor)
        assert cursor == {'keyword': '三亚', 'page': 2, 'done': 40}

    def test_a_cursor_cannot_be_edited_and_does_not_alias_its_source(self):
        """The sink's snapshot is the value, not a view of the crawler's working dict."""
        source = {'keyword': '三亚', 'pages': [1, 2]}
        cursor = Cursor.of(source)

        source['keyword'] = '海口'
        source['pages'].append(3)

        assert cursor['keyword'] == '三亚', 'the cursor kept a reference to the crawler dict'
        assert cursor.as_dict()['pages'] == [1, 2], 'a nested list still aliases the source'
        with pytest.raises(AttributeError):
            cursor.position = {}
        moved = cursor.merged(page=3)
        assert moved['page'] == 3 and 'page' not in cursor, 'merged replaced the value instead of deriving one'

    @pytest.mark.parametrize(('proven', 'total'), [(-1, 3), (4, 3)])
    def test_a_prefix_outside_the_batch_it_describes_is_refused(self, proven, total):
        """'Recorded what it proved' is a fact of the value; 0..total is its domain."""
        with pytest.raises(ValueError):
            Cursor.proven_prefix(proven, total)

    def test_a_prefix_with_no_batch_behind_it_is_refused(self):
        """``url_index`` without ``url_total`` is a claim nothing can check, so it cannot be one."""
        with pytest.raises(ValueError):
            Cursor({}, proven=2)

    def test_the_proven_pair_round_trips_as_the_fields_url_index_and_url_total(self):
        written = Cursor.proven_prefix(2, 10)
        read = Cursor.of({PROVEN_INDEX: 2, PROVEN_TOTAL: 10})

        assert written.as_dict() == {PROVEN_INDEX: 2, PROVEN_TOTAL: 10}
        assert read.proven == 2 and read.total == 10 and read.position == {}
        assert read == written

    def test_the_store_hands_back_a_cursor_and_writes_the_historical_json(self, store):
        """A position cursor and a proven prefix keep their stored shape; readers get the type."""
        store.start_run('r1', 'wf', 'fp', node_total=1)
        store.begin_node('r1', 'node-1', 'source', fingerprint='fp')
        store.save_cursor('r1', 'node-1', Cursor.at(keyword='三亚', page=2))

        assert store.get_cursor('r1', 'node-1') == Cursor.at(keyword='三亚', page=2)
        assert store.node_statuses('r1')['node-1']['cursor'] == {'keyword': '三亚', 'page': 2}

        store.save_cursor('r1', 'node-1', Cursor.proven_prefix(2, 10))
        assert store.node_statuses('r1')['node-1']['cursor'] == {PROVEN_INDEX: 2, PROVEN_TOTAL: 10}

    def test_nothing_written_is_absent_and_a_resumed_crawl_still_starts_at_the_top(self, store):
        store.start_run('r1', 'wf', 'fp', node_total=1)
        store.begin_node('r1', 'node-1', 'source', fingerprint='fp')

        assert store.get_cursor('r1', 'node-1') is None
        assert Crawler.resume_of({'resume': store.get_cursor('r1', 'node-1') or {}}) == {}

    def test_a_platform_walk_sees_the_cursor_the_store_handed_back(self):
        """``resume_of`` refused anything but a dict, which silently dropped every resume."""
        cursor = Cursor.at(keyword='三亚', page=3)

        assert Crawler.resume_of({'resume': cursor}) == {'keyword': '三亚', 'page': 3}


class TestLedgerKey:
    def test_a_comment_is_its_site_id_whatever_the_floor_number(self):
        first = {'平台': 'weibo', '评论ID': '4981', '评论内容': '说得好', '楼层': 1}
        later = {'平台': 'weibo', '评论ID': '4981', '评论内容': '说得好', '楼层': 7}

        assert item_key(first) == item_key(later) == LedgerKey('comment', ('weibo', '4981')).digest()

    def test_a_comment_without_an_id_keeps_the_content_identity_and_drops_the_counters(self):
        key = LedgerKey('comment-text', ('zhihu', 'https://a', '张三', '原文', '2026-01-01')).digest()
        row = {'平台': 'zhihu', '文章URL': 'https://a', '评论者': '张三', '评论内容': '原文', '评论时间': '2026-01-01'}

        assert item_key({**row, '点赞': 3, '楼层': 2}) == item_key({**row, '点赞': 99, '楼层': 8}) == key

    def test_a_signed_link_is_the_same_item_after_its_token_is_re_signed(self):
        first = {'笔记ID': 'n1', '笔记链接': 'https://xhs/n1?xsec_token=aaa', '标题': '标题'}
        later = {'笔记ID': 'n1', '笔记链接': 'https://xhs/n1?xsec_token=bbb', '标题': '标题'}

        assert item_key(first) == item_key(later) == LedgerKey('site', ('', 'n1')).digest()

    @pytest.mark.parametrize(
        ('row', 'kind', 'parts'),
        [
            ({'链接': 'https://a/post'}, 'url', ('https://a/post',)),
            ({'标题': '标题', '作者': '李四', '正文': '正文'}, 'text', ('标题', '李四', '正文')),
            ({'未知列': 'x'}, 'json', ('{"未知列": "x"}',)),
            ('裸字符串', 'raw', ('裸字符串',)),
        ],
    )
    def test_each_identity_shape_is_one_ledger_key(self, row, kind, parts):
        assert item_key(row) == LedgerKey(kind, parts).digest()

    def test_a_different_kind_never_shares_a_key(self):
        """``more`` and ``url`` read the same evidence; the kind is what keeps them apart."""
        assert LedgerKey('site', ('xhs', 'n1')).digest() != LedgerKey('url', ('n1',)).digest()

    def test_a_missing_part_reads_as_empty_never_as_the_word_none(self):
        """The join treats ``None`` as a blank, so a missing platform cannot become 'None'."""
        assert LedgerKey('url', (None,)).digest() == LedgerKey('url', ('',)).digest()
