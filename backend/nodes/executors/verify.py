"""采集校验 (collect audit): does the result table hold what the list table promised?

Two tables, two questions:

* **覆盖** — is every key of the list (a post table's 链接, by default) present in the result
  (a comment table's 文章URL)? The comparison is the same one the 内容去重 step uses
  (``services.analysis.matching``), so a link one feature calls "missing" is the link the
  other would still keep.
* **条数** — the list carries the site's own 评论数; the result carries one row per comment.
  A link whose result is shorter than the number it promised is 不完整 even though it was
  covered.

The output is a REPORT TABLE, not a verdict: the list's own columns are preserved (so the
链接 column can be wired straight into a comment crawl's input column) and five columns are
appended (``采集状态``/``期望条数``/``实际条数``/``缺失条数``/``完成度``). A gap is an ANSWER —
the node settles DONE — because failing here would throw away the very table the user needs
to re-crawl the missing links.

Roles are decided by connection ORDER, like the analysis node's two-table steps: the first
wire is the 清单 (what was promised), the second is the 结果 (what was collected). The
console prints both parents by name on every run, and ``swap_tables`` flips them without
rewiring.
"""

from __future__ import annotations

import pandas as pd
from api.http import _safe_int
from core.refs import as_bool
from core.refs import json_safe_records as _json_safe_records
from runtime.state import add_log

from crawlers.engine.counters import has_count, parse_count
from i18n import t
from nodes.context import NodeCall, node_params
from nodes.labels import node_label, parent_label
from services.analysis.matching import COUNT_MODES, key_counts, value_key

NODE_TYPE = 'verify'

#: The report's appended columns. They are a data contract: a downstream chart, a filter or
#: a re-crawl feed reads these names, so renaming one is a breaking change and is pinned by
#: a test rather than left to whichever executor edited last.
COL_STATUS = '采集状态'
COL_EXPECTED = '期望条数'
COL_ACTUAL = '实际条数'
COL_GAP = '缺失条数'
COL_DONE = '完成度'
REPORT_COLUMNS = (COL_STATUS, COL_EXPECTED, COL_ACTUAL, COL_GAP, COL_DONE)

#: The status cell's vocabulary. Data values stay Chinese like every other crawled table's
#: cells (链接, 评论数, 阶段); only console sentences are localized.
STATUS_COMPLETE = '完整'
STATUS_SHORT = '不完整'
STATUS_MISSING = '未采集'
STATUS_OVER = '超出'
STATUS_UNCHECKED = '无法核对'
STATUSES = (STATUS_COMPLETE, STATUS_SHORT, STATUS_MISSING, STATUS_OVER, STATUS_UNCHECKED)

#: The rows worth re-crawling. ``all`` is the audit table; ``gaps`` is the feed.
GAP_STATUSES = frozenset({STATUS_MISSING, STATUS_SHORT})

#: What ``output_mode`` may say: the actionable table, or the full audit.
OUTPUT_MODES = ('gaps', 'all')


def read_columns(node: dict) -> list[str]:
    """The columns the audit will read from its fan-in, so diagnostics can flag a typo.

    Diagnostics compares these against the UNION of both parents (the run's fan-in does not
    tell the static view which wire is which), which is the honest reach of the check: a name
    neither table holds is provably wrong, while a name only the other table holds is a role
    mistake this view cannot see.
    """
    params = node_params(node)
    found = [
        str(params.get('input_key_column') or '').strip(),
        str(params.get('result_key_column') or '').strip(),
        str(params.get('expected_count_column') or '').strip(),
    ]
    return [column for column in found if column]


