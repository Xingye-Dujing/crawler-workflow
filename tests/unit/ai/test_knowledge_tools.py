"""The two workspace tools over the capability skills: a catalogue and a named body.

The kernel tests prove the derivation; these prove the tool surface the model actually calls: the
refusals carry a key the HTTP layer can localize, the catalogue is bounded, and both verbs are in
the always-offered set so no skill has to remember them.
"""

import pytest
from ai import knowledge, tools
from ai.errors import AIError

pytestmark = pytest.mark.unit


class TestTheTools:
    def test_both_verbs_are_registered_and_universal(self):
        for name in ('capability_catalog', 'capability_load'):
            assert name in tools.TOOLS
            assert name in tools.UNIVERSAL_TOOLS

    def test_the_catalogue_returns_level_one_rows(self):
        answer = tools.tool_capability_catalog({'query': 'comment'}, {})
        assert answer['total'] == len(answer['skills'])
        assert answer['skills'][0]['id'] == 'node.comment'
        assert 'markdown' not in answer['skills'][0]

    def test_the_catalogue_refuses_an_unknown_kind_by_name(self):
        with pytest.raises(AIError) as raised:
            tools.tool_capability_catalog({'kind': 'gadget'}, {})
        assert raised.value.key == 'ai.skillKindBad'
        assert raised.value.params['kind_name'] == 'gadget'

    def test_the_catalogue_integer_field_is_clamped(self):
        """9999 is clamped to the largest page, and the whole catalogue still fits in it."""
        answer = tools.tool_capability_catalog({'limit': 9999}, {})
        assert answer['total'] == len(answer['skills'])
        assert answer['total'] == len(knowledge.catalog(limit=200)['skills'])
        assert answer['total'] >= len(knowledge.catalog()['skills']), 'the clamp must not cap below the default page'

    def test_loading_a_skill_returns_the_body_and_template(self):
        answer = tools.tool_capability_load({'skill_id': 'node.tokenize'}, {})
        assert answer['id'] == 'node.tokenize'
        assert answer['template']['type'] == 'tokenize'
        assert '| `text_column` |' in answer['markdown']
        assert answer['tools'] == ['workflow_schema', 'apply_workflow', 'workflow_validate']

    def test_loading_an_unknown_skill_is_refused_with_the_id(self):
        with pytest.raises(AIError) as raised:
            tools.tool_capability_load({'skill_id': 'node.no_such'}, {})
        assert raised.value.key == 'ai.skillUnknown'
        assert raised.value.params['skill'] == 'node.no_such'

    def test_a_missing_id_is_the_same_named_refusal_not_a_key_error(self):
        with pytest.raises(AIError) as raised:
            tools.tool_capability_load({}, {})
        assert raised.value.key == 'ai.skillUnknown'

    def test_the_title_falls_back_to_the_capability_id_without_a_server_word(self):
        row = knowledge.catalog(kind='node', limit=1)['skills'][0]
        assert row['title'] == row['capability']
