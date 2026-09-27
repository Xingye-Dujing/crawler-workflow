"""Plumbing for the *run-level* live tier: a real crawl driven the way the user drives one.

The live tier used to own exactly one driving style — build a crawler with
:func:`tests.live_site.conftest.live_crawler` and call its method. That covers what a
*site* answers, and nothing else: the run record, the console the user reads, the
``继续`` banner, 停止, the cookie-death path and the serial/parallel split all live one
layer up, behind ``POST /api/workflow/execute``. This module is the harness for that
layer, written platform-first rather than zhihu-first so the next platform's matrix
copies it instead of re-deriving it.

Four rules shape everything below, and each one exists because a cheaper version was
already refused elsewhere in the suite:

* **No sentence is ever pasted.** :func:`resolve` renders an i18n key in *both*
  languages, so a case asserts on what the catalogue says rather than on a copy that rots
  the day a message is reworded (AGENTS: assert on the reason, never on a pasted line).
* **The console is read, not sampled.** ``/api/workflow/status`` ships only the last 200
  lines plus a running total, so :class:`ConsoleRecorder` keeps a cursor on that total and
  folds the window on every poll — each line exactly once, with an overflow flag when the
  gap was wider than the window. A case that grepped ``logs`` once would read 200 lines of
  a 900-line crawl and call the missing 700 evidence of nothing.
* **The outcome is judged by what the console names.** :func:`classify_verdict` answers
  FULL / NAMED_SHORT / SILENT_SHORT: under target is fine when the site said why, and is
  a bug when it said nothing — the same rule AGENTS states for a refusal: name it or fail.
* **Every case leaves an artifact.** :func:`audit_dump` writes the whole console plus one
  CSV row into ``scratchpad/live_audit/`` (gitignored), because a live red that can only be
  re-read by spending the account again is not evidence, and the closure run is judged on
  those dumps. One directory per pass, so re-running the matrix compares against the previous
  pass instead of overwriting the transcript a red was root-caused from.

* **A case that dies must kill its run.** :func:`abort_run` is what :class:`LiveRun.__exit__`
  calls when an assertion failed mid-crawl. A leaked worker holds the platform's lane and the
  profile directory for the *next* case, and keeps narrating into the *next* case's console —
  which can hand a stranger's 「没有更多了」 to a verdict and grade a real under-collection as
  legitimate. That is a false green in the one tier that exists to catch false greens.

``app`` is never imported at module level: collection beats every fixture, and ``app.py``
freezes ``data/`` paths into singletons at its own import (``tests/unit/test_test_tiers.py``
refuses it). Anything that needs the module takes it as an argument.
"""

import contextlib
import csv
import logging
import re
import threading
import time
from pathlib import Path

import real_paths
from run_wait import describe_state, run_finished

import crawl_capabilities
import i18n
from config import Config

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The jar the user actually saved, and the answer to "does it hold a session" — both owned by
#: :mod:`tests.real_paths`, which the live tier's own conftest imports too. Two copies of a
#: storage path is how the tier ends up disagreeing with itself about whether anybody is
#: logged in, and the run-level cases would crawl anonymous while the crawler-level ones skipped.
COOKIE_DIR = real_paths.COOKIE_DIR

#: Where a live case's evidence lands. Deliberately ``scratchpad/`` and not ``data/``:
#: the session-finish guard fails the whole run if ``data/`` gains a byte, so an audit
#: written there would make the tier red for having written its report.
AUDIT_ROOT = REPO_ROOT / 'scratchpad' / 'live_audit'

#: One identifier per *pass* of the tier, decided when this module is first imported.
#: ``verdicts.csv`` is append-only across passes — that is what makes it a history a closure
#: run can compare against — and a timestamp per row is the only thing that keeps a second
#: pass from being unreadable. Transcripts go into a directory of their own for the same
#: reason: the evidence a previous red was root-caused from must survive the next run.
PASS_ID = time.strftime('%Y%m%d-%H%M%S')

#: The param that chooses a mode, and the column a link feed is taken from. Both come from
#: the crawl matrix rather than from a copy here: the matrix is the only answer to what a
#: platform's node means, and a second opinion in a test helper is how the two drift apart.
MODE_KEY = crawl_capabilities.MODE_KEY
LINK_COLUMN = '链接'

#: How many console lines one status poll carries.
CONSOLE_WINDOW = 200

#: The record's own terminal verdicts, as ``/api/workflow/status`` writes them. An empty
#: outcome means "still deciding" and is the only reason to keep watching; ``rejected`` is
#: terminal because nothing will ever be written after it — the case reads the refusal back
#: rather than spending its budget on a run that never started.
OUTCOMES = ('completed', 'failed', 'interrupted', 'rejected')

# ─── verdicts ───────────────────────────────────────────────────────────

#: The crawl reached the number the user asked for.
FULL = 'FULL'
#: Short of it, and the console says which legitimate exit the site answered with.
NAMED_SHORT = 'NAMED_SHORT'
#: Short of it with no reason named. The one verdict a live case may never accept.
SILENT_SHORT = 'SILENT_SHORT'

#: Exits any platform can reach, because the executor or the shared comment engine prints
#: them. A platform adds its own site-shaped exits (``crawl.<platform>.no_more`` and
#: friends) to this tuple at the call site — a helper that hard-coded one platform's
#: vocabulary would quietly grade every other platform's short crawls as silent.
#:
#: ``crawl.stopped`` deliberately is NOT here, and neither is any other sentence the code
#: never prints: the token the Stop carries is the *message of* ``CrawlerStopped``, and
#: ``_settle_node_as_stopped`` drops it (the node has one true line, ``run.nodeStopped``).
#: A dead entry in a closed whitelist is how the next platform's author concludes that
#: stopping is graded when it is graded by ``run.nodeStopped`` alone.
SHARED_EXITS = (
    'run.cookieExpired',
    'run.dedupe_skipped',
    'run.dedupe_all_skipped',
    'run.nodeStopped',
    'crawl.loginWall',
    'crawl.riskBlocked',
)


# ─── real cookie jar ────────────────────────────────────────────────────


