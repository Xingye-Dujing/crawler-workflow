"""CatBus as the app's second crawl backend: one subprocess boundary, one source of truth.

Three facts give this file its shape:

- CatBus is Node-only, and the adapter that lives inside it already speaks 采析绘's row contract
  (JSONL rows on stdout, one summary envelope on stderr, exit codes that classify the failure). The
  boundary is therefore a command line, not a ported crawler — see ``docs/crawler-workflow.md`` in
  the CatBus repository.
- **What is supported is never copied into a Python table.** The 平台 × 模式 matrix is read out of
  the adapter itself (:func:`probe`), so a CatBus upgrade cannot leave this side believing a
  combination still works. A second opinion here is exactly the drift the frontend rule forbids.
- Everything that can go wrong goes wrong **BY NAME**: no Node, no adapter, an old Node, an answer
  this side cannot read, a login the adapter does not have. None of them is allowed to arrive as an
  empty table, because an empty table is what a node settles DONE on.

The Selenium path is untouched: this module is only ever consulted when a node asks for
``backend == 'catbus'``, and CatBus keeps its own account files — a Selenium cookie is never handed
to it and never read from here.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass, field

from config import Config
from i18n import t
from utils import machine_deps, procs

BACKEND_NAME = 'catbus'

#: Suffixes that mean "this entry is a script, so Node runs it". Anything else is the program
# itself, which is how a user pointing ``CATBUS_CLI`` at a wrapper stays honoured. The same tuple
# decides how :mod:`utils.machine_deps` tests the file on disk, so a non-executable ``cli.js`` is not
# reported as missing on a POSIX box that has it.
_SCRIPT_SUFFIXES = machine_deps.CATBUS_SCRIPT_SUFFIXES

#: One process gets this long before it is taken down. Finite on purpose: one run slot cannot
# survive a "wait forever", and 停止 stays the user's exit at any point inside the window.
#: A comments crawl runs one process per link, so this bounds one article, not a whole node.
RUN_TIMEOUT = 900

#: A capability probe costs one short-lived Node process; it is re-asked at most this often.
PROBE_TTL = 300.0

#: Only these two manifest states may be crawled; anything else is refused with its own reason.
_RUNNABLE_STATES = ('available', 'partial')

#: The four outcomes the adapter's own summary is allowed to report. Anything else — including a
# missing summary — is this side's ``error``, never a silently accepted blank.
_SUMMARY_STATES = ('ok', 'partial', 'blocked', 'dead')

_LOCK = threading.Lock()
_PROBE: Probe | None = None
_PROBE_AT = 0.0

#: Every adapter process running right now, keyed by the caller's token. 停止 is raised on the
# run-control thread while the worker sits inside :func:`run` reading a child's stdout, and a
# blocking read cannot be interrupted by an ``abort`` predicate between rows — a child that stalls
# mid-crawl would keep the run slot (and the site) busy until the deadline. A token lets the
# stopping thread aim the reaper at exactly this caller's process, the way the browser path aims it
# at exactly this session's driver.
_ACTIVE: dict[str, subprocess.Popen] = {}
_ACTIVE_LOCK = threading.Lock()


def kill_running(token: str) -> bool:
    """Reap whatever process ``token`` is running now. False when it has none (the honest answer)."""
    with _ACTIVE_LOCK:
        proc = _ACTIVE.get(str(token))
    if proc is None:
        return False
    _reap(proc)
    return True


# ─── Probe: what this machine can actually do ────────────────────────────────────────────────


@dataclass(frozen=True)
class Probe:
    """The discovery verdict, cached so a page load does not spawn Node per canvas.

    ``reason_key`` is a catalogue key, never a sentence: the caller renders it in the language of
    whoever asked, and the machine facts (which paths were looked at) stay in this object.
    """

    available: bool
    reason_key: str = ''
    reason_params: dict = field(default_factory=dict)
    node: str = ''
    entry: str = ''
    node_version: str = ''
    manifest: dict = field(default_factory=dict)

    @property
    def platforms(self) -> tuple[str, ...]:
        return tuple((self.manifest.get('platforms') or {}).keys())

    def mode(self, platform: str, mode: str) -> dict:
        """The manifest entry for one 平台 × 模式, or ``{}`` when the adapter does not list it."""
        entry = (self.manifest.get('platforms') or {}).get(str(platform or '').strip().lower()) or {}
        return (entry.get('modes') or {}).get(str(mode or '').strip().lower()) or {}


def explicit_paths() -> tuple[str, str]:
    """The two hand-written paths, settings panel first and environment second.

    The panel wins because that is where the user just typed it, and the setting is what survives a
    restart of a service whose environment nobody controls (a systemd unit, a container). An empty
    setting means "look it up on this machine", not "nothing is configured" — the candidate tables in
    :mod:`utils.machine_deps` answer that, and ``PATH`` is only the last fallback there, never a thing
    the user is asked to edit.
    """
    # Imported here rather than at module scope: ``settings_store`` reads ``Config``, and this module
    # is read by the capabilities endpoint at import time on a cold start.
    from settings_store import get_setting

    node = str(get_setting('catbus_node') or '').strip() or str(Config.CATBUS_NODE or '').strip()
    cli = str(get_setting('catbus_cli') or '').strip() or str(Config.CATBUS_CLI or '').strip()
    return node, cli


def _probe_now() -> Probe:
    """Ask the machine, then ask the adapter. Every negative answer names itself.

    The order is cost-ordered: a missing Node is answered without spawning anything, and a missing
    adapter entry the same way, because a cloud box that installed neither is the common case.
    """
    node_setting, cli_setting = explicit_paths()
    node = machine_deps.find_node(node_setting)
    if not node:
        return Probe(available=False, reason_key='catbus.noNode')
    # The runtime answers for itself: ``node --version`` is what the version gate is about, and
    # asking the adapter would confuse "no CatBus" with "the Node under it is too old".
    check = _call([node, '--version'], capture=True, timeout=30)
    node_version = check.stdout.strip()
    if check.spawn_error or not machine_deps.node_version_supported(node_version):
        return Probe(
            available=False,
            reason_key='catbus.oldNode',
            reason_params={'version': node_version or check.spawn_error or '?', 'node': node},
            node=node,
            node_version=node_version,
        )
    entry = machine_deps.find_catbus_cli(cli_setting)
    if not entry:
        return Probe(available=False, reason_key='catbus.noCli', node=node, node_version=node_version)
    call = _call(argv_for(node, entry, ['capabilities']), capture=True)
    if call.spawn_error or call.code != 0:
        return Probe(
            available=False,
            reason_key='catbus.probeFailed',
            reason_params={'detail': _reason_of(call)},
            node=node,
            entry=entry,
            node_version=node_version,
        )
    try:
        manifest = json.loads(call.stdout)
    except (ValueError, TypeError):
        return Probe(
            available=False,
            reason_key='catbus.probeUnreadable',
            reason_params={'detail': (call.stderr or call.stdout)[:200]},
            node=node,
            entry=entry,
            node_version=node_version,
        )
    return Probe(
        available=True,
        node=node,
        entry=entry,
        node_version=node_version,
        manifest=manifest if isinstance(manifest, dict) else {},
    )


def probe(force: bool = False) -> Probe:
    """The cached discovery verdict. ``force`` is what a settings write or a manual re-check uses."""
    global _PROBE, _PROBE_AT
    with _LOCK:
        if force or _PROBE is None or (time.monotonic() - _PROBE_AT) > PROBE_TTL:
            _PROBE = _probe_now()
            _PROBE_AT = time.monotonic()
        return _PROBE


def reset_probe_cache() -> None:
    """Drop the cached verdict. Tests and a changed ``CATBUS_CLI`` both need the next ask to be real."""
    global _PROBE, _PROBE_AT
    with _LOCK:
        _PROBE = None
        _PROBE_AT = 0.0


def available() -> bool:
    """Whether this machine can crawl through CatBus at all.

    One answer, asked of the server, so the front end neither keeps its own opinion nor offers a
    backend it has no way to run (AGENTS: a capability that cannot exist refuses by name, and its
    entry disappears).
    """
    return probe().available


def mode_state(platform: str, mode: str) -> tuple[str, str]:
    """``(status, reason)`` for one 平台 × 模式 as the adapter itself reports it.

    An unlisted combination is ``('unavailable', ...)`` with a reason that says the adapter does not
    list it — the absence is reported as itself, never folded into a default ``planned``.
    """
    info = probe()
    if not info.available:
        return ('unavailable', t(info.reason_key, **info.reason_params))
    entry = info.mode(platform, mode)
    if not entry:
        return ('unavailable', t('catbus.notInManifest', platform=platform, mode=mode))
    return (str(entry.get('status') or ''), str(entry.get('reason') or ''))


def crawlability(platform: str, mode: str) -> tuple[bool, str]:
    """Whether this cell may be crawled, and the manifest's own reason when it may not.

    The verdict and its sentence are one answer on purpose: a caller that tests the status and then
    rebuilds the message asks the manifest twice, and the two asks can be served by different states
    (a re-probe mid-refusal) — the reason printed would then not belong to the state refused on.
    """
    state, why = mode_state(platform, mode)
    return state in _RUNNABLE_STATES, why


def supports(platform: str, mode: str) -> bool:
    """Whether CatBus may crawl this combination — the only gate the dispatcher asks."""
    return crawlability(platform, mode)[0]


#: Why the backend is missing, in words the PANEL can print. The console keys above carry the machine
# facts (which Node, which path, what the child said) and are rendered with those parameters; a select
# option has no room for a path, so the server names a second, parameter-free key for it. The browser
# translates the key it is handed — it never decides which word fits which absence.
_PANEL_KEYS = {
    'catbus.noNode': 'settings.backendNoNode',
    'catbus.noCli': 'settings.backendNoCli',
    'catbus.oldNode': 'settings.backendOldNode',
    'catbus.probeFailed': 'settings.backendProbeFailed',
    'catbus.probeUnreadable': 'settings.backendProbeFailed',
}


def status_payload() -> dict:
    """What this machine can crawl through CatBus, as language-free data.

    This is the payload half of ``GET /api/capabilities``. ``reasonKey`` and ``panelKey`` are catalogue
    keys, and each cell carries the adapter's status token plus two answers derived HERE rather than in
    the browser: ``runnable`` (so the panel never keeps its own copy of which states crawl) and
    ``auth`` (so the run gate asks the login question of the backend the node is about to use, instead
    of assuming the Selenium matrix's answer for a crawl that reads no cookie of ours).

    Nothing travels as a sentence: the canvas translates a key, and an unknown one shows as itself. Each
    cell also carries the adapter's own ``reason`` (prose, in CatBus' language) because the three-dimensional
    panel lists a mode an engine cannot run and must say why — the generic ``settings.backendNoCell`` is the
    fallback when the adapter gave no sentence, never a replacement for one it did give.

    The map is the adapter's, never a list kept here: a cell CatBus stops supporting disappears from the
    panel on the next probe rather than needing a change on this side.
    """
    info = probe()
    cells: dict[str, dict] = {}
    for platform, entry in (info.manifest.get('platforms') or {}).items():
        for mode, mode_entry in (entry.get('modes') or {}).items():
            state = str((mode_entry or {}).get('status') or '')
            cells[f'{platform}.{mode}'] = {
                'status': state,
                'runnable': state in _RUNNABLE_STATES,
                'auth': str((mode_entry or {}).get('auth') or 'required'),
                'reason': str((mode_entry or {}).get('reason') or (mode_entry or {}).get('note') or ''),
            }
    return {
        'available': info.available,
        'reasonKey': info.reason_key,
        'panelKey': _PANEL_KEYS.get(info.reason_key, 'settings.backendProbeFailed') if not info.available else '',
        'cells': cells,
    }


def manifest_platforms() -> dict:
    """The adapter's platform entries (label, modes, columns, params), or ``{}`` when unavailable.

    One accessor so the capability layer never reaches into a probe object: the manifest is the adapter's
    own answer, and the Python matrix must read it rather than keep a second list of what CatBus can do.
    """
    info = probe()
    return dict(info.manifest.get('platforms') or {}) if info.available else {}


def manifest_mode(platform: str, mode: str) -> dict:
    """One mode's full manifest entry (columns, params, args, optional, paged, handler), or ``{}``."""
    return dict(probe().mode(platform, mode) or {}) if probe().available else {}


