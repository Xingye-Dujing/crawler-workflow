"""One reader for the BROWSER dictionary: where the words live, and what they say.

The dictionary used to be one 3,600-line block inside ``app.js``. It is now that block *plus* every
``js/i18n/<domain>.js`` the page loads before it — a browser merges them at load and refuses a key two
domains both claim. Every audit that asks "does this word exist / what does it say" has to read the
same shape the browser does, so the knowledge lives here once: a test that re-parses ``app.js`` by
hand reports the moved half as missing words, and one that reads only the moved files would miss the
remainder.

``entry_text`` is the quoting helper: a test that pins a *sentence* (not merely the existence of a
key) reads the value as written, English then Chinese.
"""

import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / 'backend' / 'static'
JS_DIR = STATIC_DIR / 'js'
CATALOGUE_DIR = JS_DIR / 'i18n'

#: ``'key': 'value'`` / ``"key": "value"`` — the declaration shape, in either quote or language.
DICT_KEY = re.compile(r"""['"]([A-Za-z][\w.]*)['"]\s*:\s*['"]""")
#: A one-line entry with its text; a value spread over lines is skipped rather than half-parsed.
TEXT_ENTRY = re.compile(r"""['"]([A-Za-z][\w.]*)['"]\s*:\s*'([^'\n]*)'""")


def catalog_files() -> list[Path]:
    """Every file that declares browser words, in the order the page loads them."""

    return [JS_DIR / 'app.js', *sorted(CATALOGUE_DIR.glob('*.js'))]


def catalog_data(path: Path) -> str:
    """The dictionary region of one catalogue file — its declarations, not its logic."""

    src = path.read_text(encoding='utf-8')
    if path.name == 'app.js':
        # ``dict: _mergeCatalogues({ en: … })`` once a domain has moved, ``dict: { en: … }`` before.
        return src[src.index('dict: ') : src.index('_missing:')]
    return src[src.index('name:') : src.rindex('});')]


def catalog_bodies() -> dict[str, str]:
    """{lang: the text of that language's dictionary, across every file that holds part of it}."""

    bodies = {'en': [], 'zh': []}
    for path in catalog_files():
        data = catalog_data(path)
        middle = data.index('zh: {')
        bodies['en'].append(data[:middle])
        bodies['zh'].append(data[middle:])
    return {lang: '\n'.join(parts) for lang, parts in bodies.items()}


def catalog_keys() -> dict[str, set[str]]:
    """{lang: every key the browser can answer with}."""

    return {lang: {m.group(1) for m in DICT_KEY.finditer(body)} for lang, body in catalog_bodies().items()}


def catalog_texts() -> dict[str, dict[str, str]]:
    """{lang: {key: text}} for the entries written on one line.

    A multi-line template is left out rather than guessed at: its slots are covered by the parity
    audit, and a regex that reached across lines would report a slot that is not there.
    """

    return {lang: dict(TEXT_ENTRY.findall(body)) for lang, body in catalog_bodies().items()}


def words_missing(prefix: str, names) -> list[str]:
    """``<prefix><name>`` for every name, asked of BOTH languages of the whole dictionary.

    A computed key — ``chart.`` + view, ``nodeType.`` + type — is invisible to the parity audit and
    to the reachability scan, because both walk the keys that ARE declared. So this walks the
    universe of values instead, which is the side that can be missing.
    """

    tables = catalog_keys()
    return [
        f'{prefix}{name} in {lang}'
        for name in sorted(names)
        for lang in ('en', 'zh')
        if f'{prefix}{name}' not in tables[lang]
    ]


def entry_text(key: str, window: int = 900) -> tuple[str, str]:
    """The value of one key as written: ``(english, chinese)``.

    ``key`` is refused by name when either language lacks it — a test quoting a sentence must not
    silently compare English against English because a domain file was renamed.
    """

    out = []
    for lang in ('en', 'zh'):
        body = catalog_bodies()[lang]
        at = body.find(f"'{key}'")
        if at == -1:
            at = body.find(f'"{key}"')
        assert at != -1, f'{key} is not declared in the browser catalogue ({lang})'
        out.append(body[at : at + window])
    return out[0], out[1]


def with_catalogue(paths) -> list[str]:
    """A harness's file list with app.js's own DATA in front of it.

    ``app.js`` merges ``js/i18n/<domain>.js`` at load, so a driver that boots app.js without them
    gets an application with no words: every ``t()`` echoes its key, and a text assertion then
    measures the echo instead of the sentence. ``tests/frontend/page_scripts.mjs`` carries this rule
    for the harnesses that read the page; the drivers that hand file paths over need it too, from
    the same place, or the two disagree about what "loaded app.js" means.
    """

    ordered = [str(path) for path in paths]
    domains = [str(path) for path in catalog_files()[1:]]
    if not domains:
        return ordered
    out: list[str] = []
    for item in ordered:
        if Path(item).name == 'app.js':
            out.extend(domains)
            domains = []
        out.append(item)
    return out
