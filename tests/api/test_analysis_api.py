"""Tests for the standalone analysis, visualization and export endpoints.

These three routes let the Analysis / Visualize / Save panels work without a
canvas at all, and they are backed by exactly the same services as the workflow
nodes — so what is worth pinning here is the HTTP contract around those
services:

* a run answers with a *new* dataset id, so its output can be charted or
  exported next, and the report says what each step removed,
* a chart spec is always JSON-safe: one bare ``NaN`` token would make the
  browser's ``JSON.parse`` reject the whole response,
* a bad spec or an unknown format is a 400 with a readable reason, never a
  traceback, and a render that fails still releases its matplotlib figure,
* a pipeline containing a sample step answers the same rows for the same input,
  so a repeated or resumed run cannot quietly change what downstream work was
  computed from,
* ML training only ever reports data problems — it never reaches a model
  server, so no transport stubbing is needed here.
"""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.api

RUN_STEPS = [
    {'op': 'drop_null', 'params': {'columns': ['score']}},
    {'op': 'drop_duplicates', 'params': {'columns': ['title']}},
]
DIRTY_RECORDS = [
    {'title': 'sanya', 'score': 3, 'city': 'Sanya'},
    {'title': 'haikou', 'score': 5, 'city': 'Haikou'},
    {'title': 'sanya', 'score': 2, 'city': 'Sanya'},
    {'title': 'boao', 'score': None, 'city': 'Boao'},
    {'title': 'xinglong', 'score': 7, 'city': 'Sanya'},
]
VIZ_RECORDS = [
    {'city': 'Sanya', 'likes': 10},
    {'city': 'Haikou', 'likes': 5},
    {'city': 'Sanya', 'likes': 7},
]


def _labeled_records(count: int = 12) -> list:
    """Balanced two-class text, which is the minimum a fit will accept."""
    return [
        {
            'text': f'lovely place number {i}' if i % 2 == 0 else f'awful crowd number {i}',
            'label': 'pos' if i % 2 == 0 else 'neg',
        }
        for i in range(count)
    ]


