"""Run a saved Python script against rows, in the account's own workspace.

This is the execution half of the Python extension surface; ``services.python_scripts`` is the
library. Both the AI tools and the canvas's **Python node** come through here, so "run my script"
means the same thing on either surface.

Contract (deliberately file-based, so a script is a normal program you can run by hand):

- ``CIXI_INPUT``  a JSON Lines file, one object per upstream row.
- ``CIXI_OUTPUT`` where the script writes JSON Lines, one object per output row.
- ``CIXI_ARGS``   a JSON object with the node/tool parameters.
- stdout/stderr are captured for the panel and the console, capped and decoded as UTF-8.

It is **not a sandbox**. A script runs with the account's privileges and can read the account's
files and datasets. That is why the capability is local-only: a cloud host refuses it by name
(``ai.pythonCloud``), and the user must grant ``ai_allow_python`` before any script runs. A
packaged desktop needs a real interpreter; when none exists the status names it and offers the
download path instead of failing on the first run.
"""

import contextlib
import json
import os
import subprocess
import sys
import time
import uuid

from core import machine
from core.config import Config
from core.procs import popen_kwargs
from runtime import paths
from runtime.settings import get_setting

MAX_OUTPUT_ROWS = 200_000
MAX_STDOUT = 20_000
MAX_FILE_BYTES = 2 * 1024 * 1024


def _interpreter_candidates() -> list:
    out = []
    configured = str(get_setting('ai_python_path') or '').strip()
    if configured:
        out.append(configured)
    if not machine.is_frozen():
        out.append(sys.executable)
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        candidate = machine.venv_python(repo)
        if os.path.isfile(candidate):
            out.append(candidate)
    out.extend(machine.python_candidates())
    seen = []
    for item in out:
        if item and item not in seen:
            seen.append(item)
    return seen


def _probe(command: list) -> dict | None:
    try:
        proc = subprocess.run(
            [*command, '-c', 'import sys; print(sys.version.split()[0]); print(sys.executable)'],
            capture_output=True,
            timeout=8,
            check=False,
            **popen_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    lines = proc.stdout.decode('utf-8', 'replace').splitlines()
    if len(lines) < 2:
        return None
    return {'command': command, 'path': lines[-1].strip(), 'version': lines[0].strip()}


_CACHE: dict = {'at': 0.0, 'value': None}


def interpreter(refresh: bool = False) -> dict:
    """Detect a usable interpreter. Cached for a minute; ``refresh`` re-probes."""
    now = time.monotonic()
    if not refresh and _CACHE['value'] is not None and now - _CACHE['at'] < 60:
        return _CACHE['value']
    result = {
        'available': False,
        'path': '',
        'version': '',
        'source': '',
        'reason': 'ai.pythonMissing',
        'downloadable': sys.platform.startswith('win') and machine.is_frozen(),
    }
    for candidate in _interpreter_candidates():
        command = [candidate]
        probed = _probe(command)
        if probed is None and os.path.basename(candidate).lower() in machine.python_launcher_names():
            probed = _probe([candidate, '-3'])
        if probed is None:
            continue
        result.update(
            {
                'available': True,
                'path': probed['path'],
                'version': probed['version'],
                'source': candidate,
                'reason': '',
                'command': probed['command'],
            }
        )
        break
    _CACHE.update({'at': now, 'value': result})
    return result


def workspace() -> str:
    target = paths.active().ensure().python_workspace_dir
    os.makedirs(target, exist_ok=True)
    for child in ('scripts', 'runs'):
        os.makedirs(os.path.join(target, child), exist_ok=True)
    return target


def _safe_path(relative: str) -> str:
    from ai.errors import AIError

    root = os.path.abspath(workspace())
    text = str(relative or '').strip().replace('\\', '/')
    if not text or text.startswith('/') or '..' in text.split('/'):
        raise AIError('ai.pythonPath', kind='bad_request', path=relative)
    target = os.path.abspath(os.path.join(root, *text.split('/')))
    if not target.startswith(root + os.sep):
        raise AIError('ai.pythonPath', kind='bad_request', path=relative)
    return target


def list_files() -> list:
    root = workspace()
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in ('__pycache__', '.runs')]
        for filename in filenames:
            if filename.endswith(('.pyc',)):
                continue
            full = os.path.join(dirpath, filename)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            out.append(
                {
                    'path': os.path.relpath(full, root).replace(os.sep, '/'),
                    'size': size,
                    'modified': int(os.path.getmtime(full)),
                }
            )
    return sorted(out, key=lambda item: item['path'])[:500]