def _expected_number(value):
    """The site's promised count, or ``None`` when the cell states none.

    Read with the crawler's own counter parser (``万``/``千``/``K``/``M`` and thousands
    separators), so an uploaded file that kept the site's label compares the same way a
    crawled integer does. A blank cell, or one with no digit at all, is NOT zero: zero is a
    real answer ("this post has no comments") and folding the two would make an unreadable
    cell look like a complete crawl of an empty thread.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            return None
        return int(value)
    if not has_count(value):
        return None
    return parse_count(value)


def _columns_of(rows: list) -> set:
    return {str(name) for row in rows if isinstance(row, dict) for name in row}


def _status_entry(actual: int, covered: bool, expected, tolerance: int) -> dict:
    """One row's verdict cells, from the numbers the two tables answered."""
    if not covered:
        status = STATUS_MISSING
        gap = expected if expected is not None else ''
    elif expected is None:
        # Covered, but the list states no number to compare with. Saying “完整” would claim a
        # check that did not happen; “无法核对” names it, and these rows stay out of the gap
        # table (there is nothing extra to crawl — only a count nobody wrote down).
        status = STATUS_UNCHECKED
        gap = ''
    elif actual + tolerance < expected:
        status = STATUS_SHORT
        gap = expected - actual - tolerance
    elif actual > expected:
        # More rows than the site's number: replies the count excludes, a stale count, or a
        # thread that grew after the post was crawled. Not a gap — re-crawling cannot fix it.
        status = STATUS_OVER
        gap = 0
    else:
        status = STATUS_COMPLETE
        gap = 0
    return {
        COL_STATUS: status,
        COL_EXPECTED: expected if expected is not None else '',
        COL_ACTUAL: actual,
        COL_GAP: gap,
        COL_DONE: f'{round(actual / expected * 100, 1)}%' if expected else '',
    }