def cell(platform: str, mode: str) -> dict:
    """One cell's manifest entry, or ``{}`` when the adapter does not list it at all."""
    return dict(probe().mode(platform, mode) or {})


def needs_session(platform: str, mode: str) -> bool:
    """Whether a CatBus crawl of this cell wants a login, per the adapter's own declaration.

    The Selenium matrix answers a different question about a different tool (weibo's 热搜 is anonymous,
    微信 has no session to want), so neither list may stand in for the other — the gate asks each.
    """
    return str(cell(platform, mode).get('auth') or 'required') == 'required'


def columns_for(platform: str, mode: str) -> tuple[str, ...]:
    """The declared output columns, which are the row contract this backend must satisfy."""
    return tuple(probe().mode(platform, mode).get('columns') or ())


def identity_for(platform: str, mode: str) -> tuple[str, ...]:
    """The columns the adapter says make a row *this* site's identity, in its own order.

    Read out of the manifest rather than guessed from the row: a comment's identity is (平台, 评论ID)
    and a video's is its link, and the two answer different questions — the ledger keys a row by the
    first pair, the cross-run watermark needs the second. A backend that declares no identity leaves
    both callers with an empty tuple, which they report rather than fill in with a column nobody
    promised: this is the shape a new platform lights up without any change on this side.
    """
    return tuple(probe().mode(platform, mode).get('identity') or ())


