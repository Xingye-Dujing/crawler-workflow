"""The capability × test matrix is current, complete, and honest.

``docs/capabilities/matrix.md`` maps every manifest to its declared contract tests and to any test
file named after it. The page deliberately does not infer coverage from string matches, so this gate
checks the three things that are facts: the page is fresh, every capability is on it, and it names
the dedicated tests whose files exist today (a scan that saw nothing would pass over everything).
"""

import importlib.util
from pathlib import Path

import pytest
from capabilities_kernel import registry

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / 'tools' / 'gen_capability_matrix.py'
KINDS = ('node', 'operator', 'chart', 'platform')


def _tool():
    spec = importlib.util.spec_from_file_location('gen_capability_matrix', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTheMatrixIsCurrent:
    def test_the_committed_page_matches_the_suite(self):
        assert _tool().check() == [], 'run `python tools/gen_capability_matrix.py` and commit the page'

    def test_every_capability_is_listed(self):
        rows = _tool().matrix()
        listed = {(row['kind'], row['id']) for row in rows}
        declared = {(kind, manifest.identity.id) for kind in KINDS for manifest in registry.manifests(kind)}
        assert listed == declared
        assert len(rows) > 80, 'the scan found almost nothing — this gate would pass over everything'

    def test_every_listed_dedicated_file_exists(self):
        for row in _tool().matrix():
            for path in row['dedicated']:
                assert (ROOT / path).is_file(), f'{row["kind"]}.{row["id"]}: {path} is gone'

    def test_the_scan_still_sees_the_dedicated_tests(self):
        rows = _tool().matrix()
        assert sum(1 for row in rows if row['dedicated']) >= 15, 'no capability has a dedicated test file'
