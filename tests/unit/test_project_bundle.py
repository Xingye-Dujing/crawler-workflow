"""Project bundles: move a saved canvas, its datasets and its templates together."""

import io
import json
import zipfile

import pandas as pd
import pytest
from core.config import Config

from services.dataset_store import SOURCE_UPLOAD, DatasetStore
from services.workflows import reusable
from services.workflows.bundle import build_bundle, import_bundle
from services.workflows.manager import WorkflowManager


@pytest.fixture(autouse=True)
def isolated_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'REUSABLE_DIR', str(tmp_path / 'reusable_nodes'))


@pytest.fixture()
def stores(tmp_path):
    return {
        'datasets': DatasetStore(str(tmp_path / 'datasets.db')),
        'workflows': WorkflowManager(str(tmp_path / 'workflows')),
        'tmp': tmp_path,
    }


def _template(name='清洗模板'):
    return {
        'name': name,
        'description': '两步',
        'nodes': [
            {'id': 'a', 'type': 'process', 'title': '清洗', 'params': {'operation': 'clean'}, 'x': 0, 'y': 0},
            {'id': 'b', 'type': 'analysis', 'title': '去空', 'params': {'operation': 'drop_null'}, 'x': 260, 'y': 0},
        ],
        'connections': [{'from': 'a', 'to': 'b'}],
        'inputs': ['a'],
        'outputs': ['b'],
    }


def _workflow(dataset_id, template_id, name='项目A'):
    return {
        'name': name,
        'nodes': [
            {
                'id': 'node-0',
                'type': 'upload',
                'title': '原始数据',
                'params': {
                    'dataset_id': dataset_id,
                    'dataset_name': 'raw.csv',
                    'row_count': 2,
                },
                'x': 0,
                'y': 0,
            },
            {
                'id': 'node-1',
                'type': 'reusable',
                'title': '清洗模板',
                'params': {
                    'template_id': template_id,
                    'template_name': '清洗模板',
                    'template': {
                        'nodes': _template()['nodes'],
                        'connections': _template()['connections'],
                        'inputs': ['a'],
                        'outputs': ['b'],
                    },
                    'collapsed': True,
                },
                'x': 300,
                'y': 0,
            },
            {'id': 'node-2', 'type': 'output', 'title': '输出', 'params': {}, 'x': 600, 'y': 0},
        ],
        'connections': [
            {'from': 'node-0', 'to': 'node-1'},
            {'from': 'node-1', 'to': 'node-2'},
        ],
        'settings': {'mode': 'serial'},
    }


def _seed(stores, workflow_name='项目A', template_name='清洗模板'):
    dataset = stores['datasets'].put(
        pd.DataFrame([{'标题': 'a', '正文': 'x'}, {'标题': 'b', '正文': 'y'}]),
        name='raw.csv',
        source=SOURCE_UPLOAD,
    )
    template = reusable.save_template(_template(template_name))
    stores['workflows'].save(workflow_name, _workflow(dataset['dataset_id'], template['id'], workflow_name))
    return dataset, template


