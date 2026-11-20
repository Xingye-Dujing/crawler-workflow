"""The manifest the clients read: where each number comes from, and what it refuses to write.

``version.json`` is the only file every installed copy asks about, and its claims are exactly the
ones a hand-edited release gets wrong — a stale shard, a byte count from the folder instead of the
zip, a Mac entry carried over from the previous release. These cases pin the refusals, and the last
one hands the produced document to the CLIENT's own validator (``services.update``) so "we wrote a
feed" means "the updater accepts it".
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOL = REPO / 'tools' / 'write_release_feed.py'
pytestmark = pytest.mark.unit


def _tool():
    spec = importlib.util.spec_from_file_location('write_release_feed_contract', TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules['write_release_feed_contract'] = module
    spec.loader.exec_module(module)
    return module


def _dist(tmp_path: Path, archive: bytes = b'A' * 30, parts: tuple[int, ...] = (16, 14)) -> Path:
    """A dist folder whose shards really add up to the archive."""
    (tmp_path / 'CaiXiHui-win64.zip').write_bytes(archive)
    offset = 0
    for index, length in enumerate(parts, start=1):
        (tmp_path / f'CaiXiHui-win64.zip.{index:03d}').write_bytes(archive[offset : offset + length])
        offset += length
    return tmp_path


def _mac(platform: str, *, digest: str = 'a' * 64, size: int = 1000) -> dict:
    word = {'darwin-arm64': 'arm64', 'darwin-x64': 'x86_64'}[platform]
    return {
        f'CaiXiHui-macOS-{word}.dmg': {'name': f'CaiXiHui-macOS-{word}.dmg', 'digest': f'sha256:{digest}', 'size': size}
    }


class TestTheNumbers:
    def test_the_released_date_drops_the_build_number(self):
        tool = _tool()
        assert tool.released_date('2026.11.18.2') == '2026-11-18'
        assert tool.released_date('2026.12.01.1') == '2026-12-01'

    def test_the_parts_carry_their_own_digest_and_url(self, tmp_path):
        tool = _tool()
        dist = _dist(tmp_path)
        entry = tool.windows_entry('exe-2026-11-19.1', dist / 'CaiXiHui-win64.zip', sorted(dist.glob('*.00[12]')))
        assert entry['size'] == 30 and entry['sha256'] == tool.sha256(dist / 'CaiXiHui-win64.zip')
        assert [part['size'] for part in entry['parts']] == [16, 14]
        assert entry['parts'][0]['url'].endswith('/exe-2026-11-19.1/CaiXiHui-win64.zip.001')
        assert entry['parts'][0]['url'].startswith('https://gitee.com/')

    def test_every_written_shard_is_listed_not_just_the_first_two(self, tmp_path):
        tool = _tool()
        dist = _dist(tmp_path, archive=b'A' * 60, parts=(20, 20, 20))
        shards = tool.windows_shards(dist)
        assert [path.name for path in shards] == [f'CaiXiHui-win64.zip.{n:03d}' for n in (1, 2, 3)]
        entry = tool.windows_entry('exe-2026-11-19.1', dist / 'CaiXiHui-win64.zip', shards)
        assert len(entry['parts']) == 3

    def test_a_stale_split_is_refused_with_both_numbers(self, tmp_path):
        """The failure this exists for: a rebuilt zip beside the previous build's parts."""
        tool = _tool()
        dist = _dist(tmp_path, archive=b'A' * 40, parts=(16, 14))
        with pytest.raises(SystemExit) as refused:
            tool.windows_entry('exe-2026-11-19.1', dist / 'CaiXiHui-win64.zip', sorted(dist.glob('*.00[12]'))[:2])
        assert '30' in str(refused.value) and '40' in str(refused.value)

    def test_a_missing_part_is_named(self, tmp_path):
        tool = _tool()
        dist = _dist(tmp_path)
        with pytest.raises(SystemExit) as refused:
            tool.windows_entry('tag', dist / 'CaiXiHui-win64.zip', [dist / 'CaiXiHui-win64.zip.001', dist / 'nope'])
        assert 'nope' in str(refused.value)

    def test_a_mac_entry_points_at_the_github_release(self):
        tool = _tool()
        entry = tool.mac_entry('exe-2026-11-19.1', 'darwin-arm64', _mac('darwin-arm64', size=193607826))
        assert entry == {
            'archive': 'dmg',
            'url': 'https://github.com/Xingye-Dujing/crawler-workflow/releases/download/exe-2026-11-19.1/'
            'CaiXiHui-macOS-arm64.dmg',
            'sha256': 'a' * 64,
            'size': 193607826,
        }

    def test_an_unpublished_dmg_is_refused(self):
        tool = _tool()
        with pytest.raises(SystemExit) as refused:
            tool.mac_entry('exe-2026-11-19.1', 'darwin-x64', _mac('darwin-arm64'))
        assert 'x86_64' in str(refused.value)

    def test_a_dmg_without_a_digest_is_refused(self):
        """A published file with no digest is UNVERIFIED: the client refuses to install it."""
        tool = _tool()
        published = _mac('darwin-arm64')
        published['CaiXiHui-macOS-arm64.dmg']['digest'] = ''
        with pytest.raises(SystemExit) as refused:
            tool.mac_entry('tag', 'darwin-arm64', published)
        assert 'digest' in str(refused.value)


