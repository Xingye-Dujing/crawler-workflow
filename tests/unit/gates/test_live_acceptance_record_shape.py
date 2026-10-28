"""The run-row shape rule, tested in the fast tier where it needs no browser.

:func:`live_acceptance.assert_record_shape` turns AGENTS' invariant (「并行是一条记录；串行是一 workflow
一行」) into an assertion, so it is graded against both shapes and against the way a shape breaks. A live
H1 that hard-coded the parallel ``wf_count == N`` went red on the user's **串行** canvas even though all
three legs had crawled honestly — the reporting line, not the crawl, failed. The whole point of reading
the mode off the row is that a canvas he flips 串行/并行 must not redden a run that did its work, and that
is exactly what the cases below pin.

Nothing here opens Chrome or touches ``scratchpad/live_audit``: the helper only reads a ``run.record`` and
a label→row map, so a couple of dicts are the faithful stand-ins.
"""

import live_acceptance as accept
import pytest

pytestmark = pytest.mark.unit


class _Run:
    def __init__(self, record: dict):
        self.record = record


def _part(label: str, source: str, mode: str) -> dict:
    return {'label': label, 'source': source, 'mode': mode}


# ─── the shape a 串行 run must show ─────────────────────────────────────


def test_serial_opens_one_row_per_leg_each_named_by_its_component():
    parts = [
        _part('作者', 'node-10', 'author'),
        _part('热榜', 'node-13', 'hot'),
        _part('评论', 'node-17', 'comments'),
    ]
    records = {
        '作者': {'mode': 'serial', 'wf_count': 1, 'workflow_name': '作者'},
        '热榜': {'mode': 'serial', 'wf_count': 1, 'workflow_name': '热榜'},
        '评论': {'mode': 'serial', 'wf_count': 1, 'workflow_name': '评论'},
    }
    run = _Run({'mode': 'serial', 'wf_count': 1, 'workflow_name': '作者'})
    accept.assert_record_shape(run, records, parts)


def test_serial_leg_recorded_as_parallel_is_caught():
    # A row that says the run was one piece of work, filed under a serial canvas, is the merged/mis-named
    # record AGENTS lists as a reporting bug — the panel cannot match it back to a node.
    parts = [_part('作者', 'node-10', 'author'), _part('评论', 'node-17', 'comments')]
    records = {
        '作者': {'mode': 'parallel', 'wf_count': 1, 'workflow_name': '作者'},
        '评论': {'mode': 'serial', 'wf_count': 1, 'workflow_name': '评论'},
    }
    run = _Run({'mode': 'serial'})
    with pytest.raises(AssertionError, match='parallel'):
        accept.assert_record_shape(run, records, parts)


def test_serial_leg_filed_under_another_component_name_is_caught():
    parts = [_part('作者', 'node-10', 'author'), _part('评论', 'node-17', 'comments')]
    records = {
        '作者': {'mode': 'serial', 'wf_count': 1, 'workflow_name': '作者'},
        # The comment leg's row carries the author's name — the 「列表对不上」 shape.
        '评论': {'mode': 'serial', 'wf_count': 1, 'workflow_name': '作者'},
    }
    run = _Run({'mode': 'serial'})
    with pytest.raises(AssertionError, match='does not name'):
        accept.assert_record_shape(run, records, parts)


def test_serial_row_claiming_more_than_one_workflow_is_caught():
    parts = [_part('作者', 'node-10', 'author')]
    records = {'作者': {'mode': 'serial', 'wf_count': 2, 'workflow_name': '作者'}}
    run = _Run({'mode': 'serial'})
    with pytest.raises(AssertionError, match='one workflow'):
        accept.assert_record_shape(run, records, parts)


# ─── the shape a 并行 run must show ─────────────────────────────────────


def test_parallel_is_one_joined_row_naming_every_leg():
    parts = [
        _part('作者', 'node-10', 'author'),
        _part('热榜', 'node-13', 'hot'),
        _part('评论', 'node-17', 'comments'),
    ]
    joined = '作者 + 热榜 + 评论'
    records = {part['label']: {'mode': 'parallel', 'wf_count': 3, 'workflow_name': joined} for part in parts}
    run = _Run({'mode': 'parallel', 'wf_count': 3, 'workflow_name': joined})
    accept.assert_record_shape(run, records, parts)


def test_parallel_row_counting_the_wrong_number_of_legs_is_caught():
    parts = [_part('作者', 'node-10', 'author'), _part('评论', 'node-17', 'comments')]
    records = {part['label']: {'mode': 'parallel', 'wf_count': 1, 'workflow_name': '作者 + 评论'} for part in parts}
    run = _Run({'mode': 'parallel', 'wf_count': 1, 'workflow_name': '作者 + 评论'})
    with pytest.raises(AssertionError, match='parallel record'):
        accept.assert_record_shape(run, records, parts)


def test_parallel_row_that_drops_a_leg_from_the_joined_name_is_caught():
    parts = [_part('作者', 'node-10', 'author'), _part('评论', 'node-17', 'comments')]
    # A label that silently fell out of the joined name is a row the panel lists short.
    records = {part['label']: {'mode': 'parallel', 'wf_count': 2, 'workflow_name': '作者'} for part in parts}
    run = _Run({'mode': 'parallel', 'wf_count': 2, 'workflow_name': '作者'})
    with pytest.raises(AssertionError, match='dropped from the joined'):
        accept.assert_record_shape(run, records, parts)


# ─── a row with no mode is never silently a pass ────────────────────────


def test_unrecognized_mode_refuses_instead_of_passing():
    parts = [_part('作者', 'node-10', 'author')]
    records = {'作者': {'mode': '', 'workflow_name': '作者'}}
    run = _Run({'mode': ''})
    with pytest.raises(AssertionError, match='recognizable mode'):
        accept.assert_record_shape(run, records, parts)
