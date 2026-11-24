"""The two durable values a run record is made of, as types instead of comments.

``Cursor`` is **where a crawl got to**, ``LedgerKey`` is **what a crawled item is**. Both rules
used to live only in prose next to a plain ``dict``/``str``, and both were broken once:

- a cursor that recorded *content* (a list of urls) made 继续 replay a page the run had already
  paid for; a cursor written *before* its rows landed laundered a hole into a completed input,
  because ``url_index`` claimed a stretch the store never held;
- a ledger key that fell back to the whole row made every resumed comment a new item (its 楼层 is
  renumbered from 1 on each visit), so 继续 re-stored the set it had already bought.

A type does not replace the order of the writes — only the caller can write the rows first — but
it does keep the two halves of a cursor apart (:meth:`Cursor.proven` refuses a prefix outside the
batch it describes) and gives the ledger one digest function instead of seven call sites agreeing
by hand.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

#: The two fields a batch walk pins for 继续: how many leading inputs it PROVED, out of how many.
PROVEN_INDEX = 'url_index'
PROVEN_TOTAL = 'url_total'


def sha1_parts(*parts) -> str:
    """The separator-joined SHA-1 every durable identity in a run is built from.

    One function, because a fingerprint computed with a different join on the two sides of a
    comparison is a silent "same thing, different name" — the ledger claims it never stored the
    row that is sitting in its own table.
    """
    joined = '\x1e'.join('' if part is None else str(part) for part in parts)
    return hashlib.sha1(joined.encode('utf-8')).hexdigest()


@dataclass(frozen=True, eq=False)
class Cursor(Mapping):
    """Where a crawl got to. Reads like the stored mapping it replaces; cannot be edited.

    ``position`` is the crawl's own vocabulary (``keyword``/``page``/``scanned``…, whatever the
    platform's walk needs). ``proven``/``total`` are the one thing a batch walk must not put in
    ``position``: a count of leading inputs whose rows are already stored, kept as its own pair so
    that "position is what was proved, never what was attempted" is a fact of the value rather
    than a comment above the call.
    """

    position: Mapping[str, object] = field(default_factory=dict)
    proven: int | None = None
    total: int | None = None
    #: ``position`` + the proven pair, filled by :meth:`__post_init__`; not a dataclass field so
    #: equality stays about what the caller said, never about a cached rendering.
    flat: dict = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        flat = copy.deepcopy(dict(self.position))
        if self.proven is not None:
            if self.total is None:
                raise ValueError('a proven prefix needs the batch it is a prefix of')
            if not 0 <= self.proven <= self.total:
                raise ValueError(f'proven={self.proven} is outside the batch (0..{self.total})')
            flat[PROVEN_INDEX] = int(self.proven)
            flat[PROVEN_TOTAL] = int(self.total)
        object.__setattr__(self, 'flat', flat)

    # ─── Constructors ───

    @classmethod
    def of(cls, raw: Mapping | None) -> Cursor:
        """Read a stored cursor back; ``None`` is the empty cursor a fresh crawl gets."""
        if isinstance(raw, Cursor):
            return raw
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise TypeError(f'a cursor is a mapping, not {type(raw).__name__}')
        proven = raw.get(PROVEN_INDEX)
        total = raw.get(PROVEN_TOTAL)
        position = {key: value for key, value in raw.items() if key not in (PROVEN_INDEX, PROVEN_TOTAL)}
        if proven is None or total is None:
            return cls(position)
        return cls(position, proven=int(proven), total=int(total))

    @classmethod
    def at(cls, **position) -> Cursor:
        """A position-only cursor — a crawl whose progress is where the page walk stands."""
        return cls(position)

    @classmethod
    def proven_prefix(cls, proven: int, total: int) -> Cursor:
        """A batch walk's cursor: the leading inputs proved out of the batch it walked.

        The caller still owns the ORDER — rows land first, this is written second, and only while
        the run of finished inputs is unbroken — but an out-of-range prefix is refused here rather
        than stored and discovered by 继续.
        """
        if total is None:
            raise ValueError('a proven prefix needs the batch it is a prefix of')
        return cls({}, proven=int(proven), total=int(total))

    # ─── Values ───

    def merged(self, **changes) -> Cursor:
        """This position with *changes* applied — what ``mark_position`` merges into."""
        return Cursor.of({**self.flat, **changes})

    def as_dict(self) -> dict:
        """The mapping as it is stored and handed to a crawler."""
        return dict(self.flat)

    # ─── Mapping ───

    def __getitem__(self, key):
        return self.flat[key]

    def __iter__(self) -> Iterator:
        return iter(self.flat)

    def __len__(self) -> int:
        return len(self.flat)

    def __repr__(self) -> str:
        return f'Cursor({self.flat!r})'

    def __eq__(self, other) -> bool:
        if isinstance(other, Cursor):
            return self.flat == other.flat
        if isinstance(other, Mapping):
            return self.flat == dict(other)
        return NotImplemented

    __hash__ = None  # a mapping whose values may be lists; the stored JSON is its identity


@dataclass(frozen=True)
class LedgerKey:
    """A crawled row's site identity — what the dedupe ledger claims, never its content.

    ``kind`` names the evidence the identity was read from (``comment``/``site``/``url``/``text``
    …) and ``parts`` are that evidence in order, so the same row on two visits produces the same
    key while a changed like-count, floor number or share token cannot move it.
    """

    kind: str
    parts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, 'parts', tuple('' if part is None else str(part) for part in self.parts))

    def digest(self) -> str:
        """The stored key: kind and parts, separated so no two shapes can collide."""
        return sha1_parts(self.kind, *self.parts)
