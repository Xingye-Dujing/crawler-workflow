"""Behaviour tests for the canvas state machine and the File-menu lifecycle.

Everything here runs the untouched canvas.js/workflow.js inside node
(tests/frontend/harness_*.mjs with the shared fake DOM). What it pins:

* restore/open must carry renamed node titles into BOTH the node object and
  the element text — the bug that made every reload erase the names;
* a node still wearing a default label re-stamps when the language flips,
  while a renamed node keeps its name;
* save → POST payload, cancel → no request;
* open-by-name rebuilds nodes/connections and applies mode/headless;
* a failed open leaves the current canvas and file name untouched;
* upload nodes whose file died on the server are cleared WITH a toast;
* newFile empties the canvas and removes the auto-save draft;
* undo/redo walk the history stack.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which('node') is None, reason='node not installed'),
]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
FRONT = REPO / 'tests' / 'frontend'


def _run(harness: str, args: list, scenarios: list, tmp_path: Path) -> dict:
    sc = tmp_path / f'{harness}.json'
    sc.write_text(json.dumps(scenarios, ensure_ascii=False), encoding='utf-8')
    proc = subprocess.run(
        ['node', str(FRONT / harness), *[str(a) for a in args], str(sc)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=60,
    )
    assert proc.returncode == 0, f'{harness} failed: {proc.stderr}'
    return json.loads(proc.stdout)


@pytest.fixture(scope='module')
def state(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('js-state')
    scenarios = [
        {
            'id': 'restore_titles',
            'restore': {
                'nodes': {
                    'node-1': {
                        'id': 'node-1',
                        'type': 'source',
                        'title': '我的抓取',
                        'params': {'platform': 'weibo', 'keyword': 'k'},
                        'x': 10,
                        'y': 20,
                    },
                    'node-2': {
                        'id': 'node-2',
                        'type': 'output',
                        'title': None,
                        'params': {'operation': 'save'},
                        'x': 40,
                        'y': 50,
                    },
                },
                'connections': [{'from': 'node-1', 'to': 'node-2'}],
            },
        },
        {'id': 'undo_last', 'add': ['source', 'output'], 'undo': True},
        {'id': 'undo_redo', 'add': ['source', 'output'], 'undo': True, 'redo': True},
        {
            'id': 'restamp',
            'restore': {
                'nodes': {
                    'node-1': {'id': 'node-1', 'type': 'source', 'title': '保留名', 'params': {}, 'x': 1, 'y': 1},
                    'node-2': {'id': 'node-2', 'type': 'output', 'title': 'Output', 'params': {}, 'x': 2, 'y': 2},
                },
                'connections': [],
            },
            'setLang': 'zh',
            'refresh': ['node-1', 'node-2'],
        },
        {
            'id': 'defaults',
            'add': [
                'source',
                'upload',
                'process',
                'output',
                'visualize',
                'tokenize',
                'analysis',
                'resume',
                'name',
                'comment',
            ],
        },
    ]
    return _run('harness_state.mjs', [JS_DIR / 'canvas.js'], scenarios, tmp)


class TestCanvasState:
    def test_open_restores_a_renamed_title_into_node_and_element(self, state):
        n1 = state['restore_titles']['nodes'][0]
        assert n1['title'] == '我的抓取'
        assert n1['elTitle'] == '我的抓取', 'the element must carry the name too — the re-stamp reads it'

    def test_a_titleless_node_becomes_the_type_label_not_null(self, state):
        n2 = state['restore_titles']['nodes'][1]
        assert n2['title'] == 'Output'

    def test_undo_removes_the_last_add_and_redo_brings_it_back(self, state):
        assert [n['id'] for n in state['undo_last']['nodes']] == ['node-1']
        ids = [n['id'] for n in state['undo_redo']['nodes']]
        assert ids == ['node-1', 'node-2']

    def test_language_flip_restamps_only_default_labels(self, state):
        nodes = {n['id']: n for n in state['restamp']['nodes']}
        assert nodes['node-1']['title'] == '保留名', 'a renamed node keeps its name across languages'
        assert nodes['node-2']['title'] == '输出', 'a still-default label translates with the UI'

    def test_every_palette_type_ships_its_default_params(self, state):
        by_type = {n['type']: n['params'] for n in state['defaults']['nodes']}
        assert {'platform', 'keyword', 'collect', 'part_size', 'format', 'keep_parts'} <= set(by_type['source'])
        assert {'urls', 'comment_limit', 'part_size'} <= set(by_type['comment'])
        assert {'dataset_id'} <= set(by_type['upload'])
        assert {'operation'} <= set(by_type['analysis'])
        assert {'chart_type', 'x_field'} <= set(by_type['visualize'])
        assert {'workflow_name'} <= set(by_type['name'])
        assert {'resume_run_id', 'resume_node_id'} <= set(by_type['resume'])


@pytest.fixture(scope='module')
def life(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('js-life')
    opened = {
        'nodes': [
            {
                'id': 'nA',
                'type': 'source',
                'title': '抓取微博',
                'params': {'platform': 'weibo', 'keyword': 'AI'},
                'x': 5,
                'y': 5,
            },
            {
                'id': 'nB',
                'type': 'upload',
                'title': '清洗',
                'params': {'dataset_id': 'dead-id', 'dataset_name': 'old.csv', 'row_count': 3},
                'x': 9,
                'y': 9,
            },
            {
                'id': 'nC',
                'type': 'output',
                'title': None,
                'params': {'operation': 'save', 'filename': 'o'},
                'x': 1,
                'y': 1,
            },
        ],
        'connections': [{'from': 'nA', 'to': 'nC'}, {'from': 'nB', 'to': 'nC'}],
        'settings': {'mode': 'serial', 'headless': False},
    }
    scenarios = [
        {'id': 'load_open', 'load': opened},
        {'id': 'newfile', 'add': ['source'], 'newFile': True},
        {'id': 'save_named', 'currentFile': 'wf1', 'save': True},
        {'id': 'save_cancel', 'dialogAnswer': None, 'save': True},
        {'id': 'save_prompt_ok', 'dialogAnswer': '新工作流', 'save': True},
        {'id': 'open_by_name', 'loadByName': '我的流程', 'loadResponse': {'ok': True, 'workflow': opened}},
        {
            'id': 'open_missing',
            'currentFile': 'old-name',
            'add': ['source'],
            'loadByName': 'nope',
            'loadResponse': {'ok': False, 'error': 'missing file'},
        },
    ]
    return _run('harness_lifecycle.mjs', [JS_DIR / 'canvas.js', JS_DIR / 'workflow.js'], scenarios, tmp)


class TestFileLifecycle:
    def test_load_rebuilds_nodes_titles_and_remaps_connections(self, life):
        r = life['load_open']
        titles = [n['title'] for n in r['nodes']]
        assert titles == ['抓取微博', '清洗', 'Output']
        # File ids (nA/nB/nC) must land on the freshly built node-1..3 ids.
        assert r['connections'] == [{'from': 'node-1', 'to': 'node-3'}, {'from': 'node-2', 'to': 'node-3'}]

    def test_load_applies_the_stored_run_settings(self, life):
        r = dict(life['load_open']['runState'])
        assert r['parallel'] is False, "settings.mode='serial' must leave parallel mode"
        assert r['headless'] is False

    def test_a_dead_upload_file_is_cleared_with_a_toast(self, life):
        r = life['load_open']
        upload = next(n for n in r['nodes'] if n['type'] == 'upload')
        assert upload['params']['dataset_id'] == '', 'the dead file id must not survive to a doomed run'
        assert any('toast.datasetsMissing' in msg for msg in r['toasts'])

    def test_newfile_empties_canvas_and_draft(self, life):
        r = life['newfile']
        assert r['nodes'] == [] and r['connections'] == []
        assert r['currentFile'] is None
        assert r['newfileDraftCleared']

    def test_saving_a_named_workflow_posts_its_name_and_canvas(self, life):
        r = life['save_named']
        assert [f['url'] for f in r['fetches']] == ['/api/workflow/save']
        body = json.loads(r['fetches'][0]['body'])
        assert body['name'] == 'wf1'
        assert r['currentFile'] == 'wf1'

    def test_a_cancelled_name_prompt_saves_nothing(self, life):
        assert life['save_cancel']['fetches'] == []
        assert life['save_cancel']['currentFile'] is None

    def test_prompted_name_is_used_and_remembered(self, life):
        r = life['save_prompt_ok']
        body = json.loads(r['fetches'][0]['body'])
        assert body['name'] == '新工作流'
        assert r['currentFile'] == '新工作流'

    def test_open_by_name_loads_and_remembers_the_file(self, life):
        r = life['open_by_name']
        assert r['currentFile'] == '我的流程'
        assert [n['title'] for n in r['nodes']] == ['抓取微博', '清洗', 'Output']
        assert any(f['url'].startswith('/api/workflow/load') for f in r['fetches'])

    def test_a_failed_open_leaves_the_current_canvas_and_name_intact(self, life):
        r = life['open_missing']
        assert r['currentFile'] == 'old-name', 'a failed open must not forget what is on screen'
        assert len(r['nodes']) == 1, 'the pre-existing canvas must survive untouched'
        assert any('loadfail' in msg for msg in r['toasts'])
