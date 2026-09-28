"""The shipped-canvas acceptance machinery, shared by every platform's H group.

``data/workflows/测试：<平台>.json`` files are the user's own: he built them, he re-runs them, and
they are the shape a real 终验 has to take. Each platform's live program runs its file three ways
(H1 exactly as saved, H2 every component enabled in series, H3 the same in parallel/headless), and
all three need the same six things: read the file without touching it, discover its components the
way the executor splits them, work out what each component was *asked* from the parameters the file
holds, find the run record each component wrote, grade each one against **its own** console slice,
and derive the case's index row from those verdicts rather than hard-coding a green.

This module holds those six. It used to live inside
:mod:`tests.live_site.test_live_zhihu_workflow`, which is the wrong home for two reasons: a second
platform either copies ~200 lines (and then one of them drifts) or skips the group — and a third
would copy the copy. The platform-specific halves stay where they were: which console lines count as
a *named* death, how a comment node's ask is judged from that site's own per-article lines, and what
a correct row looks like.

Nothing here decides whether a run passed: every judgement arrives through the caller's ``grade``
callback and is returned as data.
"""

import contextlib
import copy
import csv
from pathlib import Path


def workflow_file(path: Path) -> dict:
    """The user's own saved canvas, read **without touching it**.

    Read-only by contract: this is a workflow he made and re-runs himself, and a test that saved over
    it would destroy the thing it measures. No endpoint is used either — ``GET /api/workflow/load``
    writes two ambient keys into the application and needs the workflow directory to be the real one.
    """
    import json

    loaded = json.loads(Path(path).read_text(encoding='utf-8'))
    assert isinstance(loaded.get('nodes'), list) and loaded['nodes'], loaded
    assert isinstance(loaded.get('settings'), dict), loaded
    return loaded


def all_enabled(workflow: dict) -> dict:
    """A deep copy with every node switched on — the shipped canvas as its author's whole test.

    The copy is the point (plan decision D5): the file on disk is never rewritten to make a variant,
    because the variant is what the test wanted and the file is what the user wrote.
    """
    opened = copy.deepcopy(workflow)
    for node in opened['nodes']:
        node.setdefault('params', {})['enabled'] = True
    return opened


def comment_ask(*, limit: int, urls: list) -> int:
    """What a comment node was actually asked for, as a row count.

    ``comment_limit`` is per article, so the ask is the product — never 1. An open-ended walk
    (``comment_limit: 0``, 「采集全部评论」) has no row budget the user wrote down, so the only number
    it can be graded against is one row per panel it was told to open.
    """
    return (limit or 0) * len(urls) if limit else max(1, len(urls))


