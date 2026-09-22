"""Tests for the data endpoints: files in, rows out, housekeeping in between.

Everything the app can analyse enters through this door — an uploaded file,
pasted records, or the ``/api/data/datasets`` registry that keeps both
addressable after a restart. The behaviours worth pinning are the ones the
frontend depends on: an upload answers with the id plus the columns it
actually parsed (a CSV header, not a guess), the preview pages without
losing rows, and ``/api/data/clear`` never deletes a file a saved workflow
still points at.

No test here touches a network or a browser; uploads go in through the same
multipart form field the browser uses.
"""

import io

import pytest

pytestmark = pytest.mark.api


def _xlsx_bytes() -> bytes:
    """A real workbook in memory — the importer must read the format, not text.

    A hand-made byte string would only prove the branch was reached; a file
    openpyxl actually wrote proves a user's spreadsheet round-trips.
    """
    import pandas as pd

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        pd.DataFrame({'title': ['sanya', 'haikou'], 'score': [3, 5]}).to_excel(writer, index=False)
    return buffer.getvalue()


CSV_BYTES = b'title,score,city\nsanya,3,Sanya\nhaikou,5,Haikou\nsanya,2,Sanya\n'
JSON_BYTES = b'[{"title": "sanya", "score": 3}, {"title": "haikou", "score": 5}]'
TXT_BYTES = '三亚的海非常蓝。\n第二行正文\n'.encode()
RECORDS = [{'title': 'sanya', 'score': 3}, {'title': 'haikou', 'score': 5}, {'title': 'sanya', 'score': 2}]


def _upload(client, filename: str, payload: bytes):
    """Post a file the way the browser does: multipart, field name ``file``."""
    return client.post(
        '/api/data/upload',
        data={'file': (io.BytesIO(payload), filename)},
        content_type='multipart/form-data',
    )


