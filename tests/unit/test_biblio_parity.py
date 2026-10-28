"""The CiteSpace parity surface, pinned as runnable behaviour rather than prose.

Phase 6 audits the feature matrix row by row. A row is only ✅ if a test exercises it, and the
audit found one row whose "16 entity types" claim had never built five of them (author,
institution, country, term, category). This module is the machine-checked half of that matrix:
every advertised entity type builds a graph from ONE corpus, every declared column contract
covers every type, and every registered chart type has a builder and a read contract. Adding a
type without wiring it is a red test here, not a paragraph someone forgets to update.
"""

import json

import pandas as pd
import pytest

from services.biblio import metrics
from services.biblio.schema import ENTITY_COLUMNS, ENTITY_REQUIRED, ENTITY_TYPES
from services.charts.contracts import BIBLIO_CHART_READS, BIBLIO_CHART_TYPES

pytestmark = pytest.mark.unit

_REFS_A = (
    '[1] 张三. 数字治理的路径[J]. 公共管理学报, 2020(1): 1-2.\n[2] 李四. 数据要素与治理[J]. 中国行政管理, 2021(2): 3-4.'
)
_REFS_B = (
    '[1] 李四. 数据要素与治理[J]. 中国行政管理, 2021(2): 3-4.\n[2] 王五. 协同监管研究[J]. 政治学研究, 2019(3): 5-6.'
)


def _corpus() -> pd.DataFrame:
    """Four records carrying every column any entity type reads, with deliberate overlap.

    One document lists TWO disciplines: a co-occurrence needs two values inside one document,
    and a corpus where each paper has exactly one 学科 has no category pair to draw — the
    refusal is right, but it would make this sweep measure nothing for that type.
    """
    return pd.DataFrame(
        [
            {
                '题名': '数字化转型中的公共治理创新',
                '年份': 2019,
                '关键词': '数字治理;数据要素',
                '作者': '张明;李华',
                '作者单位': '清华大学;北京大学',
                '国家': 'China;USA',
                '学科': 'Public Administration;Information Science',
                '来源期刊': '公共管理学报',
                '基金': '国家社科基金;自然科学基金',
                '摘要': '数字治理与数据要素的协同研究',
                '参考文献': _REFS_A,
                '引用次数': 10,
                '使用次数': 5,
            },
            {
                '题名': '数据要素驱动的协同监管',
                '年份': 2020,
                '关键词': '数字治理;协同监管',
                '作者': '张明;王强',
                '作者单位': '清华大学;复旦大学',
                '国家': 'China;UK',
                '学科': 'Public Administration',
                '来源期刊': '中国行政管理',
                '基金': '国家社科基金;教育部项目',
                '摘要': '数据要素与协同监管的治理机制',
                '参考文献': _REFS_A,
                '引用次数': 6,
                '使用次数': 3,
            },
            {
                '题名': '协同监管的制度逻辑',
                '年份': 2021,
                '关键词': '协同监管;制度逻辑',
                '作者': '王强;赵敏',
                '作者单位': '复旦大学;浙江大学',
                '国家': 'China;Germany',
                '学科': 'Political Science',
                '来源期刊': '政治学研究',
                '基金': '教育部项目;自然科学基金',
                '摘要': '协同监管与制度逻辑的分析',
                '参考文献': _REFS_B,
                '引用次数': 3,
                '使用次数': 2,
            },
            {
                '题名': '数字治理的技术伦理',
                '年份': 2022,
                '关键词': '数字治理;技术伦理',
                '作者': '赵敏;张明',
                '作者单位': '浙江大学;清华大学',
                '国家': 'China;Japan',
                '学科': 'Information Science',
                '来源期刊': '公共管理学报',
                '基金': '自然科学基金',
                '摘要': '数字治理中的技术伦理问题',
                '参考文献': _REFS_B,
                '引用次数': 1,
                '使用次数': 1,
            },
        ]
    )


def _params(entity_type: str) -> dict:
    return {
        'entity_type': entity_type,
        'min_count': 1,
        'cluster': False,
        'burst': False,
        'selection': 'top_n',
        'top_n': 50,
        'link_measure': 'cosine',
        'pruning': 'none',
        'export_files': False,
    }


@pytest.mark.parametrize('entity_type', ENTITY_TYPES)
def test_every_advertised_entity_type_builds_a_graph(entity_type):
    """One corpus, sixteen node types: each must produce entities AND links.

    A type whose construction silently broke (a renamed column, a branch that returns nothing)
    would otherwise only surface when a user's canvas happened to use it; five of these types
    had no test at all before this audit.
    """
    result = metrics.build(_corpus(), _params(entity_type), 'parity')
    assert result['summary']['entity_type'] == entity_type
    assert result['rows'], f'{entity_type} built no nodes'
    assert result['edges'], f'{entity_type} built no links'
    assert all({'节点', '频次', '连接'} <= set(row) for row in result['rows'])
    assert json.loads(result['rows'][0]['连接']), f'{entity_type} has an empty adjacency cell'


def test_every_entity_type_declares_the_columns_it_needs():
    assert set(ENTITY_COLUMNS) == set(ENTITY_TYPES)
    assert set(ENTITY_REQUIRED) == set(ENTITY_TYPES)
    for entity in ENTITY_TYPES:
        assert ENTITY_COLUMNS[entity] in ENTITY_REQUIRED[entity], (
            f'{entity} reads {ENTITY_COLUMNS[entity]!r} but does not require it'
        )


def test_every_advertised_view_has_a_builder_and_a_read_contract():
    from services.biblio import charts

    assert set(charts.BUILDERS) == set(BIBLIO_CHART_TYPES)
    assert set(BIBLIO_CHART_READS) == set(BIBLIO_CHART_TYPES)
    for chart_type in BIBLIO_CHART_TYPES:
        assert BIBLIO_CHART_READS[chart_type], f'{chart_type} declares no required column'


class TestPerformanceGuards:
    """The size caps are a promise: a run that would hang must refuse BY NAME instead.

    The cap VALUES are constants (5000 nodes / 100000 edges / 2000 clustered nodes), so these
    tests lower them with ``monkeypatch`` and prove the guard fires; a test that built 5001
    nodes would spend the suite's time proving arithmetic.
    """

    def test_the_node_cap_names_the_count_and_the_cap(self, monkeypatch):
        monkeypatch.setitem(metrics.LIMITS, 'max_nodes', 3)
        with pytest.raises(ValueError) as err:
            metrics.build(_corpus(), _params('keyword'), 'parity')
        assert '5' in str(err.value) and '3' in str(err.value), str(err.value)

    def test_the_edge_cap_names_the_count_and_the_cap(self, monkeypatch):
        monkeypatch.setitem(metrics.LIMITS, 'max_edges', 1)
        with pytest.raises(ValueError) as err:
            metrics.build(_corpus(), _params('keyword'), 'parity')
        assert '1' in str(err.value), str(err.value)

    def test_the_spectral_clustering_cap_refuses_before_the_cubic_work(self, monkeypatch):
        from services.biblio import cluster

        monkeypatch.setattr(cluster, 'MAX_CLUSTER_NODES', 3)
        with pytest.raises(ValueError) as err:
            metrics.build(_corpus(), {**_params('keyword'), 'cluster': True}, 'parity')
        assert '3' in str(err.value), str(err.value)
