"""The reusable script library: forks, versions and metadata survive a partial save."""

import pytest

pytestmark = pytest.mark.unit


def _save(**over):
    from services import python_scripts

    payload = {
        'id': 'keeps_columns',
        'name': 'Keeps columns',
        'code': 'import os\nopen(os.environ["CIXI_OUTPUT"], "w").close()\n',
        'inputs': ['a'],
        'outputs': ['a'],
        'tags': ['demo'],
    }
    payload.update(over)
    return python_scripts.save_script(payload)


def test_a_save_that_omits_metadata_keeps_what_the_script_had():
    from services import python_scripts

    first = _save()
    assert first['inputs'] == ['a'] and first['tags'] == ['demo']
    # The studio's save sends only id/name/description/code; it used to erase the column hints and
    # tags a fork had recorded.
    second = python_scripts.save_script({'id': 'keeps_columns', 'name': 'Renamed', 'code': 'print(1)\n'})
    assert second['version'] == 2
    assert second['inputs'] == ['a'] and second['outputs'] == ['a'] and second['tags'] == ['demo']
    python_scripts.delete_script('keeps_columns')


def test_forking_twice_never_overwrites_the_users_copy():
    from services import python_scripts

    forked = python_scripts.fork_script('passthrough')
    assert forked['id'] == 'passthrough_mine'
    python_scripts.save_script(
        {'id': 'passthrough_mine', 'name': 'Edited', 'code': 'print("mine")\n', 'inputs': [], 'outputs': [], 'tags': []}
    )
    again = python_scripts.fork_script('passthrough')
    assert again['id'] == 'passthrough_mine2'
    assert python_scripts.get_script('passthrough_mine')['code'] == 'print("mine")\n'
    python_scripts.delete_script('passthrough_mine')
    python_scripts.delete_script('passthrough_mine2')


def test_a_named_fork_target_is_refused_by_name():
    from ai.errors import AIError

    from services import python_scripts

    python_scripts.fork_script('passthrough', 'chosen_copy')
    with pytest.raises(AIError) as refusal:
        python_scripts.fork_script('passthrough', 'chosen_copy')
    assert refusal.value.key == 'ai.pythonForkExists'
    python_scripts.delete_script('chosen_copy')
