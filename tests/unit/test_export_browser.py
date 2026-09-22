"""Tests for services/export_browser.py — the read side of ``data/exports``.

The interesting failures here are all path-shaped, so the fixtures are named
like an attacker's input form rather than a user's: every one of them must
resolve to '' (and answer 404) instead of reaching a file outside the export
directory. A listing that silently skipped a locked file is also pinned, because
the alternative — one open spreadsheet emptying the whole panel — is worse.
"""

import os
import time

import pytest

from services.export_browser import (
    MAX_ENTRIES,
    delete_export_file,
    export_usage,
    is_downloadable,
    list_exports,
    resolve_download_path,
    resolve_export_file,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def exports(tmp_path):
    """A directory with a handful of real exports plus two things that must not
    be reachable through a name."""
    directory = tmp_path / 'exports'
    directory.mkdir()
    (directory / 'run-a.csv').write_text('标题\n三亚\n', encoding='utf-8')
    (directory / 'run-b.json').write_text('[]', encoding='utf-8')
    (directory / 'chart.png').write_bytes(b'\x89PNG')
    (directory / 'nested.py').write_text('print(1)', encoding='utf-8')
    (tmp_path / 'outside.csv').write_text('secret\n', encoding='utf-8')
    (directory / 'sub').mkdir()
    (directory / 'sub' / 'deep.csv').write_text('x\n', encoding='utf-8')
    # A distinguishable mtime ordering: the newest file must sort first.
    os.utime(directory / 'run-b.json', (time.time() + 50, time.time() + 50))
    return str(directory)


class TestListing:
    def test_files_are_listed_newest_first_with_sizes(self, exports):
        rows = list_exports(exports)
        assert {row['name'] for row in rows} == {'run-a.csv', 'run-b.json', 'chart.png', 'nested.py'}
        # Only the ORDER is a contract; two files written in the same tick are
        # free to tie, so the assertion is monotonic rather than positional.
        times = [row['mtime'] for row in rows]
        assert times == sorted(times, reverse=True), 'newest first'
        assert rows[0]['name'] == 'run-b.json', 'the fixture made that one clearly newest'
        assert all(row['size'] > 0 and row['mtime'] > 0 for row in rows)
        assert [row['kind'] for row in rows if row['name'] == 'run-b.json'] == ['json']

    def test_subdirectories_are_never_walked(self, exports):
        """The panel deletes one file at a time; a listing that included a
        subtree would offer a delete that is not one file."""
        assert 'deep.csv' not in [row['name'] for row in list_exports(exports)]

    def test_a_script_is_listed_but_not_downloadable(self, exports):
        row = next(row for row in list_exports(exports) if row['name'] == 'nested.py')
        assert row['downloadable'] is False
        assert row['kind'] == 'other'

    def test_the_limit_bounds_the_listing(self, exports):
        assert len(list_exports(exports, limit=2)) == 2
        assert len(list_exports(exports, limit=0)) >= 1, 'a nonsense limit still lists what is there'
        assert len(list_exports(exports, limit=10_000)) == 4, 'the hard cap is what a huge limit gets'
        assert MAX_ENTRIES == 500

    def test_a_missing_or_empty_directory_is_an_empty_panel(self, tmp_path):
        assert list_exports(str(tmp_path / 'never-created')) == []
        assert list_exports('') == []
        assert export_usage(str(tmp_path / 'never-created')) == {'files': 0, 'bytes': 0}

    def test_usage_totals_cover_the_whole_directory(self, exports):
        usage = export_usage(exports)
        assert usage['files'] == 4
        assert usage['bytes'] == sum(row['size'] for row in list_exports(exports))


class TestResolution:
    def test_the_files_own_name_resolves(self, exports):
        assert os.path.basename(resolve_export_file(exports, 'run-a.csv')) == 'run-a.csv'

    @pytest.mark.parametrize(
        'name',
        [
            '',
            '   ',
            None,
            'missing.csv',
            'sub/deep.csv',
            '../outside.csv',
            '..\\outside.csv',
            '../../config.py',
            '/etc/passwd',
            'C:/Windows/win.ini',
            'nested.py/../outside.csv',
            # Decorated spellings of a real file are refused too: the name comes
            # from the listing, so anything that has to be *rewritten* to resolve
            # is a name the panel never sent, and rewriting it is the sloppier
            # half of the bug this function exists to close.
            './run-a.csv',
            'run-a.csv/',
            'exports/run-a.csv',
        ],
    )
    def test_nothing_outside_the_directory_resolves(self, exports, name):
        """Each of these used to be a plausible request; none of them may reach a
        file, and all of them answer the same way a missing file does."""
        assert resolve_export_file(exports, name) == ''

    def test_a_directory_is_not_a_file(self, tmp_path):
        (tmp_path / 'sub').mkdir()
        assert resolve_export_file(str(tmp_path), 'sub') == ''

    def test_the_export_directory_itself_cannot_be_named(self, exports):
        assert resolve_export_file(exports, '.') == ''
        assert resolve_export_file(exports, '..') == ''

    def test_a_symlink_out_is_refused(self, exports, tmp_path):
        """``realpath`` is what catches this: the link lives inside the
        directory and its target does not."""
        target = tmp_path / 'outside.csv'
        link = os.path.join(exports, 'link.csv')
        try:
            os.symlink(str(target), link)
        except (OSError, NotImplementedError):
            pytest.skip('symlinks need developer mode on Windows')
        assert resolve_export_file(exports, 'link.csv') == ''


class TestDownloadRule:
    """The listing marks a ``.py`` non-downloadable; this is what makes the flag
    true. A rule the panel alone enforces is a rule that only exists in the UI."""

    def test_a_real_export_resolves_for_download(self, exports):
        assert os.path.basename(resolve_download_path(exports, 'run-a.csv')) == 'run-a.csv'

    @pytest.mark.parametrize('name', ['script.py', '../outside.csv', 'missing.csv', ''])
    def test_a_refused_name_resolves_to_nothing(self, exports, name):
        assert resolve_download_path(exports, name) == ''

    def test_the_kind_rule_is_named_in_one_place(self, exports):
        assert is_downloadable(os.path.join(exports, 'chart.png')) is True
        assert is_downloadable('/tmp/anything.html') is False
        assert is_downloadable('/tmp/x.exe') is False

    def test_a_script_can_still_be_deleted(self, exports):
        """Removal is not the same permission as serving: clearing a stray file out
        of the export folder is exactly what the delete button is for."""
        assert resolve_download_path(exports, 'nested.py') == '', 'but it is never served'
        assert delete_export_file(exports, 'nested.py') is True
        assert resolve_export_file(exports, 'nested.py') == ''


class TestDeletion:
    def test_one_file_is_removed_and_reported(self, exports):
        assert delete_export_file(exports, 'run-a.csv') is True
        assert not os.path.exists(os.path.join(exports, 'run-a.csv'))
        assert len(list_exports(exports)) == 3

    def test_deleting_a_missing_file_is_not_a_success_claim(self, exports):
        assert delete_export_file(exports, 'gone.csv') is False

    @pytest.mark.parametrize('name', ['../outside.csv', 'sub/deep.csv', '', None])
    def test_a_name_that_escapes_is_never_deleted(self, exports, tmp_path, name):
        assert delete_export_file(exports, name) is False
        assert (tmp_path / 'outside.csv').exists()
        assert os.path.isdir(os.path.join(exports, 'sub'))

    def test_a_locked_file_reports_the_state_that_holds(self, exports, monkeypatch):
        """Windows raises on removing a file Excel has open; the answer must
        still describe reality rather than crash the panel."""

        def _refuse(path):
            raise PermissionError('locked')

        monkeypatch.setattr(os, 'remove', _refuse)
        assert delete_export_file(exports, 'run-a.csv') is False
        assert os.path.exists(os.path.join(exports, 'run-a.csv'))
