"""The 内容去重 step (``ops/anti_join.py``) and its wiring through the analysis node.

The step answers: "which rows of THIS table are not already in THAT table's column?". Its
output is the left table's own columns — no right column is merged in — because a downstream
node keeps reading the names it always read. Every refusal names what is missing: a second
table, a column, or a mode.
"""

import pandas as pd
import pytest

from services.analysis.kernels import UnknownOperationError
from services.analysis.ops.anti_join import anti_join

pytestmark = pytest.mark.unit


def _left() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {'标题': '甲', '链接': 'https://ex.com/p/1'},
            {'标题': '乙', '链接': 'https://ex.com/p/2/'},
            {'标题': '丙', '链接': 'https://ex.com/p/3?utm_source=share'},
            {'标题': '丁', '链接': ''},
        ]
    )


def _right() -> pd.DataFrame:
    # /p/9 is collected but was never promised by the list: the swap case below keeps it.
    return pd.DataFrame(
        [
            {'文章URL': 'https://ex.com/p/1'},
            {'文章URL': 'https://ex.com/p/2'},
            {'文章URL': 'https://ex.com/p/9'},
        ]
    )


class TestTheSetDifference:
    def test_rows_already_present_are_dropped_and_the_rest_kept_in_order(self):
        out = anti_join(_left(), _right(), left_on='链接', right_on='文章URL', mode='url')
        assert list(out['标题']) == ['丙', '丁']
        assert list(out.columns) == ['标题', '链接'], 'the right table never contributes a column'

    def test_the_tracking_parameter_and_trailing_slash_are_the_same_page(self):
        out = anti_join(_left(), _right(), left_on='链接', right_on='文章URL', mode='url')
        assert '丙' in list(out['标题']), 'a share link to an already-collected page is still that page'

    def test_keep_is_the_mirror_question(self):
        out = anti_join(_left(), _right(), left_on='链接', right_on='文章URL', mode='url', keep='keep')
        assert list(out['标题']) == ['甲', '乙']

    def test_an_empty_right_table_keeps_every_row(self):
        """Nothing to exclude is not an error: the caller gets the left table back unchanged."""
        out = anti_join(_left(), pd.DataFrame(columns=['文章URL']), left_on='链接', right_on='文章URL')
        assert len(out) == len(_left())

    def test_a_blank_key_never_matches_anything(self):
        right = pd.DataFrame([{'文章URL': ''}])
        out = anti_join(_left(), right, left_on='链接', right_on='文章URL')
        assert len(out) == len(_left()), 'two absences are not "the same content"'

    def test_two_columns_are_one_composite_key(self):
        left = pd.DataFrame(
            [
                {'平台': 'weibo', '链接': 'https://a/1'},
                {'平台': 'zhihu', '链接': 'https://a/1'},
            ]
        )
        right = pd.DataFrame([{'平台': 'weibo', '链接': 'https://a/1'}])
        out = anti_join(left, right, left_on='平台,链接', right_on='平台,链接')
        assert out['平台'].tolist() == ['zhihu']

    def test_swapping_reads_the_other_side_as_the_table_to_keep(self):
        swapped = anti_join(
            _left(),
            _right(),
            left_on='链接',
            right_on='文章URL',
            mode='url',
            swap_tables=True,
        )
        assert list(swapped.columns) == ['文章URL']
        # The comment table is filtered against the post table: everything already promised is
        # dropped, and only the collected page the list never mentioned survives.
        assert list(swapped['文章URL']) == ['https://ex.com/p/9']

    def test_near_identical_text_can_be_excluded(self):
        left = pd.DataFrame([{'评论': '今天的三亚湾日落真的很美'}, {'评论': '完全无关的另一句话'}])
        right = pd.DataFrame([{'旧评论': '今天的三亚湾日落真的很美啊'}])
        out = anti_join(left, right, left_on='评论', right_on='旧评论', mode='similar', max_distance=15)
        assert out['评论'].tolist() == ['完全无关的另一句话']

    def test_a_blank_key_is_not_a_fingerprint_in_similar_mode(self):
        """``str(nan)`` is the token 'nan': every empty cell would share one fingerprint.

        The mode-agnostic rule is the same one ``trim``/``url`` already follow: two absences are
        not the same content, so a row with an empty key is never dropped as "already present".
        """
        left = pd.DataFrame({'键': [None, None, 'aaaaaaaa']})
        right = pd.DataFrame({'键': [None]})
        out = anti_join(left, right, left_on='键', right_on='键', mode='similar')
        assert len(out) == 3, out['键'].tolist()

    def test_a_partially_blank_composite_key_never_matches(self):
        left = pd.DataFrame({'平台': ['weibo', 'weibo'], '链接': ['u1', None]})
        right = pd.DataFrame({'平台': ['weibo'], '链接': [None]})
        out = anti_join(left, right, left_on='平台,链接', right_on='平台,链接', mode='similar')
        assert len(out) == 2


