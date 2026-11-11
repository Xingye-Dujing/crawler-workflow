"""Runtime-editable app settings, persisted to ``data/settings.json``.

The keys are declared once in :mod:`runtime.settings_schema`; this module is the
store: load, validate, merge, persist, plus the named presets and the export/import
payloads. Every crawler / LLM call reads a value through :func:`get_setting`, so a
save applies on the next execution without a server restart (the couple of
``restart`` keys are flagged in the schema).

The old hand-written ``if key == ...`` chain is gone: a new key is one declaration
in the schema, and the panel, the validator, the export filter and the coverage
gate all read it from there. A path setting still gets its own warning ("the file
does not exist yet") rather than a refusal, because the user may be configuring a
machine where it will exist later.
"""

import json
import math
import os
import re
import sys
import threading
from datetime import datetime

from core.atomic import replace as atomic_replace
from core.config import Config
from core.machine import catbus_source_twin

from i18n import t
from runtime.settings_schema import (
    BY_KEY,
    DEFAULTS,
    MACHINE_KEYS,
    PRESETS,
    SETTINGS,
    schema_payload,
)

_PATH = os.path.join(Config.DATA_DIR, 'settings.json')
_lock = threading.Lock()
_values = None
_preset_state: dict = {}

#: Bumped when the stored/exported payload shape changes in a way an older build
#: cannot read. Import refuses a payload from the future by name.
SCHEMA_VERSION = 1
EXPORT_KIND = 'crawler-workflow.settings'

__all__ = [
    'DEFAULTS',
    'MACHINE_KEYS',
    'PRESETS',
    'SCHEMA_VERSION',
    'SETTINGS',
    'all_settings',
    'apply_preset',
    'export_payload',
    'get_setting',
    'import_payload',
    'preset_state',
    'restore_preset',
    'save_settings',
    'schema_payload',
]


# ─── Load / persist ─────────────────────────────────────────────────────────


def _read_file() -> dict:
    try:
        with open(_PATH, encoding='utf-8') as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return {}
    return stored if isinstance(stored, dict) else {}


def _load() -> dict:
    global _values, _preset_state
    if _values is None:
        stored = _read_file()
        vals = dict(DEFAULTS)
        for key in DEFAULTS:
            if key in stored and stored[key] is not None:
                vals[key] = stored[key]
        # Retirement migration: ``gentle_crawl`` was a bare multiplier. A user who
        # had it on keeps the same pacing as an explicit scale; a preset snapshot is
        # deliberately not invented (there is no "before" state to restore to).
        if 'gentle_crawl' in stored and 'crawl_pace_scale' not in stored:
            vals['crawl_pace_scale'] = 4.0 if bool(stored.get('gentle_crawl')) else 1.0
        preset = stored.get('_preset')
        _preset_state = preset if isinstance(preset, dict) else {}
        _values = vals
    return _values


def all_settings() -> dict:
    with _lock:
        return dict(_load())


def get_setting(key: str):
    with _lock:
        return _load().get(key, DEFAULTS.get(key))


def _write_locked(vals: dict) -> None:
    """Write values + preset state atomically. Caller holds ``_lock``."""
    payload = dict(vals)
    if _preset_state:
        payload['_preset'] = dict(_preset_state)
    tmp = _PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    atomic_replace(tmp, _PATH)


# ─── Validation ─────────────────────────────────────────────────────────────


def _as_bool(raw) -> bool | None:
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ('true', '1', 'yes', 'on'):
        return True
    if text in ('false', '0', 'no', 'off'):
        return False
    return None


