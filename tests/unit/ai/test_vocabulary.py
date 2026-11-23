"""The Harness seam: legal vocabulary and the workflow draft round trip.

No browser, no provider, no network. These are the server facts a workflow draft depends on, and
they are the ones a model gets wrong when the prompt is thin.
"""

import os

import pytest

pytestmark = pytest.mark.unit


class TestVocabulary:
    def test_every_node_type_is_named_with_its_params(self):
        from ai import vocabulary
        from nodes.catalog import NODE_TYPES

        catalog = {row['type']: row for row in vocabulary.node_catalog()}
        assert set(catalog) == set(NODE_TYPES)
        assert 'operation' in catalog['analysis']['params']
        assert 'chart_type' in catalog['visualize']['params']
        assert catalog['source']['params_from'] == 'capabilities'

    def test_the_prompt_names_every_platform_mode_and_chart(self):
        from ai import vocabulary

        from services.charts.registry import SPECS

        text = vocabulary.prompt_block()
        for row in vocabulary.platform_matrix():
            assert row['platform'] in text
        for spec in SPECS:
            assert spec.key in text
        # A display word the model used to invent is NOT a node type, and the rules say so.
        assert 'analysis（' in text or 'analysis' in text

    def test_the_analysis_catalog_keeps_its_required_columns(self):
        from ai import vocabulary

        rows = {row['operation']: row for row in vocabulary.analysis_catalog()}
        assert rows['groupby_agg']['needs_column'] == ['group_col', 'agg_col']
        assert rows['filter_rows']['allowed']['op']

    def test_the_workflow_schema_is_the_file_shape_the_canvas_loads(self):
        from ai import vocabulary

        schema = vocabulary.workflow_schema()
        assert schema['shape']['nodes'][0]['type'] == '<node type>'
        assert 'connections' in schema['shape']
        assert 'type=' in schema['rules']


class TestDraftValidation:
    def _payload(self):
        return {
            'nodes': [
                {'id': 'n1', 'type': 'upload', 'x': 0, 'y': 0, 'params': {'dataset_id': 'ds1'}},
                {
                    'id': 'n2',
                    'type': 'output',
                    'x': 200,
                    'y': 0,
                    'params': {'operation': 'save', 'format': 'csv', 'filename': 'export.csv'},
                },
            ],
            'connections': [{'from': 'n1', 'to': 'n2'}],
        }

    def test_a_legal_draft_passes_structure_and_the_engine(self):
        from ai import workflow_draft

        report = workflow_draft.validate(self._payload())
        assert report['structural'] == []
        assert report['engine'] == []
        assert report['ok'] is True

    def test_a_display_word_is_refused_by_name(self):
        from ai import workflow_draft

        payload = self._payload()
        payload['nodes'][0]['type'] = '分析'
        report = workflow_draft.validate(payload)
        assert report['ok'] is False
        assert any('分析' in item for item in report['structural'])

    def test_params_that_are_a_sentence_are_refused(self):
        from ai import workflow_draft

        payload = self._payload()
        payload['nodes'][0]['params'] = '去重，按评论内容'
        assert any('params' in item for item in workflow_draft.problems(payload))

    def test_saving_never_overwrites_a_users_workflow(self, data_root):
        from ai import workflow_draft

        first = workflow_draft.save(self._payload(), 'AI 流程')
        second = workflow_draft.save(self._payload(), 'AI 流程')
        assert first['name'] == 'AI 流程'
        assert second['name'] != first['name']
        assert os.path.isfile(first['path'])

    def test_a_full_length_name_still_gets_a_free_suffix(self, data_root):
        """The suffix was appended AFTER the 60-char cap, so it was cut off and the loop exited."""
        from ai import workflow_draft

        base = '长' * 60
        first = workflow_draft.save(self._payload(), base)
        second = workflow_draft.save(self._payload(), base)
        assert first['name'] == base
        assert second['name'] != first['name']
        assert len(second['name']) <= 60
        assert os.path.isfile(second['path'])
