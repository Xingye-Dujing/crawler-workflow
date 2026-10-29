"""The ECharts option builder: validation, the shared frame, and the per-type registry.

The option dict is plain JSON — no ``renderItem`` callbacks — so a preview, a saved chart and a
fullscreen render all draw the same figure. Chart families share the palette and the base frame
defined here; one chart type is one builder function in a family module (``series``,
``distributions``, ``relations``, ``topics``), registered by name in ``BUILDERS``.

Before this registry ``_build_option`` was a 700-line ``if chart_type == …`` chain: adding a type
meant editing that one function, and a type that existed in ``CHART_TYPES`` but was never reached
by the chain answered only at the end with the generic bar/line axes. The contract test
``test_chart_registry`` now refuses a type with no builder, a builder for a type that does not
exist, and a duplicate registration.
"""

from dataclasses import dataclass, field

import pandas as pd

from ..contracts import ChartConfigError
from ..registry import BIBLIO_CHART_TYPES, CHART_TYPES
from ..style import ANNOTATED_TYPES, CATEGORY_COLORS

#: One builder per chart type: the type key → the function that completes the base option.
BUILDERS: dict = {}


def builder(*chart_types: str):
    """Register one function as the builder of *chart_types* (refusing a second claim)."""

    def register(fn):
        for chart_type in chart_types:
            if chart_type in BUILDERS:
                raise ValueError(
                    f'{chart_type} already has a builder ({BUILDERS[chart_type].__qualname__}); '
                    'a chart type is one plugin entry, not two opinions about the same figure'
                )
            BUILDERS[chart_type] = fn
        return fn

    return register


@dataclass(frozen=True)
class ChartRequest:
    """What the user asked for, in one object every builder receives.

    Fields keep the names of the old ``_build_option`` parameters (``x``/``y``/``y2``/``agg``…)
    because those names are the node's parameter contract, echoed into the durable run record.
    ``kwargs`` carries the type-specific switches (``tokenize``, ``stack_fields``,
    ``center_node``, ``model_field`` …); a builder that reads one says so in its docstring.
    """

    df: pd.DataFrame
    x: str = None
    y: str = None
    value_field: str = None
    series: str = None
    agg: str = 'sum'
    y2: str = None
    agg2: str = None
    label_field: str = None
    annotations: str = ''
    title: str = ''
    kwargs: dict = field(default_factory=dict)


def base_option(chart_type: str, title: str) -> dict:
    """The frame every console chart starts from (palette, title, tooltip, animation).

    Key insertion order is part of the shipped JSON, so the families append to it rather than
    rebuilding it. The tooltip trigger and formatter are the two pieces that depend on the type.
    """
    base = {
        'backgroundColor': 'transparent',
        'color': CATEGORY_COLORS[:],
        'title': {
            'text': title,
            'textStyle': {'color': '#e8e8e8', 'fontSize': 14, 'fontWeight': 500, 'fontFamily': 'sans-serif'},
            'left': 'center',
            'top': 6,
        },
        'tooltip': {
            'trigger': 'item' if chart_type in ('pie', 'wordcloud', 'map', 'sankey', 'network') else 'axis',
            'backgroundColor': 'rgba(30,30,40,0.9)',
            'borderColor': '#444',
            'borderWidth': 1,
            'textStyle': {'color': '#eee', 'fontSize': 12, 'fontFamily': 'sans-serif'},
            'formatter': '{b}: {c}' if chart_type not in ('pie', 'sankey', 'network') else None,
        },
        'animationDuration': 800,
        'animationEasing': 'cubicOut',
    }
    return base


class OptionMixin:
    @classmethod
    def _build_option(
        cls,
        df: pd.DataFrame,
        chart_type: str,
        x: str = None,
        y: str = None,
        value_field: str = None,
        _series: str = None,
        agg: str = 'sum',
        y2: str = None,
        agg2: str = None,
        label_field: str = None,
        annotations: str = '',
        title: str = '',
        **kwargs,
    ) -> dict:
        if chart_type not in CHART_TYPES:
            raise ChartConfigError(f'Unsupported chart type: {chart_type}')
        if annotations and chart_type not in ANNOTATED_TYPES:
            # Checked before anything is built, so the message is about the box, not about a
            # half-drawn figure.
            raise ChartConfigError(
                f'the {chart_type} figure cannot carry event markers: only {", ".join(ANNOTATED_TYPES)} draw a '
                'vertical line at one category. Clear the box rather than trusting a figure '
                'that quietly dropped it.'
            )

        base = base_option(chart_type, title)
        request = ChartRequest(
            df=df,
            x=x,
            y=y,
            value_field=value_field,
            series=_series,
            agg=agg,
            y2=y2,
            agg2=agg2,
            label_field=label_field,
            annotations=annotations,
            title=title,
            kwargs=kwargs,
        )

        # ── Bibliometric views (fixed columns from the biblio node) ──
        # They are a family of their own: `services.biblio.charts` builds them from the frame the
        # biblio node writes, and each refuses a missing column by name.
        if chart_type in BIBLIO_CHART_TYPES:
            from services.biblio import charts

            try:
                return charts.build(df, chart_type, base)
            except charts.BiblioChartError as exc:
                raise ChartConfigError(str(exc)) from exc

        build = BUILDERS.get(chart_type)
        if build is None:
            # Unreachable while the registry contract holds; stated rather than KeyError'd so a
            # half-landed plugin reads as a refusal, not as a crash inside a node.
            raise ChartConfigError(f'Unsupported chart type: {chart_type}')
        return build(cls, base, request)