class TestUpload:
    @pytest.mark.parametrize(
        ('filename', 'payload', 'columns', 'row_count', 'is_txt'),
        [
            ('rows.csv', CSV_BYTES, ['title', 'score', 'city'], 3, False),
            ('rows.json', JSON_BYTES, ['title', 'score'], 2, False),
            ('notes.txt', TXT_BYTES, ['content'], 1, True),
        ],
    )
    def test_each_accepted_extension_becomes_a_registered_dataset(
        self, client, filename, payload, columns, row_count, is_txt
    ):
        response = _upload(client, filename, payload)
        body = response.get_json()
        assert response.status_code == 200
        assert body['ok'] is True
        assert body['columns'] == columns
        assert body['row_count'] == row_count
        assert body['is_txt'] is is_txt
        # The name is what the Upload node labels itself with, so it must
        # travel back with the id.
        assert body['name'] == filename
        assert body['persisted'] is True
        assert len(body['preview']) == row_count
        assert body['preview'][0].keys() <= set(columns)

    def test_a_txt_file_keeps_its_whole_text_in_one_row(self, client):
        body = client.post(
            '/api/data/upload',
            data={'file': (io.BytesIO(TXT_BYTES), 'notes.txt')},
            content_type='multipart/form-data',
        ).get_json()
        detail = client.get(f'/api/data/datasets/{body["dataset_id"]}').get_json()['dataset']
        assert detail['row_count'] == 1
        assert '三亚' in detail['preview'][0]['content']

    def test_an_excel_workbook_imports_as_a_table(self, client):
        """The format non-technical users actually have their data in.

        Before this branch an .xlsx fell through to ``read_csv`` and came back
        as one garbled column with a 200 — an import that looked successful and
        was nonsense, which is worse than a refusal.
        """
        body = _upload(client, 'sheet.xlsx', _xlsx_bytes()).get_json()
        assert body['ok'] is True
        assert body['columns'] == ['title', 'score']
        assert body['row_count'] == 2
        assert {row['title'] for row in body['preview']} == {'sanya', 'haikou'}

    def test_a_tsv_is_split_on_tabs(self, client):
        body = _upload(client, 'rows.tsv', b'title\tscore\nsanya\t3\n').get_json()
        assert body['columns'] == ['title', 'score'] and body['row_count'] == 1

    def test_a_comma_file_with_a_tab_inside_a_cell_stays_comma_split(self, client):
        """The regression the ``sep=None`` sniffing version introduced: one
        quoted cell containing a tab re-shaped the whole table."""
        tricky = b'title,score\n"sanya\tbeach",3\n'
        body = _upload(client, 'tricky.csv', tricky).get_json()
        assert body['columns'] == ['title', 'score']
        assert body['preview'][0]['title'] == 'sanya\tbeach'

    @pytest.mark.parametrize('filename', ['data.parquet', 'report.pdf', 'noextension', 'archive.zip'])
    def test_an_unknown_extension_is_refused_not_guessed(self, client, tmp_path, filename):
        """Refusing is honest; "parsed" as CSV is a plausible-looking wrong
        table that the rest of the workflow then analyses seriously."""
        response = _upload(client, filename, b'\x01\x02parquet-ish bytes\nnot,a,csv\n')
        assert response.status_code == 400
        assert 'csv' in response.get_json()['error'] or '.csv' in response.get_json()['error']

    def test_re_uploading_the_same_rows_reuses_one_copy(self, client):
        first = _upload(client, 'same.csv', CSV_BYTES).get_json()
        second = _upload(client, 'renamed.csv', CSV_BYTES).get_json()
        # Content-addressed: same id, and the first name is the one saved
        # workflows already know the file by.
        assert second['dataset_id'] == first['dataset_id']
        assert second['name'] == 'renamed.csv'
        listed = client.get('/api/data/datasets').get_json()['datasets']
        assert [item['dataset_id'] for item in listed] == [first['dataset_id']]

    def test_a_missing_file_is_a_bad_request(self, client):
        response = client.post('/api/data/upload', data={}, content_type='multipart/form-data')
        assert response.status_code == 400
        assert 'missing file' in response.get_json()['error']

    @pytest.mark.parametrize(
        ('filename', 'payload'),
        [
            # pandas 3 is forgiving about ragged rows but not about a quote it
            # can never close, so this is the shortest truly unreadable file.
            ('broken.csv', b'x,y\n"a,1\nb,2\n'),
            ('broken.json', b'[{"title": "unterminated'),
        ],
    )
    def test_an_unparseable_file_is_reported_not_raised(self, client, filename, payload):
        """A mis-encoded file is user input, so it must come back as a 400 the
        upload panel can read instead of an HTML 500."""
        response = _upload(client, filename, payload)
        assert response.status_code == 400
        assert 'Could not parse the file' in response.get_json()['error']


class TestDatasetRegistry:
    def test_paste_list_detail_delete_round_trip(self, client, paste):
        dataset_id = paste(RECORDS, name='hand.csv')
        assert client.get('/api/data/datasets').get_json()['datasets'][0]['dataset_id'] == dataset_id

        listed = client.get('/api/data/datasets').get_json()
        assert listed['datasets'][0]['source'] == 'paste'
        assert listed['datasets'][0]['row_count'] == 3
        assert listed['datasets'][0]['workflows'] == []
        assert set(listed['stats']) == {'datasets', 'rows', 'bytes', 'refs'}
        assert listed['stats']['datasets'] == 1

        detail = client.get(f'/api/data/datasets/{dataset_id}').get_json()
        assert detail['dataset']['name'] == 'hand.csv'
        assert sorted(detail['dataset']['columns']) == ['score', 'title']
        assert len(detail['dataset']['preview']) == 3

        assert client.delete(f'/api/data/datasets/{dataset_id}').get_json() == {
            'ok': True,
            'dataset_id': dataset_id,
        }
        assert client.get(f'/api/data/datasets/{dataset_id}').status_code == 404
        assert client.delete(f'/api/data/datasets/{dataset_id}').status_code == 404
        assert client.get('/api/data/datasets').get_json()['datasets'] == []

    def test_paste_requires_a_list_of_records(self, client):
        response = client.post('/api/data/paste', json={'data': {'title': 'not a list'}})
        assert response.status_code == 400
        assert 'data' in response.get_json()['error']

    def test_paste_of_an_empty_list_still_gets_an_identity(self, client, paste):
        """An empty table has no content to hash, so it gets a fresh id rather
        than colliding with every other empty file."""
        first = paste([], name='empty-a')
        second = paste([], name='empty-b')
        assert first != second
        detail = client.get(f'/api/data/datasets/{first}').get_json()['dataset']
        assert detail['row_count'] == 0

    def test_limit_pages_the_list_without_changing_the_stats(self, client, paste):
        paste(RECORDS, name='one.csv')
        paste([{'x': 1}] * 2, name='two.csv')
        limited = client.get('/api/data/datasets', query_string={'limit': 1}).get_json()
        assert len(limited['datasets']) == 1
        # Stats describe the whole store, not the page that was returned.
        assert limited['stats']['datasets'] == 2


