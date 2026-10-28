"""Project bundles: one zip to move a saved canvas and the files it reads.

A workflow file names its datasets by id. Copying the JSON to another machine is
therefore not enough — the ids point into this machine's ``datasets.db``, and
the upload nodes reopen empty. This module packages a saved workflow (or every
saved workflow) together with the datasets and reusable templates it references,
and on import writes them back with NEW ids, rewriting every reference it knows.

The bundle is deliberately a plain zip of JSON files with a manifest:

    manifest.json
    workflows/000.json
    datasets/000.json
    templates/000.json

No database file is copied. A dataset is written as its explicit column list plus
its records, exactly the shape ``DatasetStore`` already round-trips, so importing
goes through the same validation as an upload. The manifest carries the format,
a version, per-file checksums and the original ids; an unknown version or a
changed byte is refused by name instead of half-importing a project.

Import is not allowed to overwrite authored work. A workflow or template whose
name already exists is imported under the next free `` (2)`` name, and the
returned summary says what was renamed. Dataset ids are content identities, so
identical data reuses the existing row and reports ``stored=False``.
"""

import copy
import hashlib
import io
import json
import re
import time
import zipfile

import pandas as pd
from core.config import Config
from stores import get_dataset_store

from i18n import t
from services.datasets.store import SOURCE_IMPORT, safe_records
from services.workflows import reusable
from services.workflows.manager import WorkflowManager

BUNDLE_FORMAT = 'cixi-project'
BUNDLE_VERSION = 1
MAX_ENTRIES = 5000
MAX_UNCOMPRESSED_BYTES = 2 * 1024**3
MAX_FILE_BYTES = 512 * 1024**2
MAX_WORKFLOWS = 200
MAX_DATASETS = 1000
MAX_TEMPLATES = 500

_ENTRY = re.compile(r'^(workflows|datasets|templates)/\d{3}\.json$')


