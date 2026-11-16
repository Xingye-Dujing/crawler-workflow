"""The account's Python script library: one row per reusable transformation.

The same table feeds two surfaces, which is the point:

- the AI workspace's Python tooling (write, save, run, inspect), and
- the canvas's **Python node**, which resolves a saved script at run time and feeds it the
  upstream rows.

A script is therefore data, not a prompt: it can be reviewed, versioned, forked and reused by a
later run or a different workflow. Built-ins are code (``BUILTIN``) and are forked, never
overwritten — the same rule user skills follow. The execution contract lives in
``services/python_runtime.py``: rows in as JSON Lines, rows out as JSON Lines.
"""

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

from runtime import paths

SCRIPT_ID_RE = re.compile(r'^[a-z][a-z0-9_]{1,63}$')
MAX_CODE_BYTES = 200_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS python_scripts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    code TEXT NOT NULL,
    inputs_json TEXT NOT NULL DEFAULT '[]',
    outputs_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 1,
    builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

#: The shared preamble every built-in uses. A user script may copy it or ignore it; the contract is
#: the environment variables and the two files, not a required import.
_PREAMBLE = """import json, os

def read_rows():
    path = os.environ["CIXI_INPUT"]
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]

def write_rows(rows):
    path = os.environ["CIXI_OUTPUT"]
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\\n")

def args():
    return json.loads(os.environ.get("CIXI_ARGS") or "{}")
"""

BUILTIN = {
    'passthrough': {
        'name': 'Pass-through / project columns',
        'description': (
            'Echoes rows, optionally keeping only the named columns. The smallest example of the node contract.'
        ),
        'inputs': ['rows'],
        'outputs': ['same columns (or the projection)'],
        'tags': ['utility'],
        'code': _PREAMBLE
        + """

def main():
    keep = [str(c) for c in args().get("columns") or [] if str(c)]
    rows = read_rows()
    if keep:
        rows = [{key: row.get(key) for key in keep} for row in rows]
    write_rows(rows)

main()
""",
    },
    'clean_text': {
        'name': 'Clean text column',
        'description': (
            'Generic text cleaning: strip HTML tags, collapse whitespace, optionally lowercase and cut at N chars.'
        ),
        'inputs': ['one text column'],
        'outputs': ['same rows with the text column cleaned'],
        'tags': ['text', 'clean'],
        'code': _PREAMBLE
        + """

import html, re

def main():
    conf = args()
    column = conf.get("column") or "正文"
    lowercase = bool(conf.get("lowercase"))
    limit = int(conf.get("limit") or 0)
    rows = read_rows()
    for row in rows:
        text = str(row.get(column) or "")
        text = re.sub(r"<[^>]+>", " ", html.unescape(text))
        text = re.sub(r"\\s+", " ", text).strip()
        if lowercase:
            text = text.lower()
        if limit > 0:
            text = text[:limit]
        row[column] = text
    write_rows(rows)

main()
""",
    },
    'dedupe': {
        'name': 'Deduplicate by columns',
        'description': (
            'Keeps the first row per key (one or more columns). Order is preserved, so the survivor is explainable.'
        ),
        'inputs': ['one or more key columns'],
        'outputs': ['deduplicated rows'],
        'tags': ['utility', 'dedupe'],
        'code': _PREAMBLE
        + """

def main():
    conf = args()
    keys = [str(c) for c in conf.get("columns") or [] if str(c)]
    if not keys:
        raise SystemExit("dedupe needs args.columns")
    seen = set()
    kept = []
    for row in read_rows():
        marker = tuple(str(row.get(key) or "") for key in keys)
        if marker in seen:
            continue
        seen.add(marker)
        kept.append(row)
    write_rows(kept)

main()
""",
    },
    'groupby': {
        'name': 'Group and aggregate',
        'description': 'Groups rows by columns and computes count/sum/mean/min/max on one value column.',
        'inputs': ['group columns', 'value column'],
        'outputs': ['one row per group'],
        'tags': ['utility', 'stats'],
        'code': _PREAMBLE
        + """

def main():
    conf = args()
    group = [str(c) for c in conf.get("by") or [] if str(c)]
    value = str(conf.get("value") or "")
    how = str(conf.get("how") or "count")
    if not group:
        raise SystemExit("groupby needs args.by")
    buckets = {}
    order = []
    for row in read_rows():
        key = tuple(str(row.get(column) or "") for column in group)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        if value:
            try:
                buckets[key].append(float(row.get(value)))
            except (TypeError, ValueError):
                pass
    out = []
    for key in order:
        numbers = buckets[key]
        if how == "count" or not value:
            answer = len(numbers)
        elif not numbers:
            answer = 0
        elif how == "sum":
            answer = sum(numbers)
        elif how == "mean":
            answer = sum(numbers) / len(numbers)
        elif how == "min":
            answer = min(numbers)
        elif how == "max":
            answer = max(numbers)
        else:
            raise SystemExit("unknown args.how: " + how)
        row = {column: key[index] for index, column in enumerate(group)}
        row[f"{how}_{value}" if value else "rows"] = answer
        out.append(row)
    write_rows(out)

main()
""",
    },
}


def now() -> str:
    return datetime.now(UTC).isoformat()


def _db_path() -> str:
    target = paths.active().python_scripts_db
    os.makedirs(os.path.dirname(target), exist_ok=True)
    return target


