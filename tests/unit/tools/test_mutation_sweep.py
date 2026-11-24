"""The mutation sweep: which decisions a suite actually checks.

The tool is not a gate, so these cases pin its two claims rather than a survivor count:
what counts as a mutation (a decision, not a cosmetically edited line), and that applying one
changes exactly that site — inside a COPY, never the checkout.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
MODULE = REPO / 'tools' / 'mutation_sweep.py'


@pytest.fixture(scope='module')
def sweep():
    spec = importlib.util.spec_from_file_location('mutation_sweep', MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules['mutation_sweep'] = module
    spec.loader.exec_module(module)
    return module


SNIPPET = """\
def decide(flag, other, size):
    if size > 3 and flag:
        return 'big'
    if not other:
        return 'none'
    return 'small' if size == 3 else 'odd'
"""


class TestWhatCountsAsAMutation:
    def test_a_comparison_a_bool_op_a_dropped_not_and_a_number(self, sweep):
        found = sweep.mutations(SNIPPET)
        described = [(item.lineno, item.description) for item in found]
        assert (2, 'Gt -> LtE') in described
        assert (2, 'And -> Or') in described
        assert (4, 'not -> (dropped)') in described
        assert (2, '3 -> 4') in described
        assert (6, 'Eq -> NotEq') in described

    def test_a_docstring_a_log_line_and_arithmetic_are_not_sites(self, sweep):
        source = '''\
"""A docstring that explains things."""

def add(left, right):
    total = left + 1
    print(f'{total} rows')
    return total + right
'''
        assert sweep.mutations(source) == []

    def test_every_site_produces_a_module_that_parses(self, sweep):
        sites = sweep.mutations(SNIPPET)
        assert len(sites) >= 5
        mutants = [sweep.mutate(SNIPPET, index) for index in range(len(sites))]
        assert [ast.parse(source) is not None for source in mutants] == [True] * len(sites)

    def test_applying_one_mutation_changes_only_that_site(self, sweep):
        source = 'lambda a, b: a == b'
        mutated = sweep.mutate(source, 0)
        assert '==' in source and '!=' not in source
        assert '!=' in mutated and '==' not in mutated

    def test_an_out_of_range_index_is_named(self, sweep):
        with pytest.raises(IndexError, match='out of range'):
            sweep.mutate('x = 1\n', 0)


@pytest.fixture
def synthetic_repo(tmp_path):
    """A tiny checkout: one module, one test file that checks only its first decision."""
    root = tmp_path / 'repo'
    (root / 'backend').mkdir(parents=True)
    (root / 'tests').mkdir()
    (root / 'pytest.ini').write_text('[pytest]\naddopts = -q\n', encoding='utf-8')
    (root / 'tests' / 'conftest.py').write_text(
        'import sys\n'
        'from pathlib import Path\n'
        'sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))\n',
        encoding='utf-8',
    )
    (root / 'backend' / 'rules.py').write_text(
        "def bigger(left, right):\n    return left > right\n\n\ndef label(flag):\n    return 'on' if flag else 'off'\n",
        encoding='utf-8',
    )
    (root / 'tests' / 'test_rules.py').write_text(
        'from rules import bigger\n\n\ndef test_bigger():\n    assert bigger(2, 1)\n    assert not bigger(1, 2)\n',
        encoding='utf-8',
    )
    return root


class TestSweepingATarget:
    def test_it_kills_what_is_checked(self, synthetic_repo, sweep):
        result = sweep.run_target(
            synthetic_repo,
            'backend/rules.py',
            'tests/test_rules.py',
            synthetic_repo,
            python=sys.executable,
            timeout=90,
        )
        assert result.error == ''
        assert result.total == 1
        assert result.killed == 1
        assert result.survivors == []

    def test_a_test_file_that_never_looks_names_the_survivors(self, synthetic_repo, sweep):
        (synthetic_repo / 'tests' / 'test_rules.py').write_text(
            'from rules import label\n\n\ndef test_label():\n    assert label(True) == "on"\n',
            encoding='utf-8',
        )
        result = sweep.run_target(
            synthetic_repo,
            'backend/rules.py',
            'tests/test_rules.py',
            synthetic_repo,
            python=sys.executable,
            timeout=90,
        )
        assert result.error == ''
        # `left > right` is never exercised by this file: its mutant survives, by name.
        assert [item.lineno for item in result.survivors] == [2]

    def test_a_missing_module_is_an_error_not_a_crash(self, tmp_path, sweep):
        result = sweep.run_target(tmp_path, 'backend/nope.py', 'tests/test_x.py', tmp_path)
        assert 'no such module' in result.error

    def test_a_missing_test_file_is_an_error(self, synthetic_repo, sweep):
        result = sweep.run_target(synthetic_repo, 'backend/rules.py', 'tests/test_nope.py', synthetic_repo)
        assert 'no such test' in result.error

    def test_a_target_whose_tests_already_fail_is_named_before_any_mutant(self, synthetic_repo, sweep):
        """A red baseline would "kill" every mutant and report a suite that proves nothing."""
        (synthetic_repo / 'tests' / 'test_rules.py').write_text(
            'def test_always_red():\n    assert False\n',
            encoding='utf-8',
        )
        result = sweep.run_target(
            synthetic_repo,
            'backend/rules.py',
            'tests/test_rules.py',
            synthetic_repo,
            python=sys.executable,
            timeout=90,
        )
        assert 'do not pass unmutated' in result.error
        assert result.killed == 0 and result.survivors == []


class TestTheCopyIsTheOnlyThingMutated:
    def test_sweep_leaves_the_checkout_byte_identical(self, synthetic_repo, sweep):
        module = synthetic_repo / 'backend' / 'rules.py'
        before = module.read_bytes()
        results = sweep.sweep(
            synthetic_repo,
            (('backend/rules.py', 'tests/test_rules.py'),),
            python=sys.executable,
            timeout=90,
        )
        assert [item.total for item in results] == [1]
        assert module.read_bytes() == before

    def test_the_report_names_each_survivor_by_its_original_line(self, sweep):
        result = sweep.TargetResult('backend/core/values.py', 'tests/unit/foundation/test_utils.py')
        result.mutations = [sweep.Mutation(31, 4, 'Gt -> LtE')]
        result.survivors = list(result.mutations)
        page = sweep.render([result], moment='2026-11-25')
        assert '`backend/core/values.py:31`' in page
        assert 'Gt -> LtE' in page
        assert '| 1 | 0 | 1 |' in page

    def test_a_clean_sweep_says_so_instead_of_an_empty_table(self, sweep):
        result = sweep.TargetResult('backend/core/values.py', 'tests/unit/foundation/test_utils.py')
        page = sweep.render([result])
        assert '无：点名的测试捕获了每一个变异。' in page