def declared_params(platform: str, mode: str) -> tuple[str, ...]:
    """The parameter names this cell's adapter actually consumes, in the manifest's own words.

    The adapter keeps unknown keys on purpose (it is shared with other callers), so a stored data
    condition it does not consume would run as if it had. Validation asks this list when deciding
    whether a time window, a comment preview or a board was silently ignored.
    """
    return tuple(str(name) for name in (probe().mode(platform, mode).get('params') or ()))


# ─── Command shape ────────────────────────────────────────────────────────────────────────────


def argv_for(node: str, entry: str, args: list[str]) -> list[str]:
    """The argv: a script runs on Node, anything else is called directly.

    The same rule the adapter applies to its own ``--catbus-bin``, kept on this side as a pure
    function so a Linux or macOS answer can be asserted from Windows without a runtime there.
    """
    entry = str(entry or '').strip()
    if entry.lower().endswith(_SCRIPT_SUFFIXES):
        return [str(node), entry, *args]
    return [entry, *args]


def _params_payload(params: dict, account: str) -> dict:
    """The JSON handed to ``--params -``.

    It goes over a pipe rather than argv on purpose: a keyword or a URL list on Windows would
    otherwise be encoded by the console's code page, and a long link list passes the length limit of
    a command line. CatBus' own account is the only account read here — the node's ``account`` is a
    Selenium session and never reaches this payload.
    """
    payload = dict(params or {})
    payload.pop('account', None)
    if account:
        payload['catbus_account'] = account
    return payload