class TestInspectAndPreview:
    def test_inspect_reports_shape_and_missing_values(self, client, paste):
        dataset_id = paste(
            [
                {'title': 'sanya', 'score': 3, 'city': 'Sanya'},
                {'title': 'haikou', 'score': None, 'city': 'Haikou'},
                {'title': 'sanya', 'score': 3, 'city': 'Sanya'},
            ],
            name='inspect.csv',
        )
        report = client.post('/api/data/inspect', json={'dataset_id': dataset_id}).get_json()['report']
        assert report['rows'] == 3
        assert sorted(report['columns']) == ['city', 'score', 'title']
        assert set(report['dtypes']) == set(report['columns'])
        assert report['null_counts']['score'] == 1
        assert report['duplicate_rows'] == 1

    def test_preview_pages_without_losing_or_doubling_rows(self, client, paste):
        dataset_id = paste([{'n': i} for i in range(5)], name='pages.csv')
        first = client.post('/api/data/preview', json={'dataset_id': dataset_id, 'limit': 2}).get_json()
        assert first['total_rows'] == 5
        assert [row['n'] for row in first['rows']] == [0, 1]
        assert first['offset'] == 0 and first['limit'] == 2

        middle = client.post('/api/data/preview', json={'dataset_id': dataset_id, 'limit': 2, 'offset': 2}).get_json()
        assert [row['n'] for row in middle['rows']] == [2, 3]

        past_end = client.post(
            '/api/data/preview', json={'dataset_id': dataset_id, 'limit': 2, 'offset': 40}
        ).get_json()
        assert past_end['rows'] == []
        # Paging past the end still reports the real total, so the UI can stop.
        assert past_end['total_rows'] == 5
        assert past_end['columns'] == first['columns']

    def test_preview_bounds_the_page_size(self, client, paste):
        dataset_id = paste([{'n': i} for i in range(3)], name='small.csv')
        body = client.post('/api/data/preview', json={'dataset_id': dataset_id, 'limit': 99999}).get_json()
        assert body['limit'] == 500
        assert len(body['rows']) == 3
        default = client.post('/api/data/preview', json={'dataset_id': dataset_id}).get_json()
        assert default['limit'] == 50 and default['offset'] == 0

    @pytest.mark.parametrize('path', ['/api/data/inspect', '/api/data/preview'])
    def test_unknown_dataset_ids_are_answered_with_400(self, client, path):
        response = client.post(path, json={'dataset_id': 'no-such-dataset'})
        assert response.status_code == 400
        assert 'Unknown dataset_id' in response.get_json()['error']

    @pytest.mark.parametrize('payload', [{}, {'node_id': 'node-9'}])
    def test_requests_without_any_resolvable_source_are_answered_with_400(self, client, payload):
        response = client.post('/api/data/preview', json=payload)
        assert response.status_code == 400
        assert response.get_json()['ok'] is False


