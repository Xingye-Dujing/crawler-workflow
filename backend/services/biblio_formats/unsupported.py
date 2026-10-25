"""Vendor collections we recognise but deliberately do not read, and what we say instead.

These are not formats, so they are not in :data:`services.biblio_formats.FORMAT_SPECS`:
accepting a file here would produce a table of the right shape and the wrong meaning. The
evidence is a real Lens export whose columns are ``Jurisdiction``, ``Kind``,
``Application Number``, ``Inventors``, ``Applicants``, ``Owners`` and ``CPC Classifications``
— the patent collection, sharing ``Title`` and ``Lens ID`` with the scholarly one.
"""

from i18n import t
from services.biblio_formats.common import header_of

#: Column names that only appear in a patent download.
LENS_PATENT_MARKERS = frozenset(
    {
        'jurisdiction',
        'kind',
        'application number',
        'inventors',
        'applicants',
        'owners',
        'cpc classifications',
        'legal status',
    }
)


def lens_patents(value: str) -> str:
    """Name a Lens patent export, or return ``''`` when this is not one.

    A refusal has to be certain: the scholarly collection is a file shape nobody on this
    project has exported, so the only claim made here is about the patent columns.
    """
    names = {str(name or '').strip().lower() for name in header_of(str(value or ''))}
    if not {'lens id', 'title'} <= names:
        return ''
    if names & LENS_PATENT_MARKERS:
        return t('api.biblioLensPatent')
    return ''


#: Each entry answers a recognisable file with the sentence that refuses it.
REFUSALS = ((lens_patents,),)
