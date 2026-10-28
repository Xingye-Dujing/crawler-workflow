"""Bibliometric network construction, metrics, bursts and citation graphs.

The input is the normalized record table produced by
:mod:`services.biblio.importer`; the output is one row per entity with a JSON
adjacency column. Everything a chart needs is in that one table, so a resume,
a CSV export and a chart preview all see the same numbers.

The stages live in sibling modules (records → network → measures → build); this
module is the public face: ``build``, its twin ``build_dual_map``, the snapshot
split, the Pajek export and the burst primitive.
"""

from services.biblio.schema import LIMITS

from .build import build, build_dual_map
from .export import export_result, snapshot_capture
from .measures import kleinberg_bursts
from .records import BiblioError

__all__ = [
    'BiblioError',
    'LIMITS',
    'build',
    'build_dual_map',
    'export_result',
    'kleinberg_bursts',
    'snapshot_capture',
]
