"""Python node: run a saved script over the upstream rows.

This is the canvas half of the same extension surface the AI workspace uses. A script is a row
in the account's ``python_scripts`` library (``services.python_scripts``), and the execution
contract is the one documented in ``services.python_runtime``: JSON Lines in, JSON Lines out.
A workflow and the AI can therefore share one reviewed transformation instead of two copies.

The node does not inline code. Inline code in a canvas would be unreviewable, unversioned and
impossible to reuse; a script id (or name) keeps the workflow a reference to a real artifact, the
same way a dataset node references a dataset by id.
"""

from __future__ import annotations

import json

from core.config import Config
from runtime.state import add_log

from i18n import t
from nodes.context import NodeCall, node_params
from nodes.labels import node_label
from services import python_runtime, python_scripts

NODE_TYPE = 'python'


def _args(params: dict) -> dict:
    raw = params.get('args')
    if isinstance(raw, dict):
        return raw
    text = str(raw or '').strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise RuntimeError(t('ai.pythonArgs', script=params.get('script_id') or params.get('script') or '')) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(t('ai.pythonArgs', script=params.get('script_id') or ''))
    return parsed


def run(node: dict, call: NodeCall) -> list:
    params = node_params(node) or node.get('params') or {}
    label = node_label(node, str(node.get('id') or ''))
    if Config.CLOUD_MODE:
        # A shared host must not execute a user's Python. Refused by name, before any read.
        raise RuntimeError(t('ai.pythonCloud'))
    reference = str(params.get('script_id') or params.get('script') or '').strip()
    script = python_scripts.find_script(reference)
    if script is None:
        raise RuntimeError(t('ai.pythonUnknown', script=reference or '(empty)'))
    result = python_runtime.run_script(
        script,
        call.current_input or [],
        _args(params),
        timeout=int(params.get('timeout') or 120),
        cancel_event=(call.run_ctx or {}).get('cancel_event'),
        max_rows=int(params.get('max_rows') or python_runtime.MAX_OUTPUT_ROWS),
    )
    rows = result['rows']
    add_log(
        t(
            'run.pythonDone',
            nid=label,
            script=script.get('name') or script.get('id'),
            n=len(rows),
            ms=result['duration_ms'],
        )
    )
    if result.get('stderr'):
        # A script's stderr is a fact the user asked for, not a hidden log: one attributed line.
        add_log(t('run.pythonStderr', nid=label, text=result['stderr'][-300:]))
    return rows