def has_cookie(platform: str, account: str = '') -> bool:
    """Does the user's own jar hold a saved session for *platform*?

    :func:`tests.real_paths.has_cookie`, asked once and shared with the live tier's conftest:
    the product's own loader decides what a session is, so a named-account jar cannot be a
    login to one file and a blank slate to another.

    Never a way of avoiding a failure — the run-level live files take no skips — this only
    records *why* a crawl was refused, in the audit row, where a human reads it back without
    crawling again.
    """
    return real_paths.has_cookie(platform, account)


def real_jar(monkeypatch, module=None) -> str:
    """Point the application at the sessions the user actually saved.

    Two attributes, because the path is captured twice: ``Config.COOKIE_DIR`` is what a
    crawler built *from now on* resolves (``_execute_source_node`` hands it to
    ``get_crawler``), while ``app.cookie_manager.cookie_dir`` was frozen from the same
    value at ``app``'s own import and is what the account list, the cookie routes and the
    preflight gate read. Patching only the first would leave the crawl authenticated while
    the code that decides *whether* to run still believed nobody had logged in.

    Pass the imported ``app`` module as *module* when the case drives HTTP; leaving it out
    is correct for a case that only crawls.
    """
    monkeypatch.setattr(Config, 'COOKIE_DIR', str(COOKIE_DIR))
    manager = getattr(module, 'cookie_manager', None) if module is not None else None
    if manager is not None:
        monkeypatch.setattr(manager, 'cookie_dir', str(COOKIE_DIR))
    return str(COOKIE_DIR)


# ─── language: every assertion is rendered, none is pasted ──────────────


def _each_language(render):
    """Call ``render(lang)`` for every catalogue language, restoring this thread's own.

    The thread-local goes back because the caller's language is not this helper's to
    change: a test that afterwards reads a rendered sentence itself must still see the
    language its request asked for.
    """
    backup = i18n.get_lang()
    try:
        for lang in i18n.LANGS:
            i18n.set_lang(lang)
            yield render(lang)
    finally:
        i18n.set_lang(backup)


def resolve(key: str, **params) -> tuple[str, ...]:
    """The line the console would print for *key*, once per catalogue language.

    A case writes ``rec.find(*resolve('run.started', rid=run_id))``, so the assertion
    survives a reword, a language switch, and the split itself: ``client`` defaults its
    requests to English while the *run* narrates in the ``lang`` its execute body carried.
    ``t()`` returns the raw template when a parameter is missing, so a forgotten ``{n}``
    shows up here as a visible placeholder instead of silently matching nothing.
    """
    return tuple(_each_language(lambda lang: i18n.t(key, **params)))


def templates(key: str) -> tuple[str, ...]:
    """The catalogue's own text for *key*, with every ``{slot}`` left standing.

    For the questions whose parameters a case cannot know: "did the site say it ran out of
    results?" is true whatever the scroll count printed inside that line was.
    """
    return tuple(_each_language(lambda _lang: i18n.t(key)))


_SLOT = re.compile(r'\{[^{}]*\}')
_PATTERN_CACHE: dict[str, re.Pattern] = {}
_PATTERN_LOCK = threading.Lock()


def _pattern(template: str) -> re.Pattern:
    """Compile one template into a matcher, widening every ``{slot}`` to "anything".

    Cached on the template text, so a matrix that asks the same question of thousands of
    console lines pays for the compile once. Console entries are single *physical* lines
    (``_push_log`` splits on newlines), so ``.*`` can never bridge two rows and report a
    match assembled from halves of each.
    """
    with _PATTERN_LOCK:
        cached = _PATTERN_CACHE.get(template)
        if cached is None:
            cached = re.compile('.*'.join(re.escape(part) for part in _SLOT.split(template)))
            _PATTERN_CACHE[template] = cached
        return cached


def _slot_pattern(template: str, slot: str) -> re.Pattern | None:
    """Compile one catalogue template into a matcher that *captures* ``{slot}``.

    :func:`_pattern` widens every slot to "anything" because it answers a presence question.
    A case that reads a *number out of* a line — the rows the summary said it filed — needs
    the one slot it asked for kept as a group and every other slot still widened, and it needs
    the surrounding words to come from the catalogue rather than from a regex pasted into a
    test: a reworded sentence then moves the pattern with it instead of turning four cases red
    with a message that blames the crawler.

    Returns ``None`` when the template carries no such slot, so a typo in a slot name is a
    visible "no lines matched" rather than a silently empty result. The other slots stay
    *non*-capturing, which is what makes the wanted one ``group(1)``.
    """
    parts = _SLOT.split(template)
    names = [match.strip('{}') for match in _SLOT.findall(template)]
    if slot not in names:
        return None
    pieces = []
    for index, name in enumerate(names):
        pieces.append(re.escape(parts[index]))
        if name != slot:
            pieces.append(r'(?:.*?)')
        # A slot the sentence continues after is read up to that continuation; one at the very
        # end — ``crawl.profile_wait`` finishes with its directory — would capture nothing at
        # all if it stayed lazy, so it takes the rest of the line.
        elif parts[index + 1]:
            pieces.append(r'(.*?)')
        else:
            pieces.append(r'(.*)')
    pieces.append(re.escape(parts[-1]))
    return re.compile(''.join(pieces))


def slots_from(lines: list, key: str, slot: str) -> list[str]:
    """What filled ``{slot}`` in *key*, once per console line that carried it, in order.

    Both catalogue languages are tried per line, so a case reads the same number whatever
    language the run narrated in (a run's language is its own, and a test client defaults to
    English — the pair is exactly why no assertion here is allowed to paste a sentence).
    """
    patterns = [
        compiled for compiled in (_slot_pattern(template, slot) for template in templates(key)) if compiled is not None
    ]
    out: list[str] = []
    for line in lines:
        for pattern in patterns:
            found = pattern.search(line)
            if found:
                out.append(found.group(1))
                break
    return out


