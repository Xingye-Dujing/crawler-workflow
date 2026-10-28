"""Tests for the Chart Studio hand-off endpoints.

The studio is an iframe that draws charts from tables the workflow already
has, so these three routes are all about *moving rows across the boundary
safely*:

* ``/api/studio/sources`` answers "can this node feed me a table *right now*?"
  and names the reason when it cannot — the picker greys the row out before the
  user clicks Load,
* ``/api/studio/dataset`` dumps a whole table (not a page) and says so when it
  quietly fell back to another node's result,
* ``/api/studio/save-image`` writes a client-rendered PNG into the export
  directory, which is the one place a test can prove a caller-chosen file name
  cannot escape that directory.

Nothing here touches the crawler, a model, or the network.
"""

import base64

import pytest

pytestmark = pytest.mark.api

# A payload with a real PNG signature; the handler stores bytes verbatim and
# never decodes them, so a header plus filler is enough to prove the write.
PNG_BYTES = b'\x89PNG\r\n\x1a\n' + bytes(range(64))
PNG_DATA_URL = 'data:image/png;base64,' + base64.b64encode(PNG_BYTES).decode('ascii')


def _sources(client, candidates):
    return client.post('/api/studio/sources', json={'candidates': candidates}).get_json()


class TestStudioSources:
    def test_every_candidate_gets_an_answer_with_a_reason(self, client, paste, app_module):
        good = paste([{'word': 'sea', 'freq': 3}, {'word': 'sun', 'freq': 1}], name='freq.csv')
        gone = paste([{'word': 'x'}], name='doomed.csv')
        assert client.delete(f'/api/data/datasets/{gone}').status_code == 200
        empty = paste([], name='nothing.csv')
        app_module.execution_state['results'] = {'node-live': [{'a': 1}, {'a': 2}, {'a': 3}]}

        body = _sources(
            client,
            [
                {'node_id': 'node-1', 'payload': {'dataset_id': good}},
                {'node_id': 'node-2', 'payload': {'node_id': 'node-live'}},
                {'node_id': 'node-3', 'payload': {'dataset_id': gone}},
                {'node_id': 'node-4', 'payload': {'dataset_id': empty}},
                {'node_id': 'node-5', 'payload': {'node_id': 'node-nobody'}},
                {'node_id': 'node-6', 'payload': None},
            ],
        )
        assert body['ok'] is True
        answers = {item['node_id']: item for item in body['sources']}
        assert len(answers) == 6

        assert answers['node-1']['available'] is True and answers['node-1']['rows'] == 2
        assert sorted(answers['node-1']['cols']) == ['freq', 'word']
        assert answers['node-2']['available'] is True and answers['node-2']['rows'] == 3
        assert answers['node-3']['available'] is False
        assert answers['node-3']['reason'] == 'stale_dataset'
        assert answers['node-3']['cols'] == []
        assert answers['node-4']['reason'] == 'empty'
        assert answers['node-5']['reason'] == 'no_result'
        assert answers['node-6']['reason'] == 'no_upstream'

    def test_a_missing_candidates_list_is_a_bad_request(self, client):
        response = client.post('/api/studio/sources', json={'candidates': 'node-1'})
        assert response.status_code == 400
        assert 'candidates list' in response.get_json()['error']

    def test_an_empty_candidate_list_answers_with_an_empty_list(self, client):
        assert _sources(client, []) == {'ok': True, 'sources': []}


