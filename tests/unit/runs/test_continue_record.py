"""The resume-adoption rule behind a 继续 press (``engine.run._continue_record``).

A split-serial canvas opens one record per workflow as its turn arrives, and the resume
path adopts the PREVIOUS attempt's row by workflow NAME. The rule worth pinning: adoption
CONSUMES the candidate. Two components of one canvas may carry the same name (validate
asks a name node for a non-empty label, not for uniqueness), and a name match that stayed
in the candidate list handed both components the same run_id — the second component's
``start_run`` upsert reset the first's record, its verdict overwrote it, and the other
same-named row of the previous attempt became an orphan nothing adopts.
"""

import pytest

from engine.run import _continue_record

pytestmark = pytest.mark.unit


def _candidates(*names):
    """Resumable rows with DISTINCT ids even at the same workflow name — the previous
    attempt opened one record per component, so two 热榜 rows are two run_ids."""
    return [{'run_id': f'rid-{position}-{name}', 'workflow_name': name} for position, name in enumerate(names)]


class TestContinueRecord:
    def test_a_plain_run_adopts_nothing(self):
        assert _continue_record('热榜', _candidates('热榜'), resuming=False) == {}

    def test_a_resume_adopts_the_matching_row(self):
        resumable = _candidates('热榜', '评论')
        assert _continue_record('评论', resumable, resuming=True) == {
            'run_id': 'rid-1-评论',
            'workflow_name': '评论',
        }

    def test_an_unmatched_name_opens_a_fresh_record(self):
        assert _continue_record('新组件', _candidates('热榜'), resuming=True) == {}

    def test_two_same_named_components_adopt_two_different_rows(self):
        """THE rule: the first 热榜 takes the first row, the second 热榜 takes the second —
        never one row shared by both (the second's upsert reset the first's record) and
        never one row adopted twice while the other orphans."""
        resumable = _candidates('热榜', '热榜')
        first = _continue_record('热榜', resumable, resuming=True)
        second = _continue_record('热榜', resumable, resuming=True)
        assert first['run_id'] == 'rid-0-热榜'
        assert second['run_id'] == 'rid-1-热榜'
        assert resumable == [], 'both candidates are consumed: nothing is left to double-adopt'

    def test_the_adopted_dict_survives_its_removal_from_the_list(self):
        resumable = _candidates('热榜')
        adopted = _continue_record('热榜', resumable, resuming=True)
        assert adopted == {'run_id': 'rid-0-热榜', 'workflow_name': '热榜'}
        assert resumable == []

    def test_the_row_the_user_pressed_continue_on_wins_over_a_newer_name_match(self):
        """The name-only lookup adopted the NEWEST row of that workflow, so 继续 on an older
        interrupted row re-ran a newer completed record and never filled the chosen one."""
        resumable = [
            {'run_id': 'newer', 'workflow_name': '热榜'},
            {'run_id': 'requested', 'workflow_name': '热榜'},
        ]
        adopted = _continue_record('热榜', resumable, resuming=True, requested='requested')
        assert adopted['run_id'] == 'requested'
        assert [row['run_id'] for row in resumable] == ['newer'], 'the adopted row is consumed'

    def test_a_requested_row_of_another_component_falls_back_to_this_one(self):
        """The banner offers each component's own row; pressing it on 评论 must not hand the
        first component (热榜) a record that belongs to 评论."""
        resumable = [
            {'run_id': 'comment-row', 'workflow_name': '评论'},
            {'run_id': 'hot-row', 'workflow_name': '热榜'},
        ]
        adopted = _continue_record('热榜', resumable, resuming=True, requested='comment-row')
        assert adopted['run_id'] == 'hot-row'
        assert [row['run_id'] for row in resumable] == ['comment-row']
