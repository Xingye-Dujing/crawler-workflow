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


def test_the_reference_picker_answers_under_the_wire_key_the_panel_reads(client):
    response = client.get('/api/ai/ws/references')
    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.get_json()
    assert data['ok'] is True
    assert isinstance(data['references'], list)
    assert any(row['kind'] == 'capability' for row in data['references'])


def test_the_recipe_catalogue_is_served_with_the_declared_steps(client):
    response = client.get('/api/ai/ws/recipes')
    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.get_json()
    recipes = {row['id']: row for row in data['recipes']}
    assert set(recipes) == {'workflow_build', 'dataset_answer'}
    assert [step['tool'] for step in recipes['workflow_build']['steps']][:2] == ['workflow_schema', 'present_artifact']