class TestClear:
    def test_clear_drops_orphans_but_keeps_files_a_workflow_still_reads(self, client, app_module, paste):
        orphan = paste([{'a': 1}], name='orphan.csv')
        wanted = paste([{'b': 2}], name='wanted.csv')
        upload_node = {'id': 'node-1', 'type': 'upload', 'params': {'dataset_id': wanted, 'row_count': 1}}
        workflow = {'nodes': [upload_node], 'connections': [], 'settings': {'mode': 'serial'}}
        assert client.post('/api/workflow/save', json={'name': 'clear-test', 'workflow': workflow}).status_code == 200

        # Back-date both files: housekeeping only ever removes old ones.
        app_module._DATASET_STORE._execute("UPDATE datasets SET last_used_at = '2000-01-01T00:00:00'")

        body = client.post('/api/data/clear', json={}).get_json()
        assert body == {'ok': True, 'removed': 1, 'kept': 1}
        remaining = client.get('/api/data/datasets').get_json()['datasets']
        assert [item['dataset_id'] for item in remaining] == [wanted]
        assert remaining[0]['workflows'] == ['clear-test']
        assert client.get(f'/api/data/datasets/{orphan}').status_code == 404
        assert client.get(f'/api/data/datasets/{wanted}').status_code == 200

    def test_an_explicit_wipe_takes_referenced_files_too(self, client, app_module, paste):
        paste([{'a': 1}], name='still-referenced.csv')
        upload_node = {'id': 'node-1', 'type': 'upload', 'params': {'dataset_id': 'whatever', 'row_count': 1}}
        workflow = {'nodes': [upload_node], 'connections': [], 'settings': {'mode': 'serial'}}
        client.post('/api/workflow/save', json={'name': 'wipe-test', 'workflow': workflow})
        assert client.post('/api/data/clear', json={'all': '1'}).get_json() == {
            'ok': True,
            'removed': 1,
            'orphans': 0,
        }
        assert app_module._DATASET_STORE.stats() == {'datasets': 0, 'rows': 0, 'bytes': 0, 'refs': 0}


class TestDatasetRename:
    """The name is the only thing in a dataset list a user can recognise — the
    id is a content hash — so relabelling is the difference between a file being
    findable and being identifiable by row count.
    """

    def test_renaming_updates_the_list_and_keeps_the_id(self, client):
        did = _upload(client, 'orders.csv', CSV_BYTES).get_json()['dataset_id']
        body = client.post(f'/api/data/datasets/{did}/rename', json={'name': '三亚订单-9月'}).get_json()
        assert body['ok'] is True and body['name'] == '三亚订单-9月'
        listed = client.get('/api/data/datasets').get_json()['datasets']
        assert [item['name'] for item in listed if item['dataset_id'] == did] == ['三亚订单-9月']
        # The rows are untouched: a rename is a label, not a re-hash.
        detail = client.get(f'/api/data/datasets/{did}').get_json()['dataset']
        assert detail['row_count'] == 3

    def test_a_name_with_path_characters_is_cleaned_not_stored_raw(self, client):
        did = _upload(client, 'orders.csv', CSV_BYTES).get_json()['dataset_id']
        body = client.post(f'/api/data/datasets/{did}/rename', json={'name': '../../etc/passwd'}).get_json()
        assert body['ok'] is True
        assert body['name'] and '\\' not in body['name'] and '/' not in body['name']

    def test_a_name_that_reduces_to_nothing_is_refused(self, client):
        """A nameless row cannot be clicked or found, so this is a 400 — not a
        silent success that leaves the list with a blank line."""
        did = _upload(client, 'orders.csv', CSV_BYTES).get_json()['dataset_id']
        for bad in ('', '   ', '...', '..'):
            response = client.post(f'/api/data/datasets/{did}/rename', json={'name': bad})
            assert response.status_code == 400, bad
            assert response.get_json()['ok'] is False
        for bad in (7, None, {'a': 1}):
            assert client.post(f'/api/data/datasets/{did}/rename', json={'name': bad}).status_code == 400
        # A separator is not refused but replaced: '/' sanitises to '_', which is
        # an ugly-but-usable label rather than an empty row.
        assert client.post(f'/api/data/datasets/{did}/rename', json={'name': '/'}).status_code == 200
        assert client.get('/api/data/datasets').get_json()['datasets'][0]['name'] == '_'

    def test_renaming_a_missing_dataset_is_a_404(self, client):
        assert client.post('/api/data/datasets/nope000/rename', json={'name': 'x'}).status_code == 404

    def test_two_files_can_share_a_label(self, client):
        """Identity is content, so a name is not a key.

        Refusing a duplicate label would make renaming feel broken for no
        protective reason; the list still separates the two rows by id, and each
        keeps its own rows.
        """
        kept = _upload(client, 'first.csv', CSV_BYTES).get_json()['dataset_id']
        other = _upload(client, 'other.tsv', b'title\tscore\nsanya\t3\n').get_json()['dataset_id']
        assert kept != other
        for did in (kept, other):
            assert client.post(f'/api/data/datasets/{did}/rename', json={'name': '同一个名字'}).status_code == 200
        listed = client.get('/api/data/datasets').get_json()['datasets']
        named = [item for item in listed if item['name'] == '同一个名字']
        assert {item['dataset_id'] for item in named} == {kept, other}
        assert {item['row_count'] for item in named} == {3, 1}

    def test_renaming_survives_a_reload_of_the_workflow_that_reads_it(self, client):
        """A workflow's Upload node remembers the file by id, and shows it by
        name — after a rename the id must be unchanged and the label updated,
        or the rename would have silently broken the binding it displays."""
        did = _upload(client, 'orders.csv', CSV_BYTES).get_json()['dataset_id']
        workflow = {'nodes': [{'id': 'u1', 'type': 'upload', 'params': {'dataset_id': did}}], 'connections': []}
        client.post('/api/workflow/save', json={'name': 'reader', 'workflow': workflow})
        client.get('/api/workflow/load', query_string={'name': 'reader'})
        client.post(f'/api/data/datasets/{did}/rename', json={'name': '九月订单'})
        entry = client.get('/api/workflow/load', query_string={'name': 'reader'}).get_json()['datasets'][0]
        assert entry['dataset_id'] == did and entry['missing'] is False
        assert client.get(f'/api/data/datasets/{did}').get_json()['dataset']['name'] == '九月订单'


