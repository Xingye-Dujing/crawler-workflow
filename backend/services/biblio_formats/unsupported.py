"""Vendor collections we recognise but deliberately do not read, and what we say instead.

These are not formats, so they are not in :data:`services.biblio_formats.FORMAT_SPECS`:
accepting a file here would produce a table of the right shape and the wrong meaning. The
evidence is a real Lens export whose columns are ``Jurisdiction``, ``Kind``,
``Application Number``, ``Inventors``, ``Applicants``, ``Owners`` and ``CPC Classifications``
— the patent collection, sharing ``Title`` and ``Lens ID`` with the scholarly one that
:mod:`services.biblio_formats.lens` reads.
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

    The scholarly collection has its own reader now, so this is a check on the columns that
    only the patent download writes — and it stays a refusal rather than a mapping because a
    patent record's ``Inventors``/``Owners`` are not the authors of a publication.
    """
    names = {str(name or '').strip().lower() for name in header_of(str(value or ''))}
    if not {'lens id', 'title'} <= names:
        return ''
    if names & LENS_PATENT_MARKERS:
        return t('api.biblioLensPatent')
    return ''


#: Each entry answers a recognisable file with the sentence that refuses it.
REFUSALS = ((lens_patents,),)