class TestAnalysisRun:
    def test_run_returns_a_new_dataset_and_a_step_report(self, client, paste):
        source_id = paste(DIRTY_RECORDS, name='dirty.csv')
        body = client.post('/api/analysis/run', json={'dataset_id': source_id, 'steps': RUN_STEPS}).get_json()
        assert body['ok'] is True
        assert body['row_count'] == 3
        # A cleaned table is a dataset of its own, so it stays addressable.
        assert body['dataset_id'] != source_id
        assert [step['op'] for step in body['report']] == ['drop_null', 'drop_duplicates']
        assert [(s['rows_before'], s['rows_after'], s['rows_removed']) for s in body['report']] == [
            (5, 4, 1),
            (4, 3, 1),
        ]
        assert [row['title'] for row in body['preview']] == ['sanya', 'haikou', 'xinglong']

        detail = client.get(f'/api/data/datasets/{body["dataset_id"]}').get_json()['dataset']
        assert detail['source'] == 'analysis'
        assert detail['name'] == 'cleaned'
        assert detail['row_count'] == 3

    def test_run_accepts_inline_records_and_no_steps(self, client):
        body = client.post('/api/analysis/run', json={'data': DIRTY_RECORDS, 'steps': []}).get_json()
        assert body['ok'] is True
        assert body['row_count'] == 5
        assert body['report'] == []

    def test_run_rejects_a_step_it_does_not_know(self, client, paste):
        dataset_id = paste(DIRTY_RECORDS, name='unknown-op.csv')
        response = client.post(
            '/api/analysis/run',
            json={'dataset_id': dataset_id, 'steps': [{'op': 'flatten_strings', 'params': {}}]},
        )
        assert response.status_code == 400
        body = response.get_json()
        assert body['ok'] is False
        assert 'Unknown analysis operation: flatten_strings' in body['error']

    def test_run_reports_a_filter_it_cannot_evaluate(self, client, paste):
        """``filter_rows`` with a text bound raises the service's own readable
        error, which the handler turns into a 400."""
        dataset_id = paste(DIRTY_RECORDS, name='bad-filter.csv')
        response = client.post(
            '/api/analysis/run',
            json={
                'dataset_id': dataset_id,
                'steps': [{'op': 'filter_rows', 'params': {'column': 'score', 'op': 'gt', 'value': 'high'}}],
            },
        )
        assert response.status_code == 400
        assert 'needs a numeric value' in response.get_json()['error']

    def test_run_needs_something_to_work_on(self, client):
        response = client.post('/api/analysis/run', json={'steps': RUN_STEPS})
        assert response.status_code == 400
        assert 'No data source provided' in response.get_json()['error']

    # ``join_tables`` is the one step whose parameters the *node* executor
    # supplies (the right-hand table comes from the second connection), so a
    # direct API call can never complete it — the handler answers 400 with the
    # reason rather than escaping run_pipeline's TypeError as a 500.
    def test_run_answers_a_readable_error_for_an_incomplete_join(self, client, paste):
        dataset_id = paste(DIRTY_RECORDS, name='join-me.csv')
        response = client.post(
            '/api/analysis/run',
            json={
                'dataset_id': dataset_id,
                'steps': [{'op': 'join_tables', 'params': {'how': 'left', 'left_on': 'city', 'right_on': 'city'}}],
            },
        )
        assert response.status_code == 400

    def test_run_can_feed_the_next_endpoint(self, client, paste):
        """The id it returns really is a dataset the rest of the API accepts."""
        source_id = paste(DIRTY_RECORDS, name='chain.csv')
        cleaned = client.post('/api/analysis/run', json={'dataset_id': source_id, 'steps': RUN_STEPS}).get_json()
        preview = client.post('/api/data/preview', json={'dataset_id': cleaned['dataset_id']}).get_json()
        assert preview['total_rows'] == 3
        inspect = client.post('/api/data/inspect', json={'dataset_id': cleaned['dataset_id']}).get_json()['report']
        assert inspect['duplicate_rows'] == 0


class TestSampleStepIsReproducible:
    """A sample step used to ride the process-wide RNG, so two runs of one input
    disagreed — the one thing the engine promises it never does (a resumed run
    re-reads rows an expensive downstream step was already paid for). The seed is
    now derived from the frame, and an explicit one still wins.
    """

    SAMPLE_STEPS = [{'op': 'sample_rows', 'params': {'n': 6}}]
    SEEDABLE_STEPS = [{'op': 'sample_rows', 'params': {'n': 6, 'seed': 11}}]
    FRAC_STEPS = [{'op': 'sample_rows', 'params': {'frac': 0.5}}]

    @staticmethod
    def _many_records(count: int = 40) -> list:
        # Every title is distinct, so a different sample is visible as a
        # different list rather than hiding behind repeated values.
        return [{'title': f'row-{i}', 'score': i % 7} for i in range(count)]

    @pytest.mark.parametrize(
        'steps', [SAMPLE_STEPS, SEEDABLE_STEPS, FRAC_STEPS], ids=['derived seed', 'explicit seed', 'frac']
    )
    def test_two_runs_of_one_input_answer_the_same_rows(self, client, paste, steps):
        records = self._many_records()
        dataset_id = paste(records, name='sample-me.csv')
        payload = {'dataset_id': dataset_id, 'steps': steps}
        first = client.post('/api/analysis/run', json=payload).get_json()
        second = client.post('/api/analysis/run', json=payload).get_json()
        assert first['ok'] is True and second['ok'] is True
        assert first['row_count'] == second['row_count'] == (6 if steps[0]['params'].get('n') else 20)
        titles = [row['title'] for row in second['preview']]
        assert titles == [row['title'] for row in first['preview']]
        # A sample really happened: it is neither the head nor the whole input.
        assert titles != [record['title'] for record in records[: len(titles)]]

    def test_the_pipeline_itself_is_deterministic_for_the_same_frame(self):
        """run_pipeline is pure — the same goes for the seed it derives."""
        import pandas as pd

        from services.data_analysis import DataAnalysisService, _stable_seed

        records = self._many_records()
        df = pd.DataFrame(records)
        first, _ = DataAnalysisService.run_pipeline(df, self.SAMPLE_STEPS)
        second, _ = DataAnalysisService.run_pipeline(df, self.SAMPLE_STEPS)
        assert first.equals(second)
        # Copying the frame must not change the answer: the seed describes the
        # data, not the object identity or the order the tests happened to run in.
        copied, _ = DataAnalysisService.run_pipeline(df.copy(), self.SAMPLE_STEPS)
        assert copied.equals(first)
        # And it is *derived from* the data, so another input lands elsewhere in
        # the seed space instead of every frame sharing one fixed draw.
        other = pd.DataFrame(records[::-1])
        assert _stable_seed(other) != _stable_seed(df)

    def test_an_explicit_seed_overrides_the_derived_one(self):
        import pandas as pd

        from services.data_analysis import DataAnalysisService

        df = pd.DataFrame(self._many_records())
        derived, _ = DataAnalysisService.run_pipeline(df, self.SAMPLE_STEPS)
        seeded, _ = DataAnalysisService.run_pipeline(df, self.SEEDABLE_STEPS)
        assert seeded['title'].tolist() != derived['title'].tolist()
        # Same seed, same rows — that is the whole point of exposing it.
        again, _ = DataAnalysisService.run_pipeline(df, self.SEEDABLE_STEPS)
        assert again.equals(seeded)


