"""Format registry contracts.

A format is a small record of what it can carry, how to recognize it, and how
to turn its text (or a spreadsheet frame) into normalized rows. Detection is
conservative: a format wins only on its own grammar, never on a word that could
appear in ordinary prose.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

Parser = Callable[[str], tuple[list[dict], int]]
FrameDetector = Callable[[pd.DataFrame], bool]
FrameParser = Callable[[pd.DataFrame], tuple[list[dict], int]]

#: Capability names used by the upload response and the biblio node's guards.
CAPABILITIES = (
    'refs',
    'tc',
    'usage',
    'categories',
    'grants',
    'abstract',
    'keywords',
    'country',
    'doi',
    'doctype',
    'language',
    'funding',
)


@dataclass(frozen=True)
class FormatSpec:
    id: str
    label: str
    extensions: tuple[str, ...]
    capabilities: frozenset[str]
    detect: Callable[[str], bool]
    parse: Parser
    detect_frame: FrameDetector | None = None
    parse_frame: FrameParser | None = None
    frame_only: bool = field(default=False)
