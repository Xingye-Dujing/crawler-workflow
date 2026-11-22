"""The analysis node's badge names the box the step contract says is empty.

The rule is the server's (``services/analysis/step_checks``, delivered with the edit-time
diagnostics); this harness runs the REAL ``Diagnostics.recompute`` + ``panels/diagnostics.js``
to prove two things a Python-only test cannot see: nothing is flagged before the payload
arrives (the browser keeps no second copy of the contract), and a payload becomes the message
the node's top-right badge shows — worded through the catalogue, naming the panel's own label.

It also pins the boundary: these are EDIT-TIME diagnostics merged like a missing column, so the
run gate stays the server's (``/api/workflow/validate``); this harness answers no local rule body.
"""

import json
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[2] / 'frontend' / 'harness_validate.mjs'


def _node(nid, ntype, params, title='t'):
    return {'id': nid, 'type': ntype, 'title': title, 'params': params}


def _canvas(params=None):
    params = {'operation': 'dedupe_similar', 'column': ''} if params is None else params
    return [
        _node('u', 'upload', {'dataset_id': 'd1', 'dataset_name': 'x.csv'}, '上传'),
        _node('a', 'analysis', params, '清理'),
        _node('o', 'output', {'operation': 'save', 'filename': 'x.csv'}, '保存'),
    ], [{'from': 'u', 'to': 'a'}, {'from': 'a', 'to': 'o'}]


def _run(tmp_path: Path, scenarios: list) -> dict:
    path = tmp_path / 'scenarios.json'
    path.write_text(json.dumps(scenarios, ensure_ascii=False), encoding='utf-8')
    proc = run_node(HARNESS, JS_DIR / 'workflow.js', path)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _parse(message: str) -> tuple[str, list[str]]:
    head, *fields = message.split('|')
    return head, fields


@pytest.fixture(scope='module')
def results(tmp_path_factory):
    nodes, connections = _canvas()
    clean_nodes, clean_connections = _canvas({'operation': 'dedupe_similar', 'column': '正文'})

    def scenario(sid, problems, **extra):
        return {'id': sid, 'nodes': nodes, 'connections': connections, 'badge': 'a', 'paramProblems': problems, **extra}

    return _run(
        tmp_path_factory.mktemp('analysis-badge'),
        [
            scenario(
                'blank_column',
                {'a': [{'code': 'need_param', 'op': 'dedupe_similar', 'param': 'column', 'field': 'settings.column'}]},
            ),
            scenario(
                'bad_option',
                {
                    'a': [
                        {
                            'code': 'bad_option',
                            'op': 'convert_type',
                            'param': 'dtype',
                            'field': 'settings.dtype',
                            'value': 'integer',
                            'allowed': ['str', 'int'],
                        }
                    ]
                },
            ),
            scenario(
                'rename_blank',
                {'a': [{'code': 'rename_blank', 'op': 'rename_columns', 'param': 'rename_to', 'cols': ['标题']}]},
            ),
            scenario(
                'labels_mismatch',
                {
                    'a': [
                        {
                            'code': 'labels_mismatch',
                            'op': 'bin_time',
                            'param': 'labels',
                            'field': 'settings.phaseLabels',
                            'edges': 3,
                            'expected': 2,
                            'given': 1,
                        }
                    ]
                },
            ),
            scenario('steps_shape', {'a': [{'code': 'steps_shape', 'op': 'analysis'}]}),
            scenario('no_payload', {}),
            {'id': 'clean_node', 'nodes': clean_nodes, 'connections': clean_connections, 'badge': 'a'},
        ],
    )


class TestAnalysisBadge:
    def test_a_blank_required_column_becomes_a_badge_message(self, results):
        messages = results['badges']['blank_column']
        assert len(messages) == 1, messages
        key, fields = _parse(messages[0])
        assert key == 'validate.analysisParam'
        assert fields[0] == '清理', 'the badge names the node'
        # the field is the panel's own label key — not the executor's ``column`` kwarg
        assert 'settings.column' in fields, fields

    def test_a_bad_select_value_names_the_value_and_the_allowed_ones(self, results):
        key, fields = _parse(results['badges']['bad_option'][0])
        assert key == 'validate.analysisParamOption'
        assert 'integer' in fields and 'str, int' in fields, fields

    def test_a_rename_with_no_new_name_is_a_badge_message(self, results):
        key, fields = _parse(results['badges']['rename_blank'][0])
        assert key == 'validate.analysisRename'
        assert '标题' in fields, fields

    def test_a_dict_shaped_steps_value_is_named(self, results):
        key, _fields = _parse(results['badges']['steps_shape'][0])
        assert key == 'validate.analysisStepsShape'

    def test_a_phase_name_list_of_the_wrong_length_is_a_badge_message(self, results):
        key, fields = _parse(results['badges']['labels_mismatch'][0])
        assert key == 'validate.analysisPhaseLabels'
        assert fields[9:12] == ['3', '2', '1'], fields

    def test_without_the_payload_nothing_is_invented(self, results):
        """The browser must not keep its own copy of which box a step needs: before the
        diagnostics fetch answers, the node carries no badge."""
        assert results['badges']['no_payload'] == [], results['badges']['no_payload']

    def test_a_complete_node_is_never_flagged(self, results):
        assert results['badges']['clean_node'] == [], results['badges']['clean_node']

    def test_the_badge_is_edit_time_and_never_a_second_run_gate(self, results):
        """These messages come from the server's diagnostics payload, so the harness answers no
        ``validate`` channel at all: the run gate is ``/api/workflow/validate``, not this file."""
        assert 'validate' not in results, results.keys()
