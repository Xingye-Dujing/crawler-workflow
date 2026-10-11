"""The executor's bert default-model + degrade-and-report seam (``app._effective_bert_model`` /
``app._resolve_bert_mode``).

BERT is now the DEFAULT for sentiment/emotion/tendency. A node that names no model resolves the
operation's registered default (``_effective_bert_model`` → ``default_model_path_for``), so a default
node actually runs bert. When bert truly cannot run (missing torch/transformers, or nothing registered
to load), the executor degrades to the op's dependency-free mode (sentiment→snownlp, emotion/tendency→ml)
and PRINTS which mode produced the column — never a silent cross-model swap. The analyzers still refuse a
direct unrunnable bert by name (defense in depth). These drive the pure helpers with the availability
primitives stubbed, so they measure the decision + the report, not a real model load.
"""


class TestBertDefaultModel:
    def test_a_blank_model_resolves_to_the_op_registered_default(self, app_module, monkeypatch):
        monkeypatch.setattr(app_module, 'default_model_path_for', lambda op: f'/models/{op}')
        assert app_module._effective_bert_model('sentiment', {}) == '/models/sentiment'
        assert app_module._effective_bert_model('emotion', {'bert_model': ''}) == '/models/emotion'

    def test_a_named_model_wins_over_the_registry_default(self, app_module, monkeypatch):
        monkeypatch.setattr(app_module, 'default_model_path_for', lambda op: '/models/default')
        assert app_module._effective_bert_model('sentiment', {'bert_model': '/my/path'}) == '/my/path'


class TestBertDegrade:
    @staticmethod
    def _capture_logs(app_module, monkeypatch):
        logs = []
        monkeypatch.setattr(app_module, 'add_log', lambda *a, **k: logs.append(a[0] if a else ''))
        return logs

    def test_unrunnable_bert_sentiment_degrades_to_snownlp_and_reports(self, app_module, monkeypatch):
        logs = self._capture_logs(app_module, monkeypatch)
        monkeypatch.setattr(app_module, 'bert_backend', lambda: 'torch, transformers')
        got = app_module._resolve_bert_mode('sentiment', 'bert', '')
        assert got == 'snownlp', 'a missing torch stack must not abort the node — fall back to SnowNLP'
        assert any('snownlp' in line for line in logs), f'the fallback must be printed, got {logs}'

    def test_unrunnable_bert_emotion_and_tendency_degrade_to_ml(self, app_module, monkeypatch):
        self._capture_logs(app_module, monkeypatch)
        monkeypatch.setattr(app_module, 'bert_backend', lambda: '')
        monkeypatch.setattr(app_module, 'resolve_bert_model', lambda spec: '')
        assert app_module._resolve_bert_mode('emotion', 'bert', '') == 'ml'
        assert app_module._resolve_bert_mode('tendency', 'bert', '') == 'ml'

    def test_runnable_bert_stays_bert_and_says_nothing(self, app_module, monkeypatch):
        logs = self._capture_logs(app_module, monkeypatch)
        monkeypatch.setattr(app_module, 'bert_backend', lambda: '')
        monkeypatch.setattr(app_module, 'resolve_bert_model', lambda spec: '/models/registered-bert')
        assert app_module._resolve_bert_mode('sentiment', 'bert', 'x') == 'bert'
        assert logs == [], 'a runnable bert must not log any fallback'

    def test_a_non_bert_mode_is_left_alone(self, app_module, monkeypatch):
        logs = self._capture_logs(app_module, monkeypatch)
        # Even with bert unavailable, a snownlp/ml/llm request passes through untouched.
        monkeypatch.setattr(app_module, 'bert_backend', lambda: 'torch')
        for mode in ('snownlp', 'ml', 'llm'):
            assert app_module._resolve_bert_mode('sentiment', mode, '') == mode
        assert logs == [], 'only a bert request is ever degraded'
