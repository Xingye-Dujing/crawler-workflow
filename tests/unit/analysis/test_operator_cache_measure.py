"""Would an operator-level cache ever pay for itself? Measured, not assumed.

``docs/architecture/w7-incremental.md`` refuses to build the W7-2 cache without a hit-rate number
from a real canvas, and the two halves of the question are answered by different machinery:

* node-level reuse (fingerprint + asset lineage) decides whether the analysis node runs AT ALL;
* the operator cache would sit inside one run of that node, keyed ``(op, params, input_hash,
  columns)``.

So the measurement has to go through ``run_node_durable`` with a real ``RunStore`` — a test that
calls ``execute_analysis_node`` directly would report every step as a cache opportunity because it
never asks the reuse question. What it counts is OP INVOCATIONS per scenario; the numbers quoted in
the doc are the ones asserted here.
"""

import nodes.executors.analysis as analysis_exec
import pandas as pd
import pytest

from engine.run import node as node_module
from engine.run.asset import record_asset
from services.analysis.pipeline import DataAnalysisService
from services.runs.store import RunStore

pytestmark = pytest.mark.unit

_ROWS = [{'正文': '  三亚 的海  ', '标题': ' A '}, {'正文': '', '标题': 'B'}, {'正文': '第三行', '标题': ' C'}]


class _Counter:
    """Every op the pipeline runs, in order — the cache's opportunity is a repeat here."""

    def __init__(self):
        self.calls: list[str] = []

    def wrap(self, operations: dict) -> dict:
        counted = {}
        for name, func in operations.items():

            def run(df, _f=func, _n=name, **kwargs):
                self.calls.append(_n)
                return _f(df, **kwargs)

            counted[name] = run
        return counted

    def take(self) -> list[str]:
        out, self.calls = self.calls, []
        return out


@pytest.fixture
def harness(tmp_path, monkeypatch):
    store = RunStore(str(tmp_path / 'runs.db'))
    store.start_run('r1', 'demo', 'fp-canvas', mode='serial', headless=True, llm={}, lang='zh', node_total=1)
    counter = _Counter()

    monkeypatch.setattr(node_module, 'add_log', lambda *_a, **_k: None)
    monkeypatch.setattr(analysis_exec, 'add_log', lambda *_a, **_k: None)
    monkeypatch.setattr(analysis_exec, 'get_run_store', lambda: None)
    real_operations = DataAnalysisService._operations.__func__
    monkeypatch.setattr(
        DataAnalysisService,
        '_operations',
        classmethod(lambda _cls: counter.wrap(dict(real_operations(_cls)))),
    )
    monkeypatch.setattr(
        node_module,
        'execute_node',
        lambda node, headless, primary, upstream=None, ctx=None, platform_of=None, label_of=None: (
            analysis_exec.execute_analysis_node(node, primary, upstream=upstream, ctx=ctx, label_of=label_of)
        ),
    )

    def attempt(steps, fingerprint, upstream_rows, resume, statuses):
        node = {'id': 'an-1', 'type': 'analysis', 'params': {'steps': steps}}
        ctx = {
            'store': store,
            'run_id': 'r1',
            'resume': resume,
            'fingerprints': {'an-1': fingerprint},
            'statuses': statuses,
            'open_records': [],
        }
        # The parent ran first, so its asset describes the table this node is about to read. Without
        # it the lineage is UNKNOWN and reuse is kept by design — which is the one way to make this
        # measurement lie about the changed-upstream case.
        record_asset(store, ctx, {'id': 'up-1', 'type': 'upload'}, 'up-1', upstream_rows, [])
        rows, status = node_module.run_node_durable(ctx, node, True, upstream_rows, [('up-1', upstream_rows)], 0)
        return rows, status, store.node_statuses('r1')

    yield attempt, counter, store
    store.close()


_STEP_STRIP = {'op': 'strip_whitespace', 'params': {'columns': ['正文', '标题']}}
_STEP_DROP = {'op': 'drop_null', 'params': {'columns': ['正文']}}


class TestWhatAnOperatorCacheCouldSave:
    def test_the_common_resume_case_offers_no_operator_to_cache(self, harness):
        """A resume with nothing edited does not run the node, so there is no step to answer."""
        attempt, counter, _store = harness
        _rows, status, statuses = attempt([_STEP_STRIP, _STEP_DROP], 'fp-2step', _ROWS, False, {})
        assert status == 'done'
        assert counter.take() == ['strip_whitespace', 'drop_null']

        _rows, status, _statuses = attempt([_STEP_STRIP, _STEP_DROP], 'fp-2step', _ROWS, True, statuses)
        assert status == 'restored'
        assert counter.take() == [], 'a restored node executed a step, so the cache measured the wrong layer'

    def test_editing_the_pipeline_tail_re_offers_every_earlier_step(self, harness):
        """Appending a step changes the node's fingerprint, so the whole node re-runs.

        The two leading steps have the same input, the same params and the same columns as the
        first attempt — this is the ONE scenario an operator cache answers, and it is worth
        exactly ``len(prefix)`` calls.
        """
        attempt, counter, _store = harness
        _rows, _status, statuses = attempt([_STEP_STRIP, _STEP_DROP], 'fp-2step', _ROWS, False, {})
        assert counter.take() == ['strip_whitespace', 'drop_null']

        longer = [
            _STEP_STRIP,
            _STEP_DROP,
            {'op': 'filter_rows', 'params': {'column': '标题', 'op': 'contains', 'value': 'A'}},
        ]
        _rows, status, _statuses = attempt(longer, 'fp-3step', _ROWS, False, statuses)
        assert status == 'done'
        assert counter.take() == ['strip_whitespace', 'drop_null', 'filter_rows']
        assert counter.calls == []

    def test_a_changed_upstream_re_offers_nothing(self, harness):
        """Every key carries the input hash: one more parent row makes all of them miss."""
        attempt, counter, _store = harness
        _rows, _status, statuses = attempt([_STEP_STRIP, _STEP_DROP], 'fp-2step', _ROWS, False, {})
        assert counter.take() == ['strip_whitespace', 'drop_null']

        grown = [*_ROWS, {'正文': '新行', '标题': 'D'}]
        _rows, status, _statuses = attempt([_STEP_STRIP, _STEP_DROP], 'fp-2step', grown, True, statuses)
        assert status == 'done', 'a resume over a changed parent must re-execute the node'
        assert counter.take() == ['strip_whitespace', 'drop_null']

    def test_what_the_cache_would_have_to_store(self, harness):
        """The price of those saved calls: every intermediate table, keyed by input hash."""
        attempt, counter, _store = harness
        rows, _status, _stat0 = attempt([_STEP_STRIP, _STEP_DROP], 'fp-2step', _ROWS, False, {})
        counter.take()

        staged = pd.DataFrame(_ROWS)
        sizes = []
        for step in (_STEP_STRIP, _STEP_DROP):
            staged = DataAnalysisService.run_pipeline(staged, [step])[0]
            sizes.append(len(staged.to_json(orient='records', force_ascii=False).encode('utf-8')))

        # Two intermediate tables for two steps — the last one is the node's own output, which
        # `node_rows` already stores. So a 2-step node pays one extra table to save two cheap
        # pandas passes; the analysis node's expensive step (topic/LLM) is cached per row already.
        assert len(rows) == 2
        assert len(sizes) == 2 and all(size > 0 for size in sizes)
