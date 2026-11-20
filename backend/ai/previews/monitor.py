"""Monitor-artifact preview: the normalized trigger rule the server would actually arm.

The spec is normalized through ``monitors.validate_spec`` — the same door ``create`` uses — so the
card cannot show a rule that the arm endpoint would later reinterpret or refuse. A malformed spec
raises its named refusal here, before the dialog is painted.
"""

from ai import monitors
from ai.previews.base import Preview, PreviewItem, register
from i18n import t


def _preview(payload: dict, _current: dict | None = None) -> Preview:
    spec = monitors.validate_spec(payload)
    events = ', '.join(spec['events']) or '—'
    filters = []
    if spec['statuses']:
        filters.append('status: ' + ', '.join(spec['statuses']))
    if spec['outcomes']:
        filters.append('outcome: ' + ', '.join(spec['outcomes']))
    if spec['node_ids']:
        filters.append('node: ' + ', '.join(spec['node_ids'][:5]))
    if spec['console_contains']:
        filters.append('console: ' + spec['console_contains'])
    detail = ' · '.join(filters)
    return Preview(
        kind='monitor',
        title=t('ai.preview.title'),
        summary=t('ai.preview.monitor', events=events),
        items=[
            PreviewItem(
                id='monitor',
                label=t('ai.preview.monitorItem'),
                detail=detail or events,
                action='add',
            )
        ],
        warnings=[t('ai.preview.monitorNote')],
    )


register('monitor', _preview)
