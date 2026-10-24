"""Chart-shape contracts shared by the engine, diagnostics and Visualize node.

The four bibliometric charts read fixed column names emitted by the ``biblio``
node. Keeping the names here means a rename on one side is a single named
refusal on the other, never an empty figure.
"""

BIBLIO_CHART_TYPES = (
    'knowledge_graph',
    'cluster_timeline',
    'burst',
    'timezone',
    'circular',
    'landscape',
    'biblio_heatmap',
    'graph3d',
    'variation',
    'dual_map',
)

#: Charts whose x axis is not a user-selected column. Validation must not demand
#: ``x_field`` for these, and the Visualize panel hides the box.
NO_X_TYPES = frozenset(('model_agreement',) + BIBLIO_CHART_TYPES)

#: Rows a structural-variation figure draws. A y-axis row has to be tall enough to carry its
#: own Chinese node name at the preview's height, and a forced label per row is exactly how the
#: names end up printed on top of each other — so the cap is a legibility limit, not a data
#: limit: the CSV and the three-line table still carry every mover.
VARIATION_ROW_LIMIT = 20

#: The fixed columns each bibliometric chart REQUIRES. Optional decorating
#: columns (cluster colour, burst rings) are read when present; a chart that
#: needs clustering or burst detection refuses when its switch was off, and
#: diagnostics flags only the hard reads below.
BIBLIO_CHART_READS = {
    'knowledge_graph': ('节点', 'x', 'y', '连接', '频次'),
    'cluster_timeline': ('节点', '聚类', '聚类标签', '首年', '末年', '频次'),
    'burst': ('节点', '突现起始', '突现结束', '突现强度'),
    'timezone': ('节点', '年份序列', '频次'),
    'circular': ('节点', '连接', '频次'),
    'landscape': ('节点', '聚类', '聚类标签', '频次'),
    'biblio_heatmap': ('节点', '聚类', '聚类标签', '年份序列', '频次'),
    'graph3d': ('节点', 'x', 'y', '连接', '频次'),
    'variation': ('节点', '起始年', '结束年', '结构变化'),
    'dual_map': ('map', 'source', 'target', 'weight'),
}