@contextmanager
def connect():
    conn = sqlite3.connect(_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row(row) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    for key in ('inputs_json', 'outputs_json', 'tags_json'):
        raw = data.pop(key, '[]')
        try:
            data[key[:-5]] = json.loads(raw) if raw else []
        except ValueError:
            data[key[:-5]] = []
    data['builtin'] = bool(data.get('builtin'))
    return data


def _builtin_rows() -> list:
    out = []
    for script_id, item in BUILTIN.items():
        out.append(
            {
                'id': script_id,
                'name': item['name'],
                'description': item['description'],
                'code': item['code'],
                'inputs': list(item['inputs']),
                'outputs': list(item['outputs']),
                'tags': list(item['tags']),
                'version': 1,
                'builtin': True,
                'created_at': '',
                'updated_at': '',
            }
        )
    return out


def all_scripts() -> list:
    with connect() as conn:
        rows = [_row(row) for row in conn.execute('SELECT * FROM python_scripts ORDER BY name').fetchall()]
    user_ids = {row['id'] for row in rows}
    merged = [row for row in _builtin_rows() if row['id'] not in user_ids]
    return sorted(merged + rows, key=lambda item: (not item['builtin'], item['name'].lower()))


def get_script(script_id: str) -> dict | None:
    key = str(script_id or '').strip()
    if key in BUILTIN:
        for row in _builtin_rows():
            if row['id'] == key:
                return row
    with connect() as conn:
        return _row(conn.execute('SELECT * FROM python_scripts WHERE id = ?', (key,)).fetchone())


def find_script(reference: str) -> dict | None:
    """Resolve an id first, then a case-insensitive name (the node panel stores one or the other)."""
    text = str(reference or '').strip()
    if not text:
        return None
    found = get_script(text)
    if found is not None:
        return found
    lowered = text.lower()
    for row in all_scripts():
        if str(row.get('name') or '').lower() == lowered:
            return row
    return None


def _clean_list(value) -> list:
    if isinstance(value, str):
        value = [part.strip() for part in value.split(',') if part.strip()]
    return [str(item).strip() for item in value or () if str(item).strip()][:50]


def save_script(payload: dict) -> dict:
    from ai.errors import AIError

    data = payload if isinstance(payload, dict) else {}
    script_id = str(data.get('id') or '').strip()
    if not SCRIPT_ID_RE.match(script_id):
        raise AIError('ai.pythonBadId', kind='bad_request', script=script_id or '(empty)')
    if script_id in BUILTIN:
        raise AIError('ai.pythonBuiltin', kind='bad_request', script=script_id)
    name = str(data.get('name') or '').strip()[:80]
    if not name:
        raise AIError('ai.pythonNoName', kind='bad_request', script=script_id)
    code = str(data.get('code') or '')
    if not code.strip():
        raise AIError('ai.pythonNoCode', kind='bad_request', script=script_id)
    if len(code.encode('utf-8')) > MAX_CODE_BYTES:
        raise AIError('ai.pythonTooLarge', kind='bad_request', script=script_id, kb=MAX_CODE_BYTES // 1024)
    stamp = now()
    with connect() as conn:
        existing = conn.execute('SELECT * FROM python_scripts WHERE id = ?', (script_id,)).fetchone()
        version = (int(existing['version']) + 1) if existing is not None else 1

        def keep(key: str, column: str) -> list:
            """A key the caller did not send keeps what the script already had.

            The studio's save sent only id/name/description/code, so every save silently erased
            the tags and column hints a fork or an earlier edit recorded.
            """
            if key in data:
                return _clean_list(data.get(key))
            if existing is None:
                return []
            try:
                parsed = json.loads(existing[column] or '[]')
            except ValueError:
                return []
            return parsed if isinstance(parsed, list) else []

        conn.execute(
            'INSERT INTO python_scripts (id, name, description, code, inputs_json, outputs_json, tags_json, '
            'version, builtin, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?) '
            'ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description, '
            'code=excluded.code, inputs_json=excluded.inputs_json, outputs_json=excluded.outputs_json, '
            'tags_json=excluded.tags_json, version=excluded.version, updated_at=excluded.updated_at',
            (
                script_id,
                name,
                str(data.get('description') or '').strip()[:500],
                code,
                json.dumps(keep('inputs', 'inputs_json'), ensure_ascii=False),
                json.dumps(keep('outputs', 'outputs_json'), ensure_ascii=False),
                json.dumps(keep('tags', 'tags_json'), ensure_ascii=False),
                version,
                stamp,
                stamp,
            ),
        )
    return get_script(script_id)


def delete_script(script_id: str) -> bool:
    from ai.errors import AIError

    key = str(script_id or '').strip()
    if key in BUILTIN:
        raise AIError('ai.pythonBuiltin', kind='bad_request', script=key)
    with connect() as conn:
        cur = conn.execute('DELETE FROM python_scripts WHERE id = ?', (key,))
    return cur.rowcount > 0


def fork_script(script_id: str, new_id: str = '', overwrite: bool = False) -> dict:
    from ai.errors import AIError

    source = get_script(script_id)
    if source is None:
        raise AIError('ai.pythonUnknown', kind='not_found', script=script_id)
    base = (new_id or f'{source["id"]}_mine').strip()
    target = base
    if not overwrite and get_script(target) is not None:
        # A fork is a new artifact: clicking twice must not replace the user's edited copy with a
        # pristine one. The second click gets a free id instead.
        if new_id:
            raise AIError('ai.pythonForkExists', kind='bad_request', script=target)
        suffix = 2
        while get_script(f'{base}{suffix}') is not None:
            suffix += 1
        target = f'{base}{suffix}'
    payload = {
        'id': target,
        'name': f'{source["name"]} (mine)',
        'description': source.get('description') or '',
        'code': source['code'],
        'inputs': source.get('inputs') or [],
        'outputs': source.get('outputs') or [],
        'tags': source.get('tags') or [],
    }
    return save_script(payload)
