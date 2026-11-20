"""Artifact previews are a kind-keyed registry, like validators, and never apply anything.

A preview makes a proposed artifact legible before the user commits to it: what nodes it brings
onto the canvas, what memory text it writes, what trigger it arms. The apply endpoints stay the
only door that changes state, so these tests pin only the description.
"""

import pytest
from ai import previews

from i18n import t

pytestmark = pytest.mark.unit

EXPECTED = frozenset({'memory', 'monitor', 'chart_spec', 'workflow', 'workflow_draft'})


def test_the_registry_pins_its_builtin_kinds():
    assert previews.registered_kinds() == EXPECTED


def test_a_duplicate_preview_is_refused():
    from ai.previews.base import PREVIEWS, Preview, register

    def first(_payload, _current):
        return Preview('x', 't', 's')

    original = dict(PREVIEWS)
    try:
        PREVIEWS.clear()
        register('x', first)
        with pytest.raises(ValueError, match='already has a previewer'):
            register('x', lambda _p, _c: first)
    finally:
        PREVIEWS.clear()
        PREVIEWS.update(original)


def test_reset_restores_the_builtin_previewers():
    previews.reset_for_tests()
    previews.load_builtin_previews()
    assert previews.registered_kinds() == EXPECTED


def test_an_unregistered_kind_has_no_preview():
    assert previews.preview('plan', {'text': 'x'}) is None


def test_a_memory_preview_shows_the_exact_text():
    result = previews.preview('memory', {'text': 'remember this'})
    assert result is not None
    assert 'remember this' in result.summary
    assert result.selectable is False
    assert result.items[0].action == 'add'


def test_a_workflow_preview_names_new_and_overwritten_nodes():
    draft = {
        'nodes': [
            {'id': 'n1', 'type': 'name', 'params': {'workflow_name': 'draft'}},
            {'id': 'n2', 'type': 'analysis', 'params': {'operation': 'topic_label'}},
        ],
        'connections': [{'from': 'n1', 'to': 'n2'}],
    }
    current = {'nodes': [{'id': 'n1', 'type': 'source', 'params': {'platform': 'bilibili'}}], 'connections': []}

    result = previews.preview('workflow_draft', draft, current)

    assert result is not None
    by_id = {item.id: item for item in result.items}
    assert by_id['n1'].action == 'change' and by_id['n1'].selectable is True
    assert by_id['n2'].action == 'add' and by_id['n2'].selectable is True
    assert result.selectable is True
    assert t('ai.preview.nodeSummary', n=2) == result.summary


def test_a_workflow_preview_keeps_existing_nodes_out_of_the_selection():
    draft = {'nodes': [{'id': 'n1', 'type': 'name', 'params': {'workflow_name': 'draft'}}], 'connections': []}
    current = {
        'nodes': [
            {'id': 'n1', 'type': 'name', 'params': {'workflow_name': 'current'}},
            {'id': 'n9', 'type': 'name', 'params': {'workflow_name': 'keep me'}},
        ],
        'connections': [{'from': 'n1', 'to': 'n9'}],
    }

    result = previews.preview('workflow', draft, current)

    kept = [item for item in result.items if item.id == 'keep:n9']
    assert len(kept) == 1 and kept[0].selectable is False
    assert result.warnings, 'a merge that leaves a node behind must say so'


def test_a_monitor_preview_shows_the_normalized_events():
    result = previews.preview('monitor', {'events': 'run.finished, node.finished', 'statuses': 'failed'})

    assert result is not None
    assert 'run.finished' in result.summary
    assert 'node.finished' in result.summary
    assert 'failed' in result.items[0].detail


def test_a_monitor_preview_refuses_a_bad_event_by_name():
    from ai.errors import AIError

    with pytest.raises(AIError) as refused:
        previews.preview('monitor', {'events': 'not.an.event'})
    assert refused.value.key == 'ai.monitorEvent'


def test_a_chart_preview_names_the_chart_and_dataset():
    result = previews.preview('chart_spec', {'chart_type': 'bar', 'dataset_id': 'd1', 'x': 'city', 'y': 'likes'})

    assert result is not None
    assert 'bar' in result.summary and 'd1' in result.summary
    assert 'city' in result.items[0].detail and 'likes' in result.items[0].detail
