"""The node catalogue and its executor table are one registration, not two lists.

The catalogue says which node types exist and what shape they carry; the executor table says how each
one runs. A type with a declaration and no executor validates cleanly and then falls through to a
refusal at run time; an executor with no declaration is unreachable. Both are the kind of half-
registration a plugin architecture must make impossible to commit, so this file pins the two sets
against each other and against the frontend's own paste guard.

The frontend still carries its own ``_VALID_NODE_TYPES`` until Phase 2 (``docs/refactor_plan.md``);
pinning it here is what keeps that duplication honest in the meantime.
"""

import re
from pathlib import Path

import pytest
from nodes import catalog

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
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
    source = (ROOT / 'backend' / 'static' / 'js' / 'app.js').read_text(encoding='utf-8')
    for plugin in catalog.PLUGINS.values():
        found = len(re.findall(rf"""['"]{re.escape(plugin.label_key)}['"]\s*:""", source))
        assert found == 2, f'{plugin.type}: {plugin.label_key} appears {found} times (want zh + en)'


def test_an_unknown_type_has_no_plugin():
    assert catalog.plugin_for('moonbase') is None
    assert catalog.plugin_for('') is None


def test_categories_group_the_types_for_a_future_palette():
    assert {'source', 'upload', 'resume', 'comment'} <= set(catalog.types_in('data'))
    assert catalog.types_in('meta') == ('name',)
    assert set(catalog.types_in('visualize')) == {'visualize', 'compile'}
