"""The DataAsset model: content identity, ownership, origin and lineage, in one declaration.

Today a node's output is a list of dicts in a run store; the chart, the report and the AI each reach
it through a different path, and nothing names the bytes. An asset fixes that with a small, explicit
record: who owns it, which node/run produced it, the hash and size of the content, where it lives,
and which assets it was derived from. The store and the materialisation hooks arrive in P2; this
module is the contract they share.

It lives in ``core`` because every layer reads it (run store, nodes, API, AI) and it imports only the
standard library, so no domain package is dragged into a reader that only wants the shape.
``services/components/catalog.py`` also has an ``Asset``, but that is a downloadable component
payload with URLs and per-OS parts, not this.

``schema`` is versioned because the run store will persist these records. A reader that meets a
newer schema refuses it by name rather than interpreting fields it does not know.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field, fields
from datetime import datetime

SCHEMA_VERSION = 1

#: What an asset can be. ``table`` is row data; ``text`` is a text artifact; ``chart``/``pdf``/
#: ``report`` are rendered artifacts; ``file`` is an opaque upload; ``dataset`` is an imported table
#: with its own store identity.
ASSET_KINDS = ('table', 'text', 'image', 'chart', 'pdf', 'report', 'file', 'dataset')

_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]*$')
_SHA256 = re.compile(r'^[0-9a-f]{64}$')

_REQUIRED = ('id', 'kind', 'owner', 'origin', 'sha256', 'size', 'uri')


class AssetError(ValueError):
    """A malformed or unsupported asset record, named with the field that cannot be trusted."""


def _json_safe(value) -> bool:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return False
    return True


@dataclass(frozen=True)
class DataAsset:
    """One output as downstream readers address it. ``parents`` are asset ids, never paths."""

    id: str
    kind: str
    owner: str
    #: Where it came from: ``run:<run_id>:<node_id>``, ``upload:<dataset_id>``, ``ai:<turn_id>``.
    origin: str
    sha256: str
    size: int
    #: A locator the producing store understands (a run/node key, a file URI, an object key).
    uri: str
    parents: tuple[str, ...] = ()
    meta: dict = field(default_factory=dict)
    created_at: str = ''
    schema: int = SCHEMA_VERSION

    def problems(self) -> list[str]:
        found: list[str] = []
        if self.schema != SCHEMA_VERSION:
            found.append(f'schema: {self.schema!r} is not supported (expected {SCHEMA_VERSION})')
        if not _ID.match(self.id or ''):
            found.append(f'id: {self.id!r} is not an asset id')
        if self.kind not in ASSET_KINDS:
            found.append(f'kind: {self.kind!r} is not one of {", ".join(ASSET_KINDS)}')
        for name in ('owner', 'origin', 'uri'):
            if not str(getattr(self, name) or '').strip():
                found.append(f'{name}: empty')
        if not _SHA256.match(self.sha256 or ''):
            found.append('sha256: not 64 lowercase hex characters')
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            found.append(f'size: {self.size!r} is not a non-negative integer')
        if not isinstance(self.parents, tuple) or any(not _ID.match(parent or '') for parent in self.parents):
            found.append('parents: must be a tuple of asset ids')
        elif self.id in self.parents:
            found.append('parents: an asset cannot be its own parent')
        elif len(set(self.parents)) != len(self.parents):
            found.append('parents: duplicate id')
        if not isinstance(self.meta, dict) or not _json_safe(self.meta):
            found.append('meta: must be a JSON-safe object')
        if self.created_at:
            try:
                datetime.fromisoformat(self.created_at)
            except ValueError:
                found.append(f'created_at: {self.created_at!r} is not ISO 8601')
        return found

    def to_dict(self) -> dict:
        """The persisted shape. ``parents`` is a JSON array; ``meta`` is copied, not shared."""
        return {
            'schema': self.schema,
            'id': self.id,
            'kind': self.kind,
            'owner': self.owner,
            'origin': self.origin,
            'sha256': self.sha256,
            'size': self.size,
            'uri': self.uri,
            'parents': list(self.parents),
            'meta': copy.deepcopy(self.meta),
            'created_at': self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DataAsset:
        """Read a persisted record, refusing unknown keys and a schema this build cannot honour."""
        if not isinstance(data, dict):
            raise AssetError(f'asset record is {type(data).__name__}, not an object')
        known = {item.name for item in fields(cls)}
        unknown = sorted(set(data) - known)
        missing = [name for name in _REQUIRED if name not in data]
        if unknown:
            raise AssetError('asset record has unknown field(s): ' + ', '.join(unknown))
        if missing:
            raise AssetError('asset record is missing field(s): ' + ', '.join(missing))
        asset = cls(
            id=data['id'],
            kind=data['kind'],
            owner=data['owner'],
            origin=data['origin'],
            sha256=data['sha256'],
            size=data['size'],
            uri=data['uri'],
            parents=tuple(data.get('parents') or ()),
            meta=copy.deepcopy(data.get('meta') or {}),
            created_at=str(data.get('created_at') or ''),
            schema=data.get('schema', SCHEMA_VERSION),
        )
        problems = asset.problems()
        if problems:
            raise AssetError('; '.join(problems))
        return asset
