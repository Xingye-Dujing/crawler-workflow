"""Watch one bibliometric network across runs.

A CiteSpace session ends at "one graph, drawn now". A field that is still moving asks the
opposite question — *what changed since last month?* — and that is a question about two graphs.
This module is the piece that turns a scheduled canvas (定时任务) into a monitor: every run
captures its own network into a named project and compares it with the capture before it, so the
answer arrives as console lines, one CSV row per change, and a diff the workspace panel can show
again after a restart.

Nothing here invents a threshold or a verdict. An alert is a named count of what moved — which
terms started bursting, which cluster appeared, which node fell out — and reading it as "the field
got hotter" stays the researcher's job.
"""

from __future__ import annotations

import csv
from pathlib import Path

from i18n import t
from services.biblio.metrics import snapshot_capture
from services.biblio.schema import WATCH_UNSHAPED
from services.biblio.store import compare_snapshots

#: One row per change the comparison found. ``前值`` is the baseline, ``后值`` this run.
WATCH_COLUMNS = ('类别', '名称', '前值', '后值')


def watch(
    rows: list[dict],
    params: dict,
    *,
    node_id: str,
    run_id: str,
    workflow_name: str,
    entity_type: str,
    shape: str,
    biblio,
    export_dir: str,
    stamp: str = '',
) -> dict | None:
    """Capture this run's network and diff it against the project's previous capture.

    Returns ``None`` when watching is off (an empty project name), so a node configured the way it
    always was behaves exactly as it did before this parameter existed. Raises ``ValueError`` with
    a named reason when it is on and cannot answer — a monitor that quietly skipped a week is
    worse than one that fails.

    ``biblio`` and ``export_dir`` are handed in rather than imported: the store is a per-process
    singleton the API owns, and a node executor that reached for it directly could not be pointed
    at a temporary database in a test.
    """
    project_name = str(params.get('watch_project') or '').strip()
    if not project_name:
        return None
    if shape in WATCH_UNSHAPED:
        # Validation already refuses this at run start; the door here is the second asking, so a
        # caller that reached the function directly cannot file a mis-shaped capture.
        raise ValueError(t('biblio.watch_needs_entity_table', nid=node_id, shape=shape))

    captured = snapshot_capture(rows)
    if not captured['nodes'] and not captured['edges']:
        raise ValueError(t('biblio.watch_empty', nid=node_id))

    notes: list[str] = []
    # Deterministic on purpose: two watched nodes on one parallel canvas can look for the same
    # name before either has filed it, and a second run must then pick the SAME project rather than
    # the other half of a duplicated history.
    named = sorted(
        (project for project in biblio.list_projects() if str(project.get('name') or '').strip() == project_name),
        key=lambda project: str(project.get('project_id') or ''),
    )
    project = named[0] if named else None
    if project is None:
        project = biblio.create_project(project_name, note=t('biblio.watch_project_note'))
        notes.append(t('biblio.watch_project_created', name=project_name))
    project_id = str(project['project_id'])

    prior = biblio.list_snapshots(project_id)
    wanted = str(params.get('watch_baseline') or '').strip()
    if wanted:
        baseline = next((s for s in prior if str(s.get('label') or '') == wanted), None)
        if baseline is None:
            known = '、'.join(str(s.get('label') or s.get('snapshot_id')) for s in prior[:10])
            raise ValueError(t('biblio.watch_baseline_missing', nid=node_id, label=wanted, known=known or '（无）'))
    else:
        # Newest first, and this run's own capture does not exist yet, so [0] is the previous one.
        baseline = prior[0] if prior else None

    label = str(params.get('watch_label') or '').strip() or stamp or run_id
    # The watch's own boxes are not settings that produced this graph — they say where the capture
    # is filed and what it is called. Filed beside the real parameters, every capture would differ
    # from its baseline by its own name, and 「参数变了」 would stop meaning anything.
    graph_params = {key: value for key, value in params.items() if not str(key).startswith('watch_')}
    snapshot = biblio.add_snapshot(
        project_id=project_id,
        label=label,
        run_id=run_id,
        node_id=node_id,
        workflow_name=workflow_name,
        entity_type=entity_type,
        shape=shape,
        # These params are the ones the engine is executing right now, so this path does not need
        # the panel's fingerprint round-trip to claim them; the panel reads a SAVED file and has
        # to prove the canvas still says what the run recorded.
        params=graph_params,
        params_verified=True,
        nodes=captured['nodes'],
        edges=captured['edges'],
    )

    diff = None if baseline is None else compare_snapshots(biblio.get_snapshot(baseline['snapshot_id']), snapshot)
    watch_rows = _rows_of(diff, snapshot, project_name)
    path = _write(watch_rows, export_dir, f'{workflow_name or "biblio"}-{node_id}-watch.csv')
    notes.extend(_narrate(diff, baseline, snapshot, project_name))
    return {
        'project': {'project_id': project_id, 'name': project_name},
        'snapshot': _brief(snapshot),
        'baseline': _brief(baseline) if baseline else None,
        'diff': diff,
        'file': str(path),
        'notes': notes,
    }


def _brief(snapshot: dict) -> dict:
    return {
        'snapshot_id': snapshot.get('snapshot_id'),
        'label': snapshot.get('label'),
        'created_at': snapshot.get('created_at'),
        'node_count': snapshot.get('node_count'),
        'edge_count': snapshot.get('edge_count'),
    }


