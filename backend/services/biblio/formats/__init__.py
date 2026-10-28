"""Registry of bibliographic export formats.

CNKI RefWorks and CSSCI stay in :mod:`services.biblio.importer` (the original
Chinese path); this package owns the international formats. Adding a format is
one module exporting a :class:`FormatSpec`, plus one tuple entry below.
"""

from services.biblio.formats import (
    bibtex,
    dimensions,
    endnote,
    lens,
    noteexpress,
    pubmed,
    ris,
    scopus,
    unsupported,
    wos,
)
from services.biblio.formats.base import CAPABILITIES, FormatSpec

FORMAT_SPECS: tuple[FormatSpec, ...] = (
    pubmed.SPEC,
    wos.SPEC,
    ris.SPEC,
    bibtex.SPEC,
    endnote.SPEC,
    noteexpress.SPEC,
    scopus.SPEC,
    dimensions.SPEC,
    lens.SPEC,
)

FORMAT_BY_ID = {spec.id: spec for spec in FORMAT_SPECS}


def format_ids() -> tuple[str, ...]:
    return tuple(spec.id for spec in FORMAT_SPECS)


def detect_format(text: str) -> str | None:
    for spec in FORMAT_SPECS:
        try:
            if spec.detect(str(text or '')):
                return spec.id
        except Exception:
            continue
    return None


def parse_format(text: str, fmt: str) -> tuple[list[dict], int]:
    spec = FORMAT_BY_ID.get(fmt)
    if spec is None:
        raise ValueError(f'unknown bibliographic format: {fmt}')
    return spec.parse(str(text or ''))


def detect_frame(frame) -> str | None:
    for spec in FORMAT_SPECS:
        if spec.detect_frame is None or spec.parse_frame is None:
            continue
        try:
            if spec.detect_frame(frame):
                return spec.id
        except Exception:
            continue
    return None


def parse_frame(frame, fmt: str) -> tuple[list[dict], int]:
    spec = FORMAT_BY_ID.get(fmt)
    if spec is None or spec.parse_frame is None:
        raise ValueError(f'format {fmt} has no tabular reader')
    return spec.parse_frame(frame)


def detect_refusal(text: str) -> str:
    """A sentence naming why this file is a bibliographic export we cannot read, or ``''``.

    Called when detection found nothing, before the upload route stores the file as an
    ordinary table: a vendor can sell two different collections to one file type, and
    silently accepting the unreadable one is how a well-formed, meaningless graph appears.
    See :mod:`services.biblio.formats.unsupported`.
    """
    for (checker,) in unsupported.REFUSALS:
        try:
            note = str(checker(str(text or '')) or '')
        except Exception:
            continue
        if note:
            return note
    return ''


def capabilities(fmt: str) -> dict[str, bool]:
    spec = FORMAT_BY_ID.get(fmt)
    known = spec.capabilities if spec else frozenset()
    return {name: name in known for name in CAPABILITIES}


def accepted_extensions() -> tuple[str, ...]:
    found: list[str] = []
    for spec in FORMAT_SPECS:
        for extension in spec.extensions:
            if extension not in found:
                found.append(extension)
    return tuple(found)


__all__ = [
    'CAPABILITIES',
    'FORMAT_BY_ID',
    'FORMAT_SPECS',
    'FormatSpec',
    'accepted_extensions',
    'capabilities',
    'detect_format',
    'detect_frame',
    'detect_refusal',
    'format_ids',
    'parse_format',
    'parse_frame',
]
