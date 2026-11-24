"""The record decisions behind a 继续 press (``engine.decide``).

A split-serial canvas opens one record per workflow as its turn arrives, and the resume path
adopts the PREVIOUS attempt's row by workflow NAME. The rule worth pinning: adoption CONSUMES the
candidate. Two components of one canvas may carry the same name (validate asks a name node for a
non-empty label, not for uniqueness), and a name match that stayed in the candidate list handed both
components the same run_id — the second component's ``start_run`` upsert reset the first's record,
its verdict overwrote it, and the other same-named row of the previous attempt became an orphan
nothing adopts.

The functions moved out of ``engine/run.py`` into ``engine/decide.py`` on 2026-11-24: they were
pure already, and this file proves it without a store, a lock or a workflow.
"""

import random

import pytest

from engine.decide import choose_record, record_belongs, record_has_component, split_records

pytestmark = pytest.mark.unit


def _candidates(*names):
    """Resumable rows with DISTINCT ids even at the same workflow name — the previous
    attempt opened one record per component, so two 热榜 rows are two run_ids."""
    return [{'run_id': f'rid-{position}-{name}', 'workflow_name': name} for position, name in enumerate(names)]


def _row(run_id: str, name: str = 'crawl', fingerprint: str = 'fp', nodes: list | None = None, **extra) -> dict:
    return {
        'run_id': run_id,
        'workflow_name': name,
        'workflow_fingerprint': fingerprint,
        'nodes': nodes if nodes is not None else [{'node_id': 'src'}],
        'wf_count': 1,
        **extra,
    }


class TestChooseRecord:
    def test_a_plain_run_adopts_nothing(self):
        assert choose_record('热榜', _candidates('热榜'), resuming=False) == (None, {})

    def test_a_resume_adopts_the_matching_row(self):
        resumable = _candidates('热榜', '评论')
        position, row = choose_record('评论', resumable, resuming=True)
        assert row == {'run_id': 'rid-1-评论', 'workflow_name': '评论'}
        assert position == 1

    def test_an_unmatched_name_opens_a_fresh_record(self):
        assert choose_record('新组件', _candidates('热榜'), resuming=True) == (None, {})

    def test_two_same_named_components_adopt_two_different_rows(self):
        """THE rule: the first 热榜 takes the first row, the second 热榜 takes the second —
        never one row shared by both (the second's upsert reset the first's record) and
        never one row adopted twice while the other orphans."""
        resumable = _candidates('热榜', '热榜')
        first_at, first = choose_record('热榜', resumable, resuming=True)
        resumable.pop(first_at)
        second_at, second = choose_record('热榜', resumable, resuming=True)
        resumable.pop(second_at)
        assert first['run_id'] == 'rid-0-热榜'
        assert second['run_id'] == 'rid-1-热榜'
        assert resumable == [], 'both candidates are consumed: nothing is left to double-adopt'

    def test_the_adopted_row_is_a_copy(self):
        resumable = _candidates('热榜')
        _, adopted = choose_record('热榜', resumable, resuming=True)
        adopted['workflow_name'] = 'mutated'
        assert resumable[0]['workflow_name'] == '热榜'

    def test_the_row_the_user_pressed_continue_on_wins_over_a_newer_name_match(self):
        """The name-only lookup adopted the NEWEST row of that workflow, so 继续 on an older
        interrupted row re-ran a newer completed record and never filled the chosen one."""
        resumable = [
            {'run_id': 'newer', 'workflow_name': '热榜'},
            {'run_id': 'requested', 'workflow_name': '热榜'},
        ]
        position, adopted = choose_record('热榜', resumable, resuming=True, requested='requested')
        assert adopted['run_id'] == 'requested'
        resumable.pop(position)
        assert [row['run_id'] for row in resumable] == ['newer'], 'the adopted row is consumed'

    def test_a_requested_row_of_another_component_falls_back_to_this_one(self):
        """The banner offers each component's own row; pressing it on 评论 must not hand the
        first component (热榜) a record that belongs to 评论."""
        resumable = [
            {'run_id': 'comment-row', 'workflow_name': '评论'},
            {'run_id': 'hot-row', 'workflow_name': '热榜'},
        ]
        position, adopted = choose_record('热榜', resumable, resuming=True, requested='comment-row')
        assert adopted['run_id'] == 'hot-row'
        resumable.pop(position)
        assert [row['run_id'] for row in resumable] == ['comment-row']

    def test_a_label_edit_still_adopts_the_same_component_by_fingerprint(self):
        """The workflow name is a label, not an input; the fingerprint and node set survive it."""
        resumable = [_row('old-row', name='旧名字', fingerprint='fp-1', nodes=[{'node_id': 'n1'}])]
        _, adopted = choose_record(
            '新名字', resumable, resuming=True, requested='old-row', fingerprint='fp-1', node_ids={'n1'}
        )
        assert adopted['run_id'] == 'old-row'

    def test_a_same_named_row_with_no_node_of_this_component_is_not_adopted(self):
        resumable = [_row('crawl-row', name='工作流', fingerprint='fp', nodes=[{'node_id': 'crawl-1'}])]
        assert choose_record('工作流', resumable, resuming=True, requested='crawl-row', node_ids={'upload-1'}) == (
            None,
            {},
        )

    def test_a_same_named_row_of_another_fingerprint_is_skipped(self):
        resumable = [_row('other-fp', fingerprint='other'), _row('mine')]
        _, adopted = choose_record('crawl', resumable, resuming=True, node_ids={'src'}, fingerprint='fp')
        assert adopted['run_id'] == 'mine'

    def test_no_choice_ever_crosses_a_fingerprint(self):
        """Property: over random row sets, the adopted row is always this canvas or this name."""
        rng = random.Random(20261124)
        for _ in range(200):
            resumable = [
                _row(
                    f'r{i}',
                    name=rng.choice(['crawl', 'upload', '']),
                    fingerprint=rng.choice(['', 'fp', 'other']),
                    nodes=[{'node_id': rng.choice(['src', 'upload', 'ana'])}],
                )
                for i in range(rng.randint(0, 6))
            ]
            _, row = choose_record('crawl', resumable, resuming=True, node_ids={'src'}, fingerprint='fp')
            if row:
                assert row['workflow_name'] == 'crawl' or row['workflow_fingerprint'] == 'fp'
                assert row['workflow_fingerprint'] in ('', 'fp')


