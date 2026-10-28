"""``GET /api/node-types`` — the catalogue the canvas reads.

The server declares the types (``nodes/catalog.py``), their seed parameters
(``nodes/defaults.py``) and the one type whose seeds are derived elsewhere (``source``). This
payload is what a running page uses; the canvas's cold-page fallback is pinned to it by
``test_frontend_node_types_js.py``, so the endpoint and the fallback cannot drift apart.
"""

import pandas as pd
import pytest
from nodes.catalog import NODE_TYPES, PLUGINS
from nodes.defaults import DYNAMIC_DEFAULTS, NODE_DEFAULTS

from services.biblio.schema import DEFAULTS as BIBLIO_DEFAULTS

pytestmark = pytest.mark.api


def _payload(client) -> dict:
    response = client.get('/api/node-types')
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _plugins():
    return list(PLUGINS.values())


class TestTheNodeTypeCatalogue:
    def test_every_catalog_type_is_served_once_in_catalogue_order(self, client):
        body = _payload(client)
        assert body['ok'] is True
        listed = [entry['type'] for entry in body['types']]
        assert listed == [plugin.type for plugin in _plugins()]
        assert set(listed) == set(NODE_TYPES)
        assert len(listed) == len(set(listed)), f'a type is served twice: {listed}'

    @pytest.mark.parametrize('plugin', _plugins(), ids=lambda p: p.type)
    def test_each_entry_carries_its_word_group_shape_and_quietness(self, client, plugin):
        entry = next(e for e in _payload(client)['types'] if e['type'] == plugin.type)
        assert entry['labelKey'] == plugin.label_key
        assert entry['category'] == plugin.category
        assert entry['rows'] == plugin.rows
        assert entry['quiet'] is plugin.quiet
        assert entry['labelKey'] in ('',) or entry['labelKey'].startswith('nodeType.'), entry['labelKey']

    def test_static_seeds_exist_for_every_type_but_source(self, client):
        """A type with no seeds is a node that cannot be created with any settings — except
        ``source``, whose platform/engine/mode come from the crawl matrix, which the payload
        names instead of freezing a shape."""
        entries = {entry['type']: entry for entry in _payload(client)['types']}
        assert set(NODE_DEFAULTS) == set(NODE_TYPES) - set(DYNAMIC_DEFAULTS)
        for type_name, seeds in NODE_DEFAULTS.items():
            assert entries[type_name]['defaults'] == seeds, type_name
            assert entries[type_name]['defaultsFrom'] == '', type_name
        assert entries['source']['defaults'] is None
        assert entries['source']['defaultsFrom'] == 'capabilities'

    def test_the_biblio_seeds_are_the_schema_defaults(self, client):
        """The canvas used to carry its own copy of these 56 keys; the API now serves the one
        table ``biblio_schema`` validates against, so a new parameter cannot be seeded on one
        side and refused on the other."""
        entry = next(e for e in _payload(client)['types'] if e['type'] == 'biblio')
        assert entry['defaults'] == BIBLIO_DEFAULTS
        assert len(entry['defaults']) == len(BIBLIO_DEFAULTS)

    def test_every_seed_set_is_json_safe(self, client):
        """The payload crosses JSON: a numpy scalar or a tuple would either 500 the endpoint or
        silently change shape in the browser."""
        for entry in _payload(client)['types']:
            if entry['defaults'] is None:
                continue
            frame = pd.DataFrame([entry['defaults']])
            assert frame.shape == (1, len(entry['defaults']))

    def test_the_endpoint_is_read_only(self, client):
        assert client.post('/api/node-types').status_code == 405
