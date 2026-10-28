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

pytestmark = pytest.mark.unit

CRAWLERS_DIR = Path(__file__).resolve().parents[3] / 'backend' / 'crawlers'
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

    def _foreign_in(self, own: str, source: str, filename: str) -> list[str]:
        """One module's cross-platform imports, as findings. Split out so a positive control can feed
        it source that no file in the tree contains — a scan nobody has seen convict anything is a scan
        that might be reading nothing."""
        foreign = []
        tree = ast.parse(source)
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
                    foreign.append(f'{own}/{filename}:{node.lineno} imports {other}')
        return foreign

    def _foreign(self) -> list[str]:
        findings = []
        for own in sorted(_platform_dirs()):
            for module in sorted((PLATFORMS_DIR / own).glob('*.py')):
                findings += self._foreign_in(own, module.read_text(encoding='utf-8'), module.name)
        return findings

    def test_no_platform_module_imports_another_platform(self):
        assert self._foreign() == [], 'a platform reaching into another is how site facts leak: ' + '; '.join(
            self._foreign()
        )

    def test_the_scan_convicts_a_cross_platform_import_it_is_given(self):
        """Positive control: the rule above is only as good as this — the parser does see the shape."""
        found = self._foreign_in(
            'zhihu',
            'from crawlers.platforms.weibo.comments import parse_weibo_comments\n',
            'crawler.py',
        )
        assert found == ['zhihu/crawler.py:1 imports weibo'], found
        # And its mirror: the same import inside its OWN package is not a finding.
        assert self._foreign_in('weibo', 'from crawlers.platforms.weibo.comments import x\n', 'crawler.py') == []

    def test_the_scan_reads_the_platform_tree_it_claims(self):
        """A guard over zero files is green forever, so the real scan must report how much it read."""
        read = sum(1 for own in _platform_dirs() for _ in (PLATFORMS_DIR / own).glob('*.py'))
        assert read >= 20, f'the scan saw {read} platform modules — did the layout move again?'
        same_package_imports = 0
        for own in sorted(_platform_dirs()):
            for module in sorted((PLATFORMS_DIR / own).glob('*.py')):
                tree = ast.parse(module.read_text(encoding='utf-8'))
                same_package_imports += sum(
                    1
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                    and f'crawlers.platforms.{own}' in ast.unparse(node)
                )
        assert same_package_imports >= 5, (
            f'only {same_package_imports} platform imports found — the parser is not seeing what the '
            f'rule is about (measured 2026-10-27: 7 — each comment walk reaching its own crawler for '
            f'the id parser, plus the hongguo harness pair)'
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


class TestTheCoreLayering:
    """``crawlers/core/`` is four files with a direction, and the direction is the point.

    `faults.py` answers "what kind of failure is this" and must be importable by code that owns no
    browser at all (the CatBus backend, an analyzer honouring 停止, the live-tier skip decision).
    `browser.py` answers "how is one Chrome built on this machine" and must not know a crawl exists.
    `crawler.py` is the crawl contract that reads those two. When all three were one file, every
    one of those questions dragged selenium and a chromedriver launch into the others' import path,
    and a test that only wanted the stop exception had to be able to construct a browser.
    """

    #: The selenium names that mean "this module drives a window". ``selenium.common.exceptions`` and
    #: ``selenium.webdriver.support`` stay legal in the base class: reading a timeout is not assembly.
    _ASSEMBLY_MODULE_ROOTS = ('selenium.webdriver.chrome', 'selenium.webdriver.remote', 'sessions.profiles')
    #: Call names that mean "this module is configuring or launching a browser itself".
    _ASSEMBLY_CALLEES = (
        'add_argument',
        'add_arguments',
        'add_experimental_option',
        'set_preference',
        'set_window_size',
        'Options',
        'Service',
        'ChromeWebDriver',
    )
    #: Attribute *assignments* that are the same decision written without a call.
    _ASSEMBLY_ASSIGNMENTS = ('page_load_strategy', 'binary_location')

    def _assembly_calls(self, path: Path) -> list[str]:
        """Every statement in a file that configures or launches a browser, as ``file:line name``.

        Read off the AST because the shapes that would reappear are the ones a substring grep
        misses: ``opts.add_arguments([...])`` is a real selenium API and ``add_arguments`` does not
        contain ``add_argument(``; ``options=Options()`` would be spelled with any local name.
        """
        findings = []
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Call):
                name = getattr(node.func, 'attr', None) or getattr(node.func, 'id', None)
                if name in self._ASSEMBLY_CALLEES:
                    findings.append(f'{path.name}:{node.lineno} {name}')
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr in self._ASSEMBLY_ASSIGNMENTS:
                        findings.append(f'{path.name}:{node.lineno} {target.attr}')
        return findings

    def _imports(self, path: Path, *, walk: bool = False) -> set[str]:
        """Module names a file imports, resolved through ``__package__`` so ``from .crawler import`` —
        the idiomatic spelling *inside one package* — is the same answer as the absolute one.

        ``walk=False`` reads top-level statements only (the *cost* question: importing a name at the
        top of a module is what a caller pays). ``walk=True`` reads every import anywhere in the file,
        including one inside a function, which is how a cycle "solved" by deferring it stays visible.
        """
        tree = ast.parse(path.read_text(encoding='utf-8'))
        nodes = list(ast.walk(tree)) if walk else list(tree.body)
        package = path.parent.name
        found = set()
        for node in nodes:
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    # Relative: ``from .crawler import y`` → ``<package>.crawler`` and
                    # ``from . import x`` → ``<package>.x``. The MODULE is what a file depends on,
                    # never the names carried out of it; left unresolved, a relative import — the
                    # idiomatic spelling inside one package — reads as no dependency at all.
                    base = package if node.level == 1 else f'{package}.{"." * (node.level - 1)}'
                    if node.module:
                        found.add(f'{base}.{node.module}')
                    else:
                        found.update(f'{base}.{alias.name}' for alias in node.names)
                elif node.module:
                    found.add(node.module)
        return found

    def _core(self, filename: str) -> Path:
        return CRAWLERS_DIR / 'core' / filename

    def test_the_failure_vocabulary_needs_no_browser_and_no_session(self):
        """`CrawlerStopped` is raised by a comment engine, a simhash scan and a subprocess reader.

        None of those has a driver, so if faults.py ever imports selenium (or the base class) the
        cheapest refusal in this repo becomes the most expensive import in it. ``walk=True``: a
        lazy import inside a helper is the same dependency, paid on the path that raises.
        """
        imports = self._imports(self._core('faults.py'), walk=True)
        assert not [name for name in imports if name.split('.')[0] == 'selenium'], (
            f'a failure name must not cost a browser to import: {sorted(imports)}'
        )
        assert not any(name.endswith('crawler') for name in imports), 'the base class depends on the faults, never back'

    def test_the_browser_assembler_does_not_know_what_a_crawl_is(self):
        """`ProfileWarmer` builds a browser to produce a directory and reads no site.

        That is only possible while `browser.py` imports nothing from the crawl contract; the moment
        it does, "launch a Chrome on this machine" can no longer be asked without a session.
        """
        imports = self._imports(self._core('browser.py'), walk=True)
        offenders = sorted(name for name in imports if name.endswith(('.crawler', '.video')))
        assert not offenders, f'browser.py is the lower layer: the base class imports it, never back ({offenders})'

    def test_the_base_class_no_longer_assembles_a_browser_itself(self):
        """The assembly is `browser.launch`'s job, so the base class must not name the parts.

        Read off the AST, not off the text: a second launch path in ``Crawler`` is how the desktop
        launcher and a crawl came to disagree about this machine, and the spelling that would evade a
        substring grep (``opts.add_arguments([...])``, ``webdriver.Chrome``, an experimental option
        re-added by hand) is exactly the shape that would reappear.
        """
        crawler = self._core('crawler.py')
        findings = self._assembly_calls(crawler)
        assert not findings, f'the base class is building a browser again: {findings}'
        imports = self._imports(crawler)
        assert not [name for name in imports if name.startswith(tuple(self._ASSEMBLY_MODULE_ROOTS))], (
            f'crawler.py imports an assembly module directly: {sorted(imports)}'
        )
        assert 'browser.launch' in crawler.read_text(encoding='utf-8'), (
            'and it must go through the one assembler, not around it'
        )

    def test_the_scanners_convict_source_that_is_not_in_the_tree(self, tmp_path):
        """Positive control: each predicate above can actually fail, so a green run means something.

        Two spellings of the same violation, because the one that breaks a layering rule most
        naturally is the *relative* import inside the package — which an absolute-name scan reports
        as clean. And an ``add_arguments`` call, which a substring grep for ``add_argument(`` misses.
        """
        inside_package = tmp_path / 'core'
        inside_package.mkdir()
        sample = inside_package / 'looks_like_browser.py'
        sample.write_text(
            'from .crawler import UNDER_TARGET\n'
            'from selenium.webdriver.chrome.webdriver import WebDriver\n'
            'import selenium\n\n'
            'def build(opts):\n'
            '    opts.add_arguments(["--headless=new"])\n'
            '    return WebDriver()\n',
            encoding='utf-8',
        )
        # The relative import resolves through the sample's own directory, so the layering check
        # (`endswith('.crawler')`) convicts it — the violation a plain absolute-name scan reports clean.
        assert 'core.crawler' in self._imports(sample), 'a relative import must resolve to the base class'
        assert 'core.crawler' in self._imports(sample, walk=True), 'and so must a deferred one'
        assembly_imports = [
            name for name in self._imports(sample) if name.startswith(tuple(self._ASSEMBLY_MODULE_ROOTS))
        ]
        assert assembly_imports == ['selenium.webdriver.chrome.webdriver'], (
            f'the assembly-import predicate read: {assembly_imports}'
        )
        # ``add_arguments`` is a real selenium API and does not contain ``add_argument(``, so only an
        # AST name match catches it — that is the evasion the token grep used to allow.
        findings = self._assembly_calls(sample)
        assert any('add_arguments' in finding for finding in findings), f'the call scanner read: {findings}'