class TestStudioDataset:
    def test_a_whole_table_arrives_without_pagination(self, client, paste):
        dataset_id = paste([{'n': i} for i in range(30)], name='tall.csv')
        body = client.post('/api/studio/dataset', json={'dataset_id': dataset_id}).get_json()
        assert body['ok'] is True
        assert body['columns'] == ['n']
        assert [row['n'] for row in body['rows']] == list(range(30))
        assert body['total_rows'] == 30
        assert body['truncated'] is False
        assert body['fallback'] is None

    def test_the_limit_caps_the_dump_and_says_so(self, client, paste):
        dataset_id = paste([{'n': i} for i in range(10)], name='cap.csv')
        body = client.post('/api/studio/dataset', json={'dataset_id': dataset_id, 'limit': 4}).get_json()
        assert len(body['rows']) == 4
        assert body['total_rows'] == 10
        assert body['truncated'] is True

    def test_a_dead_node_falls_back_to_whatever_has_data(self, client, app_module):
        """A freshly restarted server has no in-memory results; the studio then
        has to be told which node it actually got, not served an error."""
        app_module.execution_state['results'] = {'node-live': [{'a': 1}, {'a': 2}]}
        body = client.post('/api/studio/dataset', json={'node_id': 'node-dead'}).get_json()
        assert body['ok'] is True
        assert body['fallback'] == {'requested': 'node-dead', 'used': 'node-live'}
        assert body['total_rows'] == 2

    def test_no_table_at_all_is_reported_as_no_result(self, client):
        response = client.post('/api/studio/dataset', json={'node_id': 'node-dead'})
        body = response.get_json()
        assert body['ok'] is False
        assert body['code'] == 'no_result'
        assert 'No tabular result available for node: node-dead' in body['error']

    def test_several_sources_merge_and_each_one_is_reported(self, client, paste):
        first = paste([{'word': 'sea', 'freq': 3}, {'word': 'sun', 'freq': 1}], name='a.csv')
        second = paste([{'word': 'wind', 'freq': 8}], name='b.csv')
        # Every merged entry is a payload with its own node_id, not the
        # ``{'node_id', 'payload'}`` shape the picker sends to /sources.
        sources = [{'node_id': 'node-1', 'dataset_id': first}, {'node_id': 'node-2', 'dataset_id': second}]
        body = client.post('/api/studio/dataset', json={'sources': sources, 'merge': 'concat'}).get_json()
        assert body['ok'] is True
        assert body['merged'] is True
        assert body['merge_mode'] == 'rows'
        # Stacked below one another, so the column names are shared, not doubled.
        assert body['columns'] == ['freq', 'word']
        assert [row['word'] for row in body['rows']] == ['sea', 'sun', 'wind']
        assert [entry['ok'] for entry in body['sources']] == [True, True]
        assert [entry['rows'] for entry in body['sources']] == [2, 1]

    def test_side_by_side_merge_renames_colliding_columns(self, client, paste):
        first = paste([{'word': 'sea', 'freq': 3}], name='left.csv')
        second = paste([{'word': 'wind', 'freq': 8}], name='right.csv')
        sources = [{'dataset_id': first}, {'dataset_id': second}]
        body = client.post('/api/studio/dataset', json={'sources': sources, 'merge': 'side'}).get_json()
        assert body['merge_mode'] == 'side'
        # The studio binds series by name, so two ``freq`` columns would make
        # the second one unreachable.
        assert len(set(body['columns'])) == len(body['columns'])
        assert sorted(body['columns']) == ['freq', 'freq_2', 'word', 'word_2']

    def test_a_dead_source_is_skipped_not_fatal(self, client, paste):
        alive = paste([{'word': 'sea'}], name='alive.csv')
        sources = [{'node_id': 'node-1', 'dataset_id': alive}, {'node_id': 'node-2'}]
        body = client.post('/api/studio/dataset', json={'sources': sources}).get_json()
        assert body['ok'] is True
        report = {entry['node_id']: entry for entry in body['sources']}
        assert report['node-1']['ok'] is True
        assert report['node-2'] == {'node_id': 'node-2', 'ok': False, 'rows': 0, 'reason': 'no_result'}
        # One surviving frame is not a "merge", whatever the caller asked for.
        assert body['merged'] is False

    def test_a_single_element_source_list_behaves_like_one_node(self, client, paste):
        dataset_id = paste([{'word': 'sea'}], name='one.csv')
        body = client.post('/api/studio/dataset', json={'sources': [{'dataset_id': dataset_id}]}).get_json()
        assert body['ok'] is True
        assert 'merged' not in body
        assert body['fallback'] is None


