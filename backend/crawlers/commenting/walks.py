"""The comment-walk registry: platform → ``walk(session, url, limit)``.

``session.py`` owns the browser and the reads every platform shares; the page walk that reads one
platform's comments lives in that platform's own package
(``crawlers/platforms/<id>/comments.py``) and registers itself here. The engine then asks this table
instead of building the method name out of a string — ``getattr(session, 'crawl_' + platform)`` had
to be answered by *whatever object happened to carry that name*, which is why the CatBus backend
needed a :meth:`__getattr__` that synthesised a method to keep the dispatch working.

Two tables must agree and are pinned against each other by ``tests/unit/crawlers/test_comments.py``: the
directories under ``crawlers/platforms/`` that define a ``walk``, and the keys registered here. A
platform can therefore not gain a walker nobody can reach, nor a reachability nobody wrote.

The set of *importable* built-ins is listed rather than discovered because the alternative is an
import side effect that some other module has to trigger by accident: a platform's parser import
would silently be its registration, and deleting an unused parser would delete its walk.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    pass

#: ``walk(session, url, limit) -> (rows, verdict)``; the verdict is one of protocol's OK/BLOCKED/DEAD.
Walk = Callable[..., tuple]

_WALKS: dict[str, Walk] = {}
_BUILTINS_LOADED = False

#: One entry per platform package that owns a browser comment walk.
_BUILTIN_WALK_MODULES = (
    'crawlers.platforms.bilibili.comments',
    'crawlers.platforms.douyin.comments',
    'crawlers.platforms.twitter.comments',
    'crawlers.platforms.weibo.comments',
    'crawlers.platforms.xiaohongshu.comments',
    'crawlers.platforms.youtube.comments',
    'crawlers.platforms.zhihu.comments',
)


class WalkContext(Protocol):
    """What a platform walk may ask of the session it is handed.

    This is the whole boundary between ``commenting`` and ``platforms``: a walk gets a live browser
    and these reads, and reaches nothing else. It exists so the walks do not import the session
    class (a cycle: the session imports the registry to dispatch), and so a helper an author thinks
    is "obviously on the session" is caught by ``TestTheWalkBoundary`` rather than at crawl time.
    """

    driver: Any

    def log(self, message: str) -> None: ...

    def nap(self, seconds: float) -> None: ...

    def may_stop(self) -> bool: ...

    def fetch_in_page(self, url: str, timeout_ms: int = 25000) -> str: ...

    def body_head(self, limit: int = 600) -> str: ...

    def safe_text(self, element) -> str: ...

    def node_text(self, selector: str) -> str: ...

    def find_or_none(self, selector: str): ...

    def mark_risk_blocked(self) -> None: ...

    def is_walled(self) -> bool: ...


def register(platform: str):
    """Decorator: bind the decorated function as *platform*'s walk. A duplicate is refused.

    ``@register('zhihu')`` above the walk is the whole registration, so the platform key sits next to
    the code that answers for that site and nowhere else — the table below is built by importing, and
    never by a second list of platforms someone has to remember to update.
    """

    def attach(walk: Walk) -> Walk:
        key = str(platform or '').strip()
        if not key:
            raise ValueError('a comment walk needs a platform key')
        if key in _WALKS and _WALKS[key] is not walk:
            raise ValueError(f'platform {key} already has a comment walk')
        _WALKS[key] = walk
        return walk

    return attach


def walk_for(platform: str) -> Walk | None:
    """The walk for *platform*, or ``None`` — the caller names what is missing."""
    load_builtin_walks()
    return _WALKS.get(str(platform or '').strip())


def platforms() -> frozenset[str]:
    load_builtin_walks()
    return frozenset(_WALKS)


def load_builtin_walks() -> None:
    """Import every built-in platform walk module once, registering as it goes.

    Idempotent: the first dispatch pays for it, the rest see the flag.
    """
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    for name in _BUILTIN_WALK_MODULES:
        importlib.import_module(name)
    _BUILTINS_LOADED = True


def reset_for_tests() -> None:
    """Drop every registration and the load flag so a test can rebuild the table from nothing."""
    global _BUILTINS_LOADED
    _WALKS.clear()
    _BUILTINS_LOADED = False


__all__ = [
    'Walk',
    'WalkContext',
    'load_builtin_walks',
    'platforms',
    'register',
    'reset_for_tests',
    'walk_for',
]