def _coerce(spec, raw, warnings: list):
    """Validate one value, returning the value to store.

    Never raises for user input: a bad value falls back to the declared default and
    appends one warning naming the setting. Paths may be stored even when the file is
    absent (a warning says so), because a machine can be configured ahead of install.
    """
    key = spec.key
    if spec.kind == 'bool':
        value = _as_bool(raw)
        if value is None:
            warnings.append(t('set.badFlag', setting=key))
            return spec.default
        return value

    if spec.kind in ('int', 'float'):
        try:
            number = float(raw)
        except (TypeError, ValueError, OverflowError):
            warnings.append(t('set.badNumber', setting=key, value=raw))
            return spec.default
        if not math.isfinite(number):
            warnings.append(t('set.badNumber', setting=key, value=raw))
            return spec.default
        value = int(number) if spec.kind == 'int' else float(number)
        if spec.minimum is not None and value < spec.minimum:
            warnings.append(t('set.outOfRange', setting=key, lo=spec.minimum, hi=spec.maximum, value=value))
            return spec.default
        if spec.maximum is not None and value > spec.maximum:
            warnings.append(t('set.outOfRange', setting=key, lo=spec.minimum, hi=spec.maximum, value=value))
            return spec.default
        return value

    if spec.kind == 'enum':
        value = str(raw or '').strip().lower()
        if value in spec.choices:
            return value
        if spec.key == 'component_source':
            warnings.append(t('set.badSource', value=raw))
        else:
            warnings.append(t('set.badChoice', setting=key, value=raw, choices=', '.join(spec.choices)))
        return spec.default

    if spec.validator == 'window':
        value = str(raw or '').strip()
        if re.fullmatch(r'\d{2,5}x\d{2,5}', value):
            return value
        warnings.append(t('set.badWindow', default=spec.default))
        return spec.default

    if spec.validator == 'url':
        value = str(raw or '').strip().rstrip('/')
        if value and not re.match(r'^https?://', value):
            warnings.append(t('set.badOllamaHost'))
            return spec.default
        return value or spec.default

    if spec.validator == 'driver':
        value = str(raw or '').strip()
        if value:
            if not os.path.isfile(value):
                warnings.append(t('set.driverMissing', path=value))
            return value
        warnings.append(t('set.driverEmpty'))
        return spec.default

    if spec.validator == 'browser':
        value = str(raw or '').strip()
        if value and not os.path.isfile(value):
            warnings.append(t('set.browserMissing', path=value))
        return value

    if spec.validator == 'latex':
        value = str(raw or '').strip()
        if value and not os.path.isfile(value):
            warnings.append(t('set.latexMissing', path=value))
        return value

    if spec.validator in ('harvest',):
        value = str(raw or '').strip().strip('"')
        if value and not os.path.isfile(value):
            warnings.append(t('set.harvestMissing', tool=key, path=value))
        return value

    if spec.validator in ('catbus', 'catbus_node'):
        value = str(raw or '').strip().strip('"')
        if value and not (os.path.isfile(value) or os.path.isdir(value)):
            warnings.append(t('set.catbusMissing', tool=key, path=value))
        if value and spec.validator == 'catbus_node' and os.path.isdir(value):
            warnings.append(t('set.catbusNeedFile', tool=key, path=value))
        twin = catbus_source_twin(value) if spec.validator == 'catbus' else ''
        if twin and os.path.isfile(value) and not os.path.isfile(twin):
            warnings.append(t('set.catbusSource', tool=key, path=value, entry=twin))
        return value

    if spec.validator == 'absdir':
        value = str(raw or '').strip().strip('"')
        if not value:
            return ''
        if not os.path.isabs(value):
            warnings.append(t('set.badProfileDir', value=value))
            return spec.default
        return value

    # A plain string.
    return str(raw if raw is not None else '').strip()


def _apply_side_effects(patch: dict) -> None:
    """Invalidate what a save just changed, once per store write."""
    if {'catbus_cli', 'catbus_node'} & set(patch or {}):
        from services.ingest import catbus

        catbus.reset_probe_cache()
    if 'max_upload_mb' in (patch or {}):
        # Flask reads ``MAX_CONTENT_LENGTH`` per request, so a save can apply at once.
        try:
            from app import app

            app.config['MAX_CONTENT_LENGTH'] = int(float(get_setting('max_upload_mb'))) * 1024 * 1024
        except Exception:
            pass  # an import-time/test double without the Flask app still saves the value


# ─── Save ───────────────────────────────────────────────────────────────────


