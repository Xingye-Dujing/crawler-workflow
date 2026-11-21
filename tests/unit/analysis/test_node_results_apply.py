"""An edit confirmed in a node trace must actually reach the rerun.

``node_results.load`` used to be dead code: the apply tool wrote a file nobody read, so the
"confirm the edit, then rerun" promise silently re-executed the node and discarded the edit. The
rerun now consumes the saved edit; this pins both the read side and the id/path safety.
"""

import pytest

from services.coding import node_results

pytestmark = pytest.mark.unit


def test_save_load_consume_round_trip(data_root):
    saved = node_results.save('run_abc', 'n3', [{'正文': 'edited'}])
    assert saved['result'] == [{'正文': 'edited'}]
    assert node_results.load('run_abc', 'n3')['result'] == [{'正文': 'edited'}]
    consumed = node_results.consume('run_abc', 'n3')
    assert consumed['result'] == [{'正文': 'edited'}]
    assert node_results.load('run_abc', 'n3') is None, 'the edit must be applied once, not replayed'


def test_save_accepts_a_dict_result(data_root):
    node_results.save('run_abc', 'n4', {'code': 'A'})
    assert node_results.load('run_abc', 'n4')['result'] == {'code': 'A'}


@pytest.mark.parametrize('bad_id', ['../escape', 'C:/x', 'a/b', '', 'a b'])
def test_unsafe_ids_are_refused(bad_id):
    with pytest.raises(ValueError):
        node_results.save(bad_id, 'n1', [])
    with pytest.raises(ValueError):
        node_results.save('run_abc', bad_id, [])