class TestStudioSaveImage:
    def test_a_png_data_url_becomes_a_file_in_the_export_dir(self, client, data_root):
        body = client.post('/api/studio/save-image', json={'image': PNG_DATA_URL, 'name': 'likes-by-city'}).get_json()
        assert body['ok'] is True
        assert body['bytes'] == len(PNG_BYTES)
        # A suffix keeps two saves of the same chart from overwriting each other.
        assert body['filename'].startswith('likes-by-city-')
        assert body['filename'].endswith('.png')
        written = data_root / 'data' / 'exports' / body['filename']
        assert written.exists()
        assert written.read_bytes() == PNG_BYTES

    def test_saving_twice_never_reuses_a_file_name(self, client):
        first = client.post('/api/studio/save-image', json={'image': PNG_DATA_URL, 'name': 'same'}).get_json()
        second = client.post('/api/studio/save-image', json={'image': PNG_DATA_URL, 'name': 'same'}).get_json()
        assert first['filename'] != second['filename']

    def test_a_traversal_in_the_chart_name_stays_inside_the_export_dir(self, client, data_root):
        body = client.post('/api/studio/save-image', json={'image': PNG_DATA_URL, 'name': '../../evil'}).get_json()
        assert body['ok'] is True
        assert '\\' not in body['filename'] and '/' not in body['filename']
        assert (data_root / 'data' / 'exports' / body['filename']).exists()
        assert not (data_root / 'evil.png').exists()

    @pytest.mark.parametrize(
        ('image', 'expected'),
        [
            ('', 'image data URL'),
            ('data:image/gif;base64,AAAA', 'image data URL'),
            ('not a data url at all', 'image data URL'),
            # Padding only: a well formed URL whose payload decodes to nothing.
            ('data:image/png;base64,====', 'empty image'),
        ],
    )
    def test_a_payload_that_is_not_a_raster_image_is_refused(self, client, image, expected):
        response = client.post('/api/studio/save-image', json={'image': image})
        assert response.status_code == 400
        assert expected in response.get_json()['error']

    def test_base64_that_cannot_be_decoded_is_refused(self, client):
        response = client.post('/api/studio/save-image', json={'image': 'data:image/png;base64,A'})
        assert response.status_code == 400
        assert 'Could not parse' in response.get_json()['error']

    def test_an_oversized_image_is_refused(self, client, monkeypatch):
        import api.studio

        monkeypatch.setattr(api.studio, 'MAX_IMAGE_BYTES', 8)
        response = client.post('/api/studio/save-image', json={'image': PNG_DATA_URL})
        assert response.status_code == 400
        assert 'image too large' in response.get_json()['error']


SVG_GOOD = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="700">'
    '<path d="M0 0 L10 10" fill="#22557A"/><text x="4" y="8">数字治理</text></svg>'
)


