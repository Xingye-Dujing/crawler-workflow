"""The process executor's bert default-model + degrade-and-report seam.

BERT is now the DEFAULT for sentiment/emotion/tendency. A node that names no model resolves the
operation's registered default (``_effective_bert_model`` → ``default_model_path_for``), so a default
node actually runs bert. When bert truly cannot run (missing torch/transformers, or nothing registered
to load), the executor degrades to the op's dependency-free mode (sentiment→snownlp, emotion/tendency→ml)
and PRINTS which mode produced the column — never a silent cross-model swap. The analyzers still refuse a
direct unrunnable bert by name (defense in depth). These drive the pure helpers with the availability
primitives stubbed, so they measure the decision + the report, not a real model load.
"""

import pytest


@pytest.fixture
def process_exec():
    """The process-node plugin, imported inside the fixture (never at module scope)."""
    from nodes.executors import process

    return process


class TestBertDefaultModel:
    def test_all_three_analysis_ops_declare_bert_as_the_default(self):
        """The whole point of "默认 BERT + 跑不动自动退": the executor's declared default for each
        bert-capable op IS bert (the frontend panel default is pinned in test_frontend_js). Without
        this, someone could flip PROCESS_ENUMS['sentiment'/'tendency'] back to snownlp/llm — only
        emotion was previously guarded — and an untouched node would silently stop running bert."""
        from services.process_params import PROCESS_ENUMS

        for op in ('sentiment', 'emotion', 'tendency'):
            default, allowed = PROCESS_ENUMS[op]['mode']
            assert default == 'bert', f'{op} must default to the recommended main model, got {default!r}'
            assert 'bert' in allowed, f'{op} must accept bert'

    def test_a_blank_model_resolves_to_the_op_registered_default(self, process_exec, monkeypatch):
        monkeypatch.setattr(process_exec, 'default_model_path_for', lambda op: f'/models/{op}')
        assert process_exec._effective_bert_model('sentiment', {}) == '/models/sentiment'
        assert process_exec._effective_bert_model('emotion', {'bert_model': ''}) == '/models/emotion'

    def test_a_named_model_wins_over_the_registry_default(self, process_exec, monkeypatch):
        monkeypatch.setattr(process_exec, 'default_model_path_for', lambda op: '/models/default')
        assert process_exec._effective_bert_model('sentiment', {'bert_model': '/my/path'}) == '/my/path'

    def test_the_single_ticked_model_is_the_one_that_runs(self, process_exec, monkeypatch):
        """The panel's checkboxes write ``bert_models``, not the legacy ``bert_model`` box. Exactly
        ONE ticked model goes down this single path (the executor branches to the comparison only on
        ``> 1``), so reading only the legacy field made a ticked model load NOTHING and fall to the
        registry default: a different model produced the column, claimed none of it, and printed
        nothing. That is the forbidden silent cross-model swap, and it decided degrade-vs-keep on the
        wrong path too."""
        monkeypatch.setattr(process_exec, 'default_model_path_for', lambda op: '/models/registry')
        picked = {'bert_models': '/models/ticked'}
        assert process_exec._effective_bert_model('tendency', picked) == '/models/ticked'
        # Blank/spaces in the list box state nothing, so the registry default still answers.
        assert process_exec._effective_bert_model('tendency', {'bert_models': '  , , '}) == '/models/registry'
        # A MULTI selection is not this path at all: it has no single answer to name.
        assert process_exec._effective_bert_model('tendency', {'bert_models': '/b,/a'}) == '/models/registry'


class TestBertDegrade:
    @staticmethod
    def _capture_logs(process_exec, monkeypatch):
        logs = []
        monkeypatch.setattr(process_exec, 'add_log', lambda *a, **k: logs.append(a[0] if a else ''))
        return logs

    def test_unrunnable_bert_sentiment_degrades_to_snownlp_and_reports(self, process_exec, monkeypatch):
        logs = self._capture_logs(process_exec, monkeypatch)
        monkeypatch.setattr(process_exec, 'bert_backend', lambda: 'torch, transformers')
        got = process_exec._resolve_bert_mode('sentiment', 'bert', '')
        assert got == 'snownlp', 'a missing torch stack must not abort the node — fall back to SnowNLP'
        assert any('snownlp' in line for line in logs), f'the fallback must be printed, got {logs}'

    def test_unrunnable_bert_emotion_and_tendency_degrade_to_ml(self, process_exec, monkeypatch):
        self._capture_logs(process_exec, monkeypatch)
        monkeypatch.setattr(process_exec, 'bert_backend', lambda: '')
        monkeypatch.setattr(process_exec, 'resolve_bert_model', lambda spec: '')
        assert process_exec._resolve_bert_mode('emotion', 'bert', '') == 'ml'
        assert process_exec._resolve_bert_mode('tendency', 'bert', '') == 'ml'

    def test_runnable_bert_stays_bert_and_says_nothing(self, process_exec, monkeypatch):
        logs = self._capture_logs(process_exec, monkeypatch)
        monkeypatch.setattr(process_exec, 'bert_backend', lambda: '')
        monkeypatch.setattr(process_exec, 'resolve_bert_model', lambda spec: '/models/registered-bert')
        assert process_exec._resolve_bert_mode('sentiment', 'bert', 'x') == 'bert'
        assert logs == [], 'a runnable bert must not log any fallback'

    def test_a_non_bert_mode_is_left_alone(self, process_exec, monkeypatch):
        logs = self._capture_logs(process_exec, monkeypatch)
        # Even with bert unavailable, a snownlp/ml/llm request passes through untouched.
        monkeypatch.setattr(process_exec, 'bert_backend', lambda: 'torch')
        for mode in ('snownlp', 'ml', 'llm'):
            assert process_exec._resolve_bert_mode('sentiment', mode, '') == mode
        assert logs == [], 'only a bert request is ever degraded'

    def test_the_default_sentiment_node_completes_on_a_torch_less_machine(self, process_exec, monkeypatch):
        """The whole executor path, not just the helper: a freshly created sentiment node whose mode
        was never touched defaults to ``bert``; on a machine with no torch it must still RUN — degrade
        to the bundled SnowNLP and hand back a column — rather than refuse and leave the generic path
        unusable. This is the end-to-end guarantee the topic step already has for its ``auto`` default."""
        logs = self._capture_logs(process_exec, monkeypatch)
        monkeypatch.setattr(process_exec, 'bert_backend', lambda: 'torch, transformers')
        records = [{'正文': '很棒 我愛了 喜欢'}, {'正文': '太差了 垃圾 再也不买'}]
        node = {'id': 'n1', 'type': 'process', 'operation': 'sentiment', 'params': {}}
        out = process_exec.execute_process_node(node, records, run_ctx=None)
        assert len(out) == 2, 'a torch-less box must still get one row per input, not an abort'
        assert 'sentiment' in out[0], f'expected a sentiment column, got {sorted(out[0])}'
        assert any('snownlp' in line for line in logs), 'the degrade must be printed, never silent'
