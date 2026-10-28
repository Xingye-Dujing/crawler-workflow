"""The node catalogue and its executor table are one registration, not two lists.

The catalogue says which node types exist and what shape they carry; the executor table says how each
one runs. A type with a declaration and no executor validates cleanly and then falls through to a
refusal at run time; an executor with no declaration is unreachable. Both are the kind of half-
registration a plugin architecture must make impossible to commit, so this file pins the two sets
against each other and against the frontend's own paste guard.

The frontend carries its own ``_VALID_NODE_TYPES``/seed table as the cold-page fallback; the
catalogue payload is what a running page reads, and this file plus
``test_frontend_node_types_js.py`` pin the fallback to the server so the two cannot drift.
"""

import re
from pathlib import Path

import pytest
from frontend_catalogue import catalog_keys as _catalog_keys
from nodes import catalog

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
JS = ROOT / 'backend' / 'static' / 'js'


def test_every_declared_type_has_an_executor_and_every_executor_a_declaration(app_module):
    from nodes import registry

    assert registry.registered_types() == catalog.NODE_TYPES


def test_registering_one_type_twice_with_a_different_executor_is_refused():
    from nodes import registry

    with pytest.raises(ValueError):
        registry.register('name', lambda _node, _call: [])


def test_no_plugin_imports_the_http_layer():
    """The seam that makes the plugins movable: an executor may use services/state, never ``app``.

    ``import app`` from a plugin would create a cycle (app imports the registry) and would drag the
    whole Flask module into any future CLI that only wants to run a node. The check is static because
    a runtime import would already have failed through the cycle; this names the offending file first.
    """
    for path in (ROOT / 'backend' / 'nodes').rglob('*.py'):
        text = path.read_text(encoding='utf-8')
        assert not re.search(r'^\s*(?:import app|from app import)', text, re.MULTILINE), path


def test_the_row_shapes_partition_the_types():
    table = catalog.TABLE_NODE_TYPES
    pdf = catalog.PDF_SOURCE_NODE_TYPES
    meta = frozenset({'name'})
    assert not (table & pdf) and not (table & meta) and not (pdf & meta)
    assert table | pdf | meta == catalog.NODE_TYPES
    assert frozenset({'name', 'upload'}) == catalog.QUIET_NODE_TYPES, (
        'quietness is a deliberate console decision; changing it should show up here'
    )


def test_the_engine_reads_the_same_sets():
    from engine import workflow

    assert workflow.NODE_TYPES == catalog.NODE_TYPES
    assert workflow.TABLE_NODE_TYPES == catalog.TABLE_NODE_TYPES
    assert workflow.PDF_SOURCE_NODE_TYPES == catalog.PDF_SOURCE_NODE_TYPES


def test_the_frontend_paste_guard_lists_the_same_types():
    """A pasted node JSON is accepted by ``_VALID_NODE_TYPES``; the run then needs an executor.

    The two lists are the same fact about the program, so a type added on one side and not the other
    is a paste the panel accepts and the engine refuses — refused by name at run time, but only
    after the user wired it up.
    """
    source = (JS / 'canvas.js').read_text(encoding='utf-8')
    match = re.search(r'_VALID_NODE_TYPES:\s*\[([^\]]*)\]', source)
    assert match, 'canvas.js no longer declares the paste-import type list'
    names = set(re.findall(r"'([\w.-]+)'", match.group(1)))
    assert names == set(catalog.NODE_TYPES), (
        f'frontend-only: {sorted(names - set(catalog.NODE_TYPES))}; '
        f'backend-only: {sorted(set(catalog.NODE_TYPES) - names)}'
    )


def test_every_plugin_names_a_label_that_exists_in_both_catalogues():
    # The label keys are per type, so they are asked of both languages of the WHOLE browser
    # dictionary (app.js's remainder plus every js/i18n/<domain>.js) — a count inside one file
    # stopped meaning "both languages" the day the domains were split.
    tables = _catalog_keys()
    missing = [
        f'{plugin.type}: {plugin.label_key} in {lang}'
        for plugin in catalog.PLUGINS.values()
        for lang in ('en', 'zh')
        if plugin.label_key not in tables[lang]
    ]
    assert missing == [], f'node types with no zh+en label: {missing}'


def test_an_unknown_type_has_no_plugin():
    assert catalog.plugin_for('moonbase') is None
    assert catalog.plugin_for('') is None


def test_categories_group_the_types_for_a_future_palette():
    assert {'source', 'upload', 'resume', 'comment'} <= set(catalog.types_in('data'))
    assert catalog.types_in('meta') == ('name',)
    assert set(catalog.types_in('visualize')) == {'visualize', 'compile'}


def test_every_type_has_seed_parameters_except_the_one_derived_from_the_matrix():
    """``GET /api/node-types`` seeds a new node from this table; a type missing here would be
    created with no settings at all. ``source`` is the documented exception — its platform,
    engine and mode come from the crawl matrix — and the payload marks that with
    ``defaultsFrom``, so it cannot be mistaken for "no parameters"."""
    from nodes.defaults import DYNAMIC_DEFAULTS, NODE_DEFAULTS

    assert set(NODE_DEFAULTS) == set(catalog.NODE_TYPES) - set(DYNAMIC_DEFAULTS)
    assert DYNAMIC_DEFAULTS == {'source': 'capabilities'}
    for plugin in catalog.PLUGINS.values():
        assert (plugin.type in NODE_DEFAULTS) or (plugin.type in DYNAMIC_DEFAULTS), plugin.type


def test_the_page_loads_the_catalogue_before_the_canvas():
    """The canvas reads the payload when it has answered; a page that never loads the module
    would silently run on the fallback forever."""
    html = (ROOT / 'backend' / 'static' / 'index.html').read_text(encoding='utf-8')
    assert '/js/node-types.js' in html
    assert html.index('/js/workflow.js') < html.index('/js/node-types.js') < html.index('/js/app.js')
    boot = (JS / 'app.js').read_text(encoding='utf-8')
    assert boot.index("boot('nodeTypes'") < boot.index("boot('canvas'")