def _json_bytes(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _nodes(workflow: dict):
    """Every top-level canvas node, including the members of serial groups."""
    for node in workflow.get('nodes') or []:
        if isinstance(node, dict):
            yield node
    for group in workflow.get('serialGroups') or []:
        if not isinstance(group, dict):
            continue
        for node in group.get('nodes') or []:
            if isinstance(node, dict):
                yield node


def _dataset_refs(workflow: dict) -> set:
    """Dataset ids a canvas reads, from ``dataset_id`` and ``*_dataset_id`` params."""
    refs = set()
    for node in _nodes(workflow):
        params = node.get('params') or {}
        if not isinstance(params, dict):
            continue
        for key, value in params.items():
            if key == 'dataset_id' or str(key).endswith('_dataset_id'):
                clean = str(value or '').strip()
                if clean:
                    refs.add(clean)
    return refs


def _template_refs(workflow: dict) -> set:
    refs = set()
    for node in _nodes(workflow):
        params = node.get('params') or {}
        if not isinstance(params, dict):
            continue
        clean = str(params.get('template_id') or '').strip()
        if clean:
            refs.add(clean)
    return refs


def _lineage_names(workflow: dict) -> set:
    """Cumulative-dataset names this canvas appends to."""
    names = set()
    for node in _nodes(workflow):
        if node.get('type') != 'accumulate':
            continue
        params = node.get('params') or {}
        clean = str(params.get('lineage_name') or '').strip()
        if clean:
            names.add(clean)
    return names


def _unique_lineage_name(original: str, taken: set) -> str:
    base = str(original or '').strip() or t('ds.lineage_name_required')
    candidate = base
    suffix = 2
    while candidate.casefold() in taken:
        candidate = f'{base} ({suffix})'
        suffix += 1
    return candidate


def _upload_refs(workflow: dict) -> dict:
    """The node → file ledger ``DatasetStore.bind`` expects, upload nodes only."""
    refs = {}
    for node in workflow.get('nodes') or []:
        if not isinstance(node, dict) or node.get('type') != 'upload':
            continue
        params = node.get('params') or {}
        if isinstance(params, dict) and str(params.get('dataset_id') or ''):
            refs[str(node.get('id') or '')] = params
    return refs


def _pack(files: dict, prefix: str, index: int, payload) -> str:
    name = f'{prefix}/{index:03d}.json'
    files[name] = _json_bytes(payload)
    return name


def _entry_meta(file: str, files: dict) -> dict:
    data = files[file]
    return {'file': file, 'sha1': _sha1(data), 'bytes': len(data)}


def _unique_workflow_name(manager: WorkflowManager, original: str, taken: set) -> str:
    base = manager.clean_name(original)
    candidate = base
    suffix = 2
    while candidate.casefold() in taken:
        candidate = manager.clean_name(f'{base} ({suffix})')
        suffix += 1
    return candidate


def _unique_template_name(original: str, taken: set) -> str:
    base = (str(original or '').strip() or t('reusable.nameRequired'))[: reusable.MAX_NAME]
    candidate = base
    suffix = 2
    while candidate.casefold() in taken:
        tail = f' ({suffix})'
        candidate = base[: max(1, reusable.MAX_NAME - len(tail))] + tail
        suffix += 1
    return candidate


def build_bundle(workflow_names, dataset_store=None, workflow_manager=None) -> tuple:
    """The zip bytes, a download name, and visible warnings.

    ``workflow_names`` is already resolved by the caller (one current file or every
    saved file). A missing dataset is a refusal: a bundle that silently omits the
    file an upload node reads is not a project. A missing template is only a warning
    because an instance carries its own embedded snapshot and still runs.
    """
    store = dataset_store or get_dataset_store()
    manager = workflow_manager or WorkflowManager()
    names = []
    for raw in workflow_names or []:
        clean = manager.clean_name(str(raw or ''))
        if clean and clean not in names:
            names.append(clean)
    if not names:
        raise ValueError(t('project.noWorkflow'))

    workflows = []
    for name in names:
        payload = manager.load(name)
        if not payload:
            raise ValueError(t('project.workflowUnreadable', name=name))
        workflows.append((name, payload))

    dataset_ids = sorted({ref for _name, payload in workflows for ref in _dataset_refs(payload)})
    template_ids = sorted({ref for _name, payload in workflows for ref in _template_refs(payload)})

    warnings = []
    lineage_entries = []
    for lineage_name in sorted({name for _name, payload in workflows for name in _lineage_names(payload)}):
        lineage = store.lineage(lineage_name)
        if lineage is None:
            warnings.append(t('project.lineageMissing', name=lineage_name))
            continue
        current_id = str(lineage.get('current_dataset_id') or '')
        if current_id and current_id not in dataset_ids:
            dataset_ids.append(current_id)
        lineage_entries.append(
            {
                'name': lineage_name,
                'current_dataset_id': current_id,
                'version': int(lineage.get('version') or 1),
            }
        )

    files = {}
    dataset_entries = []
    for index, dataset_id in enumerate(dataset_ids):
        frame = store.get(dataset_id)
        if frame is None:
            raise ValueError(t('project.datasetMissing', id=dataset_id))
        meta = store.meta(dataset_id) or {}
        file = _pack(
            files,
            'datasets',
            index,
            {
                'id': dataset_id,
                'name': meta.get('name') or dataset_id,
                'source': meta.get('source') or '',
                'columns': [str(column) for column in frame.columns],
                'records': safe_records(frame),
            },
        )
        dataset_entries.append(
            {
                'id': dataset_id,
                'name': meta.get('name') or dataset_id,
                'rows': int(meta.get('row_count') or len(frame)),
                **_entry_meta(file, files),
            }
        )

    template_entries = []
    for index, template_id in enumerate(template_ids):
        try:
            template = reusable.get_template(template_id)
        except reusable.TemplateCorruptError:
            template = None
        if template is None:
            warnings.append(t('project.templateMissing', id=template_id))
            continue
        file = _pack(files, 'templates', index, template)
        template_entries.append(
            {
                'id': template_id,
                'name': str(template.get('name') or ''),
                **_entry_meta(file, files),
            }
        )

    workflow_entries = []
    for index, (name, payload) in enumerate(workflows):
        file = _pack(files, 'workflows', index, payload)
        workflow_entries.append({'name': name, **_entry_meta(file, files)})

    manifest = {
        'format': BUNDLE_FORMAT,
        'version': BUNDLE_VERSION,
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'workflows': workflow_entries,
        'datasets': dataset_entries,
        'templates': template_entries,
        'lineages': lineage_entries,
        'warnings': warnings,
        'counts': {
            'workflows': len(workflow_entries),
            'datasets': len(dataset_entries),
            'templates': len(template_entries),
        },
    }
    files['manifest.json'] = _json_bytes(manifest)

    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in ['manifest.json', *sorted(key for key in files if key != 'manifest.json')]:
            archive.writestr(name, files[name])
    filename = f'project-{time.strftime("%Y%m%d-%H%M%S")}.zip'
    return output.getvalue(), filename, warnings


def _read_json(archive: zipfile.ZipFile, names: set, entry: dict, prefix: str):
    file = str(entry.get('file') or '')
    if not _ENTRY.match(file) or not file.startswith(prefix + '/'):
        raise ValueError(t('project.badEntry', file=file or '(empty)'))
    if file not in names:
        raise ValueError(t('project.entryMissing', file=file))
    info = archive.getinfo(file)
    if info.file_size > MAX_FILE_BYTES:
        raise ValueError(t('project.fileTooLarge', file=file, mb=MAX_FILE_BYTES // (1024 * 1024)))
    data = archive.read(file)
    recorded = str(entry.get('sha1') or '')
    if recorded and _sha1(data) != recorded:
        raise ValueError(t('project.checksum', file=file))
    try:
        return json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as e:
        raise ValueError(t('project.badJson', file=file)) from e


def _validate_manifest(manifest) -> None:
    if not isinstance(manifest, dict) or manifest.get('format') != BUNDLE_FORMAT:
        raise ValueError(t('project.badFormat'))
    if manifest.get('version') != BUNDLE_VERSION:
        raise ValueError(t('project.badVersion', version=manifest.get('version')))
    for section, limit in (
        ('workflows', MAX_WORKFLOWS),
        ('datasets', MAX_DATASETS),
        ('templates', MAX_TEMPLATES),
    ):
        rows = manifest.get(section)
        if not isinstance(rows, list):
            raise ValueError(t('project.badManifest', section=section))
        if len(rows) > limit:
            raise ValueError(t('project.tooMany', section=section, max=limit))
    lineages = manifest.get('lineages', [])
    if not isinstance(lineages, list):
        raise ValueError(t('project.badManifest', section='lineages'))


def _rewrite_refs(workflow: dict, datasets: dict, templates: dict, lineages: dict = None) -> None:
    """Point every recognised reference at the id/name the import actually wrote."""
    for node in _nodes(workflow):
        params = node.get('params')
        if not isinstance(params, dict):
            continue
        old_dataset = str(params.get('dataset_id') or '')
        for key in list(params):
            if key == 'dataset_id' or str(key).endswith('_dataset_id'):
                meta = datasets.get(str(params.get(key) or ''))
                if meta is not None:
                    params[key] = meta['id']
        meta = datasets.get(old_dataset)
        if meta is not None and (node.get('type') == 'upload' or 'dataset_name' in params):
            params['dataset_name'] = meta['name']
            params['row_count'] = meta['row_count']
        old_template = str(params.get('template_id') or '')
        found = templates.get(old_template)
        if found is not None:
            params['template_id'] = found['id']
            params['template_name'] = found['name']
        old_lineage = str(params.get('lineage_name') or '')
        found_lineage = (lineages or {}).get(old_lineage)
        if found_lineage is not None:
            params['lineage_name'] = found_lineage


def import_bundle(file_obj, dataset_store=None, workflow_manager=None) -> dict:
    """Read a bundle and write its pieces, remapping ids and avoiding overwrites."""
    store = dataset_store or get_dataset_store()
    manager = workflow_manager or WorkflowManager()
    try:
        archive = zipfile.ZipFile(file_obj)
    except zipfile.BadZipFile as e:
        raise ValueError(t('project.badZip')) from e

    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > MAX_ENTRIES:
            raise ValueError(t('project.tooManyEntries', max=MAX_ENTRIES))
        total = sum(max(0, int(info.file_size)) for info in infos)
        if total > MAX_UNCOMPRESSED_BYTES:
            raise ValueError(t('project.tooLarge', mb=MAX_UNCOMPRESSED_BYTES // (1024 * 1024)))
        names = {info.filename for info in infos}
        if 'manifest.json' not in names:
            raise ValueError(t('project.entryMissing', file='manifest.json'))
        if archive.getinfo('manifest.json').file_size > MAX_FILE_BYTES:
            raise ValueError(t('project.fileTooLarge', file='manifest.json', mb=MAX_FILE_BYTES // (1024 * 1024)))
        try:
            manifest = json.loads(archive.read('manifest.json').decode('utf-8'))
        except (UnicodeDecodeError, ValueError) as e:
            raise ValueError(t('project.badJson', file='manifest.json')) from e
        _validate_manifest(manifest)
        if not manifest['workflows']:
            raise ValueError(t('project.noWorkflowInBundle'))

        datasets = []
        for entry in manifest['datasets']:
            payload = _read_json(archive, names, entry, 'datasets')
            if not isinstance(payload, dict):
                raise ValueError(t('project.datasetInvalid', id=entry.get('id') or '(empty)'))
            old_id = str(payload.get('id') or entry.get('id') or '').strip()
            if not old_id:
                raise ValueError(t('project.datasetInvalid', id='(empty)'))
            columns = payload.get('columns')
            records = payload.get('records')
            if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
                raise ValueError(t('project.datasetInvalid', id=old_id))
            if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
                raise ValueError(t('project.datasetInvalid', id=old_id))
            if len(records) > Config.DATASET_MAX_ROWS:
                raise ValueError(t('project.datasetTooLarge', id=old_id, max=Config.DATASET_MAX_ROWS))
            try:
                frame = pd.DataFrame(records, columns=columns)
            except (TypeError, ValueError) as e:
                raise ValueError(t('project.datasetInvalid', id=old_id)) from e
            datasets.append(
                {
                    'id': old_id,
                    'name': str(payload.get('name') or entry.get('name') or old_id),
                    'frame': frame,
                }
            )

        templates = []
        for entry in manifest['templates']:
            payload = _read_json(archive, names, entry, 'templates')
            if not isinstance(payload, dict):
                raise ValueError(t('project.templateInvalid', name=entry.get('name') or entry.get('id') or ''))
            try:
                reusable.validate_template(payload)
            except ValueError as e:
                raise ValueError(
                    t('project.templateInvalid', name=payload.get('name') or entry.get('name') or '')
                ) from e
            templates.append(
                {
                    'id': str(payload.get('id') or entry.get('id') or ''),
                    'name': str(payload.get('name') or ''),
                    'payload': payload,
                }
            )

        lineage_entries = []
        for entry in manifest.get('lineages', []):
            if not isinstance(entry, dict):
                raise ValueError(t('project.lineageInvalid'))
            old_name = str(entry.get('name') or '').strip()
            current_id = str(entry.get('current_dataset_id') or '').strip()
            if not old_name or not current_id:
                raise ValueError(t('project.lineageInvalid'))
            lineage_entries.append({'name': old_name, 'current_dataset_id': current_id})

        dataset_ids = {row['id'] for row in datasets}
        template_ids = {row['id'] for row in templates}
        workflows = []
        for entry in manifest['workflows']:
            payload = _read_json(archive, names, entry, 'workflows')
            if not isinstance(payload, dict) or not isinstance(payload.get('nodes'), list):
                raise ValueError(t('project.workflowInvalid', name=entry.get('name') or ''))
            missing = sorted(_dataset_refs(payload) - dataset_ids)
            if missing:
                raise ValueError(t('project.datasetRefMissing', id=missing[0]))
            name = str(payload.get('name') or entry.get('name') or 'untitled')
            workflows.append((name, payload))

        warnings = []
        for name, payload in workflows:
            missing_templates = sorted(_template_refs(payload) - template_ids)
            for template_id in missing_templates:
                warnings.append(t('project.templateRefMissing', name=name, id=template_id))

        dataset_map = {}
        for row in datasets:
            try:
                meta = store.put(row['frame'], name=row['name'], source=SOURCE_IMPORT)
            except ValueError as e:
                raise ValueError(t('project.datasetInvalid', id=row['id'])) from e
            dataset_map[row['id']] = {
                'id': meta['dataset_id'],
                'name': meta.get('name') or row['name'],
                'row_count': int(meta.get('row_count') or len(row['frame'])),
                'stored': bool(meta.get('stored')),
            }

        taken_lineages = {row['name'].casefold() for row in store.list_lineages()}
        lineage_map = {}
        lineage_results = []
        for entry in lineage_entries:
            mapped = dataset_map.get(entry['current_dataset_id'])
            if mapped is None:
                raise ValueError(t('project.datasetRefMissing', id=entry['current_dataset_id']))
            new_name = _unique_lineage_name(entry['name'], taken_lineages)
            taken_lineages.add(new_name.casefold())
            created = store.create_lineage(new_name, mapped['id'])
            lineage_map[entry['name']] = new_name
            lineage_results.append({'from': entry['name'], 'to': new_name, 'version': created['version']})

        taken_templates = {str(row['name']).casefold() for row in reusable.list_templates() if not row['broken']}
        template_map = {}
        for row in templates:
            name = _unique_template_name(row['name'], taken_templates)
            taken_templates.add(name.casefold())
            body = copy.deepcopy(row['payload'])
            body.pop('id', None)
            body.pop('created_at', None)
            body.pop('updated_at', None)
            body['name'] = name
            try:
                saved = reusable.save_template(body)
            except ValueError as e:
                raise ValueError(t('project.templateInvalid', name=name)) from e
            template_map[row['id']] = {'id': saved['id'], 'name': saved['name']}

        taken_workflows = {manager.clean_name(name).casefold() for name in manager.list_workflows()}
        workflow_results = []
        for name, payload in workflows:
            imported_name = _unique_workflow_name(manager, name, taken_workflows)
            taken_workflows.add(imported_name.casefold())
            body = copy.deepcopy(payload)
            body['name'] = imported_name
            _rewrite_refs(body, dataset_map, template_map, lineage_map)
            manager.save(imported_name, body)
            store.bind(imported_name, _upload_refs(body))
            workflow_results.append({'from': name, 'to': imported_name})

    return {
        'workflows': workflow_results,
        'datasets': [{'from': old_id, **meta} for old_id, meta in dataset_map.items()],
        'templates': [
            {'from': old_id, 'to': meta['id'], 'name': meta['name']} for old_id, meta in template_map.items()
        ],
        'lineages': lineage_results,
        'warnings': warnings,
    }