class TestVisualizeRender:
    def test_bar_chart_option_is_json_safe_and_aggregated(self, client, paste):
        dataset_id = paste(VIZ_RECORDS, name='viz.csv')
        response = client.post(
            '/api/visualize/render',
            json={'dataset_id': dataset_id, 'chart_type': 'bar', 'x_field': 'city', 'y_field': 'likes', 'agg': 'sum'},
        )
        body = response.get_json()
        assert body['ok'] is True and body['engine'] == 'echarts'
        option = body['option']
        assert option['series'][0]['type'] == 'bar'
        assert option['xAxis']['data'] == ['Haikou', 'Sanya']
        assert option['series'][0]['data'] == [5, 17]
        # Re-parsing with a strict parser is what the browser does.
        assert json.loads(json.dumps(option)) == option

    def test_a_missing_value_becomes_null_instead_of_nan(self, client, paste):
        dataset_id = paste([{'city': 'Sanya', 'likes': None}, {'city': 'Haikou', 'likes': 4}], name='holes.csv')
        response = client.post(
            '/api/visualize/render',
            json={
                'dataset_id': dataset_id,
                'chart_type': 'bar',
                'x_field': 'city',
                'y_field': 'likes',
                'agg': 'mean',
            },
        )
        # A bare ``NaN`` token is valid for Python but fatal for JSON.parse.
        assert b'NaN' not in response.data
        # ``mean`` of an all-missing group is genuinely undefined, unlike a sum.
        assert response.get_json()['option']['series'][0]['data'] == [4.0, None]

    def test_counting_rows_needs_only_a_category_field(self, client, paste):
        dataset_id = paste(VIZ_RECORDS, name='count.csv')
        option = client.post(
            '/api/visualize/render',
            json={'dataset_id': dataset_id, 'chart_type': 'pie', 'x_field': 'city'},
        ).get_json()['option']
        assert option['series'][0]['type'] == 'pie'
        assert {entry['name'] for entry in option['series'][0]['data']} == {'Haikou', 'Sanya'}

    @pytest.mark.parametrize(
        ('spec', 'expected'),
        [
            ({'chart_type': 'treemap', 'x_field': 'city'}, 'Unsupported chart type: treemap'),
            ({'chart_type': 'bar'}, 'requires a category field (x)'),
            ({'chart_type': 'bar', 'x_field': 'nope'}, 'Field not found in the data: nope'),
            ({'chart_type': 'scatter', 'x_field': 'city'}, 'Scatter chart requires both x and y fields'),
        ],
    )
    def test_a_bad_chart_spec_is_a_readable_400(self, client, paste, spec, expected):
        dataset_id = paste(VIZ_RECORDS, name='bad-spec.csv')
        payload = {'dataset_id': dataset_id, **spec}
        response = client.post('/api/visualize/render', json=payload)
        assert response.status_code == 400
        assert expected in response.get_json()['error']

    def test_matplotlib_engine_returns_a_png_data_uri(self, client, paste):
        dataset_id = paste(VIZ_RECORDS, name='image.csv')
        body = client.post(
            '/api/visualize/render',
            json={
                'dataset_id': dataset_id,
                'engine': 'matplotlib',
                'chart_type': 'bar',
                'x_field': 'city',
                'y_field': 'likes',
                'title': 'likes by city',
            },
        ).get_json()
        assert body['ok'] is True
        assert body['engine'] == 'matplotlib'
        assert body['image'].startswith('data:image/png;base64,')
        assert len(body['image']) > 1000

    def test_a_failed_render_does_not_leave_its_figure_open(self, client, paste):
        """matplotlib holds every figure it opens until something closes it, so
        a chart that failed *after* creating one used to leak it — and the UI
        retries charts, so the leak grew with every click. The renderer now
        closes in a ``finally``, the error path included.
        """
        import matplotlib.pyplot as plt

        # A pie cannot be drawn over a negative sum, which is exactly the
        # failure that arrives after plt.subplots() has opened the figure.
        negative = [{'city': 'Sanya', 'likes': -5}, {'city': 'Haikou', 'likes': 7}]
        dataset_id = paste(negative, name='negative.csv')
        base = {'dataset_id': dataset_id, 'engine': 'matplotlib', 'x_field': 'city', 'y_field': 'likes'}
        open_before = set(plt.get_fignums())

        for _ in range(3):
            response = client.post('/api/visualize/render', json={**base, 'chart_type': 'pie'})
            assert response.status_code == 400, response.get_json()
            assert set(plt.get_fignums()) == open_before, 'a failed render leaked its figure'

        assert client.post('/api/visualize/render', json={**base, 'chart_type': 'bar'}).get_json()['ok'] is True
        assert set(plt.get_fignums()) == open_before, 'a successful render leaked its figure'


