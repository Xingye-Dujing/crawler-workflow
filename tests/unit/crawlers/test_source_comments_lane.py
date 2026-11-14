"""A comments-mode source node must take the platform lane PER LINK, never at node level.

Regression, measured 2026-11-14 on the user's real machine: with 慢速采集 applied
(``same_platform_queue`` on), a 小红书 comments source opened its browser and then sat on
the first link until 停止. The node-level ``gate.hold`` (source.run) held the lane for the
whole node, and the comment engine's per-link ``gate.hold`` — the one that exists so a
blocked link can rotate logins — waited on the same non-reentrant lock. The pool branch
already stated the rule; the plain branch did not follow it.
"""

from types import SimpleNamespace

import pytest
from nodes.executors import source

pytestmark = pytest.mark.unit


class _Hold:
    def __init__(self, platform, events):
        self.platform = platform
        self.events = events

    def __enter__(self):
        self.events.append(('enter', self.platform))
        return False

    def __exit__(self, *exc):
        self.events.append(('exit', self.platform))
        return False


def _call():
    return SimpleNamespace(headless=True, ctx=None, upstream=None)


def _node(collect: str):
    return {
        'id': 'node-1',
        'type': 'source',
        'params': {'platform': 'xiaohongshu', 'collect': collect, 'urls': 'https://www.xiaohongshu.com/explore/x'},
    }


def test_a_comments_source_does_not_take_a_node_level_lane(monkeypatch):
    events = []
    monkeypatch.setattr(source.gate, 'hold', lambda platform, **kwargs: _Hold(platform, events))
    monkeypatch.setattr(source, 'execute_source_node', lambda *args, **kwargs: ['ran'])
    monkeypatch.setattr(source.capabilities, 'mode_of_node', lambda node: SimpleNamespace(handler='comments'))

    assert source.run(_node('comments'), _call()) == ['ran']
    assert events == [], 'a comments node held the lane itself, so its per-link turn would wait forever'


def test_a_search_source_still_takes_the_lane(monkeypatch):
    events = []
    monkeypatch.setattr(source.gate, 'hold', lambda platform, **kwargs: _Hold(platform, events))
    monkeypatch.setattr(source, 'execute_source_node', lambda *args, **kwargs: ['ran'])
    monkeypatch.setattr(source.capabilities, 'mode_of_node', lambda node: SimpleNamespace(handler='search'))

    assert source.run(_node('search'), _call()) == ['ran']
    assert events == [('enter', 'xiaohongshu'), ('exit', 'xiaohongshu')], events
