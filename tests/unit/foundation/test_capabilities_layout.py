"""The declaration layer's shape: one platform per file, panel order, no crawling imports.

``capabilities/registry.py`` used to be a 1,577-line module that held the nine platforms, their
shared atoms, the CatBus vocabulary and the queries in one place. The split's promise is that a
platform is declared exactly once, in its own file, and that the query side never grows a second
copy of the matrix — so the promises get tests, not just a commit message:

* every module under ``capabilities/platforms/`` declares one ``CAPABILITY`` whose platform is
  its file name, and the package's tuple names every one of them;
* the tuple's order is the Data Source panel's order (pinned below — overseas last on purpose);
* the package imports nothing that crawls: the arrow points from crawlers to declarations;
* ``registry`` re-exports the *same objects* the declarations define, so a caller that imports
  ``BACKENDS`` from either spelling cannot get two answers.
"""

import ast
import sys
from pathlib import Path

from capabilities import catbus, fields, platforms, registry

BACKEND = Path(__file__).resolve().parents[3] / 'backend'
PLATFORMS_DIR = BACKEND / 'capabilities' / 'platforms'
CAPABILITIES_DIR = BACKEND / 'capabilities'
STDLIB = set(sys.stdlib_module_names)

#: The panel's order, and the only list of it: a Chinese-language user reaches for the first
#: entries, and the overseas three come last because they are the newest additions.
PANEL_ORDER = [
    'zhihu',
    'weibo',
    'xiaohongshu',
    'wechat',
    'bilibili',
    'douyin',
    'hongguo',
    'cnki',
    'youtube',
    'twitter',
]

#: Layers above the declarations. An import of any of these from ``capabilities`` would invert
#: the arrow (the panel must be answerable without Selenium/pandas/the app) — the same rule
#: ``test_foundation_layering`` applies to ``core``. Only module-level imports count; the two
#: function-local ``services.ingest.catbus`` seams are the deliberate request-time dependency.
ABOVE_CAPABILITIES = {
    'app',
    'api',
    'crawlers',
    'services',
    'analyzers',
    'engine',
    'nodes',
    'sessions',
    'scheduling',
    'runtime',
}
HEAVY = {'sklearn', 'scipy', 'matplotlib', 'joblib', 'torch', 'transformers', 'selenium', 'flask', 'pandas'}


class TestOnePlatformOneFile:
    def test_every_platform_module_declares_its_own_capability(self):
        files = {path.stem for path in PLATFORMS_DIR.glob('*.py')} - {'__init__'}
        assert files == {cap.platform for cap in platforms.CAPABILITIES}
        for stem in files:
            module = __import__(f'capabilities.platforms.{stem}', fromlist=['CAPABILITY'])
            assert module.CAPABILITY.platform == stem, (
                f'{stem}.py declares platform {module.CAPABILITY.platform!r}; a file that answers to '
                'another name is one platform living in two places again'
            )

    def test_the_panel_order_is_the_declared_order(self):
        assert [cap.platform for cap in platforms.CAPABILITIES] == PANEL_ORDER

    def test_the_registry_only_imports_the_matrix_rather_than_rebuilding_it(self):
        source = (CAPABILITIES_DIR / 'registry.py').read_text(encoding='utf-8')
        assert 'Capability(' not in source, 'the matrix belongs to capabilities/platforms/, not to the queries'


class TestTheDeclarationsImportNothingThatCrawls:
    def test_no_module_level_import_reaches_above_the_declaration_layer(self):
        offenders = set()
        for path in sorted(CAPABILITIES_DIR.rglob('*.py')):
            if path.name == '__init__.py':
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'), str(path))
            for node in tree.body:
                if isinstance(node, ast.Import):
                    roots = {alias.name.split('.')[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    roots = {node.module.split('.')[0]}
                else:
                    continue
                for root in roots:
                    if root in STDLIB or root in {'capabilities', 'core', 'i18n'}:
                        continue
                    if root in ABOVE_CAPABILITIES or root in HEAVY:
                        offenders.add(f'{path.relative_to(BACKEND).as_posix()}: imports {root}')
        assert offenders == set(), 'capabilities/ reached upward: ' + '; '.join(sorted(offenders))


class TestTheMatrixHasOneOwner:
    def test_the_registry_re_exports_the_very_objects_it_serves(self):
        assert registry.CAPABILITIES is platforms.CAPABILITIES
        assert registry.FILE_FIELDS is fields.FILE_FIELDS
        assert registry.BACKENDS is fields.BACKENDS
        assert registry.BACKEND_CATBUS == fields.BACKEND_CATBUS
        assert registry.CATBUS_ONLY_PLATFORMS is catbus.CATBUS_ONLY_PLATFORMS

    def test_the_shared_mode_factories_are_public_vocabulary(self):
        """The platform files import these names; a rename back to ``_hot_mode`` would make the
        public vocabulary private again and quietly force copies."""
        for name in (
            'KEYWORD',
            'TARGET',
            'RECOLLECT',
            'ACCOUNT',
            'BACKEND_FIELDS',
            'INPUT_COLUMN',
            'TIMES',
            'COMMENT_LIMIT',
            'COMMENT_TIMES',
            'PER_ARTICLE',
            'AUTHOR',
            'WITH_FACTS',
            'FULL_BODY',
            'BOARD',
        ):
            assert hasattr(fields, name), f'capabilities.fields.{name} is gone; the platform modules import it'
        for name in ('posts_mode', 'author_mode', 'hot_mode', 'comment_mode'):
            assert callable(getattr(fields, name))