class TestTheRefusals:
    def test_no_second_table_is_named(self):
        with pytest.raises(UnknownOperationError) as excinfo:
            anti_join(_left(), None, left_on='链接', right_on='文章URL')
        assert 'anti_join' in str(excinfo.value)

    def test_an_unknown_mode_or_keep_name_is_refused_with_the_list_it_accepts(self):
        with pytest.raises(UnknownOperationError) as mode:
            anti_join(_left(), _right(), left_on='链接', right_on='文章URL', mode='moon')
        assert 'moon' in str(mode.value) and 'trim' in str(mode.value)
        with pytest.raises(UnknownOperationError) as keep:
            anti_join(_left(), _right(), left_on='链接', right_on='文章URL', keep='moon')
        assert 'moon' in str(keep.value) and 'exclude' in str(keep.value)

    def test_an_empty_column_box_is_refused(self):
        with pytest.raises(UnknownOperationError) as excinfo:
            anti_join(_left(), _right(), left_on='', right_on='文章URL')
        assert 'anti_join' in str(excinfo.value)

    def test_unequal_column_lists_are_refused(self):
        with pytest.raises(UnknownOperationError) as excinfo:
            anti_join(_left(), _right(), left_on='标题,链接', right_on='文章URL')
        assert '标题' in str(excinfo.value) and '文章URL' in str(excinfo.value)

    def test_a_column_missing_from_either_side_is_named(self):
        with pytest.raises(UnknownOperationError) as left_missing:
            anti_join(_left(), _right(), left_on='网址', right_on='文章URL')
        assert '网址' in str(left_missing.value)
        with pytest.raises(UnknownOperationError) as right_missing:
            anti_join(_left(), _right(), left_on='链接', right_on='网址')
        assert '网址' in str(right_missing.value)


class TestTheNodeWiring:
    """The analysis node hands the step its SECOND incoming table, and says which role each
    parent fills. The roles are decided by connection order, so the console line is the only
    place a user can check it without opening the JSON."""

    @staticmethod
    def _node(**params):
        return {
            'id': 'a1',
            'type': 'analysis',
            'title': '去重',
            'params': {
                'operation': 'anti_join',
                'left_on': '链接',
                'right_on': '文章URL',
                'match_mode': 'url',
                **params,
            },
        }

    def test_the_second_connection_becomes_the_other_table(self, monkeypatch):
        from nodes.executors import analysis

        lines = []
        monkeypatch.setattr(analysis, 'add_log', lambda msg, **kw: lines.append(msg))
        rows = analysis.execute_analysis_node(
            self._node(),
            current_input=_left().to_dict('records'),
            upstream=[
                ('p1', _left().to_dict('records')),
                ('p2', _right().to_dict('records')),
            ],
            label_of={'p1': '帖子表 #p1', 'p2': '评论表 #p2'},
        )
        assert [row['标题'] for row in rows] == ['丙', '丁']
        assert any('帖子表 #p1' in line and '评论表 #p2' in line for line in lines), lines

    def test_swapping_is_announced_with_the_roles_it_will_use(self, monkeypatch):
        from nodes.executors import analysis

        lines = []
        monkeypatch.setattr(analysis, 'add_log', lambda msg, **kw: lines.append(msg))
        rows = analysis.execute_analysis_node(
            self._node(swap_tables=True),
            current_input=_left().to_dict('records'),
            upstream=[
                ('p1', _left().to_dict('records')),
                ('p2', _right().to_dict('records')),
            ],
            label_of={'p1': '帖子表 #p1', 'p2': '评论表 #p2'},
        )
        # Swapped: the comment table is now the table being filtered, and only the page the
        # post list never promised survives.
        assert [row['文章URL'] for row in rows] == ['https://ex.com/p/9']
        assert any('评论表 #p2' in line for line in lines), lines

    def test_one_wire_is_refused_by_name(self):
        from nodes.executors import analysis

        with pytest.raises(UnknownOperationError) as excinfo:
            analysis.execute_analysis_node(
                self._node(),
                current_input=_left().to_dict('records'),
                upstream=[('p1', _left().to_dict('records'))],
            )
        assert '第二条' in str(excinfo.value) or 'second' in str(excinfo.value).lower()

    def test_a_non_table_second_wire_is_refused_by_the_parent_name(self):
        from nodes.executors import analysis

        with pytest.raises(UnknownOperationError) as excinfo:
            analysis.execute_analysis_node(
                self._node(),
                current_input=_left().to_dict('records'),
                upstream=[('p1', _left().to_dict('records')), ('p2', {'chart': 'spec'})],
                label_of={'p2': '图表 #p2'},
            )
        assert '图表 #p2' in str(excinfo.value)
