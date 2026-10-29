"""One builder per console chart type: the registry, its family modules, and the mixin.

``visualizer`` composes ``OptionMixin`` into ``VisualizationService``; this package is split by
figure family so a new chart is one function in one file plus a ``@builder('name')`` line:

``base``           validation, the shared frame, ``ChartRequest`` and the ``BUILDERS`` registry;
``series``         bar, line, dual_line, stack_pct;
``distributions``  pie, histogram, box, wordcloud, map;
``relations``      scatter, heatmap, model_agreement, sankey, network;
``topics``         topic_map, topic_terms.

The family modules are imported for their registration side effect; ``BUILDER_MODULES`` keeps
them referenced (a linter cannot read a side effect, and an import that looks unused is how a
registration gets deleted).
"""

from . import distributions, relations, series, topics
from .base import BUILDERS, ChartRequest, OptionMixin, base_option, builder

#: Importing these modules is what registers their chart types in ``BUILDERS``.
BUILDER_MODULES = (series, distributions, relations, topics)

__all__ = ['BUILDERS', 'BUILDER_MODULES', 'ChartRequest', 'OptionMixin', 'base_option', 'builder']
