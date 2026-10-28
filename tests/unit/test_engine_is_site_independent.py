"""``crawlers/engine`` is mechanics; a site's own facts live in the site's package.

The engine package promised "nothing here knows what a 微博 or a 视频 is" while three named
first-run dialogs and YouTube's InnerTube transport were sitting inside it. They now live beside
the crawlers that use them (``platforms/<id>/dialogs.py`` and ``platforms/youtube/innertube.py``),
and this file keeps them there: the mechanism (``Prompt``, ``dismiss``) stays shared, the wording
and the endpoints stay with the site.
"""

import ast
import importlib
from pathlib import Path

from crawlers.engine import popup

BACKEND = Path(__file__).resolve().parents[2] / 'backend'
ENGINE = BACKEND / 'crawlers' / 'engine'
PLATFORMS = BACKEND / 'crawlers' / 'platforms'


def _module_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding='utf-8'), str(path))
    found = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


class TestTheEngineHoldsOnlyMechanics:
    def test_no_module_in_the_engine_declares_a_dialog(self):
        offenders = []
        for path in sorted(ENGINE.glob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'), str(path))
            for node in tree.body:
                if (
                    isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == 'Prompt'
                ):
                    offenders.append(f'{path.name}:{node.lineno}')
        assert offenders == [], 'a dialog declaration returned to the site-independent engine: ' + ', '.join(offenders)
        assert not any(isinstance(value, popup.Prompt) for value in vars(popup).values())

    def test_no_module_in_the_engine_imports_a_platform(self):
        offenders = set()
        for path in sorted(ENGINE.glob('*.py')):
            for name in _module_level_imports(path):
                if name.startswith('crawlers.platforms'):
                    offenders.add(f'{path.name}: {name}')
        assert offenders == set(), 'the engine reached into a platform: ' + '; '.join(sorted(offenders))

    def test_the_innertube_transport_moved_to_the_site_that_asks_it(self):
        assert not (ENGINE / 'innertube.py').exists(), 'engine/innertube.py is back; it knows YouTube'
        from crawlers.platforms.youtube import crawler

        assert crawler.innertube.__name__ == 'crawlers.platforms.youtube.innertube'


class TestEveryDialogLivesWithItsSite:
    def test_every_declared_prompt_is_named_after_the_platform_that_shows_it(self):
        declared = []
        for path in sorted(PLATFORMS.glob('*/dialogs.py')):
            module = importlib.import_module(f'crawlers.platforms.{path.parent.name}.dialogs')
            for value in vars(module).values():
                if isinstance(value, popup.Prompt):
                    declared.append((path.parent.name, value))
        assert {prompt.key for _site, prompt in declared} == {
            'douyin_trust_login',
            'instagram_notifications',
            'youtube_consent',
        }, 'a dialog was added or removed without updating this contract'
        for site, prompt in declared:
            assert prompt.key.startswith(site), f'{site}/dialogs.py declares {prompt.key!r}, which names another site'

    def test_the_douyin_crawler_is_wired_to_the_dialog_it_shows(self):
        from crawlers.platforms.douyin.crawler import DouyinCrawler
        from crawlers.platforms.douyin.dialogs import TRUST_LOGIN

        assert DouyinCrawler.prompts == (TRUST_LOGIN,)
        assert TRUST_LOGIN.choose == ('取消',), 'declining is the measured-safe answer; accepting walks into 验证'
