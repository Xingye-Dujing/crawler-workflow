"""What each bibliographic source really exports, and how to get it.

The panel this feeds is the only place the app tells a user "go to this site, click this
button, upload the file that comes out". That makes it a claim about the outside world, so
every line here is bounded by a file we actually parsed: the tag names, column headers,
file names and missing fields come from the real exports in ``samples/`` (measured by
``scratchpad/export_measure.py``-style runs, recorded in ``docs/analysis.md``), not from
vendor marketing pages or from what a format specification says *could* appear.

Consequences worth stating:

* No XML reader for PubMed exists here, because nobody has a PubMed XML export to test it.
* Lens is not an importable format at all: the one Lens file we were given is its patent
  collection, and it is refused by name (:mod:`services.biblio_formats.unsupported`).
* ``extensions`` and ``capabilities`` are read from the format registry, never restated, so
  the panel cannot disagree with the parser about what a file carries.
"""

from __future__ import annotations

import re

from i18n import t
from services import biblio_formats
from services.biblio_import import CNKI, CSSCI

#: Official starting point for each source. Institutional access (WoS, Scopus, Dimensions)
#: usually arrives through a university proxy, so this is where to search, not a promise
#: that the page is open to everyone.
SITES = {
    CNKI: 'https://kns.cnki.net/',
    CSSCI: 'https://cssci.nju.edu.cn/',
    'WoS': 'https://www.webofscience.com/',
    'Scopus': 'https://www.scopus.com/',
    'Dimensions': 'https://www.dimensions.ai/',
    'PubMed': 'https://pubmed.ncbi.nlm.nih.gov/',
    'RIS': 'https://www.zotero.org/',
    'BibTeX': 'https://www.zotero.org/',
    'EndNote': 'https://endnote.com/',
    'NoteExpress': 'https://kns.cnki.net/',
}

#: Two groups, because "a database's own export" and "a citation-manager format" are found
#: by different clicks.
GROUPS = {
    CNKI: 'library',
    CSSCI: 'library',
    'WoS': 'library',
    'Scopus': 'library',
    'Dimensions': 'library',
    'PubMed': 'library',
    'RIS': 'exchange',
    'BibTeX': 'exchange',
    'EndNote': 'exchange',
    'NoteExpress': 'exchange',
}

#: CNKI and CSSCI live outside the registry (``services.biblio_import``), so their labels and
#: extensions are declared here; everything else is taken from the registry itself.
_EXTRA_LABELS = {CNKI: '中国知网 · RefWorks', CSSCI: 'CSSCI'}
_EXTRA_EXTENSIONS = {CNKI: ('.txt',), CSSCI: ('.txt',)}

#: What the real files proved each source is missing. Kept beside the code that refuses those
#: analyses so the panel and the node guard cannot drift apart.
_SPACED_TAG = re.compile(r'[ \t　]+')


def _split_lines(value: str) -> list[str]:
    return [line for line in str(value or '').split('\n') if line.strip()]


def source_for(fmt: str) -> dict[str, object]:
    """One entry of the export guide, translated for the requesting thread's language.

    Mirrors :func:`services.cookie_flow.flow_for`: the server ships sentences, the browser
    only draws them, so a language switch is one refetch and never a second copy of the text.
    """
    spec = biblio_formats.FORMAT_BY_ID.get(fmt)
    label = spec.label if spec else _EXTRA_LABELS.get(fmt, fmt)
    extensions = spec.extensions if spec else _EXTRA_EXTENSIONS.get(fmt, ())
    declared = spec.capabilities if spec else frozenset()
    return {
        'id': fmt,
        'label': label,
        'group': GROUPS.get(fmt, 'exchange'),
        'site': SITES.get(fmt, ''),
        'extensions': list(extensions),
        'capabilities': {name: name in declared for name in biblio_formats.CAPABILITIES},
        'purpose': t(f'source.{fmt}.purpose'),
        'steps': _split_lines(t(f'source.{fmt}.steps')),
        'missing': _split_lines(t(f'source.{fmt}.missing')),
    }


def all_sources() -> list[dict[str, object]]:
    """Every source the importer can read, in the order detection itself tries them."""
    return [source_for(fmt) for fmt in ([CSSCI, CNKI] + list(biblio_formats.format_ids()))]


def folded_tag(tag: str) -> str:
    """Strip the alignment padding CSSCI writes inside its bracket tags (``关 键 词``)."""
    return _SPACED_TAG.sub('', str(tag or ''))


__all__ = ['GROUPS', 'SITES', 'all_sources', 'folded_tag', 'source_for']
