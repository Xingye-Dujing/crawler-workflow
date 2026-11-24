"""The per-conversation row grant: only a human answer creates it, and every row read spends it."""

import pytest
from ai.errors import AIError

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_registry():
    from ai import dataset_access

    dataset_access.reset()
    yield
    dataset_access.reset()


def test_a_grant_is_created_by_an_allow_answer_and_spends_down():
    from ai import dataset_access

    labels = {'allow': '允许读取 100 行', 'deny': '不允许'}
    dataset_access.request('c1', 'ds1', 100, 'demo', 'call1', labels)
    grant = dataset_access.settle('c1', 'call1', [{'id': 'dataset_access', 'selected': [labels['allow']]}])
    assert grant is not None and grant['max_rows'] == 100
    allowed, state = dataset_access.consume('c1', 'ds1', 40)
    assert allowed == 40
    assert state == {'max_rows': 100, 'rows_read': 40, 'remaining': 60}
    # Spending more than remains clamps to what the user allowed, and says so.
    allowed, state = dataset_access.consume('c1', 'ds1', 90)
    assert allowed == 60 and state['remaining'] == 0
    with pytest.raises(AIError) as exhausted:
        dataset_access.consume('c1', 'ds1', 1)
    assert exhausted.value.key == 'ai.datasetGrantExhausted'


def test_a_deny_answer_grants_nothing_even_with_a_typed_number():
    from ai import dataset_access

    labels = {'allow': 'allow', 'deny': 'deny'}
    dataset_access.request('c1', 'ds1', 100, 'demo', 'call1', labels)
    assert dataset_access.settle('c1', 'call1', [{'selected': ['deny']}], custom='300') is None
    assert dataset_access.active('c1') == []


def test_a_typed_number_overrides_the_requested_budget():
    from ai import dataset_access

    labels = {'allow': 'allow', 'deny': 'deny'}
    dataset_access.request('c1', 'ds1', 100, 'demo', 'call1', labels)
    grant = dataset_access.settle('c1', 'call1', [{'custom': '250'}], custom='250')
    assert grant is not None and grant['max_rows'] == 250


def test_zero_means_all_rows():
    from ai import dataset_access

    dataset_access.grant('c1', 'ds1', 0, 'demo')
    allowed, state = dataset_access.consume('c1', 'ds1', 5000)
    assert allowed == 5000
    assert state['max_rows'] == 0 and state['remaining'] == 0


def test_without_a_grant_the_refusal_names_the_tool_to_call():
    from ai import dataset_access

    with pytest.raises(AIError) as refused:
        dataset_access.consume('c1', 'ds1', 10)
    assert refused.value.key == 'ai.datasetAccessNeeded'
    assert refused.value.params['dataset'] == 'ds1'


def test_revoke_drops_one_dataset_and_keeps_the_others():
    from ai import dataset_access

    dataset_access.grant('c1', 'ds1', 10, 'one')
    dataset_access.grant('c1', 'ds2', 20, 'two')
    assert dataset_access.revoke('c1', 'ds1') == 1
    assert [row['dataset_id'] for row in dataset_access.active('c1')] == ['ds2']
    assert dataset_access.revoke('c1') == 1
    assert dataset_access.active('c1') == []


def test_dataset_page_spends_the_grant_and_stops_at_zero(monkeypatch):
    import pandas as pd
    from ai import dataset_access, tools

    frame = pd.DataFrame({'a': list(range(100))})
    monkeypatch.setattr('ai.tools.datasets._dataset_frame', lambda dataset_id: frame)
    dataset_access.grant('c1', 'ds1', 5, 'demo')
    page = tools.tool_dataset_page({'dataset_id': 'ds1', 'limit': 10}, {'conversation_id': 'c1'})
    assert len(page['rows']) == 5
    assert page['grant'] == {'max_rows': 5, 'rows_read': 5, 'remaining': 0}
    with pytest.raises(AIError):
        tools.tool_dataset_page({'dataset_id': 'ds1', 'limit': 10}, {'conversation_id': 'c1'})


def test_the_five_row_preview_stays_free(monkeypatch):
    import pandas as pd
    from ai import tools

    frame = pd.DataFrame({'a': list(range(100))})
    monkeypatch.setattr('ai.tools.datasets._dataset_frame', lambda dataset_id: frame)
    peek = tools.tool_dataset_peek({'dataset_id': 'ds1'}, {'conversation_id': 'c1'})
    assert peek['shown_rows'] == 5
    assert 'grant' not in peek


def test_a_filtered_query_is_a_row_read_but_an_aggregation_is_not(monkeypatch):
    import pandas as pd
    from ai import tools

    frame = pd.DataFrame({'a': list(range(100))})
    monkeypatch.setattr('ai.tools.datasets._dataset_frame', lambda dataset_id: frame)
    count = tools.tool_dataset_query({'dataset_id': 'ds1', 'op': 'count', 'columns': ['a']}, {'conversation_id': 'c1'})
    assert count['matched_rows'] == 100
    with pytest.raises(AIError) as refused:
        tools.tool_dataset_query(
            {'dataset_id': 'ds1', 'op': 'filter', 'columns': ['a'], 'limit': 3},
            {'conversation_id': 'c1'},
        )
    assert refused.value.key == 'ai.datasetAccessNeeded'


def test_a_tool_call_without_a_conversation_is_not_an_agent_turn(monkeypatch):
    """Direct/internal reads (unit tests, the trace writer) have no conversation to grant against."""
    import pandas as pd
    from ai import tools

    frame = pd.DataFrame({'a': list(range(100))})
    monkeypatch.setattr('ai.tools.datasets._dataset_frame', lambda dataset_id: frame)
    page = tools.tool_dataset_page({'dataset_id': 'ds1', 'limit': 7}, {})
    assert len(page['rows']) == 7
    assert 'grant' not in page
