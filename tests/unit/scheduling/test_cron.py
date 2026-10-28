"""``scheduling/cron`` — the five-field clock the scheduler reads, and no second opinion about it.

The scheduler asks an expression exactly three questions: does it mean anything, when does it fire
next, and does it ever fire again. Every one of them is time arithmetic on a cloud box nobody can
walk over to, so the edges are the point of this file: a calendar jump that must not be a
minute-by-minute walk, the POSIX OR between a restricted day-of-month and day-of-week, a rule that
never fires, and the two DST mornings — a wall clock the zone skips is skipped, and an ambiguous
one fires on its FIRST pass, once.

The zones here are IANA names, given explicitly, so nothing depends on the machine running the
suite: ``Asia/Shanghai`` (no DST), ``America/New_York`` (both edges), ``UTC``. The empty zone name
— "this machine's own clock" — is pinned to the machine's own offset instead of a fixed one.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from scheduling import cron

from i18n import t

pytestmark = pytest.mark.unit

SHANGHAI = ZoneInfo('Asia/Shanghai')
NEW_YORK = ZoneInfo('America/New_York')


class TestGrammar:
    def test_every_field_form_is_understood(self):
        assert cron.parse('0 8 * * *').hour == frozenset({8})
        assert cron.parse('0 8,20 * * *').hour == frozenset({8, 20})
        assert cron.parse('0 8-11 * * *').hour == frozenset({8, 9, 10, 11})
        assert cron.parse('*/15 * * * *').minute == frozenset({0, 15, 30, 45})
        assert cron.parse('0 */6 * * *').hour == frozenset({0, 6, 12, 18})
        assert cron.parse('0 1-5/2 * * *').hour == frozenset({1, 3, 5})
        assert cron.parse('5 4 3 2 *').day == frozenset({3})

    def test_three_letter_names_are_read_in_either_case(self):
        spec = cron.parse('0 0 * jan mon')
        assert spec.month == frozenset({1}) and spec.weekday == frozenset({1})
        assert cron.parse('0 0 * DEC FRI').month == frozenset({12})

    def test_sunday_is_both_zero_and_seven(self):
        for written in ('0 9 * * 0', '0 9 * * 7', '0 9 * * sun'):
            assert cron.parse(written).weekday == frozenset({0}), written

    def test_a_starred_field_is_recorded_as_unrestricted(self):
        spec = cron.parse('0 8 * * 1-5')
        assert spec.day_restricted is False
        assert spec.weekday_restricted is True

    def test_the_macros_a_crontab_allows_expand(self):
        assert cron.parse('@daily').raw == '0 0 * * *'
        assert cron.parse('@HOURLY').raw == '0 * * * *'
        assert cron.parse('@weekly').weekday == frozenset({0})
        assert cron.parse('@yearly').month == frozenset({1})


class TestRefusals:
    """Each refusal names the FIELD it could not read — the message is the whole report."""

    @pytest.mark.parametrize(
        ('written', 'word'),
        [
            ('99 8 * * *', 'sched.cronMinute'),
            ('0 25 * * *', 'sched.cronHour'),
            ('0 0 32 * *', 'sched.cronDay'),
            ('0 0 * 13 *', 'sched.cronMonth'),
            ('0 8 * * 8', 'sched.cronWeekday'),
            ('a b c d e', 'sched.cronMinute'),
            ('0 8 * January *', 'sched.cronMonth'),
            ('0 8 * * january', 'sched.cronWeekday'),
            ('0 18-8 * * *', 'sched.cronHour'),
            ('3/2 * * * *', 'sched.cronMinute'),
            ('*/0 * * * *', 'sched.cronMinute'),
            ('0 8 * * 1,,2', 'sched.cronWeekday'),
        ],
    )
    def test_a_field_that_cannot_be_read_is_refused_by_name(self, written, word):
        with pytest.raises(cron.CronError) as caught:
            cron.parse(written)
        assert t(word) in str(caught.value), f'{written!r} refused without naming {word}'

    def test_a_wrong_field_count_is_refused_with_the_count(self):
        """A one-field line out of a crontab is the mistake this names first."""
        for written, count in (('', 0), ('0 8 * *', 4), ('0 8 * * * *', 6)):
            with pytest.raises(cron.CronError) as caught:
                cron.parse(written)
            message = str(caught.value)
            assert str(count) in message and '5' in message, message

    def test_a_refusal_carries_the_part_it_could_not_read(self):
        with pytest.raises(cron.CronError) as caught:
            cron.parse('0 25 * * *')
        assert '25' in str(caught.value), 'the value itself is missing from the refusal'


class TestWhenItFiresNext:
    def test_a_moment_equal_to_the_rule_is_not_next(self):
        """Strictly after: a fire at 08:00 sharp must not answer 08:00 again."""
        after = datetime(2026, 10, 15, 0, 0, tzinfo=UTC)  # 08:00 in Shanghai
        assert cron.next_after(cron.parse('0 8 * * *'), after, SHANGHAI) == datetime(
            2026, 10, 16, 8, 0, tzinfo=SHANGHAI
        )

    def test_the_search_jumps_the_calendar_instead_of_the_clock(self):
        """A daily rule is a handful of steps; a minute-by-minute walk would be 1440 a day."""
        after = datetime(2026, 10, 15, 8, 30, tzinfo=UTC)  # 16:30 Shanghai
        assert cron.next_after(cron.parse('0 8 * * *'), after, SHANGHAI) == datetime(
            2026, 10, 16, 8, 0, tzinfo=SHANGHAI
        )
        assert cron.next_after(cron.parse('0 */6 * * *'), datetime(2026, 10, 15, 7, 30, tzinfo=UTC), UTC) == datetime(
            2026, 10, 15, 12, 0, tzinfo=UTC
        )
        assert cron.next_after(cron.parse('0 0 1 1 *'), datetime(2026, 10, 15, tzinfo=UTC), UTC) == datetime(
            2027, 1, 1, tzinfo=UTC
        )

    def test_an_hour_field_steps_to_the_next_permitted_minute(self):
        assert cron.next_after(cron.parse('*/15 8 * * *'), datetime(2026, 10, 15, 8, 7, tzinfo=UTC), UTC) == datetime(
            2026, 10, 15, 8, 15, tzinfo=UTC
        )

    def test_a_restricted_day_and_weekday_are_oned_not_anded(self):
        """POSIX: ``0 0 13 * 5`` fires on the 13th OR on a Friday, whichever comes first."""
        spec = cron.parse('0 0 13 * 5')
        # 2026-10-02 is a Friday, the 13th is the following Tuesday.
        assert cron.next_after(spec, datetime(2026, 10, 1, 12, tzinfo=UTC), UTC) == datetime(2026, 10, 2, tzinfo=UTC)
        assert cron.next_after(spec, datetime(2026, 10, 3, tzinfo=UTC), UTC) == datetime(2026, 10, 9, tzinfo=UTC)
        assert cron.next_after(spec, datetime(2026, 10, 10, tzinfo=UTC), UTC) == datetime(2026, 10, 13, tzinfo=UTC)

    def test_a_rule_that_can_never_match_answers_none(self):
        assert cron.next_after(cron.parse('0 0 30 2 *'), datetime(2026, 10, 15, tzinfo=UTC), UTC) is None

    def test_a_naive_moment_is_read_as_utc(self):
        """The only assumption that never guesses at a zone — pinned rather than assumed."""
        naive = cron.next_after(cron.parse('0 8 * * *'), datetime(2026, 10, 15, 23, 0), SHANGHAI)
        assert naive == datetime(2026, 10, 16, 8, 0, tzinfo=SHANGHAI)

    def test_an_empty_zone_name_means_this_machine_own_clock(self):
        answer = cron.next_after(cron.parse('0 8 * * *'), datetime(2026, 10, 15, 0, 0, tzinfo=UTC))
        assert (answer.hour, answer.minute) == (8, 0)
        assert answer.utcoffset() == datetime(2026, 10, 16, 8, 0).astimezone().utcoffset()

    def test_the_zone_a_rule_names_is_the_zone_it_fires_in(self):
        """The same expression in two zones is two different instants — the reason a task owns one."""
        after = datetime(2026, 10, 15, 0, 0, tzinfo=UTC)
        in_shanghai = cron.next_after(cron.parse('0 8 * * *'), after, SHANGHAI)
        in_utc = cron.next_after(cron.parse('0 8 * * *'), after, UTC)
        assert in_shanghai.astimezone(UTC) == datetime(2026, 10, 16, 0, 0, tzinfo=UTC)
        assert in_utc == datetime(2026, 10, 15, 8, 0, tzinfo=UTC)


class TestDaylightSaving:
    """A wall clock the zone skips does not exist; an ambiguous one exists twice and fires once."""

    def test_a_spring_forward_wall_clock_is_skipped(self):
        # 2026-03-08: New York goes 02:00 EST → 03:00 EDT, so 02:30 does not happen that day.
        after = datetime(2026, 3, 8, 5, 0, tzinfo=UTC)  # 00:00 EST
        answer = cron.next_after(cron.parse('30 2 * * *'), after, NEW_YORK)
        assert answer == datetime(2026, 3, 9, 2, 30, tzinfo=NEW_YORK), 'a nonexistent 02:30 was answered as real'

    def test_a_fall_back_wall_clock_fires_on_its_first_pass_only(self):
        # 2026-11-01: New York repeats 01:00-02:00 (01:30 EDT at 05:30Z, then 01:30 EST at 06:30Z).
        spec = cron.parse('30 1 * * *')
        first = cron.next_after(spec, datetime(2026, 11, 1, 4, 0, tzinfo=UTC), NEW_YORK)
        assert first == datetime(2026, 11, 1, 1, 30, tzinfo=NEW_YORK), 'the ambiguous hour did not fire at all'
        second = cron.next_after(spec, first, NEW_YORK)
        assert second == datetime(2026, 11, 2, 1, 30, tzinfo=NEW_YORK), 'the repeated hour fired twice in a day'
        # The two are 25 hours apart on the UTC clock — the fall-back hour was skipped, not repeated.
        assert second.astimezone(UTC) - first.astimezone(UTC) == timedelta(hours=25)

    def test_a_daily_rule_keeps_its_wall_clock_across_the_change(self):
        """08:00 stays 08:00 — which is 25 hours after the previous one, not 24."""
        before = cron.next_after(cron.parse('0 8 * * *'), datetime(2026, 10, 31, 0, 0, tzinfo=UTC), NEW_YORK)
        after = cron.next_after(cron.parse('0 8 * * *'), before, NEW_YORK)
        assert (before.hour, after.hour) == (8, 8)
        # Through UTC: subtracting two aware datetimes that share one tzinfo object compares the
        # wall clocks and ignores the offset, so the 25th hour would vanish from the difference.
        assert (after.astimezone(UTC) - before.astimezone(UTC)) == timedelta(hours=25), 'the DST change was not crossed'


class TestZoneFor:
    def test_a_blank_name_is_the_machine_own_zone_not_an_error(self):
        assert cron.zone_for('') == (None, '')
        assert cron.zone_for(None) == (None, '')
        assert cron.zone_for('   ') == (None, '')

    def test_a_known_iana_name_gives_a_zone(self):
        zone, error = cron.zone_for('Asia/Shanghai')
        assert error == '' and zone is not None

    def test_an_unknown_name_is_refused_by_name(self):
        zone, error = cron.zone_for('Mars/Olympus')
        assert zone is None
        assert 'Mars/Olympus' in error and error == t('sched.badTimezone', name='Mars/Olympus')


def test_the_clock_is_aware_and_in_utc():
    moment = cron.now()
    assert moment.tzinfo is not None
    assert moment.utcoffset().total_seconds() == 0
    assert abs((datetime.now(UTC) - moment).total_seconds()) < 5
