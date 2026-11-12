"""Gitee's 1 GB attachment budget: which files a release run may delete, and which it must keep.

The release feed (``version.json``) names exactly one tag, so "keep the newest" is the wrong rule:
a re-published older tag must stay downloadable, and deleting the current tag's split archives
would leave the feed pointing at three 404s. These cases pin the plan function and the two guards
(a typo must not empty the repository, a dry run must not delete) without touching the network.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOL = REPO / 'tools' / 'prune_gitee_releases.py'
pytestmark = pytest.mark.unit


def _tool():
    spec = importlib.util.spec_from_file_location('prune_gitee_contract', TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # ``@dataclass`` resolves its own module through ``sys.modules`` while the class is built,
    # so a module executed without being registered there fails at definition time.
    sys.modules['prune_gitee_contract'] = module
    spec.loader.exec_module(module)
    return module


def _release(tag: str, release_id: int, files: list[tuple[int, str, int]]) -> dict:
    return {
        'id': release_id,
        'tag_name': tag,
        'assets': [{'id': attach_id, 'name': name, 'size': size} for attach_id, name, size in files],
    }


def test_the_current_tag_keeps_every_attachment():
    tool = _tool()
    releases = [
        _release('exe-2026-11.13', 3, [(30, 'CaiXiHui-win64.zip.001', 99614720)]),
        _release('exe-2026-11.12', 2, [(20, 'CaiXiHui-win64.zip.001', 99614720)]),
    ]
    doomed, total = tool.plan(releases, {'exe-2026-11.13'})
    assert [item.tag for item in doomed] == ['exe-2026-11.12']
    assert total == 99614720


def test_every_older_tag_is_released_even_when_it_sorts_higher():
    """A re-published old tag is still the one ``version.json`` points at."""
    tool = _tool()
    releases = [
        _release('exe-2026-12', 4, []),
        _release('exe-2026-11.2', 1, [(11, 'CaiXiHui-Setup.exe.001', 5), (12, 'CaiXiHui-Setup.exe.002', 7)]),
        _release('exe-2026-11.13', 3, [(30, 'CaiXiHui-win64.zip.001', 9)]),
    ]
    doomed, total = tool.plan(releases, {'exe-2026-12'})
    assert sorted(item.name for item in doomed) == [
        'CaiXiHui-Setup.exe.001',
        'CaiXiHui-Setup.exe.002',
        'CaiXiHui-win64.zip.001',
    ]
    assert total == 21


def test_a_second_kept_tag_survives_the_sweep():
    """The manual is a separate release, not an old program version: naming it keeps its PDF."""
    tool = _tool()
    releases = [
        _release('manual-2026-11', 5, [(50, 'CaiXiHui-Manual-2026-11.pdf', 9)]),
        _release('exe-2026-11.13', 6, [(60, 'a.zip', 1)]),
        _release('exe-2026-11.12', 7, [(70, 'b.zip', 2)]),
    ]
    doomed, total = tool.plan(releases, {'exe-2026-11.13', 'manual-2026-11'})
    assert [item.name for item in doomed] == ['b.zip']
    assert total == 2


def test_a_release_without_attachments_costs_nothing_and_is_not_a_delete_target():
    tool = _tool()
    releases = [_release('manual-2026-11', 5, []), _release('exe-2026-11.13', 6, [(60, 'a.zip', 1)])]
    doomed, total = tool.plan(releases, {'exe-2026-11.13'})
    assert doomed == []
    assert total == 0


def test_an_unknown_keep_tag_refuses_before_deleting_anything(monkeypatch):
    """Without the guard a typo in ``--tag`` deletes the whole repository's release assets."""
    tool = _tool()
    monkeypatch.setattr(tool, 'list_releases', lambda repo, token: [_release('exe-2026-11.13', 3, [(30, 'a.zip', 1)])])
    with pytest.raises(SystemExit) as excinfo:
        tool.prune('owner/name', 'token', {'exe-2026-99'}, dry_run=False)
    assert 'exe-2026-11.13' in str(excinfo.value)


def test_a_dry_run_deletes_nothing(monkeypatch):
    tool = _tool()
    monkeypatch.setattr(
        tool,
        'list_releases',
        lambda repo, token: [_release('exe-2026-11.13', 3, [(30, 'a.zip', 1)]), _release('old', 2, [(20, 'b.zip', 2)])],
    )
    monkeypatch.setattr(
        tool, 'list_attachments', lambda repo, token, release_id: [{'id': 20, 'name': 'b.zip', 'size': 2}]
    )

    def _boom(*args, **kwargs):
        raise AssertionError('a dry run must not call the delete endpoint')

    monkeypatch.setattr(tool.requests, 'delete', _boom)
    assert tool.prune('owner/name', 'token', {'exe-2026-11.13'}, dry_run=True) == 0
