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

    def test_an_oversized_image_is_refused(self, client, app_module, monkeypatch):
        monkeypatch.setattr(app_module, 'MAX_IMAGE_BYTES', 8)
        response = client.post('/api/studio/save-image', json={'image': PNG_DATA_URL})
        assert response.status_code == 400
        assert 'image too large' in response.get_json()['error']