def save_settings(patch: dict) -> tuple[dict, list]:
    """Validate + merge ``patch``, persist, and return ``(values, warnings)``.

    Validation never rejects a whole save: a mistyped value falls back to its default
    and a warning comes back so the panel can show it. Unknown keys are ignored (the
    import path reports them instead of silently dropping them).
    """
    warnings = []
    with _lock:
        vals = dict(_load())
        for key in DEFAULTS:
            if key not in patch:
                continue
            vals[key] = _coerce(BY_KEY[key], patch[key], warnings)
        _values.update(vals)
        try:
            _write_locked(vals)
        except OSError as e:
            warnings.append(t('set.saveFailed', err=e))
    _apply_side_effects(patch)
    return dict(vals), warnings


# ─── Presets ────────────────────────────────────────────────────────────────


def preset_state() -> dict:
    """What the 慢速采集 card shows: active preset, when, and whether it was edited."""
    with _lock:
        vals = dict(_load())
        state = dict(_preset_state or {})
    if not state.get('active'):
        return {'active': '', 'customized': False, 'applied_at': '', 'keys': []}
    preset = PRESETS.get(state.get('active'))
    applied = state.get('applied') or {}
    customized = bool(preset) and any(vals.get(key) != applied.get(key) for key in preset['values'] if key in applied)
    return {
        'active': state.get('active', ''),
        'customized': customized,
        'applied_at': state.get('applied_at', ''),
        'keys': sorted(applied),
        'can_restore': bool(state.get('previous')),
    }


def apply_preset(preset_id: str) -> tuple[dict, list]:
    """Write a named preset as concrete values, snapshotting what it replaced.

    Values are written, not layered over the user's settings, so the effective
    configuration is exactly what the panel shows and no multiplier can stack.
    Applying a preset while another is active keeps the *original* snapshot: restore
    always goes back to the state before the first preset, never to an intermediate.
    """
    preset = PRESETS.get(str(preset_id or '').strip())
    if preset is None:
        raise KeyError(t('set.presetUnknown', preset=preset_id))
    warnings = []
    with _lock:
        vals = dict(_load())
        previous = dict((_preset_state or {}).get('previous') or {})
        applied = {}
        for key, raw in preset['values'].items():
            spec = BY_KEY[key]
            # The presets carry numbers that may need clamping (a machine with fewer
            # than 2 headless slots). Coerce through the same path, then record the
            # value that was actually stored so "customized" is measured against it.
            value = _coerce(spec, raw, warnings)
            applied[key] = value
            if key not in previous:
                previous[key] = vals.get(key, spec.default)
            vals[key] = value
        _preset_state.clear()
        _preset_state.update(
            {
                'active': str(preset_id),
                'applied_at': datetime.now().astimezone().isoformat(timespec='seconds'),
                'previous': previous,
                'applied': applied,
            }
        )
        _values.update(vals)
        try:
            _write_locked(vals)
        except OSError as e:
            warnings.append(t('set.saveFailed', err=e))
    return dict(vals), warnings


def restore_preset() -> tuple[dict, list]:
    """Put back exactly the values the active preset replaced, then clear it."""
    warnings = []
    with _lock:
        state = dict(_preset_state or {})
        if not state.get('active'):
            return dict(_load()), [t('set.presetNone')]
        previous = state.get('previous') or {}
        vals = dict(_load())
        for key, raw in previous.items():
            spec = BY_KEY.get(key)
            if spec is None:
                continue
            vals[key] = _coerce(spec, raw, warnings)
        _preset_state.clear()
        _values.update(vals)
        try:
            _write_locked(vals)
        except OSError as e:
            warnings.append(t('set.saveFailed', err=e))
    _apply_side_effects(dict(previous))
    return dict(vals), warnings


# ─── Export / import ────────────────────────────────────────────────────────


