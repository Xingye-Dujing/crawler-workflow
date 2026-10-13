"""Turn the stored ``userdict`` terms into a jieba user dictionary and load it process-wide.

``keyword.py`` already knows how to read ``<Config.DATA_DIR>/jieba/userdict.txt``, but nothing
ever wrote that file and the load was lazy (only the keyword path triggered it), so a domain
term was invisible to tokenize / topic / ML / word-cloud cuts. This module owns the file: it
materialises it from the lexicon store and loads it once at startup, so every jieba tokenizer
in the process sees the same words. A write from the panel calls :func:`reload_userdict` so the
change is live for the next run without a restart.
"""

import logging
import os

import jieba

from config import Config
from i18n import t

logger = logging.getLogger(__name__)

USERDICT_RELPATH = os.path.join('jieba', 'userdict.txt')


def userdict_path() -> str:
    return os.path.join(Config.DATA_DIR, USERDICT_RELPATH)


def materialize_userdict() -> int:
    """Write the stored terms to the jieba user-dict file; return how many were written.

    A missing or empty store writes an empty file (harmless). Any store error is swallowed to
    "no user dict" — the built-in pipeline must still run.
    """
    try:
        from stores import get_lexicon_store

        rows = get_lexicon_store().list('userdict')
    except Exception:
        logger.debug(t('lex.userdictReadFailed'), exc_info=True)
        return 0
    path = userdict_path()
    lines = []
    for row in rows:
        term = str(row.get('term') or '').strip()
        if not term:
            continue
        weight = row.get('weight')
        lines.append(f'{term} {weight}' if weight else term)
    if not lines and not os.path.isfile(path):
        # Nothing to add and no file to clear: touch nothing. Writing an empty file on every
        # import would make ``data/`` gain a byte — which the test isolation guard treats as a
        # failure, and which is pointless anyway.
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(lines))
        if lines:
            handle.write('\n')
    os.replace(tmp, path)
    return len(lines)


def load_userdict() -> None:
    """Materialise and load the user dict into the process-wide jieba tokenizer."""
    count = materialize_userdict()
    path = userdict_path()
    if count and os.path.isfile(path):
        try:
            jieba.load_userdict(path)
        except Exception:
            logger.warning(t('lex.userdictLoadFailed'), exc_info=True)


def reload_userdict() -> int:
    """Re-run after a panel edit so the next run sees the change without a restart."""
    # Reset keyword's path guard so it does not skip a dict it thinks it already loaded.
    try:
        from analyzers import keyword

        keyword._loaded_userdict = None
    except Exception:
        pass
    load_userdict()
    return 0