def numbers_from(lines: list, key: str, slot: str) -> list[int]:
    """The same as :func:`slots_from`, as numbers — for the counts a case ties against a table.

    A slot that came back non-numeric is refused by name: the pattern widened something it
    should not have, and a bare ``ValueError`` would read as a crawler bug rather than as a
    harness question asked of the wrong slot.
    """
    out: list[int] = []
    for value in slots_from(lines, key, slot):
        try:
            out.append(int(value))
        except ValueError as e:
            raise AssertionError(f'{key!r} filled {{{slot}}} with {value!r}, which is not a number') from e
    return out


_STAMP = re.compile(r'^\[(\d{1,2}):([0-5]\d):([0-5]\d)\]\s')


def stamped_second(line: str) -> float | None:
    """The wall-clock second a console entry carries its ``[HH:MM:SS]`` stamp as, in
    seconds since midnight — or ``None`` when the line carries no leading stamp.

    :meth:`ConsoleRecorder.first_index` answers *which* line came first; this answers *how
    far apart* two of them were, which is the only console-side way a case can watch a
    setting measured in seconds — the 错峰 interval — actually pass the way the gate said
    it would. The stamp is the product's own: ``add_log`` and ``LogBufferHandler`` prefix
    every entry with it, so reading it is reading the same clock the user watched, not a
    parallel instrument the test carries.

    No calendar is claimed: the number is seconds since midnight, so a spacing measured
    across midnight reads negative and the asking case fails with the stamps in its
    message — which is the honest shape for a once-a-day accident, not a pass.
    """
    found = _STAMP.match(str(line or ''))
    if found is None:
        return None
    hours, minutes, seconds = (int(part) for part in found.groups())
    if hours > 23:
        return None
    return float(hours * 3600 + minutes * 60 + seconds)


def names_key(text: str, key: str) -> bool:
    """Did this console *name* the message behind *key*, whatever its parameters were?"""
    return any(_pattern(template).search(text) for template in templates(key))


def mentions(text: str, key: str, **params) -> bool:
    """Did this console print *key* rendered with exactly these parameters?"""
    return any(needle and needle in text for needle in resolve(key, **params))


# ─── canvases ───────────────────────────────────────────────────────────


def run_settings(mode: str = 'serial', headless: bool = False, use_profile=None, **extra) -> dict:
    """The ``settings`` block of one run.

    ``use_profile`` is *omitted* unless the case states it, because absence is the
    product's own "follow the setting" answer — coercing a missing value to ``False`` would
    turn one dialog's reply into a global override (AGENTS: absence means follow the
    setting, never coerce missing to False).
    """
    settings = {'mode': mode, 'headless': bool(headless), 'max_workers': 4, 'disabledTypes': []}
    if use_profile is not None:
        settings['use_profile'] = bool(use_profile)
    settings.update(extra)
    return settings


def params_for(platform: str, mode_key: str, **overrides) -> dict:
    """A complete, matrix-legal ``params`` block for one mode.

    Seeded from :func:`crawl_capabilities.declared_defaults` — the same table the canvas
    seeds a new node from — with the mode named explicitly. Naming it is not decoration:
    ``mode_for`` answers an unknown or missing key with the platform's FIRST mode, which on
    a four-mode platform would quietly turn an author node into a keyword search.
    """
    params = dict(crawl_capabilities.declared_defaults(platform))
    params[MODE_KEY] = mode_key
    params.update(overrides)
    return params


def source_node(node_id: str, platform: str, mode_key: str, *, title: str = '采集', **overrides) -> dict:
    """One data-source node, addressed by a caller-chosen id.

    The id is a storage key everywhere downstream (node rows, cursors, fingerprints), so a
    case that wants to read one node back names it rather than guessing what a canvas
    minted for it.
    """
    return {
        'id': node_id,
        'type': 'source',
        'title': title,
        'platform': platform,
        'params': params_for(platform, mode_key, **overrides),
    }


def name_node(node_id: str, label: str) -> dict:
    """A 工作流命名 node — the canvas's only way to give its own record a name."""
    return {'id': node_id, 'type': 'name', 'title': '工作流命名', 'params': {'workflow_name': label}}


def canvas_for(
    platform: str,
    mode_key: str,
    *,
    node_id: str = 'node-1',
    title: str = '采集',
    settings: dict | None = None,
    **overrides,
) -> dict:
    """The smallest canvas that runs: one source node, no wires.

    No ``output`` node is needed to hold the evidence — a source node checkpoints every row
    into ``runs.db`` as it crawls, so the record's ``row_count`` is the assertion surface
    and the exported file exists only once an output node runs.
    """
    return {
        'nodes': [source_node(node_id, platform, mode_key, title=title, **overrides)],
        'connections': [],
        'settings': dict(settings or run_settings()),
    }


def resume_node(
    node_id: str,
    *,
    run_id: str = '',
    source_node_id: str = '',
    limit: int = 0,
    title: str = '断点续跑',
) -> dict:
    """A 断点续跑 node: another run's stored table, adopted as this node's rows.

    The three params are the product's own names (``canvas.js`` writes exactly these and
    ``app._execute_resume_node`` reads them), and two of them carry meaning a test must be
    able to state separately: an empty ``resume_run_id`` is "the newest unfinished run of
    THIS canvas's fingerprint" — the fingerprint filter is what stops a canvas adopting a
    stranger's ``node-2``, which repeats on every canvas — and an empty ``resume_node_id``
    is "the fullest node of that run", not "the first one".
    """
    return {
        'id': node_id,
        'type': 'resume',
        'title': title,
        'params': {
            'resume_run_id': str(run_id or ''),
            'resume_node_id': str(source_node_id or ''),
            'resume_limit': int(limit or 0),
        },
    }


