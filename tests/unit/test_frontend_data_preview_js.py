"""The Data Preview panel — ``dataPreview`` in ``workflow.js`` — row by row.

The panel is the only place a user reads the rows a node actually produced, and
before these cases nothing had executed it: not the limit it asks the server for
per output format, not the cursor ``prevPage``/``nextPage`` move, not the table
``_render`` writes, not the answer it gives an empty result.

The markup is the real ``#data-preview-panel`` block cut out of ``index.html``, so
the ids the render path writes into are the ids the page declares, and a cell is
read back as an element (``textContent`` and child count), not as a substring of
``innerHTML`` — the stub parses the markup the product writes, which is what makes
"this value arrived as text, not as live markup" an observation.

The wording assertions compare against ``I18n.t(...)`` evaluated inside the same
sandbox in the same language (the ``catalog`` of each report), never a pasted
sentence: the panel speaks both languages and a pasted Chinese label would go stale
the next time the catalog is edited.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
INDEX = REPO / 'backend' / 'static' / 'index.html'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_data_preview.mjs'

PANEL_IDS = [
    'data-preview-panel',
    'data-preview-meta',
    'data-preview-table-wrap',
    'data-preview-pager',
    'data-preview-page-label',
]


def _panel_markup() -> str:
    """The `#data-preview-panel` element from index.html, braces balanced.

    Read from the page instead of being copied here: the point of the fixture is
    that the panel the product writes into is the panel the product ships.
    """
    src = INDEX.read_text(encoding='utf-8')
    start = src.index('<div id="data-preview-panel">')
    opens, closes = re.compile(r'<div\b'), re.compile(r'</div>')
    pos, depth = start, 0
    while True:
        opened, closed = opens.search(src, pos), closes.search(src, pos)
        if opened and (not closed or opened.start() < closed.start()):
            depth += 1
            pos = opened.end()
        elif closed:
            depth -= 1
            pos = closed.end()
            if depth == 0:
                return src[start:pos]
        else:
            raise AssertionError('the data-preview panel never closes in index.html')


def _rows(count, prefix='r'):
    return [{'标题': f'{prefix}{i}', 'n': i} for i in range(count)]


SCENARIOS = [
    # ── the table path ───────────────────────────────────────────────────────
    {
        'id': 'table-first-page',
        'payload': {'node_id': '3', 'workflow_name': '知乎 + 情感'},
        'columns': ['标题', 'n'],
        'rows': _rows(2),
        'steps': ['open'],
    },
    {
        'id': 'csv-format-is-a-table',
        'payload': {'node_id': '3', 'preview_format': 'csv'},
        'columns': ['标题'],
        'rows': _rows(1),
        'steps': ['open'],
    },
    {
        'id': 'no-format-is-a-table',
        'payload': {'dataset_id': 'ds-7'},
        'columns': ['标题'],
        'rows': _rows(1),
        'steps': ['open'],
    },
    # ── the text path ────────────────────────────────────────────────────────
    {
        'id': 'txt-format',
        'payload': {'node_id': '3', 'preview_format': 'txt'},
        'columns': ['标题', 'n'],
        'rows': _rows(2),
        'steps': ['open'],
    },
    {
        'id': 'json-format',
        'payload': {'node_id': '3', 'preview_format': 'json'},
        'columns': ['标题', 'n'],
        'rows': _rows(2),
        'steps': ['open'],
    },
    # ── the cursor ───────────────────────────────────────────────────────────
    {
        'id': 'paging',
        'payload': {'node_id': '3'},
        'columns': ['标题', 'n'],
        'rows': _rows(120),
        'steps': ['open', 'next', 'next', 'next', 'prev', 'prev', 'prev'],
    },
    {
        'id': 'shorter-than-a-page',
        'payload': {'node_id': '3'},
        'columns': ['标题'],
        'rows': _rows(3),
        'steps': ['open', 'next', 'prev'],
    },
    {
        'id': 'exact-page-boundary',
        'payload': {'node_id': '3'},
        'columns': ['标题'],
        'rows': _rows(100),
        'steps': ['open', 'next', 'next'],
    },
    {
        'id': 'reopen-from-another-node',
        'payload': {'node_id': '3'},
        'columns': ['标题'],
        'rows': _rows(120),
        'steps': ['open', 'next', {'do': 'open', 'payload': {'dataset_id': 'ds-9'}}],
    },
    {
        'id': 'opened-twice-one-handle',
        'payload': {'node_id': '3'},
        'columns': ['标题'],
        'rows': _rows(1),
        'steps': ['open', {'do': 'open', 'payload': {'node_id': '3'}}],
    },
    {
        'id': 'closed-again',
        'payload': {'node_id': '3'},
        'columns': ['标题'],
        'rows': _rows(1),
        'steps': ['open', 'close'],
    },
    # ── empty answers ────────────────────────────────────────────────────────
    {
        'id': 'empty-table',
        'payload': {'node_id': '3'},
        'columns': [],
        'rows': [],
        'steps': ['open'],
    },
    {
        'id': 'empty-text',
        'payload': {'node_id': '3', 'preview_format': 'json'},
        'columns': [],
        'rows': [],
        'steps': ['open'],
    },
    # ── refused and unreachable ──────────────────────────────────────────────
    {
        'id': 'server-refused',
        'payload': {'node_id': '3'},
        'fails': True,
        'error': 'node 3 has no recorded rows',
        'steps': ['open'],
    },
    {
        'id': 'transport-died',
        'payload': {'node_id': '3'},
        'transport': 'reject',
        'transportError': 'network is unreachable',
        'steps': ['open'],
    },
    # ── values that are not words ────────────────────────────────────────────
    {
        'id': 'hostile-cells',
        'payload': {'node_id': '3'},
        'columns': ['<b>title</b>', 'note & co'],
        'rows': [
            {'<b>title</b>': '<img src=x onerror=alert(1)>', 'note & co': 'a "quoted" & <script>value</script>'},
            {'<b>title</b>': None, 'note & co': 0},
            {'<b>title</b>': 'plain'},
        ],
        'steps': ['open'],
    },
    # ── language ─────────────────────────────────────────────────────────────
    {
        'id': 'language-of-the-meta-line',
        'payload': {'node_id': '3'},
        'columns': ['标题'],
        'rows': _rows(2),
        'lang': 'zh',
        'steps': ['open', {'do': 'lang', 'value': 'en'}, 'open'],
    },
]

SCENARIO_IDS = [sc['id'] for sc in SCENARIOS]


@pytest.fixture(scope='module')
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('data-preview')
    payload = tmp / 'scenarios.json'
    payload.write_text(json.dumps(SCENARIOS, ensure_ascii=False), encoding='utf-8')
    markup = tmp / 'panel.html'
    markup.write_text(_panel_markup(), encoding='utf-8')
    proc = run_node(str(HARNESS), str(JS_DIR), str(payload), str(markup))
    assert proc.returncode == 0, f'harness failed: {proc.stderr}'
    report = json.loads(proc.stdout)
    assert set(report) == set(SCENARIO_IDS), 'a scenario did not report'
    return report


def case(world, id_):
    return world[id_]


def offsets(report):
    """The `offset` of every request the panel made, in order."""
    return [r['body']['offset'] for r in report['requests']]


def pages(trace):
    return [step['after']['pageLabel'] for step in trace]


# ─── the fixture itself ───────────────────────────────────────────────────


class TestPanelMarkupIsThePages:
    def test_the_panel_the_product_writes_into_is_the_panel_index_html_declares(self):
        """Every id the render path touches has to exist on the page, or the preview
        writes into a phantom and the user sees an empty box."""
        markup = _panel_markup()
        for id_ in PANEL_IDS:
            assert f'id="{id_}"' in markup, f'{id_} is gone from index.html'
        assert 'class="panel-header"' in markup, 'the drag handle the panel expects is gone'


# ─── which limit, for which format ────────────────────────────────────────


class TestLimitFollowsTheFormat:
    def test_a_tabular_answer_is_asked_for_a_screen_of_rows(self, world):
        body = case(world, 'table-first-page')['requests'][0]['body']
        assert body['limit'] == 50
        assert body['offset'] == 0

    def test_the_panel_posts_the_payload_it_was_given_plus_its_own_cursor(self, world):
        """`workflow_name` is how a preview still finds its rows after a refresh, so
        the envelope must not lose the identity it was handed."""
        report = case(world, 'table-first-page')
        request = report['requests'][0]
        assert request['method'] == 'POST'
        assert request['url'] == '/api/data/preview'
        assert request['body'] == {'node_id': '3', 'workflow_name': '知乎 + 情感', 'limit': 50, 'offset': 0}

    @pytest.mark.parametrize('scenario, limit', [('txt-format', 5000), ('json-format', 5000)])
    def test_a_text_answer_is_asked_for_the_whole_thing(self, world, scenario, limit):
        """A text view has no pager, so it must be fetched wide in one go — the 50 a
        table wants would show a fifth of a report and offer no way to the rest."""
        assert case(world, scenario)['requests'][0]['body']['limit'] == limit

    @pytest.mark.parametrize('scenario', ['csv-format-is-a-table', 'no-format-is-a-table'])
    def test_every_other_format_keeps_the_paged_table(self, world, scenario):
        report = case(world, scenario)
        assert report['requests'][0]['body']['limit'] == 50
        assert report['world']['table'] is not None


# ─── the cursor ───────────────────────────────────────────────────────────


class TestPaging:
    def test_the_cursor_walks_the_pages_and_back_again(self, world):
        """The whole conversation of `open, next, next, next, prev, prev, prev` over
        120 rows at 50 a page: four of those seven steps ask the server for
        something, and the two clamped ones ask for nothing at all."""
        report = case(world, 'paging')
        assert offsets(report) == [0, 50, 100, 50, 0]

    def test_the_last_page_is_the_end_of_the_line(self, world):
        """Offset 150 of a 120-row set would answer with nothing and leave the user
        staring at an empty table they cannot page back out of."""
        at_end = case(world, 'paging')['trace'][3]['after']
        assert at_end['state']['offset'] == 100
        assert at_end['state']['total'] == 120
        assert len(case(world, 'paging')['trace'][3]['requests']) == 3, 'a clamped next still asked'

    def test_prev_walks_back_and_stops_at_the_first_page(self, world):
        report = case(world, 'paging')
        assert report['world']['state']['offset'] == 0
        assert len(report['requests']) == 5, 'a clamped prev still asked the server'

    def test_the_rows_shown_are_the_rows_the_cursor_asked_for(self, world):
        """120 rows, third page, 50 a page: twenty. A render that dumped the whole
        answer would look identical on page one and lie on every later one."""
        trace = case(world, 'paging')['trace']
        assert [len(step['after']['table']['rows']) for step in trace[:3]] == [50, 50, 20]
        assert trace[2]['after']['table']['rows'][0][0]['text'] == 'r100'

    def test_the_page_label_counts_pages_and_not_rows(self, world):
        assert pages(case(world, 'paging')['trace']) == [
            '1 / 3',
            '2 / 3',
            '3 / 3',
            '3 / 3',
            '2 / 3',
            '1 / 3',
            '1 / 3',
        ]

    def test_a_result_shorter_than_a_page_moves_nowhere(self, world):
        report = case(world, 'shorter-than-a-page')
        assert offsets(report) == [0]
        assert report['world']['state']['offset'] == 0
        assert report['world']['pageLabel'] == '1 / 1'

    def test_an_exact_multiple_of_a_page_does_not_open_a_blank_one(self, world):
        """100 rows at 50 a page is two pages; a `<` vs `<=` here is a third page of
        nothing, which is the report this case exists for."""
        report = case(world, 'exact-page-boundary')
        assert offsets(report) == [0, 50]
        assert pages(report['trace']) == ['1 / 2', '2 / 2', '2 / 2']

    def test_opening_another_nodes_preview_starts_at_its_first_page(self, world):
        """The cursor belongs to the answer, not to the panel: a stale offset would
        show page three of a dataset with two, i.e. an empty table."""
        report = case(world, 'reopen-from-another-node')
        assert offsets(report) == [0, 50, 0]
        assert report['requests'][2]['body'] == {'dataset_id': 'ds-9', 'limit': 50, 'offset': 0}

    def test_closing_the_panel_does_not_undo_the_render(self, world):
        report = case(world, 'closed-again')
        assert 'open' not in report['world']['panelClass']


# ─── what the render writes ───────────────────────────────────────────────


class TestTableRender:
    def test_the_header_row_is_the_servers_columns_in_order(self, world):
        table = case(world, 'table-first-page')['world']['table']
        assert [h['text'] for h in table['headers']] == ['标题', 'n']

    def test_every_row_has_one_cell_per_column(self, world):
        table = case(world, 'table-first-page')['world']['table']
        assert len(table['rows']) == 2
        assert [[c['text'] for c in row] for row in table['rows']] == [['r0', '0'], ['r1', '1']]

    def test_the_meta_line_states_rows_and_columns(self, world):
        report = case(world, 'table-first-page')
        words = report['catalog']
        assert report['world']['meta'] == f'{words["rows"]}: 2  |  {words["columns"]}: 2'

    def test_the_loading_placeholder_makes_way_for_the_answer(self, world):
        report = case(world, 'table-first-page')
        assert report['trace'][0]['after']['spinner'] is False
        assert report['world']['pagerDisplay'] == '', 'the pager stayed hidden from a previous preview'

    def test_the_meta_line_counts_the_dataset_not_the_page(self, world):
        """The user reads "Rows: 120" as the size of what was collected; the page in
        front of them is only 20 of those rows, and on the last page the two numbers
        differ the most."""
        third_page = case(world, 'paging')['trace'][2]['after']
        words = case(world, 'paging')['trace'][2]['words']
        assert len(third_page['table']['rows']) == 20
        assert third_page['meta'] == f'{words["rows"]}: 120  |  {words["columns"]}: 2'

    def test_the_drag_and_resize_setup_happens_once_per_panel(self, world):
        """`_uiInit` brackets the setup, and the tell is not the handle element
        (`makeResizable` reuses one it finds) but the header: `makeDraggable` hangs
        another mousedown listener on it every time it is called, so a second render
        would start the panel dragging twice per press."""
        report = case(world, 'opened-twice-one-handle')
        assert report['world']['uiInit'] == '1'
        assert report['world']['resizeHandles'] == 1
        assert report['world']['dragListeners'] == 1


class TestTextRender:
    def test_a_txt_answer_is_one_tab_separated_line_per_row(self, world):
        report = case(world, 'txt-format')
        assert report['world']['prePresent'] is True
        assert report['world']['preText'] == 'r0\t0\nr1\t1'
        assert report['world']['table'] is None

    def test_a_json_answer_is_the_rows_themselves(self, world):
        """The text view dumps the row objects the server sent, which is the whole
        point of offering JSON: a column list the table view follows is not a
        restriction here."""
        report = case(world, 'json-format')
        assert json.loads(report['world']['preText']) == _rows(2)

    def test_a_text_answer_hides_the_pager_it_cannot_use(self, world):
        """There is one page by construction, so the controls would only offer a
        cursor that has nowhere to go."""
        assert case(world, 'txt-format')['world']['pagerDisplay'] == 'none'


# ─── empty and refused ────────────────────────────────────────────────────


class TestNothingAndRefused:
    def test_an_empty_answer_is_an_empty_table_and_not_a_failure(self, world):
        """`ok: true` with no rows is the server saying "that node produced nothing",
        which is a fact the user should be able to see — not a red toast that hides
        the difference between an empty result and a broken request."""
        report = case(world, 'empty-table')
        words = report['catalog']
        toast = report['world']['toast']
        assert toast in ('', None), f'an empty answer announced a failure: {toast!r}'
        assert report['world']['table'] is not None
        assert report['world']['table']['rows'] == []
        assert report['world']['table']['headers'] == []
        assert report['world']['meta'] == f'{words["rows"]}: 0  |  {words["columns"]}: 0'
        assert report['world']['pageLabel'] == '1 / 1', 'zero rows still have one page to show'
        assert 'open' in report['world']['panelClass'], 'the panel refused to open on an empty answer'

    def test_an_empty_text_answer_renders_an_empty_block(self, world):
        """An empty JSON answer is the literal `[]` — the shape the server actually
        sent — and not a failure notice; nothing was invented and nothing thrown."""
        report = case(world, 'empty-text')
        assert report['world']['prePresent'] is True
        assert report['world']['preText'] == '[]'
        assert report['world']['table'] is None
        assert report['world']['toast'] in ('', None)

    def test_a_refusal_is_reported_with_the_servers_reason(self, world):
        report = case(world, 'server-refused')
        toast = report['world']['toast']
        assert toast.startswith(report['catalog']['failed']), toast
        assert 'node 3 has no recorded rows' in toast, 'the reason the server gave was dropped'
        assert report['world']['table'] is None, 'nothing was rendered over the refusal'

    def test_a_dead_transport_names_the_failure_and_leaves_no_table(self, world):
        """The catch is the only thing between a refused connection and a panel that
        never answers; it has to say so, and it must not throw into the click."""
        report = case(world, 'transport-died')
        toast = report['world']['toast']
        assert toast.startswith(report['catalog']['failed'])
        assert 'network is unreachable' in toast
        assert report['world']['table'] is None


# ─── values that are not words ────────────────────────────────────────────


class TestCellValues:
    def test_a_crawled_value_arrives_as_text_never_as_markup(self, world):
        """Comment and title fields carry HTML, and the panel is written with
        `innerHTML`. One un-escaped cell is the user's own page running a crawled
        site's script, so the check is on the rendered elements, not on a string."""
        report = case(world, 'hostile-cells')
        table = report['world']['table']
        assert [h['text'] for h in table['headers']] == ['<b>title</b>', 'note & co']
        assert all(h['kids'] == 0 for h in table['headers']), 'a column name became live markup'
        first = table['rows'][0]
        assert first[0]['text'] == '<img src=x onerror=alert(1)>'
        assert first[1]['text'] == 'a "quoted" & <script>value</script>'
        assert all(cell['kids'] == 0 for row in table['rows'] for cell in row)
        assert '<img' not in report['world']['wrapHtml'], 'an image tag reached the markup'
        assert '<script>' not in report['world']['wrapHtml']

    def test_an_absent_or_null_cell_is_empty_and_a_zero_is_a_zero(self, world):
        """A row without that key at all and a `null` both read as nothing; `0` is a
        figure the user came to read, and a truthiness test would blank it."""
        table = case(world, 'hostile-cells')['world']['table']
        assert [c['text'] for c in table['rows'][1]] == ['', '0']
        assert [c['text'] for c in table['rows'][2]] == ['plain', '']


# ─── language ─────────────────────────────────────────────────────────────


class TestLanguage:
    def test_the_meta_line_speaks_the_language_it_was_rendered_in(self, world):
        """The counts are stamped from the catalog at render time, so a line drawn in
        one language and a line drawn after a flip must not read the same — asserted
        against the catalog asked for those same words, never a pasted sentence."""
        report = case(world, 'language-of-the-meta-line')
        before, after = report['trace'][0], report['trace'][2]
        assert before['words']['rows'] != after['words']['rows'], 'the catalog has only one language'
        assert before['after']['meta'] == f'{before["words"]["rows"]}: 2  |  {before["words"]["columns"]}: 1'
        assert after['after']['meta'] == f'{after["words"]["rows"]}: 2  |  {after["words"]["columns"]}: 1'