class TestExportSave:
    def test_csv_export_lands_in_the_isolated_export_dir(self, client, paste, data_root):
        dataset_id = paste(VIZ_RECORDS, name='export.csv')
        body = client.post(
            '/api/export/save',
            json={'dataset_id': dataset_id, 'filename': 'api-export', 'format': 'csv'},
        ).get_json()
        assert body['ok'] is True
        assert body['format'] == 'csv'
        assert body['rows'] == 3
        written = data_root / 'data' / 'exports' / 'api-export.csv'
        # The answer names the file it wrote, inside the isolated export dir.
        assert Path(body['path']) == written
        assert written.exists()
        text = written.read_text(encoding='utf-8-sig')
        assert text.splitlines()[0] == 'city,likes'
        assert len(text.strip().splitlines()) == 4

    def test_json_export_is_strict_json(self, client, paste, data_root):
        dataset_id = paste([{'city': 'Sanya', 'likes': None}], name='export-json.csv')
        body = client.post(
            '/api/export/save',
            json={'dataset_id': dataset_id, 'filename': 'api-export.json', 'format': 'json'},
        ).get_json()
        assert body['format'] == 'json'
        raw = (data_root / 'data' / 'exports' / 'api-export.json').read_text(encoding='utf-8')
        assert 'NaN' not in raw
        assert json.loads(raw) == [{'city': 'Sanya', 'likes': None}]

    def test_the_format_is_inferred_from_the_filename(self, client, paste, data_root):
        dataset_id = paste(VIZ_RECORDS, name='infer.csv')
        body = client.post('/api/export/save', json={'dataset_id': dataset_id, 'filename': 'inferred.txt'}).get_json()
        assert body['format'] == 'txt'
        assert (data_root / 'data' / 'exports' / 'inferred.txt').exists()

    def test_an_unsupported_format_is_a_400(self, client, paste):
        dataset_id = paste(VIZ_RECORDS, name='bad-format.csv')
        response = client.post('/api/export/save', json={'dataset_id': dataset_id, 'format': 'parquet'})
        assert response.status_code == 400
        assert 'Unsupported export format: parquet' in response.get_json()['error']

    def test_export_resolves_a_workflow_node_by_id(self, client, app_module):
        app_module.execution_state['results'] = {'node-4': [{'city': 'Sanya', 'likes': 1}]}
        body = client.post('/api/export/save', json={'node_id': 'node-4', 'filename': 'from-node', 'format': 'csv'})
        assert body.status_code == 200
        assert body.get_json()['rows'] == 1