def resume_canvas(
    *,
    node_id: str = 'node-1',
    run_id: str = '',
    source_node_id: str = '',
    limit: int = 0,
    label: str = '',
    settings: dict | None = None,
) -> dict:
    """The smallest canvas that adopts stored rows: one 断点续跑 node, optionally named.

    ``label`` is not decoration. A record's name is the key every preview probe falls back
    to once the run's in-memory results are gone, so an unnamed canvas is one refresh away
    from answering "no rows" about a table that exists — and the label node is wired INTO
    the resume node because that is the only shape the validator accepts for a name
    (``engine/workflow.py`` refuses a name node with nothing downstream).
    """
    nodes: list = [resume_node(node_id, run_id=run_id, source_node_id=source_node_id, limit=limit)]
    connections: list = []
    if label:
        label_id = f'{node_id}-name'
        nodes.insert(0, name_node(label_id, label))
        connections.append({'from': label_id, 'to': node_id})
    return {'nodes': nodes, 'connections': connections, 'settings': dict(settings or run_settings())}


def posts_then_comments_canvas(
    platform: str,
    *,
    posts: dict | None = None,
    comments: dict | None = None,
    posts_id: str = 'node-1',
    comments_id: str = 'node-2',
    link_column: str = LINK_COLUMN,
    settings: dict | None = None,
) -> dict:
    """Search → 评论采集 wired the way the panel wires it: the feed replaces the textarea.

    The comments mode declares ``urls`` with ``fed_by='input_column'``, so once a
    data-bearing parent is attached the pasted value's requiredness is waived and the
    column's links arrive at execution time. The column defaults to the matrix's own link
    column rather than a name invented here: a wired node naming a column the upstream
    table lacks is a refusal *by name*, and this helper must not be what hides that.
    """
    comments_params = {'comment_limit': 3, **(comments or {})}
    comments_params.setdefault('input_column', link_column)
    return {
        'nodes': [
            source_node(posts_id, platform, 'posts', title='搜索', **(posts or {})),
            source_node(comments_id, platform, 'comments', title='评论', **comments_params),
        ],
        'connections': [{'from': posts_id, 'to': comments_id}],
        'settings': dict(settings or run_settings()),
    }


def component_canvas(components, *, settings: dict | None = None) -> dict:
    """Several independent components on one canvas — the serial/parallel split's input.

    Each entry is ``{'platform', 'mode', 'source', 'label', 'title', 'params'}``; ``label``
    adds a name node, which is how one parallel record becomes ``A + B``. The components
    are *unwired* to each other on purpose: ``find_workflows`` splits on connected
    components, so this is the one shape that says "N workflows" without holding a second
    opinion about what a workflow is.
    """
    nodes: list = []
    connections: list = []
    for index, part in enumerate(components, start=1):
        source_id = part.get('source') or f'node-{index * 2 - 1}'
        label = part.get('label')
        if label:
            label_id = part.get('label_id') or f'node-{index * 2}'
            nodes.append(name_node(label_id, label))
            connections.append({'from': label_id, 'to': source_id})
        nodes.append(
            source_node(
                source_id,
                part['platform'],
                part['mode'],
                title=part.get('title', '采集'),
                **part.get('params', {}),
            )
        )
    return {'nodes': nodes, 'connections': connections, 'settings': dict(settings or run_settings())}


# ─── console ────────────────────────────────────────────────────────────


class _MirrorHandler(logging.Handler):
    """A second copy of every log record, for the audit file only.

    The console buffer filters transport chatter out on purpose (``LogBufferHandler`` drops
    werkzeug and urllib3 so the user's panel stays readable), while an audit of a real
    browser wants what actually happened. The verdict math never reads this stream: that
    is the console's job, because the console is what the user would have seen.
    """

    def __init__(self, sink: list):
        super().__init__(level=logging.INFO)
        self._sink = sink

    def emit(self, record):
        with contextlib.suppress(Exception):
            self._sink.append(record.getMessage())


def fold_window(lines: list, seen_total: int, window: list, total: int) -> tuple[list, int, bool, bool]:
    """What the recorder appends, where its cursor lands, and what it must admit.

    Pure on purpose, so the fast tier can drive it with a fake poller. ``total`` is the
    console's running line count and ``window`` its last :data:`CONSOLE_WINDOW` lines, read
    together under one lock by the status endpoint, so the delta says how many lines are
    new and the *end* of the tail says which ones:

    * delta ≤ window → the newest ``delta`` entries are exactly what we had not seen;
    * delta > window → the gap is wider than the tail: everything the window holds is new
      **and** some lines are gone for good, so ``overflow`` is set rather than a shorter
      transcript passed off as the whole crawl;
    * total < cursor → the console was reset, i.e. a second run started in this process
      (``_begin_run`` clears it). Its lines keep accumulating in the same recorder, because
      a resume case wants the whole conversation, and ``reset`` says so out loud.
    """
    total = int(total)
    if total < seen_total:
        return list(window), total, False, True
    delta = total - seen_total
    if delta <= 0:
        return [], total, False, False
    if delta <= len(window):
        return list(window[len(window) - delta :]), total, False, False
    return list(window), total, True, False


