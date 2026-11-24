"""The test value inventory is current and honest.

``docs/testing/value-inventory.md`` is generated from the suite with ``ast``; this gate refuses a
stale copy, and refuses a test that asserts nothing unless ``tools/test_inventory.py`` records WHY
it is still a test. That is the P8 rule made executable: a case earns its runtime by proving
something, or by saying in one line what it proves instead.
"""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / 'tools' / 'test_inventory.py'


def _tool():
    spec = importlib.util.spec_from_file_location('test_inventory', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTheInventoryIsCurrent:
    def test_the_committed_page_matches_the_suite(self):
        assert _tool().check() == [], 'run `python tools/test_inventory.py` and commit the page'

    def test_no_test_asserts_nothing_without_a_written_reason(self):
        data = _tool().inventory()
        assert data['flagged_no_assert'] == [], 'these tests assert nothing and carry no reason: ' + '; '.join(
            f'{row["file"]}: {", ".join(row["names"])}' for row in data['flagged_no_assert']
        )

    def test_the_no_assert_count_is_the_pinned_one(self):
        data = _tool().inventory()
        assert data['totals']['no_assert'] == _tool().NO_ASSERT_TOTAL, (
            'a case that asserts nothing was added or removed: assert something, or record the reason and the new total'
        )

    def test_the_inventory_sees_the_suite(self):
        data = _tool().inventory()
        assert data['totals']['files'] > 300, data['totals']
        assert data['totals']['cases'] > 5000, data['totals']
