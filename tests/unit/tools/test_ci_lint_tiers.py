"""The portable lint-target enumerator, tested without spawning pylint.

The workflow's old PowerShell enumeration was a Windows fact in a gate that claims to protect
three systems. These cases pin the replacement's contract: explicit files, both roots, a stable
order, the same standard on every tier, and a refusal — not a green run — over an empty tree.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
MODULE = REPO / 'tools' / 'ci_lint_tiers.py'


@pytest.fixture(scope='module')
def linting():
    spec = importlib.util.spec_from_file_location('ci_lint_tiers', MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(root: Path) -> None:
    files = (
        'backend/app.py',
        'backend/services/engine.py',
        'backend/test_probe.py',
        'desktop/desktop_entry.py',
        'tools/build_icon.py',
        'ml_train/scripts/train.py',
        'ml_train/not_linted.py',
        'tests/unit/test_one.py',
        'tests/api/helpers.py',
    )
    for relative in files:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('x = 1\n', encoding='utf-8')


def test_product_targets_are_explicit_files_and_skip_the_measurement_probes(linting, tmp_path):
    _tree(tmp_path)
    names = [path.relative_to(tmp_path).as_posix() for path in linting.targets('product', root=tmp_path)]
    assert names == [
        'backend/app.py',
        'backend/services/engine.py',
        'desktop/desktop_entry.py',
        'ml_train/scripts/train.py',
        'tools/build_icon.py',
    ]
    assert 'backend/test_probe.py' not in names, 'the probes tier is local-only'
    assert not any(path.endswith('/') for path in names), 'pylint must receive files, never directories'


def test_tests_targets_are_recursive(linting, tmp_path):
    _tree(tmp_path)
    names = [path.relative_to(tmp_path).as_posix() for path in linting.targets('tests', root=tmp_path)]
    assert names == ['tests/api/helpers.py', 'tests/unit/test_one.py']


def test_the_command_carries_the_standard_the_rcfile_and_the_files(linting, tmp_path):
    _tree(tmp_path)
    files = linting.targets('tests', root=tmp_path)
    command = linting.command('tests', files)
    assert command[:3] == [sys.executable, '-m', 'pylint']
    assert '--rcfile=.pylintrc.tests' in command
    assert '--persistent=n' in command and '--jobs=2' in command
    assert '--disable=C,R' in command and '--fail-on=W,E,F' in command
    assert command[-2:] == [str(path) for path in files]


def test_repository_targets_are_relative_to_the_invocation_cwd(linting, tmp_path, monkeypatch):
    """The absolute path pushed the product tier over Windows' 32,767-character limit."""
    file = tmp_path / 'backend' / 'app.py'
    file.parent.mkdir(parents=True)
    file.write_text('x = 1\n', encoding='utf-8')
    monkeypatch.setattr(linting, 'REPO', tmp_path)
    command = linting.command('product', [file])
    assert Path(command[-1]).as_posix() == 'backend/app.py'
    assert len(str(file)) > len(command[-1])


def test_an_empty_tier_is_refused_by_name(linting, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(linting, 'REPO', tmp_path)
    code = linting.main(['product'])
    assert code == 1
    assert 'no product sources found to lint' in capsys.readouterr().err


def test_main_runs_pylint_from_the_repository_root(linting, tmp_path, monkeypatch, capsys):
    _tree(tmp_path)
    monkeypatch.setattr(linting, 'REPO', tmp_path)
    seen = {}

    def record(command, cwd=None, check=False):
        seen.update(command=command, cwd=cwd, check=check)
        return type('Result', (), {'returncode': 0})()

    monkeypatch.setattr(linting.subprocess, 'run', record)
    assert linting.main(['product']) == 0
    assert seen['cwd'] == tmp_path
    assert seen['check'] is False
    assert 'linting 5 product files' in capsys.readouterr().out
    assert seen['command'][3:7] == ['--persistent=n', '--disable=C,R', '--fail-on=W,E,F', '--jobs=2']
