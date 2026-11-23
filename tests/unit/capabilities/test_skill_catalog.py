"""The capability skill: one L1 catalogue, one L2 body, both derived from the manifest.

These cases pin the derivation rather than a document: the parameter table is read at render time,
the negative triggers are part of the selection text, and the generated page is the same function
the ``skill_load`` tool calls.
"""

import dataclasses

import pytest
from capabilities_kernel import knowledge, registry
from capabilities_kernel.manifest import Ai

pytestmark = pytest.mark.unit


def _nodes():
    return registry.manifests('node')


class TestTheCatalogue:
    def test_every_node_has_one_skill_and_every_skill_resolves(self):
        rows = knowledge.catalog(kind='node')
        assert len(rows) == len(_nodes())
        assert len({row['id'] for row in rows}) == len(rows)
        for row in rows:
            assert knowledge.find(row['id']) is not None

    def test_the_level_one_record_does_not_carry_the_body(self):
        row = knowledge.catalog(kind='node')[0]
        assert set(row) == {
            'id',
            'kind',
            'capability',
            'category',
            'title_key',
            'summary',
            'when_to_use',
            'when_not_to_use',
            'docs',
        }

    def test_a_query_ranks_the_capability_it_names_first(self):
        rows = knowledge.catalog(query='评论 comment')
        assert rows, 'a query with a capability word found nothing'
        assert rows[0]['id'] == 'node.comment'

    def test_an_unknown_kind_is_refused_with_the_known_kinds(self):
        with pytest.raises(ValueError, match='known kinds'):
            knowledge.catalog(kind='not-a-kind')

    def test_a_limit_truncates_but_zero_means_all(self):
        assert len(knowledge.catalog(kind='node', limit=3)) == 3
        assert len(knowledge.catalog(kind='node', limit=0)) == len(_nodes())

    def test_find_accepts_the_address_or_a_bare_id(self):
        manifest = knowledge.find('node.analysis')
        assert manifest is not None and manifest.identity.id == 'analysis'
        assert knowledge.find('analysis', kind='node') is not None
        assert knowledge.find('node.no_such_capability') is None

    def test_the_prompt_lines_name_every_skill_with_its_summary(self):
        lines = knowledge.prompt_lines()
        assert len(lines) == len(_nodes())
        assert all(line.startswith('- node.') for line in lines)


class TestTheBody:
    def test_the_seven_sections_are_present(self):
        body = knowledge.render(knowledge.find('node.process'))
        for heading in (
            '## When to use',
            '## Prerequisites',
            '## Steps',
            '## Examples',
            '## Template JSON',
            '## Parameters',
            '## Failure modes',
            '## Acceptance',
        ):
            assert heading in body, heading

    def test_the_parameter_table_is_read_from_the_manifest_now(self):
        manifest = knowledge.find('node.analysis')
        body = knowledge.render(manifest)
        for spec in manifest.params:
            assert f'| `{spec.name}` |' in body

    def test_editing_a_default_changes_the_rendered_body(self):
        manifest = knowledge.find('node.tokenize')
        changed = dataclasses.replace(
            manifest,
            params=tuple(
                dataclasses.replace(spec, default='99') if spec.name == 'top_n' else spec for spec in manifest.params
            ),
        )
        body = knowledge.render(changed)
        assert '| `top_n` | string | `99` |' in body
        assert '| `top_n` | string | `120` |' not in body

    def test_an_empty_section_is_printed_as_declared_not_omitted(self):
        manifest = knowledge.find('node.output')
        bare = dataclasses.replace(manifest, ai=Ai(summary=manifest.ai.summary))
        body = knowledge.render(bare)
        assert '## Acceptance' in body
        assert '- (none declared)' in body

    def test_the_template_and_examples_are_printed_as_json(self):
        manifest = knowledge.find('node.visualize')
        body = knowledge.render(manifest)
        assert '"chart_type": "bar"' in body
        assert '"type": "visualize"' in body

    def test_the_reach_section_names_the_generic_workflow_tools(self):
        body = knowledge.render(knowledge.find('node.upload'))
        assert '`workflow_schema`' in body
        assert '`apply_workflow`' in body
