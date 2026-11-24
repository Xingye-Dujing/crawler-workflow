"""Every platform's declared interstitial is one its crawler actually dismisses.

A ``dialogs.py`` nobody imports is a site fact no code can use: the 2026-10 refactor left
Instagram's and YouTube's declarations unmounted, and the dead-module gate had to carry an
exemption for each. The declarations are worth keeping only if the platform's own crawler
carries them, so this walks the declaration side and refuses one that no ``prompts`` tuple names.

No browser is needed: ``prompts`` is class data, and the dismissal mechanism is proved next to the
engine (``tests/unit/crawlers/test_crawler_engine.py``).
"""

import importlib
from pathlib import Path

import pytest

from crawlers import crawler_class
from crawlers.engine.popup import Prompt

pytestmark = pytest.mark.unit

PLATFORM_DIRS = Path(__file__).resolve().parents[3] / 'backend' / 'crawlers' / 'platforms'


def declared_prompts() -> list[tuple[str, str, Prompt]]:
    """Every ``Prompt`` constant under a platform's ``dialogs.py``, with its platform and name."""
    found = []
    for path in sorted(PLATFORM_DIRS.glob('*/dialogs.py')):
        platform = path.parent.name
        module = importlib.import_module(f'crawlers.platforms.{platform}.dialogs')
        for name in sorted(vars(module)):
            value = getattr(module, name)
            if isinstance(value, Prompt):
                found.append((platform, name, value))
    return found


class TestEveryDeclaredPopupIsMounted:
    def test_the_walk_finds_the_known_declarations(self):
        """A walk that finds nothing would report this gate green without reading anything."""
        names = {(platform, name) for platform, name, _prompt in declared_prompts()}
        assert {('douyin', 'TRUST_LOGIN'), ('instagram', 'NOTIFICATIONS'), ('youtube', 'CONSENT')} <= names

    def test_the_platform_crawler_carries_its_own_dialog(self):
        unmounted = [
            f'{platform}.{name}'
            for platform, name, prompt in declared_prompts()
            if prompt not in tuple(getattr(crawler_class(platform), 'prompts', ()) or ())
        ]
        assert unmounted == [], 'a declared dialog no crawl path dismisses: ' + ', '.join(unmounted)

    def test_a_mounted_prompt_names_the_site_it_belongs_to(self):
        """The key is the console's word for what was clicked, so it carries the platform."""
        for platform, _name, prompt in declared_prompts():
            assert platform in prompt.key, prompt.key
