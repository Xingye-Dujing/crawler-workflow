"""Bounded text for the workspace's ``@`` references.

A reference is expanded on the server and stored on the user's row, so every reader here caps its
own output: a dataset is a shape plus three rows, a workflow is a node map, a run is verdicts plus a
console tail. A missing object returns ``''`` so the framework reports it as unresolved by name.
"""

import pandas as pd
import pytest
from ai import reference_text
from runtime import stores

pytestmark = pytest.mark.unit


class TestDatasets:
    def test_the_preview_is_a_shape_and_a_few_rows(self):
        frame = pd.DataFrame({'正文': ['one', 'two', 'three', 'four']})
        dataset_id, _stored = stores.register_dataset_result(frame, name='ref.csv')
        text = reference_text.dataset(dataset_id)
        assert '共 4 行' in text
        assert '正文' in text
        assert 'one' in text
        assert 'four' not in text, 'the preview must not carry the whole table'

    def test_a_missing_dataset_is_unresolved(self):
        assert reference_text.dataset('ds_missing') == ''


class TestWorkflows:
    def test_a_saved_canvas_reads_back_as_a_node_map(self):
        stores.get_workflow_manager().save(
            'ref-test',
            {
                'nodes': [
                    {'id': 'n1', 'type': 'name', 'title': 'Head', 'params': {'workflow_name': 'ref-test'}},
                    {'id': 'n2', 'type': 'upload', 'title': 'Rows', 'params': {'dataset_id': 'ds_1'}},
                ],
                'connections': [{'from': 'n1', 'to': 'n2'}],
            },
        )
        text = reference_text.workflow('ref-test')
        assert '工作流 ref-test（2 个节点' in text
        assert 'Head [name]' in text
        assert 'n1→n2' in text

    def test_a_missing_name_is_unresolved(self):
        assert reference_text.workflow('no-such-workflow') == ''


class TestRuns:
    def test_an_unknown_run_is_unresolved(self):
        assert reference_text.run('run_missing') == ''


class TestExportsAndSkills:
    def test_a_missing_export_and_a_missing_skill_are_unresolved(self):
        assert reference_text.export('no-such-export.csv') == ''
        assert reference_text.skill('node.no_such') == ''