def execute_verify_node(node: dict, _current_input: list, upstream: list = None, label_of=None):
    """Compare the list table with the result table and return the audit report rows."""
    params = node_params(node)
    nid = str(node.get('id') or '')
    label = node_label(node, nid)
    pairs = [(str(pid), res) for pid, res in (upstream or ())]
    if len(pairs) != 2:
        # Both wires are the feature: one table is the promise, the other is the evidence.
        # Refused BY NAME rather than read as "the first wire is both" — comparing a table
        # with itself would report 100% coverage, the worst possible false green.
        raise ValueError(t('verify.needs_two', nid=label, n=len(pairs)))
    list_rows, result_rows = pairs[0][1], pairs[1][1]
    if not isinstance(list_rows, list) or not isinstance(result_rows, list):
        raise ValueError(t('verify.bad_tables', nid=label))
    swapped = as_bool(params.get('swap_tables'), False)
    if swapped:
        list_rows, result_rows = result_rows, list_rows
    list_parent = parent_label(label_of, pairs[1][0] if swapped else pairs[0][0])
    result_parent = parent_label(label_of, pairs[0][0] if swapped else pairs[1][0])
    add_log(t('verify.roles', nid=label, list=list_parent, result=result_parent))

    if not list_rows:
        add_log(t('verify.empty_list', nid=label, up=list_parent))
        return []

    list_key = str(params.get('input_key_column') or '').strip()
    result_key = str(params.get('result_key_column') or '').strip()
    count_column = str(params.get('expected_count_column') or '').strip()
    mode = str(params.get('match_mode') or 'url').strip().lower()
    output_mode = str(params.get('output_mode') or 'gaps').strip().lower()
    if mode not in COUNT_MODES:
        # ``similar`` is a legitimate 内容去重 mode but cannot answer a per-link COUNT: its
        # grouping is transitive, so "how many comments does this article have" has no
        # answer to give. Refused with the list it does accept.
        raise ValueError(t('verify.bad_mode', nid=label, mode=mode, allowed=', '.join(COUNT_MODES)))
    if output_mode not in OUTPUT_MODES:
        raise ValueError(t('verify.bad_output_mode', nid=label, mode=output_mode, allowed=', '.join(OUTPUT_MODES)))
    if not list_key:
        raise ValueError(t('verify.need_list_col', nid=label))
    if not result_key:
        raise ValueError(t('verify.need_result_col', nid=label))
    list_columns = _columns_of(list_rows)
    result_columns = _columns_of(result_rows)
    if list_key not in list_columns:
        raise ValueError(t('verify.missing_list_col', nid=label, col=list_key, up=list_parent))
    if result_key not in result_columns:
        raise ValueError(t('verify.missing_result_col', nid=label, col=result_key, up=result_parent))
    if count_column and count_column not in list_columns:
        # The count box is optional ON PURPOSE: leave it blank and the node checks coverage
        # only. A name that is typed but absent is a mistake, and the message says which
        # box to clear.
        raise ValueError(t('verify.missing_count_col', nid=label, col=count_column, up=list_parent))

    tolerance = _safe_int(params.get('tolerance'), 0, minimum=0)
    per_link_limit = _safe_int(params.get('per_link_limit'), 0, minimum=0)
    ignore_case = as_bool(params.get('ignore_case'), False)

    actual_counts, result_blank = key_counts(
        [row.get(result_key) for row in result_rows if isinstance(row, dict)], mode, ignore_case
    )

    # One verdict per DISTINCT key, so a link repeated in the list (two keywords, one post)
    # is checked once; every one of its rows still receives the same cells.
    entries: dict[str, dict] = {}
    out_rows: list[dict] = []
    gap_rows = 0
    duplicate_rows = 0
    list_blank = 0
    for row in list_rows:
        row = row if isinstance(row, dict) else {}
        key = value_key(row.get(list_key), mode, ignore_case)
        expected = _expected_number(row.get(count_column)) if count_column else None
        if expected is not None and per_link_limit:
            # The collector may have been told to keep only the first N comments of a link;
            # comparing against the site's full number would then call every link short. The
            # panel tells the user to copy that limit here.
            expected = min(expected, per_link_limit)
        if not key:
            # No identity to look up: reported as 无法核对 (it is neither covered nor proven
            # absent), and kept out of the gap table because there is no link to re-crawl.
            list_blank += 1
            entry = _status_entry(0, False, expected, tolerance)
            entry[COL_STATUS] = STATUS_UNCHECKED
            entry[COL_GAP] = ''
            # No link means no measurable completion: printing 0.0% would read as a real
            # measurement of a row nobody could even identify.
            entry[COL_DONE] = ''
        elif key in entries:
            duplicate_rows += 1
            entry = entries[key]
        else:
            entry = _status_entry(int(actual_counts.get(key, 0)), key in actual_counts, expected, tolerance)
            entries[key] = entry
        report = dict(row)
        report.update(entry)
        needs_recrawl = entry[COL_STATUS] in GAP_STATUSES
        if needs_recrawl:
            gap_rows += 1
        if output_mode == 'all' or needs_recrawl:
            out_rows.append(report)

    statuses = {status: 0 for status in STATUSES}
    for entry in entries.values():
        statuses[entry[COL_STATUS]] = statuses.get(entry[COL_STATUS], 0) + 1
    links = len(entries)
    covered_links = sum(1 for key in entries if key in actual_counts)
    coverage = f'{round(covered_links / links * 100, 1)}%' if links else '—'
    missing = statuses.get(STATUS_MISSING, 0)
    short = statuses.get(STATUS_SHORT, 0)
    short_by = sum(int(entry[COL_GAP] or 0) for entry in entries.values() if entry[COL_STATUS] == STATUS_SHORT)
    unchecked = statuses.get(STATUS_UNCHECKED, 0)
    over = statuses.get(STATUS_OVER, 0)
    add_log(
        t(
            'verify.done',
            nid=label,
            rows=len(list_rows),
            links=links,
            results=len(result_rows),
            covered=covered_links,
            coverage=coverage,
            missing=missing,
            short=short,
            short_by=short_by,
            over=over,
            unchecked=unchecked,
            out=len(out_rows),
        )
    )
    if gap_rows:
        add_log(t('verify.retry_hint', nid=label, n=gap_rows))
    else:
        add_log(t('verify.all_ok', nid=label))
    if duplicate_rows:
        add_log(t('verify.duplicate_links', nid=label, n=duplicate_rows))
    if list_blank:
        add_log(t('verify.list_blank', nid=label, n=list_blank))
    if result_blank:
        add_log(t('verify.result_blank', nid=label, n=result_blank))
    if count_column and unchecked:
        add_log(t('verify.count_unreadable', nid=label, n=unchecked, col=count_column))
    orphans = len(actual_counts.keys() - entries.keys())
    if orphans:
        # A result row whose key is in no list row is not a gap in THIS list — it is evidence
        # that the two tables may not belong together (the wrong result file, another batch).
        # Said out loud rather than folded into the numbers above.
        add_log(t('verify.orphans', nid=label, n=orphans))
    return _json_safe_records(pd.DataFrame(out_rows)) if out_rows else []


def run(node: dict, call: NodeCall):
    return execute_verify_node(
        node,
        call.current_input,
        upstream=call.upstream,
        label_of=call.label_of,
    )
