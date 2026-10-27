"""The platform plugin boundary: one directory per site, and sites may not reach into each other.

`docs/refactor_plan.md` Stage 1 moved each platform into `crawlers/platforms/<id>/` because one
platform's code used to live in three places (its crawler module, its `comments_<id>.py`, and that
platform's method + in-page JS inside the shared `comments.py`). Splitting files is easy to undo
silently — a new helper lands in a sibling platform, or a directory appears that nothing registers —
so this file pins the shape rather than trusting the layout to stay obvious:

* the registry and the directories are the same set of platform ids;
* every platform package really is a package with the module the registry names;
* no platform module imports another platform's module (that is how one site's facts leak into
  another's crawl, and it is the reason the old layout was wrong rather than merely untidy).
"""

import ast
from pathlib import Path

import pytest

from crawlers import CRAWLERS
from crawlers.commenting import session as comment_session

pytestmark = pytest.mark.unit

CRAWLERS_DIR = Path(__file__).resolve().parents[2] / 'backend' / 'crawlers'
PLATFORMS_DIR = CRAWLERS_DIR / 'platforms'


def _platform_dirs() -> set[str]:
    return {path.name for path in PLATFORMS_DIR.iterdir() if (path / '__init__.py').is_file()}


class TestTheRegistryIsTheDirectories:
    def test_every_platform_directory_is_registered(self):
        unregistered = _platform_dirs() - set(CRAWLERS)
        assert unregistered == set(), f'a directory nobody can reach crawls from: {sorted(unregistered)}'

    def test_every_registered_platform_has_its_own_directory(self):
        missing = {
            platform for platform, cls in CRAWLERS.items() if not (PLATFORMS_DIR / platform / 'crawler.py').is_file()
        }
        assert missing == set(), f'registered from somewhere else: {sorted(missing)}'

    def test_a_registered_class_lives_in_its_own_package(self):
        """The map key and the module path must agree, or the folder is decoration and the real
        grouping is still the file names."""
        wrong = {
            platform: cls.__module__
            for platform, cls in CRAWLERS.items()
            if cls.__module__ != f'crawlers.platforms.{platform}.crawler'
        }
        assert wrong == {}, f'platform id does not match where its class lives: {wrong}'


class TestPlatformsDoNotReachIntoEachOther:
    """Cross-platform imports are the drift this layout exists to prevent."""

    #: Modules a platform may depend on: its own package, and the shared layers.
    _ALLOWED_PREFIXES = ('crawlers.engine', 'crawlers.core', 'crawlers.commenting')

    def _foreign(self) -> list[str]:
        foreign = []
        for own in sorted(_platform_dirs()):
            for module in sorted((PLATFORMS_DIR / own).glob('*.py')):
                tree = ast.parse(module.read_text(encoding='utf-8'))
                for node in ast.walk(tree):
                    targets = []
                    if isinstance(node, ast.Import):
                        targets = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        targets = [node.module]
                    for target in targets:
                        if not target.startswith('crawlers.platforms.'):
                            continue
                        other = target.split('.')[2]
                        if other != own:
                            foreign.append(f'{own}/{module.name}:{node.lineno} imports {other}')
        return foreign

    def test_no_platform_module_imports_another_platform(self):
        assert self._foreign() == [], 'a platform reaching into another is how site facts leak: ' + '; '.join(
            self._foreign()
        )

    def test_the_scan_asks_the_imports_it_claims(self):
        """A guard that parses nothing is green forever: the shared comment session DOES import
        several platform packages, so it must be outside this rule and still have imports found."""
        tree = ast.parse(Path(comment_session.__file__).read_text(encoding='utf-8'))
        platform_imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom)) and 'crawlers.platforms.' in ast.unparse(node)
        ]
        assert len(platform_imports) >= 4, (
            'the comment session no longer imports platform modules — did the shape change?'
        )


class TestEveryPlatformDeclaresWhatTheFactoryAsks:
    """`cookie_hosts` / `is_crawlable` read class attributes, and `is_crawlable` used to supply a
    `getattr` default — which is how a new platform could silently answer "crawls" without anyone
    deciding it. The answer now has to exist on the class."""

    def test_each_class_states_the_host_it_cookies_on(self):
        silent = {platform for platform, cls in CRAWLERS.items() if not getattr(cls, 'domain', '')}
        assert silent == set(), f'platforms with no domain to plant a cookie on: {sorted(silent)}'

    def test_each_class_answers_whether_it_crawls(self):
        """The factory used to ask ``getattr(cls, 'supports_crawl', True)``, so a platform that never
        considered the question was answered for. ``Crawler`` declares it now, so the answer exists."""
        silent = [platform for platform, cls in CRAWLERS.items() if not hasattr(cls, 'supports_crawl')]
        assert silent == [], f'these would have been called crawlable by a default: {sorted(silent)}'

    def test_only_the_cookie_capture_platform_refuses(self):
        refusing = sorted(p for p, cls in CRAWLERS.items() if not cls.supports_crawl)
        assert refusing == ['instagram'], (
            f'instagram is the platform declared cookie-capture-only; {refusing} just joined it — if that '
            'is real, the crawl matrix and the refusal message have to say so too'
        )
