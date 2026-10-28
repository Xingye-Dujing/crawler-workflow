"""Server-side expansion of reusable nodes: schedules run from a saved file, not the browser."""

import copy

from services.workflows.expand import expand_reusable_workflow


def group(group_id='g1', inputs=('a', 'b'), outputs=('c',), enabled=True, template_nodes=None):
    return {
        'id': group_id,
        'type': 'reusable',
        'title': '测试组',
        'params': {
            'template_name': '测试组',
            'enabled': enabled,
            'collapsed': True,
            'template': {
                'nodes': template_nodes
                or [
                    {'id': 'a', 'type': 'process', 'title': 'A', 'params': {'operation': 'clean'}},
                    {'id': 'b', 'type': 'process', 'title': 'B', 'params': {'operation': 'clean'}},
                    {'id': 'c', 'type': 'analysis', 'title': 'C', 'params': {'operation': 'drop_null'}},
                ],
                'connections': [{'from': 'a', 'to': 'c'}, {'from': 'b', 'to': 'c'}],
                'inputs': list(inputs),
                'outputs': list(outputs),
            },
        },
    }


def workflow(nodes, connections):
    return {'nodes': nodes, 'connections': connections, 'settings': {'mode': 'serial'}}


class TestExpansion:
    def test_children_are_namespaced_and_external_wires_land_on_ordered_slots(self):
        wf = workflow(
            [
                {'id': 'up1', 'type': 'process', 'params': {}},
                {'id': 'up2', 'type': 'process', 'params': {}},
                group(),
                {'id': 'down', 'type': 'output', 'params': {'operation': 'save', 'filename': 'x.csv'}},
            ],
            [
                {'from': 'up1', 'to': 'g1'},
                {'from': 'up2', 'to': 'g1'},
                {'from': 'g1', 'to': 'down'},
            ],
        )
        expanded, error = expand_reusable_workflow(wf)
        assert error == ''
        ids = [n['id'] for n in expanded['nodes']]
        assert set(ids) == {'up1', 'up2', 'down', 'g1__a', 'g1__b', 'g1__c'}
        assert 'g1' not in ids
        edges = {(c['from'], c['to']) for c in expanded['connections']}
        assert edges == {
            ('g1__a', 'g1__c'),
            ('g1__b', 'g1__c'),
            ('up1', 'g1__a'),
            ('up2', 'g1__b'),
            ('g1__c', 'down'),
        }
        child = next(n for n in expanded['nodes'] if n['id'] == 'g1__c')
        assert child['type'] == 'analysis'
        assert child['params']['operation'] == 'drop_null'
        assert expanded['settings'] == {'mode': 'serial'}

    def test_a_workflow_without_groups_is_returned_untouched(self):
        wf = workflow([{'id': 'a', 'type': 'process', 'params': {}}], [])
        expanded, error = expand_reusable_workflow(wf)
        assert error == ''
        assert expanded is wf

    def test_a_disabled_group_is_dropped_with_its_wires(self):
        wf = workflow(
            [
                {'id': 'up', 'type': 'process', 'params': {}},
                group(enabled=False),
                {'id': 'down', 'type': 'output', 'params': {}},
            ],
            [
                {'from': 'up', 'to': 'g1'},
                {'from': 'g1', 'to': 'down'},
            ],
        )
        expanded, error = expand_reusable_workflow(wf)
        assert error == ''
        assert [n['id'] for n in expanded['nodes']] == ['up', 'down']
        assert expanded['connections'] == []

    def test_a_group_to_group_wire_uses_the_source_output_and_target_slot(self):
        wf = workflow(
            [
                group('g1', inputs=(), outputs=('c',)),
                group('g2', inputs=('a',), outputs=('c',)),
            ],
            [{'from': 'g1', 'to': 'g2'}],
        )
        expanded, error = expand_reusable_workflow(wf)
        assert error == ''
        edges = {(c['from'], c['to']) for c in expanded['connections']}
        assert ('g1__c', 'g2__a') in edges
        assert ('g2__c', 'g1__a') not in edges

    def test_a_group_may_have_no_inputs(self):
        wf = workflow(
            [group(inputs=(), outputs=('c',))],
            [],
        )
        expanded, error = expand_reusable_workflow(wf)
        assert error == ''
        assert len(expanded['nodes']) == 3
        assert {(c['from'], c['to']) for c in expanded['connections']} == {
            ('g1__a', 'g1__c'),
            ('g1__b', 'g1__c'),
        }