class TestTheRequestedRowBelongsToThisComponent:
    """The id the user pressed 继续 on may only be kept by the component that owns that row.

    When a serial canvas's sibling record was deleted (or aged out by retention) the first
    component used to write its nodes into the OTHER workflow's record: ``start_run`` renamed
    that row, ``node_done`` was then counted against one component's ``node_total`` (the panel
    read 4/3), and the history carried the same id twice. An empty fingerprint on either side
    is "not recorded", never a mismatch — old rows and direct callers rely on that.
    """

    def test_a_row_carrying_this_components_node_belongs_to_it(self):
        record = {'run_id': 'r', 'workflow_fingerprint': 'fp', 'nodes': [{'node_id': 'n1'}]}
        assert record_belongs(record, {'n1', 'n2'}, 'fp') is True

    def test_a_row_of_the_other_workflow_does_not(self):
        record = {'run_id': 'r', 'workflow_fingerprint': 'fp', 'nodes': [{'node_id': 'upload-1'}]}
        assert record_belongs(record, {'crawl-1'}, 'fp') is False

    def test_a_different_canvas_fingerprint_does_not(self):
        record = {'run_id': 'r', 'workflow_fingerprint': 'other', 'nodes': [{'node_id': 'n1'}]}
        assert record_belongs(record, {'n1'}, 'fp') is False

    def test_a_record_with_no_fingerprint_or_nodes_is_acceptable(self):
        assert record_belongs({'run_id': 'r'}, {'n1'}, 'fp') is True
        assert record_belongs({'run_id': 'r', 'workflow_fingerprint': 'fp'}, {'n1'}, '') is True

    def test_a_missing_record_never_belongs(self):
        assert record_belongs(None, {'n1'}, 'fp') is False
        assert record_belongs({}, {'n1'}, 'fp') is False

    def test_a_missing_row_is_not_a_mismatch_at_the_node_level(self):
        """``record_belongs`` is the door that refuses a missing row; this predicate only reads nodes."""
        assert record_has_component(None, {'n1'}) is True
        assert record_has_component(_row('r', nodes=[{'node_id': 'n1'}]), {'n1', 'n2'}) is True
        assert record_has_component(_row('r', nodes=[{'node_id': 'n1'}]), {'n2'}) is False


class TestWhenTheRecordsAreSplit:
    """Serial is one record per workflow — except a 继续 onto a canvas-wide row."""

    def test_serial_with_several_workflows_splits(self):
        assert split_records('serial', 2, None) is True

    def test_parallel_is_one_record_for_the_canvas(self):
        assert split_records('parallel', 3, None) is False

    def test_one_workflow_is_one_record(self):
        assert split_records('serial', 1, None) is False

    def test_a_continued_canvas_wide_record_keeps_its_one_row(self):
        """Its rows are filed under that id; per-component records would refuse it and every
        component but the first would re-crawl paid work."""
        assert split_records('serial', 2, {'run_id': 'p', 'wf_count': 2}) is False

    def test_a_continued_component_record_still_splits(self):
        assert split_records('serial', 2, {'run_id': 'a', 'wf_count': 1}) is True