class ConsoleRecorder:
    """Every console line of one live run, read exactly once — plus the timing to audit.

    *client* only has to answer ``.get('/api/workflow/status').get_json()``: the real test
    client and a fake poller are the same thing to this class, which is what lets the delta
    math be tested without a browser or a network.
    """

    def __init__(self, client, cadence: float = 2.0, *, mirror: bool = True):
        """*cadence* is how often one status poll is asked for.

        Two seconds, not half a second: every poll answers on the worker's own lock and
        rebuilds the per-workflow view plus a results snapshot, which is the lock the run
        wants at its finish line, and a live case's budget is measured in thousands of
        polls. The rate only has to stay well under the console's production rate — the
        loudest walk in the project prints a couple of lines per scroll round and sleeps a
        second between them, so a 200-line window cannot be out-run at this cadence. The
        fast tier drives it at 0 through the parameter.
        """
        self._client = client
        self.cadence = cadence
        self.lines: list[str] = []
        self.mirror_lines: list[str] = []
        # The two facts a reader must not be left to guess at: a lost line is a gap in the
        # evidence, and a reset is a second run, not a crawl that restarted itself.
        self.overflow = False
        self.resets = 0
        self.snapshots = 0
        self.status: dict = {}
        self._total = 0
        # Where this transcript stood when the console restarted, so :meth:`complete` can
        # still say "every line the server counted is in here" across a second run.
        self._baseline = 0
        # One transcript per workflow, folded with the same delta math as the global one.
        # A run of four components is four verdicts, and grading one component against the
        # whole console lets a reason named by its sibling excuse its own silence — which is
        # the exact shape this tier exists to catch. Keyed by the workflow's *name* (the
        # label its own name node gave it, which is also what the run record is filed under).
        self.wf_lines: dict[str, list[str]] = {}
        self.wf_totals: dict[str, int] = {}
        # Where the console was on this thread's clock, for a wait that must not be paid twice.
        self._began = time.monotonic()
        self._root = logging.getLogger()
        self._handler = None
        self._previous_level = None
        if mirror:
            self._handler = _MirrorHandler(self.mirror_lines)
            if self._root.level > logging.INFO or self._root.level < 0:
                self._previous_level = self._root.level
                self._root.setLevel(logging.INFO)
            self._root.addHandler(self._handler)

    # ── reading ─────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """One status poll: fold in whatever is new, and hand the payload back."""
        payload = (self._client.get('/api/workflow/status').get_json() or {}) if self._client else {}
        self.status = payload
        self.snapshots += 1
        window = list(payload.get('logs') or [])
        total = int(payload.get('log_total') or 0)
        fresh, self._total, overflow, reset = fold_window(self.lines, self._total, window, total)
        if reset:
            self.resets += 1
            # A reset whose tail is shorter than its own count already lost lines at the
            # boundary: the second run began producing before this recorder first looked.
            overflow = overflow or len(window) < total
        if overflow:
            self.overflow = True
        self.lines.extend(fresh)
        if reset:
            self._baseline = len(self.lines) - self._total
        self._fold_workflows(payload, reset=reset)
        return payload

    def _fold_workflows(self, payload: dict, *, reset: bool) -> None:
        """Fold this poll's per-workflow tails into their own transcripts.

        The global buffer and a workflow's buffer are read in the same locked snapshot of the
        same payload, so the delta math is identical — and a workflow's delta can never exceed
        the global one (every line lands in the global buffer, only some carry a workflow), so
        :attr:`overflow` on the global transcript already covers a gap in any slice of it.
        """
        for entry in payload.get('workflows') or []:
            name = str(entry.get('name') or '')
            if not name:
                continue
            window = list(entry.get('logs') or [])
            total = int(entry.get('total') or 0)
            if reset:
                # A console reset wipes every buffer, so each slice starts over: the old
                # transcript stays in the global one, where the case that wants a resume can
                # still read it.
                self.wf_lines[name] = []
                self.wf_totals[name] = 0
            fresh, new_total, _overflow, _reset = fold_window(
                self.wf_lines.get(name, []), self.wf_totals.get(name, 0), window, total
            )
            self.wf_lines.setdefault(name, []).extend(fresh)
            self.wf_totals[name] = new_total

    def transcript_for(self, name: str) -> str:
        """This workflow's own console, or ``''`` when it never narrated anything.

        Callers assert the slice is non-empty: an empty transcript graded as "nothing was
        said" would convict a component for a name the console never used rather than for its
        own silence.
        """
        return '\n'.join(self.wf_lines.get(str(name or ''), []))

    @property
    def counted(self) -> int:
        """What the console says it has produced in total — the number :meth:`complete` answers to."""
        return self._total

    def complete(self) -> bool:
        """The recorder's own proof: every line the server counted is in this transcript.

        Without it a case could assert on 200 lines of a 900-line crawl and call the
        missing 700 evidence of nothing. It is a *count* equality, not a claim about order —
        the ordering questions are answered by :meth:`first_index`.

        One limitation, stated rather than papered over: a console reset is only seen when
        the new count lands *below* the old one, because a second run that is already longer
        than the first is indistinguishable from growth. So the equality means what it says
        for one run per recorder — which is how the live matrix uses it — and
        :attr:`resets` is the flag that says when a transcript spans more than one.
        """
        return len(self.lines) - self._baseline == self._total

    def drain(self, reads: int = 3) -> dict:
        """Keep reading until the console stops growing.

        The worker writes its closing lines (the finish sentence, a store warning) after
        ``running`` goes False and before its thread ends, so one post-run read can land
        between the two and lose the very line the case is about.
        """
        payload = self.snapshot()
        for _ in range(reads):
            before = len(self.lines)
            payload = self.snapshot()
            if len(self.lines) == before:
                break
        return payload

    def pump(self, timeout: float, *, run_id: str = '') -> dict:
        """Poll at :attr:`cadence` until the run has written a verdict, or fail naming why."""
        deadline = time.monotonic() + timeout
        payload: dict = {}
        while True:
            payload = self.snapshot()
            if settled(payload):
                return payload
            if time.monotonic() >= deadline:
                raise AssertionError(
                    'the run never reached a verdict within '
                    f'{timeout}s{f" (run {run_id})" if run_id else ""}: '
                    f'outcome={payload.get("outcome")!r} running={payload.get("running")} '
                    f'stopping={payload.get("stopping")} settling={payload.get("settling")}, '
                    f'{len(self.lines)} console lines, last {self.lines[-5:]!r}'
                )
            time.sleep(self.cadence)

    # ── asking ──────────────────────────────────────────────────────────

    @property
    def text(self) -> str:
        return '\n'.join(self.lines)

    def find(self, *substrings) -> list[str]:
        """The lines carrying **any** of these substrings — pass :func:`resolve` or
        :func:`templates` to it.

        OR rather than AND, because both helpers hand back the same sentence once per
        language: the case wants the line, whichever language it happened to be printed in.
        """
        wanted = [needle for needle in substrings if needle]
        return [line for line in self.lines if any(needle in line for needle in wanted)]

    def counts(self, substring: str) -> int:
        """How many lines contain this literal — the count "one failure, one line" is checked with."""
        return sum(1 for line in self.lines if substring in line)

    def first_index(self, key: str) -> int:
        """Where this message first appears, or -1 when the console never said it.

        Sequence, not presence: "the run booked itself before any node executed" is a
        different claim from "both lines exist somewhere", and a transcript that lost its
        head would satisfy the second one.
        """
        for index, line in enumerate(self.lines):
            if any(_pattern(template).search(line) for template in templates(key)):
                return index
        return -1

    def counts_key(self, key: str) -> int:
        """How many lines named this message, whatever its parameters were."""
        return sum(1 for line in self.lines if any(_pattern(t).search(line) for t in templates(key)))

    def elapsed(self) -> float:
        """Wall seconds since this recorder opened — the case's own cost, in its audit row."""
        return round(time.monotonic() - self._began, 1)

    def close(self) -> None:
        """Hand the root logger back exactly what it had before.

        A handler left installed would keep growing one list for the rest of the session,
        and a root level lowered here would turn the fast tier's silence into every
        library's INFO chatter for whichever test runs next.
        """
        if self._handler is not None:
            self._root.removeHandler(self._handler)
            with contextlib.suppress(Exception):
                self._handler.close()
            self._handler = None
        if self._previous_level is not None:
            self._root.setLevel(self._previous_level)
            self._previous_level = None


