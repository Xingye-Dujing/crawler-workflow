"""执行历史 files a run under the LEDGER's own id.

The same execution was a different object in 运行记录 and 执行历史: the history row minted its own
``uuid4`` id, so a record's metrics could never be related back to the run it belongs to.
"""

import pytest

from services.runs import history

pytestmark = pytest.mark.unit


class _FakeHistory:
    def __init__(self):
        self.rows = []

    def now(self):
        return '2026-01-01T00:00:00'

    def record_many(self, rows, log_label=''):
        self.rows = list(rows)


class _Engine:
    nodes = {'n1': {'type': 'process'}}


def test_the_history_row_carries_the_run_record_id(monkeypatch):
    fake = _FakeHistory()
    monkeypatch.setattr('runtime.state.history_service', fake)
    history.record_execution_history(
        None,
        _Engine(),
        {'n1': [{'text': '一条'}, {'text': '两条'}]},
        workflow_name='wf',
        run_id='abc123def456',
    )
    assert fake.rows, 'no metric was recorded'
    assert {row[0] for row in fake.rows} == {'abc123def456'}
