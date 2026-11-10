"""``core.atomic.replace``: the staged-write rename that survives a reader.

On POSIX ``os.replace`` succeeds even while another handle has the target open. On Windows it answers
``PermissionError`` — so every durable store in this project turned a perfectly valid save into an
HTTP 500 whenever a second request (or an antivirus, or the console tail) happened to be reading the
file at that instant. The retry is the fix; a file that stays locked must still raise.
"""

import errno
import os

import pytest
from core import atomic

pytestmark = pytest.mark.unit


class TestTheRenameRetriesAReader:
    def test_a_transient_permission_error_is_retried(self, tmp_path, monkeypatch):
        staged = tmp_path / 'staged.tmp'
        target = tmp_path / 'target.json'
        staged.write_text('{"ok": true}', encoding='utf-8')

        real = os.replace
        calls = {'n': 0}

        def flaky(src, dst):
            calls['n'] += 1
            if calls['n'] < 3:
                raise PermissionError(errno.EACCES, 'the file is held by another process')
            return real(src, dst)

        monkeypatch.setattr(atomic, 'os', type('OsModule', (), {'replace': staticmethod(flaky)})())
        monkeypatch.setattr(atomic.time, 'sleep', lambda _seconds: None)
        atomic.replace(staged, target)
        assert calls['n'] == 3, 'the rename was not retried'
        assert target.read_text(encoding='utf-8') == '{"ok": true}'
        assert not staged.exists()

    def test_a_file_that_stays_locked_still_raises(self, tmp_path, monkeypatch):
        """A retry that swallowed the failure would be worse than none: the caller must be able to
        name the file it could not write."""
        staged = tmp_path / 'staged.tmp'
        staged.write_text('x', encoding='utf-8')

        def always_locked(_src, _dst):
            raise PermissionError(errno.EACCES, 'still held')

        monkeypatch.setattr(atomic, 'os', type('OsModule', (), {'replace': staticmethod(always_locked)})())
        monkeypatch.setattr(atomic.time, 'sleep', lambda _seconds: None)
        with pytest.raises(PermissionError):
            atomic.replace(staged, tmp_path / 'target.json')

    def test_a_non_permission_error_is_not_retried(self, tmp_path, monkeypatch):
        """A full disk or a cross-device rename is not a reader problem, and retrying it ten times
        only delays the refusal."""
        staged = tmp_path / 'staged.tmp'
        staged.write_text('x', encoding='utf-8')
        calls = {'n': 0}

        def no_space(_src, _dst):
            calls['n'] += 1
            raise OSError(errno.ENOSPC, 'no space left')

        monkeypatch.setattr(atomic, 'os', type('OsModule', (), {'replace': staticmethod(no_space)})())
        with pytest.raises(OSError):
            atomic.replace(staged, tmp_path / 'target.json')
        assert calls['n'] == 1, 'a disk-full rename was retried'

    def test_the_happy_path_moves_the_file(self, tmp_path):
        staged = tmp_path / 'staged.tmp'
        target = tmp_path / 'target.json'
        staged.write_text('payload', encoding='utf-8')
        atomic.replace(staged, target)
        assert target.read_text(encoding='utf-8') == 'payload'
        assert not staged.exists()
