"""The exact-number tool: bounded, read-only, and named in its refusals."""

import pytest
from ai.errors import AIError


@pytest.fixture
def frame(monkeypatch):
    import pandas as pd
    from ai import tools

    data = pd.DataFrame(
        [
            {'平台': '知乎', '正文': 'a' * 300, '点赞': 3, '阶段': '一'},
            {'平台': '微博', '正文': 'b' * 300, '点赞': 7, '阶段': '一'},
            {'平台': '知乎', '正文': 'c' * 300, '点赞': 5, '阶段': '二'},
            {'平台': '知乎', '正文': 'd' * 300, '点赞': None, '阶段': '二'},
        ]
    )
    monkeypatch.setattr(tools, '_dataset_frame', lambda dataset_id: data)
    return data


def test_count_is_exact_and_filtered(frame):
    from ai import tools

    result = tools.tool_dataset_query(
        {
            'dataset_id': 'd1',
            'op': 'count',
            'columns': ['平台'],
            'where': {'column': '平台', 'op': 'eq', 'value': '知乎'},
        },
        {},
    )
    assert result['total_rows'] == 4
    assert result['matched_rows'] == 3
    assert result['columns']['平台'] == 3


def test_numeric_aggregations_return_json_safe_numbers(frame):
    from ai import tools

    result = tools.tool_dataset_query({'dataset_id': 'd1', 'op': 'mean', 'columns': ['点赞']}, {})
    assert result['columns'][0]['mean'] == 5
    result = tools.tool_dataset_query({'dataset_id': 'd1', 'op': 'max', 'columns': ['点赞']}, {})
    assert result['columns'][0]['max'] == 7


def test_groupby_is_bounded_and_names_its_agg(frame):
    from ai import tools

    result = tools.tool_dataset_query(
        {'dataset_id': 'd1', 'op': 'groupby', 'by': ['阶段'], 'columns': ['点赞'], 'agg': 'sum', 'limit': 1}, {}
    )
    assert result['by'] == ['阶段']
    assert result['agg'] == 'sum'
    assert result['truncated'] is True
    assert len(result['groups']) == 1
    assert result['groups'][0]['点赞'] == 10


def test_value_counts_are_exact_and_capped(frame):
    from ai import tools

    result = tools.tool_dataset_query({'dataset_id': 'd1', 'op': 'value_counts', 'columns': ['平台'], 'limit': 1}, {})
    assert result['column'] == '平台'
    assert result['rows'][0] == {'value': '知乎', 'count': 3}
    assert result['truncated'] is True


def test_filter_caps_rows_and_cells(frame):
    from ai import tools

    result = tools.tool_dataset_query({'dataset_id': 'd1', 'op': 'filter', 'limit': 2, 'width': 10}, {})
    assert result['truncated'] is True
    assert len(result['rows']) == 2
    assert result['rows'][0]['正文'].endswith('…')


def test_contains_is_a_literal_substring_not_a_regex(frame):
    from ai import tools

    # A valid regex used to match unintended rows; a malformed one (``[``) escaped the tool's
    # error handling as re.error. ``contains`` is a literal substring test, so neither applies.
    for value in ('知乎|微博', '[', 'C++'):
        result = tools.tool_dataset_query(
            {
                'dataset_id': 'd1',
                'op': 'count',
                'columns': ['平台'],
                'where': {'column': '平台', 'op': 'contains', 'value': value},
            },
            {},
        )
        assert result['matched_rows'] == 0, value


def test_an_unknown_op_is_refused_by_name(frame):
    from ai import tools

    with pytest.raises(AIError) as refusal:
        tools.tool_dataset_query({'dataset_id': 'd1', 'op': 'exec'}, {})
    assert refusal.value.key == 'ai.toolRefused'
    assert 'unsupported op exec' in refusal.value.params['reason']


def test_a_missing_column_is_refused_by_name(frame):
    from ai import tools

    with pytest.raises(AIError) as refusal:
        tools.tool_dataset_query({'dataset_id': 'd1', 'op': 'mean', 'columns': ['不存在的列']}, {})
    assert refusal.value.key == 'ai.toolRefused'
    assert 'columns is required' in refusal.value.params['reason']


def test_the_tool_is_offered_without_a_new_switch():
    from ai import skills, tools

    # Offered by the analysis skill, which is the framework's offer list — no extra switch.
    assert 'dataset_query' in skills.BUILTIN['analysis'].tools
    assert tools.TOOLS['dataset_query'].permission == 'read:project'
