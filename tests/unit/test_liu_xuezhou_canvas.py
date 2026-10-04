"""The 刘学州 canvases keep their intertopic-map bubbles Chinese.

These files are authored work in `data/workflows/` (versioned on purpose). Every 主题距离图 node
must read its bubble label from a 概括 column produced by a ``topic_label`` node sitting BETWEEN the
``topic_map`` data node and the chart — otherwise the figure draws ``Topic-1`` codes a reader cannot
interpret (the exact complaint the canvas had to answer). The test pins that wiring so a future edit
cannot silently drop the label path back to raw codes, and pins that the two per-corpus canvases stay
structurally in lockstep (they differ only by upload datasets and the corpus column names).

Nothing here runs a workflow or reads a dataset: it checks the saved graph's shape only, which is the
part that must not drift.
"""

import json
from pathlib import Path

import pytest

from engine.workflow import WorkflowEngine

REPO = Path(__file__).resolve().parents[2]
POST = REPO / 'data/workflows/刘学州-情感演化分析.json'
COMMENT = REPO / 'data/workflows/刘学州-评论-情感演化分析.json'
CANVASES = [POST, COMMENT]

# (topic_map data node, the topic_label inserted after it, the chart node it feeds) — per phase.
MAP_CHAINS = [
    ('node-40', 'node-124', 'node-41'),
    ('node-48', 'node-125', 'node-49'),
    ('node-74', 'node-126', 'node-75'),
    ('node-81', 'node-127', 'node-82'),
]


def _load(path):
    return json.loads(path.read_text(encoding='utf-8'))


@pytest.mark.parametrize('path', CANVASES, ids=['post', 'comment'])
def test_canvas_loads_and_validates(path):
    errors = WorkflowEngine(_load(path), None).validate()
    assert errors == [], f'{path.name} does not validate: {errors}'


@pytest.mark.parametrize('path', CANVASES, ids=['post', 'comment'])
def test_every_intertopic_map_reads_a_chinese_label(path):
    wf = _load(path)
    nodes = {n['id']: n for n in wf['nodes']}
    edges = {(c['from'], c['to']) for c in wf['connections']}
    for data_id, label_id, chart_id in MAP_CHAINS:
        assert nodes[label_id]['params']['operation'] == 'topic_label'
        assert nodes[label_id]['params']['label_summary_col'] == '主题概括'
        assert (data_id, label_id) in edges and (label_id, chart_id) in edges
        assert nodes[chart_id]['params']['label_field'] == '主题概括', f'{chart_id} bubble label is not Chinese'
        assert (data_id, chart_id) not in edges, f'{chart_id} still reads raw {data_id} (Topic-N codes)'


@pytest.mark.parametrize('path', CANVASES, ids=['post', 'comment'])
def test_raw_distance_export_still_reads_unlabelled_data(path):
    # node-45 exports the numeric distance table; it must keep reading node-40 directly, not the
    # labelled copy, or the CSV would carry a 主题概括 column the export never asked for.
    edges = {(c['from'], c['to']) for c in _load(path)['connections']}
    assert ('node-40', 'node-45') in edges


def test_the_two_canvases_stay_in_lockstep():
    """Identical except uploads and the per-corpus text/time columns (正文↔评论内容, 发布时间↔评论时间).

    Mirrors the checker in ``data/workflows/README.md``: upload params, the corpus column names, node
    x/y and the canvas name are not content; everything else must match one-for-one, so the new
    topic_label nodes have to appear in both files identically or this fails.
    """

    def norm(path):
        w = _load(path)
        for n in w['nodes']:
            if n['type'] == 'upload':
                n['params'] = {'u': 1}
            pr = n['params']
            if n['type'] == 'process' and pr.get('operation') == 'clean':
                pr['text_column'] = 'TEXT'
            if n['type'] == 'analysis' and pr.get('operation') in ('extract_time', 'bin_time'):
                pr['column'] = 'TIME'
            # Per-corpus prose legitimately differs (发帖量↔评论量, filenames, event peaks):
            # the two canvases measure different data, so their labels/numbers may not match;
            # what MUST match is the structure — ids, types, operations, connections, and every
            # method parameter. Blanking prose here keeps the lockstep test about structure.
            n['title'] = 'T'
            for key in ('title', 'filename', 'annotations'):
                if key in pr:
                    pr[key] = 'P'
            n.pop('x', None)
            n.pop('y', None)
        w.get('settings', {}).pop('view', None)
        w['name'] = 'X'
        return json.dumps(w, sort_keys=True, ensure_ascii=False)

    assert norm(POST) == norm(COMMENT)


def test_the_two_canvases_share_one_phase_boundary_set():
    """The five-stage periodization is one event, so both corpora cut it at the SAME dates."""
    edges = '2022-01-16, 2022-01-24, 2022-01-29, 2022-02-26, 2022-03-25, 2022-04-06'
    for path in CANVASES:
        w = _load(path)
        node12 = next(n for n in w['nodes'] if n['id'] == 'node-12')
        assert node12['params']['phase_edges'] == edges, f'{path.name} drifted from the shared boundaries'


def test_the_event_window_tail_is_cut_before_the_daily_chart():
    """Both canvases drop out-of-phase days (the comment corpus runs to 2026) before 每日图."""
    for path in CANVASES:
        w = _load(path)
        edges = {(c['from'], c['to']) for c in w['connections']}
        assert ('node-12', 'node-128') in edges and ('node-128', 'node-13') in edges
        assert ('node-12', 'node-13') not in edges, 'the daily series must pass through the cap'
        cap = next(n for n in w['nodes'] if n['id'] == 'node-128')
        assert cap['params']['column'] == '阶段' and cap['params']['op'] == 'not_null'


def test_the_comment_canvas_is_labelled_as_comments():
    """Item the copy-paste left wrong: the comment canvas spoke of 发帖量 and shared filenames."""
    w = _load(COMMENT)
    nodes = {n['id']: n for n in w['nodes']}
    assert '评论量' in nodes['node-14']['params']['title'], '图2 must read 每日评论量, not 发帖量'
    assert '评论量' in nodes['node-17']['params']['title'], '图3 must read 各阶段评论量'
    for n in w['nodes']:
        if n['type'] == 'output' and n['params'].get('operation') == 'save':
            assert n['params']['filename'].startswith('刘学州-评论-'), f'{n["id"]} filename not namespaced'
    # and the post canvas must NOT have been dragged into the rename
    p = _load(POST)
    pnodes = {n['id']: n for n in p['nodes']}
    assert '发帖量' in pnodes['node-14']['params']['title']
    for n in p['nodes']:
        if n['type'] == 'output' and n['params'].get('operation') == 'save':
            assert n['params']['filename'].startswith('刘学州-') and not n['params']['filename'].startswith(
                '刘学州-评论-'
            )
