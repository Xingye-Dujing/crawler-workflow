"""Lifecycle state machines as one transition table, not five if-chains.

A run, a node, an AI turn, a recipe and the workspace view all pause, resume, fail and get
superseded. Written as scattered flags they can reach states no designer meant (a stopped run that
still reports completed, a turn that streams after it settled). This module gives each lifecycle one
declared table: the states, the legal moves, the terminal states. ``require`` refuses every other
move by name.

This is the P1 skeleton. The run engine and the AI turn runner adopt it in their own migrations; the
tables here are the contract those adoptions are checked against, and ``tests/unit/foundation/test_fsm.py``
exhausts every legal and illegal pair.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType


class FsmError(ValueError):
    """An unknown state or an illegal move, named with the machine and both ends."""


@dataclass(frozen=True)
class StateMachine:
    """One lifecycle. Built by :func:`machine`, which refuses an incoherent table."""

    name: str
    initial: str
    transitions: Mapping[str, tuple[str, ...]]
    terminal: frozenset[str]
    states: frozenset[str]

    def targets(self, state: str) -> tuple[str, ...]:
        if state not in self.states:
            raise FsmError(f'{self.name}: unknown state {state!r}')
        return self.transitions.get(state, ())

    def can(self, source: str, target: str) -> bool:
        if target not in self.states:
            raise FsmError(f'{self.name}: unknown state {target!r}')
        return target in self.targets(source)

    def require(self, source: str, target: str) -> str:
        """Return *target* when the move is legal; otherwise refuse by name."""
        if not self.can(source, target):
            raise FsmError(f'{self.name}: illegal transition {source} -> {target}')
        return target

    def is_terminal(self, state: str) -> bool:
        if state not in self.states:
            raise FsmError(f'{self.name}: unknown state {state!r}')
        return state in self.terminal


def machine(
    name: str,
    initial: str,
    transitions: Mapping[str, Iterable[str]],
    terminal: Iterable[str] = (),
) -> StateMachine:
    """Build and validate one table.

    Refused by name: an empty name, an initial state that is terminal, a target/terminal state the
    table never introduces, a terminal state with an outlet, and a non-terminal state with no
    outlet (a lifecycle that can never finish or move).
    """
    if not str(name or '').strip():
        raise FsmError('a state machine needs a name')
    table = {source: tuple(dict.fromkeys(targets)) for source, targets in transitions.items()}
    ends = frozenset(terminal)
    states = {initial} | set(table) | {target for targets in table.values() for target in targets} | set(ends)

    if initial in ends:
        raise FsmError(f'{name}: initial state {initial!r} is terminal')
    if any(not str(state or '').strip() for state in states):
        raise FsmError(f'{name}: a state has an empty name')
    for source in table:
        if source in ends and table[source]:
            raise FsmError(f'{name}: terminal state {source!r} has an outlet')
    for state in sorted(states - ends):
        if not table.get(state):
            raise FsmError(f'{name}: state {state!r} is neither terminal nor able to move')
    return StateMachine(
        name=name,
        initial=initial,
        transitions=MappingProxyType(table),
        terminal=ends,
        states=frozenset(states),
    )


#: A run: queued by the queue, started by the worker, settled once, then a verdict.
RUN = machine(
    'RunFSM',
    initial='queued',
    transitions={
        'queued': ('starting', 'stopped'),
        'starting': ('running', 'failed', 'interrupted', 'stopped'),
        'running': ('stopping', 'settling', 'failed', 'interrupted'),
        'stopping': ('settling', 'stopped', 'interrupted'),
        'settling': ('completed', 'failed', 'stopped', 'interrupted'),
    },
    terminal=('completed', 'failed', 'stopped', 'interrupted'),
)

#: A node: pending until its upstream settles, then one attempt, then the store's verdict.
#: ``restored`` is reuse of a previous attempt, not a failure; ``partial`` did write rows.
NODE = machine(
    'NodeFSM',
    initial='pending',
    transitions={
        'pending': ('blocked', 'ready', 'restored', 'skipped', 'stopped'),
        'blocked': ('ready', 'restored', 'skipped', 'stopped'),
        'ready': ('running', 'restored', 'skipped', 'stopped'),
        'running': ('done', 'partial', 'failed', 'stopped', 'restored'),
    },
    terminal=('done', 'partial', 'failed', 'skipped', 'stopped', 'restored'),
)

#: One AI turn. ``awaiting_user`` is a durable interrupt (question/approval), not a blocked thread:
#: its answer re-enters streaming. A turn that settled never streams again.
TURN = machine(
    'TurnFSM',
    initial='new',
    transitions={
        'new': ('context', 'interrupted'),
        'context': ('streaming', 'interrupted'),
        'streaming': ('tool', 'awaiting_user', 'settled', 'interrupted'),
        'tool': ('streaming', 'awaiting_user', 'interrupted'),
        'awaiting_user': ('streaming', 'interrupted'),
    },
    terminal=('settled', 'interrupted'),
)

#: The workspace view. Every open surface can reach every other surface, and closing is always
#: allowed; the point is that switching panels is a state, not a pile of booleans.
VIEW_STATES = ('closed', 'docked', 'full', 'settings', 'studio', 'skills')
VIEW = machine(
    'ViewFSM',
    initial='closed',
    transitions={state: tuple(other for other in VIEW_STATES if other != state) for state in VIEW_STATES},
)

#: Fixed lifecycles a caller may ask for by name. ``recipe`` is parameterised by its step count.
MACHINES = {'run': RUN, 'node': NODE, 'turn': TURN, 'view': VIEW}


def machine_for(name: str) -> StateMachine:
    key = str(name or '')
    if key == 'recipe':
        raise FsmError('RecipeFSM is parameterised; call recipe_machine(steps)')
    machine_ = MACHINES.get(key)
    if machine_ is None:
        raise FsmError(f'unknown state machine {name!r}; known: {", ".join(sorted(MACHINES))}, recipe')
    return machine_


def recipe_machine(steps: int) -> StateMachine:
    """A recipe's linear lifecycle: ``created → step_1 … step_n → done``.

    A step is skipped by advancing to the next one and recording the skip as evidence; the state
    table has no ``skipped`` node because the recipe itself did not stop. A recipe with no step is
    refused: it would be a lifecycle that begins finished.
    """
    count = int(steps)
    if count < 1:
        raise FsmError('a recipe needs at least one step')
    names = [f'step_{index}' for index in range(1, count + 1)]
    transitions: dict[str, tuple[str, ...]] = {'created': (names[0],)}
    for index, state in enumerate(names):
        transitions[state] = (names[index + 1],) if index + 1 < count else ('done',)
    return machine('RecipeFSM', initial='created', transitions=transitions, terminal=('done',))
