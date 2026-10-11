"""The executor's bert degrade-and-report seam (``app._resolve_bert_mode``).

The analyzers still refuse an unrunnable ``bert`` by name when reached directly; the node executor
now degrades such a run to the op's dependency-free mode (sentiment→snownlp, emotion/tendency→ml)
and PRINTS which mode actually produced the column, so the general method is usable on a torch-less
machine without a silent cross-model substitution. These tests drive the pure helper with the two
availability primitives (``bert_backend`` / ``resolve_bert_model``) and the console writer stubbed, so
they measure the decision + the report, not a real model load.
"""


class TestBertDegrade:
    @staticmethod
    def _capture_logs(app_module, monkeypatch):
        logs = []
        monkeypatch.setattr(app_module, 'add_log', lambda *a, **k: logs.append(a[0] if a else ''))
        return logs

    def test_unrunnable_bert_sentiment_degrades_to_snownlp_and_reports(self, app_module, monkeypatch):
        logs = self._capture_logs(app_module, monkeypatch)
        monkeypatch.setattr(app_module, 'bert_backend', lambda: 'torch, transformers')
        got = app_module._resolve_bert_mode('sentiment', 'bert', {'bert_model': ''})
        assert got == 'snownlp', 'a missing torch stack must not abort the node — fall back to SnowNLP'
        assert any('snownlp' in line for line in logs), f'the fallback must be printed, got {logs}'

    def test_unrunnable_bert_emotion_and_tendency_degrade_to_ml(self, app_module, monkeypatch):
        self._capture_logs(app_module, monkeypatch)
        monkeypatch.setattr(app_module, 'bert_backend', lambda: '')
        monkeypatch.setattr(app_module, 'resolve_bert_model', lambda spec: '')
        assert app_module._resolve_bert_mode('emotion', 'bert', {'bert_model': ''}) == 'ml'
        assert app_module._resolve_bert_mode('tendency', 'bert', {'bert_model': ''}) == 'ml'

    def test_runnable_bert_stays_bert_and_says_nothing(self, app_module, monkeypatch):
        logs = self._capture_logs(app_module, monkeypatch)
        monkeypatch.setattr(app_module, 'bert_backend', lambda: '')
        monkeypatch.setattr(app_module, 'resolve_bert_model', lambda spec: '/models/registered-bert')
        assert app_module._resolve_bert_mode('sentiment', 'bert', {'bert_model': 'x'}) == 'bert'
        assert logs == [], 'a runnable bert must not log any fallback'

    def test_a_non_bert_mode_is_left_alone(self, app_module, monkeypatch):
        logs = self._capture_logs(app_module, monkeypatch)
        # Even with bert unavailable, a snownlp/ml/llm request passes through untouched.
        monkeypatch.setattr(app_module, 'bert_backend', lambda: 'torch')
        for mode in ('snownlp', 'ml', 'llm'):
            assert app_module._resolve_bert_mode('sentiment', mode, {}) == mode
        assert logs == [], 'only an explicit bert is ever degraded'
