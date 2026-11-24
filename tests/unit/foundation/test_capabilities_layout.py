"""The declaration layer's shape: one platform per manifest, panel order, no crawling imports.

The platform matrix used to be ten modules under ``capabilities/platforms/``; it is now a capability
tree (``capabilities_kernel/platforms/<id>/manifest.py``) projected by ``capabilities.platforms``.
The promises are unchanged and still get tests: a platform is declared exactly once, the order is the
panel's order, the declarations import nothing that crawls, and the registry serves the very objects
the tree declares.
"""

import ast
import sys
from pathlib import Path

from capabilities import catbus, platforms, registry
from capabilities_kernel.platforms import _fields

BACKEND = Path(__file__).resolve().parents[3] / 'backend'
PLATFORM_TREE = BACKEND / 'capabilities_kernel' / 'platforms'
CAPABILITIES_DIR = BACKEND / 'capabilities'
KERNEL_DIR = BACKEND / 'capabilities_kernel'
STDLIB = set(sys.stdlib_module_names)

#: The panel's order, and the only list of it: a Chinese-language user reaches for the first entries,
#: and the overseas entries come last because they are the newest additions.
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

#: Layers above the declarations. An import of any of these from the declaration trees would invert
#: the arrow (the panel must be answerable without Selenium/pandas/the app). Only module-level imports
#: count; the function-local ``services.ingest.catbus`` seams are the deliberate request-time dependency.
ABOVE_DECLARATIONS = {
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


class TestOnePlatformOneManifest:
    def test_every_platform_directory_declares_its_own_manifest(self):
        dirs = {
            path.name
            for path in PLATFORM_TREE.iterdir()
            if path.is_dir() and (path / 'manifest.py').is_file() and not path.name.startswith('_')
        }
        assert dirs == {cap.platform for cap in platforms.CAPABILITIES}
        for ident in dirs:
            module = __import__(f'capabilities_kernel.platforms.{ident}.manifest', fromlist=['MANIFEST'])
            assert module.MANIFEST.platform == ident, (
                f'{ident}/manifest.py declares platform {module.MANIFEST.platform!r}; a directory that answers '
                'to another name is one platform living in two places again'
            )

    def test_the_panel_order_is_the_declared_order(self):
        assert [cap.platform for cap in platforms.CAPABILITIES] == PANEL_ORDER

    def test_the_registry_only_imports_the_matrix_rather_than_rebuilding_it(self):
        source = (CAPABILITIES_DIR / 'registry.py').read_text(encoding='utf-8')
        assert 'Capability(' not in source, 'the matrix belongs to the kernel tree, not to the queries'


class TestTheDeclarationsImportNothingThatCrawls:
    def test_no_module_level_import_reaches_above_the_declaration_layer(self):
        offenders = set()
        for root_dir in (CAPABILITIES_DIR, PLATFORM_TREE):
            for path in sorted(root_dir.rglob('*.py')):
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
                        if root in STDLIB or root in {'capabilities', 'capabilities_kernel', 'core', 'i18n'}:
                            continue
                        if root in ABOVE_DECLARATIONS or root in HEAVY:
                            offenders.add(f'{path.relative_to(KERNEL_DIR).as_posix()}: imports {root}')
        assert offenders == set(), 'a declaration reached upward: ' + '; '.join(sorted(offenders))


class TestTheMatrixHasOneOwner:
    def test_the_registry_re_exports_the_very_objects_it_serves(self):
        assert registry.CAPABILITIES is platforms.CAPABILITIES
        assert registry.FILE_FIELDS is _fields.FILE_FIELDS
        assert registry.BACKENDS is _fields.BACKENDS
        assert registry.BACKEND_CATBUS == _fields.BACKEND_CATBUS
        assert registry.CATBUS_ONLY_PLATFORMS is catbus.CATBUS_ONLY_PLATFORMS

    def test_the_shared_mode_factories_are_public_vocabulary(self):
        """The platform manifests import these names; a rename back to ``_hot_mode`` would make the
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
            assert hasattr(_fields, name), f'platforms._fields.{name} is gone; the platform manifests import it'
        for name in ('posts_mode', 'author_mode', 'hot_mode', 'comment_mode'):
            assert callable(getattr(_fields, name))
