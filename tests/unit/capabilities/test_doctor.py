"""The doctor answers the same questions as the gate, and can fail by name.

A doctor that only prints green checkmarks is a report, not a gate. These cases pin both halves:
every live dimension is checked for the pilot, and a broken handler/contract produces a failed row
that names the capability and the dimension — never a traceback.
"""

from dataclasses import replace

import pytest
from capabilities_kernel import doctor, registry

pytestmark = pytest.mark.unit


def _manifest():
    manifest = registry.manifest_for_node('tokenize')
    assert manifest is not None
    return manifest


class TestTheGreenReport:
    def test_every_pilot_row_is_checked_and_the_artifacts_are_fresh(self):
        rows = doctor.check_all()
        assert {(row['capability'], row['name']) for row in rows} >= {
            ('node:tokenize', name) for name in ('structure', 'executor', 'port_hooks', 'docs', 'contracts')
        }
        assert all(row['ok'] for row in rows), [row for row in rows if not row['ok']]

    def test_the_report_prints_a_checkbox_per_row(self):
        text = doctor.report(doctor.check_all(['node:tokenize']))
        assert 'node:tokenize' in text
        assert '[x] executor' in text

    def test_legacy_types_are_named_not_failed(self):
        legacy = doctor.legacy_node_types()
        assert 'tokenize' not in legacy
        assert 'analysis' in legacy, 'P2 has not moved analysis yet; the doctor should say so'


class TestAFailureIsNamed:
    def test_a_handler_that_cannot_import_fails_the_executor_row(self):
        broken = replace(_manifest(), execution=replace(_manifest().execution, handler='moonbase.run:go'))
        rows = doctor.capability_rows(broken)
        executor = next(row for row in rows if row['name'] == 'executor')
        assert executor['ok'] is False
        assert 'moonbase' in executor['detail']

    def test_a_missing_contract_or_page_fails_its_row(self):
        broken = replace(
            _manifest(),
            docs=replace(_manifest().docs, page='docs/capabilities/nodes/gone.md'),
            tests=replace(_manifest().tests, contracts=('tests/unit/capabilities/gone.py',)),
        )
        rows = {row['name']: row for row in doctor.capability_rows(broken)}
        assert rows['docs']['ok'] is False and 'gone.md' in rows['docs']['detail']
        assert rows['contracts']['ok'] is False and 'gone.py' in rows['contracts']['detail']

    def test_a_broken_validator_fails_its_row(self):
        broken = replace(_manifest(), validators=('moonbase.validate:check',))
        rows = {row['name']: row for row in doctor.capability_rows(broken)}
        assert rows['validators']['ok'] is False
        assert 'moonbase' in rows['validators']['detail']

    def test_an_unknown_filter_is_a_failed_row_not_an_empty_green_report(self):
        rows = doctor.check_all(['node:moonbase'])
        assert [(row['capability'], row['ok']) for row in rows] == [('node:moonbase', False)]
        assert 'no such manifest' in rows[0]['detail']