class TestDatasetDeletionGuards:
    def test_a_file_a_saved_workflow_reads_is_not_deleted_quietly(self, client):
        did = _upload(client, 'orders.csv', CSV_BYTES).get_json()['dataset_id']
        workflow = {'nodes': [{'id': 'u1', 'type': 'upload', 'params': {'dataset_id': did}}], 'connections': []}
        client.post('/api/workflow/save', json={'name': 'reader', 'workflow': workflow})
        client.get('/api/workflow/load', query_string={'name': 'reader'})

        response = client.delete(f'/api/data/datasets/{did}')
        assert response.status_code == 409
        body = response.get_json()
        assert body['ok'] is False and body['workflows'] == ['reader']
        assert 'reader' in body['error'], 'the refusal must name the workflow at fault'
        assert client.get(f'/api/data/datasets/{did}').get_json()['dataset']

    def test_force_overrides_the_guard_because_the_user_asked_twice(self, client):
        did = _upload(client, 'orders.csv', CSV_BYTES).get_json()['dataset_id']
        client.post(
            '/api/workflow/save',
            json={
                'name': 'reader',
                'workflow': {
                    'nodes': [{'id': 'u1', 'type': 'upload', 'params': {'dataset_id': did}}],
                    'connections': [],
                },
            },
        )
        client.get('/api/workflow/load', query_string={'name': 'reader'})
        assert client.delete(f'/api/data/datasets/{did}').status_code == 409
        assert client.delete(f'/api/data/datasets/{did}?force=1').get_json()['ok'] is True

    def test_an_unreferenced_file_deletes_normally(self, client):
        did = _upload(client, 'loose.csv', CSV_BYTES).get_json()['dataset_id']
        assert client.delete(f'/api/data/datasets/{did}').get_json()['ok'] is True
        assert client.get(f'/api/data/datasets/{did}').status_code == 404
