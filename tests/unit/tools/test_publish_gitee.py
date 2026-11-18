"""The release's upload half: the split, the order, and the shapes Gitee's write API insists on.

Every case here is a step that failed once for real during the 2026.11.18.2 release:

* a part reused because its SIZE matched (a rebuilt archive has the same first-shard length);
* the prune refusing because the tag being published had no release entry yet;
* Gitee answering 400 “验证失败，所有参数不能为空” for a write that carried the token only in a
  header;
* an attachment uploaded twice because the existing names were never read.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOL = REPO / 'tools' / 'publish_gitee.py'
pytestmark = pytest.mark.unit


def _tool():
    spec = importlib.util.spec_from_file_location('publish_gitee_contract', TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules['publish_gitee_contract'] = module
    spec.loader.exec_module(module)
    return module


class _Answer:
    def __init__(self, status: int, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)[:200]

    def json(self):
        return self._payload


class TestTheSplit:
    def test_the_parts_add_up_to_the_archive(self):
        tool = _tool()
        plan = tool.shard_plan(250_000_000)
        assert [length for _offset, length in plan] == [99_614_720, 99_614_720, 50_770_560]
        assert sum(length for _offset, length in plan) == 250_000_000
        assert [offset for offset, _length in plan] == [0, 99_614_720, 199_229_440]

    def test_an_exact_multiple_does_not_gain_an_empty_tail(self):
        """``range(0, size, shard)`` plus a slice would otherwise append a zero-byte ``.003``."""
        tool = _tool()
        plan = tool.shard_plan(99_614_720 * 2)
        assert len(plan) == 2

    def test_a_zero_byte_archive_is_refused(self):
        tool = _tool()
        with pytest.raises(ValueError):
            tool.shard_plan(0)

    def test_a_rebuilt_archive_rewrites_every_part(self, tmp_path):
        """The measured bug: part ``.001`` kept its size and lost its bytes on the second build."""
        tool = _tool()
        archive = tmp_path / 'CaiXiHui-win64.zip'
        first = b'A' * 40
        second = b'B' * 40
        archive.write_bytes(first)
        parts = tool.write_shards(archive, shard=16)
        assert [part.read_bytes() for part in parts] == [b'A' * 16, b'A' * 16, b'A' * 8]
        assert ''.join(part.read_text() for part in parts) == first.decode()

        archive.write_bytes(second)
        tool.write_shards(archive, shard=16)
        # Same length, different bytes: a size-only check would have kept the old ``.001``.
        assert [part.read_bytes() for part in parts] == [b'B' * 16, b'B' * 16, b'B' * 8]

    def test_a_dry_run_writes_nothing(self, tmp_path):
        tool = _tool()
        archive = tmp_path / 'CaiXiHui-win64.zip'
        archive.write_bytes(b'A' * 40)
        parts = tool.write_shards(archive, shard=16, dry_run=True)
        assert [part.exists() for part in parts] == [False, False, False]


class TestTheGiteeShapes:
    def test_creating_a_release_sends_the_token_and_owner_in_the_form(self, monkeypatch):
        """A write with the token only in the header answers 400 “验证失败，所有参数不能为空”."""
        tool = _tool()
        seen = {}

        def fake_post(url, **kwargs):
            seen['url'] = url
            seen['data'] = kwargs.get('data') or {}
            return _Answer(201, {'id': 77})

        monkeypatch.setattr(tool.requests, 'post', fake_post)
        monkeypatch.setattr(tool, 'list_releases', lambda repo, token: [])
        assert tool.ensure_release('owner/name', 'tok', 'exe-2026-11-19.1', body='notes') == 77
        assert seen['data']['access_token'] == 'tok'
        assert seen['data']['owner'] == 'owner' and seen['data']['repo'] == 'name'
        assert seen['data']['tag_name'] == 'exe-2026-11-19.1'
        # An absent `body` is the 400; the notes travel with the entry.
        assert seen['data']['body'] == 'notes'

    def test_an_existing_release_is_adopted_not_created_twice(self, monkeypatch):
        tool = _tool()

        def _boom(*args, **kwargs):
            raise AssertionError('a second create would be a 400 on Gitee')

        monkeypatch.setattr(tool, 'list_releases', lambda repo, token: [{'id': 9, 'tag_name': 'exe-2026-11-19.1'}])
        monkeypatch.setattr(tool.requests, 'post', _boom)
        assert tool.ensure_release('owner/name', 'tok', 'exe-2026-11-19.1') == 9

    def test_an_already_attached_name_is_not_uploaded_again(self, monkeypatch, tmp_path):
        tool = _tool()
        part = tmp_path / 'CaiXiHui-win64.zip.001'
        part.write_bytes(b'x' * 10)
        monkeypatch.setattr(tool, 'attached', lambda repo, token, release_id: {part.name: 10})

        def _boom(*args, **kwargs):
            raise AssertionError('re-uploading overwrites published bytes the feed already pinned')

        monkeypatch.setattr(tool.requests, 'post', _boom)
        tool.upload('owner/name', 'tok', 12, [part])

    def test_the_token_comes_from_the_environment_only(self, monkeypatch, tmp_path):
        tool = _tool()
        monkeypatch.setattr(tool, 'DIST', tmp_path)
        for name in (*tool.ARCHIVES, *tool.STANDALONE):
            (tmp_path / name).write_bytes(b'A' * 20)
        monkeypatch.delenv('GITEE_TOKEN', raising=False)
        # A real run refuses before it touches the network…
        with pytest.raises(SystemExit) as refused:
            tool.publish('owner/name', 'exe-2026-11-19.1', {'exe-2026-11-19.1'})
        assert 'GITEE_TOKEN' in str(refused.value)
        # …a dry run needs no token at all: it reads the local bytes only.
        assert tool.publish('owner/name', 'exe-2026-11-19.1', {'exe-2026-11-19.1'}, dry_run=True) == 0
        # argv is world-readable, so there is no `--token`: passing one is an unknown argument.
        with pytest.raises(SystemExit) as rejected:
            tool.main(['exe-2026-11-19.1', '--token', 'abc'])
        assert rejected.value.code == 2


class TestTheOrder:
    def _dress(self, tool, monkeypatch, tmp_path) -> list[str]:
        """A dist folder of stub artifacts, with the split recorded instead of executed."""
        calls: list[str] = []
        monkeypatch.setenv('GITEE_TOKEN', 'tok')
        monkeypatch.setattr(tool, 'DIST', tmp_path)
        for name in (*tool.ARCHIVES, *tool.STANDALONE):
            (tmp_path / name).write_bytes(b'A' * 20)

        def write_shards(path, shard=0, *, dry_run=False):
            # The real call leaves a part on disk, and `publish` hashes it at the end.
            part = path.with_name(path.name + '.001')
            part.write_bytes(b'A' * 20)
            calls.append('write')
            return [part]

        monkeypatch.setattr(tool, 'write_shards', write_shards)
        return calls

    def test_the_release_is_created_before_the_prune(self, monkeypatch, tmp_path):
        """The prune refuses a keep-tag without a release entry — measured on 2026.11.18.2."""
        tool = _tool()
        calls = self._dress(tool, monkeypatch, tmp_path)
        monkeypatch.setattr(tool, 'ensure_release', lambda *args, **kwargs: calls.append('create') or 5)
        monkeypatch.setattr(tool, 'prune', lambda *args, **kwargs: calls.append('prune'))
        monkeypatch.setattr(tool, 'upload', lambda *args, **kwargs: calls.append('upload'))
        tool.publish('owner/name', 'exe-2026-11-19.1', {'exe-2026-11-19.1'})
        assert calls == ['write', 'write', 'create', 'prune', 'upload'], calls

    def test_a_dry_run_creates_nothing_and_prunes_nothing(self, monkeypatch, tmp_path):
        tool = _tool()
        calls: list[str] = []
        monkeypatch.setenv('GITEE_TOKEN', 'tok')
        monkeypatch.setattr(tool, 'DIST', tmp_path)
        for name in (*tool.ARCHIVES, *tool.STANDALONE):
            (tmp_path / name).write_bytes(b'A' * 20)

        def write_shards(path, shard=0, *, dry_run=False):
            calls.append('write')
            return [path]

        monkeypatch.setattr(tool, 'write_shards', write_shards)
        monkeypatch.setattr(tool, 'ensure_release', lambda *args, **kwargs: calls.append('create') or 0)
        monkeypatch.setattr(tool, 'prune', lambda *args, **kwargs: calls.append('prune'))
        monkeypatch.setattr(tool, 'upload', lambda *args, **kwargs: calls.append('upload'))
        tool.publish('owner/name', 'exe-2026-11-19.1', {'exe-2026-11-19.1'}, dry_run=True)
        # Only the local split runs: a dry run is the offline check made before the upload window.
        assert calls == ['write', 'write'], calls


def test_the_tool_runs_as_a_script():
    """A module with no `__main__` guard exits 0 and prints nothing — the release would look done."""
    out = subprocess.run(
        [sys.executable, str(TOOL), '--help'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=120,
        check=False,
    )
    assert out.returncode == 0, out.stderr[-800:]
    assert 'exe-2026-11-19.1' in out.stdout and '--dry-run' in out.stdout, out.stdout


def test_the_release_doc_names_the_tool_it_documents():
    """A step only a transcript knows is a step the next release re-invents."""
    doc = (REPO / 'docs' / 'release.md').read_text(encoding='utf-8')
    assert 'tools/publish_gitee.py' in doc, 'docs/release.md must name the publish tool'
    # Windows commands in that file write the path with backslashes; the file name is the claim.
    assert 'prune_gitee_releases.py' in doc, 'the prune step must stay documented too'
