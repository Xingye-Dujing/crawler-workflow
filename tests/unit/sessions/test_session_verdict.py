"""What a session verdict means, and the slot it is filed in — without a browser or a clock.

``sessions.preflight`` pays for the probe and bounds it; these are the decisions it carries:
which word a page's facts become, which words block a run, and which (scope, platform, account,
profile-mode) cache slot the answer belongs to.
"""

import pytest
from sessions import verdict

pytestmark = pytest.mark.unit


class TestTheClassification:
    def test_a_page_that_came_back_as_content_is_valid(self):
        assert verdict.classify_probe({}) == verdict.VALID

    def test_a_login_wall_is_expired(self):
        assert verdict.classify_probe({'login_wall': True}) == verdict.EXPIRED

    @pytest.mark.parametrize(
        'facts',
        [
            {'error': 'driver died'},
            {'unreachable': True},
            {'unreachable': True, 'login_wall': True},
            {'risk_blocked': True},
        ],
    )
    def test_a_failure_to_observe_never_calls_the_session_dead(self, facts):
        """An unverifiable page is not evidence about the cookie — it outranks a wall."""
        assert verdict.classify_probe(facts) == verdict.UNKNOWN

    def test_a_risk_page_does_not_hide_a_wall_in_the_same_answer(self):
        assert verdict.classify_probe({'login_wall': True, 'risk_blocked': True}) == verdict.EXPIRED


class TestWhatBlocksARun:
    def test_the_blocking_set_is_the_users_own_decision_and_nothing_else(self):
        assert verdict.BLOCKING == (verdict.EXPIRED, verdict.NO_COOKIE, verdict.COOLING)

    @pytest.mark.parametrize('state', verdict.BLOCKING)
    def test_a_blocking_state_says_so(self, state):
        assert verdict.is_blocking(state) is True

    @pytest.mark.parametrize('state', [verdict.VALID, verdict.UNKNOWN, verdict.NO_LOGIN, verdict.NOT_CRAWLABLE])
    def test_an_unclear_answer_never_blocks(self, state):
        assert verdict.is_blocking(state) is False


class TestTheSentenceKey:
    def test_every_state_has_its_own_sentence(self):
        for state in (verdict.VALID, verdict.EXPIRED, verdict.UNKNOWN, verdict.NO_COOKIE, verdict.NO_LOGIN):
            assert verdict.REASONS[state]

    def test_an_unnamed_state_reads_as_could_not_check_not_as_a_crash(self):
        assert verdict.reason_key('made-up') == verdict.REASONS[verdict.UNKNOWN]


class TestTheCacheSlot:
    def test_two_spellings_of_the_default_login_share_one_slot(self):
        assert verdict.cache_key('u_a', 'zhihu', 'default', True) == verdict.cache_key('u_a', 'zhihu', '', True)

    def test_two_accounts_do_not_share_an_answer(self):
        assert verdict.cache_key('u_a', 'zhihu', 'work', True) != verdict.cache_key('u_a', 'zhihu', '', True)

    def test_the_profile_mode_is_part_of_the_question_asked(self):
        assert verdict.cache_key('u_a', 'zhihu', '', True) != verdict.cache_key('u_a', 'zhihu', '', False)

    def test_the_scope_comes_first_so_one_account_cannot_read_anothers_verdict(self):
        key = verdict.cache_key('u_a', 'zhihu', 'work', True)
        assert key[0] == 'u_a'
        assert key != verdict.cache_key('u_b', 'zhihu', 'work', True)


class TestWhatMayBeCached:
    @pytest.mark.parametrize('state', [verdict.VALID, verdict.EXPIRED])
    def test_a_fact_about_the_session_is_reusable(self, state):
        assert verdict.cacheable(state) is True

    @pytest.mark.parametrize('state', [verdict.UNKNOWN, verdict.NO_COOKIE, verdict.COOLING])
    def test_could_not_check_is_never_reused(self, state):
        assert verdict.cacheable(state) is False


class TestTheTtlBoundary:
    def test_a_verdict_read_exactly_at_the_ttl_is_still_quotable(self):
        assert verdict.is_fresh(100.0, 400.0, 300) is True

    def test_a_verdict_older_than_the_ttl_is_not(self):
        assert verdict.is_fresh(100.0, 400.001, 300) is False

    def test_a_clock_that_went_backwards_does_not_discard_a_fresh_answer(self):
        assert verdict.is_fresh(100.0, 99.0, 0) is True
