"""Every registered capability must have an AI entry; a missing cell fails CI, not the user."""

import pytest

pytestmark = pytest.mark.unit


def test_every_capability_has_an_ai_entry():
    from ai import coverage

    report = coverage.audit()
    assert report['ok'] is True, report['missing']
    assert report['totals']['missing'] == 0
    for name, family in report['families'].items():
        assert family['total'] > 0, f'{name} enumerated nothing; a green cell would be vacuous'
        assert family['covered'] == family['total'], (name, family['missing'])


def test_the_matrix_names_the_entry_for_each_family():
    from ai import coverage

    entries = {name: family['entry'] for name, family in coverage.audit()['families'].items()}
    assert entries == {
        'workflow_nodes': 'workflow_schema',
        'platform_modes': 'capabilities',
        'analysis_ops': 'analysis_catalog',
        'chart_types': 'chart_catalog',
        'tools': 'skill tools + universal',
    }


def test_a_tool_with_no_skill_or_universal_entry_is_reported(monkeypatch):
    """The gate must be able to fail: drop every skill's tool list and a known specialized tool
    (dataset_page is not in the universal set) must appear as a missing cell."""
    from ai import coverage, skills

    monkeypatch.setattr(skills, 'all_skills', lambda: {})
    report = coverage.audit()
    assert report['ok'] is False
    assert 'dataset_page' in report['missing']['tools']


def test_the_coverage_tool_is_itself_reachable():
    from ai import agent, tools

    assert 'ai_coverage' in agent.UNIVERSAL_TOOLS
    assert 'ai_coverage' in tools.TOOLS
