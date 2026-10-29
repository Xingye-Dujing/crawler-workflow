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

_STYLESHEET = re.compile(r'<link\b[^>]*\brel="stylesheet"[^>]*\bhref="/css/([^"]+)"')


def css_files(page: Path = INDEX) -> list[Path]:
    """The page's ``/css/…`` stylesheets, in the order the page loads them."""
    return [CSS_DIR / name for name in _STYLESHEET.findall(page.read_text(encoding='utf-8'))]


def css_text(page: Path = INDEX) -> str:
    """Everything those files contain, concatenated in page order — the sheet the browser parses."""
    return '\n'.join(path.read_text(encoding='utf-8') for path in css_files(page))
