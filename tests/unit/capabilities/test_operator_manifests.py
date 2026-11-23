"""One analysis operator, declared once and projected everywhere it is read.

The operator tree replaced five hand-kept tables (``OPS``, ``STEP_PARAMS``/``LLM_OPS``, the
``params`` write tables, ``STEP_TWO_TABLE`` and the executor's ``EMPTY_BY_DESIGN``). These cases walk
the declarations and the projections together, so a table and its manifest cannot drift: a new
operator that declares a column contract is refused by name when the projection disagrees, and an
operator the panel offers without a manifest fails here first.
"""

import json

import pytest
from capabilities_kernel import generate, registry
from capabilities_kernel.operator import WRITE_MODES

from services.analysis.contracts import LLM_OPS, STEP_PARAMS
from services.analysis.matching import STEP_TWO_TABLE
from services.analysis.ops import OPS
from services.analysis.params import (
    STEP_ADD_MAYBE,
    STEP_ADD_ONE,
    STEP_DYNAMIC_REPLACE,
    STEP_EMPTY_BY_DESIGN,
    STEP_PASSTHROUGH,
    STEP_REPLACE,
    STEP_SELECT,
    STEP_UNKNOWN,
)
from services.analysis.step_checks import TWO_TABLE_KEYS, param_problems

pytestmark = pytest.mark.unit

MANIFESTS = registry.manifests('operator')
IDS = [manifest.identity.id for manifest in MANIFESTS]


class TestEveryOperatorIsDeclaredOnce:
    def test_the_tree_is_not_empty(self):
        assert MANIFESTS, 'the operator tree discovered nothing — every case below would pass over nothing'

    def test_the_handlers_and_the_manifests_name_the_same_steps(self):
        assert set(OPS) == set(IDS), 'an op module exists without a manifest, or the reverse'
        for manifest in MANIFESTS:
            handler = registry.resolve(manifest.execution.handler)
            assert handler is OPS[manifest.identity.id], manifest.identity.id

    def test_the_identifier_is_the_module_and_the_parameter_contract(self):
        for manifest in MANIFESTS:
            ident = manifest.identity.id
            assert manifest.execution.handler == f'services.analysis.ops.{ident}:{ident}'
            assert manifest.identity.title_key == f'op.{ident}'

    def test_every_manifest_projects_the_contract_the_validator_reads(self):
        assert set(STEP_PARAMS) == set(IDS)
        for manifest in MANIFESTS:
            assert STEP_PARAMS[manifest.identity.id] == manifest.contract()

    def test_the_policy_sets_are_projections(self):
        assert frozenset(m.identity.id for m in MANIFESTS if m.needs_llm) == LLM_OPS
        assert frozenset(m.identity.id for m in MANIFESTS if m.reads.two_table_keys) == STEP_TWO_TABLE
        assert frozenset(TWO_TABLE_KEYS) == STEP_TWO_TABLE
        assert frozenset(m.identity.id for m in MANIFESTS if m.empty_by_design) == STEP_EMPTY_BY_DESIGN
        assert frozenset(m.identity.id for m in MANIFESTS if m.writes.mode == 'select') == STEP_SELECT

    def test_the_write_tables_partition_every_operator(self):
        declared = {manifest.identity.id: manifest.writes.mode for manifest in MANIFESTS}
        assert set(declared.values()) <= set(WRITE_MODES)
        covered = (
            set(STEP_REPLACE)
            | set(STEP_ADD_ONE)
            | set(STEP_PASSTHROUGH)
            | set(STEP_UNKNOWN)
            | set(STEP_DYNAMIC_REPLACE)
            | set(STEP_SELECT)
        )
        assert covered == set(IDS)
        for op, mode in declared.items():
            assert (op in STEP_REPLACE) == (mode == 'replace'), op
            assert (op in STEP_PASSTHROUGH) == (mode == 'passthrough'), op
            assert (op in STEP_UNKNOWN) == (mode == 'unknown'), op
            assert (op in STEP_DYNAMIC_REPLACE) == (mode == 'dynamic'), op
            assert (op in STEP_SELECT) == (mode == 'select'), op
            assert (op in STEP_ADD_ONE) == (mode == 'add'), op

    def test_an_add_step_projects_its_named_columns(self):
        for manifest in MANIFESTS:
            if not manifest.writes.add:
                continue
            ident = manifest.identity.id
            assert STEP_ADD_ONE[ident] == tuple(manifest.writes.add[0])
            assert STEP_ADD_MAYBE.get(ident, ()) == tuple(manifest.writes.add_maybe)

    def test_a_two_table_key_is_checked_against_both_tables_not_one(self):
        for manifest in MANIFESTS:
            overlap = set(manifest.reads.one) & set(manifest.reads.two_table_keys)
            assert not overlap, f'{manifest.identity.id}: {overlap} cannot be a one-table read'


class TestTheBadgeNamesTheBoxThePanelShows:
    def test_every_label_override_exists_in_both_languages(self):
        from frontend_catalogue import catalog_keys

        tables = catalog_keys()
        missing = [
            f'{key} in {lang}'
            for manifest in MANIFESTS
            for _param, key in manifest.labels
            for lang in ('en', 'zh')
            if key not in tables[lang]
        ]
        assert missing == []


class TestTheDeclaredSkillTeachesTheDeclaredStep:
    @pytest.mark.parametrize('manifest', MANIFESTS, ids=IDS)
    def test_the_template_carries_every_required_box(self, manifest):
        """The template is what the assistant sends back: it must not be refused by name."""
        step = json.loads(manifest.ai.template['params']['steps'])[0]
        assert step['op'] == manifest.identity.id
        assert param_problems(manifest.identity.id, step['params']) == []

    @pytest.mark.parametrize('manifest', MANIFESTS, ids=IDS)
    def test_the_seven_sections_are_present(self, manifest):
        for value in (
            manifest.ai.summary,
            manifest.ai.prerequisites,
            manifest.ai.steps,
            manifest.ai.examples,
            manifest.ai.failures,
            manifest.ai.acceptance,
        ):
            assert value

    def test_the_generated_pages_exist(self):
        for manifest in MANIFESTS:
            assert manifest.docs.page.startswith('docs/capabilities/operators/')
            assert manifest.docs.skill.startswith('docs/capabilities/skills/operators/')

    def test_the_rendered_artifacts_are_fresh(self):
        assert generate.check() == [], 'run `python tools/gen_capabilities.py` and commit the result'