def _rows_of(diff: dict | None, snapshot: dict, project_name: str) -> list[dict]:
    # ``baseline`` is deliberately not a parameter (``_narrate`` beside this does read it): every
    # 前值/后值 pair a row carries already came out of the comparison, so the table needs nothing
    # but the diff and this capture.
    if diff is None:
        return [
            {
                '类别': t('biblio.watch.first'),
                '名称': project_name,
                '前值': '',
                '后值': f'{snapshot.get("node_count")}/{snapshot.get("edge_count")}',
            }
        ]
    rows: list[dict] = []

    def add(kind: str, name: str, before='', after='') -> None:
        rows.append({'类别': kind, '名称': name, '前值': before, '后值': after})

    nodes = diff['nodes']
    for name in nodes['added']['items']:
        add(t('biblio.watch.node_added'), name)
    for name in nodes['removed']['items']:
        add(t('biblio.watch.node_removed'), name)
    for item in nodes['changed']['items']:
        for column, move in sorted(item['columns'].items()):
            add(t('biblio.watch.node_changed'), f'{item["name"]} · {column}', move['a'], move['b'])

    edges = diff['edges']
    for item in edges['added']['items']:
        add(t('biblio.watch.edge_added'), f'{item["source"]} — {item["target"]}')
    for item in edges['removed']['items']:
        add(t('biblio.watch.edge_removed'), f'{item["source"]} — {item["target"]}')
    for item in edges['weight_changed']['items']:
        add(t('biblio.watch.edge_weight'), f'{item["source"]} — {item["target"]}', item['a'], item['b'])

    clusters = diff['clusters']
    for key in clusters['added']['items']:
        add(t('biblio.watch.cluster_added'), f'#{key}')
    for key in clusters['removed']['items']:
        add(t('biblio.watch.cluster_removed'), f'#{key}')
    for item in clusters['relabeled']['items']:
        add(t('biblio.watch.cluster_relabeled'), f'#{item["cluster"]}', item['a'], item['b'])
    for item in clusters['size_changed']['items']:
        add(t('biblio.watch.cluster_size'), f'#{item["cluster"]}', item['a'], item['b'])

    bursts = diff['bursts']
    for name in bursts['added']['items']:
        add(t('biblio.watch.burst_added'), name)
    for name in bursts['removed']['items']:
        add(t('biblio.watch.burst_removed'), name)
    for item in bursts['strength_changed']['items']:
        add(t('biblio.watch.burst_strength'), item['name'], item['a'], item['b'])

    for item in diff['params_differ']['items']:
        add(t('biblio.watch.param'), item['name'], item['a'], item['b'])
    return rows


def _count(block: dict, key: str) -> int:
    return int((block[key] or {}).get('total') or 0)


def _narrate(diff: dict | None, baseline: dict | None, snapshot: dict, project_name: str) -> list[str]:
    if diff is None:
        return [
            t(
                'biblio.watch_first_done',
                project=project_name,
                label=snapshot.get('label'),
                nodes=snapshot.get('node_count'),
                edges=snapshot.get('edge_count'),
            )
        ]
    moved = {
        t('biblio.watch.node_added'): _count(diff['nodes'], 'added'),
        t('biblio.watch.node_removed'): _count(diff['nodes'], 'removed'),
        t('biblio.watch.node_changed'): _count(diff['nodes'], 'changed'),
        t('biblio.watch.edge_added'): _count(diff['edges'], 'added'),
        t('biblio.watch.edge_removed'): _count(diff['edges'], 'removed'),
        t('biblio.watch.edge_weight'): _count(diff['edges'], 'weight_changed'),
        t('biblio.watch.cluster_added'): _count(diff['clusters'], 'added'),
        t('biblio.watch.cluster_removed'): _count(diff['clusters'], 'removed'),
        t('biblio.watch.burst_added'): _count(diff['bursts'], 'added'),
        t('biblio.watch.burst_removed'): _count(diff['bursts'], 'removed'),
    }
    # A monitor that reports "0 of everything" in ten lines is noise the user learns to skip, so
    # the zeros fold into one phrase and only what actually moved is spelled out.
    details = '；'.join(f'{word} {count}' for word, count in moved.items() if count)
    lines = [
        t(
            'biblio.watch_done',
            project=project_name,
            baseline=baseline.get('label'),
            label=snapshot.get('label'),
            detail=details or t('biblio.watch.nothing'),
            limit=diff['diff_limit'],
        )
    ]
    if diff['params_differ']['total']:
        # Naming the settings that moved is what lets the reader tell "the field changed" from
        # "someone edited the node" — the two look identical in a diff of numbers.
        lines.append(
            t(
                'biblio.watch_params_differ',
                n=diff['params_differ']['total'],
                names='、'.join(str(item['name']) for item in diff['params_differ']['items'][:8]),
            )
        )
    elif not details:
        lines.append(t('biblio.watch_unchanged', nodes=snapshot.get('node_count'), edges=snapshot.get('edge_count')))
    if not diff['same_shape']:
        lines.append(t('biblio.watch_shape_differs', a=baseline.get('shape'), b=snapshot.get('shape')))
    return lines


def _write(rows: list[dict], export_dir: str, name: str) -> Path:
    directory = Path(export_dir)
    directory.mkdir(parents=True, exist_ok=True)
    safe = ''.join(ch for ch in name if ch not in '\\/:*?"<>|').strip() or 'watch.csv'
    path = directory / safe
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(WATCH_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return path