# ─── The subprocess ──────────────────────────────────────────────────────────────────────────


@dataclass
class _Call:
    code: int = 1
    stdout: str = ''
    stderr: str = ''
    timed_out: bool = False
    stopped: bool = False
    spawn_error: str = ''


def _reap(proc: subprocess.Popen) -> None:
    """Take the whole process tree down, on whichever system this is.

    ``proc.kill()`` ends only the Node this side started, and the adapter starts a second Node for
    the platform command: a bare kill leaves a crawler running against the site after the user
    pressed 停止. The reaper knows the per-OS answer (a tree on Windows and Linux, the direct child
    on macOS, which has no ``/proc`` to walk), so this side asks for it before the plain kill.
    """
    if proc.poll() is not None:
        return
    procs.reap_process(proc.pid)
    if proc.poll() is None:
        proc.kill()


def _call(
    argv: list[str],
    *,
    stdin_text: str | None = None,
    on_line=None,
    timeout: float | None = None,
    abort=None,
    capture: bool = False,
    token: str = '',
) -> _Call:
    """Run one adapter command. stdout is read line by line as it arrives; stderr is drained whole.

    Every byte is decoded here instead of trusting a locale: a Chinese keyword is UTF-8 in the
    adapter's stdout on all three systems, and a cp936 console would mangle it into a row that
    parses as something else.
    """
    out = _Call()
    deadline = RUN_TIMEOUT if timeout is None else float(timeout)
    try:
        with subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **procs.popen_kwargs(),
        ) as proc:
            _drive(
                proc,
                out,
                deadline=deadline,
                stdin_text=stdin_text,
                on_line=on_line,
                abort=abort,
                capture=capture,
                token=token,
            )
    except (OSError, ValueError) as exc:
        out.code = -1
        out.spawn_error = str(exc)
    return out


