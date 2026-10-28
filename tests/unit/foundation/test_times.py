"""``crawlers/engine/times.py`` — the one place that knows what a timestamp looks like.

Three families arrive from the sites: the RFC-822-ish stamp an API hands back, the site's own
absolute display form, and its own RELATIVE wording. The first two were always converted. The
third was kept as the site wrote it, which is honest and useless: a time series built on it
loses every recent row, and 发布时间 is empty for exactly the posts a fresh event is about.

What is pinned here is the shape of the compromise, because two things can go wrong in
opposite directions:

* a PERMISSIVE parser writes a fabricated time into 发布时间 — the coarsest date cells
  sometimes hold a topic tag (``#2025年高考``), which is why bilibili's author mode leaves
  unrecognised cells empty. So the recognised set is closed, and everything else comes back
  unchanged.
* a parser that claims more precision than it has turns ``昨天`` into a clock reading nobody
  measured. So a named day with no time answers that day's ``00:00`` and an offset answers
  ``now − N``, and the two are documented as different claims.
"""

from datetime import datetime

import pytest

from crawlers.engine import times

pytestmark = pytest.mark.unit

#: A fixed "now" so every expectation below is arithmetic rather than a race with the clock.
NOW = datetime(2026, 10, 2, 14, 30)


class TestRelativeChinese:
    @pytest.mark.parametrize(
        'label, expected',
        [
            ('刚刚', '2026-10-02 14:30'),
            ('刚才', '2026-10-02 14:30'),
            ('3秒前', '2026-10-02 14:29'),
            ('5分钟前', '2026-10-02 14:25'),
            ('2小时前', '2026-10-02 12:30'),
            ('3天前', '2026-09-29 14:30'),
            ('2周前', '2026-09-18 14:30'),
        ],
    )
    def test_an_offset_keeps_the_clock_because_it_names_an_instant(self, label, expected):
        assert times.relative_to_absolute(label, now=NOW) == expected

    @pytest.mark.parametrize(
        'label, expected',
        [
            ('今天 09:05', '2026-10-02 09:05'),
            ('昨天 21:30', '2026-10-01 21:30'),
            ('前天21:30', '2026-09-30 21:30'),
            # A named day with no clock: the DATE is exact, the time of day is not, so the
            # answer sits at 00:00 rather than pretending to a reading nobody took.
            ('昨天', '2026-10-01 00:00'),
            ('前天', '2026-09-30 00:00'),
            ('今天', '2026-10-02 00:00'),
        ],
    )
    def test_a_named_day_uses_its_own_clock_or_none(self, label, expected):
        assert times.relative_to_absolute(label, now=NOW) == expected


class TestRelativeEnglish:
    @pytest.mark.parametrize(
        'label, expected',
        [
            ('5 minutes ago', '2026-10-02 14:25'),
            ('2 hours ago', '2026-10-02 12:30'),
            ('3 days ago', '2026-09-29 14:30'),
            ('a week ago', '2026-09-25 14:30'),
            ('an hour ago', '2026-10-02 13:30'),
            ('one day ago', '2026-10-01 14:30'),
            ('yesterday', '2026-10-01 00:00'),
            ('today', '2026-10-02 00:00'),
        ],
    )
    def test_the_overseas_shapes_are_read_too(self, label, expected):
        assert times.relative_to_absolute(label, now=NOW) == expected

    def test_the_english_match_is_case_insensitive(self):
        assert times.relative_to_absolute('2 Days Ago', now=NOW) == '2026-09-30 14:30'


class TestTheClosedSet:
    """What must NOT be converted is the half that protects the column."""

    @pytest.mark.parametrize(
        'value',
        [
            '#2025年高考',  # a topic tag that landed in the date cell — the bilibili B1 case
            '发布了视频',
            '2天',  # an interval without the 前 is not a time
            'ago',
            '前天昨天',
            '2025年11月12日',  # an absolute date without a clock: handled by `absolute`, not here
            '',
            None,
        ],
    )
    def test_anything_outside_the_set_answers_empty(self, value):
        assert times.relative_to_absolute(value, now=NOW) == '', (
            'a parser that guesses here writes a fabricated time into a real column'
        )

    def test_a_year_less_date_is_deliberately_not_invented(self):
        """``09月26日 21:00`` names no year. The site only omits one when the post is from the
        current year, so it COULD be inferred — and inferring it is the decision that was
        already taken the other way for bilibili's author mode, because getting it wrong
        moves a row into another year. Left as the site wrote it."""
        assert times.relative_to_absolute('09月26日 21:00', now=NOW) == ''
        assert times.absolute('09月26日 21:00', now=NOW) == '09月26日 21:00'


class TestAbsolute:
    def test_the_rfc822_stamp_still_parses(self):
        assert times.absolute('Wed Sep 24 15:42:51 +0800 2026') == '2026-09-24 15:42'

    def test_the_cjk_display_form_parses_with_and_without_a_clock(self):
        assert times.absolute('2022年01月27日 00:59') == '2022-01-27 00:59'
        assert times.absolute('2022年1月27日') == '2022-01-27 00:00'

    def test_an_iso_string_is_already_what_we_want(self):
        # Not in the recognised list on purpose — it needs no conversion, and rewriting it
        # through a second format string is how two spellings of one instant appear.
        assert times.absolute('2022-01-27 00:59') == '2022-01-27 00:59'

    def test_the_relative_shapes_now_go_through_the_same_door(self):
        assert times.absolute('3小时前', now=NOW) == '2026-10-02 11:30'
        assert times.absolute('2 days ago', now=NOW) == '2026-09-30 14:30'

    def test_an_unrecognised_value_is_returned_unchanged(self):
        """The site's own words are still better than a fabricated time — and a caller can
        tell the two apart by asking ``relative_to_absolute`` for its empty answer."""
        assert times.absolute('发布于 昨天下午', now=NOW) == '发布于 昨天下午'
        assert times.absolute('#2025年高考', now=NOW) == '#2025年高考'

    def test_empty_stays_empty(self):
        assert times.absolute('') == '' and times.absolute(None) == ''

    def test_normalise_rfc822_keeps_its_own_narrow_contract(self):
        # The name is load-bearing for two call sites that read the same JSON stamp; it must
        # not start answering relative labels behind their backs.
        assert times.normalise_rfc822('Wed Sep 24 15:42:51 +0800 2026') == '2026-09-24 15:42'
        assert times.normalise_rfc822('3小时前') == '3小时前'
