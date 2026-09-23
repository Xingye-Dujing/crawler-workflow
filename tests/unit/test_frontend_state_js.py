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
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which('node') is None, reason='node not installed'),
]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
FRONT = REPO / 'tests' / 'frontend'


def _run(harness: str, args: list, scenarios: list, tmp_path: Path, extra: list | None = None) -> dict:
    sc = tmp_path / f'{harness}.json'
    sc.write_text(json.dumps(scenarios, ensure_ascii=False), encoding='utf-8')
    # Anything the harness reads after the scenario file (a dumped matrix, say)
    # goes last, so the argument order in the harness header stays the real one.
    tail = [str(item) for item in (extra or [])]
    proc = run_node(str(FRONT / harness), *[str(a) for a in args], str(sc), *tail)
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
            'id': 'wired_node',
            'add': ['source'],
            'wire': 'node-1',
        },
        {
            'id': 'hostile_id',
            'restore': {
                'nodes': {
                    "x' onmouseover='alert(1)": {
                        'id': "x' onmouseover='alert(1)",
                        'type': 'source',
                        'title': "evil' onclick='alert(2)",
                        'params': {'platform': 'weibo', 'keyword': "k'); alert(3); //"},
                        'x': 10,
                        'y': 20,
                    }
                },
                'connections': [],
            },
        },
        {
            'id': 'copy_paste_named',
            'restore': {
                'nodes': {
                    'node-1': {
                        'id': 'node-1',
                        'type': 'source',
                        'title': '我的抓取',
                        'params': {'platform': 'zhihu', 'keyword': 'AI'},
                        'x': 12,
                        'y': 34,
                    }
                },
                'connections': [],
            },
            'copy': 'node-1',
            'paste': 2,
        },
        {
            'id': 'copy_paste_default_label',
            'add': ['source'],
            'copy': 'node-1',
            'paste': 1,
            'setLang': 'zh',
            'refresh': ['node-2'],
        },
        {'id': 'paste_without_copy', 'add': ['source'], 'paste': 1},
        {
            'id': 'undo_keeps_ids',
            'add': ['source', 'source', 'source'],
            'deleteNode': 'node-2',
            'undo': True,
        },
        {
            'id': 'restore_then_add',
            'restore': {
                'nodes': {
                    'node-1': {'id': 'node-1', 'type': 'source', 'title': '一号', 'params': {}, 'x': 1, 'y': 1},
                    'node-5': {'id': 'node-5', 'type': 'output', 'title': '五号', 'params': {}, 'x': 2, 'y': 2},
                },
                'connections': [{'from': 'node-1', 'to': 'node-5'}],
            },
            'add': ['output'],
        },
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

    def test_copying_a_named_node_pastes_the_name_too(self, state):
        nodes = state['copy_paste_named']['nodes']
        assert [n['title'] for n in nodes] == ['我的抓取', '我的抓取', '我的抓取']
        pasted = nodes[1]
        assert pasted['elTitle'] == '我的抓取', 'the element text is what the user reads on the canvas'
        assert state['copy_paste_named']['clipboard']['title'] == '我的抓取'
        for n in nodes[1:]:
            assert n['params'] == nodes[0]['params'], 'the settings must travel with the name'
            assert n['id'] != nodes[0]['id'], 'a paste is a new node, not a second label on the old one'
        assert any(msg == 'toast.nodeCopied' for msg in state['copy_paste_named']['toasts'])

    def test_a_pasted_default_label_still_translates_with_the_language(self, state):
        nodes = {n['id']: n for n in state['copy_paste_default_label']['nodes']}
        assert nodes['node-1']['title'] == 'Data Source'
        assert nodes['node-2']['title'] == '数据源', 'nothing was named, so there is nothing to keep'

    def test_pasting_with_nothing_copied_adds_no_node(self, state):
        r = state['paste_without_copy']
        assert [n['id'] for n in r['nodes']] == ['node-1']
        assert not any(msg == 'toast.nodePasted' for msg in r['toasts'])

    def test_undo_removes_the_last_add_and_redo_brings_it_back(self, state):
        assert [n['id'] for n in state['undo_last']['nodes']] == ['node-1']
        ids = [n['id'] for n in state['undo_redo']['nodes']]
        assert ids == ['node-1', 'node-2']

    def test_an_undo_keeps_every_node_under_its_own_id(self, state):
        """Ids are storage keys: runs, resume cursors and cached answers are all
        filed under them, and the workflow fingerprint hashes them. Re-minting
        them on Ctrl+Z used to detach the canvas from its own interrupted run."""
        r = state['undo_keeps_ids']
        assert [n['id'] for n in r['nodes']] == ['node-1', 'node-2', 'node-3']
        assert [n['title'] for n in r['nodes']] == ['Data Source', 'Data Source', 'Data Source']

    def test_a_restored_canvas_continues_the_numbering_past_its_ids(self, state):
        """A canvas restored from a sparse/foreign numbering must still be able
        to add a node without colliding with one already on the board."""
        r = state['restore_then_add']
        assert [n['id'] for n in r['nodes']] == ['node-1', 'node-5', 'node-6']
        assert r['connections'] == [{'from': 'node-1', 'to': 'node-5'}], 'the new node is not wired to anything'

    def test_language_flip_restamps_only_default_labels(self, state):
        nodes = {n['id']: n for n in state['restamp']['nodes']}
        assert nodes['node-1']['title'] == '保留名', 'a renamed node keeps its name across languages'
        assert nodes['node-2']['title'] == '输出', 'a still-default label translates with the UI'

    def test_every_palette_type_ships_its_default_params(self, state):
        by_type = {n['type']: n['params'] for n in state['defaults']['nodes']}
        # A source node seeds only its identity here: this world has no
        # /api/capabilities to ask, and the figures a crawl needs have one owner
        # (the matrix), which TestNewSourceNodeCarriesTheMatrix supplies below.
        assert {'platform', 'collect'} <= set(by_type['source'])
        assert {'urls', 'comment_limit', 'part_size'} <= set(by_type['comment'])
        assert {'dataset_id'} <= set(by_type['upload'])
        assert {'operation'} <= set(by_type['analysis'])
        assert {'chart_type', 'x_field'} <= set(by_type['visualize'])
        assert {'workflow_name'} <= set(by_type['name'])
        assert {'resume_run_id', 'resume_node_id'} <= set(by_type['resume'])


