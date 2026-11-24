"""The AI workspace's server boundary has exactly two spellings of ``fetch``, both in ``kernel/``.

W5 split the 4,446-line panel into ``ai/kernel`` + ``ai/features`` + ``ai/render`` and gave the
workspace one JSON door. The split left the door under-used: 38 routes in the feature modules still
spelled ``fetch`` + ``Content-Type`` + ``JSON.stringify`` + ``.json()`` themselves, so a refusal, its
status and the field it updates were re-derived at every call site — and the two product routes the
panel also calls (a chart render, a page setting) had nowhere to go at all.

The rule this gate enforces is mechanical and one sentence long: **only the door and the stream
opener may name ``fetch``**. Two exemptions, both by name and both with their reason:

* ``ai/kernel/http.js`` — the door itself (``jsonDoor``), which is where ``fetch`` belongs;
* ``ai/kernel/sse.js`` — the stream opener: ``response.body`` and ``Accept: text/event-stream`` are
  not expressible as JSON, and the non-stream fallback reads the raw body too.

Proved on a synthetic tree as well, because a scan pointed only at the real directory cannot show
that it would ever say no.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
AI_DIR = ROOT / 'backend' / 'static' / 'js' / 'ai'

#: The two files allowed to spell a raw call, and why — a third entry is a decision, not a shortcut.
ALLOWED = {
    'ai/kernel/http.js': 'the JSON door itself',
    'ai/kernel/sse.js': 'the stream opener: response.body and the event-stream Accept header',
}

#: A raw call is `fetch(` not preceded by a word character or a dot — `AIHttp.fetch(` is the door,
#: not a route spelling itself.
_RAW = re.compile(r'(?<![\w.])fetch\s*\(')


def raw_calls(root: Path = AI_DIR) -> list[str]:
    """``ai/<module>:<line>`` for every raw call outside the two allowed files."""

    found: list[str] = []
    for path in sorted(root.rglob('*.js')):
        name = 'ai/' + path.relative_to(root).as_posix()
        if name in ALLOWED:
            continue
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if _RAW.search(line):
                found.append(f'{name}:{number}')
    return found


class TestTheBoundary:
    def test_no_feature_module_spells_fetch(self):
        assert raw_calls() == [], (
            'ask AIHttp (workspace routes) or ProductHttp (the rest of the page) instead: ' + ', '.join(raw_calls())
        )

    def test_the_feature_modules_really_ask_the_door(self):
        """The gate above is only meaningful if the calls moved, not vanished."""

        asked = 0
        for path in (AI_DIR / 'features').glob('*.js'):
            asked += len(re.findall(r'\b(?:AIHttp|ProductHttp)\.', path.read_text(encoding='utf-8')))
        assert asked >= 30, f'only {asked} door calls in ai/features — a route was deleted, not redirected'

    def test_the_stream_opener_prefixes_the_one_base(self):
        """``_stream`` takes a route, so no feature module needs to know ``AI_BASE`` at all."""

        sse = (AI_DIR / 'kernel' / 'sse.js').read_text(encoding='utf-8')
        assert 'AIStream.post(AIHttp.url(path)' in sse

    def test_a_base_is_spelled_once(self):
        spellings = [
            f'{path.name}:{number}'
            for path in AI_DIR.rglob('*.js')
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1)
            if re.search(r"""['"]/api/ai/ws""", line)
        ]
        assert spellings == ['http.js:11'], (
            'the workspace prefix belongs to kernel/http.js only; these spell it again: ' + ', '.join(spellings)
        )


class TestTheGateCanFail:
    def test_a_raw_call_in_a_feature_module_is_reported(self, tmp_path):
        (tmp_path / 'features').mkdir()
        (tmp_path / 'features' / 'bad.js').write_text("fetch('/api/ai/ws/chat')\n", encoding='utf-8')
        assert raw_calls(tmp_path) == ['ai/features/bad.js:1']

    def test_the_door_and_the_stream_opener_are_exempt(self, tmp_path):
        for name in ALLOWED:
            path = tmp_path / name.split('/', 1)[1]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fetch('/x')\n", encoding='utf-8')
        assert raw_calls(tmp_path) == []

    def test_a_door_call_is_not_a_raw_call(self, tmp_path):
        (tmp_path / 'features').mkdir()
        (tmp_path / 'features' / 'ok.js').write_text(
            "await AIHttp.post('/chat', {});\nreturn AIHttp.fetch('/files', options);\n",
            encoding='utf-8',
        )
        assert raw_calls(tmp_path) == []
