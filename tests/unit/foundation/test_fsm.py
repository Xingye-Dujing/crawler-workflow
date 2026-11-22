"""Every lifecycle table is exhaustive and every illegal move is refused by name.

The tables are the contract the run/turn migrations adopt, so a missing edge is not a test detail:
it is a transition the engine will one day attempt and be refused. The exhaustive pair check makes
that visible now, on a table small enough to read.
"""

import pytest
from runtime import fsm

pytestmark = pytest.mark.unit

TABLES = [fsm.RUN, fsm.NODE, fsm.TURN, fsm.VIEW]


@pytest.mark.parametrize('table', TABLES, ids=lambda table: table.name)
class TestTheDeclaredTable:
    def test_the_initial_state_is_not_terminal_and_belongs(self, table):
        assert table.initial in table.states
        assert not table.is_terminal(table.initial)

    def test_every_terminal_state_has_no_outlet(self, table):
        for state in table.terminal:
            assert table.targets(state) == (), state

    def test_every_non_terminal_state_can_move(self, table):
        for state in table.states - table.terminal:
            assert table.targets(state), f'{table.name}: {state} is a dead end'

    def test_every_declared_edge_is_allowed_and_every_other_pair_refused(self, table):
        for source in table.states:
            allowed = set(table.targets(source))
            for target in table.states:
                if target in allowed:
                    assert table.require(source, target) == target
                else:
                    with pytest.raises(fsm.FsmError, match=f'{table.name}: illegal transition {source} -> {target}'):
                        table.require(source, target)

    def test_an_unknown_state_is_named(self, table):
        with pytest.raises(fsm.FsmError, match=f'{table.name}: unknown state .*moonbase'):
            table.require('moonbase', table.initial)
        with pytest.raises(fsm.FsmError, match=f'{table.name}: unknown state .*moonbase'):
            table.require(table.initial, 'moonbase')


class TestTheSpecificLifecycles:
    def test_a_run_settles_before_it_completes(self):
        assert not fsm.RUN.can('running', 'completed')
        assert fsm.RUN.require('running', 'settling') == 'settling'
        assert fsm.RUN.require('settling', 'completed') == 'completed'
        assert fsm.RUN.is_terminal('stopped')
        assert fsm.RUN.targets('queued') == ('starting', 'stopped')

    def test_a_node_restored_is_terminal_but_not_a_failure(self):
        assert fsm.NODE.require('pending', 'restored') == 'restored'
        assert fsm.NODE.is_terminal('restored')
        assert set(fsm.NODE.terminal) == {'done', 'partial', 'failed', 'skipped', 'stopped', 'restored'}

    def test_a_settled_turn_never_streams_again(self):
        assert fsm.TURN.is_terminal('settled')
        with pytest.raises(fsm.FsmError, match='settled -> streaming'):
            fsm.TURN.require('settled', 'streaming')
        assert fsm.TURN.require('awaiting_user', 'streaming') == 'streaming'

    def test_the_view_can_switch_between_every_surface(self):
        for source in fsm.VIEW_STATES:
            for target in fsm.VIEW_STATES:
                if source != target:
                    assert fsm.VIEW.require(source, target) == target


class TestRecipes:
    def test_a_recipe_walks_its_steps_in_order(self):
        table = fsm.recipe_machine(3)
        assert table.require('created', 'step_1') == 'step_1'
        assert table.require('step_1', 'step_2') == 'step_2'
        assert table.require('step_2', 'step_3') == 'step_3'
        assert table.require('step_3', 'done') == 'done'
        assert table.is_terminal('done')

    def test_a_step_cannot_be_skipped(self):
        table = fsm.recipe_machine(3)
        with pytest.raises(fsm.FsmError, match='step_1 -> step_3'):
            table.require('step_1', 'step_3')

    def test_a_recipe_with_no_step_is_refused(self):
        with pytest.raises(fsm.FsmError, match='at least one step'):
            fsm.recipe_machine(0)

    def test_the_parameterised_recipe_is_not_asked_for_by_name(self):
        with pytest.raises(fsm.FsmError, match='recipe_machine'):
            fsm.machine_for('recipe')


class TestTheBuilderRefusesIncoherentTables:
    def test_a_table_needs_a_name(self):
        with pytest.raises(fsm.FsmError, match='needs a name'):
            fsm.machine('', initial='a', transitions={'a': ('b',)})

    def test_an_initial_terminal_state_is_refused(self):
        with pytest.raises(fsm.FsmError, match='initial state'):
            fsm.machine('X', initial='a', transitions={'a': ()}, terminal=('a',))

    def test_a_terminal_state_with_an_outlet_is_refused(self):
        with pytest.raises(fsm.FsmError, match='terminal state'):
            fsm.machine('X', initial='a', transitions={'a': ('b',), 'b': ('a',)}, terminal=('b',))

    def test_a_dead_end_that_is_not_terminal_is_refused(self):
        with pytest.raises(fsm.FsmError, match='neither terminal'):
            fsm.machine('X', initial='a', transitions={'a': ('b',), 'b': ()})

    def test_an_empty_state_name_is_refused(self):
        with pytest.raises(fsm.FsmError, match='empty name'):
            fsm.machine('X', initial='', transitions={'': ('b',)}, terminal=('b',))

    def test_an_unknown_machine_is_named(self):
        with pytest.raises(fsm.FsmError, match='unknown state machine'):
            fsm.machine_for('moonbase')

    def test_the_registry_serves_the_same_objects(self):
        assert fsm.machine_for('run') is fsm.RUN
        assert fsm.machine_for('node') is fsm.NODE
        assert fsm.machine_for('turn') is fsm.TURN
        assert fsm.machine_for('view') is fsm.VIEW