def settled(payload: dict) -> bool:
    """The run answered for itself: no worker in flight **and** a verdict on the record.

    ``running`` alone is not it — 停止 clears that flag on the *request* thread while the
    worker still owes the record its conclusion — and neither is ``settling``, which is
    precisely "the thread has not written yet". A missing verdict would let a recorder
    return before the finish sentence existed.

    An empty ``outcome`` means the run is still deciding, so the watch continues.
    ``rejected`` is in :data:`OUTCOMES` on purpose: validation refused the canvas, nothing
    will ever be written after it, and a watcher that kept waiting for a verdict that
    cannot arrive would spend the case's whole budget on a run that never started. The
    refusal is not hidden by that — :meth:`LiveRun.assert_l3` reads ``run.rejected`` back
    and refuses it for a canvas that was meant to crawl.
    """
    if payload.get('running') or payload.get('stopping') or payload.get('settling'):
        return False
    return str(payload.get('outcome') or '') in OUTCOMES


def abort_run(client, module, rec, budget: float = 600.0, run_id: str = '') -> dict:
    """End a run a case has stopped caring about, and read its verdict before letting go.

    A live case that dies on an assertion between ``execute`` and the run's finish leaves the
    worker crawling, and the leak is worse than untidy:

    * ``tests/conftest`` restores ``execution_state`` wholesale when the client goes away, so
      the tripwire that normally fails a test for leaking a run never sees it, and the handle
      to the browser the worker is inside is discarded with the state — 停止 could no longer
      reach it through the registry either;
    * the orphan keeps the platform's turn in :mod:`crawl_gate` and the profile directory, so
      the next case's ``_wait_for_quiet_server`` (30 s) times out and the rest of the tier
      errors for a reason that belongs to a different test;
    * and it keeps *writing into the shared console*, whose lines the next case folds into
      its own transcript — which can convict an innocent case of a stranger's failure, or, the
      damaging direction, hand a stranger's 「没有更多了」 to a verdict and grade a real
      under-collection as named-and-therefore-legitimate.

    So this is not cleanup, it is containment. 停止 is asked first (the same request the user's
    button makes, which is why it knows how to kill the driver the worker is blocked in), then
    the recorder watches for the verdict the worker still owes and the slot is given back.
    Returns the last status payload, plus ``abort_quiet`` / ``abort_error`` when either step
    did not complete: a run that refuses to settle is *reported*, never raised over the
    failure the case is already dying of. The caller owes that report to the audit row — see
    :func:`abort_summary` — because a leak that is only in the next case's transcript reads as
    the next case's own bug.
    """
    outcome: dict = {}
    try:
        client.post('/api/workflow/stop')
    except Exception as e:
        return {'abort_error': str(e)}
    left = max(60.0, float(budget))
    tried = time.monotonic()
    try:
        outcome = rec.pump(left, run_id=run_id)
    except AssertionError as e:
        outcome = dict(rec.status or {})
        outcome['abort_error'] = str(e)
    # The verdict is the record's; the *thread* is what the next case waits on. A worker still
    # unwinding after writing 已中断 holds the claim, so this is the half that actually contains
    # the leak, and its budget is what the pump did not spend.
    quiet = run_finished(module, timeout=max(30.0, left - (time.monotonic() - tried)))
    outcome['abort_quiet'] = bool(quiet)
    if not quiet:
        outcome['abort_error'] = f'the aborted worker is still alive: {describe_state(module)}'
    return outcome


def abort_summary(note: dict | None) -> str:
    """What containment achieved, as one readable cell — the audit row's only say-so on a leak.

    The distinction the rest of the tier lives or dies by is not "the case failed" (its own
    assertion already said that) but "the next case is owed a free lane and a free profile".
    :func:`abort_run` answers that with ``abort_quiet`` / ``abort_error`` and a case that
    discards them leaves the reader of ``verdicts.csv`` chasing a timeout in a later row whose
    cause is an earlier case's still-alive worker. An empty string means containment was never
    attempted — the run settled on its own — which is a different fact from "attempted, and the
    browser is still out there".
    """
    if not note:
        return ''
    error = str(note.get('abort_error') or '')
    if error:
        return f'not contained: {error}'
    return 'contained' if note.get('abort_quiet') else 'not contained: the worker never reported'


# ─── runs, records and the wait ─────────────────────────────────────────


def wait_run_finished(module, timeout: float = 1800.0) -> bool:
    """``run_wait.run_finished`` with a budget a real crawl can actually live inside.

    The shared helper's 30 s default is right for a fake crawler and is a guaranteed red
    for a browser: one page's first content may take ``Config.PAGE_WAIT_TIMEOUT`` (300 s),
    and a profile may be waited for up to ``Config.PROFILE_LOCK_TIMEOUT`` (900 s). So the
    timeout is a parameter and the failure names the state — "timeout" alone never said
    which of those two it had been waiting on.
    """
    if run_finished(module, timeout=timeout):
        return True
    raise AssertionError(f'the worker thread never went away ({describe_state(module)})')