class TestMlTraining:
    # Fitting the default pipeline used to die while *saving* it (the TF-IDF
    # hooks were unpicklable lambdas). They are module-level functions now, so
    # the full train → persist → report path is expected to work.
    def test_training_reports_what_it_fitted(self, client, paste, tmp_path, monkeypatch):
        """The fit is real scikit-learn, so only the model directory is moved
        out of the repository; no model server is contacted."""
        from analyzers import ml_base

        monkeypatch.setattr(ml_base, 'MODEL_DIR', str(tmp_path))
        dataset_id = paste(_labeled_records(), name='labeled.csv')
        body = client.post(
            '/api/analysis/train',
            json={'dataset_id': dataset_id, 'model_type': 'emotion', 'text_column': 'text', 'label_column': 'label'},
        ).get_json()
        assert body == {
            'ok': True,
            'model_type': 'emotion',
            'trained_on': 12,
            'labels': ['neg', 'pos'],
            'label_count': 2,
        }
        assert (tmp_path / 'emotion.pkl').exists()

    @pytest.mark.parametrize(
        ('text_column', 'label_column'),
        [('missing_text', 'label'), ('text', 'missing_label')],
    )
    def test_a_column_that_is_not_there_is_named_in_the_error(self, client, paste, text_column, label_column):
        dataset_id = paste(_labeled_records(), name='columns.csv')
        response = client.post(
            '/api/analysis/train',
            json={'dataset_id': dataset_id, 'text_column': text_column, 'label_column': label_column},
        )
        assert response.status_code == 400
        missing = text_column if text_column.startswith('missing') else label_column
        assert f'No such column in the data: {missing}' in response.get_json()['error']

    def test_too_few_labelled_rows_says_how_many_it_needs(self, client, paste):
        dataset_id = paste(_labeled_records(4), name='thin.csv')
        response = client.post(
            '/api/analysis/train',
            json={'dataset_id': dataset_id, 'text_column': 'text', 'label_column': 'label'},
        )
        assert response.status_code == 400
        assert 'At least 10 labelled rows' in response.get_json()['error']

    def test_one_class_only_is_reported_as_a_data_problem(self, client, paste, tmp_path, monkeypatch):
        from analyzers import ml_base

        monkeypatch.setattr(ml_base, 'MODEL_DIR', str(tmp_path))
        records = [{'text': f'text number {i}', 'label': 'pos'} for i in range(12)]
        dataset_id = paste(records, name='one-class.csv')
        response = client.post(
            '/api/analysis/train',
            json={'dataset_id': dataset_id, 'text_column': 'text', 'label_column': 'label'},
        )
        assert response.status_code == 400
        assert 'pos' in response.get_json()['error']
