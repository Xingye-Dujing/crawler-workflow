"""Chart-spec preview: the chart, dataset and named columns a render would use.

The full validation (chart type, dataset, required columns) stays in ``/api/ai/chart/preview`` and
``/api/visualize/render``; this preview is only the legible description, never a second gate that
could drift from them.
"""

from ai.previews.base import Preview, PreviewItem, register
from i18n import t


def _preview(payload: dict, _current: dict | None = None) -> Preview:
    chart_type = str(payload.get('chart_type') or payload.get('type') or '').strip() or '—'
    dataset = str(payload.get('dataset_id') or '').strip() or '—'
    columns = [str(payload.get(key) or '').strip() for key in ('x', 'y', 'value', 'category')]
    columns = [column for column in columns if column]
    return Preview(
        kind='chart_spec',
        title=t('ai.preview.title'),
        summary=t('ai.preview.chart', type=chart_type, dataset=dataset),
        items=[
            PreviewItem(
                id='chart',
                label=t('ai.preview.chartItem'),
                detail=' · '.join(columns) or t('ai.preview.noColumns'),
                action='add',
            )
        ],
    )


register('chart_spec', _preview)
