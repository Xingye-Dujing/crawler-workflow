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