def components(workflow: dict, *, file_name: str) -> list:
    """The canvas's own components, read out of the file rather than copied into this test.

    An expected label that is a literal in a test file goes red over a rename by the user with a
    message about missing console lines — and the ask each component is graded against has to be the
    ask the record holds, not a number this module remembered. Each entry is
    ``{'label', 'source', 'mode', 'ask', 'comment_limit', 'urls', 'on'}``: ``label`` is the name node's
    label (what the run is filed under), ``on`` is whether the component still has all of its 启用
    switches, and ``ask`` is the node's own number — the *user's* ask, whatever the site does with it.

    Grouping is by connected component, exactly the way the executor splits a canvas into workflows:
    following one wire in one direction is not the same thing and would miss a canvas whose name node
    hangs off the far end of a chain.
    """
    import live_run_harness as harness

    nodes = {str(node.get('id')): node for node in workflow.get('nodes') or []}
    neighbours: dict = {nid: set() for nid in nodes}
    for conn in workflow.get('connections') or []:
        source_id, target_id = str(conn.get('from')), str(conn.get('to'))
        if source_id in neighbours and target_id in neighbours:
            neighbours[source_id].add(target_id)
            neighbours[target_id].add(source_id)

    seen: set = set()
    out = []
    for start in nodes:
        if start in seen:
            continue
        group, queue = set(), [start]
        seen.add(start)
        while queue:
            nid = queue.pop()
            group.add(nid)
            for nxt in neighbours[nid] - group:
                seen.add(nxt)
                queue.append(nxt)
        sources = [nid for nid in group if nodes[nid].get('type') == 'source']
        names = [nid for nid in group if nodes[nid].get('type') == 'name']
        if not sources:
            continue
        assert len(sources) == 1, f'{file_name} has a component with {len(sources)} sources: {group}'
        source_id = sources[0]
        params = nodes[source_id].get('params') or {}
        mode = str(params.get(harness.MODE_KEY) or '')
        urls = [line for line in str(params.get('urls') or '').split('\n') if line.strip()]
        limit = int(params.get('comment_limit') or 0)
        label = ''
        if names:
            label = str((nodes[names[0]].get('params') or {}).get('workflow_name') or '').strip()
        out.append(
            {
                'label': label,
                'source': source_id,
                'mode': mode,
                'ask': comment_ask(limit=limit, urls=urls)
                if mode == 'comments'
                else int(params.get('target_count') or 0),
                'comment_limit': limit,
                'urls': urls,
                # A disabled node anywhere in the component takes the whole workflow out — that is
                # ``effective_workflow`` cascading, and it is why the file's author switches off the
                # *name* node rather than the crawler.
                'on': all(bool((nodes[nid].get('params') or {}).get('enabled', True)) for nid in group),
            }
        )
    assert out, f'{file_name} holds no component with a source to run'
    return out


def parts(workflow: dict, *, file_name: str) -> tuple:
    """``(enabled_labels, disabled_labels, components)`` — all three from the workflow given.

    No shape claim is made here, because the three callers ask different questions: H1 runs the file
    **as saved** and is about naming who sat out, so it needs both an on and an off side; H2/H3 run
    ``all_enabled`` copies, where an empty ``off`` is the point. Asserting ``on and off`` inside this
    helper made those two cases unfailable.
    """
    found = components(workflow, file_name=file_name)
    on = [part['label'] for part in found if part['on']]
    off = [part['label'] for part in found if not part['on']]
    assert found, f'{file_name} holds no components at all: {workflow}'
    return on, off, found


def records_by_name(client) -> dict:
    """The panel's list, indexed by the name each component gave itself."""
    import live_run_harness as harness

    out: dict = {}
    for record in harness.read_records(client, limit=30):
        out.setdefault(str(record.get('workflow_name') or ''), record)
    return out


def records_by_node(client, found: list, *, limit: int = 40) -> dict:
    """Each 串行 component's own row, found by the node it owns rather than by its name.

    A serial run opens one record per workflow *as it is reached*, and a record is named by its
    ENABLED name node, falling back to the canvas's own name when that node is switched off — the
    product's documented precedence. So several rows can carry the identical 名称, and a name→record
    map hands two of them the wrong row. Node identity cannot collide: a component's source node
    exists in exactly one record of the run, which is what this resolves by.
    """
    import live_run_harness as harness

    records = harness.read_records(client, limit=limit)
    out: dict = {}
    for part in found:
        holder = [
            one
            for one in records
            if any(str(node.get('node_id') or '') == part['source'] for node in one.get('nodes') or [])
        ]
        assert len(holder) == 1, (
            f'component {part["label"]!r} (source {part["source"]}) is held by {len(holder)} run '
            f'records, exactly one was expected: {[one.get("workflow_name") for one in holder]}'
        )
        out[part['label']] = holder[0]
    return out


