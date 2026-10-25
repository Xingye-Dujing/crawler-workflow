"""``GET /api/biblio/sources``: read-only, complete, and translated per request.

The guide ships finished sentences (the cookie guide's convention) because the payload has no
language of its own — so the request's ``X-Lang`` has to be visible in the answer, and a
language switch in the panel means one refetch rather than a second copy of the text in JS.
"""

import pytest

from services import biblio_sources

pytestmark = pytest.mark.api


@pytest.fixture
def sources(client):
    response = client.get('/api/biblio/sources')
    assert response.status_code == 200, response.get_json()
    return response.get_json()


class TestTheGuideIsServed:
    def test_every_readable_source_arrives_in_the_response(self, sources):
        assert [entry['id'] for entry in sources['sources']] == [entry['id'] for entry in biblio_sources.all_sources()]

    def test_the_response_ships_the_file_types_the_picker_should_offer(self, sources):
        assert sources['extensions'], 'an empty accept list would hide every bibliographic format from the dialog'
        assert '.net' in sources['extensions'], 'the CNKI NoteExpress download has to be selectable'
        assert '.xml' not in sources['extensions'], 'no reader takes XML; the picker must not offer it'

    def test_the_guide_speaks_the_language_of_the_request(self, client):
        english = client.get('/api/biblio/sources', headers={'X-Lang': 'en'}).get_json()['sources']
        chinese = client.get('/api/biblio/sources', headers={'X-Lang': 'zh'}).get_json()['sources']
        by_id_en = {entry['id']: entry for entry in english}
        by_id_zh = {entry['id']: entry for entry in chinese}
        for fmt in by_id_en:
            assert by_id_en[fmt]['purpose'] != by_id_zh[fmt]['purpose'], f'{fmt}: one language was served twice'
            assert not by_id_en[fmt]['purpose'].startswith('source.'), by_id_en[fmt]['purpose']

    def test_a_post_is_refused_because_nothing_here_writes(self, client):
        assert client.post('/api/biblio/sources', json={}).status_code == 405

    def test_the_guide_does_not_depend_on_any_run_existing(self, sources):
        """A first launch has no runs, no datasets and no project; the guide still has to open."""
        assert sources['sources'], 'an empty guide reads as a broken panel'