class TestStudioSaveVector:
    def test_an_svg_chart_becomes_a_vector_file_in_the_export_dir(self, client, data_root):
        body = client.post('/api/studio/save-vector', json={'svg': SVG_GOOD, 'name': '知识图谱'}).get_json()
        assert body['ok'] is True
        assert body['filename'].startswith('知识图谱-')
        assert body['filename'].endswith('.svg')
        written = data_root / 'data' / 'exports' / body['filename']
        assert written.read_text(encoding='utf-8') == SVG_GOOD

    def test_the_leading_xml_declaration_is_accepted(self, client):
        body = client.post(
            '/api/studio/save-vector',
            json={'svg': '<?xml version="1.0" encoding="UTF-8"?>' + SVG_GOOD, 'name': 'x'},
        ).get_json()
        assert body['ok'] is True

    def test_saving_twice_never_reuses_a_file_name(self, client):
        first = client.post('/api/studio/save-vector', json={'svg': SVG_GOOD, 'name': 'same'}).get_json()
        second = client.post('/api/studio/save-vector', json={'svg': SVG_GOOD, 'name': 'same'}).get_json()
        assert first['filename'] != second['filename']

    def test_a_traversal_in_the_chart_name_stays_inside_the_export_dir(self, client, data_root):
        body = client.post('/api/studio/save-vector', json={'svg': SVG_GOOD, 'name': '../../evil'}).get_json()
        assert body['ok'] is True
        assert '/' not in body['filename'] and chr(92) not in body['filename']
        assert (data_root / 'data' / 'exports' / body['filename']).exists()
        assert not (data_root / 'evil.svg').exists()

    @pytest.mark.parametrize(
        ('markup', 'expected'),
        [
            ('', 'svg markup'),
            ('<div>not a chart</div>', '<svg'),
            # An SVG without its namespace is not an SVG document; browsers disagree with
            # whatever else parses it, and the file would open as a blank page.
            ('<svg width="10"><path/></svg>', 'xmlns'),
            (SVG_GOOD.replace('</svg>', ''), '</svg>'),
        ],
    )
    def test_markup_that_is_not_a_whole_svg_document_is_refused(self, client, markup, expected):
        response = client.post('/api/studio/save-vector', json={'svg': markup})
        assert response.status_code == 400
        assert expected in response.get_json()['error']

    @pytest.mark.parametrize(
        'payload',
        [
            '<svg xmlns="s"><script>alert(1)</script></svg>',
            '<svg xmlns="s"><rect onload="alert(1)"/></svg>',
            '<svg xmlns="s"><image href="http://evil/x.png"/></svg>',
            '<svg xmlns="s"><a xlink:href="javascript:alert(1)">x</a></svg>',
            '<!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="s"/>',
            '<svg xmlns="s"><foreignObject><div xmlns="http://www.w3.org/1999/xhtml">hi</div></foreignObject></svg>',
        ],
    )
    def test_markup_that_could_carry_a_script_is_refused_by_name(self, client, payload, data_root):
        """An .svg served from our own origin is a script tag with a filename. The refusal names
        what it found rather than quietly stripping it: a sanitized file that parses differently
        than the bytes the user inspected is worse than no file."""
        response = client.post('/api/studio/save-vector', json={'svg': payload, 'name': 'refused-chart'})
        assert response.status_code == 400
        assert 'SVG' in response.get_json()['error']
        assert not list((data_root / 'data' / 'exports').glob('refused-chart-*.svg'))

    def test_an_oversized_markup_is_refused_before_it_is_buffered_to_disk(self, client):
        huge = '<svg xmlns="s">' + ('<path d="M0 0"/>' * 600000) + '</svg>'
        response = client.post('/api/studio/save-vector', json={'svg': huge, 'name': 'x'})
        assert response.status_code == 400
        assert 'bytes' in response.get_json()['error']


LATEX_FIGURE = (
    r'\documentclass[border=6pt]{standalone}'
    '\n'
    r'\begin{document}'
    '\n'
    r'\begin{tikzpicture}\end{tikzpicture}'
    '\n'
    r'\end{document}'
    '\n'
)
LATEX_TABLE = (
    r'\documentclass[border=6pt]{standalone}'
    '\n'
    r'\begin{document}'
    '\n'
    r'\begin{tabular}{lr}\toprule 城市 & 分数 \\'
    '\n'
    r'\bottomrule\end{tabular}'
    '\n'
    r'\end{document}'
    '\n'
)


def _register(data_root, name, kind='latex', run_id='run-pdf', node_id='node-2', content=None):
    """File a source in the export folder AND in the run ledger, the way a visualize node does."""
    from stores import get_run_store

    exports = data_root / 'data' / 'exports'
    exports.mkdir(parents=True, exist_ok=True)
    (exports / name).write_text(content or LATEX_FIGURE, encoding='utf-8')
    assert get_run_store().record_file(run_id, node_id, name, kind)
    return run_id, node_id


