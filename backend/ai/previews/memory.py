"""Memory-artifact preview: the exact text that will be written, and nothing else.

The validator already trimmed the text to what the store accepts, so the preview carries the SAME
bytes the apply endpoint will persist — a card that previewed one string and applied another would
be a second, wrong opinion about the artifact.
"""

from ai.previews.base import Preview, PreviewItem, register
from i18n import t

_LIMIT = 160


def _clip(text: str) -> str:
    return text if len(text) <= _LIMIT else text[:_LIMIT] + '…'


def _preview(payload: dict, _current: dict | None = None) -> Preview:
    text = str(payload.get('text') or '').strip()
    return Preview(
        kind='memory',
        title=t('ai.preview.title'),
        summary=t('ai.preview.memory', text=_clip(text)),
        items=[
            PreviewItem(
                id='memory',
                label=t('ai.preview.memoryItem'),
                detail=t('ai.preview.chars', n=len(text)),
                action='add',
            )
        ],
    )


register('memory', _preview)
