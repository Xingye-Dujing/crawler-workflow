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

The second half of this module is the parameter boundary the 分析 node stands on:
``_normalize_analysis_params`` turns the settings panel's flat strings into the
kwargs ``DataAnalysisService`` accepts. It is the only such bridge, it is called
from exactly one place, and the ``steps`` pipeline never crosses it — so every
one of its fourteen branches, and every field name the browser is allowed to
write, is pinned here.
"""

import json
import re
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

    # The five chart types below had never been answered by a test. Each one has
    # its own required-field rule and its own series shape, so "the panel offers
    # it" and "it renders" were separate claims until now.
    RICH_RECORDS = [
        {'city': '三亚', 'district': '海棠区', 'likes': 10, 'text': '三亚的海滩很美'},
        {'city': '三亚', 'district': '天涯区', 'likes': 4, 'text': '海风和阳光都不错'},
        {'city': '海口', 'district': '海棠区', 'likes': 7, 'text': '骑楼老街值得逛'},
        {'city': '海口', 'district': '龙华区', 'likes': 2, 'text': '海口早茶很好吃'},
    ]

    @pytest.mark.parametrize(
        'spec, series_type',
        [
            ({'chart_type': 'box', 'x_field': 'city', 'y_field': 'likes'}, 'boxplot'),
            (
                {'chart_type': 'heatmap', 'x_field': 'city', 'y_field': 'district', 'value_field': 'likes'},
                'heatmap',
            ),
            (
                {'chart_type': 'sankey', 'x_field': 'city', 'y_field': 'district', 'value_field': 'likes'},
                'sankey',
            ),
            ({'chart_type': 'map', 'x_field': 'city', 'value_field': 'likes'}, 'map'),
            ({'chart_type': 'wordcloud', 'x_field': 'city', 'value_field': 'likes'}, 'wordCloud'),
        ],
    )
    def test_each_chart_type_builds_its_own_series(self, client, paste, spec, series_type):
        dataset_id = paste(self.RICH_RECORDS, name='rich.csv')
        body = client.post('/api/visualize/render', json={'dataset_id': dataset_id, **spec}).get_json()
        assert body['ok'] is True, body
        assert body['option']['series'][0]['type'] == series_type

    def test_a_word_cloud_can_segment_the_text_instead_of_counting_labels(self, client, paste):
        dataset_id = paste(self.RICH_RECORDS, name='rich.csv')
        plain = client.post(
            '/api/visualize/render',
            json={'dataset_id': dataset_id, 'chart_type': 'wordcloud', 'x_field': 'city', 'value_field': 'likes'},
        ).get_json()
        segmented = client.post(
            '/api/visualize/render',
            json={'dataset_id': dataset_id, 'chart_type': 'wordcloud', 'x_field': 'text', 'tokenize': True},
        ).get_json()
        assert plain['ok'] is True and segmented['ok'] is True
        # Without jieba the vocabulary is the four city labels; with it, words
        # that exist only inside the sentences appear.
        assert {entry['name'] for entry in plain['option']['series'][0]['data']} == {'三亚', '海口'}
        names = {entry['name'] for entry in segmented['option']['series'][0]['data']}
        assert '海滩' in names or '骑楼' in names, names

    def test_wordcloud_style_only_changes_the_text_style(self, client, paste):
        dataset_id = paste(self.RICH_RECORDS, name='rich.csv')
        base = {'dataset_id': dataset_id, 'chart_type': 'wordcloud', 'x_field': 'text', 'tokenize': True}
        vibrant = client.post('/api/visualize/render', json={**base, 'wordcloud_style': 'vibrant'}).get_json()
        assert vibrant['ok'] is True
        # An unknown style name must not lose the chart: it falls back.
        fallback = client.post('/api/visualize/render', json={**base, 'wordcloud_style': 'not-a-style'}).get_json()
        assert fallback['ok'] is True
        assert len(fallback['option']['series'][0]['data']) == len(vibrant['option']['series'][0]['data'])

    def test_a_heatmap_aggregates_the_value_field_per_cell(self, client, paste):
        dataset_id = paste(self.RICH_RECORDS, name='rich.csv')
        body = client.post(
            '/api/visualize/render',
            json={
                'dataset_id': dataset_id,
                'chart_type': 'heatmap',
                'x_field': 'city',
                'y_field': 'district',
                'value_field': 'likes',
                'agg': 'sum',
            },
        ).get_json()
        assert body['ok'] is True
        option = body['option']
        assert option['xAxis']['data'] == ['三亚', '海口']
        # An empty combination is stored as 0, not as a hole, so the colour scale
        # spans 0..the real maximum.
        cells = {tuple(entry[:2]): entry[2] for entry in option['series'][0]['data']}
        assert [option['visualMap']['min'], option['visualMap']['max']] == [0, 10]
        assert 10 in cells.values(), cells
        assert 0 in cells.values(), 'city x district pairs with no row still get a cell'

    def test_a_map_needs_only_a_region_column(self, client, paste):
        dataset_id = paste(self.RICH_RECORDS, name='rich.csv')
        body = client.post(
            '/api/visualize/render',
            json={'dataset_id': dataset_id, 'chart_type': 'map', 'x_field': 'city', 'value_field': 'likes'},
        ).get_json()
        assert body['ok'] is True
        assert {entry['name'] for entry in body['option']['series'][0]['data']} == {'三亚', '海口'}

    def test_unrenderable_specs_for_the_new_types_are_readable_400s(self, client, paste):
        dataset_id = paste(self.RICH_RECORDS, name='rich.csv')
        cases = {
            'box': 'Box plot requires',
            'heatmap': 'Heatmap requires two category fields',
            'sankey': 'Sankey diagram requires',
            'map': 'Map chart requires',
            'wordcloud': 'Word cloud requires',
        }
        for chart_type, expected in cases.items():
            response = client.post('/api/visualize/render', json={'dataset_id': dataset_id, 'chart_type': chart_type})
            assert response.status_code == 400, (chart_type, response.get_json())
            assert expected in response.get_json()['error'], (chart_type, response.get_json())


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


class TestPanelParamsReachTheOperator:
    """The Settings panel stores flat strings; the normalizer is the only bridge
    to the operator's kwargs, and three of its fields used to fall off the edge
    of that bridge. A dropped parameter is not a missing feature — it is the
    operator silently doing the OTHER thing while the panel shows a choice.
    """

    @staticmethod
    def _normalize(op, **params):
        import app as app_module

        return app_module._normalize_analysis_params(op, params)

    def test_drop_null_how_survives(self):
        assert self._normalize('drop_null', columns='a, b', how='all') == {'columns': ['a', 'b'], 'how': 'all'}
        # An unset how stays the documented default instead of vanishing.
        assert self._normalize('drop_null', columns='a')['how'] == 'any'

    def test_fill_null_method_survives_and_blank_means_use_the_value(self):
        filled = self._normalize('fill_null', columns='a', value='0', method='ffill')
        assert filled == {'columns': ['a'], 'value': '0', 'method': 'ffill'}
        assert 'method' not in self._normalize('fill_null', columns='a', value='0', method='  ')

    def test_bins_is_a_count_or_a_list_of_edges(self):
        counted = self._normalize('bin_column', column='score', bins='4')
        assert counted['bins'] == 4 and 'labels' not in counted
        edged = self._normalize('bin_column', column='score', bins='0, 60, 80, 100', bin_labels='低, 中, 高')
        assert edged['bins'] == [0.0, 60.0, 80.0, 100.0]
        assert edged['labels'] == ['低', '中', '高'] and edged['new_col'] == ''

    def test_edges_with_junk_keep_the_numbers(self):
        assert self._normalize('bin_column', column='s', bins='0, oops, 60')['bins'] == [0.0, 60.0]

    def test_the_wired_params_actually_change_the_output(self):
        """Normalizing into a kwarg nobody consumes would pass every test above,
        so the effect is checked end to end through the real pipeline."""
        import pandas as pd

        from services.data_analysis import DataAnalysisService

        rows = [{'a': 1, 'b': None}, {'a': None, 'b': 2}, {'a': 3, 'b': 4}]

        def _drop(how):
            params = self._normalize('drop_null', columns='a, b', how=how)
            return DataAnalysisService.run_pipeline(pd.DataFrame(rows), [{'op': 'drop_null', 'params': params}])[0]

        any_null, all_null = _drop('any'), _drop('all')
        assert len(any_null) == 1 and len(all_null) == 3, 'how must decide whether one or every cell drops the row'

        scored = pd.DataFrame([{'score': value} for value in (10, 55, 70, 95)])
        binned = DataAnalysisService.run_pipeline(
            scored,
            [
                {
                    'op': 'bin_column',
                    'params': dict(
                        self._normalize('bin_column', column='score', bins='0, 60, 100', bin_labels='低, 高'),
                        new_col='档',
                    ),
                }
            ],
        )[0]
        # run_pipeline hands back a DataFrame, and iterating one yields column
        # names — the values have to be read out of the column.
        assert [str(value) for value in binned['档']] == ['低', '低', '高', '高']


# ─── parameter normalization ───────────────────────────────────────────

# One realistic panel payload per operation, and the exact kwargs the operator
# must receive for it. The browser stores every field as a flat string (a
# comma-separated list, '' for "left empty"), so this table *is* the boundary
# between the 分析 node's settings form and ``DataAnalysisService``.
#
# The op names are keys, never a list: the cases are parametrized over the
# Python registry, so an operator added to the service shows up here as a
# KeyError instead of an untested branch.
NORMALIZED = {
    'drop_null': (
        {'columns': '名称, 城市', 'how': 'all'},
        {'columns': ['名称', '城市'], 'how': 'all'},
    ),
    'fill_null': (
        {'columns': '名称', 'value': '未知', 'method': 'ffill'},
        {'columns': ['名称'], 'value': '未知', 'method': 'ffill'},
    ),
    'drop_duplicates': ({'columns': '名称'}, {'columns': ['名称']}),
    'filter_rows': (
        {'column': '城市', 'op': 'not_in', 'value': '北京, 上海'},
        {'column': '城市', 'op': 'not_in', 'value': '北京, 上海'},
    ),
    'select_columns': ({'columns': '名称,城市'}, {'columns': ['名称', '城市']}),
    'rename_columns': ({'rename_from': '名称', 'rename_to': '标题'}, {'mapping': {'名称': '标题'}}),
    'strip_whitespace': ({'columns': ' 名称 , 城市'}, {'columns': ['名称', '城市']}),
    'convert_type': ({'column': '序号', 'dtype': 'int'}, {'column': '序号', 'dtype': 'int'}),
    'sort_rows': ({'column': '序号', 'ascending': 'false'}, {'column': '序号', 'ascending': False}),
    'sample_rows': ({'n': '3', 'frac': '', 'seed': '7'}, {'n': 3, 'frac': None, 'seed': 7}),
    'groupby_agg': (
        {'group_col': '城市', 'agg_col': '序号', 'agg_func': 'mean'},
        {'group_col': '城市', 'agg_col': '序号', 'agg_func': 'mean'},
    ),
    'join_tables': (
        {'join_how': 'inner', 'left_on': '城市', 'right_on': '城市'},
        {'how': 'inner', 'left_on': '城市', 'right_on': '城市'},
    ),
    'column_calc': ({'new_col': '两倍', 'expr': '序号 * 2'}, {'new_col': '两倍', 'expr': '序号 * 2'}),
    'bin_column': (
        {'column': '序号', 'bins': '0, 40, 80', 'bin_labels': '低, 中, 高', 'bin_new_col': '档'},
        {'column': '序号', 'new_col': '档', 'bins': [0.0, 40.0, 80.0], 'labels': ['低', '中', '高']},
    ),
}

# What a step with an empty form answers with — the state of a node the user
# dragged onto the canvas and never configured.
BLANK_FORM = {
    'drop_null': {'columns': [], 'how': 'any'},
    'fill_null': {'columns': [], 'value': None},
    'drop_duplicates': {'columns': None},
    'filter_rows': {'column': '', 'op': 'eq', 'value': None},
    'select_columns': {'columns': []},
    'rename_columns': {'mapping': {}},
    'strip_whitespace': {'columns': []},
    'convert_type': {'column': '', 'dtype': 'str'},
    'sort_rows': {'column': '', 'ascending': True},
    'sample_rows': {'n': None, 'frac': None},
    'groupby_agg': {'group_col': '', 'agg_col': '', 'agg_func': 'sum'},
    'join_tables': {'how': 'left', 'left_on': '', 'right_on': ''},
    'column_calc': {'new_col': '', 'expr': ''},
    'bin_column': {'column': '', 'new_col': ''},
}

# The values this repository uses for "the user typed nothing sensible".
JUNK = ['', '   ', 'abc', 1e400, -5, 999999, None, [], ['a', ' b ', ''], {'k': 1}, True, 0]

CLEAN_TABLE = [
    {'名称': '甲', '序号': 3, '城市': '北京'},
    {'名称': '乙', '序号': 5, '城市': '上海'},
    {'名称': '丙', '序号': 1, '城市': '广州'},
    {'名称': '丁', '序号': 4, '城市': '北京'},
]


def _normalize(app_module, op: str, params: dict) -> dict:
    return app_module._normalize_analysis_params(op, params)


def _registry() -> list:
    from services.data_analysis import DataAnalysisService

    return sorted(DataAnalysisService._operations())


# ─── what the browser's settings panel actually writes ─────────────────
#
# The panel is generated by ``renderAnalysisSettings`` in workflow.js: one block
# per operation, each block writing its fields back with ``updateParam`` or
# ``renderParamInput/Select/Checkbox``. Reading those field names out of the file
# is what lets the contract below be checked in both directions — and it is why
# no test here needs its own list of operation names.

WORKFLOW_JS = Path(__file__).resolve().parents[2] / 'backend' / 'static' / 'js' / 'workflow.js'
_PANEL_FUNCTION = 'renderAnalysisSettings'
_OP_CONDITION = re.compile(r"if \(op === '([a-z_]+)'\) \{|if \((\[[^\]]*\])\.indexOf\(op\) >= 0\) \{")
_PANEL_CALL = re.compile(r'(updateParam|renderParam\w*)\s*\(')


def _call_arguments(text: str, open_index: int) -> list:
    """The top-level arguments of the call whose ``(`` sits at ``open_index``."""
    depth = 0
    quote = None
    current = []
    arguments = []
    for position in range(open_index + 1, len(text)):
        char = text[position]
        if quote:
            if char == quote:
                quote = None
            current.append(char)
        elif char in '\'"':
            quote = char
            current.append(char)
        elif char in '([':
            depth += 1
            current.append(char)
        elif char in ')]':
            if depth == 0:
                arguments.append(''.join(current).strip())
                return arguments
            depth -= 1
            current.append(char)
        elif char == ',' and depth == 0:
            arguments.append(''.join(current).strip())
            current = []
        else:
            current.append(char)
    raise AssertionError('unbalanced call in workflow.js')


def _panel_blocks() -> list:
    """``[(ops, [field, …]), …]`` for every block of the analysis settings panel.

    ``ops`` is ``None`` for the part that renders whatever the operation is — the
    步骤 dropdown itself.
    """
    text = WORKFLOW_JS.read_text(encoding='utf-8')
    header = f'function {_PANEL_FUNCTION}(nodeId, p) {{'
    start = text.index(header)
    opening = text.index('{', start)
    depth = 0
    for position in range(opening, len(text)):
        if text[position] == '{':
            depth += 1
        elif text[position] == '}':
            depth -= 1
            if depth == 0:
                body = text[opening + 1 : position]
                break
    else:
        raise AssertionError('the analysis settings panel is unbalanced')
    # Inline handlers escape their quotes for the attribute; drop the escapes so
    # the field names read as ordinary string literals.
    body = body.replace("\\'", "'")
    conditions = list(_OP_CONDITION.finditer(body))
    blocks = [(None, body[: conditions[0].start()])]
    for index, match in enumerate(conditions):
        stop = conditions[index + 1].start() if index + 1 < len(conditions) else len(body)
        ops = [match.group(1)] if match.group(1) else re.findall(r"'([^']*)'", match.group(2))
        blocks.append((ops, body[match.end() : stop]))
    out = []
    for ops, chunk in blocks:
        fields = []
        for call in _PANEL_CALL.finditer(chunk):
            arguments = _call_arguments(chunk, call.end() - 1)
            # updateParam(nodeId, field, …) / renderParamX(nodeId, p, field, …)
            slot = 1 if call.group(1) == 'updateParam' else 2
            if len(arguments) > slot:
                field = re.fullmatch(r"'([A-Za-z_]\w*)'", arguments[slot])
                if field:
                    fields.append(field.group(1))
        out.append((ops, fields))
    return out


def _panel_fields(op: str) -> set:
    """Every field written for ``op`` — an operation can appear in more than one
    block (``drop_null`` shares the 列 field with four others and then adds its own
    ``how``), so the blocks are unioned rather than searched for a first hit.
    """
    fields = set()
    for ops, written in _panel_blocks():
        if ops and op in ops:
            fields.update(written)
    return fields


def _ops_writing(field: str) -> list:
    """Every registered operation whose panel block writes ``field``."""
    return sorted(op for op in _registry() if field in _panel_fields(op))


class TestNormalizedKwargs:
    """All fourteen branches, including the ten that had never been asserted.

    A dropped key here is not a missing feature: the operator keeps its own
    default, so the panel still shows the choice the crawl never received. That
    is how ``how`` turned every 任一为空 crawl into 全部为空.
    """

    def test_the_table_covers_every_registered_operation(self):
        assert set(NORMALIZED) == set(_registry()) == set(BLANK_FORM)

    @pytest.mark.parametrize('op', sorted(NORMALIZED))
    def test_the_panel_payload_becomes_exactly_these_kwargs(self, app_module, op):
        params, expected = NORMALIZED[op]
        assert _normalize(app_module, op, params) == expected

    @pytest.mark.parametrize('op', sorted(BLANK_FORM))
    def test_an_untouched_form_becomes_exactly_these_kwargs(self, app_module, op):
        assert _normalize(app_module, op, {}) == BLANK_FORM[op]

    @pytest.mark.parametrize(
        ('op, cleared'),
        [
            ('convert_type', {'column': '', 'dtype': ''}),
            ('fill_null', {'columns': [], 'value': ''}),
            ('filter_rows', {'column': '', 'op': '', 'value': ''}),
            ('groupby_agg', {'group_col': '', 'agg_col': '', 'agg_func': ''}),
            ('join_tables', {'how': '', 'left_on': '', 'right_on': ''}),
            ('sort_rows', {'column': '', 'ascending': False}),
        ],
    )
    def test_a_cleared_field_is_not_an_absent_one_for_six_fields(self, app_module, op, cleared):
        """CURRENT behaviour, pinned on purpose. Six fields are read with
        ``params.get(key, DEFAULT)``, which only fires when the key is *missing*;
        the panel writes ``''`` as soon as the user deletes what was in the box, so
        a cleared ``ascending`` sorts descending, a cleared ``op`` is refused by
        name and a cleared ``value`` fills with the empty string. The fields that
        go through ``or`` instead (``how``, ``method``, ``n``, ``frac``, ``seed``,
        ``bins``, ``bin_labels``) read the two states the same way — that
        inconsistency is what a workflow file has to guess about.
        """
        blank = BLANK_FORM[op]
        cleared_form = {
            'value': '',
            'op': '',
            'dtype': '',
            'ascending': '',
            'agg_func': '',
            'join_how': '',
            'method': '',
        }
        assert _normalize(app_module, op, cleared_form) == cleared
        assert cleared != blank, f'{op} does not distinguish a cleared field from an absent one'

    def test_a_cleared_number_is_not_a_zero_row_count(self, app_module):
        """The contrast that makes the six above survivable: the numeric fields all
        read a blank as "not configured", so clearing 行数 keeps every row — typing
        ``0`` into it is the only way to ask for none.
        """
        assert _normalize(app_module, 'sample_rows', {'n': '', 'frac': '', 'seed': ''}) == {
            'n': None,
            'frac': None,
        }
        assert _normalize(app_module, 'sample_rows', {'n': '0'})['n'] == 0
        # An int 0 is falsy, so it is read as "the field was never written".
        assert _normalize(app_module, 'sample_rows', {'n': 0})['n'] is None

    def test_an_unknown_operation_gets_no_kwargs_and_is_refused_by_name(self, app_module, client, paste):
        """``return {}`` is the normalizer's last line, so a mistyped op arrives at
        the pipeline with nothing attached — which is only safe because the
        pipeline refuses the *name* rather than defaulting to some operator.
        """
        assert _normalize(app_module, 'drop_rows', {'columns': 'a'}) == {}
        dataset_id = paste(CLEAN_TABLE, name='unknown-step.csv')
        response = client.post(
            '/api/analysis/run',
            json={'dataset_id': dataset_id, 'steps': [{'op': 'drop_rows', 'params': {}}]},
        )
        assert response.status_code == 400
        assert 'Unknown analysis operation: drop_rows' in response.get_json()['error']

    @pytest.mark.parametrize('op', [op for op in sorted(BLANK_FORM) if op != 'join_tables'])
    def test_an_untouched_form_never_destroys_a_row(self, app_module, op):
        """The safety half of the defaults: an unconfigured step may be a no-op,
        it may not be a filter. ``join_tables`` is excluded because the node
        executor — not the normalizer — is the only caller that can supply its
        right-hand table.
        """
        import pandas as pd

        from services.data_analysis import DataAnalysisService

        frame = pd.DataFrame(CLEAN_TABLE)
        result, report = DataAnalysisService.run_pipeline(frame, [{'op': op, 'params': _normalize(app_module, op, {})}])
        assert len(result) == len(frame), f'{op} dropped rows it was never asked to drop'
        assert report[0]['rows_removed'] == 0

    def test_join_tables_alone_cannot_be_completed_and_answers_400(self, app_module, client, paste):
        """The normalizer's join kwargs are deliberately incomplete; the missing
        ``other_df`` is a caller error with a reason, never a 500 traceback.
        """
        dataset_id = paste(CLEAN_TABLE, name='half-a-join.csv')
        steps = [{'op': 'join_tables', 'params': _normalize(app_module, 'join_tables', {})}]
        response = client.post('/api/analysis/run', json={'dataset_id': dataset_id, 'steps': steps})
        assert response.status_code == 400
        assert 'other_df' in response.get_json()['error']


class TestJunkInTheStringFields:
    """The list-and-text fields, fed everything this repo calls junk.

    ``columns`` is the one field with a parser (a comma-separated form value or a
    real JSON list), and its contract is: always a list of non-empty stripped
    names, whatever arrives. What it cannot promise is that those names exist —
    see :meth:`test_a_name_that_is_not_a_column_widens_the_step_instead_of_narrowing_it`.
    """

    @pytest.mark.parametrize('junk', JUNK)
    @pytest.mark.parametrize('op', [op for op in _ops_writing('columns') if op != 'drop_duplicates'])
    def test_columns_is_always_a_list_of_stripped_names(self, app_module, op, junk):
        out = _normalize(app_module, op, {'columns': junk})
        assert isinstance(out['columns'], list)
        assert all(isinstance(name, str) and name == name.strip() and name for name in out['columns'])

    @pytest.mark.parametrize('junk', JUNK)
    def test_an_empty_selection_for_drop_duplicates_is_sent_as_no_subset(self, app_module, junk):
        """The one list field that does not arrive as a list: ``columns or None``,
        because pandas reads ``subset=None`` as "the whole row" — which is what an
        empty box means, and what an empty list would not.
        """
        names = _normalize(app_module, 'select_columns', {'columns': junk})['columns']
        assert _normalize(app_module, 'drop_duplicates', {'columns': junk})['columns'] == (names or None)

    @pytest.mark.parametrize(
        ('junk, expected'),
        [
            ('', []),
            ('   ', []),
            ('abc', ['abc']),
            ('a, b', ['a', 'b']),
            ('a ,, b ', ['a', 'b']),
            (None, []),
            ([], []),
            (['a', ' b ', ''], ['a', 'b']),
            (0, []),
            (False, []),
            (True, ['True']),
            (-5, ['-5']),
            (1e400, ['inf']),
            (123, ['123']),
            ({'k': 1}, ["{'k': 1}"]),
        ],
    )
    def test_the_measured_reading_of_the_columns_field(self, app_module, junk, expected):
        """A number or a boolean is *stringified into a column name* — the reason
        ``False``/``0`` answer ``[]`` (they are falsy, so "blank") while ``True``
        asks for a column called ``True``. Pinned as-is: a caller that sends a
        non-string should be refused, not reinterpreted.
        """
        assert _normalize(app_module, 'select_columns', {'columns': junk}) == {'columns': expected}

    def test_a_name_that_is_not_a_column_widens_the_step_instead_of_narrowing_it(self, client, paste):
        """A typo in 列名 is the opposite of a filter: the service drops names it
        cannot find, an empty selection means "no subset", and 任一为空 then reads
        *every* column — so the crawl loses more rows than the one it named.
        """
        records = [{'a': 1, 'b': None}, {'a': 2, 'b': 3}]
        dataset_id = paste(records, name='typo.csv')
        named = client.post(
            '/api/analysis/run',
            json={'dataset_id': dataset_id, 'steps': [{'op': 'drop_null', 'params': {'columns': ['a']}}]},
        ).get_json()
        typo = client.post(
            '/api/analysis/run',
            json={'dataset_id': dataset_id, 'steps': [{'op': 'drop_null', 'params': {'columns': ['nope']}}]},
        ).get_json()
        assert named['row_count'] == 2
        assert typo['row_count'] == 1, 'a mistyped column made every column count'

    @pytest.mark.parametrize('junk', ['', '   ', 'abc', None, [], {}, 0, True, 1e400])
    def test_the_pass_through_fields_arrive_untouched(self, app_module, junk):
        """``column`` / ``value`` / ``dtype`` / ``expr`` … have no parser at all, so
        junk is forwarded to pandas verbatim. That is why the operators own the
        "column is not there" answer, not the normalizer.
        """
        out = _normalize(app_module, 'filter_rows', {'column': junk, 'op': junk, 'value': junk})
        assert out == {'column': junk, 'op': junk, 'value': junk}
        assert _normalize(app_module, 'convert_type', {'column': junk, 'dtype': junk}) == {
            'column': junk,
            'dtype': junk,
        }

    @pytest.mark.parametrize('junk', ['', '   ', 'abc', None, [], {}, True, 0, 1e400])
    def test_the_defaults_only_apply_to_a_missing_key_not_to_an_empty_one(self, app_module, junk):
        """``params.get('op', 'eq')`` answers ``None`` for a key the browser wrote as
        null, so the fallback to ``eq`` protects a caller that omitted the field
        and not one that cleared it. The operator then refuses the name, which is
        the loud half of this contract.
        """
        out = _normalize(app_module, 'filter_rows', {'column': 'a', 'op': junk})
        assert out['op'] == junk
        out = _normalize(app_module, 'convert_type', {'column': 'a', 'dtype': junk})
        assert out['dtype'] == junk
        # Only an absent key takes the documented default.
        assert _normalize(app_module, 'filter_rows', {'column': 'a'})['op'] == 'eq'
        assert _normalize(app_module, 'convert_type', {'column': 'a'})['dtype'] == 'str'


class TestJunkInTheNumberFields:
    """Numbers arrive as text and must never become a crash or a silent zero.

    ``_optional_int`` / ``_optional_float`` treat blank, unparseable, ``inf`` and
    ``nan`` as "not configured", which is what keeps ``df.sample`` from raising
    and a cleared 行数 from meaning "keep nothing".
    """

    @pytest.mark.parametrize(
        ('raw, expected'),
        [
            ('', None),
            ('   ', None),
            ('abc', None),
            ('1e400', None),
            ('inf', None),
            ('nan', None),
            (None, None),
            ([], None),
            ({}, None),
            (True, None),
            (False, None),
            # The panel can only send text, and ``'0'`` is a real answer there:
            # zero rows. The *number* 0 is falsy and reads as "left empty".
            (0, None),
            ('0', 0),
            ('2.7', 2),
            (-5, -5),
            ('-5', -5),
            ('999999', 999999),
        ],
    )
    def test_the_row_count_is_a_number_or_nothing_at_all(self, app_module, raw, expected):
        out = _normalize(app_module, 'sample_rows', {'n': raw})
        assert out['n'] == expected
        assert out['frac'] is None

    @pytest.mark.parametrize(
        ('raw, expected'),
        [
            ('0.5', 0.5),
            ('2', 2.0),
            ('-1', -1.0),
            ('', None),
            ('abc', None),
            ('1e400', None),
            (None, None),
            (0, None),
            ('0', 0.0),
            (True, None),
            (['a'], None),
        ],
    )
    def test_the_fraction_is_a_number_or_nothing_at_all(self, app_module, raw, expected):
        assert _normalize(app_module, 'sample_rows', {'frac': raw})['frac'] == expected

    def test_a_cleared_number_is_not_a_request_to_empty_the_table(self, app_module, client, paste):
        """``n=''`` normalizes to None, which the service reads as "no bound", so
        the four rows survive. A default of ``0`` here would have emptied every
        form the user opened and never filled.
        """
        dataset_id = paste(CLEAN_TABLE, name='blank-n.csv')
        steps = [{'op': 'sample_rows', 'params': _normalize(app_module, 'sample_rows', {'n': '', 'frac': ''})}]
        body = client.post('/api/analysis/run', json={'dataset_id': dataset_id, 'steps': steps}).get_json()
        assert body['row_count'] == len(CLEAN_TABLE)

    def test_a_negative_row_count_empties_the_table_today(self, app_module, client, paste):
        """CURRENT behaviour, pinned on purpose: nothing clamps 行数 into
        ``_optional_int`` (unlike ``_safe_int``, which takes a minimum), so ``-12``
        reaches ``df.sample`` and answers zero rows — a typo that silently throws
        away the whole crawl instead of refusing it.
        """
        dataset_id = paste(CLEAN_TABLE, name='negative-n.csv')
        params = _normalize(app_module, 'sample_rows', {'n': '-12'})
        assert params['n'] == -12
        body = client.post(
            '/api/analysis/run', json={'dataset_id': dataset_id, 'steps': [{'op': 'sample_rows', 'params': params}]}
        ).get_json()
        assert body['row_count'] == 0

    @pytest.mark.parametrize(
        ('raw, expected'),
        [
            ('4', 4),
            ('1', 1),
            ('0', 'omitted'),
            ('-5', -5),
            ('999999', 999999),
            ('abc', 'omitted'),
            ('', 'omitted'),
            ('   ', 'omitted'),
            ('1e400', 'omitted'),
            ('0, 40, 80', [0.0, 40.0, 80.0]),
            ('0,abc,80', [0.0, 80.0]),
            ('2,2', [2.0, 2.0]),
            ('4,,', 'omitted'),
            (None, 'omitted'),
            ([], 'omitted'),
            (['0', '40'], [0.0, 40.0]),
        ],
    )
    def test_bins_is_a_bucket_count_or_a_list_of_edges(self, app_module, raw, expected):
        """``bins`` is overloaded the way pandas overloads it, and one spelling has
        no answer that does not surprise: ``0``, a blank and an unparseable value
        all *omit* the key, which the service reads as "four buckets" — so a user
        who types 0 gets buckets, not an error.
        """
        out = _normalize(app_module, 'bin_column', {'column': '序号', 'bins': raw})
        if expected == 'omitted':
            assert 'bins' not in out, out
        else:
            assert out['bins'] == expected

    def test_labels_and_edges_are_parsed_independently(self, app_module):
        out = _normalize(app_module, 'bin_column', {'column': 'a', 'bins': '0,1', 'bin_labels': 'lo,,hi'})
        assert out['bins'] == [0.0, 1.0] and out['labels'] == ['lo', 'hi']
        # A label list with nothing in it is not a label list: pandas would then
        # refuse a bucket count that has no matching number of names.
        assert 'labels' not in _normalize(app_module, 'bin_column', {'column': 'a', 'bins': '4', 'bin_labels': ','})


# ─── the twelve filter comparisons, as a node would send them ──────────

# The fields the normalizer transforms; every other field it forwards verbatim.
PARSED_FIELDS = {
    'columns',
    'n',
    'frac',
    'seed',
    'bins',
    'bin_labels',
    'method',
    'how',
    'ascending',
    'rename_from',
    'rename_to',
}


class TestJunkAcrossEveryField:
    """The whole field vocabulary of the panel, fed the whole junk vocabulary.

    The normalizer runs inside a request handler and inside a node executor, so a
    ``TypeError`` raised here is an HTTP 500 or an opaque node failure — the two
    outcomes this repo keeps converting into a named refusal. Nothing it does to
    a value may depend on the value's type.
    """

    @pytest.mark.parametrize('op', [op for op in sorted(_registry()) if op != 'rename_columns'])
    def test_no_field_and_no_value_can_make_the_normalizer_raise(self, app_module, op):
        """Thirteen of the fourteen branches judge nothing on the way: any value
        the panel can write, however wrong, comes out as kwargs.
        ``rename_columns`` is the exception and is pinned by its own test below,
        because it uses an incoming value as a dict key and can raise.
        """
        fields = sorted(_panel_fields(op))
        assert fields, op
        for field in fields:
            for junk in JUNK:
                payload = {key: PANEL_VALUE[key] for key in fields}
                payload[field] = junk
                assert isinstance(_normalize(app_module, op, payload), dict), (op, field, junk)

    @pytest.mark.parametrize('op', sorted(_registry()))
    def test_a_word_field_reaches_the_operator_untouched(self, app_module, op):
        """A word field is the operator's business, not the normalizer's: the
        service owns "this column does not exist" and "this operator name is not a
        name", and it can only do that if the value arrives as written.
        """
        for field in sorted(_panel_fields(op) - PARSED_FIELDS):
            for junk in ['', 'abc', 999999, None, [], {'k': 1}, True]:
                payload = {key: PANEL_VALUE[key] for key in _panel_fields(op)}
                payload[field] = junk
                out = _normalize(app_module, op, payload)
                assert junk in out.values(), (op, field, out)


# ─── the twelve filter comparisons, as a node would send them ──────────

# A table with one real integer column, one text column whose values look like
# numbers, an empty cell, a None and a duplicate row.
FILTER_TABLE = [
    {'名称': '甲', '序号': 3, '城市': '北京'},
    {'名称': '乙', '序号': 5, '城市': ''},
    {'名称': '丙', '序号': 1, '城市': '上海'},
    {'名称': '丁', '序号': 4, '城市': '北京'},
    {'名称': '戊', '序号': None, '城市': '广州'},
]

FILTER_SWEEP = {
    # case name -> (column, op, value, rows left), measured on FILTER_TABLE
    'number_eq': ('序号', 'eq', '3', 0),
    'number_ne': ('序号', 'ne', '3', 5),
    'number_gt': ('序号', 'gt', '3', 2),
    'number_gte': ('序号', 'gte', '3', 3),
    'number_lt': ('序号', 'lt', '3', 1),
    'number_lte': ('序号', 'lte', '3', 2),
    'number_contains': ('序号', 'contains', '3', 1),
    'number_not_contains': ('序号', 'not_contains', '3', 4),
    'number_in': ('序号', 'in', '3, 5', 0),
    'number_not_in': ('序号', 'not_in', '3, 5', 5),
    'number_is_null': ('序号', 'is_null', '', 1),
    'number_not_null': ('序号', 'not_null', '', 4),
    'text_eq': ('城市', 'eq', '北京', 2),
    'text_ne': ('城市', 'ne', '北京', 3),
    'text_gt': ('城市', 'gt', '3', 0),
    'text_in': ('城市', 'in', '北京,上海', 3),
    'text_not_in': ('城市', 'not_in', '北京', 3),
    'text_contains': ('城市', 'contains', '京', 2),
    'text_not_contains': ('城市', 'not_contains', '京', 3),
    'text_is_null': ('城市', 'is_null', '', 1),
    'text_not_null': ('城市', 'not_null', '', 4),
    'row_eq': ('名称', 'eq', '丙', 1),
    'row_not_in': ('名称', 'not_in', '甲,乙,丙', 2),
}


def _step(op: str, params: dict) -> list:
    return [{'op': op, 'params': params}]


def _run_analysis_node(client, app_module, paste, operation, params, records=None, steps=None):
    """``upload → 分析 node``, answered with the rows the run stored for that node.

    A real run, because the boundary under test is the node's own: the panel's
    flat fields go into ``params``, the executor normalizes them, and what comes
    back is what a user sees in the preview. ``operation`` travels inside
    ``params`` exactly as ``updateParam`` writes it. ``steps=`` takes the other
    door — the node's step list, which no normalizer ever touches.
    """
    from run_wait import run_finished

    from services.data_analysis import DataAnalysisService

    body = records or FILTER_TABLE
    dataset_id = paste(body, name='analysis-node.csv')
    node_params = {'steps': steps} if steps is not None else {'operation': operation, **params}
    chain = [
        {
            'id': 'node-1',
            'type': 'upload',
            'title': 'upload',
            'params': {'dataset_id': dataset_id, 'row_count': len(body)},
        },
        {'id': 'node-target', 'type': 'analysis', 'title': 'analysis', 'params': node_params},
    ]
    connections = [{'from': 'node-1', 'to': 'node-target'}]
    started = client.post(
        '/api/workflow/execute',
        json={
            'workflow': {'nodes': chain, 'connections': connections, 'settings': {'mode': 'serial'}},
            'workflow_name': 'analysis-api',
        },
    )
    assert started.status_code == 200, started.get_json()
    assert run_finished(app_module), 'the run never settled'
    run_id = started.get_json()['run_id']
    status = app_module._RUN_STORE.node_statuses(run_id).get('node-target', {})
    assert status.get('status') == 'done', status.get('error') or status
    rows = app_module._RUN_STORE.load_rows(run_id, 'node-target')
    # The node ran the operation the registry knows, not a look-alike.
    assert operation == '' or operation in DataAnalysisService._operations()
    return rows


class TestFilterOperatorsThroughTheApi:
    """Every comparison name the panel offers, through the node's own kwargs.

    The service half is swept in ``tests/unit/test_data_analysis.py``; what this
    class owns is the whole path a 过滤 rows node takes — flat form fields in,
    normalization, ``run_pipeline``, HTTP answer out — including the four names
    (``not_in``, ``gt``, ``lt``, ``lte``) no node-level case had ever sent, and a
    column the table does not have.
    """

    @pytest.mark.parametrize('case', sorted(FILTER_SWEEP))
    def test_the_measured_row_count_for_each_comparison(self, app_module, client, paste, case):
        column, op, value, expected = FILTER_SWEEP[case]
        dataset_id = paste(FILTER_TABLE, name=f'filter-{case}.csv')
        params = _normalize(app_module, 'filter_rows', {'column': column, 'op': op, 'value': value})
        body = client.post(
            '/api/analysis/run', json={'dataset_id': dataset_id, 'steps': _step('filter_rows', params)}
        ).get_json()
        assert body['row_count'] == expected, (case, params, body['preview'])

    def test_a_column_that_is_not_in_the_table_keeps_every_row(self, app_module, client, paste):
        """Silently, for every one of the twelve names — the no-op is the service's
        answer, not the normalizer's, and it is why a rename earlier in a pipeline
        can turn a filter into a pass-through (the order half of that is pinned by
        ``TestPipelineOrder`` in ``tests/unit/test_data_analysis.py``).
        """
        dataset_id = paste(FILTER_TABLE, name='filter-ghost.csv')
        for op in sorted({row[1] for row in FILTER_SWEEP.values()}):
            params = _normalize(app_module, 'filter_rows', {'column': '不存在', 'op': op, 'value': 'x'})
            body = client.post(
                '/api/analysis/run', json={'dataset_id': dataset_id, 'steps': _step('filter_rows', params)}
            ).get_json()
            assert body['row_count'] == len(FILTER_TABLE), op

    @pytest.mark.parametrize('op', ['gt', 'gte', 'lt', 'lte'])
    @pytest.mark.parametrize('value', ['', '   ', 'abc', None, '3, 5'])
    def test_a_comparison_without_a_number_is_a_400_naming_the_bound(self, app_module, client, paste, op, value):
        """The value the user left blank is the same shape as the one they mistyped,
        and both refuse: ``float('')`` never reaches pandas, and the message quotes
        what arrived.
        """
        dataset_id = paste(FILTER_TABLE, name='filter-bound.csv')
        params = _normalize(app_module, 'filter_rows', {'column': '序号', 'op': op, 'value': value})
        body = {'dataset_id': dataset_id, 'steps': _step('filter_rows', params)}
        response = client.post('/api/analysis/run', json=body)
        assert response.status_code == 400
        message = response.get_json()['error']
        assert 'needs a numeric value' in message and repr(value) in message

    def test_an_operator_the_service_does_not_know_is_refused_by_name(self, app_module, client, paste):
        """The normalizer forwards an unrecognised name untouched (it owns no
        opinion), so the refusal has to come from the operator — for every one of
        the twelve names, each asked for with a suffix that makes it unknown. A
        fallback to ``eq`` here would answer a mistyped filter with "the data was
        already clean", which is the failure this repo refuses to print.
        """
        dataset_id = paste(FILTER_TABLE, name='filter-unknown.csv')
        for op in sorted({row[1] for row in FILTER_SWEEP.values()}):
            unknown = f'{op}_nope'
            params = _normalize(app_module, 'filter_rows', {'column': '城市', 'op': unknown, 'value': '北京'})
            response = client.post(
                '/api/analysis/run', json={'dataset_id': dataset_id, 'steps': _step('filter_rows', params)}
            )
            assert response.status_code == 400, (op, response.get_json())
            assert f'Unknown filter operator: {unknown}' in response.get_json()['error']


# ─── two traps read out of the source ──────────────────────────────────


@pytest.mark.serial
class TestAscendingIsTheStringTrue:
    """``params.get('ascending', 'true') == 'true'`` — the whole comparison.

    The browser's checkbox writes the strings ``'true'``/``'false'``, so the node
    works from the panel. But a workflow file, an API caller or any later
    serialization can carry a real JSON boolean, and ``True == 'true'`` is False:
    the direction the user chose is inverted, silently, and the run still settles
    done. The panel's own reader tolerates both spellings
    (``p[key] === true || p[key] === 'true'``), so the checkbox shows what the
    crawl did not do. Pinned as CURRENT behaviour; the fix is to read it with the
    service's own ``_to_bool``.
    """

    @pytest.mark.parametrize(
        ('sent, ascending'),
        [
            ('true', True),
            ('false', False),
            ('True', False),
            ('TRUE', False),
            (True, False),
            (False, False),
            ('', False),
            (None, False),
            ('abc', False),
            (1, False),
            (0, False),
            (['true'], False),
        ],
    )
    def test_only_the_exact_lowercase_word_means_ascending(self, app_module, sent, ascending):
        out = _normalize(app_module, 'sort_rows', {'column': '序号', 'ascending': sent})
        assert out['ascending'] is ascending
        # An absent field is the documented default, the only other way up.
        assert _normalize(app_module, 'sort_rows', {'column': '序号'})['ascending'] is True

    def test_a_boolean_true_sorts_the_table_down(self, client, app_module, paste):
        """End to end, from the workflow file a caller would write: the rows come
        back in the opposite order to the one the box claims.
        """
        rows = _run_analysis_node(client, app_module, paste, 'sort_rows', {'column': '序号', 'ascending': True})
        assert [row['序号'] for row in rows] == [5, 4, 3, 1, None]

    def test_the_word_true_sorts_it_up(self, client, app_module, paste):
        rows = _run_analysis_node(client, app_module, paste, 'sort_rows', {'column': '序号', 'ascending': 'true'})
        assert [row['序号'] for row in rows][:4] == [1, 3, 4, 5]


@pytest.mark.serial
class TestRenameWithoutANewName:
    """``mapping[from] = params.get('rename_to', '')`` — an empty target is a name.

    The panel shows two boxes; filling only the first is a half-finished thought,
    and the node renames the column to the empty string. Every later reader of that
    table — the preview, the chart's field dropdown, the export header — then looks
    at a column called ``""`` (or at nothing, because a blank key is what the
    browser uses for "no column chosen"). Refusing the step, or leaving the column
    alone, are the two answers a user can act on; neither is what happens. Pinned
    as CURRENT behaviour.
    """

    def test_the_mapping_is_built_with_an_empty_target(self, app_module):
        assert _normalize(app_module, 'rename_columns', {'rename_from': '城市'}) == {'mapping': {'城市': ''}}
        assert _normalize(app_module, 'rename_columns', {'rename_from': '城市', 'rename_to': ''}) == {
            'mapping': {'城市': ''}
        }

    @pytest.mark.parametrize('rename_from', [['a', 'b'], {'k': 1}])
    def test_an_unhashable_source_name_raises_inside_the_normalizer(self, app_module, rename_from):
        """CURRENT behaviour, pinned because it is the one branch that can break a
        run rather than disappoint it: ``mapping[params['rename_from']] = …`` uses
        the incoming value as a dict key, so a JSON list or object — which the
        panel cannot send but a workflow file can — dies with
        ``TypeError: unhashable type`` inside the node executor. Every other
        branch normalizes junk into *kwargs* and lets the operator refuse by name.
        """
        with pytest.raises(TypeError) as excinfo:
            _normalize(app_module, 'rename_columns', {'rename_from': rename_from, 'rename_to': '新'})
        assert 'unhashable type' in str(excinfo.value)

    def test_the_run_then_hands_out_a_column_named_nothing_at_all(self, client, app_module, paste):
        rows = _run_analysis_node(client, app_module, paste, 'rename_columns', {'rename_from': '城市'})
        assert '' in rows[0] and '城市' not in rows[0], rows[0]
        assert {key for key in rows[0] if not key}, 'the renamed column is addressable only as the empty string'

    @pytest.mark.parametrize(
        ('rename_from, mapping'),
        [
            ('城市', {'城市': '新'}),
            # The guard is ``if params.get('rename_from')`` — truthiness, so the
            # falsy spellings build no mapping at all…
            ('', {}),
            (0, {}),
            (None, {}),
            (False, {}),
            ([], {}),
            # …and everything else names a column, whether or not it exists. A
            # whitespace name renames nothing and reports success; so does a typo.
            ('   ', {'   ': '新'}),
            ('nope', {'nope': '新'}),
            (123, {123: '新'}),
        ],
    )
    def test_only_a_falsy_source_names_nothing(self, app_module, rename_from, mapping):
        assert _normalize(app_module, 'rename_columns', {'rename_from': rename_from, 'rename_to': '新'}) == {
            'mapping': mapping
        }


# ─── the two ways a step list reaches the operators ────────────────────


@pytest.mark.serial
@pytest.mark.serial
class TestOnlyTheSingleOperationPathNormalizes:
    """``params['steps']`` bypasses the normalizer, and so does the HTTP route.

    ``_normalize_analysis_params`` is called from exactly one place: the branch
    that turns a node's *flat* settings into one step. A node carrying a step list
    (the shape ``/api/analysis/run`` accepts, and the shape a workflow file can
    hold) sends its params straight to ``run_pipeline`` as kwargs. Nothing rejects
    the panel's spelling there, so ``columns: '名称, 城市'`` is not a list of two
    names but an iterable of seven characters, and the step quietly does nothing.
    Pinned, because the asymmetry is invisible from the UI: the same form fields
    work in one node and silently fail in the other.
    """

    def test_a_panel_shaped_step_is_not_normalized_and_changes_nothing(self, client, paste):
        dataset_id = paste(FILTER_TABLE, name='raw-steps.csv')
        steps = [{'op': 'select_columns', 'params': {'columns': '名称, 城市'}}]
        body = client.post('/api/analysis/run', json={'dataset_id': dataset_id, 'steps': steps}).get_json()
        # No name survives, so ``select_columns`` falls back to "keep everything" —
        # the step reports success over a table it never touched.
        assert body['report'][0]['rows_removed'] == 0
        assert set(body['preview'][0]) == {'名称', '序号', '城市'}

    def test_the_same_words_as_a_single_operation_select_two_columns(self, client, app_module, paste):
        """The contrast: identical user intent, normalized, and the columns really
        are narrowed — which is what makes the case above a silent failure rather
        than a different answer.
        """
        dataset_id = paste(FILTER_TABLE, name='normalized-step.csv')
        params = _normalize(app_module, 'select_columns', {'columns': '名称, 城市'})
        payload = {'dataset_id': dataset_id, 'steps': _step('select_columns', params)}
        body = client.post('/api/analysis/run', json=payload).get_json()
        assert set(body['preview'][0]) == {'名称', '城市'}

    def test_a_node_with_a_step_list_is_the_same_path(self, client, app_module, paste):
        """The node keeps its promise in both directions: with ``steps`` present the
        executor does not normalize (the workflow file below is a raw
        ``columns`` string and stays a no-op), and without it every flat field is
        normalized before the operator sees it.
        """
        raw = _run_analysis_node(
            client, app_module, paste, '', {}, steps=[{'op': 'select_columns', 'params': {'columns': '名称, 城市'}}]
        )
        assert set(raw[0]) == {'名称', '序号', '城市'}
        normalized = _run_analysis_node(client, app_module, paste, 'select_columns', {'columns': '名称, 城市'})
        assert set(normalized[0]) == {'名称', '城市'}


# ─── the panel/normalizer field contract ───────────────────────────────

# One plausible value per field the browser can write, chosen so that the value
# differs from the field's own default: a field whose probe equals the default is
# indistinguishable from a field the normalizer ignores.
PANEL_VALUE = {
    'columns': 'a, b',
    'column': 'a',
    'value': 'x',
    'op': 'contains',
    'how': 'all',
    'method': 'ffill',
    'rename_from': 'a',
    'rename_to': 'b',
    'dtype': 'int',
    'ascending': 'false',
    'n': '3',
    'frac': '0.5',
    'seed': '7',
    'group_col': 'a',
    'agg_col': 'b',
    'agg_func': 'mean',
    'join_how': 'inner',
    'left_on': 'a',
    'right_on': 'b',
    'new_col': 'c',
    'expr': 'a + 1',
    'bin_new_col': 'd',
    'bins': '0, 1, 2',
    'bin_labels': 'lo, hi',
}


class TestPanelFieldsAndNormalizerKeysAgree:
    """The browser's field names and the normalizer's ``params.get`` keys.

    ``_normalize_analysis_params`` reads its keys by hand-typed string, and
    ``renderAnalysisSettings`` writes them by hand-typed string, one block per
    operation. A field named differently on the two sides is not a crash: the
    operator silently keeps its own default while the panel shows a choice. That
    is the drift this contract stops, in both directions:

    * every field a block writes must change the kwargs it produces (leave-one-out),
    * no key outside that block's fields may change them (the whole field
      vocabulary of the panel is offered to each operation instead).
    """

    def test_the_panel_has_a_block_for_every_registered_operation(self):
        blocks = _panel_blocks()
        rendered = {op for ops, _fields in blocks if ops for op in ops}
        assert rendered == set(_registry()), 'a block renders for an operation that does not exist (or none does)'
        # The part of the form that is not per-operation is the operation picker.
        head = [fields for ops, fields in blocks if ops is None]
        assert head == [['operation']], head

    @pytest.mark.parametrize('op', sorted(_registry()))
    def test_every_field_the_panel_writes_changes_the_kwargs(self, app_module, op):
        fields = sorted(_panel_fields(op))
        assert fields, f'{op} has no writable field in the panel'
        assert set(fields) <= set(PANEL_VALUE), f'no probe value for {sorted(set(fields) - set(PANEL_VALUE))}'
        full = _normalize(app_module, op, {key: PANEL_VALUE[key] for key in fields})
        for field in fields:
            without = _normalize(app_module, op, {k: PANEL_VALUE[k] for k in fields if k != field})
            assert without != full, f'{op}.{field} is written by the panel and ignored by the normalizer'

    @pytest.mark.parametrize('op', sorted(_registry()))
    def test_no_key_outside_the_panel_changes_the_kwargs(self, app_module, op):
        fields = sorted(_panel_fields(op))
        full = _normalize(app_module, op, {key: PANEL_VALUE[key] for key in fields})
        for stray in sorted(set(PANEL_VALUE) - set(fields)):
            probe = _normalize(app_module, op, {**{key: PANEL_VALUE[key] for key in fields}, stray: PANEL_VALUE[stray]})
            assert probe == full, f'{op} reads {stray}, which its panel block never writes'

    def test_the_operation_picker_is_read_by_the_executor(self, app_module):
        """``operation`` is the one field outside the kwargs: the executor reads it
        to choose which branch of the normalizer runs, so a panel that renamed it
        would leave every node configured but inert.
        """
        assert _normalize(app_module, 'drop_null', {'operation': 'sort_rows'}) == {'columns': [], 'how': 'any'}


# ─── step order through the endpoint ───────────────────────────────────


class TestStepOrderIsTheAnswer:
    """The report the endpoint answers with is in the order the steps were sent.

    The console prints one line per entry of it, so the browser's step order has
    to survive the round trip — and ``run_pipeline`` is the only code that decides
    what "then" means. The chain is chosen so that each step only does something
    because of the one before it: a rename, then a filter on the new name, then a
    descending sort, then a de-duplication.
    """

    def test_the_report_the_endpoint_answers_is_in_the_order_the_steps_were_sent(self, client, app_module, paste):
        dataset_id = paste(FILTER_TABLE, name='ordered-steps.csv')
        steps = (
            _step('rename_columns', {'mapping': {'城市': 'city'}})
            + _step('filter_rows', {'column': 'city', 'op': 'contains', 'value': '京'})
            + _step('sort_rows', {'column': '序号', 'ascending': False})
            + _step('drop_duplicates', {'columns': ['city']})
        )
        body = client.post('/api/analysis/run', json={'dataset_id': dataset_id, 'steps': steps}).get_json()
        assert [step['op'] for step in body['report']] == [step['op'] for step in steps]
        assert [step['rows_before'] for step in body['report']] == [5, 5, 2, 2]
        assert [step['rows_after'] for step in body['report']] == [5, 2, 2, 1]
        # The filter could only have found 京 because the rename ran first, and the
        # descending sort decided *which* 北京 row the de-duplication kept.
        assert [row['city'] for row in body['preview']] == ['北京']
        assert [row['序号'] for row in body['preview']] == [4]

    def test_the_same_steps_in_another_order_answer_another_table(self, client, paste):
        """Reversing the first two steps is not a cosmetic change: the filter then
        looks for a column that is not there yet and keeps all five rows, which is
        the same silent no-op the service-level order tests pin.
        """
        dataset_id = paste(FILTER_TABLE, name='reordered-steps.csv')
        steps = _step('filter_rows', {'column': 'city', 'op': 'contains', 'value': '京'}) + _step(
            'rename_columns', {'mapping': {'城市': 'city'}}
        )
        body = client.post('/api/analysis/run', json={'dataset_id': dataset_id, 'steps': steps}).get_json()
        assert body['row_count'] == 5
        assert [step['rows_removed'] for step in body['report']] == [0, 0]