@pytest.fixture
def fake_xelatex(monkeypatch):
    """The compiler is the user's own MiKTeX, so nothing here shells out: `find_xelatex` and
    ``subprocess.run`` are stood in for, exactly as ``test_compile_api`` does."""
    import os
    from types import SimpleNamespace

    import services.charts.pdf as latex_compile

    monkeypatch.setattr(latex_compile, 'find_xelatex', lambda: 'xelatex')

    def run(command, *args, **kwargs):
        outdir = None
        for i, arg in enumerate(command):
            if arg == '-output-directory':
                outdir = command[i + 1]
        if outdir:
            with open(os.path.join(outdir, 'main.pdf'), 'wb') as handle:
                handle.write(b'%PDF-1.4 fake')
        return SimpleNamespace(returncode=0, stderr=b'')

    monkeypatch.setattr(latex_compile.subprocess, 'run', run)
    return latex_compile


class TestStudioSavePdf:
    def test_a_registered_latex_source_compiles_into_a_pdf_next_to_it(self, client, data_root, fake_xelatex):
        run_id, node_id = _register(data_root, '图23-a1b2.txt')
        body = client.post('/api/studio/save-pdf', json={'name': '图23-a1b2.txt'}).get_json()
        assert body['ok'] is True, body
        assert body['filename'] == '图23-a1b2.pdf'
        assert body['run_id'] == run_id and body['node_id'] == node_id
        written = data_root / 'data' / 'exports' / body['filename']
        assert written.read_bytes().startswith(b'%PDF')
        # Recorded under the SAME run and node, so the export panel and 智能清除 see it.
        from stores import get_run_store

        rows = get_run_store().files_for_run(run_id, node_id, 'pdf')
        assert [row['name'] for row in rows] == ['图23-a1b2.pdf']

    def test_the_figure_and_its_three_line_table_become_one_document(
        self, client, data_root, fake_xelatex, monkeypatch
    ):
        _register(data_root, 'fig-9.txt')
        _register(data_root, 'fig-9-table.txt', kind='latex_table', content=LATEX_TABLE)
        seen = {}

        def capture(tex, out_name, export_dir):
            seen['tex'] = tex
            return {'pdf_file': out_name, 'pdf_bytes': 7}, out_name

        monkeypatch.setattr(fake_xelatex, 'compile_pdf', capture)
        body = client.post('/api/studio/save-pdf', json={'name': 'fig-9.txt'}).get_json()
        assert body['ok'] is True
        assert 'tikzpicture' in seen['tex'] and 'tabular' in seen['tex'], 'both boxes must be in one pass'

    def test_a_name_the_ledger_does_not_know_is_refused_by_name(self, client, data_root):
        (data_root / 'data' / 'exports').mkdir(parents=True, exist_ok=True)
        response = client.post('/api/studio/save-pdf', json={'name': 'invented.txt'})
        assert response.status_code == 400
        assert 'invented.txt' in response.get_json()['error']

    def test_a_path_in_the_name_is_refused_rather_than_resolved(self, client, data_root):
        for hostile in ('../../etc/passwd', r'..\windows\system.ini', ''):
            response = client.post('/api/studio/save-pdf', json={'name': hostile})
            assert response.status_code == 400, hostile

    def test_a_registered_file_that_is_not_latex_is_refused(self, client, data_root):
        _register(data_root, 'nodes-1.txt', kind='biblio_nodes')
        response = client.post('/api/studio/save-pdf', json={'name': 'nodes-1.txt'})
        assert response.status_code == 400
        assert 'biblio_nodes' in response.get_json()['error']

    def test_a_ledger_row_whose_file_was_cleared_says_so(self, client, data_root):
        _register(data_root, 'gone-1.txt')
        (data_root / 'data' / 'exports' / 'gone-1.txt').unlink()
        response = client.post('/api/studio/save-pdf', json={'name': 'gone-1.txt'})
        assert response.status_code == 400
        assert 'gone-1.txt' in response.get_json()['error']

    def test_a_missing_compiler_fails_with_its_own_reason(self, client, data_root, monkeypatch):
        import services.charts.pdf as latex_compile

        _register(data_root, 'nofont.txt')
        monkeypatch.setattr(latex_compile, 'find_xelatex', lambda: '')
        response = client.post('/api/studio/save-pdf', json={'name': 'nofont.txt'})
        assert response.status_code == 500
        assert 'xelatex' in response.get_json()['error']
