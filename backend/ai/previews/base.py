"""Artifact previews: kind → a bounded, structured description of what applying would change.

A validator answers "is this draft legal?"; a preview answers "what exactly will happen if I apply
it?". Both are server facts keyed by artifact kind. This registry mirrors ``ai.validators`` on
purpose: adding a previewable format is one module and one ``register`` call, never a new branch in
the API route or the turn loop.

A preview never applies anything and never grants permission — the existing apply endpoints stay
authoritative. It only makes the proposal legible before the user commits to it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

Previewer = Callable[[dict, dict | None], 'Preview']


@dataclass(frozen=True)
class PreviewItem:
    """One legible line of a preview.

    ``id`` is the key the client sends back when it applies only a selection (a workflow node id).
    A non-selectable item is still shown — it is part of the change, just not something the user may
    opt out of independently. ``checked`` is the default for a selectable item, never the user's
    final answer.
    """

    id: str
    label: str
    detail: str = ''
    action: str = 'info'
    selectable: bool = False
    checked: bool = True

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'label': self.label,
            'detail': self.detail,
            'action': self.action,
            'selectable': self.selectable,
            'checked': self.checked,
        }


@dataclass(frozen=True)
class Preview:
    """The whole bounded report for one artifact."""

    kind: str
    title: str
    summary: str
    items: list[PreviewItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def selectable(self) -> bool:
        return any(item.selectable for item in self.items)

    def to_dict(self) -> dict:
        return {
            'kind': self.kind,
            'title': self.title,
            'summary': self.summary,
            'items': [item.to_dict() for item in self.items],
            'warnings': list(self.warnings),
            'selectable': self.selectable,
        }


PREVIEWS: dict[str, Previewer] = {}


def register(kind: str, previewer: Previewer) -> None:
    """Bind one artifact kind to its previewer. A duplicate is refused, never silently replaced."""
    key = str(kind or '').strip()
    if not key:
        raise ValueError('an artifact preview needs a kind')
    if key in PREVIEWS and PREVIEWS[key] is not previewer:
        raise ValueError(f'artifact kind {key} already has a previewer')
    PREVIEWS[key] = previewer


def preview(kind: str, payload: dict, current: dict | None = None) -> Preview | None:
    """Build a preview for *kind*, or ``None`` when that kind has no published shape to show."""
    previewer = PREVIEWS.get(str(kind or ''))
    return previewer(payload, current) if previewer else None


def registered_kinds() -> frozenset[str]:
    return frozenset(PREVIEWS)
