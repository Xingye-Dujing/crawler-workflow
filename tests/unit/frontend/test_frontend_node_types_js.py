"""The node-type catalogue: the canvas reads the server's list and seeds, and the fallback matches.

Two directions are pinned here:

* **the payload is used** — order, label/category, a deep-copied seed set, and a switch of
  ``validNodeTypes()`` from the pinned list to the served one;
* **the fallback is the same table** — with no payload the canvas returns exactly what
  ``nodes/defaults.py`` says, so the cold-page path cannot drift from the server.

A failed fetch is a named failure, never an empty catalogue: the fallback stays and the toast
carries the reason.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node
from nodes.catalog import PLUGINS
from nodes.defaults import NODE_DEFAULTS

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[3]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_node_types.mjs'


def _catalogue() -> dict:
    types = []
    for plugin in PLUGINS.values():
        types.append(
            {
                'type': plugin.type,
                'labelKey': plugin.label_key,
                'category': plugin.category,
                'rows': plugin.rows,
                'quiet': plugin.quiet,
                'defaults': NODE_DEFAULTS.get(plugin.type),
                'defaultsFrom': 'capabilities' if plugin.type == 'source' else '',
            }
        )
    return {'ok': True, 'types': types}


def _run(tmp_path: Path, scenarios: list) -> dict:
    file = tmp_path / 'scenarios.json'
    file.write_text(json.dumps(scenarios, ensure_ascii=False), encoding='utf-8')
    proc = run_node(str(HARNESS), str(JS_DIR / 'canvas.js'), str(JS_DIR / 'node-types.js'), str(file))
    assert proc.returncode == 0, f'harness failed: {proc.stderr}'
    return json.loads(proc.stdout)


class TestTheServedCatalogue:
    def test_the_payload_is_read_in_order_and_seeds_are_deep_copied(self, tmp_path):
        payload = _catalogue()
        served = payload['types']
        result = _run(
            tmp_path,
            [{'id': 'ok', 'fetch': {'status': 200, 'body': payload}, 'types': ['process', 'biblio']}],
        )['ok']
        loaded = result['loaded']
        assert loaded['ready'] is True
        assert loaded['failure'] == ''
        assert loaded['types'] == [entry['type'] for entry in served], 'the server order is the order shown'
        assert loaded['labelKey'] == 'nodeType.process'
        assert loaded['category'] == 'process'
        assert loaded['defaultsProcess'] == NODE_DEFAULTS['process']
        # The mutation test: the second read is untouched by the first edit.
        assert '__mutated' not in result['afterMutate'], 'seeds must not share one object with the payload'
        assert result['afterMutate'] == NODE_DEFAULTS['process']

    def test_a_failed_fetch_is_named_and_the_fallback_stays(self, tmp_path):
        result = _run(
            tmp_path,
            [{'id': 'down', 'fetch': {'status': 500, 'body': {}}, 'types': ['process']}],
        )['down']
        assert result['loaded']['ready'] is False
        assert 'HTTP 500' in result['loaded']['failure'], result['loaded']['failure']
        assert result['fallback']['process'] == NODE_DEFAULTS['process'], 'the cold-page table stays in use'
        assert result['validAfter'] == result['beforeValid'], 'a failed catalogue must not empty the type list'

    def test_the_fallback_table_equals_the_python_defaults(self, tmp_path):
        """Every type the server seeds must start from the same parameters on a cold page.

        ``source`` is excluded on purpose: its seeds come from the crawl matrix (platform,
        engine, mode), which is exactly why the payload marks it ``defaultsFrom``.
        """
        types = [plugin.type for plugin in PLUGINS.values() if plugin.type != 'source']
        result = _run(
            tmp_path,
            [{'id': 'fallback', 'fetch': {'status': 500, 'body': {}}, 'types': types}],
        )['fallback']
        assert set(result['fallback']) == set(types)
        for type_name, expected in NODE_DEFAULTS.items():
            assert result['fallback'][type_name] == expected, f'{type_name} seeds drifted from nodes/defaults.py'

    def test_valid_types_switch_to_the_served_list(self, tmp_path):
        payload = {'ok': True, 'types': [_catalogue()['types'][0]]}
        result = _run(
            tmp_path,
            [{'id': 'switch', 'fetch': {'status': 200, 'body': payload}, 'types': ['name']}],
        )['switch']
        assert result['beforeValid'] != result['validAfter'], (
            'the canvas kept its literal list after the payload answered'
        )
        assert result['validAfter'] == [payload['types'][0]['type']]
