"""The settings declaration is the single source: every key, one place, no dead knobs.

These are gates, not feature tests: a key added to the store without a panel label, a
consumer or a preset entry would otherwise pass every other suite while being
unreachable from the page.
"""

import ast
from pathlib import Path

import pytest
from frontend_catalogue import catalog_keys
from runtime.settings_schema import BY_KEY, DEFAULTS, GROUPS, PRESETS, SETTINGS

pytestmark = pytest.mark.unit

BACKEND = Path(__file__).resolve().parents[3] / 'backend'


def _backend_text() -> str:
    return '\n'.join(path.read_text(encoding='utf-8') for path in BACKEND.rglob('*.py'))


def _frontend_text() -> str:
    return '\n'.join(path.read_text(encoding='utf-8') for path in (BACKEND / 'static' / 'js').rglob('*.js'))


class TestSchema:
    def test_keys_are_unique_and_defaults_are_derived(self):
        assert len(SETTINGS) == len({spec.key for spec in SETTINGS})
        assert set(DEFAULTS) == {spec.key for spec in SETTINGS}

    def test_every_field_has_a_group_label_and_kind(self):
        groups = {group_id for group_id, _label in GROUPS}
        kinds = {'str', 'int', 'float', 'bool', 'enum', 'path'}
        for spec in SETTINGS:
            assert spec.group in groups, spec.key
            assert spec.kind in kinds, spec.key
            assert spec.label.startswith('set.'), spec.key
            if spec.kind == 'enum':
                assert spec.choices, spec.key
                assert spec.default in spec.choices, spec.key

    def test_every_numeric_field_declares_bounds_around_its_default(self):
        for spec in SETTINGS:
            if spec.kind not in ('int', 'float'):
                continue
            assert spec.minimum is not None and spec.maximum is not None, spec.key
            assert spec.minimum <= spec.default <= spec.maximum, spec.key

    def test_every_consumer_is_one_of_the_known_shapes(self):
        for spec in SETTINGS:
            assert spec.consumer in ('server', 'browser', 'both', 'startup', 'internal'), spec.key

    def test_every_label_and_hint_exists_in_both_browser_languages(self):
        tables = catalog_keys()
        for spec in SETTINGS:
            for key in (spec.label, spec.hint):
                if not key:
                    continue
                for lang in ('en', 'zh'):
                    assert key in tables[lang], f'{spec.key}: {key} missing from {lang}'

    def test_preset_metadata_matches_the_bundles(self):
        for preset_id, preset in PRESETS.items():
            assert preset['values'], preset_id
            for key in preset['values']:
                assert key in BY_KEY, f'{preset_id} writes unknown setting {key}'
                assert preset_id in BY_KEY[key].presets, f'{key} is written by {preset_id} but does not declare it'

    def test_preset_labels_exist_in_both_browser_languages(self):
        tables = catalog_keys()
        for preset in PRESETS.values():
            for key in (preset['label'], preset['hint']):
                for lang in ('en', 'zh'):
                    assert key in tables[lang], f'{key} missing from {lang}'


class TestCoverage:
    def test_a_server_read_setting_is_read_somewhere_outside_the_store(self):
        backend = _backend_text()
        for spec in SETTINGS:
            if spec.consumer not in ('server', 'both'):
                continue
            if spec.key in ('max_visible_browsers', 'max_headless_browsers'):
                # engine.run picks one of the two by run shape, then asks get_setting on
                # the chosen name — still one read, just not a literal call per key.
                assert f"'{spec.key}'" in backend, f'{spec.key} is never named'
                continue
            if spec.key == 'default_source_part_size':
                # capabilities.registry chooses the source/comment column by mode.
                assert "'default_source_part_size'" in backend
                continue
            patterns = (
                f"get_setting('{spec.key}')",
                f"_int_setting('{spec.key}'",
                f"_bool_setting('{spec.key}'",
                f"_setting_number('{spec.key}'",
            )
            assert any(pattern in backend for pattern in patterns), f'{spec.key} is declared but never read'

    def test_a_browser_read_setting_is_named_by_the_page(self):
        frontend = _frontend_text()
        for spec in SETTINGS:
            if spec.consumer not in ('browser', 'both'):
                continue
            # Either the settings store maps it to a field or a consumer reads it by name.
            assert spec.key in frontend, f'{spec.key} is declared for the browser but never referenced'

    def test_a_startup_setting_is_read_before_the_store_is_used(self):
        for spec in SETTINGS:
            if spec.consumer != 'startup':
                continue
            assert spec.restart is True, f'{spec.key} is startup-only and must be flagged restart'

    def test_no_platform_module_reads_settings_directly_or_sleeps_by_hand(self):
        """A platform may keep its measured baseline; it may not keep a private switch.

        The global ``crawl_*_scale`` values must be the only user-facing pacing choice,
        so a platform that calls ``get_setting`` or ``time.sleep`` has bypassed it.
        """
        for path in (BACKEND / 'crawlers' / 'platforms').rglob('*.py'):
            if path.name == 'harvest.py':
                # The 红果 harvest's own machine paths (player, mitmdump, port, CA) are
                # settings by design and have no neutral module to read them through.
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if isinstance(node, ast.Call):
                    name = ''
                    if isinstance(node.func, ast.Name):
                        name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        name = node.func.attr
                    assert name != 'get_setting', f'{path.name} reads a setting directly'
                    if name == 'sleep':
                        owner = node.func.value if isinstance(node.func, ast.Attribute) else None
                        assert not (isinstance(owner, ast.Name) and owner.id == 'time'), (
                            f'{path.name} sleeps by hand instead of pacing'
                        )

    def test_no_platform_names_a_preset_key_itself(self):
        presets = {key for preset in PRESETS.values() for key in preset['values']}
        for path in (BACKEND / 'crawlers' / 'platforms').rglob('*.py'):
            text = path.read_text(encoding='utf-8')
            for key in presets:
                assert key not in text, f'{path.name} references preset key {key}'
