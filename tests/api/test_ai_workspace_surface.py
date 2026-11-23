"""The framework-backed surface through the real app: one bootstrap answer the panel can read."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.api


def test_the_workspace_bootstrap_answers_in_the_real_app(client):
    response = client.get('/api/ai/ws/bootstrap')
    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.get_json()
    assert data['ok'] is True
    assert isinstance(data['providers'], list) and data['providers']
    assert isinstance(data['skills'], list)
    assert isinstance(data['conversations'], list)