class TestRefusals:
    def test_a_missing_input_is_named_with_the_count(self):
        wf = workflow([group()], [])
        expanded, error = expand_reusable_workflow(wf)
        assert expanded == {}
        assert '测试组' in error and '2' in error

    def test_an_extra_input_is_named(self):
        wf = workflow(
            [
                {'id': 'a', 'type': 'process', 'params': {}},
                {'id': 'b', 'type': 'process', 'params': {}},
                {'id': 'c', 'type': 'process', 'params': {}},
                group(),
            ],
            [
                {'from': 'a', 'to': 'g1'},
                {'from': 'b', 'to': 'g1'},
                {'from': 'c', 'to': 'g1'},
            ],
        )
        _, error = expand_reusable_workflow(wf)
        assert '测试组' in error

    def test_an_invalid_template_is_named(self):
        bad_nodes = [
            {'id': 'a', 'type': 'source', 'params': {}},
            {'id': 'c', 'type': 'process', 'params': {}},
        ]
        wf = workflow([group(inputs=('a',), template_nodes=bad_nodes)], [])
        _, error = expand_reusable_workflow(wf)
        assert '测试组' in error

    def test_exactly_one_output_is_required(self):
        wf = workflow([group(inputs=(), outputs=('a', 'b'))], [])
        _, error = expand_reusable_workflow(wf)
        assert '测试组' in error

    def test_a_duplicate_inner_id_is_refused(self):
        nodes = [
            {'id': 'a', 'type': 'process', 'params': {}},
            {'id': 'a', 'type': 'process', 'params': {}},
        ]
        wf = workflow([group(inputs=('a',), outputs=('a',), template_nodes=nodes)], [])
        _, error = expand_reusable_workflow(wf)
        assert '测试组' in error

    def test_a_hand_edited_group_without_a_template_is_named(self):
        broken = copy.deepcopy(group())
        broken['params']['template'] = {}
        _, error = expand_reusable_workflow(workflow([broken], []))
        assert '测试组' in error


class TestCallSites:
    def test_the_scheduled_canvas_gate_sees_an_llm_step_inside_a_group(self):
        """The file keeps the group; the schedule gate must expand before asking for a model,
        or a timer would start a clean step that needs credentials it can never have."""
        from stores import get_workflow_manager

        from engine.run import scheduled_canvas

        manager = get_workflow_manager()

        name = 'reusable-sched-gate'
        draft = {
            'nodes': [
                {
                    'id': 'g1',
                    'type': 'reusable',
                    'params': {
                        'template_name': '组',
                        'template': {
                            'nodes': [{'id': 'a', 'type': 'process', 'params': {'operation': 'clean'}}],
                            'connections': [],
                            'inputs': [],
                            'outputs': ['a'],
                        },
                    },
                }
            ],
            'connections': [],
        }
        try:
            manager.save(name, draft)
            loaded = scheduled_canvas(name)
            assert loaded['workflow'] is None
            assert name in loaded['error']
        finally:
            manager.delete(name)

    def test_both_run_start_and_the_scheduled_canvas_expand_before_using_the_workflow(self):
        from pathlib import Path

        run_source = (Path(__file__).resolve().parents[3] / 'backend' / 'engine' / 'run.py').read_text(encoding='utf-8')
        # Both doors are in this module now (the run start and the scheduled canvas moved together),
        # so the rule is two expansions in the file that owns them — one per door, never one
        # shared assumption about the other.
        assert run_source.count('expand_reusable_workflow(') >= 2, (
            'both begin_run (manual/queued) and scheduled_canvas must expand'
        )
        begin = run_source[run_source.index('def begin_run(') :][:8000]
        assert 'expand_reusable_workflow(' in begin
        scheduled = run_source[run_source.index('def scheduled_canvas(') : run_source.index('def start_scheduled_run(')]
        assert 'expand_reusable_workflow(' in scheduled
        assert scheduled.index('expand_reusable_workflow(') < scheduled.index('workflow_needs_llm('), (
            'the LLM gate must see the expanded children, not the group'
        )