class TestTheDocument:
    def test_the_version_notes_and_platforms_are_required(self):
        tool = _tool()
        good = {'win32': {'sha256': 'a' * 64, 'size': 1}}
        with pytest.raises(SystemExit):
            tool.feed_document('1.0', 'notes', good)
        with pytest.raises(SystemExit):
            tool.feed_document('2026.11.19.1', '  ', good)
        with pytest.raises(SystemExit):
            tool.feed_document('2026.11.19.1', 'notes', {})

    def test_a_windows_only_release_drops_the_mac_entries(self, tmp_path, monkeypatch):
        """Leaving them would send a Mac client to the PREVIOUS DMG under a newer version."""
        tool = _tool()
        dist = _dist(tmp_path)

        def _boom(tag, repo=''):
            raise AssertionError('a Windows-only feed must not even ask for the mac assets')

        monkeypatch.setattr(tool, 'release_assets', _boom)
        document = tool.build_feed('2026.11.19.1', 'exe-2026-11-19.1', notes='x', windows_only=True, dist=dist)
        assert list(document['platforms']) == ['win32']

    def test_a_full_release_carries_all_three(self, tmp_path, monkeypatch):
        tool = _tool()
        dist = _dist(tmp_path)
        monkeypatch.setattr(tool, 'release_assets', lambda tag, repo='': {**_mac('darwin-arm64'), **_mac('darwin-x64')})
        document = tool.build_feed('2026.11.19.1', 'exe-2026-11-19.1', notes='x', windows_only=False, dist=dist)
        assert list(document['platforms']) == ['win32', 'darwin-arm64', 'darwin-x64']
        assert document['released'] == '2026-11-19'


def test_the_clients_own_validator_accepts_what_this_writes(tmp_path, monkeypatch):
    """The point of the tool: the updater must be able to read the file it produced."""
    from services import update

    tool = _tool()
    dist = _dist(tmp_path)
    monkeypatch.setattr(tool, 'release_assets', lambda tag, repo='': {**_mac('darwin-arm64'), **_mac('darwin-x64')})
    document = tool.build_feed('2026.11.19.1', 'exe-2026-11-19.1', notes='x', windows_only=False, dist=dist)

    assert update._valid_feed(document), 'the feed does not match the client’s schema'
    for platform, entry in document['platforms'].items():
        monkeypatch.setattr(update, '_platform_key', lambda key=platform: key)
        usable, why = update._asset_usable(entry)
        assert usable, f'{platform}: {why}'


def test_writing_keeps_the_file_readable_and_ordered(tmp_path):
    tool = _tool()
    dist = _dist(tmp_path)
    feed = tmp_path / 'version.json'
    document = tool.write_feed(
        '2026.11.19.1', 'exe-2026-11-19.1', notes='一句话', windows_only=True, feed=feed, dist=dist
    )
    text = feed.read_text(encoding='utf-8')
    assert text.endswith('\n') and json.loads(text) == document
    assert list(document) == ['schema', 'version', 'released', 'notes', 'platforms']
    assert document['version'] == '2026.11.19.1'


def test_the_tool_runs_as_a_script():
    """A module with no `__main__` guard exits 0 and prints nothing — the feed would never be written."""
    out = subprocess.run(
        [sys.executable, str(TOOL), '--help'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=120,
        check=False,
    )
    assert out.returncode == 0, out.stderr[-800:]
    assert '--windows-only' in out.stdout and '--notes-file' in out.stdout, out.stdout


def test_the_release_doc_names_the_tool_it_documents():
    doc = (REPO / 'docs' / 'release.md').read_text(encoding='utf-8')
    assert 'tools/write_release_feed.py' in doc, 'docs/release.md must name the feed writer'
