"""The chart_spec door: validate once on the server, render through the existing chart route."""

import pytest

pytestmark = pytest.mark.api


class _Store:
    def __init__(self, frame):
        self.frame = frame

    def get(self, dataset_id):
        return self.frame if dataset_id == 'd1' else None


@pytest.fixture
def seeded(monkeypatch):
    import pandas as pd
    import runtime.stores

    frame = pd.DataFrame([{'城市': '北京', '点赞': 3}, {'城市': '上海', '点赞': 5}])
    monkeypatch.setattr(runtime.stores, 'get_dataset_store', lambda: _Store(frame))
    return frame


def _preview(client, spec):
    return client.post('/api/ai/ws/chart/preview', json={'spec': spec}).get_json()


def test_a_chart_spec_becomes_a_validated_render_request(client, seeded):
    data = _preview(client, {'chart_type': 'bar', 'dataset_id': 'd1', 'x': '城市', 'y': '点赞'})
    assert data['ok'] is True
    assert data['request']['dataset_id'] == 'd1'
    assert data['request']['x_field'] == '城市'
    assert data['request']['y_field'] == '点赞'
    assert data['request']['chart_type'] == 'bar'


def test_an_unknown_chart_type_is_refused_by_name(client, seeded):
    data = _preview(client, {'chart_type': 'not_a_chart', 'dataset_id': 'd1'})
    assert data['ok'] is False
    assert data['key'] == 'ai.chartSpecRefused'
    assert 'unknown chart type not_a_chart' in data['error']


def test_a_column_that_does_not_exist_is_refused_by_name(client, seeded):
    data = _preview(client, {'chart_type': 'bar', 'dataset_id': 'd1', 'x': '城市', 'y': '不存在的列'})
    assert data['ok'] is False
    assert data['key'] == 'ai.chartSpecRefused'
    assert 'no such columns: 不存在的列' in data['error']


def test_a_missing_dataset_is_refused_by_name(client, seeded):
    data = _preview(client, {'chart_type': 'bar', 'dataset_id': 'missing', 'x': '城市', 'y': '点赞'})
    assert data['ok'] is False
    assert data['key'] == 'ai.chartSpecRefused'
    assert 'no dataset missing' in data['error']
