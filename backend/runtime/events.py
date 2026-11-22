"""The event contract: names and payloads are data, validated before a listener sees them.

``runtime/run_events.py`` is the bus — it delivers whatever dict it is handed and must never raise
into a run. That is the right shape for a notification channel and the wrong shape for a contract:
a producer that renames a field, a monitor that subscribes to an event nobody publishes, or a
convenience f-string in place of a count all pass silently. This module is the contract half.

The four run events are declared once with their required fields and JSON-ish types. New producers
call :func:`publish` (validate, then hand the bus the same values); existing ``run_events.publish``
call sites are checked by ``tests/unit/gates/test_event_contract.py`` until they migrate. Events
carry ids, statuses and counts — never crawled text; that rule is the bus's, restated here because
this is where a producer looks first.
"""

from __future__ import annotations

from dataclasses import dataclass

from runtime import run_events


class EventError(ValueError):
    """An undeclared event or a payload that does not match its declaration."""


@dataclass(frozen=True)
class Field:
    """One payload field. ``kind`` is the small vocabulary the validator knows."""

    name: str
    kind: str
    required: bool = True


_KINDS = {
    'str': (str,),
    'int': (int,),
    'bool': (bool,),
    'list[str]': (list,),
    'int|None': (int, type(None)),
}


@dataclass(frozen=True)
class EventSpec:
    name: str
    fields: tuple[Field, ...]

    def field(self, name: str) -> Field | None:
        for item in self.fields:
            if item.name == name:
                return item
        return None

    def validate(self, values: dict) -> dict:
        declared = {item.name: item for item in self.fields}
        unknown = sorted(set(values) - set(declared))
        missing = sorted(item.name for item in self.fields if item.required and item.name not in values)
        wrong = []
        for name, value in values.items():
            spec = declared.get(name)
            if spec is None:
                continue
            if spec.kind in ('int', 'int|None') and isinstance(value, bool):
                wrong.append(f'{name} is bool, not {spec.kind}')
            elif spec.kind == 'list[str]':
                if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                    wrong.append(f'{name} is not list[str]')
            elif not isinstance(value, _KINDS[spec.kind]):
                wrong.append(f'{name} is {type(value).__name__}, not {spec.kind}')
        if unknown or missing or wrong:
            parts = []
            if unknown:
                parts.append(f'unknown field(s) {", ".join(unknown)}')
            if missing:
                parts.append(f'missing {", ".join(missing)}')
            if wrong:
                parts.append('; '.join(wrong))
            raise EventError(f'{self.name}: ' + '; '.join(parts))
        return dict(values)


#: The run events, in the order monitors name them. A new event is a declaration plus its producer;
#: an event no monitor may subscribe to is deliberately not in ``ai.monitors.EVENTS``.
EVENTS: dict[str, EventSpec] = {
    'run.started': EventSpec(
        'run.started',
        (
            Field('run_id', 'str'),
            Field('workflow', 'str'),
            Field('wf_idx', 'int'),
            Field('resume', 'bool'),
        ),
    ),
    'node.finished': EventSpec(
        'node.finished',
        (
            Field('run_id', 'str'),
            Field('node_id', 'str'),
            Field('node_type', 'str'),
            Field('label', 'str'),
            Field('status', 'str'),
            Field('rows', 'int'),
            Field('wf_idx', 'int'),
            Field('workflow', 'str'),
        ),
    ),
    'run.finished': EventSpec(
        'run.finished',
        (
            Field('run_id', 'str'),
            Field('records', 'list[str]'),
            Field('workflow', 'str'),
            Field('outcome', 'str'),
            Field('done', 'int'),
            Field('total', 'int'),
            Field('failed', 'int'),
            Field('skipped', 'int'),
        ),
    ),
    'run.log': EventSpec(
        'run.log',
        (
            Field('run_id', 'str'),
            Field('line', 'str'),
            Field('wf_idx', 'int|None'),
            Field('level', 'str'),
        ),
    ),
}


def validate(name: str, values: dict) -> dict:
    """The declared payload for *name*, or a refusal naming the event and the mismatched field."""
    spec = EVENTS.get(str(name or ''))
    if spec is None:
        raise EventError(f'unknown event {name!r}; declared: {", ".join(EVENTS)}')
    return spec.validate(values)


def publish(name: str, **fields) -> None:
    """Validate one fact and hand it to the bus. A producer bug raises before any listener sees it.

    The bus itself still never raises into a run: this function is for producers that have adopted
    the contract, and a wrong payload is a programming error caught by its tests, not a crawl fact.
    """
    run_events.publish(name, **validate(name, fields))