def audit_components(run, *, records: dict, case_id: str, found: list, grade) -> tuple:
    """One audit row per component, graded against that component's own console slice.

    ``grade(part, record, console)`` is the caller's: which lines excuse a shortfall differs by mode,
    and a comment crawl is judged from that site's per-article numbers, not from a row budget.

    A four-component run is four verdicts: rolling them into one number is how a half-empty crawl
    gets presented as a success, and grading them against the *whole* console is how one component's
    honest 「没有更多了」 whitewashes another component's silence. Returns the silent ones, the rows
    kept, the asks added up, and each component's own verdict — the last is what the summary row is
    derived from, so an index line can never read FULL over a run whose components did not.
    """
    import live_run_harness as harness

    silent: list = []
    answers: list = []
    kept_total = 0
    ask_total = 0
    for part in found:
        label, node_id, mode, target = part['label'], part['source'], part['mode'], part['ask']
        record = records.get(label)
        if record is None:
            silent.append((label, 'no record was opened for this component'))
            continue
        kept = harness.stored_rows(record, node_id)
        kept_total += kept
        ask_total += target
        answer = grade(part, record, run._slice(label))
        answers.append((label, answer))
        run.audit(
            # The node, not just the mode: a shipped canvas can hold TWO 帖子 components, and a row
            # named after the mode alone would overwrite the first component's transcript with the
            # second's and leave verdicts.csv with two rows no artifact can be matched to.
            f'{case_id}.{mode}.{node_id}',
            verdict=answer['verdict'],
            reasons=answer['reasons'],
            rows=kept,
            target=target,
            warn=answer['verdict'] != harness.FULL,
            # The component's own mode, not the case's: an acceptance run is ``mixed`` by necessity, and a
            # ledger that says ``mixed`` four times cannot be read against the platform's mode table.
            mode=mode,
        )
        if answer['verdict'] == harness.SILENT_SHORT:
            silent.append((label, f'kept {kept} of {target} with no reason named, or only one that lies'))
    return silent, kept_total, ask_total, answers


def summary_row(run, *, case_id: str, found: list, answers: list, kept: int, asked: int) -> str:
    """Derive the case's own index row from its components — never a hard-coded FULL.

    The artifact is what a root-cause pass reads, and a line that says FULL about a run whose
    components came up short contradicts the rows written directly above it.
    """
    import live_run_harness as harness

    verdicts = {label: answer['verdict'] for label, answer in answers}
    silent = [label for label, verdict in verdicts.items() if verdict == harness.SILENT_SHORT]
    short = [label for label, verdict in verdicts.items() if verdict == harness.NAMED_SHORT]
    missing = [part['label'] for part in found if part['label'] not in verdicts]
    if silent or missing:
        verdict = harness.SILENT_SHORT
    elif short or run.warned():
        verdict = harness.NAMED_SHORT
    else:
        verdict = harness.FULL
    reasons = [f'{len(found)} components, {kept} rows', *(f'silent: {label}' for label in silent + missing)]
    reasons += [f'short: {label}' for label in short]
    if run.warned():
        reasons.append('the session died mid-crawl (named)')
    run.audit(
        case_id,
        verdict=verdict,
        reasons=reasons,
        rows=kept,
        target=asked,
        warn=verdict != harness.FULL,
    )
    return verdict


def new_exports(before: set) -> list:
    """Files :data:`Config.EXPORT_DIR` gained while a run was going, newest first."""
    from config import Config

    return sorted(
        (path for path in Path(Config.EXPORT_DIR).glob('*') if path.name not in before),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def csv_row_count(path) -> tuple:
    """How many data rows one exported CSV holds, and its header."""
    with Path(path).open(newline='', encoding='utf-8-sig') as handle:
        rows = list(csv.reader(handle))
    return max(0, len(rows) - 1), rows[0] if rows else []


def named_refusals(text: str, keys) -> list:
    """Which of *keys* this console actually printed (keys, so a reworded message still counts)."""
    import live_run_harness as harness

    return [key for key in keys if harness.names_key(text, key)]


def export_dir_entries() -> set:
    """The export directory's current names — the baseline a 三一致 check reads before a run starts."""
    from config import Config

    with contextlib.suppress(OSError):
        return {path.name for path in Path(Config.EXPORT_DIR).glob('*')}
    return set()
