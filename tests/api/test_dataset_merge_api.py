"""HTTP contract for merging stored datasets."""

import pandas as pd
import pytest
from runtime.stores import get_dataset_store

from services.datasets.merge import SOURCE_COLUMN

pytestmark = pytest.mark.api


def _put(name, rows, columns=('标题', '正文')):
    return get_dataset_store().put(pd.DataFrame(rows, columns=list(columns)), name=name, source='upload')


class TestDatasetMergeApi:
    def test_merge_returns_the_new_dataset_and_sources(self, client):
        a = _put('A.csv', [{'标题': 'a', '正文': 'x'}])
        b = _put('B.csv', [{'标题': 'b', '正文': 'y'}])
        response = client.post(
            '/api/data/merge',
            json={'dataset_ids': [a['dataset_id'], b['dataset_id']], 'name': '合并结果'},
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body['ok'] is True
        assert body['rows'] == 2
        assert body['columns'][0] == SOURCE_COLUMN
        assert body['dataset']['name'] == '合并结果'
        assert [row['name'] for row in body['sources']] == ['A.csv', 'B.csv']

    def test_refusals_are_named(self, client):
        a = _put('A.csv', [{'标题': 'a', '正文': 'x'}])
        b = _put('B.csv', [{'标题': 'b', '额外': 1}], columns=('标题', '额外'))
        mismatch = client.post('/api/data/merge', json={'dataset_ids': [a['dataset_id'], b['dataset_id']], 'name': 'x'})
        assert mismatch.status_code == 400
        assert '额外' in mismatch.get_json()['error']
        missing = client.post('/api/data/merge', json={'dataset_ids': [a['dataset_id'], 'gone'], 'name': 'x'})
        assert missing.status_code == 400
        assert 'gone' in missing.get_json()['error']
        one = client.post('/api/data/merge', json={'dataset_ids': [a['dataset_id']], 'name': 'x'})
        assert one.status_code == 400
        blank = client.post('/api/data/merge', json={'dataset_ids': [a['dataset_id'], b['dataset_id']], 'name': ''})
        assert blank.status_code == 400
        for body in (
            {'dataset_ids': 'x', 'name': 'y'},
            {'dataset_ids': [1, 2], 'name': 'y'},
            {'dataset_ids': [a['dataset_id'], b['dataset_id']], 'name': 3},
        ):
            response = client.post('/api/data/merge', json=body)
            assert response.status_code == 400, body

    def test_a_lineage_can_be_listed_and_reset_independently(self, client):
        store = get_dataset_store()
        created = store.append_lineage(
            '累积关键词',
            pd.DataFrame([{'标题': 'a'}, {'标题': 'b'}], columns=['标题']),
        )
        listed = client.get('/api/data/lineages').get_json()
        assert listed['lineages'][0]['name'] == '累积关键词'
        one = client.get('/api/data/lineages?name=累积关键词').get_json()
        assert one['lineage']['rows'] == 2
        assert one['history'][0]['added_rows'] == 2
        dataset = client.get('/api/data/datasets').get_json()['datasets']
        current = next(row for row in dataset if row['dataset_id'] == created['lineage']['current_dataset_id'])
        assert current['lineage'] == {'name': '累积关键词', 'version': 1}
        reset = client.post('/api/data/lineages/reset', json={'name': '累积关键词'})
        assert reset.status_code == 200 and reset.get_json()['reset'] is True
        assert store.lineage('累积关键词') is None
        assert store.get(created['lineage']['current_dataset_id']) is not None
        missing = client.post('/api/data/lineages/reset', json={'name': '累积关键词'})
        assert missing.status_code == 404
        assert client.get('/api/data/lineages?name=累积关键词').status_code == 404

    def test_a_cumulative_current_version_is_protected_until_forced(self, client):
        store = get_dataset_store()
        created = store.append_lineage(
            '累积关键词',
            pd.DataFrame([{'标题': 'a'}], columns=['标题']),
        )
        dataset_id = created['lineage']['current_dataset_id']
        refused = client.delete('/api/data/datasets/' + dataset_id)
        assert refused.status_code == 409
        assert '累积关键词' in refused.get_json()['error']
        forced = client.delete('/api/data/datasets/' + dataset_id + '?force=1')
        assert forced.status_code == 200
        assert store.lineage('累积关键词') is None

    def test_the_merged_dataset_is_listable(self, client):
        a = _put('A.csv', [{'标题': 'a', '正文': 'x'}])
        b = _put('B.csv', [{'标题': 'b', '正文': 'y'}])
        _ = client.post('/api/data/merge', json={'dataset_ids': [a['dataset_id'], b['dataset_id']], 'name': '合并结果'})
        listed = client.get('/api/data/datasets').get_json()['datasets']
        assert any(row['name'] == '合并结果' for row in listed)