class TestBuildAndImport:
    def test_a_bundle_carries_the_workflow_dataset_and_template(self, stores):
        dataset, template = _seed(stores)
        payload, filename, warnings = build_bundle(
            ['项目A'], dataset_store=stores['datasets'], workflow_manager=stores['workflows']
        )
        assert filename.endswith('.zip')
        assert warnings == []
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            assert manifest['format'] == 'cixi-project'
            assert manifest['counts'] == {'workflows': 1, 'datasets': 1, 'templates': 1}
            assert manifest['datasets'][0]['id'] == dataset['dataset_id']
            assert manifest['templates'][0]['id'] == template['id']
            assert set(archive.namelist()) >= {'manifest.json', 'workflows/000.json'}

    def test_import_remaps_ids_and_rewrites_the_saved_workflow(self, stores, tmp_path, monkeypatch):
        dataset, template = _seed(stores)
        payload, _filename, _warnings = build_bundle(
            ['项目A'], dataset_store=stores['datasets'], workflow_manager=stores['workflows']
        )

        other = tmp_path / 'other'
        monkeypatch.setattr(Config, 'REUSABLE_DIR', str(other / 'reusable_nodes'))
        target_datasets = DatasetStore(str(other / 'datasets.db'))
        target_workflows = WorkflowManager(str(other / 'workflows'))
        summary = import_bundle(io.BytesIO(payload), dataset_store=target_datasets, workflow_manager=target_workflows)

        assert summary['workflows'] == [{'from': '项目A', 'to': '项目A'}]
        assert summary['datasets'][0]['stored'] is True
        imported = target_workflows.load('项目A')
        assert imported is not None
        upload = imported['nodes'][0]['params']
        assert upload['dataset_id'] == summary['datasets'][0]['id']
        # Dataset identity is the content hash, so identical bytes imported into a
        # fresh store deliberately keep the same id; the pointer is still rewritten
        # through the bundle map and the workflow's ref ledger.
        assert upload['dataset_id'] == dataset['dataset_id']
        assert upload['dataset_name'] == 'raw.csv'
        group = imported['nodes'][1]['params']
        assert group['template_id'] == summary['templates'][0]['to']
        assert group['template_id'] != template['id']
        assert group['template_name'] == '清洗模板'
        assert target_datasets.get(upload['dataset_id']) is not None
        assert target_datasets.refs_for('项目A')['node-0']['dataset_id'] == upload['dataset_id']

    def test_a_cumulative_lineage_travels_with_the_bundle(self, stores, tmp_path, monkeypatch):
        dataset, template = _seed(stores)
        lineage = stores['datasets'].append_lineage(
            '累积关键词',
            pd.DataFrame([{'标题': '历史'}], columns=['标题']),
        )
        workflow = _workflow(dataset['dataset_id'], template['id'])
        workflow['nodes'].append(
            {
                'id': 'node-9',
                'type': 'accumulate',
                'params': {'lineage_name': '累积关键词', 'identity': 'row', 'key_columns': ''},
            }
        )
        workflow['connections'].append({'from': 'node-0', 'to': 'node-9'})
        stores['workflows'].save('项目A', workflow)

        payload, _filename, _warnings = build_bundle(
            ['项目A'], dataset_store=stores['datasets'], workflow_manager=stores['workflows']
        )
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            assert manifest['lineages'][0]['name'] == '累积关键词'
            assert manifest['lineages'][0]['current_dataset_id'] == lineage['lineage']['current_dataset_id']
            assert lineage['lineage']['current_dataset_id'] in {row['id'] for row in manifest['datasets']}

        other = tmp_path / 'other'
        monkeypatch.setattr(Config, 'REUSABLE_DIR', str(other / 'reusable_nodes'))
        target_datasets = DatasetStore(str(other / 'datasets.db'))
        target_workflows = WorkflowManager(str(other / 'workflows'))
        target_datasets.append_lineage('累积关键词', pd.DataFrame([{'标题': '本地'}], columns=['标题']))
        summary = import_bundle(io.BytesIO(payload), dataset_store=target_datasets, workflow_manager=target_workflows)
        assert summary['lineages'] == [{'from': '累积关键词', 'to': '累积关键词 (2)', 'version': 1}]
        imported = target_workflows.load('项目A')
        node = next(row for row in imported['nodes'] if row.get('type') == 'accumulate')
        assert node['params']['lineage_name'] == '累积关键词 (2)'
        assert target_datasets.lineage('累积关键词 (2)')['rows'] == 1
        assert target_datasets.lineage('累积关键词')['rows'] == 1

    def test_import_never_overwrites_existing_workflows_or_template_names(self, stores, tmp_path, monkeypatch):
        _seed(stores)
        payload, _filename, _warnings = build_bundle(
            ['项目A'], dataset_store=stores['datasets'], workflow_manager=stores['workflows']
        )

        other = tmp_path / 'other'
        monkeypatch.setattr(Config, 'REUSABLE_DIR', str(other / 'reusable_nodes'))
        target_datasets = DatasetStore(str(other / 'datasets.db'))
        target_workflows = WorkflowManager(str(other / 'workflows'))
        target_workflows.save('项目A', {'nodes': [], 'connections': []})
        reusable.save_template(_template('清洗模板'))
        summary = import_bundle(io.BytesIO(payload), dataset_store=target_datasets, workflow_manager=target_workflows)

        assert summary['workflows'] == [{'from': '项目A', 'to': '项目A (2)'}]
        assert summary['templates'][0]['name'] == '清洗模板 (2)'
        assert target_workflows.load('项目A')['nodes'] == []
        imported = target_workflows.load('项目A (2)')
        assert imported['nodes'][1]['params']['template_name'] == '清洗模板 (2)'

    def test_a_missing_dataset_is_refused_before_any_write(self, stores):
        _seed(stores)
        workflow = stores['workflows'].load('项目A')
        workflow['nodes'][0]['params']['dataset_id'] = 'gone'
        stores['workflows'].save('项目A', workflow)
        with pytest.raises(ValueError) as exc:
            build_bundle(['项目A'], dataset_store=stores['datasets'], workflow_manager=stores['workflows'])
        assert 'gone' in str(exc.value)

    def test_a_broken_checksum_is_refused(self, stores):
        _seed(stores)
        payload, _filename, _warnings = build_bundle(
            ['项目A'], dataset_store=stores['datasets'], workflow_manager=stores['workflows']
        )
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        entries['datasets/000.json'] = entries['datasets/000.json'][:-1] + b' '
        broken = io.BytesIO()
        with zipfile.ZipFile(broken, 'w') as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        with pytest.raises(ValueError) as exc:
            import_bundle(
                io.BytesIO(broken.getvalue()),
                dataset_store=stores['datasets'],
                workflow_manager=stores['workflows'],
            )
        assert 'datasets/000.json' in str(exc.value)

    def test_a_non_zip_and_an_unknown_version_are_named(self, stores):
        with pytest.raises(ValueError):
            import_bundle(
                io.BytesIO(b'not a zip'), dataset_store=stores['datasets'], workflow_manager=stores['workflows']
            )
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, 'w') as archive:
            archive.writestr(
                'manifest.json',
                json.dumps(
                    {
                        'format': 'cixi-project',
                        'version': 99,
                        'workflows': [],
                        'datasets': [],
                        'templates': [],
                    }
                ),
            )
        with pytest.raises(ValueError) as exc:
            import_bundle(
                io.BytesIO(payload.getvalue()),
                dataset_store=stores['datasets'],
                workflow_manager=stores['workflows'],
            )
        assert '99' in str(exc.value)

    def test_an_entry_outside_the_known_folders_is_refused(self, stores):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, 'w') as archive:
            archive.writestr(
                'manifest.json',
                json.dumps(
                    {
                        'format': 'cixi-project',
                        'version': 1,
                        'workflows': [{'name': 'x', 'file': '../escape.json'}],
                        'datasets': [],
                        'templates': [],
                    }
                ),
            )
        with pytest.raises(ValueError) as exc:
            import_bundle(
                io.BytesIO(payload.getvalue()),
                dataset_store=stores['datasets'],
                workflow_manager=stores['workflows'],
            )
        assert '../escape.json' in str(exc.value)
