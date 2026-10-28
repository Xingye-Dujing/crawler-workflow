"""Chart-shape contracts shared by the engine, diagnostics and Visualize node.

The bibliometric charts read fixed column names emitted by the ``biblio`` node. Those names are
declared once per chart in :mod:`services.charts.registry` and re-exported here, so a rename on
one side is a single named refusal on the other, never an empty figure. The remaining constants
in this module are limits that are not a property of a chart *type* (row caps, polarity order).
"""

from services.charts.registry import BIBLIO_CHART_READS, BIBLIO_CHART_TYPES, NO_X_TYPES

#: Re-exported for the modules (and tests) that have always imported these three names from
#: here; ``services.charts.registry`` is their one declaration.
__all__ = ['BIBLIO_CHART_TYPES', 'BIBLIO_CHART_READS', 'NO_X_TYPES']


#: Rows a structural-variation figure draws. A y-axis row has to be tall enough to carry its
#: own Chinese node name at the preview's height, and a forced label per row is exactly how the
#: names end up printed on top of each other — so the cap is a legibility limit, not a data
#: limit: the CSV and the three-line table still carry every mover.
VARIATION_ROW_LIMIT = 20

#: Rows the two overlay views draw. Like ``VARIATION_ROW_LIMIT`` this is a legibility limit, not
#: a data limit: a y-axis row must be tall enough to carry its own Chinese node name, and the
#: node table, the CSV export and the three-line table still carry every node's distribution.
OVERLAY_ROW_LIMIT = 20

#: Topic columns a topic overlay draws. Twelve Chinese topic heads fit across the preview panel
#: before they need rotation past legibility; the JSON distribution column keeps the rest.
OVERLAY_TOPIC_LIMIT = 12

#: Rows the printed overlay tables carry. A paper table is an excerpt — the run's CSV and the
#: node table's distribution column are the complete record, and the figure note says so.
OVERLAY_TABLE_LIMIT = 40

#: The polarity values the sentiment step writes, in print order (negative → neutral → positive).
#: A column holding any other label set (emotion/tendency/a user's own topic names) is drawn in
#: descending frequency order instead, because those labels have no left-to-right polarity.
POLARITY_LABELS = ('negative', 'neutral', 'positive')

#: One colour per polarity label, shared by the ECharts view and the TikZ figure so the two
#: projections of the same data read the same way.
POLARITY_COLORS = {'negative': '#A85442', 'neutral': '#9AA0A6', 'positive': '#4F7355'}