def read_file(relative: str, max_bytes: int = MAX_FILE_BYTES) -> dict:
    from ai.errors import AIError

    target = _safe_path(relative)
    if not os.path.isfile(target):
        raise AIError('ai.pythonPath', kind='not_found', path=relative)
    if os.path.getsize(target) > max_bytes:
        raise AIError('ai.pythonFileLarge', kind='bad_request', path=relative, kb=max_bytes // 1024)
    with open(target, encoding='utf-8', errors='replace') as handle:
        return {'path': relative, 'content': handle.read()}


def write_file(relative: str, content: str) -> dict:
    from ai.errors import AIError

    text = str(content or '')
    if len(text.encode('utf-8')) > MAX_FILE_BYTES:
        raise AIError('ai.pythonFileLarge', kind='bad_request', path=relative, kb=MAX_FILE_BYTES // 1024)
    target = _safe_path(relative)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'w', encoding='utf-8') as handle:
        handle.write(text)
    return {'path': relative, 'size': len(text.encode('utf-8'))}


def delete_file(relative: str) -> bool:
    target = _safe_path(relative)
    if os.path.isfile(target):
        os.remove(target)
        return True
    return False


def _clean_env() -> dict:
    env = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if any(marker in upper for marker in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL')):
            continue
        env[key] = value
    env.pop('PYTHONPATH', None)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


def _decode(data: bytes) -> str:
    return data.decode('utf-8', 'replace')[:MAX_STDOUT]


def run_code(
    code: str,
    rows: list,
    args: dict | None = None,
    *,
    timeout: int = 120,
    cancel_event=None,
    max_rows: int = MAX_OUTPUT_ROWS,
    label: str = 'script',
) -> dict:
    """Run *code* against *rows*; return ``{rows, stdout, stderr, exit_code, duration_ms}``."""
    from ai.errors import AIError

    if Config.CLOUD_MODE:
        raise AIError('ai.pythonCloud', kind='capability')
    if not bool(get_setting('ai_allow_python')):
        raise AIError('ai.pythonDisabled', kind='capability')
    found = interpreter()
    if not found['available']:
        raise AIError('ai.pythonMissing', kind='capability')
    root = workspace()
    run_id = uuid.uuid4().hex[:12]
    run_dir = os.path.join(root, 'runs')
    input_path = os.path.join(run_dir, f'{run_id}.in.jsonl')
    output_path = os.path.join(run_dir, f'{run_id}.out.jsonl')
    script_path = os.path.join(run_dir, f'{run_id}.py')
    with open(input_path, 'w', encoding='utf-8') as handle:
        for row in rows or ():
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
    with open(script_path, 'w', encoding='utf-8') as handle:
        handle.write(str(code or ''))
    env = _clean_env()
    env.update(
        {
            'CIXI_INPUT': input_path,
            'CIXI_OUTPUT': output_path,
            'CIXI_ARGS': json.dumps(args or {}, ensure_ascii=False),
        }
    )
    command = [*found['command'], script_path]
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            command,
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **popen_kwargs(),
        )
        while proc.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                raise AIError('ai.cancelled', kind='cancelled')
            if time.monotonic() - started > max(1, int(timeout)):
                proc.kill()
                raise AIError('ai.pythonTimeout', kind='timeout', seconds=int(timeout))
            time.sleep(0.2)
        stdout, stderr = proc.communicate(timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AIError('ai.pythonMissing', kind='capability', detail=str(exc)[:200]) from exc
    duration = int((time.monotonic() - started) * 1000)
    out_text = _decode(stdout or b'')
    err_text = _decode(stderr or b'')
    if proc.returncode != 0:
        raise AIError('ai.pythonFailed', kind='error', code=proc.returncode, detail=(err_text or out_text)[-800:])
    result_rows = []
    if os.path.isfile(output_path):
        with open(output_path, encoding='utf-8', errors='replace') as handle:
            for index, line in enumerate(handle):
                if index >= max(1, int(max_rows)):
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    raise AIError('ai.pythonOutput', kind='bad_response', label=label, line=index + 1) from None
                result_rows.append(row if isinstance(row, dict) else {'value': row})
    for path in (input_path, output_path, script_path):
        with contextlib.suppress(OSError):
            os.remove(path)
    return {
        'rows': result_rows,
        'stdout': out_text,
        'stderr': err_text,
        'exit_code': proc.returncode,
        'duration_ms': duration,
        'interpreter': found['version'],
    }


def run_script(
    script: dict,
    rows: list,
    args: dict | None = None,
    *,
    timeout: int = 120,
    cancel_event=None,
    max_rows: int = MAX_OUTPUT_ROWS,
) -> dict:
    return run_code(
        str(script.get('code') or ''),
        rows,
        args,
        timeout=timeout,
        cancel_event=cancel_event,
        max_rows=max_rows,
        label=str(script.get('name') or script.get('id') or 'script'),
    )


#: The official embeddable build. Pinned by version so a future URL move is a named failure, not a
#: silent upgrade of the interpreter the user's scripts run on.
PYTHON_EMBED_VERSION = '3.11.9'
PYTHON_EMBED_URL = (
    f'https://www.python.org/ftp/python/{PYTHON_EMBED_VERSION}/python-{PYTHON_EMBED_VERSION}-embed-amd64.zip'
)


def install_plan() -> dict:
    """What a download would do, without doing it. The UI shows this before asking permission."""
    found = interpreter(refresh=True)
    if found['available']:
        return {'available': True, 'needs_permission': False, 'path': found['path'], 'version': found['version']}
    return {
        'available': False,
        'needs_permission': True,
        'supported': sys.platform.startswith('win') and machine.is_frozen(),
        'url': PYTHON_EMBED_URL,
        'version': PYTHON_EMBED_VERSION,
        'target': os.path.join(paths.active().data_dir, 'python'),
    }


def install_interpreter(allow_download: bool) -> dict:
    """Download and unpack the embeddable interpreter after the user said yes.

    Refused by name on anything but a frozen Windows build: a source run already has
    ``sys.executable`` and a macOS/Linux desktop should use the system Python rather than a second
    private copy the user cannot update. Nothing is downloaded until ``allow_download`` is true.
    """
    import io
    import zipfile

    import requests
    from ai.errors import AIError
    from runtime.settings import save_settings

    plan = install_plan()
    if plan['available']:
        return plan
    if not plan['supported']:
        raise AIError('ai.pythonInstallWindows', kind='capability')
    if not allow_download:
        return {**plan, 'downloaded': False}
    target = plan['target']
    os.makedirs(target, exist_ok=True)
    try:
        response = requests.get(PYTHON_EMBED_URL, timeout=(15, 300))
    except requests.RequestException as exc:
        raise AIError('ai.pythonInstallUrl', kind='network', url=PYTHON_EMBED_URL) from exc
    if response.status_code != 200 or len(response.content) < 1_000_000:
        raise AIError('ai.pythonInstallUrl', kind='network', url=PYTHON_EMBED_URL)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        for member in archive.namelist():
            name = os.path.normpath(member)
            if name.startswith('..') or os.path.isabs(name):
                continue
            archive.extract(member, target)
    executable = machine.embedded_python_executable(target)
    if not os.path.isfile(executable):
        raise AIError('ai.pythonInstallUrl', kind='network', url=PYTHON_EMBED_URL)
    save_settings({'ai_python_path': executable})
    result = interpreter(refresh=True)
    return {**result, 'downloaded': True}
