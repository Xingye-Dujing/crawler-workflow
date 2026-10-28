"""The comment-walk plugin boundary: one walk per platform package, one registry, one dispatch.

``CommentSession`` used to carry seven platforms' page walks as methods and the engine reached one by
building a name out of a string (``getattr(session, 'crawl_' + platform)``). That shape cannot be
pinned, because any object answering any such name passed — which is how the CatBus backend came to
need a synthesised ``__getattr__`` just to stay reachable. These tests pin the replacement: the table,
the boundary a walk may ask of the session, and the named refusal when nobody wrote a platform.
"""

import ast
import inspect
from pathlib import Path

import pytest

from crawlers.commenting import walks
from crawlers.commenting.session import CommentSession
from crawlers.commenting.walks import WalkContext

PLATFORMS_DIR = Path(inspect.getfile(__import__('crawlers.platforms', fromlist=['__file__']))).parent

pytestmark = pytest.mark.unit


def _platforms_defining_a_walk() -> set[str]:
    """Every platform package whose ``comments.py`` defines a top-level ``walk``."""
    found = set()
    for path in sorted(PLATFORMS_DIR.glob('*/comments.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        if any(isinstance(node, ast.FunctionDef) and node.name == 'walk' for node in tree.body):
            found.add(path.parent.name)
    return found


class TestTheWalkTable:
    def test_the_registered_platforms_are_the_packages_that_define_a_walk(self):
        """A platform can gain a walk nobody can reach, or a reachability nobody wrote — both are red."""
        defined = _platforms_defining_a_walk()
        assert walks.platforms() == defined, (
            f'registry {sorted(walks.platforms())} != packages defining walk() {sorted(defined)}'
        )

    def test_the_import_list_is_the_same_set_as_the_packages(self):
        """The list that BUILDS the registry is pinned too: a walk module nobody imports is invisible.

        ``load_builtin_walks`` is explicit rather than automatic, so an author can add a platform
        directory, write ``walk``, and have the engine still refuse it. That is exactly the bug this
        test exists to catch before a crawl pays for it.
        """
        expected = {f'crawlers.platforms.{platform}.comments' for platform in _platforms_defining_a_walk()}
        assert set(walks._BUILTIN_WALK_MODULES) == expected, (
            f'import list {sorted(walks._BUILTIN_WALK_MODULES)} != walk modules {sorted(expected)}'
        )

    def test_the_scan_finds_the_walks_it_claims_to(self):
        """Teeth: the two assertions above compare two sets, and an empty pair matches trivially."""
        assert len(_platforms_defining_a_walk()) >= 7, _platforms_defining_a_walk()

    def test_the_registry_key_is_the_platform_directory_name(self):
        """``platform_for`` routes a link to a directory name, so a key spelled differently is a miss."""
        for platform in walks.platforms():
            assert (PLATFORMS_DIR / platform / 'comments.py').exists(), platform

    def test_a_platform_cannot_be_registered_twice(self):
        with pytest.MonkeyPatch.context() as patch:
            # A table the test owns: registering a fake under a real platform would leave it bound
            # for every later test in the session.
            patch.setattr(walks, '_WALKS', {})

            @walks.register('synthetic')
            def one_walk(session, url, limit):  # pragma: no cover - never runs
                return [], 'ok'

            with pytest.raises(ValueError, match='synthetic'):

                @walks.register('synthetic')
                def second_walk(session, url, limit):  # pragma: no cover - never runs
                    return [], 'ok'

    def test_a_walk_without_a_platform_key_is_refused(self):
        with pytest.raises(ValueError, match='platform key'):

            @walks.register('')
            def nameless(session, url, limit):  # pragma: no cover - never runs
                return [], 'ok'


class TestTheDispatch:
    def test_the_session_names_the_platform_when_no_walk_exists(self, monkeypatch):
        """An unregistered platform raises: a table that answers 「no comments」 for a site nobody
        wrote is the outcome this dispatch must never produce (AGENTS: 具名拒绝, never ``[]``)."""
        monkeypatch.setattr(walks, '_WALKS', {})
        monkeypatch.setattr(walks, '_BUILTINS_LOADED', True)
        session = CommentSession(driver=None, nap=lambda s: None)
        with pytest.raises(ValueError, match='kuaishou'):
            session.walk('kuaishou', 'https://kuaishou.com/short-video/x', 0)

    def test_the_walk_receives_the_platform_it_was_asked_about(self, monkeypatch):
        seen = []

        def fake_walk(session, url, limit):
            seen.append((session, url, limit))
            return [{'评论ID': 'c1'}], 'ok'

        monkeypatch.setattr(walks, '_WALKS', {'zhihu': fake_walk})
        monkeypatch.setattr(walks, '_BUILTINS_LOADED', True)
        session = CommentSession(driver=None, nap=lambda s: None)
        rows, status = session.walk('zhihu', 'https://www.zhihu.com/question/1', 5)
        assert status == 'ok' and rows == [{'评论ID': 'c1'}]
        assert seen == [(session, 'https://www.zhihu.com/question/1', 5)]

    def test_the_engine_no_longer_builds_a_method_name(self):
        """The old surface is gone, not kept alongside: a ``crawl_<platform>`` method on the session
        would mean two dispatch paths, and only one of them would be tested by the table above."""
        assert [name for name in vars(CommentSession) if name.startswith('crawl_')] == []

    def test_every_platform_walk_is_a_function_of_its_own_package(self):
        """Where the code lives is part of the contract: a walk that sits in ``commenting`` again
        puts seven sites' DOM knowledge back into one module."""
        for platform, walk in sorted(walks._WALKS.items()):
            assert walk.__module__ == f'crawlers.platforms.{platform}.comments', (platform, walk.__module__)


class TestTheWalkBoundary:
    def test_the_session_answers_everything_a_walk_may_ask(self):
        """``WalkContext`` is documentation unless something checks it: a walk that reaches for a
        helper the session does not have fails at crawl time, hundreds of pages deep.

        Asked of an instance, not of the class: ``log`` and ``nap`` are set in ``__init__`` (a
        caller may hand either, so they cannot be class attributes), and a class-level check would
        convict a session that works.
        """
        declared = [name for name in vars(WalkContext) if not name.startswith('_') and name != 'annotations']
        assert declared, 'the Protocol lost every member, so this test would pass on nothing'
        session = CommentSession(driver=None)
        missing = [name for name in declared if not hasattr(session, name)]
        assert missing == [], missing

    def test_a_walk_never_reaches_through_the_session_into_its_owner(self):
        """风控 and the wall question have methods of their own, so a platform module stays usable
        with no crawler behind it (the live tier builds a bare session off a browser)."""
        for path in PLATFORMS_DIR.glob('*/comments.py'):
            source = path.read_text(encoding='utf-8')
            assert '_owner' not in source, path
            assert 'risk_blocked =' not in source, path
