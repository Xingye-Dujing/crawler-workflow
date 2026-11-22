"""Every event a producer publishes is declared, and every declared field is what it sends.

The bus accepts any dict, so a producer that starts sending ``rows=...`` under a new name, or a
monitor that subscribes to an event nobody publishes, is invisible at run time. This gate reads the
call sites with ``ast`` — the same approach the console-seam census uses — and joins them to
``runtime.events.EVENTS``. The validating wrapper in ``runtime/events.py`` is the one dynamic call
site and is named explicitly, so a second dynamic name cannot hide.
"""

import ast
from pathlib import Path

import pytest
from ai import monitors
from runtime import events

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / 'backend'
WRAPPER = 'runtime/events.py'


def _publish_calls():
    """(file, line, event name or None, keyword names) for every ``run_events.publish`` call."""
    calls = []
    for path in sorted(BACKEND.rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'), str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == 'publish'):
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id == 'run_events'):
                continue
            name = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
            keywords = [keyword.arg for keyword in node.keywords]
            calls.append((path.relative_to(BACKEND).as_posix(), node.lineno, name, keywords))
    return calls


CALLS = _publish_calls()


class TestEveryProducerIsCovered:
    def test_the_scan_finds_the_four_run_producers(self):
        assert len(CALLS) >= 4, f'the gate found only {CALLS} — the AST stopped matching'

    def test_only_the_validating_wrapper_publishes_a_dynamic_name(self):
        dynamic = {file for file, _line, name, _keywords in CALLS if name is None}
        assert dynamic <= {WRAPPER}, f'dynamic event names outside the wrapper: {sorted(dynamic)}'

    def test_every_literal_event_name_is_declared(self):
        unknown = sorted({name for _file, _line, name, _keywords in CALLS if name and name not in events.EVENTS})
        assert unknown == [], f'published but not declared: {unknown}'

    def test_every_keyword_is_a_declared_field(self):
        bad = []
        for file, line, name, keywords in CALLS:
            if name not in events.EVENTS:
                continue
            declared = {field.name for field in events.EVENTS[name].fields}
            for keyword in keywords:
                if keyword is None:
                    bad.append(f'{file}:{line} uses **kwargs for {name}')
                elif keyword not in declared:
                    bad.append(f'{file}:{line} sends {name}.{keyword}')
        assert bad == [], 'undeclared event fields: ' + '; '.join(bad)

    def test_every_required_field_is_present(self):
        bad = []
        for file, line, name, keywords in CALLS:
            if name not in events.EVENTS:
                continue
            present = set(keywords)
            for field in events.EVENTS[name].fields:
                if field.required and field.name not in present:
                    bad.append(f'{file}:{line} omits {name}.{field.name}')
        assert bad == [], 'missing required event fields: ' + '; '.join(bad)

    def test_the_monitors_vocabulary_is_exactly_the_declared_events(self):
        assert tuple(events.EVENTS) == tuple(monitors.EVENTS)
