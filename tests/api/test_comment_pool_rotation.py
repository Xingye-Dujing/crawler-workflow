"""Pool mode at the comment node: rotation only for a wall BEFORE this link answered.

The rule the source node already follows (``tests/unit/executors/test_source_pool_rotation.py``)
applies per LINK here. A walk that returns rows and then reports BLOCKED has already read
data; rotating for it discarded those rows (only the LAST attempt's rows reach the writer),
benched a login for a link whose data had been read, and paid for the same walk again. A
zero-row wall is the one attempt a second login can redo with nothing to reconcile.

Offline throughout: the crawler and the comment session are scripted stubs.
"""

import capabilities.registry as capabilities
import pytest

import crawlers.commenting.protocol as _protocol
import crawlers.commenting.session as _comments
from services.pool import selector

pytestmark = pytest.mark.api

_URL = 'https://www.douyin.com/video/7000000000000000001'


class _FakeCrawler:
    """The owning browser a comment session is built on."""

    def __init__(self):
        self.risk_blocked = False
        self.login_wall = True
        self.driver = None
        self.end_reason = None
        self.skipped_targets = []

    def close(self):
        return None


class _ScriptedSession:
    """Stand-in for CommentSession: one scripted answer per attempt, in order."""

    instances: list = []
    script: list = []

    def __init__(self, driver, log=None, nap=None, abort=None, owner=None, include_replies=True):
        self._owner = owner
        self.attempt = len(_ScriptedSession.instances)
        _ScriptedSession.instances.append(self)

    def walk(self, platform, url, limit):
        return _ScriptedSession.script[self.attempt]


def _node(account='@pool'):
    return {
        'id': 'node-1',
        'type': 'source',
        'title': '评论',
        'platform': 'douyin',
        'params': {
            'platform': 'douyin',
            capabilities.MODE_KEY: 'comments',
            'urls': _URL,
            'comment_limit': 0,
            'account': account,
        },
    }


@pytest.fixture
def pool_calls(monkeypatch):
    """The pool, recorded instead of read: claims are two logins, nothing is persisted."""
    from services import pool

    calls = []
    logins = ('work', 'home')

    def claim(platform, exclude_accounts=()):
        excluded = set(exclude_accounts or ())
        for name in logins:
            if name not in excluded:
                calls.append(name)
                return selector.Candidate(platform, name)
        return None

    monkeypatch.setattr(pool, 'claim', claim)
    monkeypatch.setattr(pool, 'release', lambda candidate: None)
    monkeypatch.setattr(pool, 'observe', lambda *a, **k: {'reason': 'login_wall'})
    monkeypatch.setattr(pool, 'max_attempts', lambda: 2)
    monkeypatch.setattr(pool, 'account_word', lambda name: name or '')
    monkeypatch.setattr(pool, 'reason_word', str)
    return calls


@pytest.fixture(autouse=True)
def _scripted(monkeypatch, app_module):
    from nodes.executors import comment as comment_exec

    _ScriptedSession.instances = []
    _ScriptedSession.script = []
    monkeypatch.setattr(comment_exec, 'get_crawler', lambda *a, **k: _FakeCrawler())
    monkeypatch.setattr(comment_exec, 'add_log', lambda message, **k: None)
    monkeypatch.setattr(_comments, 'CommentSession', _ScriptedSession)
    # A direct executor call has no claim of its own; the loop's stop check reads this dict.
    monkeypatch.setitem(app_module.execution_state, 'running', True)
    monkeypatch.setitem(app_module.execution_state, 'stopping', False)
    # The blocked case raises the cookie-death flag on the SHARED state dict; monkeypatch puts
    # the previous value back, so the next test does not inherit "a cookie expired".
    monkeypatch.setitem(app_module.execution_state, 'cookie_expired', False)
    yield
    _ScriptedSession.instances = []
    _ScriptedSession.script = []


@pytest.mark.usefixtures('clean_globals')
def test_a_wall_that_already_answered_rows_keeps_them_and_spends_no_second_login(pool_calls):
    """The measured failure: 42 parents read, then the panel's replies gate; 42 rows dropped
    and two logins benched for one link."""
    from nodes.executors import comment as comment_exec

    _ScriptedSession.script = [([{'评论ID': 'c1', '评论内容': 'x'}], _protocol.BLOCKED)]
    with pytest.raises(ValueError) as refusal:
        comment_exec.execute_comment_node(_node(), headless=True, ctx=None)
    # Blocked is still a failed node with the cookie verdict — never a silent DONE.
    from i18n import platform_label

    assert platform_label('douyin') in str(refusal.value)
    assert len(_ScriptedSession.instances) == 1, 'the link was re-walked after answering rows'
    assert pool_calls == ['work'], 'a login was rotated away for a link that already answered'


@pytest.mark.usefixtures('clean_globals')
def test_a_zero_row_wall_still_rotates_to_the_next_login(pool_calls):
    """The carve-out this rule protects: nothing was read, so a second login owes nothing."""
    from nodes.executors import comment as comment_exec

    _ScriptedSession.script = [
        ([], _protocol.BLOCKED),
        ([{'评论ID': 'c1', '评论内容': 'x'}], _protocol.OK),
    ]
    rows = comment_exec.execute_comment_node(_node(), headless=True, ctx=None)
    assert rows == [{'评论ID': 'c1', '评论内容': 'x'}]
    assert len(_ScriptedSession.instances) == 2
    assert pool_calls == ['work', 'home']