def start(
    client,
    workflow,
    *,
    workflow_name: str | None = None,
    resume_run_id: str | None = None,
    queue: bool | None = None,
    lang: str = 'zh',
) -> dict:
    """``POST /api/workflow/execute``, and hand the response body back.

    A refusal is raised as a failure that names the response rather than returned for a
    case to notice: the one thing a live matrix must not do is go on polling a run that
    never started. ``queue=False`` is what the 继续 banner sends — a *queued* resume would
    spend its whole read budget on somebody else's console, so this helper refuses one.
    """
    body: dict = {'workflow': workflow, 'lang': lang}
    if workflow_name is not None:
        body['workflow_name'] = workflow_name
    if resume_run_id:
        body['resume_run_id'] = resume_run_id
    if queue is not None:
        body['queue'] = bool(queue)
    response = client.post('/api/workflow/execute', json=body)
    payload = response.get_json() or {}
    assert response.status_code == 200, f'execute refused with HTTP {response.status_code}: {payload}'
    assert payload.get('ok'), f'execute did not accept the run: {payload}'
    assert not payload.get('queued'), f'the server was busy, so this run only got in line: {payload}'
    assert payload.get('run_id'), f'no run id came back: {payload}'
    return payload


def read_record(client, run_id: str) -> dict:
    """The stored run: every node with its ``status``, ``row_count`` and ``cursor``.

    ``GET /api/runs/<id>`` is the only endpoint carrying the cursor and the error text —
    and the only one that does **not** settle orphaned rows, which is what a case watching
    its own live run needs: a reconciler read here would hand it a verdict the worker had
    not written.
    """
    payload = client.get(f'/api/runs/{run_id}').get_json() or {}
    assert payload.get('ok'), f'no record for run {run_id}: {payload}'
    return payload['run']


def read_records(client, limit: int = 50) -> list:
    """The panel's own list, newest first (and, like the panel, it settles orphans)."""
    payload = client.get(f'/api/runs/list?limit={limit}').get_json() or {}
    assert payload.get('ok'), payload
    return payload.get('runs') or []


def preview(client, node_id: str, workflow_name: str = '', limit: int = 500) -> list:
    """The rows one node actually collected — the same probe the Data Preview panel uses.

    ``row_count`` says how many, which is a number; this is the table, and a live matrix
    needs it for the claims that can only be made about content: that no link repeats (the
    dedupe identity), that a comment belongs to a link this canvas crawled, that a 正文 is
    an excerpt rather than a body. The run's own results are still in memory, so the
    workflow name is only the fallback path — but it is sent anyway, because a case must
    read the rows *this* canvas filed and never a stranger node that happens to share an id.
    """
    payload = (
        client.post(
            '/api/data/preview',
            json={'node_id': node_id, 'workflow_name': workflow_name, 'limit': min(int(limit), 500)},
        ).get_json()
        or {}
    )
    assert payload.get('ok'), f'no preview for node {node_id}: {payload}'
    return payload.get('rows') or []


def node_of(record: dict, node_id: str) -> dict:
    """One node row of a record, by the id the case gave its canvas."""
    for row in record.get('nodes') or []:
        if row.get('node_id') == node_id:
            return row
    ids = [row.get('node_id') for row in record.get('nodes') or []]
    raise AssertionError(f'run {record.get("run_id")} has no node {node_id!r}; it has {ids}')


def stored_rows(record: dict, node_id: str) -> int:
    """How many rows this node actually has on disk (``finish_node`` re-derives it)."""
    return int(node_of(record, node_id).get('row_count') or 0)


def cursor_of(record: dict, node_id: str) -> dict:
    return node_of(record, node_id).get('cursor') or {}


def classify_verdict(target: int, rows_kept: int, console: str, exits=SHARED_EXITS, bug_lines=()) -> dict:
    """How a crawl that fell short behaved — and the only verdict that is ever a bug.

    ``FULL`` is arithmetic. Everything below it is *reading the console*: a site that says
    「没有更多了」, hits its own board cap, answers with risk control, meets a login wall,
    refuses an already-collected re-crawl, or is cut short by 停止 has told the user what
    happened, and its crawl is entitled to be short. A crawl that keeps fewer rows and
    prints no such sentence is the silent under-report this tier exists to catch.

    *console* is the transcript this verdict is graded against, and the caller's job is to
    hand over the slice that belongs to the component being judged: a reason named by one
    workflow whitewashing another one's silence is precisely the false green a multi-node
    canvas can produce and a single-component one cannot.

    *bug_lines* is the other half of the whitelist's discipline. Some sentences in the
    catalogue name a reason that is not true — the plan's 「说了但说谎」 list
    (``docs/live_test_plan.md`` §5, items Z3/Z6/Z16): a scroll loop that gave up on its first
    non-growing check reporting 「确认到底了」, an empty tab reporting 「这个作者没发过」 when the
    page simply rendered slowly. Those lines may not license a shortfall, so a console that
    names only one of them answers SILENT_SHORT with the liar quoted in ``reasons``.

    Returns ``{'verdict', 'reasons'}`` naming the catalogue *keys* that fired, so an audit
    row cites a message rather than a sentence copied out of one language.
    """
    if rows_kept >= target:
        return {'verdict': FULL, 'reasons': []}
    liars = [key for key in bug_lines if names_key(console, key)]
    named = [key for key in exits if key not in liars and names_key(console, key)]
    if named:
        return {'verdict': NAMED_SHORT, 'reasons': named + liars}
    if liars:
        return {
            'verdict': SILENT_SHORT,
            'reasons': [f'kept {rows_kept} of {target} and the only line named is one that lies: {liars}'],
        }
    return {
        'verdict': SILENT_SHORT,
        'reasons': [f'kept {rows_kept} of {target} with no legitimate exit named in the console'],
    }


def wall_flags(console: str) -> list[str]:
    """Which walls this console spoke about — a separate column because a *risk* block and
    a *dead session* are different facts wearing one face, and the fix is different too."""
    return [key for key in ('crawl.loginWall', 'crawl.riskBlocked', 'run.cookieExpired') if names_key(console, key)]


