"""What an approval card says it will do: the resolved target and, for a write, the exact diff.

The model's ``summary`` is its own story. These tests pin that the card shows the file/command the
grant will actually authorise, that a preview never writes, and that an unresolvable target is
reported with the same named sentence the tool would answer — not by blowing up the turn.
"""

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def folder(tmp_path, monkeypatch):
    from ai import workspace

    monkeypatch.setattr(workspace, 'folder', lambda: str(tmp_path))
    return tmp_path


def test_an_existing_file_shows_a_unified_diff(folder):
    from ai import approval_preview

    (folder / 'notes.txt').write_text('alpha\nbeta\n', encoding='utf-8')
    view = approval_preview.preview('workspace_write', {'path': 'notes.txt', 'content': 'alpha\nBETA\ngamma\n'})
    assert view['kind'] == 'write'
    assert view['exists'] is True
    assert view['changed'] is True
    assert view['truncated'] is False
    assert view['error'] == ''
    facts = {row['key']: row['value'] for row in view['facts']}
    assert facts['path'] == 'notes.txt'
    assert facts['target'] == str(folder / 'notes.txt')
    assert facts['bytes_before'] == str((folder / 'notes.txt').stat().st_size)
    assert facts['bytes_after'] == str(len(b'alpha\nBETA\ngamma\n'))
    assert '-beta' in view['diff']
    assert '+BETA' in view['diff']
    assert '+gamma' in view['diff']


def test_a_new_file_is_marked_as_new(folder):
    from ai import approval_preview

    view = approval_preview.preview('workspace_write', {'path': 'new.txt', 'content': 'hello\n'})
    assert view['exists'] is False
    assert view['changed'] is True
    assert any(line.startswith('@@ -0,0') for line in view['diff'])
    assert '+hello' in view['diff']


def test_an_identical_write_is_said_to_change_nothing(folder):
    from ai import approval_preview

    (folder / 'same.txt').write_text('unchanged\n', encoding='utf-8')
    view = approval_preview.preview('workspace_write', {'path': 'same.txt', 'content': 'unchanged\n'})
    assert view['diff'] == []
    assert view['changed'] is False
    assert (folder / 'same.txt').read_text(encoding='utf-8') == 'unchanged\n'


def test_an_escaping_path_is_reported_without_crashing(folder):
    from ai import approval_preview

    view = approval_preview.preview('workspace_write', {'path': '../escape.txt', 'content': 'x'})
    assert view['kind'] == 'write'
    assert view['error']
    assert 'escape.txt' in view['error']
    assert view['diff'] == []


def test_a_huge_file_reports_sizes_instead_of_a_diff(folder):
    from ai import approval_preview, workspace

    (folder / 'large.txt').write_text('x' * (workspace.MAX_READ_BYTES + 10), encoding='utf-8')
    view = approval_preview.preview('workspace_write', {'path': 'large.txt', 'content': 'small'})
    # The write still replaces the whole file, so it is a change even without a line-by-line diff.
    assert view['changed'] is True
    assert view['diff'] == []
    assert {row['key'] for row in view['facts']} >= {'bytes_before', 'bytes_after'}


def test_a_long_diff_is_capped_and_says_so(folder):
    from ai import approval_preview

    view = approval_preview.preview(
        'workspace_write', {'path': 'many.txt', 'content': ''.join(f'line {i}\n' for i in range(600))}
    )
    assert len(view['diff']) == approval_preview.MAX_DIFF_LINES
    assert view['truncated'] is True


def test_a_command_names_what_would_run(folder):
    from ai import approval_preview

    view = approval_preview.preview('run_cmd', {'command': 'pytest -q', 'cwd': 'sub', 'timeout': 30})
    facts = {row['key']: row['value'] for row in view['facts']}
    assert view['kind'] == 'command'
    assert facts['command'] == 'pytest -q'
    assert facts['cwd'] == str(folder / 'sub')
    assert facts['timeout'] == '30'


def test_an_import_names_the_file_and_its_size(folder):
    from ai import approval_preview

    (folder / 'data.csv').write_text('a,b\n1,2\n', encoding='utf-8')
    view = approval_preview.preview('workspace_import', {'path': 'data.csv', 'name': 'Mine'})
    facts = {row['key']: row['value'] for row in view['facts']}
    assert view['kind'] == 'import'
    assert facts['name'] == 'Mine'
    assert facts['bytes'] == str((folder / 'data.csv').stat().st_size)
    assert view['error'] == ''

    missing = approval_preview.preview('workspace_import', {'path': 'absent.csv'})
    assert missing['error']


def test_an_unknown_approval_tool_still_shows_its_arguments(folder):
    from ai import approval_preview

    view = approval_preview.preview('future_tool', {'a': 1, 'b': {'c': 2}})
    assert view['kind'] == 'unknown'
    facts = {row['key']: row['value'] for row in view['facts']}
    assert facts['a'] == '1'
    assert '"c": 2' in facts['b']
