"""One class of request bug: a FIELD of the right presence but the wrong TYPE.

The body policy (``_json_body``) already refuses a body that is not an object. Below that layer a
handler reads individual fields, and a field can still be a dict where a column name is expected, a
list where an object is expected, or the string ``"false"`` where a switch is expected. Each used
to surface as an HTML 500 — or, worse, as the opposite answer. What every case here must answer is
the ``{ok: false, error: …}`` envelope with a 4xx status (or, for the read-only diagnostics route,
a normal answer for the part it can read).
"""

import io
import zipfile

import pytest
from api.runs import _log_filters

from services.runs.payload import workflow_shape_error

pytestmark = pytest.mark.api


def test_a_zip_that_is_not_a_workbook_is_a_named_parse_failure(client):
    """A .docx renamed .xlsx is a valid ZIP, so the bomb guard lets it through to pandas."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('word/document.xml', '<document/>')
    buffer.seek(0)
    response = client.post(
        '/api/data/upload',
        data={'file': (buffer, 'report.xlsx')},
        content_type='multipart/form-data',
    )
    assert response.status_code == 400, response.get_data(as_text=True)
    body = response.get_json()
    assert body['ok'] is False
    assert body['error']


def test_a_non_object_settings_does_not_kill_diagnostics(client):
    """The route exists to read a malformed canvas; ``settings`` is one of its fields."""
    response = client.post(
        '/api/workflow/diagnostics',
        json={
            'nodes': {'n1': {'id': 'n1', 'type': 'upload', 'params': {}}},
            'connections': [],
            'settings': '去重',
        },
    )
    assert response.status_code == 200
    assert response.get_json()['ok'] is True


def test_a_column_field_that_is_an_object_is_a_bad_parameter(client):
    response = client.post(
        '/api/analysis/train',
        json={'data': [{'text': 'a', 'label': 'pos'}], 'text_column': {'a': 1}},
    )
    assert response.status_code == 400
    assert response.get_json()['ok'] is False


def test_an_image_field_that_is_a_number_is_a_bad_parameter(client):
    response = client.post('/api/studio/save-image', json={'image': 1})
    assert response.status_code == 400
    assert response.get_json()['ok'] is False


def test_a_context_field_that_is_a_list_is_a_bad_parameter(client):
    response = client.post('/api/ai/context', json={'query': 'x', 'context': ['dataset_id']})
    assert response.status_code == 400
    assert response.get_json()['ok'] is False


def test_a_bad_codebook_id_is_not_found_not_a_crash(client):
    response = client.delete('/api/ai/codebooks/x')
    assert response.status_code == 404
    assert response.get_json()['ok'] is False


def test_log_filters_do_not_int_a_numeric_looking_non_number():
    """``'²'.isdigit()`` is True and ``int('²')`` raises; the shared reader answers 'not a tab'."""
    from flask import Flask, request

    app = Flask(__name__)
    with app.test_request_context('/api/runs/r1/log?wf=%C2%B2&before=%C2%B2&level=INFO'):
        wf_idx, level, q = _log_filters(request)
    assert wf_idx is None
    assert level == 'info'
    assert q is None


def test_a_non_object_llm_payload_is_refused_before_the_slot():
    error = workflow_shape_error(
        {
            'workflow': {'nodes': [{'id': 'n1', 'type': 'upload', 'params': {}}], 'connections': []},
            'llm': 'openrouter',
        }
    )
    assert error, 'a string llm transport must be refused by name, not crash plan.llm_provider'


def test_a_switch_reads_its_value_instead_of_its_truthiness(client):
    """``bool('false')`` is True, so the panel's own serialisation turned 取消锁 into 加锁."""
    response = client.post('/api/locks', json={'panel': 'workflows', 'key': 'demo', 'locked': 'false'})
    assert response.status_code == 200
    body = response.get_json()
    assert body['ok'] is True
    assert body['locked'] is False
    assert all(row['key'] != 'demo' for row in body['locks'])
