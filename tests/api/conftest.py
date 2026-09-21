"""API-test helpers layered on the shared ``client`` fixture from tests/conftest.py."""
import pytest


@pytest.fixture
def paste(client):
    """``paste(records, name=…)`` → dataset id, through the real paste endpoint.

    Test data arrives over HTTP rather than by poking the store, so a test that
    needs a file also proves the response hands back an id the Upload node and
    the analysis endpoints can resolve.
    """

    def _paste(records, name: str = 'pasted'):
        response = client.post('/api/data/paste', json={'data': records, 'name': name})
        body = response.get_json()
        assert response.status_code == 200, body
        assert body['ok'] is True, body
        return body['dataset_id']

    return _paste