def _drive(
    proc: subprocess.Popen,
    out: _Call,
    *,
    deadline: float,
    stdin_text: str | None,
    on_line,
    abort,
    capture: bool,
    token: str = '',
) -> None:
    """Talk to one running adapter process, and never leave it running.

    stderr gets its own thread: the adapter writes logs there, and a parent that only reads stdout
    would fill the pipe buffer and stall a child that is still producing rows. The deadline is a
    timer rather than a poll, because the blocking read is the thing that has to be interrupted.
    """
    if token:
        with _ACTIVE_LOCK:
            _ACTIVE[token] = proc
    stderr: list[str] = []

    def _drain() -> None:
        try:
            blob = proc.stderr.read() if proc.stderr else b''
            stderr.append(blob.decode('utf-8', errors='replace'))
        except (OSError, ValueError):
            stderr.append('')

    watcher = threading.Thread(target=_drain, daemon=True)
    watcher.start()

    killed: list[str] = []

    def _kill(why: str) -> None:
        if not killed:
            killed.append(why)
            _reap(proc)

    timer = threading.Timer(max(deadline, 1.0), lambda: _kill('timeout'))
    timer.daemon = True
    timer.start()
    try:
        if stdin_text is not None and proc.stdin:
            proc.stdin.write(stdin_text.encode('utf-8'))
            proc.stdin.close()
        if on_line is not None and proc.stdout:
            for raw in proc.stdout:
                # Delivered first, then asked. The line has already been bought from the site, so a
                # stop that dropped it would throw away a row to be punctual about the interrupt.
                line = raw.decode('utf-8', errors='replace').strip()
                if line:
                    on_line(line)
                if abort is not None and abort():
                    _kill('stopped')
                    break
        elif capture and proc.stdout:
            out.stdout = proc.stdout.read().decode('utf-8', errors='replace')
        out.code = proc.wait()
    except (OSError, ValueError) as exc:
        out.code = -1
        out.spawn_error = str(exc)
    finally:
        timer.cancel()
        if proc.poll() is None:
            _reap(proc)
        if token:
            with _ACTIVE_LOCK:
                if _ACTIVE.get(token) is proc:
                    _ACTIVE.pop(token, None)
        watcher.join(5.0)
        out.timed_out = 'timeout' in killed
        out.stopped = 'stopped' in killed
        out.stderr = ''.join(stderr)


def _reason_of(call: _Call) -> str:
    """One line saying what the process actually did, for a refusal that has no envelope to read."""
    if call.spawn_error:
        return call.spawn_error
    if call.timed_out:
        return t('catbus.timeout', seconds=int(RUN_TIMEOUT))
    text = (call.stderr or call.stdout or '').strip().splitlines()
    return text[-1][:200] if text else f'exit={call.code}'


def _summary_of(call: _Call) -> dict | None:
    """The adapter's summary envelope: the last JSON object on stderr."""
    for line in reversed((call.stderr or '').strip().splitlines()):
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and parsed.get('backend') == BACKEND_NAME:
            return parsed
    return None


# ─── preflight: CatBus' own login state ──────────────────────────────────────────────────────


def preflight(platform: str, account: str = '') -> dict:
    """Ask CatBus whether *it* is logged in. Selenium cookies are never read or offered here.

    The adapter's own verdict object is returned when it can be read; every other outcome is
    translated into the same shape with ``logged_in`` false and a message that names what is missing,
    because a run gate that cannot tell 「not logged in」 from 「cannot ask」 must not block.
    """
    info = probe()
    if not info.available:
        return {
            'available': False,
            'logged_in': False,
            'verdict': 'unverifiable',
            'message': t(info.reason_key, **info.reason_params),
            'hint': '',
            'account': account or None,
        }
    args = ['preflight', '--platform', str(platform)]
    if account:
        args += ['--account', account]
    call = _call(argv_for(info.node, info.entry, args), capture=True, timeout=120)
    if call.spawn_error or not call.stdout.strip():
        return {
            'available': True,
            'logged_in': False,
            'verdict': 'unverifiable',
            'message': _reason_of(call),
            'hint': '',
            'account': account or None,
        }
    try:
        verdict = json.loads(call.stdout)
    except ValueError:
        return {
            'available': True,
            'logged_in': False,
            'verdict': 'unverifiable',
            'message': t('catbus.probeUnreadable', detail=call.stdout[:200]),
            'hint': '',
            'account': account or None,
        }
    error = verdict.get('error') or {}
    return {
        'available': True,
        'logged_in': bool(verdict.get('logged_in')),
        'verdict': 'valid' if verdict.get('logged_in') else 'expired',
        'message': str(error.get('message') or ''),
        'hint': str(error.get('hint') or ''),
        'account': verdict.get('account') or (account or None),
        'user': verdict.get('user'),
        'method': verdict.get('method'),
        'expires_at': verdict.get('expires_at'),
    }


# ─── run ─────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Article:
    """What the adapter proved about one input link. Comments mode is the only one that fills it."""

    url: str
    status: str
    rows: int
    error: dict | None = None


