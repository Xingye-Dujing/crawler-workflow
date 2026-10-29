"""Read the page's stylesheets through the page, not through a hardcoded file name.

``css/style.css`` used to be one 5,017-line file and a dozen test modules opened it by name to
grep a declaration. It is now one stylesheet per UI domain (``base``/``menu``/``canvas``/
``panels``/``controls``/``console``/``reusable``/``workspace``/``dialog``/``overlays``), loaded by
``index.html`` **in the order the rules were written** — the cascade tie-breaks exactly as before.

A test that named one file would have to know which domain owns a selector, and that knowledge
drifts the day a rule moves. Asking for the whole sheet keeps the assertion where it belongs (what
the browser ends up seeing) and leaves the split an implementation detail.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / 'backend' / 'static'
INDEX = STATIC / 'index.html'
STUDIO = STATIC / 'zenviz.html'
CSS_DIR = STATIC / 'css'
JS_DIR = STATIC / 'js'

_STYLESHEET = re.compile(r'<link\b[^>]*\brel="stylesheet"[^>]*\bhref="/css/([^"]+)"')
_SCRIPT = re.compile(r'<script\b[^>]*\bsrc="/js/([^"]+)"')


def page_js(page: Path = INDEX) -> list[Path]:
    """The ``/js/…`` modules one page boots, in the page's own order.

    Asked of ``index.html`` this is the workbench; of ``zenviz.html``, the studio. A rule about
    "who binds a global" has to be scoped to a page, because the two pages share the ``js/``
    directory and neither loads the other's modules.
    """

    return [JS_DIR / name for name in _SCRIPT.findall(page.read_text(encoding='utf-8'))]


def css_files(page: Path = INDEX) -> list[Path]:
    """The page's ``/css/…`` stylesheets, in the order the page loads them."""
    return [CSS_DIR / name for name in _STYLESHEET.findall(page.read_text(encoding='utf-8'))]


def css_text(page: Path = INDEX) -> str:
    """Everything those files contain, concatenated in page order — the sheet the browser parses."""
    return '\n'.join(path.read_text(encoding='utf-8') for path in css_files(page))


def js_files(name: str) -> list[Path]:
    """One module under ``js/`` plus every file split out of it, in page order.

    The split map (``tests/frontend/splits.json``, the same one the node loader and
    ``frontend_catalogue.with_companions`` read) decides the members, so a scan of "the settings
    panel" keeps working when a panel is cut again — and cannot quietly miss the half that moved.
    """
    from frontend_catalogue import with_companions

    seen: list[Path] = []
    for item in with_companions([JS_DIR / name]):
        path = Path(str(item))
        if path not in seen:
            seen.append(path)
    return seen


def js_text(*names: str) -> str:
    """The source the browser actually evaluates for those modules: each owner, then its split-outs."""
    paths: list[Path] = []
    for name in names:
        for path in js_files(name):
            if path not in paths:
                paths.append(path)
    return '\n'.join(path.read_text(encoding='utf-8') for path in paths)