# ─── the one site answer a live case cannot wait for ─────────────────────


def session_dies_after(monkeypatch, crawler_class, handler: str, *, rows: int, budget_kw: str = 'target_count') -> dict:
    """Make the next real crawl report a dead login session once it holds *rows* rows.

    **What stays real:** the crawler opens the live page, walks it and streams live rows into
    this run's own table. **What is injected:** one boolean — :attr:`Crawler.login_wall`, the
    flag ``app._execute_source_node`` reads to decide "the platform bounced this browser to a
    login page". That flag together with a table under target *is* the designed cookie-death
    path (node ``partial``, run ``failed``, ``run.cookieExpired`` printed once, and 继续 offered
    from the stored cursor — ``AGENTS.md``), and a test may not wait for the user's real
    session to expire in order to walk it: the alternative to injecting the verdict is not
    measuring the path, it is a case that quietly never runs.

    The walk is asked for *rows* instead of the user's number because "ended early with the
    wall latched" is the shape the executor reads, and reducing the budget is how a live walk
    is made to stop where a wall would have stopped it. The latch is one-shot and any call
    carrying a stored ``resume`` goes straight to the real handler, because the resumed
    attempt is the half of the cell that must crawl for real.

    The returned dict is the case's own record of what was injected, so its audit row can
    tell a simulated death from one the site actually answered.
    """
    real = getattr(crawler_class, handler)
    state = {'latched': False, 'rows': 0, 'calls': 0}

    def _cut(self, *args, **kwargs):
        state['calls'] += 1
        if state['latched'] or kwargs.get('resume'):
            return real(self, *args, **kwargs)
        narrowed = dict(kwargs)
        narrowed[budget_kw] = rows
        kept = real(self, *args, **narrowed)
        if kept:
            state['latched'] = True
            state['rows'] = len(kept)
            self.login_wall = True
        return kept

    monkeypatch.setattr(crawler_class, handler, _cut)
    return state


# ─── audit ──────────────────────────────────────────────────────────────

#: One row per case, in this order. These are the questions a root-cause pass asks first:
#: what was asked for, what came back, what the console said, and whether a wall or a dead
#: cookie was in the answer — the four facts that separate "the site refused" from "the
#: code broke". ``pass_id`` first, because the index is append-only across passes and the
#: closure run is a *comparison*: without it, forty rows for twenty cases say nothing about
#: which half is current. ``abort`` sits beside the two other health facts because it answers
#: a question about the *next* row: whether this case let go of the platform lane and the
#: profile directory on its way out, or left a worker holding them.
VERDICT_COLUMNS = (
    'pass_id',
    'case_id',
    'platform',
    'mode',
    'headless',
    'use_profile',
    'lang',
    'target',
    'rows',
    'verdict',
    'reasons',
    'wall_flags',
    'cookie_expired',
    'abort',
    'seconds',
)


def audit_dump(case_id: str, payload: dict, *, root=None, pass_id: str | None = None) -> Path:
    """Write one case's whole console, and append its verdict row to the index.

    The transcript carries its own overflow and reset markers *inside* the file, because a
    report that quietly shows 200 of 900 lines is worse than no report: it reads as a crawl
    that narrated nothing. The CSV is the index you scan when forty cases ran and three
    went red.

    Transcripts live under ``<root>/<pass_id>/``, one directory per pass. Overwriting them in
    place would destroy the evidence a previous red was root-caused from, and a re-run of the
    same case is the normal thing (the closure gate is exactly that), so the two passes are
    kept side by side and the ``pass_id`` column ties a row back to its own transcript.
    """
    base = Path(root) if root is not None else Path(AUDIT_ROOT)
    stamp = str(pass_id if pass_id is not None else PASS_ID)
    here = base / stamp
    here.mkdir(parents=True, exist_ok=True)
    recorder = payload.get('recorder')
    lines = list(getattr(recorder, 'lines', None) or payload.get('lines') or [])
    overflow = getattr(recorder, 'overflow', None)
    if overflow is None:
        overflow = bool(payload.get('overflow'))
    resets = getattr(recorder, 'resets', None)
    if resets is None:
        resets = int(payload.get('resets') or 0)
    mirror = list(getattr(recorder, 'mirror_lines', None) or payload.get('mirror_lines') or [])
    reasons = payload.get('reasons') or []
    # Containment arrives as ``abort_run``'s own dict, which is two facts a reader needs
    # together: whether the worker went quiet, and what stopped it reporting that.
    abort_note = payload.get('abort')
    abort = abort_summary(abort_note) if isinstance(abort_note, (dict, list, tuple)) else str(abort_note or '')

    transcript = here / f'{case_id}.console.txt'
    header = [
        f'# case {case_id}',
        f'# pass {stamp}',
        f'# verdict {payload.get("verdict", "")}',
        f'# reasons {"; ".join(str(item) for item in reasons)}',
        f'# console lines {len(lines)}',
        '# overflow ' + ('YES — the status window was out-run, this transcript has gaps' if overflow else 'no'),
        f'# console resets observed {resets}',
        f'# containment {abort}' if abort else '# containment not attempted (the run settled itself)',
        f'# seconds {payload.get("seconds", "")}',
    ]
    body = [f'## console ({len(lines)} lines)', *lines, '## logging mirror (unfiltered root logger)', *mirror]
    transcript.write_text('\n'.join([*header, '', *body]), encoding='utf-8')

    index = base / 'verdicts.csv'
    fresh = not index.exists()
    row = {column: payload.get(column, '') for column in VERDICT_COLUMNS}
    row['pass_id'] = row['pass_id'] or stamp
    row['case_id'] = row['case_id'] or case_id
    if isinstance(row['reasons'], (list, tuple)):
        row['reasons'] = '; '.join(str(item) for item in row['reasons'])
    if isinstance(row['wall_flags'], (list, tuple)):
        row['wall_flags'] = '; '.join(str(item) for item in row['wall_flags'])
    row['abort'] = abort
    with index.open('a', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(VERDICT_COLUMNS))
        if fresh:
            writer.writeheader()
        writer.writerow(row)
    return transcript