def export_payload(include_machine: bool = False) -> dict:
    """A portable settings package.

    Machine paths are host fingerprints and are omitted unless the caller asks for
    them. ``secret`` settings are never written by this function, today or later.
    """
    with _lock:
        vals = dict(_load())
        preset = dict(_preset_state or {})
    values = {}
    machine = {}
    for spec in SETTINGS:
        if spec.secret:
            continue
        value = vals.get(spec.key, spec.default)
        if spec.portable:
            values[spec.key] = value
        elif include_machine:
            machine[spec.key] = value
    payload = {
        'kind': EXPORT_KIND,
        'schema': SCHEMA_VERSION,
        'app_version': _app_version(),
        'exported_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'platform': sys.platform,
        'values': values,
        'preset': preset,
    }
    if include_machine:
        payload['machine'] = machine
    return payload


def _app_version() -> str:
    try:
        from services.version import APP_VERSION

        return str(APP_VERSION)
    except Exception:
        return ''


def import_payload(
    payload: dict,
    *,
    mode: str = 'merge',
    include_machine: bool = False,
    dry_run: bool = False,
) -> dict:
    """Validate and (unless ``dry_run``) apply an exported settings package.

    Returns ``{ok, values, warnings, skipped, changed, dry_run}``. A bad package is a
    named refusal (``ok=False``) and writes nothing; individual bad values still
    degrade to their defaults with warnings, exactly like an ordinary save.
    """
    warnings: list[str] = []
    skipped: list[str] = []
    if not isinstance(payload, dict):
        return {'ok': False, 'error': t('set.importBadPayload'), 'warnings': [], 'skipped': []}
    if payload.get('kind') != EXPORT_KIND:
        return {
            'ok': False,
            'error': t('set.importBadKind', kind=payload.get('kind') or ''),
            'warnings': [],
            'skipped': [],
        }
    try:
        version = int(payload.get('schema') or 0)
    except (TypeError, ValueError):
        version = 0
    if version > SCHEMA_VERSION:
        return {
            'ok': False,
            'error': t('set.importFuture', version=version, current=SCHEMA_VERSION),
            'warnings': [],
            'skipped': [],
        }
    if mode not in ('merge', 'replace'):
        return {'ok': False, 'error': t('set.importBadMode', mode=mode), 'warnings': [], 'skipped': []}

    source: dict = {}
    raw_values = payload.get('values')
    if isinstance(raw_values, dict):
        source.update(raw_values)
    raw_machine = payload.get('machine')
    if isinstance(raw_machine, dict):
        if include_machine:
            source.update(raw_machine)
        else:
            skipped.extend(sorted(raw_machine))
            if raw_machine:
                warnings.append(t('set.importMachineSkipped', n=len(raw_machine)))

    with _lock:
        current = dict(_load())
    next_values = dict(DEFAULTS) if mode == 'replace' else dict(current)
    if mode == 'replace' and not include_machine:
        # A replace package never carries host paths unless the caller opted in, so
        # "reset everything" must not blank the driver/profile this machine is using.
        for key in MACHINE_KEYS:
            next_values[key] = current.get(key, DEFAULTS.get(key))
    changed = []
    for key, raw in source.items():
        spec = BY_KEY.get(key)
        if spec is None:
            warnings.append(t('set.importUnknownKey', setting=key))
            skipped.append(key)
            continue
        if not spec.portable and not include_machine:
            warnings.append(t('set.importMachineSkippedKey', setting=key))
            skipped.append(key)
            continue
        value = _coerce(spec, raw, warnings)
        if next_values.get(key) != value:
            changed.append(key)
        next_values[key] = value

    result = {
        'ok': True,
        'values': next_values,
        'warnings': warnings,
        'skipped': skipped,
        'changed': sorted(changed),
        'dry_run': bool(dry_run),
    }
    if dry_run:
        return result

    with _lock:
        _values.update(next_values)
        preset = payload.get('preset')
        if isinstance(preset, dict) and preset.get('active'):
            _preset_state.clear()
            _preset_state.update(preset)
        elif mode == 'replace':
            # A replace package is the whole configuration; a stale snapshot from the
            # previous profile would restore values this import just replaced.
            _preset_state.clear()
        try:
            _write_locked(next_values)
        except OSError as e:
            return {'ok': False, 'error': t('set.saveFailed', err=e), 'warnings': warnings, 'skipped': skipped}
    _apply_side_effects({key: True for key in changed})
    return result
