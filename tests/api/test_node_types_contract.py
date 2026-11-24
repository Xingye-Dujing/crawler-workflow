"""What the browser is served agrees with the manifests, field for field.

``/api/node-types`` is the canvas's whole vocabulary: the types it may draw, the defaults a new node
seeds, the chart boxes and the analysis step's form. Those payloads are projections, and a projection
can drift in a way no unit test of the manifest would notice (a default key that the node's own
validator would refuse, a chart field that the chart registry does not declare). These cases compare
the SERVED answer with the declaration it came from.
"""

import pytest
from capabilities_kernel import registry
from nodes.defaults import NODE_DEFAULTS

from services.charts.registry import chart_profiles

pytestmark = [pytest.mark.api]


@pytest.fixture()
def payload(client):
    body = client.get('/api/node-types').get_json()
    assert body['ok'] is True
    return body


class TestTheNodeTypesPayload:
    def test_every_served_default_is_a_declared_parameter(self, payload):
        for entry in payload['types']:
            manifest = registry.manifest_for_node(entry['type'])
            assert manifest is not None, entry['type']
            declared = {spec.name for spec in manifest.params}
            served = set(entry['defaults'] or {})
            assert served <= declared, f'{entry["type"]}: served defaults not declared: {sorted(served - declared)}'

    def test_a_type_without_manifest_defaults_serves_none(self, payload):
        for entry in payload['types']:
            manifest = registry.manifest_for_node(entry['type'])
            if manifest.ui.defaults_from:
                assert entry['defaults'] is None, entry['type']
            else:
                assert entry['defaults'] is not None, entry['type']

    def test_the_seed_values_are_the_manifest_defaults(self, payload):
        for entry in payload['types']:
            manifest = registry.manifest_for_node(entry['type'])
            if manifest.ui.defaults_from:
                continue
            for name, value in (entry['defaults'] or {}).items():
                if name in NODE_DEFAULTS.get(entry['type'], {}):
                    continue  # the runtime settings overlay (comment limits, part sizes) is read here
                assert value == manifest.defaults()[name], f'{entry["type"]}.{name}'


class TestTheChartProfiles:
    def test_the_served_profiles_are_the_registry_projection(self, payload):
        assert payload['charts'] == chart_profiles()

    def test_every_field_is_declared_by_its_chart(self, payload):
        for profile in payload['charts']:
            spec = registry.get('chart', profile['key'])
            assert spec is not None, profile['key']
            assert [field['name'] for field in profile['fields']] == [field.name for field in spec.fields]

    def test_every_default_names_a_declared_field(self, payload):
        for profile in payload['charts']:
            declared = {field['name'] for field in profile['fields']}
            assert set(profile['defaults']) <= declared, profile['key']


class TestTheOperatorProfiles:
    def test_every_operator_is_served_with_its_declared_parameters(self, payload):
        manifests = {manifest.identity.id: manifest for manifest in registry.manifests('operator')}
        assert {row['id'] for row in payload['operators']} == set(manifests)
        for row in payload['operators']:
            manifest = manifests[row['id']]
            assert row['params'] == [
                {
                    'name': spec.name,
                    'type': spec.type,
                    'default': spec.default,
                    'required': spec.required,
                    'enum': list(spec.enum),
                    'minimum': spec.minimum,
                    'maximum': spec.maximum,
                    'widget': spec.widget,
                }
                for spec in manifest.params
            ], row['id']

    def test_a_panel_box_feeds_a_declared_parameter(self, payload):
        for row in payload['operators']:
            declared = {spec['name'] for spec in row['params']}
            for box in row['panel']:
                if box['control'] in ('note', 'roles'):
                    continue
                assert box['canonical'] in declared, f'{row["id"]}.{box["key"]} → {box["canonical"]}'
