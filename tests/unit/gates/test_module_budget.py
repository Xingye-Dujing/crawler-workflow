"""Module size is a ratchet, not a target: a file over budget may only get smaller.

A 600-line ceiling is the line where a Python module stops being one thing you can hold in your
head (the same threshold the god-module detectors use). 34 hand-written modules are above it on
2026-11-24; forcing them all to shrink in one change would be a rewrite, so each is **frozen at its
current size** here. The rules:

* a module not in :data:`BUDGETS` must be at or under :data:`LIMIT`;
* a module in :data:`BUDGETS` must not grow past its recorded size;
* a module that dropped more than :data:`SLACK` lines must have its budget lowered — otherwise the
  table becomes a licence to grow back, which is exactly what a ratchet is for.

Declaration tables and generated files are exempt by name, not by convention: they are data, and a
new setting or a new capability must not be a failing test.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / 'backend'

#: The ceiling for a module that is not already over it.
LIMIT = 600

#: How far below its budget a frozen module may fall before the budget is considered stale.
SLACK = 100

#: Hand-written code modules above the ceiling, frozen at their 2026-11-24 size.
#: Lowering a number here is the reward for a split; raising one needs a reason in the review.
BUDGETS: dict[str, int] = {
    'engine/run.py': 1900,
    'ai/tools.py': 1697,
    'crawlers/core/crawler.py': 1241,
    'api/ai_workspace.py': 1205,
    'api/sessions.py': 1153,
    'services/update.py': 1075,
    'analyzers/llm_client.py': 1072,
    'crawlers/platforms/hongguo/harvest.py': 1056,
    'core/machine.py': 978,
    'services/ingest/catbus.py': 928,
    'crawlers/platforms/zhihu/crawler.py': 892,
    'sessions/profiles.py': 889,
    'crawlers/platforms/weibo/crawler.py': 884,
    'nodes/executors/source.py': 881,
    'app.py': 859,
    'services/datasets/store.py': 835,
    'services/charts/tikz_console.py': 809,
    'capabilities/registry.py': 789,
    'crawlers/platforms/douyin/crawler.py': 776,
    'services/accounts/service.py': 763,
    'sessions/preflight.py': 747,
    'nodes/executors/comment.py': 746,
    'services/analysis/topic_kernels.py': 726,
    'crawlers/platforms/cnki/crawler.py': 720,
    'api/workflow.py': 704,
    'services/biblio/metrics/records.py': 683,
    'capabilities_kernel/generate.py': 680,
    'analyzers/sentiment.py': 667,
    'services/biblio/importer.py': 627,
    'crawlers/platforms/hongguo/player_ui.py': 626,
    'services/runs/store/ledger.py': 623,
    'crawlers/platforms/xiaohongshu/comments.py': 617,
    'services/analysis/params.py': 612,
    'services/charts/tikz_biblio_charts.py': 601,
}

#: Declaration data, not code: one line per setting / message / capability. These grow with the
#: product by design, so a line ceiling would be a gate against adding features.
DECLARATIONS = {
    'runtime/settings_schema.py',
}
EXEMPT_DIRS = ('i18n_catalog/', 'capabilities_kernel/generated/')
EXEMPT_SUFFIX = '/manifest.py'


def measured(root: Path) -> dict[str, int]:
    sizes = {}
    for path in root.rglob('*.py'):
        rel = path.relative_to(root).as_posix()
        if '__pycache__' in path.parts:
            continue
        if rel in DECLARATIONS or rel.startswith(EXEMPT_DIRS) or rel.endswith(EXEMPT_SUFFIX):
            continue
        sizes[rel] = len(path.read_text(encoding='utf-8').splitlines())
    return sizes


class TestModuleBudget:
    def test_no_new_module_crosses_the_ceiling(self):
        sizes = measured(BACKEND)
        over = sorted(name for name, n in sizes.items() if n > LIMIT and name not in BUDGETS)
        assert over == [], (
            'a new module over 600 lines must be split, or added to BUDGETS with the plan that splits it: '
            + ', '.join(over)
        )

    def test_a_frozen_module_did_not_grow(self):
        sizes = measured(BACKEND)
        grown = sorted(
            f'{name}: {sizes.get(name, 0)} > {budget}'
            for name, budget in BUDGETS.items()
            if sizes.get(name, 0) > budget
        )
        assert grown == [], 'these modules grew past their frozen size: ' + '; '.join(grown)

    def test_a_budget_is_lowered_after_a_split(self):
        sizes = measured(BACKEND)
        stale = sorted(
            f'{name}: budget {budget}, now {sizes.get(name, 0)}'
            for name, budget in BUDGETS.items()
            if name in sizes and sizes[name] < budget - SLACK
        )
        assert stale == [], 'lower the recorded budget so the file cannot grow back: ' + '; '.join(stale)

    def test_every_budget_names_a_real_module(self):
        sizes = measured(BACKEND)
        missing = sorted(name for name in BUDGETS if name not in sizes)
        assert missing == [], f'the budget list names files that no longer exist: {missing}'

    def test_the_ratchet_can_fail(self, tmp_path):
        """A synthetic 700-line module with no budget must be reported."""
        (tmp_path / 'pkg').mkdir()
        (tmp_path / 'pkg' / 'big.py').write_text('x = 1\n' * 700, encoding='utf-8')
        sizes = measured(tmp_path)
        assert sizes['pkg/big.py'] == 700
        assert [name for name, n in sizes.items() if n > LIMIT] == ['pkg/big.py']
