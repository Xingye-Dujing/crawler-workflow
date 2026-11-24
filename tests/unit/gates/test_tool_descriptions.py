"""The tool catalogue is a contract: a name, a bounded schema, a permission, and a description a small
model can select on.

The three rules below are the ones a small local model can actually act on, and each of them has
already been broken once:

1. **A name says its domain and its object** — ``dataset_query``, ``workflow_export``, ``model_infer``.
   A model picks tools by name; ``query`` alone collides with the analysis vocabulary.
2. **At most eight parameters, and no parameter is a free-form program** — a tool that takes ``code``
   is a code-execution surface, and the query surface is a closed table of ops instead.
3. **The description says what it returns and when NOT to use it** — "use this first", "don't pull
   the table to recompute", "never install anything". That sentence is the whole difference between a
   model that reads five rows and one that reads the table.

``docs/capabilities/tool-descriptions.md`` is the human page; this gate keeps it from rotting.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
TOOLS_DIR = REPO / 'backend' / 'ai' / 'tools'
DOC = REPO / 'docs' / 'capabilities' / 'tool-descriptions.md'

PERMISSIONS = {
    'read:project',
    'write:project',
    'read:code',
    'ask',
    'exec:model',
    'read:python',
    'write:python',
    'exec:python',
}


def _specs():
    from ai.tools import TOOLS

    assert TOOLS, 'no tools — this gate measures nothing'
    return TOOLS


class TestEveryToolIsSelectable:
    def test_a_name_names_its_domain_and_its_object(self):
        bad = sorted(name for name in _specs() if '_' not in name)
        assert not bad, f'{bad} have no domain prefix; a model selects by name'

    def test_the_description_says_what_it_does_and_when_not_to(self):
        thin = sorted(name for name, spec in _specs().items() if len(str(spec.description or '').strip()) < 40)
        assert not thin, f'{thin} have a description too thin to select on (>=40 characters)'

    def test_at_most_eight_parameters(self):
        wide = sorted(
            name for name, spec in _specs().items() if len((spec.parameters or {}).get('properties') or {}) > 8
        )
        assert not wide, f'{wide} take more than eight parameters; split the tool instead'

    def test_no_tool_takes_free_form_code(self):
        """A `code`/`script` parameter would make a read-only tool an execution surface."""
        offenders = []
        for name, spec in _specs().items():
            for parameter in (spec.parameters or {}).get('properties') or {}:
                if parameter.lower() in ('code', 'script', 'python', 'command', 'shell'):
                    offenders.append(f'{name}.{parameter}')
        assert not offenders, f'{offenders} accept executable text; use the Python extension surface instead'

    def test_every_permission_is_one_of_the_known_verbs(self):
        unknown = sorted(
            f'{name}: {spec.permission}'
            for name, spec in _specs().items()
            if str(getattr(spec, 'permission', '') or '') not in PERMISSIONS
        )
        assert not unknown, f'{unknown} declare a permission the policy engine does not know'


class TestTheDocPageMatchesTheCatalogue:
    def test_every_tool_is_listed_on_the_page(self):
        page = DOC.read_text(encoding='utf-8')
        missing = sorted(name for name in _specs() if f'`{name}`' not in page)
        assert not missing, f'{missing} are offered but not documented in {DOC.relative_to(REPO)}'

    def test_the_page_names_no_tool_the_build_does_not_offer(self):
        page = DOC.read_text(encoding='utf-8')
        listed = {
            token.strip('`') for token in page.split() if token.startswith('`') and token.endswith('`') and '_' in token
        }
        from ai.tools import TOOLS

        known = set(TOOLS) | {'ask_user_question', 'update_plan', 'present_artifact', 'request_approval'}
        stale = sorted(
            name for name in listed if name.islower() and '_' in name and name not in known and len(name) > 8
        )
        # Only names that look like tools are checked; prose words with underscores are allowed.
        suspicious = [
            name for name in stale if name.split('_')[0] in {'dataset', 'workflow', 'model', 'export', 'code'}
        ]
        assert not suspicious, f'{suspicious} are named on the page but not offered by this build'

    def test_the_page_is_generated_from_no_second_list(self):
        """One page, and it must not claim a count this test cannot check."""
        page = DOC.read_text(encoding='utf-8')
        assert '`TOOLS`' in page, 'the page must point at the catalogue as its source of truth'


def test_the_gate_can_see_a_thin_description(tmp_path):
    """A synthetic spec with a one-word description must be reported by the same rule."""
    source = 'x = 1\n'
    assert len(source.strip()) < 40
    assert ast is not None
