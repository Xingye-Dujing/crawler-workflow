"""The capability skills as the workspace reads them: a catalogue, a body and a named refusal.

``capabilities_kernel.knowledge`` owns the derivation; this module adds the two things the product
owns: the translated title and an ``AIError`` whose key the HTTP layer can localize. Keeping the
split means the kernel stays standard-library only while the workspace still refuses an unknown
skill by name instead of returning an empty page.
"""

from __future__ import annotations

from capabilities_kernel import knowledge as kernel

from ai.errors import AIError
from i18n import t

#: The smallest useful page and the largest a model should read in one call.
MIN_LIMIT = 1
MAX_LIMIT = 200


def _title(title_key: str, fallback: str) -> str:
    """The localized capability word, or its stable id when this process has no such table.

    A node's title key lives in the browser catalogue (the canvas draws it); the server keeps no
    second copy of those words, so a headless call falls back to the id the model already knows.
    """
    translated = t(title_key)
    return fallback if translated == title_key else translated


def _limit(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 30
    return max(MIN_LIMIT, min(number, MAX_LIMIT))


def catalog(kind: str = '', query: str = '', limit=30) -> dict:
    """The level-1 catalogue. An unknown kind is refused by name, never treated as 'all'."""
    kind = str(kind or '').strip()
    try:
        rows = kernel.catalog(kind=kind, query=str(query or ''), limit=_limit(limit))
    except ValueError as exc:
        raise AIError(
            'ai.skillKindBad',
            kind='bad_request',
            kind_name=kind,
            kinds=', '.join(kernel.KINDS),
        ) from exc
    for row in rows:
        row['title'] = _title(row['title_key'], row['capability'])
    return {'skills': rows, 'total': len(rows)}


def load(identifier: str) -> dict:
    """One level-2 body. An unknown id is refused with the id the caller sent."""
    text = str(identifier or '').strip()
    manifest = kernel.find(text)
    if manifest is None:
        raise AIError('ai.skillUnknown', kind='bad_request', skill=text)
    title = _title(manifest.identity.title_key, manifest.identity.id)
    return {
        'id': kernel.skill_id(manifest),
        'kind': manifest.identity.kind,
        'title': title,
        'markdown': kernel.render(manifest, title=title),
        'template': manifest.ai.template,
        'tools': list(kernel.KIND_TOOLS.get(manifest.identity.kind, ())),
    }
