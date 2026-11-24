"""The rotation rule as a function: what may spend one of the user's accounts.

Every case here is an invariant the account pool exists to keep, and each one was violated by an
earlier build of the two executors: a network fault rotated an account away from a page the site
never served, a wall that had already answered rows rotated away the rows (and the login) with it,
and a stop pressed mid-link could still open the next login. The rule is pure, so the cases below
enumerate the inputs instead of scripting a browser.
"""

import pytest

from services.pool import policy
from services.pool.policy import ROTATE, SETTLE, Attempt, decide

pytestmark = pytest.mark.unit


class TestTheRuleRotates:
    def test_a_login_wall_that_stored_nothing_spends_the_next_login(self):
        decision = decide(Attempt(reason='login_wall', stored_rows=0, attempts_left=2))

        assert decision.rotates() and decision.reason == 'login_wall'

    def test_a_risk_page_is_the_same_evidence_against_the_session(self):
        assert decide(Attempt(reason='risk', stored_rows=0, attempts_left=1)).rotates()

    def test_a_budget_of_none_means_the_caller_only_asks_whether_the_outcome_justifies_it(self):
        """The source executor decides before it knows how many logins are left; the loop owns that."""
        assert decide(Attempt(reason='login_wall', stored_rows=0, attempts_left=None)).rotates()

    def test_the_decision_names_the_reason_so_the_console_line_can_quote_it(self):
        assert decide(Attempt(reason='risk', stored_rows=0, attempts_left=1)) == policy.Decision(ROTATE, 'risk')


class TestTheRuleDoesNotRotate:
    @pytest.mark.parametrize('reason', ['network', '', 'unknown'])
    def test_a_failure_that_names_neither_wall_nor_risk_is_not_evidence_about_the_login(self, reason):
        """A timeout, a dead cable or an un-named refusal says nothing about the account."""
        assert decide(Attempt(reason=reason, stored_rows=0, attempts_left=2)).action == SETTLE

    def test_rows_already_stored_keep_the_partial_and_continue_path(self):
        """Rotating a link that answered threw the answer away and re-paid for the same walk."""
        assert decide(Attempt(reason='login_wall', stored_rows=42, attempts_left=2)).action == SETTLE

    def test_a_stop_is_an_instruction_not_a_measurement(self):
        assert decide(Attempt(reason='login_wall', stored_rows=0, stopped=True, attempts_left=2)).action == SETTLE

    def test_a_node_that_is_not_rotating_never_claims_another_login(self):
        assert decide(Attempt(reason='login_wall', stored_rows=0, pooled=False, attempts_left=2)).action == SETTLE

    @pytest.mark.parametrize('attempts_left', [0, -1])
    def test_a_spent_budget_settles_instead_of_trying_again(self, attempts_left):
        assert decide(Attempt(reason='login_wall', stored_rows=0, attempts_left=attempts_left)).action == SETTLE

    def test_a_negative_row_count_reads_as_zero_rather_than_as_work(self):
        """A re-linked node reconciles against its own baseline; a negative is still no rows here."""
        assert decide(Attempt(reason='login_wall', stored_rows=-3, attempts_left=1)).rotates()


class TestTheOrderOfTheChecks:
    def test_stop_outranks_a_wall_because_it_is_the_users_answer(self):
        assert decide(Attempt(reason='login_wall', stored_rows=0, stopped=True, attempts_left=5)).action == SETTLE

    def test_rows_outrank_a_remaining_budget(self):
        """Having another login left is not a reason to throw away an answer already read."""
        assert decide(Attempt(reason='risk', stored_rows=1, attempts_left=5)).action == SETTLE
