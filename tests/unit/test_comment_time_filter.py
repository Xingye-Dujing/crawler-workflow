"""The comment node's table-side time filter (``_filter_comments_by_time``).

A range that chooses which rows survive is a data-choosing parameter, so it is read or
refused by name — never guessed — and a comment whose time cell is blank or unrecognised is
dropped and counted rather than assigned a year. This mirrors ``bin_time`` (compare by
calendar day, inclusive) and the crawl window's own need_both / bad_range / bad_date rules.

It is a pure function over already-crawled rows, so no crawler, browser or model is touched:
the rows come from the comment engine, the filter only decides which reach downstream.
"""

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def exec_():
    import app

    return app


def _row(stamp):
    return {'评论内容': 'x', '评论时间': stamp}


class TestCommentTimeFilter:
    def test_no_range_returns_every_row_untouched(self, exec_):
        rows = [_row('2024-01-01 10:00'), _row(''), _row('nonsense')]
        # neither end given → the switch is simply off; not a single row is judged.
        assert exec_._filter_comments_by_time(rows, {}, 'node-1') is rows

    def test_a_half_range_is_refused_by_name(self, exec_):
        """One end alone cannot bound a window; refusing is the same rule the crawl window
        uses — silently treating a missing end as "unbounded" would keep far more than asked."""
        for params in ({'comment_start': '2024-01-01'}, {'comment_end': '2024-03-01'}):
            with pytest.raises(ValueError, match='node-1'):
                exec_._filter_comments_by_time([_row('2024-02-01 00:00')], params, 'node-1')

    def test_an_inverted_window_is_refused(self, exec_):
        with pytest.raises(ValueError):
            exec_._filter_comments_by_time([], {'comment_start': '2024-06-01', 'comment_end': '2024-01-01'}, 'node-1')

    def test_an_unparseable_bound_is_refused_not_guessed(self, exec_):
        with pytest.raises(ValueError):
            exec_._filter_comments_by_time([], {'comment_start': 'nonsense', 'comment_end': '2024-01-31'}, 'node-1')

    def test_rows_outside_the_range_are_dropped_boundaries_are_inclusive(self, exec_):
        rows = [
            _row('2024-01-31 23:59'),  # the day BEFORE start → out
            _row('2024-02-01 00:00'),  # start day → in (inclusive)
            _row('2024-03-15 12:00'),  # middle → in
            _row('2024-03-31 23:59'),  # end day → in (inclusive)
            _row('2024-04-01 00:00'),  # the day AFTER end → out
        ]
        out = exec_._filter_comments_by_time(
            rows, {'comment_start': '2024-02-01', 'comment_end': '2024-03-31'}, 'node-1'
        )
        assert [r['评论时间'] for r in out] == ['2024-02-01 00:00', '2024-03-15 12:00', '2024-03-31 23:59']

    def test_a_blank_or_unrecognised_time_is_dropped_not_guessed(self, exec_):
        """A relative phrase the timestamp reader does not fold, and a blank cell, are not
        dates; keeping them would pretend they matched the window. They are dropped."""
        rows = [_row(''), _row('三年前'), _row('2024-02-10 09:00')]
        out = exec_._filter_comments_by_time(
            rows, {'comment_start': '2024-02-01', 'comment_end': '2024-02-28'}, 'node-1'
        )
        assert out == [_row('2024-02-10 09:00')]

    def test_a_second_within_the_same_day_still_counts(self, exec_):
        """Comparison is by calendar day, so any time on the end date is kept — a
        23:59 comment is not thrown away for being after the bare end date's midnight."""
        rows = [_row('2024-05-02 23:59')]
        out = exec_._filter_comments_by_time(
            rows, {'comment_start': '2024-05-02', 'comment_end': '2024-05-02'}, 'node-1'
        )
        assert out == rows
