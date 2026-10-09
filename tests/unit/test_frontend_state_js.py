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
import re
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
        {
            'id': 'param_edits_then_undo',
            'add': ['source'],
            'paramEdits': [
                {'id': 'node-1', 'key': 'keyword', 'value': 'AI'},
                {'id': 'node-1', 'key': 'keyword', 'value': 'Robot'},
            ],
            'undo': True,
        },
        {
            'id': 'param_edits_history',
            'add': ['source'],
            'paramEdits': [
                {'id': 'node-1', 'key': 'keyword', 'value': 'AI'},
                {'id': 'node-1', 'key': 'keyword', 'value': 'Robot'},
            ],
        },
        {
            'id': 'autosaves_do_not_evict_history',
            'initialPush': True,
            'add': ['source'],
            'autosaves': 60,
            'undo': True,
        },
        {
            'id': 'draft_open_leaves_one_snapshot',
            'restore': {
                'nodes': {
                    f'node-{i}': {'id': f'node-{i}', 'type': 'source', 'title': 'x', 'params': {}, 'x': i, 'y': i}
                    for i in range(1, 6)
                },
                'connections': [],
            },
        },
        {
            'id': 'backspace_in_a_textarea',
            'add': ['source'],
            'select': 'node-1',
            'key': {'key': 'Backspace', 'target': {'tagName': 'TEXTAREA'}},
        },
        {
            'id': 'backspace_on_the_canvas',
            'add': ['source'],
            'select': 'node-1',
            'key': {'key': 'Backspace', 'target': 'DIV'},
        },
        {
            'id': 'f_key_in_a_textarea',
            'add': ['source'],
            'select': 'node-1',
            'key': {'key': 'f', 'target': {'tagName': 'TEXTAREA'}},
        },
        {
            'id': 'f_key_on_the_canvas',
            'add': ['source'],
            'select': 'node-1',
            'key': {'key': 'f', 'target': 'DIV'},
        },
        # ── disable / enable (canvas mirror of the backend effective graph) ──
        {
            'id': 'disable_head_cascades',
            'restore': {
                'nodes': {
                    'name-1': {
                        'id': 'name-1',
                        'type': 'name',
                        'title': 'A',
                        'params': {'workflow_name': 'A'},
                        'x': 1,
                        'y': 1,
                    },
                    'src-1': {
                        'id': 'src-1',
                        'type': 'source',
                        'title': 'x',
                        'params': {'platform': 'zhihu'},
                        'x': 2,
                        'y': 1,
                    },
                    'out-1': {
                        'id': 'out-1',
                        'type': 'output',
                        'title': 'x',
                        'params': {'operation': 'save'},
                        'x': 3,
                        'y': 1,
                    },
                    'name-2': {
                        'id': 'name-2',
                        'type': 'name',
                        'title': 'B',
                        'params': {'workflow_name': 'B', 'enabled': False},
                        'x': 1,
                        'y': 2,
                    },
                    'src-2': {
                        'id': 'src-2',
                        'type': 'source',
                        'title': 'x',
                        'params': {'platform': 'zhihu'},
                        'x': 2,
                        'y': 2,
                    },
                },
                'connections': [
                    {'from': 'name-1', 'to': 'src-1'},
                    {'from': 'src-1', 'to': 'out-1'},
                    {'from': 'name-2', 'to': 'src-2'},
                ],
            },
        },
        {
            'id': 'fan_in_keeps_join',
            'restore': {
                'nodes': {
                    'sa': {
                        'id': 'sa',
                        'type': 'source',
                        'title': 'x',
                        'params': {'platform': 'zhihu', 'enabled': False},
                        'x': 1,
                        'y': 1,
                    },
                    'sb': {'id': 'sb', 'type': 'source', 'title': 'x', 'params': {'platform': 'weibo'}, 'x': 1, 'y': 2},
                    'j': {
                        'id': 'j',
                        'type': 'analysis',
                        'title': 'x',
                        'params': {'operation': 'drop_null'},
                        'x': 2,
                        'y': 1,
                    },
                },
                'connections': [{'from': 'sa', 'to': 'j'}, {'from': 'sb', 'to': 'j'}],
            },
        },
        {
            'id': 'type_off_starves_child',
            'restore': {
                'nodes': {
                    's': {'id': 's', 'type': 'source', 'title': 'x', 'params': {'platform': 'zhihu'}, 'x': 1, 'y': 1},
                    'p': {'id': 'p', 'type': 'process', 'title': 'x', 'params': {'operation': 'clean'}, 'x': 2, 'y': 1},
                },
                'connections': [{'from': 's', 'to': 'p'}],
            },
            'disabledTypes': ['source'],
        },
        {
            'id': 'toggle_flips_enabled',
            'add': ['source'],
            'toggle': ['node-1'],
        },
        {
            'id': 'type_toggle_off',
            'add': ['source', 'process'],
            'toggleType': ['source'],
        },
        {
            'id': 'add_defaults_on',
            'add': ['source'],
        },
        {
            # A pan/zoom followed by the draft write the real handlers debounce into.
            'id': 'draft_and_file_carry_the_camera',
            'add': ['source'],
            'setView': {'panX': 120, 'panY': -40, 'zoom': 1.5},
            'autosaves': 1,
        },
        {
            'id': 'undo_leaves_the_camera',
            'initialPush': True,
            'add': ['source'],
            'setView': {'panX': 500, 'panY': 60, 'zoom': 2},
            'undo': True,
        },
        {
            # The draft a refresh hands back: a camera AND a node standing at 0,0.
            'id': 'restored_draft_moves_the_camera',
            'restore': {
                'nodes': {
                    'node-1': {
                        'id': 'node-1',
                        'type': 'source',
                        'title': 'x',
                        'params': {'platform': 'zhihu'},
                        'x': 0,
                        'y': 0,
                    },
                },
                'connections': [],
                'view': {'panX': -70, 'panY': 15, 'zoom': 0.5},
            },
        },
        {
            # The user's report: a DISABLED 输出 node, copied then pasted, came back
            # switched-on. The bug was never specific to the output node — a paste rewrites
            # the node's params and title AFTER addNode has already saved a snapshot, and the
            # paste saved nothing, so the draft (what a reload reads) kept the fresh defaults.
            # Reading the DRAFT — not the live nodes — is what catches it.
            'id': 'copy_paste_disabled',
            'restore': {
                'nodes': {
                    'node-1': {
                        'id': 'node-1',
                        'type': 'output',
                        'title': '禁用输出',
                        'params': {'operation': 'save', 'enabled': False},
                        'x': 10,
                        'y': 20,
                    },
                },
                'connections': [],
            },
            'copy': 'node-1',
            'paste': 1,
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

    def test_pasting_a_disabled_node_persists_the_disable_in_the_draft(self, state):
        """Copy/paste writes the node's params and name only after addNode had saved a
        snapshot of the fresh defaults — so unless the paste saves again, a reload hands back
        an ENABLED, unnamed node. The report was a disabled 输出 node coming back switched-on;
        the loss was really every params field and the title, on a paste of any node type.

        The live `nodes` would pass even with the bug (they hold the overwritten params);
        only the persisted `draft` distinguishes saved from merely-in-memory.
        """
        case = state['copy_paste_disabled']
        src, pasted = case['nodes'][0], case['nodes'][1]
        assert src['params'].get('enabled') is False
        assert pasted['type'] == 'output'
        assert pasted['title'] == '禁用输出'
        draft_nodes = case['draft']['nodes']
        assert draft_nodes[pasted['id']]['params'].get('enabled') is False, (
            'the disabled state must reach the persisted draft, not just memory'
        )
        assert draft_nodes[pasted['id']]['title'] == '禁用输出', 'the copied name must persist too'

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
        assert {'workflow_name', 'layout_order'} <= set(by_type['name'])
        assert {'resume_run_id', 'resume_node_id'} <= set(by_type['resume'])


class TestUndoCoversParameterEdits:
    """A snapshot must be a snapshot, and the stack must hold the user's work.

    getState() handed out the node's LIVE params dict, and updateParam mutates that
    dict in place — so every history entry for a node aliased its current state: Ctrl+Z
    undid positions, folds and deletes, but no parameter edit anywhere in the app, and
    a later edit rewrote the PAST entries too. Compounding it, the 30-second autosave
    pushed an identical state each time, so after ~25 idle minutes the 50-deep stack
    held 50 copies of "now" and real edits had been shifted out.
    """

    def test_undo_returns_the_previous_keyword(self, state):
        nodes = state['param_edits_then_undo']['nodes']
        assert len(nodes) == 1, 'undo must not have dropped the node itself'
        assert nodes[0]['params']['keyword'] == 'AI', 'the value typed BEFORE this one is what undo owes the user'

    def test_an_editing_session_keeps_one_entry_per_change(self, state):
        # Two edits + the initial empty canvas = three entries, and the newest one
        # carries the newest value (the undo test above proves the older one does not).
        r = state['param_edits_history']
        assert r['historyLen'] == 3, r['historyLen']
        assert r['nodes'][0]['params']['keyword'] == 'Robot'

    def test_idle_autosaves_cannot_shift_real_edits_out_of_history(self, state):
        r = state['autosaves_do_not_evict_history']
        # The scenario opens the way the page does — one snapshot of an empty canvas,
        # then the node is added, then sixty autosaves of a state nobody changed.
        # History is 50 deep: each of those saves used to be an entry, so half an idle
        # hour at the keyboard pushed every real edit out of the stack and Ctrl+Z
        # started doing nothing at all.
        assert r['historyLen'] == 2, f'60 identical autosaves became {r["historyLen"]} history entries'
        assert r['nodes'] == [], 'undo after half an hour of autosaving still has to remove the added node'

    def test_opening_a_draft_leaves_one_undo_point(self, state):
        """The first Ctrl+Z on a restored canvas must not start deleting restored nodes."""
        r = state['draft_open_leaves_one_snapshot']
        assert len(r['nodes']) == 5
        assert r['historyLen'] == 1, f'each restored node pushed its own snapshot: {r["historyLen"]}'
        assert r['historyIdx'] == 0


class TestTypingNeverTouchesTheCanvas:
    """Shortcuts belong to the canvas only while the user is not typing.

    The guard named INPUT and SELECT, so every multi-line field in the app was
    unprotected: with a node selected, Backspace at the end of a pasted URL deleted
    THE NODE (toast, closed panel, one undo away from being noticed), and typing an
    `f` — in a URL, in `pdf`, in `if` — was swallowed and folded the node instead.
    """

    def test_backspace_in_a_textarea_keeps_the_node(self, state):
        assert len(state['backspace_in_a_textarea']['nodes']) == 1
        assert state['backspace_in_a_textarea']['toasts'] == []

    def test_backspace_on_the_canvas_still_deletes_the_selected_node(self, state):
        assert state['backspace_on_the_canvas']['nodes'] == [], 'the shortcut itself must stay alive'

    def test_f_in_a_textarea_is_a_letter_not_a_fold(self, state):
        r = state['f_key_in_a_textarea']
        assert len(r['nodes']) == 1
        assert not any('fold' in str(msg).lower() for msg in r['toasts']), r['toasts']

    def test_f_on_the_canvas_still_folds(self, state):
        """The exclusion must not quietly retire the shortcut it was written around."""
        r = state['f_key_on_the_canvas']
        assert len(r['nodes']) == 1, r['nodes']


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
        {
            # A file that also carries the camera its author arranged behind.
            'id': 'load_with_view',
            'load': {
                'nodes': opened['nodes'],
                'connections': opened['connections'],
                'settings': {
                    'mode': 'serial',
                    'headless': False,
                    'view': {'panX': -300, 'panY': -80, 'zoom': 0.8},
                },
            },
        },
        {
            # A draft is hand-editable: a garbage camera must not throw or scatter —
            # zoom stays inside the wheel's own clamp.
            'id': 'load_with_broken_view',
            'load': {
                'nodes': opened['nodes'],
                'connections': opened['connections'],
                'settings': {'view': {'panX': 'wide', 'panY': None, 'zoom': 999}},
            },
        },
        {
            # The same file the other way round: a canvas saved as 并行 + 无头.
            'id': 'load_parallel_headless',
            'load': {
                'nodes': opened['nodes'],
                'connections': opened['connections'],
                'settings': {'mode': 'parallel', 'headless': True},
            },
        },
        {
            # A file that says nothing about the run bar must not flip it either way.
            'id': 'load_without_settings',
            'load': {'nodes': opened['nodes'], 'connections': opened['connections']},
        },
        {'id': 'newfile', 'add': ['source'], 'newFile': True},
        {
            # A reload/restart reopens the file the draft belongs to — the boot `openFile`
            # step restores the persisted name, so runName()/export identity survives.
            'id': 'restore_after_reload',
            'storedOpenFile': '甲流程',
            'restore': True,
        },
        {
            # An empty browser (no draft) must not claim a file it never loaded: restoring a
            # name with nothing on screen would attribute the next Save to a phantom.
            'id': 'restore_without_a_draft',
            'storedOpenFile': '幽灵',
            'hasDraft': False,
            'restore': True,
        },
        {
            # The draft is only a snapshot; the file can be updated outside this browser. On entry the
            # remembered file must be RE-FETCHED by name so the latest server content loads, not the
            # stale draft (the seeded draft has no nodes; the loaded workflow does — proving the reload won).
            'id': 'reload_open_file_fetches_latest',
            'storedOpenFile': '甲流程',
            'hasDraft': True,
            'restore': True,
            'reload': True,
            'loadResponse': {'ok': True, 'workflow': opened},
        },
        {'id': 'save_named', 'currentFile': 'wf1', 'save': True},
        {
            # The camera a person panned to must ride into the saved file.
            'id': 'save_with_view',
            'currentFile': 'wf-view',
            'add': ['source'],
            'setView': {'panX': 60, 'panY': -25, 'zoom': 1.25},
            'save': True,
        },
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

    def test_a_parallel_headless_file_applies_its_settings_too(self, life):
        """The reader had only two of the four directions.

        `toWorkflowJSON` writes mode/headless/parallel/lang, but loadFromJSON looked
        only for ``mode === 'serial'`` and ``headless === false``. Opening a workflow
        saved as 并行 + 无头 therefore left the bar where the LAST file had it — and the
        next 保存 wrote those wrong values back over the file, so opening a workflow
        quietly rewrote its own settings.
        """
        r = dict(life['load_parallel_headless']['runState'])
        assert r['parallel'] is True, r
        assert r['headless'] is True, r

    def test_a_file_without_settings_changes_neither(self, life):
        """An absent block is "leave the user's choice alone", not "reset it"."""
        assert life['load_without_settings']['runState'] == []

    def test_opening_a_file_looks_through_the_camera_it_was_saved_with(self, life):
        """「保存时的视角跟读取得到的视角不一样」 was the complaint: the file knew
        where its author had been looking — the loader just never read it back.
        And the draft re-saved after the open must hold THAT camera, not the one
        the previous canvas had."""
        r = life['load_with_view']
        assert r['view'] == {'panX': -300, 'panY': -80, 'zoom': 0.8}, r['view']
        assert r['draftView'] == r['view'], 'the next refresh owes the same viewpoint'

    def test_a_file_without_a_camera_leaves_the_viewport_where_it_was(self, life):
        """Old files predate the field; opening one must not yank the camera the
        user is currently looking through just because the key is missing."""
        assert life['load_open']['view'] == {'panX': 0, 'panY': 0, 'zoom': 1}
        assert life['load_without_settings']['view'] == {'panX': 0, 'panY': 0, 'zoom': 1}

    def test_a_broken_camera_cannot_crash_the_open_or_unclamp_the_zoom(self, life):
        """A workflow file is hand-editable, so a string pan and a 999 zoom are
        expected input: the open still works and the values land inside the
        wheel's own clamp rather than being believed."""
        r = life['load_with_broken_view']
        assert r['view']['zoom'] == 3, r['view']
        assert r['view']['panX'] == 0, 'a non-number pan is not applied'

    def test_saving_a_workflow_carries_the_camera_into_the_file(self, life):
        r = life['save_with_view']
        body = json.loads(r['fetches'][0]['body'])
        assert body['workflow']['settings']['view'] == {'panX': 60, 'panY': -25, 'zoom': 1.25}, body['workflow'][
            'settings'
        ]

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
        # 新建 is the ONLY thing that starts a new file: it must also forget the open-file
        # record, so the next reload does not resurrect the file the user just abandoned.
        assert r['openFileStored'] is None, '新建 must clear the persisted open-file record'

    def test_saving_a_named_workflow_posts_its_name_and_canvas(self, life):
        r = life['save_named']
        assert [f['url'] for f in r['fetches']] == ['/api/workflow/save']
        body = json.loads(r['fetches'][0]['body'])
        assert body['name'] == 'wf1'
        assert r['currentFile'] == 'wf1'
        assert r['openFileStored'] == 'wf1', 'a save records the file so a reload reopens it'

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
        assert r['openFileStored'] == '我的流程', 'opening records the file for the next reload'
        assert [n['title'] for n in r['nodes']] == ['抓取微博', '清洗', 'Output']
        assert any(f['url'].startswith('/api/workflow/load') for f in r['fetches'])

    def test_a_reload_reopens_the_file_the_draft_belongs_to(self, life):
        """After a refresh or a backend restart the boot `openFile` step restores the persisted
        name, so the canvas reopens as the SAME saved file — not a new one — and runName() (the
        key every preview/chart/export/resume probe uses) is correct without a name node."""
        r = life['restore_after_reload']
        assert r['currentFile'] == '甲流程'
        assert r['openFileStored'] == '甲流程'

    def test_an_empty_browser_restores_no_file(self, life):
        """A fresh browser has no draft, so it must not adopt a leftover name: claiming a file
        with nothing on screen would attribute the next Save to a workflow the user never loaded."""
        r = life['restore_without_a_draft']
        assert r['currentFile'] is None, 'no draft means no reopened file'
        assert r['draftStored'] is None

    def test_entry_reloads_the_open_files_latest_content(self, life):
        """The remembered draft is a snapshot; the file may have changed outside this browser. On
        entry the open file is RE-FETCHED by name so the latest server content loads — the seeded
        draft has no nodes, so seeing the server's three nodes proves the reload (not the draft) won."""
        r = life['reload_open_file_fetches_latest']
        assert r['currentFile'] == '甲流程'
        assert any(f['url'].startswith('/api/workflow/load') for f in r['fetches']), 'entry must re-fetch the open file'
        assert [n['title'] for n in r['nodes']] == ['抓取微博', '清洗', 'Output'], (
            'the server content loads, not the stale draft'
        )

    def test_a_failed_open_leaves_the_current_canvas_and_name_intact(self, life):
        r = life['open_missing']
        assert r['currentFile'] == 'old-name', 'a failed open must not forget what is on screen'
        assert len(r['nodes']) == 1, 'the pre-existing canvas must survive untouched'
        assert any('loadfail' in msg for msg in r['toasts'])

    def test_a_node_is_never_looked_up_by_dom_id(self):
        """`addNode` makes the node's id its element id, and the ids a workflow file
        carries are adopted as they are — so `getElementById(<node id>)` is a question
        about the PAGE, not about the node: a node called `status-zoom` made
        `deleteNode` and the undo path remove the status bar itself, and the geometry
        reads measured whatever element got there first. The DOM stub cannot express
        the collision (its registry lets the later element win, a browser keeps the
        first), so the rule is pinned where it is written: every node lookup goes
        through `canvas._nodeEl`, and no call in the file takes a variable id.
        """
        source = (JS_DIR / 'canvas.js').read_text(encoding='utf-8')
        by_variable = re.findall(r"getElementById\(\s*(?!['\"])[^)]*\)", source)
        assert by_variable == [], f'node lookups must go through _nodeEl: {by_variable}'
        assert source.count('this._nodeEl(') >= 8, 'the helper exists but nothing uses it'

    def test_opening_a_file_without_a_node_list_changes_nothing(self, life):
        """The server answered ok for a JSON file that is not a workflow. Loading
        used to clear the canvas FIRST and then die on the missing node list, so a
        stray file cost the user their unsaved work and said only 'load failed'."""
        r = life['open_file_without_nodes']
        assert len(r['nodes']) == 1, 'the canvas on screen must survive the bad file'
        assert r['currentFile'] == 'good-name', 'the next Save must not overwrite the junk file as if it were loaded'
        assert any('toast.workflowFileInvalid' in msg for msg in r['toasts']), r['toasts']


class TestCanvasDisable:
    """The canvas mirror of the effective graph: grey-out and run-naming agree with the backend."""

    def test_disabling_a_head_node_starves_its_whole_chain(self, state):
        r = state['disable_head_cascades']
        assert r['disableStates']['name-2'] == 'off', 'the switched-off head reads as disabled'
        assert r['disableStates']['src-2'] == 'starved', 'the box that lost its only input starves'
        assert r['disableStates']['name-1'] == 'on' and r['disableStates']['out-1'] == 'on', (
            'the live workflow is untouched'
        )
        assert r['effective'] == ['name-1', 'out-1', 'src-1'], r['effective']
        assert r['dclasses']['name-2']['off'] is True and r['dclasses']['name-2']['starved'] is False
        assert r['dclasses']['src-2']['starved'] is True and r['dclasses']['src-2']['off'] is False

    def test_a_join_survives_on_one_live_branch(self, state):
        r = state['fan_in_keeps_join']
        assert r['disableStates']['sa'] == 'off'
        assert r['disableStates']['sb'] == 'on'
        assert r['disableStates']['j'] == 'on', 'disabling ONE upstream must not kill a fan-in node'
        assert 'j' in r['effective']

    def test_a_disabled_type_takes_its_whole_chain(self, state):
        r = state['type_off_starves_child']
        assert r['disableStates']['s'] == 'off' and r['disableStates']['p'] == 'starved', r['disableStates']
        assert r['effective'] == [], 'nothing survives when every source type is off'
        assert r['savedDisabledTypes'] == ['source'], 'the type set persists into the saved state'

    def test_toggling_a_node_off_flips_its_switch(self, state):
        r = state['toggle_flips_enabled']
        assert r['disableStates']['node-1'] == 'off'
        assert r['effective'] == []
        assert r['savedDisabledTypes'] == []
        flipped = next(n for n in r['nodes'] if n['id'] == 'node-1')
        assert flipped['params'].get('enabled') is False, 'the switch lives in params.enabled (survives save/undo)'

    def test_toggle_type_off_disables_every_box_of_that_kind(self, state):
        r = state['type_toggle_off']
        # node-1 is the source (type off), node-2 the process (its own type stays on).
        assert r['disableStates']['node-1'] == 'off', 'the whole source type is switched off'
        assert r['disableStates']['node-2'] == 'on', 'an unrelated type is untouched'
        assert r['effective'] == ['node-2']
        assert r['savedDisabledTypes'] == ['source'], 'the type set persists into the saved state'
        # The type toggle never edits the node's own switch — so turning the type back on restores
        # each node to its individual enabled state.
        src = next(n for n in r['nodes'] if n['id'] == 'node-1')
        assert 'enabled' not in src['params'], 'toggleTypeDisabled must not write params.enabled'

    def test_a_newly_added_node_comes_in_enabled(self, state):
        """The add-time decision the user settled on: a dragged node is ON by default
        (no dialog), and the header power button is the one-toggle away from off. If
        addNode ever started writing enabled: False — or the effective-graph mirror
        read an absent switch as off — every freshly dragged node would vanish from
        its own workflow on arrival."""
        r = state['add_defaults_on']
        assert r['disableStates']['node-1'] == 'on', r['disableStates']
        assert r['effective'] == ['node-1']
        assert r['dclasses']['node-1']['off'] is False

    def test_the_draft_and_the_file_carry_the_camera_and_undo_history_does_not(self, state):
        """适应/自动排布 arranged the VIEW, not just the boxes.

        The draft must hold the camera (or a refresh opens at a viewpoint nobody
        chose), the serialized file must hold it too (or the exported workflow
        forgets how its author left it) — while the undo stack must NOT: Ctrl+Z
        rewinds a node, not a look, and a camera in every snapshot would also turn
        every pan into an undo step and flood the 50-deep stack with drags.
        """
        r = state['draft_and_file_carry_the_camera']
        assert r['view'] == {'panX': 120, 'panY': -40, 'zoom': 1.5}, r['view']
        assert r['draftView'] == r['view'], 'a refresh must come back to this viewpoint'
        assert r['serializedView'] == r['view'], 'the saved/exported file carries the view it was arranged behind'
        assert r['draftHasViewKey'] is True
        assert r['modelHasView'] is False, 'getState is the model snapshot; the camera lives beside it'
        assert r['historyHasView'] is False, 'Ctrl+Z must not rewind the camera'

    def test_an_undo_rearranges_nodes_without_yanking_the_viewport(self, state):
        r = state['undo_leaves_the_camera']
        assert [n['id'] for n in r['nodes']] == [], 'the undo itself must still have removed the node'
        assert r['view'] == {'panX': 500, 'panY': 60, 'zoom': 2}, 'the camera the user set survived the rewind'

    def test_a_restored_draft_reapplies_its_camera_and_zero_is_a_position(self, state):
        """Two loss paths the same scenario used to hide: the camera was nowhere in
        the draft, and a node whose saved x or y was exactly 0 hit the `x || random`
        fallback and landed somewhere else — routine right after 自动排布 centers a
        layout."""
        r = state['restored_draft_moves_the_camera']
        assert r['view'] == {'panX': -70, 'panY': 15, 'zoom': 0.5}, r['view']
        assert r['elpos']['node-1'] == {'left': '0px', 'top': '0px'}, 'x=0 is a position, not an absence'