@dataclass(frozen=True)
class Outcome:
    """One adapter run: how it ended, and every row it got out before that.

    ``status`` keeps the adapter's own words (``ok`` / ``partial`` / ``blocked`` / ``dead`` /
    ``error``) and adds two this side can produce and the adapter cannot: ``stopped`` (the user
    pressed 停止) and ``unavailable`` (this machine has no backend). Rows already read are handed to
    ``on_row`` as they arrive, so a stopped or failed run keeps what landed.
    """

    status: str
    rows: int
    warnings: tuple[str, ...] = ()
    articles: tuple[Article, ...] = ()
    error: dict | None = None
    exit_code: int = 0
    message: str = ''
    hint: str = ''


def _as_article(entry: dict) -> Article:
    return Article(
        url=str(entry.get('url') or ''),
        status=str(entry.get('status') or 'error'),
        rows=int(entry.get('rows') or 0),
        error=entry.get('error') if isinstance(entry.get('error'), dict) else None,
    )


def run(
    platform: str,
    mode: str,
    params: dict,
    *,
    on_row=None,
    abort=None,
    account: str = '',
    timeout: float | None = None,
    token: str = '',
) -> Outcome:
    """Crawl one 平台 × 模式 through CatBus, streaming rows into ``on_row``.

    A refusal never returns an empty table: ``on_row`` is only ever called with a row the adapter
    produced, and every failure path carries the code and hint the adapter printed. ``token`` lets
    the caller's 停止 aim the reaper at this exact process (see :func:`kill_running`).
    """
    info = probe()
    if not info.available:
        return Outcome(status='unavailable', rows=0, message=t(info.reason_key, **info.reason_params))
    status, reason = mode_state(platform, mode)
    if status not in _RUNNABLE_STATES:
        return Outcome(
            status='error',
            rows=0,
            message=reason or t('catbus.notInManifest', platform=platform, mode=mode),
        )
    argv = argv_for(info.node, info.entry, ['run', '--platform', str(platform), '--mode', str(mode), '--params', '-'])
    payload = json.dumps(_params_payload(params, account), ensure_ascii=False)
    declared = columns_for(platform, mode)
    rows = 0
    drift: list[str] = []

    def _consume(line: str) -> None:
        nonlocal rows
        try:
            row = json.loads(line)
        except ValueError:
            drift.append(line[:160])
            return
        if not isinstance(row, dict):
            drift.append(line[:160])
            return
        if declared:
            missing = [name for name in declared if name not in row]
            extra = [str(key) for key in row if str(key) not in declared]
            if missing or extra:
                # A row whose columns moved is a CatBus upgrade that changed the contract, not a row
                # to file: the charts downstream read these names, and a renamed column there is an
                # empty figure nobody can explain.
                drift.append(t('catbus.columnDrift', missing='、'.join(missing) or '—', extra='、'.join(extra) or '—'))
                return
        rows += 1
        if on_row is not None:
            on_row(row)

    call = _call(argv, stdin_text=payload, on_line=_consume, abort=abort, timeout=timeout, token=token)
    if drift:
        return Outcome(status='error', rows=rows, exit_code=call.code, message=drift[0])
    summary = _summary_of(call)
    articles = tuple(_as_article(item) for item in (summary or {}).get('articles') or [] if isinstance(item, dict))
    warnings = tuple(str(item) for item in (summary or {}).get('warnings') or [])
    error = summary.get('error') if isinstance((summary or {}).get('error'), dict) else None
    message = str((error or {}).get('message') or '')
    hint = str((error or {}).get('hint') or '')
    state = str((summary or {}).get('status') or '')
    if call.stopped:
        return Outcome(
            status='stopped',
            rows=rows,
            warnings=warnings,
            articles=articles,
            error=error,
            exit_code=call.code,
            message=t('catbus.stopped', platform=platform, mode=mode),
        )
    if state in _SUMMARY_STATES:
        return Outcome(
            status=state,
            rows=rows,
            warnings=warnings,
            articles=articles,
            error=error,
            exit_code=call.code,
            message=message,
            hint=hint,
        )
    # Nothing usable came back: the process died, timed out, or printed something that is not this
    # contract. Say which, and never let it read as "the site had nothing".
    return Outcome(
        status='error',
        rows=rows,
        warnings=warnings,
        articles=articles,
        error=error,
        exit_code=call.code,
        message=message or _reason_of(call),
        hint=hint,
    )