class TestNodeWiringAndMarkup:
    """A node's handlers are attached, not spelled into its markup.

    The header used to be built as `ondblclick="canvas.renameNode('<id>')"` and
    `onclick="canvas.editNode('<id>')"` strings with the id spliced in — and the
    id, the title and the params all come out of a workflow JSON file the user can
    open in an editor. One quote in any of them ended the string literal and the
    rest ran as code on every load of that file.
    """

    def test_the_title_and_both_buttons_still_do_their_job(self, state):
        r = state['wired_node']
        assert r['wiring']['rename'] == 'node-1', 'double-clicking the title must open the rename prompt'
        assert r['wiring']['edit'] == 'node-1', 'the pencil button must open the settings panel'
        assert r['wiring']['left'] == [], 'the cross button must delete the node it belongs to'

    def test_a_built_node_carries_no_inline_handler_at_all(self, state):
        html = state['wired_node']['wiring']['markup']
        assert html, 'the harness must report the markup it built'
        for gone in ('onclick', 'ondblclick', 'onmouseover', 'javascript:'):
            assert gone not in html, f'{gone} is back in the node markup'

    def test_an_id_that_is_not_id_shaped_gets_a_fresh_one(self, state):
        """The hostile file asks to be identified by
        ``x' onmouseover='alert(1)`` — the node is built anyway (the workflow is
        still usable) but under a minted id, so the string never reaches markup."""
        node = state['hostile_id']['nodes'][0]
        assert node['id'] == 'node-1'
        assert node['params']['platform'] == 'weibo', 'refusing the id must not throw the node away'
        assert node['elTitle'] == "evil' onclick='alert(2)", 'and the chosen name still shows'
        html = node['html']
        for never in ('alert(', 'onmouseover', "onclick='x"):
            assert never not in html, f'{never} reached the markup'

    def test_user_text_reaches_the_node_only_as_text(self, state):
        """The summary line is built from params (a keyword, a filename): it goes in
        through textContent, so a quote or a tag inside it stays visible text."""
        node = state['hostile_id']['nodes'][0]
        assert '); alert(3); //' in node['params']['keyword']
        assert '<script' not in node['html'] and 'alert(3)' not in node['html']


@pytest.fixture(scope='module')
def life(tmp_path_factory, capabilities_matrix):
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
        {
            'id': 'open_file_without_nodes',
            'currentFile': 'good-name',
            'add': ['source'],
            'loadByName': 'junk',
            'loadResponse': {'ok': True, 'workflow': {'settings': {}}},
        },
        {
            # A node dragged out of the palette with nobody having touched its
            # panel: the numbers it carries must be the server's, not a copy.
            'id': 'matrix_defaults',
            'add': ['source'],
        },
    ]
    return _run(
        'harness_lifecycle.mjs',
        [JS_DIR / 'canvas.js', JS_DIR / 'workflow.js'],
        scenarios,
        tmp,
        extra=[capabilities_matrix],
    )


class TestNewSourceNodeCarriesTheMatrix:
    """canvas.js seeds a Data Source from the crawl matrix, in the one world where
    both halves of the product are loaded together and the endpoint answers."""

    def test_the_seeded_params_are_the_declared_defaults(self, life):
        import crawl_capabilities

        node = life['matrix_defaults']['nodes'][0]
        assert node['type'] == 'source'
        expected = crawl_capabilities.declared_defaults('zhihu')
        expected['platform'] = 'zhihu'
        expected['collect'] = 'posts'
        assert node['params'] == expected, (
            'a node that never opened its panel must crawl with exactly the figures its panel would have previewed'
        )

    def test_the_number_default_survives_the_round_trip_as_a_number(self, life):
        params = life['matrix_defaults']['nodes'][0]['params']
        assert params['target_count'] == 50 and params['part_size'] == 0
        assert params['keep_parts'] is False and params['format'] == 'csv'


class TestFileLifecycle:
    def test_load_rebuilds_nodes_titles_and_keeps_their_ids(self, life):
        r = life['load_open']
        titles = [n['title'] for n in r['nodes']]
        assert titles == ['抓取微博', '清洗', 'Output']
        # The file's own ids come back unchanged. They used to be re-minted to
        # node-1..3, which silently detached the canvas from every run record,
        # resume cursor and cached answer filed under the original ids.
        assert [n['id'] for n in r['nodes']] == ['nA', 'nB', 'nC']
        assert r['connections'] == [{'from': 'nA', 'to': 'nC'}, {'from': 'nB', 'to': 'nC'}]

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

    def test_opening_a_file_without_a_node_list_changes_nothing(self, life):
        """The server answered ok for a JSON file that is not a workflow. Loading
        used to clear the canvas FIRST and then die on the missing node list, so a
        stray file cost the user their unsaved work and said only 'load failed'."""
        r = life['open_file_without_nodes']
        assert len(r['nodes']) == 1, 'the canvas on screen must survive the bad file'
        assert r['currentFile'] == 'good-name', 'the next Save must not overwrite the junk file as if it were loaded'
        assert any('toast.workflowFileInvalid' in msg for msg in r['toasts']), r['toasts']
