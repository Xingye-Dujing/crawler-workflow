"""The release-version gate: a dispatch placeholder must not be stamped onto a real build."""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
MODULE = REPO / 'tools' / 'check_release_version.py'


@pytest.fixture(scope='module')
def checker():
    spec = importlib.util.spec_from_file_location('check_release_version', MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_prefix_of_app_version_is_accepted(checker):
    current = checker.app_version()
    assert checker.check('.'.join(current.split('.')[:3])) == '.'.join(current.split('.')[:3])


def test_the_workflow_placeholder_is_refused(checker):
    with pytest.raises(SystemExit):
        checker.check('1.0.0')


def test_a_bare_or_two_group_value_is_refused(checker):
    for value in ('', '2026', '2026.11'):
        with pytest.raises(SystemExit):
            checker.check(value)
