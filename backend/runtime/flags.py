"""Migration switches that expire, with an owner and a reason.

A strangler migration has two paths for a while. The switch between them is not a feature flag: it
is a temporary scaffolding that must be removed, so each one declares who owns it and the date by
which the old path (or the switch itself) is gone. ``problems()`` turns an expired switch into a
gate failure instead of a comment nobody reads.

No domain has declared a switch yet — the kernel pilots changed behavior without a parallel path.
The mechanism lands first so the next migration (P2 node catalogue, P4 AI framework) adds one in the
same change that introduces its second path, never before it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date

_NAME = re.compile(r'^[a-z][a-z0-9_.-]*$')
_TRUE = {'1', 'true', 'yes', 'on'}
_FALSE = {'0', 'false', 'no', 'off'}


class FlagError(ValueError):
    """An unknown switch, a bad environment value, or a declaration that cannot expire honestly."""


@dataclass(frozen=True)
class Flag:
    """One temporary switch. ``remove_by`` is ISO ``YYYY-MM-DD`` and is inclusive."""

    name: str
    owner: str
    remove_by: str
    description: str
    default: bool = False

    def remove_date(self) -> date:
        try:
            return date.fromisoformat(self.remove_by)
        except ValueError as exc:
            raise FlagError(f'{self.name}: remove_by {self.remove_by!r} is not YYYY-MM-DD') from exc

    def env_key(self) -> str:
        return 'CIXI_FLAG_' + re.sub(r'[^A-Za-z0-9]+', '_', self.name).upper()


#: Declared switches. A flag with no consumer would be config that pretends to control something.
FLAGS: dict[str, Flag] = {
    # The old /api/ai surface and the framework-backed /api/ai/ws run side by side until parity;
    # deleting the old engine and this switch is one change (P4 接入).
    'ai_workspace': Flag(
        name='ai_workspace',
        owner='P4 AI 接入',
        remove_by='2027-03-01',
        description='Serve /api/ai/ws from the agent-workspace framework alongside the old /api/ai.',
        default=True,
    ),
}


def flag_for(name: str) -> Flag:
    flag = FLAGS.get(str(name or ''))
    if flag is None:
        raise FlagError(
            f'unknown migration flag {name!r}; declared: {", ".join(sorted(FLAGS)) or "(none)"}',
        )
    return flag


def active(name: str) -> bool:
    """The switch's value: the environment when it names a boolean, else its declared default.

    A blank variable is "not configured" (the default), not false: a CI job that only sets the
    switches it cares about must not silently turn every other migration off. A typo like
    ``CIXI_FLAG_X=treu`` is refused by name rather than coerced.
    """
    flag = flag_for(name)
    raw = os.environ.get(flag.env_key(), '').strip().lower()
    if not raw:
        return flag.default
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise FlagError(f'{flag.name}: {flag.env_key()}={raw!r} is not a boolean (1/0, true/false, on/off)')


def problems(declared: tuple[Flag, ...] | None = None, today: date | None = None) -> list[str]:
    """Every switch that is malformed or past its removal date, as ``name: sentence``.

    The gate calls this with the real registry and today's date; the tests call it with a synthetic
    switch to prove the gate can fail. The removal date itself is allowed — the flag is expired the
    day after it.
    """
    flags = tuple(FLAGS.values()) if declared is None else tuple(declared)
    now = today or date.today()
    found: list[str] = []
    seen: set[str] = set()
    for flag in flags:
        if not _NAME.match(flag.name or ''):
            found.append(f'{flag.name!r}: name is not a lowercase identifier')
        if flag.name in seen:
            found.append(f'{flag.name}: declared twice')
        seen.add(flag.name)
        if not str(flag.owner or '').strip():
            found.append(f'{flag.name}: no owner')
        if not str(flag.description or '').strip():
            found.append(f'{flag.name}: no description')
        if not isinstance(flag.default, bool):
            found.append(f'{flag.name}: default is not a boolean')
        try:
            remove_by = flag.remove_date()
        except FlagError as exc:
            found.append(str(exc))
            continue
        if remove_by < now:
            found.append(f'{flag.name}: expired on {flag.remove_by} (owner {flag.owner or "?"})')
    return found


def expired(today: date | None = None, declared: tuple[Flag, ...] | None = None) -> list[Flag]:
    flags = tuple(FLAGS.values()) if declared is None else tuple(declared)
    now = today or date.today()
    return [flag for flag in flags if flag.remove_date() < now]


def require_live(today: date | None = None) -> None:
    """Raise the first problem; the startup/gate path can call this instead of formatting a list."""
    found = problems(today=today)
    if found:
        raise FlagError('; '.join(found))
