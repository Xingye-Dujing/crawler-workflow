"""The capability doctor: one row per declared check, printed with a checkbox.

The completeness gate and the doctor ask the same question from two doors. The gate is the one that
must be green in CI; the doctor is what a developer runs after adding a capability, and it names the
file to fix instead of a test id. Both read ``Manifest.problems()`` and resolve the declared
handler/hooks, so they cannot disagree about what "complete" means.

Legacy node types are reported as ``pending`` (not a failure): P1 migrated one pilot; P2 moves the
rest. A failure always names the capability and the dimension, never a generic "invalid manifest".
"""

from __future__ import annotations

from pathlib import Path

from capabilities_kernel import generate, registry
from capabilities_kernel.manifest import KINDS

ROOT = Path(__file__).resolve().parents[2]


def _row(name: str, ok: bool, detail: str = '') -> dict:
    return {'name': name, 'ok': ok, 'detail': detail}


def capability_rows(manifest, root: Path = ROOT) -> list[dict]:
    """Every live check for one manifest. A missing file is a failed row, not a crash."""
    rows = []
    problems = manifest.problems()
    rows.append(_row('structure', not problems, '; '.join(problems)))

    if manifest.execution.handler:
        try:
            handler = registry.resolve(manifest.execution.handler)
            ok = callable(handler)
            detail = '' if ok else f'{manifest.execution.handler} is not callable'
        except Exception as exc:  # the refusal is the row; a doctor must survive a broken import
            ok, detail = False, str(exc)
    else:
        ok, detail = False, 'no execution.handler'
    rows.append(_row('executor', ok, detail))

    bad_hooks = []
    for reference in (manifest.ports.emit_columns, manifest.ports.read_columns):
        if not reference:
            continue
        try:
            if not callable(registry.resolve(reference)):
                bad_hooks.append(f'{reference} is not callable')
        except Exception as exc:
            bad_hooks.append(f'{reference}: {exc}')
    rows.append(_row('port_hooks', not bad_hooks, '; '.join(bad_hooks)))

    bad_validators = []
    for reference in manifest.validators:
        try:
            if not callable(registry.resolve(reference)):
                bad_validators.append(f'{reference} is not callable')
        except Exception as exc:
            bad_validators.append(f'{reference}: {exc}')
    rows.append(_row('validators', not bad_validators, '; '.join(bad_validators)))

    preflight_ok = True
    preflight_detail = 'not declared'
    if manifest.preflight:
        try:
            preflight_ok = callable(registry.resolve(manifest.preflight))
            preflight_detail = '' if preflight_ok else f'{manifest.preflight} is not callable'
        except Exception as exc:
            preflight_ok = False
            preflight_detail = f'{manifest.preflight}: {exc}'
    rows.append(_row('preflight', preflight_ok, preflight_detail))

    page = manifest.docs.page
    page_ok = bool(page) and (root / page).is_file()
    rows.append(_row('docs', page_ok, page or 'no docs.page'))

    missing_contracts = [path for path in manifest.tests.contracts if not (root / path).is_file()]
    rows.append(
        _row('contracts', bool(manifest.tests.contracts) and not missing_contracts, ', '.join(missing_contracts))
    )

    return rows


def check_all(only: list[str] | None = None) -> list[dict]:
    """Every capability's rows plus one artifact-freshness row per file.

    ``only`` filters by ``kind:id``; an unknown filter is itself a failed row so a typo cannot
    produce an empty, green report.
    """
    wanted = set(only or ())
    found = set()
    rows = []
    for kind in KINDS:
        for manifest in registry.manifests(kind):
            name = f'{manifest.identity.kind}:{manifest.identity.id}'
            if wanted and name not in wanted:
                continue
            found.add(name)
            for row in capability_rows(manifest):
                rows.append({'capability': name, **row})
    for missing in sorted(wanted - found):
        rows.append({'capability': missing, 'name': 'discovery', 'ok': False, 'detail': 'no such manifest'})

    if not wanted:
        for detail in generate.check():
            rows.append({'capability': 'artifacts', 'name': 'artifacts', 'ok': False, 'detail': detail})
        if not any(row['capability'] == 'artifacts' for row in rows):
            rows.append({'capability': 'artifacts', 'name': 'artifacts', 'ok': True, 'detail': ''})
    return rows


def legacy_node_types() -> list[str]:
    """Node types still declared in ``nodes/catalog.py`` rather than a manifest (P2 moves them)."""
    from nodes.catalog import NODE_TYPES

    migrated = {manifest.identity.id for manifest in registry.manifests('node')}
    return sorted(set(NODE_TYPES) - migrated)


def report(rows: list[dict]) -> str:
    """The console view: ``[x]``/``[ ]`` per row, grouped by capability."""
    lines = []
    current = None
    for row in rows:
        if row['capability'] != current:
            current = row['capability']
            lines.append(f'{current}')
        mark = '[x]' if row['ok'] else '[ ]'
        suffix = f'  {row["detail"]}' if row['detail'] else ''
        lines.append(f'  {mark} {row["name"]}{suffix}')
    return '\n'.join(lines)
