"""``/api/lexicon`` CRUD over the real client — the panel's contract with the store.

The behaviours that matter: add returns how many landed (duplicates skipped, not double
counted), a write reports fresh counts, an unknown kind is refused by name, and a malformed
body is a 400 rather than a 500.
"""

import pytest

pytestmark = pytest.mark.api


def test_add_list_and_remove_round_trip(client):
    r = client.post('/api/lexicon', json={'kind': 'stopword', 'terms': ['哈哈', '么么哒']})
    assert r.status_code == 200
    assert r.get_json()['added'] == 2

    listed = client.get('/api/lexicon?kind=stopword').get_json()
    assert {e['term'] for e in listed['entries']} == {'哈哈', '么么哒'}
    assert listed['counts']['stopword'] == 2

    rm = client.delete('/api/lexicon', json={'kind': 'stopword', 'term': '哈哈'})
    assert rm.get_json()['removed'] == 1
    assert client.get('/api/lexicon?kind=stopword').get_json()['counts']['stopword'] == 1


def test_duplicates_are_skipped_not_added_twice(client):
    client.post('/api/lexicon', json={'kind': 'stopword', 'terms': ['重复词']})
    r = client.post('/api/lexicon', json={'kind': 'stopword', 'terms': ['重复词']}).get_json()
    assert r['added'] == 0 and r['skipped'] == 1


def test_clear_removes_a_whole_kind(client):
    client.post('/api/lexicon', json={'kind': 'userdict', 'terms': ['词一', '词二']})
    r = client.delete('/api/lexicon', json={'kind': 'userdict', 'clear': True}).get_json()
    assert r['removed'] == 2
    assert client.get('/api/lexicon?kind=userdict').get_json()['counts']['userdict'] == 0


def test_an_unknown_kind_is_refused_by_name(client):
    r = client.post('/api/lexicon', json={'kind': 'nonsense', 'terms': ['x']})
    assert r.status_code == 400
    assert 'nonsense' in r.get_json()['error']


def test_an_empty_term_list_is_refused(client):
    assert client.post('/api/lexicon', json={'kind': 'stopword', 'terms': []}).status_code == 400


def test_a_non_object_body_is_a_400(client):
    assert client.post('/api/lexicon', json=[1, 2]).status_code == 400
