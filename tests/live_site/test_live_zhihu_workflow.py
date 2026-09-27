"""The zhihu LIVE program: real runs through the app, judged by what the console says.

Everything else in :mod:`tests/live_site` measures a *crawler* called directly. That is the
right instrument for "what does the site answer", and blind to everything above it: the
record the run leaves in ``runs.db``, the console the user watches, 串行 vs 并行, 无头 vs
窗口, 停止, the 继续 banner, the fed comment node, and the shipped acceptance canvas
``data/workflows/测试：知乎.json``. This file drives all of that through
``POST /api/workflow/execute`` with the user's real cookie jar in place, and reports every
case into ``scratchpad/live_audit/`` so a red can be read back without spending the account
again.

**How a short crawl is judged.** Each case states the target it asked for and gets its verdict
from :func:`live_run_harness.classify_verdict`: FULL (the number arrived), NAMED_SHORT (it
did not, and the console carries the site's own reason), SILENT_SHORT (it did not, and
nothing was said). The approved strictness:

* a windowed case on a keyword chosen for its supply must be FULL — anything else is a red;
* a headless case may also pass on a *named* risk-control or login-wall exit, but only with
  the line quoted into the audit row and the row flagged ``WARN``;
* a SILENT_SHORT is never acceptable anywhere, and neither is a duplicated failure line, a
  traceback in the console, a ``cookie_expired`` flag, or a console the recorder could not
  read whole (``overflow``).

**A named reason is only an excuse when the reason is true.** ``docs/live_test_plan.md`` §5
keeps a second list beside the whitelist — the lines that *say* something and lie (Z6's
「未加载新内容」 after one non-growing check, Z3's one-word-for-three-causes 「为空或被拦截」,
Z16's 「这个标签页没有作品」 on a slowly rendered tab). Those are :data:`ZHIHU_LIES` here and are
handed to the grader as ``bug_lines``, so a crawl that came up short naming only one of them
grades SILENT_SHORT and goes red: the message is the bug, and a whitelist that licensed it
would retire the only signal that says so.

**Whose console is a component graded against?** Its own. ``/api/workflow/status`` ships a
transcript per workflow, the recorder folds them alongside the global one, and a four-component
run writes four verdicts from four slices — because a reason named by the board walk can
otherwise excuse a search that said nothing, which is exactly the half-empty crawl presented
as a success that this tier exists to catch.

**No case skips.** Nothing here declines to run: a refusal that names itself is the site's
answer and is asserted, and the tier's skip allowance is a closed list this file does not
extend. What a run here needs is the session the user saved — every case reads
``data/cookies`` through :func:`live_run_harness.real_jar`, the two author cases refuse a
missing jar as a *red* before they touch any fixture, and ``cookie_expired`` never became true
(case F2, woven through all of them). The one thing that can still grey a line is the tier's
own environment: no Chrome, no driver.

**Whose browser.** Cases take the tier's own profile root (the session fixture in
``tests/live_site/conftest.py`` writes it as a setting), which is that tier's standing
policy; with ``CIXI_LIVE_USE_USER_PROFILE=1`` that root *is* the user's real login, and this
file is what to run then. ``use_profile`` is stated only where a case is about it (G1 says
False to buy true overlap, G3 says True to prove the profile serializes).

Run it on the domestic network, deliberately, never unattended::

    .venv/Scripts/python.exe -m pytest -q -m "live_site and live_cn" \\
        tests/live_site/test_live_zhihu_workflow.py -p no:cacheprovider
"""

import contextlib
import copy
import csv
import json
import re
import time
from pathlib import Path

import browser_profiles
import cookie_preflight
import live_run_harness as harness
import pytest

import settings_store

pytestmark = [
    pytest.mark.live_site,
    pytest.mark.live_cn,
    pytest.mark.enable_socket,
    # This file presses Run. The worker puts a tee over ``sys.stdout`` for its whole life, so
    # two of these side by side would interleave consoles (see the ``serial`` marker).
    pytest.mark.serial,
]

REPO_ROOT = Path(__file__).resolve().parents[2]
PLATFORM = 'zhihu'

#: The user's own acceptance canvas, read **read-only** and run exactly as saved. The path is
#: absolute on purpose: ``Config.WORKFLOW_DIR`` is redirected into a throwaway root by the
#: test harness, so the file this case is about only exists where the user put it.
ACCEPTANCE_FILE = REPO_ROOT / 'data' / 'workflows' / '测试：知乎.json'

#: zhihu's own legitimate exits, on top of the ones the executor and the comment engine print
#: for every platform. Each is an i18n key rather than a sentence: the console is matched
#: through the catalogue, so a reworded message keeps matching and a renamed one fails
#: visibly instead of quietly turning a pass into a red.
#:
#: Deliberately absent: ``crawl.zhihu.finished`` and ``crawl.zhihu.target_reached``. Both are
#: printed by a walk that reached its number, so letting one into a whitelist lets a crawl
#: certify its own FULL — 「说了」 is only evidence when what it says explains a shortfall.
ZHIHU_LEGIT_EXITS = harness.SHARED_EXITS + (
    'crawl.zhihu.no_more',
    'crawl.zhihu.hotCapped',
    'crawl.zhihu.hotWall',
    'crawl.zhihu.hotRefused',
)

#: The lines the approved plan files under 「说了但说谎」 (``docs/live_test_plan.md`` §5's
#: closing note, §6's Z3/Z6/Z16): each reports a site answer while really reporting a walk
#: that gave up. Never exits. A short crawl whose only reason is one of these is graded as the
#: silent one it still is, with the liar quoted into the audit row — the message is the bug,
#: and a whitelist that licensed it would retire the only signal that says so.
#:
#: ``crawl.zhihu.confirmed`` is deliberately not listed: the walk used to end on its FIRST
#: stalled round and print that line, which is why §6 Z6 filed it as a lie. The give-up now
#: waits for ``STUCK_ROUNDS`` consecutive stalls, so the sentence has no caller left.
#: ``crawl.zhihu.stuck`` — the line that replaced it — stays banned *pending evidence*: it
#: states its round count honestly now, but a list that stops growing is still not proven to
#: be out of supply rather than softly throttled, and §5's whitelist is a closed list that a
#: live measurement has to open.
ZHIHU_LIES = (
    'crawl.zhihu.stuck',
    'crawl.zhihu.emptyOrBlocked',
    'crawl.zhihu.authorTabEmpty',
)

#: An author walk that drains a tab holding fewer items than were asked for says so per tab,
#: with the count and the reason it stopped. That line — not 「这个标签页没有作品」, which Z16
#: measures as a slow-render lie — is the honest short-supply exit for the mode.
AUTHOR_EXITS = ZHIHU_LEGIT_EXITS + ('crawl.zhihu.authorTabDone',)

#: A comment crawl's honest endings, in the shared comment engine's words: no panel on the
#: page, the section is closed, the link unreadable, the article blocked. Without these, a
#: closed comment section reads as a silent shortfall in a mode that has no row budget at all.
#:
#: Built from the *shared* exits, not from ``ZHIHU_LEGIT_EXITS``: 没有更多了/热榜封顶 are lines
#: the search walk prints and a comment handler can never print, and a feed canvas puts both
#: nodes in ONE workflow — so inheriting them would let the parent's honest tail excuse a
#: comment node that stored nothing and said nothing, which is the whitewash this whole file
#: exists to refuse.
COMMENT_EXITS = harness.SHARED_EXITS + (
    'comment.zhihuNoPanels',
    'comment.commentsClosed',
    'comment.status.blocked',
    'comment.status.dead',
)

#: The walls a *headless* crawl may answer with. AGENTS records that zhihu throttles a headless
#: session day-by-day (risk 40362) and that 「0 行」 is then a legitimate outcome; the raised
#: 「为空或被拦截」 refusal is that throttle in its loud form, so it belongs here and only here —
#: in a windowed case the same line is Z3 and may not excuse anything.
HEADLESS_REFUSALS = ('crawl.riskBlocked', 'crawl.loginWall', 'crawl.zhihu.emptyOrBlocked')

#: One screen of zhihu search results is ~20 cards (docs/crawler_notes.md), so a target of 40
#: is a proven multi-screen walk rather than a second pass over the first screen.
DEEP_TARGET = 40

# The timeouts are the product's own worst cases stacked up, not a guess at "long enough":
# one page's first content may take PAGE_WAIT_TIMEOUT (300 s) and a profile or a platform
# lane up to 900 s, so a target of 10 is not "fast" and 50 rows with 展开全文 is not "slow" —
# it is minutes of scroll rounds and per-row expansion waits.
#
# One number means one wall-clock budget per case: :meth:`LiveRun.wait` hands what the console
# watch did not spend to the thread watch, rather than paying each in full.
QUICK_TIMEOUT = 1200.0
DEEP_TIMEOUT = 2700.0
COMMENT_TIMEOUT = 3000.0
ACCEPTANCE_TIMEOUT = 7200.0

#: How long E1 waits for a crawl to reach its first stored row before it calls 停止. Derived
#: from the product's own tails rather than from "seems enough": a browser start, one page's
#: first content (``PAGE_WAIT_TIMEOUT``) and the wall back-off a first-row wall spends.
STOP_DEADLINE = 1200.0

#: Measured floor for "this 正文 is still an excerpt": a search-page body ran 35–109 characters
#: while the same answer's own page reached 308 (``docs/crawler_notes.md``). The absolute number
#: is only the *outer* bound — the same question is also judged against the row's own page in
#: ``test_live_zhihu.py`` and in A5, because a constant breaks the day the site lengthens a card.
EXCERPT_CEILING = 300

#: The 8 columns ``ZhihuCrawler.search`` and ``author`` emit, and the 7 the board emits. The
#: crawl matrix deliberately carries no column names, so this tier is the only place those
#: two vocabularies are pinned against the live page.
POST_COLUMNS = ('作者', '标题', '正文', '赞同数', '评论数', '发布时间', '链接', '分类')
HOT_COLUMNS = ('排名', '标题', '链接', '热度', '回答数', '关注数', '摘要')
QUESTION_LINK = re.compile(r'^https://www\.zhihu\.com/question/\d+$')

#: A distinct abundant keyword per case, so the incremental ledger — scoped by node
#: fingerprint, and therefore shared by two canvases whose params match — can never be the
#: reason a later case came up short. A7 is the one case that reuses a word on purpose.
#: The D group shares ONE keyword because it shares one probe crawl: the comment cases want
#: answered links, and asking zhihu for four separate searches of one comment question is
#: four payments for one fact.
KEYWORDS = {
    'A1': '人工智能',
    'A2': '旅游攻略',
    'A3': '高考志愿',
    'A4': '新能源',
    'A5': '职场',
    'A7': '剧本杀',
    'B1': '旅行',
    'B2': '城市规划',
    'D': '美食',
    'E': '机器学习',
    # The E group's own words, one per crawl that could otherwise be refused by a sibling's
    # ledger: E3 walks while its board sibling runs, E5 asks the SAME node two different
    # keywords, E6 dies and resumes, E7 is adopted by a later canvas. Two of those shapes
    # sharing a keyword would mean one of them came up short for a reason the other paid for.
    'E3': ('宠物', '养猫'),
    'E5': '成语',
    'E5B': '诗歌',
    'E6': '咖啡',
    'E7': '博物馆',
    'G1': ('考研', '研究生'),
    'G1B': ('就业', '房价'),
    'G3': ('减肥', '育儿'),
    # The S cells each run a fresh pair of same-platform crawls, so each pair needs two
    # words no earlier ledger has claimed — one shared word between the cells would let
    # the other come up short for a reason its sibling paid for.
    'S1': ('电影', '电视剧'),
    'S2': ('手机', '数码'),
}

#: How many rows the shared comment probe crawls. Six, not three: the probe's job is to hand
#: the comment cases two links whose own card reports 评论数 > 0, and a card label of 0 is
#: common enough that three draws sample to nothing on a good day. Still cheap — the probe
#: never clicks 展开全文.
PROBE_COUNT = 6

#: A phrase with real results and no depth: a search that cannot fill 20 rows here is the
#: site running out, which is the exit this case exists to see named.
THIN_KEYWORD = '氟橡胶硫化工艺'


# ─── the driver every case shares ───────────────────────────────────────


class LiveRun:
    """One real run: started on construction, watched to its verdict, audited on the way out.

    The recorder opens *before* the POST because the earliest lines — the record the run was
    booked against, the validation errors, 「本次跳过」 — are exactly what a case needs when
    something refused it. Leaving the ``with`` block early on a failed assertion still writes
    the audit row, still hands the root logger back, and — the part that protects the *other*
    cases — asks 停止 for a run that is still crawling. See :func:`live_run_harness.abort_run`.
    """

    def __init__(
        self,
        client,
        app_module,
        workflow,
        *,
        case_id,
        mode,
        target,
        timeout=QUICK_TIMEOUT,
        resume_run_id=None,
        queue=None,
        lang='zh',
        named_death_ok=False,
    ):
        """*named_death_ok* is a decision about what a dead session convicts.

        A cookie that dies mid-crawl is a designed path (AGENTS): the node settles ``partial``,
        the run goes ``failed``, ``run.cookieExpired`` is printed and 继续 offers the cursor
        back. For a case that chose its own links that outcome is evidence the session is
        unreliable, so :meth:`assert_l3` refuses it. For a case running links **the user
        stored** — a pasted 评论 URL from a file he edits by hand — it is input age, not code,
        and the component verdicts are what the case is really about. Those cases pass the flag
        and the audit row carries the death as a WARN.
        """
        self.client = client
        self.app = app_module
        self.case_id = case_id
        self.workflow = workflow
        self.mode = mode
        self.target = target
        self.timeout = timeout
        self.lang = lang
        self._named_death_ok = bool(named_death_ok)
        settings = workflow.get('settings') or {}
        self.headless = bool(settings.get('headless', True))
        self.use_profile = settings.get('use_profile')
        self.rec = harness.ConsoleRecorder(client)
        self.run_id = ''
        self.status: dict = {}
        self.record: dict = {}
        # What the run said about the session, and what containment had to do on the way out.
        # Read by ``audit`` even when a case died before :meth:`assert_l3` ever ran.
        self.cookie_expired = False
        self.abort_note: dict = {}
        self._resumed = bool(resume_run_id)
        self._audited = False
        self._closed = False
        # Read BEFORE the resume is asked for, because the ownership proof this case can give
        # is the pair of numbers the resume line itself prints: how many rows it is picking up
        # and when the interrupted attempt started. Afterwards they are the *new* run's.
        self._resume_proof = harness.read_record(client, resume_run_id) if resume_run_id else None
        try:
            self.accepted = harness.start(client, workflow, resume_run_id=resume_run_id, queue=queue, lang=lang)
        except BaseException:
            self.rec.close()
            self._closed = True
            raise
        self.run_id = self.accepted['run_id']

    # ── watching ────────────────────────────────────────────────────────

    def wait(self) -> dict:
        """Block until the run wrote its verdict, then read the record back.

        One budget, not two: the console watch gets the stated timeout and the thread watch
        gets whatever it did not spend. A case that handed ``self.timeout`` to each would cost
        twice its stated wall clock, and on this tier the difference is minutes-to-hours of
        the user's own login.
        """
        self.status = self.rec.pump(self.timeout, run_id=self.run_id)
        left = max(60.0, self.timeout - self.rec.elapsed())
        harness.wait_run_finished(self.app, timeout=left)
        self.status = self.rec.drain()
        if str(self.status.get('outcome') or '') == 'rejected':
            # Validation refused this canvas, so the app returned before opening a record
            # (``app.py`` never creates a row for a rejected run). Reading one here would fail
            # as 「no record for run …」 and report the product's refusal as a missing run —
            # the sentence that convicts is the one the console already printed.
            refused = [
                line
                for line in self.rec.lines
                if harness.names_key(line, 'wf.validation_error') or harness.names_key(line, 'run.rejected')
            ]
            raise AssertionError(
                f'the run was refused by validation, so nothing crawled: {refused or self.rec.text[-1500:]}'
            )
        self.refresh()
        return self.status

    def refresh(self) -> dict:
        self.record = harness.read_record(self.client, self.run_id)
        return self.record

    def rows(self, node_id: str = 'node-1') -> int:
        return harness.stored_rows(self.refresh(), node_id)

    def live_rows(self, node_id: str = 'node-1') -> int:
        """Rows on disk *right now*: a source node's ``row_count`` column is only re-derived
        when the node settles, so a case watching a crawl fill up has to ask the rows."""
        return int(self.app.get_run_store().row_count(self.run_id, node_id))

    def live_statuses(self) -> dict:
        """The store's per-node rows *right now*, mid-crawl — status included.

        ``self.record`` is only read at the wait's end, and a node's ``row_count`` column is
        written by ``finish_node``, which a walking crawl has not reached: so "which of my two
        components is still inside its walk" is answered here, and only together with
        :meth:`live_rows` does it mean anything (a node that is ``running`` still reads 0).
        """
        return self.app.get_run_store().node_statuses(self.run_id)

    def stop(self) -> dict:
        """Press 停止 for this case's own run, and refuse a press that took no record.

        E1, E3 and E4 all cut a live crawl short and the request is the same one the user's
        button makes; a second copy of the guard is how one of them ends up asserting a
        different answer from the endpoint. ``records`` is the proof the Stop found a run to
        own — an idle server answers 「ok」 with nothing stopped, which is not evidence.
        """
        stopped = self.client.post('/api/workflow/stop').get_json()
        assert stopped.get('ok') and stopped.get('records'), f'停止 answered without taking a record: {stopped}'
        return stopped

    def wait_until(self, predicate, *, within: float, what: str) -> None:
        """Poll the console and the rows until *predicate* holds, or fail naming what it waited for.

        The trigger for a mid-crawl 停止 cannot be a sleep: a crawl that stored its first row
        at second 40 and one that stored it at second 900 are the same test, and a fixed wait
        would either press too early (nothing to stop) or too late (a crawl that finished). One
        second per pass, with a status page read on every pass so the transcript this case
        later judges still holds every line the run wrote.

        A run that reaches its verdict first is reported as the failed premise it is, rather
        than being sat on for the whole deadline: 「there was nothing to stop」 is a different
        finding from 「the crawl never started」, and both are different from a timeout.
        """
        deadline = time.monotonic() + within
        while True:
            if predicate():
                return
            self.rec.snapshot()
            if harness.settled(self.rec.status):
                raise AssertionError(
                    f'{what} never happened: this run reached its verdict '
                    f'(outcome={self.rec.status.get("outcome")!r}) before the moment the case '
                    f'was waiting for. Nodes: {self._status_dump()}'
                )
            if time.monotonic() >= deadline:
                raise AssertionError(
                    f'{what} did not happen within {within}s (run {self.run_id}): '
                    f'outcome={self.rec.status.get("outcome")!r} running={self.rec.status.get("running")} '
                    f'stopping={self.rec.status.get("stopping")}, nodes: {self._status_dump()}, '
                    f'{len(self.rec.lines)} console lines, last {self.rec.lines[-5:]!r}'
                )
            time.sleep(1.0)

    def _status_dump(self) -> dict:
        """``{node_id: (status, rows)}`` — the same two columns a reader would ask for first."""
        with contextlib.suppress(Exception):
            return {
                nid: (str(state.get('status') or ''), self.live_rows(nid))
                for nid, state in self.live_statuses().items()
            }
        return {}

    def node(self, node_id: str = 'node-1') -> dict:
        return harness.node_of(self.record, node_id)

    def preview(self, node_id: str = 'node-1', workflow_name=None, limit: int = 500) -> list:
        """The rows this canvas filed, addressed the way the panel addresses them.

        ``workflow_name`` is sent because AGENTS makes a node id a *storage key shared by every
        canvas*: ``_durable_node_rows`` answers nothing rather than guessing when its identity
        lookup misses. The default is the name the run's own record carries, which is the
        backend's precedence (name node, then file name) — so a case cannot read a stranger's
        ``node-2`` and believe it measured its own.
        """
        name = self.record.get('workflow_name') if workflow_name is None else workflow_name
        return harness.preview(self.client, node_id, str(name or ''), limit=limit)

    def verdict(
        self,
        node_id: str = 'node-1',
        *,
        target=None,
        rows=None,
        exits=None,
        bug_lines=None,
        console=None,
    ) -> dict:
        """Grade one node's table against the ask, on the transcript that belongs to it.

        The vocabulary defaults to this case's own *mode* and *shape*: an author walk is
        excused by lines a search never prints, and a headless crawl is excused by the throttle
        a windowed one may not hide behind. *console* defaults to the whole run, which is the
        right slice for a single-component canvas and the wrong one for a four-component run —
        see :meth:`component_verdict`.
        """
        asked = self.target if target is None else target
        kept = self.rows(node_id) if rows is None else rows
        default_exits, default_liars = _vocabulary(self.mode, self.headless)
        return harness.classify_verdict(
            asked,
            kept,
            self.rec.text if console is None else console,
            exits=default_exits if exits is None else exits,
            bug_lines=default_liars if bug_lines is None else bug_lines,
        )

    def component_verdict(self, label: str, record: dict, node_id: str, *, target: int, mode: str) -> dict:
        """This component's own verdict, graded against its own workflow's console.

        A reason named by a sibling is not this component's reason: graded on the whole
        transcript, a 0-row author walk is excused by the search beside it saying 「没有更多了」,
        and a multi-component run — the shape that can hide it — could never be told apart
        from one that said nothing.
        """
        exits, liars = _vocabulary(mode, self.headless)
        return harness.classify_verdict(
            target,
            harness.stored_rows(record, node_id),
            self._slice(label),
            exits=exits,
            bug_lines=liars,
        )

    def _slice(self, label: str) -> str:
        """This workflow's own transcript, and a refusal when the console has none for it.

        Falling back to the whole console would be the false green these helpers exist to
        prevent: graded on everybody's lines, a 0-row component is excused by a sibling's
        「没有更多了」, and one component's 被停止 reads as another's — which is exactly what
        :meth:`component_verdict` and ``ConsoleRecorder.transcript_for`` warn the caller about.
        So a component the console never spoke about is reported as an attribution failure by
        name, not graded on evidence that belongs to its neighbour.
        """
        own = self.rec.transcript_for(label)
        if own:
            return own
        attributed = sorted(name for name, lines in self.rec.wf_lines.items() if lines)
        raise AssertionError(
            f'the console attributed no lines to the workflow {label!r}, so its crawl cannot be '
            f"graded on a sibling's transcript ({self.rec.counted} lines were recorded; the names "
            f'that did get a slice are {attributed})'
        )

    # ── the checks every case owes ──────────────────────────────────────

    def assert_l3(self) -> None:
        """The minimum sequence a run must have narrated, and the shapes it must not have.

        Four sentences in that order, with the last one allowed to be any of the ways a node
        honestly ends. The console is the user's only view of a crawl, so a run that filed
        the right table while saying none of this has already failed at being diagnosable.

        And the transcript must be *this run's*: presence is not ownership. ``run.started``
        carries the run id, so the booking line is matched with the id the case then reads
        rows for; a resume prints no id, so a resumed case proves it by the two numbers the
        resume line does carry, taken from the record before the continue was asked for.
        """
        text = self.rec.text
        opened = 'run.resume_from' if self._resumed else 'run.started'
        finished = ('wf.node_completed', 'run.nodeStopped', 'wf.node_failed', 'run.partial_down', 'run.restored')
        assert self.rec.complete(), (
            f'the recorder holds {len(self.rec.lines)} lines while the console counted {self.rec.counted}: '
            'this transcript is not the whole run, so nothing below can be trusted as evidence'
        )
        assert self.rec.resets == 0, (
            f'this transcript spans {self.rec.resets + 1} console resets, i.e. more than one run, so its '
            'line count proves nothing about the run this case started'
        )
        if self._resumed:
            proof = self._resume_proof or {}
            assert harness.mentions(
                text,
                'run.resume_from',
                at=str(proof.get('started_at') or '?'),
                rows=sum(int(row.get('row_count') or 0) for row in proof.get('nodes') or []),
            ), f'the console did not say it was continuing *this* run ({self.run_id}):\n{text[:2000]}'
        else:
            assert harness.mentions(text, 'run.started', rid=self.run_id), (
                f"nothing booked this console against run {self.run_id}; it is somebody else's "
                f'transcript:\n{text[:2000]}'
            )
        assert harness.names_key(text, 'wf.executing_node'), 'no node was announced as executing'
        assert any(harness.names_key(text, key) for key in finished), (
            f'no node reported finishing ({", ".join(finished)}); the console ended with:\n{text[-2000:]}'
        )
        assert harness.names_key(text, 'run.finished'), 'the run never wrote its closing sentence'
        order = [
            self.rec.first_index(opened),
            self.rec.first_index('wf.executing_node'),
            self.rec.first_index('run.finished'),
        ]
        assert order == sorted(order) and -1 not in order, (
            f'the console is out of order, which means lines were lost: {order}'
        )

        assert 'Traceback' not in text, f'a traceback reached the console:\n{_window_around(text, "Traceback")}'
        died = harness.names_key(text, 'run.cookieExpired')
        self.cookie_expired = bool(self.status.get('cookie_expired')) or died
        if not self._named_death_ok:
            assert not died, f'the session died mid-crawl:\n{_window_around(text, "cookie")}'
            assert self.status.get('cookie_expired') is False, f'F2: the run reported a dead cookie: {self.status}'
        # "One failure, one line" is a statement about a *message*, so it is counted by key.
        # Comparing whole console entries instead compares strings that each begin with the
        # stamping second (``add_log`` writes ``[HH:MM:SS] ``), so the same refusal printed one
        # second apart is two different lines and the check can never fire — which is how a
        # 双打 like the login-wall one docs/live_test_plan.md §6 TX7 records would pass here.
        for key in ('wf.validation_error', 'run.rejected', 'run.cookieExpired'):
            said = self.rec.counts_key(key)
            assert said <= 1, f'{key} printed {said} lines; one fact is one console line'
            if key == 'run.rejected':
                assert said == 0, 'the canvas was refused by validation'
        # The two lines that carry a node id are one fact *per node*. A four-component canvas
        # that loses two of them owes two sentences; counting the key across the whole run read
        # the sibling's honest failure as a 双打 that never happened — and reported it as a
        # console defect instead of naming the two nodes that actually died.
        for key in ('wf.node_failed', 'run.nodeStopped'):
            named = harness.slots_from(self.rec.lines, key, 'nid')
            doubled = sorted({str(one) for one in named if named.count(one) > 1})
            assert not doubled, f'{key} spoke twice about the same node {doubled}: one fact, one line'
        assert not self.rec.overflow, (
            'the status window was out-run, so this transcript has gaps and cannot convict '
            f'{self.target} rows of anything'
        )

    def audit(self, case_id: str, *, verdict, reasons, rows, target, warn=False) -> Path:
        """One audit row plus one transcript, for one crawl. A case with four components writes four."""
        payload = {
            'recorder': self.rec,
            'platform': PLATFORM,
            'mode': self.mode,
            'headless': self.headless,
            'use_profile': '' if self.use_profile is None else self.use_profile,
            'lang': self.lang,
            'target': target,
            'rows': rows,
            'verdict': f'{verdict}/WARN' if warn and verdict != harness.FULL else verdict,
            'reasons': list(reasons),
            'wall_flags': harness.wall_flags(self.rec.text),
            'cookie_expired': bool(getattr(self, 'cookie_expired', False)),
            # What containment had to do on the way out, in the row that explains why the *next*
            # case had to wait for a lane. An empty dict is the case's own answer to "the run
            # settled itself", so the column distinguishes the two instead of going blank.
            'abort': self.abort_note,
            'seconds': self.rec.elapsed(),
        }
        path = harness.audit_dump(case_id, payload)
        self._audited = True
        return path

    def warned(self) -> bool:
        """Whether this run owes a WARN: a dead session it was allowed to name, or a shortfall
        the site explained. A case that lets ``cookie_expired`` stand must say so in its row."""
        return bool(getattr(self, 'cookie_expired', False))

    def finish(self, *, answer=None, node_id: str = 'node-1', warn=False, case_id=None, target=None, rows=None):
        """The case's shared epilogue: the L3 checks, the audit row, and the recorder closed.

        ``warn`` is ORed with :meth:`warned`, so a run that was allowed to name a dead session
        cannot land a plain green row: the artifact is where a WARN must survive even when the
        assertions below it passed.
        """
        answer = answer if answer is not None else self.verdict(node_id, rows=rows, target=target)
        kept = self.rows(node_id) if rows is None else rows
        self.assert_l3()
        self.audit(
            case_id or self.case_id,
            verdict=answer['verdict'],
            reasons=answer['reasons'],
            rows=kept,
            target=self.target if target is None else target,
            warn=bool(warn) or self.warned(),
        )
        self.close()
        return answer

    def close(self) -> None:
        if not self._closed:
            self.rec.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            # Read the table this case died holding *before* containment, so the row states what
            # the assertions saw rather than what the worker filed after they stopped looking.
            kept = 0
            with contextlib.suppress(Exception):
                kept = self.rows() if self.run_id else 0
            if self.run_id and not harness.settled(self.status):
                # The case is over and the crawl is not. Left alone, that worker keeps the
                # platform's lane and the profile directory away from every later case, keeps
                # its browser out of anyone's reach (the client teardown restores
                # ``execution_state`` wholesale, handle included), and keeps narrating lines
                # that the *next* case will fold into its own transcript — where a stranger's
                # 「没有更多了」 can turn a real under-collection into a named, legitimate one.
                # Containment therefore happens before the row is written: the row is where a
                # leak gets reported, and a leak the next case inherits is the finding.
                with contextlib.suppress(Exception):
                    self.abort_note = harness.abort_run(
                        self.client, self.app, self.rec, budget=min(600.0, self.timeout), run_id=self.run_id
                    )
            if not self._audited:
                # A failed assertion is exactly when the transcript matters: the next attempt
                # costs minutes of real crawling and some of the account's patience.
                with contextlib.suppress(Exception):
                    self.audit(
                        self.case_id,
                        verdict='ABORTED',
                        reasons=[f'{exc_type.__name__}: {exc}'],
                        rows=kept,
                        target=self.target,
                    )
        self.close()
        return False


def _vocabulary(mode: str, headless: bool) -> tuple[tuple, tuple]:
    """Which lines excuse a shortfall in this shape, and which of them are known liars.

    Split by mode because the modes end differently: an author tab runs out, a comment panel is
    closed, a board is 30 rows. Split by shape because the *same* sentence is honest in one and
    a lie in the other — ``crawl.zhihu.emptyOrBlocked`` reports the day-by-day headless throttle
    accurately (AGENTS calls a 0-row headless search a legitimate outcome) and reports a
    windowed search's stalled scroll loop as "the site had nothing" (plan §6, Z3/Z6).
    """
    exits, liars = {
        'posts': (ZHIHU_LEGIT_EXITS, ZHIHU_LIES),
        'author': (AUTHOR_EXITS, ZHIHU_LIES),
        'hot': (ZHIHU_LEGIT_EXITS, ()),
        'comments': (COMMENT_EXITS, ()),
    }.get(str(mode or ''), (ZHIHU_LEGIT_EXITS, ZHIHU_LIES))
    if headless and str(mode or '') in ('posts', 'author'):
        exits = tuple(exits) + HEADLESS_REFUSALS
        liars = tuple(key for key in liars if key not in HEADLESS_REFUSALS)
    return exits, liars


def _window_around(text: str, needle: str, width: int = 600) -> str:
    at = text.find(needle)
    return text[max(0, at - width) : at + width] if at >= 0 else text[-width:]


# ─── shared builders ────────────────────────────────────────────────────


def posts_canvas(target: int, keyword: str, *, headless=False, full_body=True, **overrides):
    return harness.canvas_for(
        PLATFORM,
        'posts',
        settings=harness.run_settings('serial', headless),
        keyword=keyword,
        target_count=target,
        full_body=full_body,
        **overrides,
    )


def hot_canvas(target: int, *, headless=False, **overrides):
    return harness.canvas_for(
        PLATFORM, 'hot', settings=harness.run_settings('serial', headless), target_count=target, **overrides
    )


def comments_canvas(urls, *, limit=20, headless=False, **overrides):
    pasted = urls if isinstance(urls, str) else '\n'.join(urls)
    return harness.canvas_for(
        PLATFORM,
        'comments',
        settings=harness.run_settings('serial', headless),
        urls=pasted,
        comment_limit=limit,
        **overrides,
    )


def author_canvas(token: str, target: int, *, headless=False):
    return harness.canvas_for(
        PLATFORM, 'author', settings=harness.run_settings('serial', headless), author=token, target_count=target
    )


def _answer_links(rows) -> list:
    """The rows a 阅读全文 click can reach, as ``(link, reported comment count)`` pairs.

    Only ``/answer/`` links qualify — ``ZhihuCrawler._is_answer_card`` says so and the
    comment panel's opener is a button on that page. A link with no panel is the silent
    zero this tier refuses to accept, so the reported 评论数 is carried along with it.
    """
    pairs = []
    for row in rows:
        link = str(row.get('链接') or '')
        if '/answer/' in link:
            pairs.append((link, int(row.get('评论数') or 0)))
    pairs.sort(key=lambda pair: -pair[1])
    return pairs


#: Answer links found by a real probe crawl this session, by keyword. The comment cases want
#: the same fact — "a zhihu answer that has comments right now" — and each probe is a full
#: browser plus a full search, so asking four times is four payments for one answer. This is
#: the :func:`tests.live_site.conftest.weibo_windowed` shape, module-level because the probe is
#: an app-driven run and the tier's ``client`` fixture is per test: a session fixture could not
#: own one. A case run alone (``-k test_d3``) simply pays for its own.
_ANSWER_PROBE: dict = {}


def _probe_answers(client, app_module, *, case_id: str, keyword: str, count: int = PROBE_COUNT) -> list:
    """A small real search, returning its answer links ordered by the comments they report.

    A comment crawl pointed at a remembered URL tests the crawler's error handling and
    nothing else: the panel has to be opened on something that has comments *now*. The probe
    is always a **windowed** crawl — it is the means of finding a commented answer, not the
    thing under test, and a headless search is throttled day-by-day (risk 40362), so
    borrowing one would make the comment cases red for a reason that belongs to another
    mode. The probe is itself a run, so it is audited under its own ``<case>.probe`` row.

    ``count`` rows are crawled rather than the minimum the caller needs: the reported 评论数
    is a card label and a lot of cards carry 0, so a two-row draw from a three-row probe
    samples to "no commented answer found" on an ordinary day.
    """
    cached = _ANSWER_PROBE.get(keyword)
    if cached is not None:
        return cached
    with LiveRun(
        client,
        app_module,
        posts_canvas(count, keyword, headless=False, full_body=False),
        case_id=f'{case_id}.probe',
        mode='posts',
        target=count,
        timeout=QUICK_TIMEOUT,
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'the probe crawl for {keyword!r} did not deliver: {answer}'
        run.finish(answer=answer)
    pairs = _answer_links(rows)
    assert pairs, f'the {keyword!r} probe returned no /answer/ link to comment on: {[r.get("链接") for r in rows]}'
    _ANSWER_PROBE[keyword] = pairs
    return pairs


def _commented_pairs(pairs: list, *, need: int, keyword: str) -> list:
    """The ``need`` links whose own card reports the most comments, or a red that says supply.

    Naming the counts and the keyword matters: "found no commented answer" on a probe that
    really crawled six rows is a statement about the day's supply, and a reader must be able to
    tell that from a probe that crawled the wrong thing.
    """
    chosen = [link for link, reported in pairs if reported > 0][:need]
    assert len(chosen) == need, (
        f'the {keyword!r} probe crawled {len(pairs)} answer links and reported comment counts '
        f'{[reported for _link, reported in pairs]}; this crawl needs {need} of them above zero. '
        'That is the site supply on a card label, not the comment walker: pick a livelier keyword.'
    )
    return chosen


def _discover_people_token(live_crawler, keyword: str) -> str:
    """A profile token taken off a live question page, with the browser handed back first.

    Re-implemented here rather than imported from ``test_live_zhihu_author`` because the
    release contract differs: the tier's crawler holds the platform's turn *and* the profile
    directory for its whole life, and an app-driven crawl takes the same two locks. Leaving
    this one open parks the run inside ``crawl_gate`` for 900 s with no browser on screen —
    the 15-minute no-output stall this tier already documents.
    """
    crawler = live_crawler(PLATFORM, headless=False)
    people = re.compile(r'/people/([^/?#]+)')
    try:
        rows = crawler.search(keyword, target_count=3)
        assert rows, f'the discovery search for {keyword!r} returned nothing, so there is no author to ask about'
        question = next((str(row.get('链接') or '') for row in rows if '/question/' in str(row.get('链接') or '')), '')
        assert question, f'no question-type result to read an author off: {[row.get("链接") for row in rows]}'
        qid = question.split('/question/', 1)[-1].split('/')[0]
        crawler.open(f'https://www.zhihu.com/question/{qid}')
        anchors = crawler.driver.find_elements('css selector', 'a[href*="/people/"]')
        hrefs = [anchor.get_attribute('href') or '' for anchor in anchors]
        tokens = [match.group(1) for href in hrefs if (match := people.search(href))]
        tokens = [token for token in tokens if token and token not in ('login', 'signup', 'setting')]
        assert tokens, 'the question page handed over no profile links to crawl'
        return tokens[0]
    finally:
        live_crawler.release(crawler)


def _assert_post_rows(rows, *, minimum: int, columns=POST_COLUMNS) -> None:
    """Shape, not only a count: a table of the right size and the wrong columns is a red."""
    assert len(rows) >= minimum, f'expected {minimum} rows, got {len(rows)}'
    links = [str(row.get('链接') or '') for row in rows]
    assert all(links), f'a row without its own address cannot be resumed or deduped: {links}'
    assert len(set(links)) == len(links), 'rows repeat a link, so the ledger identity (链接) is broken'
    for row in rows:
        missing = [column for column in columns if column not in row]
        assert not missing, f'a column the crawler promised is absent: {missing}'
        assert str(row.get('正文') or '').strip() or str(row.get('标题') or '').strip(), f'empty row: {row}'


# ─── A · 关键词搜索 (posts) ─────────────────────────────────────────────


def test_a1_windowed_serial_search_delivers_ten_rows_with_bodies(client, app_module, monkeypatch):
    """A1 — the ordinary case end to end: ten rows, eight columns, the target announced.

    No 三一致 leg here, and that is the shape rather than an oversight: A1's canvas is one
    source node, and a source checkpoints its rows without writing a file — the exported CSV
    only exists once an output node runs. The third leg (export == rows == preview) is walked
    by H1, whose saved canvas has one per component.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(client, app_module, posts_canvas(10, KEYWORDS['A1']), case_id='A1', mode='posts', target=10) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'a windowed search on a rich keyword must fill: {answer}'
        assert run.rows() == 10, run.record
        assert harness.names_key(run.rec.text, 'crawl.zhihu.target_reached'), (
            'the walk never said it reached the number'
        )
        _assert_post_rows(run.preview('node-1'), minimum=10)
        run.finish(answer=answer)


def test_a2_twenty_rows_cost_more_screens_but_still_arrive(client, app_module, monkeypatch):
    """A2 — double the ask, same promise. One target cannot tell a thin day apart from a
    scroll loop that stops early; two of them can."""
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(
        client,
        app_module,
        posts_canvas(20, KEYWORDS['A2']),
        case_id='A2',
        mode='posts',
        target=20,
        timeout=DEEP_TIMEOUT,
    ) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'20 rows on {KEYWORDS["A2"]!r} is supply the site has: {answer}'
        assert run.rows() == 20
        _assert_post_rows(run.preview('node-1'), minimum=20)
        run.finish(answer=answer)


def test_a3_forty_rows_prove_the_scroll_loop_and_nothing_else(client, app_module, monkeypatch):
    """A3 — the multi-screen proof. Past one screen of ~20 cards, and the console must show a
    walk that kept growing: 「未加载新内容」 as the ending here means the scroll stopped working."""
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(
        client,
        app_module,
        posts_canvas(DEEP_TARGET, KEYWORDS['A3']),
        case_id='A3',
        mode='posts',
        target=DEEP_TARGET,
        timeout=DEEP_TIMEOUT,
    ) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'{DEEP_TARGET} rows is two screens of a rich keyword: {answer}'
        assert run.rows() == DEEP_TARGET
        assert harness.names_key(run.rec.text, 'crawl.zhihu.target_reached'), 'the target line is the evidence'
        # FULL does not excuse the liars: a walk that reached 40 while printing 「未加载新内容」
        # once and then growing again says the growth check is wrong, and that is Z6.
        for stalled in ZHIHU_LIES:
            assert not harness.names_key(run.rec.text, stalled), f'the walk named {stalled} on the way to its target'
        _assert_post_rows(run.preview('node-1'), minimum=DEEP_TARGET)
        run.finish(answer=answer)


def test_a4_headless_search_is_full_or_names_the_refusal(client, app_module, monkeypatch):
    """A4 — the strict-plus-WARN rule for headless. zhihu throttles a headless session
    day-by-day (risk 40362), so a short crawl is legitimate only when the console says which
    wall it met; a silent shortfall stays a red, and a WARN is still written down.

    The rule is graded by the *verdict*, not by a three-word vocabulary: this mode's own
    honest endings include the walk saying 「没有更多了」 (zhihu answers a throttled session by
    falling through to a scroll loop that finds nothing, ``crawlers/zhihu.py``). Refusing
    everything but three named walls would red a documented outcome — and ``crawl.riskBlocked``
    on a login-wall retry is an ``add_log``, not a raised refusal, so the old shape red-flagged
    a crawl whose console had explained itself in full.
    """
    harness.real_jar(monkeypatch, app_module)
    canvas = posts_canvas(10, KEYWORDS['A4'], headless=True)
    with LiveRun(client, app_module, canvas, case_id='A4', mode='posts', target=10) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] != harness.SILENT_SHORT, (
            f'a headless search came back {run.rows()}/10 naming no wall, no risk control and no end of '
            f'supply, which is the silent under-report rather than a throttle:\n{run.rec.text[-2500:]}'
        )
        if answer['verdict'] == harness.FULL:
            assert run.rows() == 10, f'FULL asks for exactly the target: {run.rows()}'
            _assert_post_rows(run.preview('node-1'), minimum=10)
        run.finish(answer=answer, warn=answer['verdict'] != harness.FULL)


def test_a5_excerpt_mode_never_clicks_and_says_so(client, app_module, monkeypatch):
    """A5 — 「展开全文」 off is a different crawl, and it must be visible twice over: the line
    that announces it, and a 正文 column that stays the length of an excerpt.

    ``EXCERPT_CEILING`` is the outer bound only. The *page-relative* half of that promise — a
    stored body measured against the length the row's own answer page holds — is measured in
    ``test_live_zhihu.py::test_an_expanded_row_carries_its_own_pages_text``, which reopens the
    link in the same browser. This case does not buy a second browser for it: a run-level case
    has no crawler to hand, and taking the tier's ``live_crawler`` fixture would import its
    skips into a file that promises none.
    """
    harness.real_jar(monkeypatch, app_module)
    canvas = posts_canvas(10, KEYWORDS['A5'], full_body=False)
    with LiveRun(client, app_module, canvas, case_id='A5', mode='posts', target=10) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'an excerpt walk is the cheaper one, so short is a bug: {answer}'
        assert harness.names_key(run.rec.text, 'crawl.zhihu.excerpt_only'), (
            'the switch off has to be stated, or a reader cannot tell a thin page from a dead click'
        )
        rows = run.preview('node-1')
        _assert_post_rows(rows, minimum=10)
        longest = max(len(str(row.get('正文') or '')) for row in rows)
        assert longest < EXCERPT_CEILING, (
            f'展开全文 is off but a row kept {longest} characters; a measured expanded answer sits at '
            f'{EXCERPT_CEILING}, so something clicked anyway'
        )
        run.finish(answer=answer)


def test_a6_a_thin_keyword_must_end_by_saying_it_is_thin(client, app_module, monkeypatch):
    """A6 — the other half of the same coin: under target is fine when the site said 「没有
    更多了」. Not when it said nothing, and not when the only thing it said was the line §6
    measures as a false one (Z6's 「未加载新内容」 after a single non-growing check).

    The ask is deliberately past anything this keyword can answer (measured twice on this tier:
    20 rows filled it, and 60 did too). Asking past the supply is the only way to reach the exit
    at all — a target the page can meet grades FULL and never has to say why it stopped — and
    ``NAMED_SHORT`` already carries the strict half: a verdict of that name is only reachable
    through an honest exit, because §5 keeps the liar lines out of every whitelist.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(client, app_module, posts_canvas(200, THIN_KEYWORD), case_id='A6', mode='posts', target=200) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.NAMED_SHORT, (
            f'{THIN_KEYWORD!r} is asked for 200 because it is chosen for its thin supply. FULL here '
            f'means the phrase is no longer thin (pick a rarer one); a silent shortfall, or one '
            f'excused only by a line that lies, is a bug either way: {answer}'
        )
        run.finish(answer=answer)


def test_a7_collecting_the_same_thing_twice_is_refused_by_name(client, app_module, monkeypatch):
    """A7 — the incremental ledger with 「重新采集」 deliberately left off.

    Two asks from one node, and the second may not store what the first already filed — and if the
    ledger cut the table down, it must say so, because 「the site had nothing more」 and 「we
    already had it」 look identical in a table that did not grow.

    The BOARD, not a keyword, is what makes that provable. This cell first asked twice about one
    keyword and the second run delivered five rows nobody had seen: measured, zhihu rotates the
    cards it serves a query, so 「the same ask」 is not 「the same items」, and a ledger test cannot
    be built on a supply that moves underneath it. The hot board is one fetch of a ranked list
    that holds its 30 questions for minutes (C1/C2 measure exactly that), so a repeat visit is
    genuinely the same item set the ledger has to refuse.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(client, app_module, hot_canvas(30, recrawl=False), case_id='A7a', mode='hot', target=30) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'the first pass has nothing to be refused for: {answer}'
        first = [str(row.get('链接') or '') for row in run.preview('node-1')]
        assert len(first) == 30, f'the board itself did not fill: {len(first)} rows'
        run.finish(answer=answer)

    with LiveRun(client, app_module, hot_canvas(30, recrawl=False), case_id='A7b', mode='hot', target=30) as run:
        run.wait()
        answer = run.verdict()
        second = [str(row.get('链接') or '') for row in run.preview('node-1')]
        stolen = sorted(set(first) & set(second))
        assert not stolen, (
            f'the ledger let {len(stolen)} already-collected questions through a second time '
            f'(重采 — the user pays twice and the table doubles): {stolen[:3]}'
        )
        assert answer['verdict'] != harness.SILENT_SHORT, (
            f'the re-run came back {len(second)}/30 having named nothing: {answer}'
        )
        if len(second) < 30:
            named = [
                key for key in ('run.dedupe_skipped', 'run.dedupe_all_skipped') if harness.names_key(run.rec.text, key)
            ]
            assert named, (
                f'the ledger held back {30 - len(second)} of the board and the console said nothing '
                'about it — an unexplained shortfall is what this cell exists to catch'
            )
        run.finish(answer=answer, warn=answer['verdict'] != harness.FULL)
        run.wait()
        answer = run.verdict()
        assert run.rows() == 0, f'the ledger let {run.rows()} already-collected rows through twice'
        assert answer['verdict'] == harness.NAMED_SHORT and 'run.dedupe_all_skipped' in answer['reasons'], (
            f'an all-seen re-run must be loud, not empty: {answer}'
        )
        run.finish(answer=answer)


# ─── B · 某作者的作品 (author) ──────────────────────────────────────────


def test_b1_an_authors_own_list_is_collected_or_named_short(client, app_module, monkeypatch, request):
    """B1 — author mode through the app, on a token discovered during this run.

    A stored token rots, and a dead profile page answers with an empty table that looks
    exactly like a broken parser, so discovery is what makes this case mean anything.

    Supply rather than code is what can make 10 rows unreachable, and the honest line for it is
    the per-tab report 「这个标签页收完」 (``crawl.zhihu.authorTabDone``), which carries the count
    and the reason it stopped. ``crawl.zhihu.authorTabEmpty`` is not: the plan lists it as Z16 —
    a slowly rendered tab reported as "this person never published" — so naming *that* instead of
    delivering is red here, by the same rule that keeps 「未加载新内容」 out of the whitelist.

    The tier's ``live_crawler`` fixture is taken *lazily*, after the cookie assert, because that
    fixture skips when the jar is empty and this file promises no skips: an author case that
    cannot start without the saved session says so as a failure of its own.
    """
    jar = harness.real_jar(monkeypatch, app_module)
    assert harness.has_cookie(PLATFORM), f'B1 needs the saved {PLATFORM} session in {jar}'
    token = _discover_people_token(request.getfixturevalue('live_crawler'), KEYWORDS['B1'])
    with LiveRun(
        client, app_module, author_canvas(token, 10), case_id='B1', mode='author', target=10, timeout=DEEP_TIMEOUT
    ) as run:
        run.wait()
        answer = run.verdict()
        assert not harness.names_key(run.rec.text, 'crawl.zhihu.authorTabEmpty'), (
            f'the walk reported an empty tab for {token}, which plan §6 measures as a slow-render '
            f'lie (Z16) rather than a supply answer:\n{run.rec.text[-2500:]}'
        )
        assert answer['verdict'] != harness.SILENT_SHORT, (
            f'{token} came back {run.rows()}/10 with nothing named:\n{run.rec.text[-2500:]}'
        )
        if answer['verdict'] == harness.FULL:
            _assert_post_rows(run.preview('node-1'), minimum=10)
        # Any undershoot is a WARN, whatever named it: "the artifact shows what sat out" is the
        # promise, and filing a 3/10 author crawl as a plain green breaks it.
        run.finish(answer=answer, warn=answer['verdict'] != harness.FULL)


def test_b2_headless_author_works_after_the_disguise(client, app_module, monkeypatch, request):
    """B2 — the #148 fingerprint disguise, measured on this very page (20→40 cards headless
    where a bare headless window rendered 0). Rows, or a refusal that names itself: the
    silent empty is exactly what the disguise was built to remove. Lazy fixture and cookie
    precondition for the same reason as B1."""
    jar = harness.real_jar(monkeypatch, app_module)
    assert harness.has_cookie(PLATFORM), f'B2 needs the saved {PLATFORM} session in {jar}'
    token = _discover_people_token(request.getfixturevalue('live_crawler'), KEYWORDS['B2'])
    canvas = author_canvas(token, 5, headless=True)
    with LiveRun(client, app_module, canvas, case_id='B2', mode='author', target=5) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] != harness.SILENT_SHORT, (
            f'a headless author crawl came back {run.rows()}/5 naming neither risk control nor an empty '
            f'tab, which is the shape the disguise retired:\n{run.rec.text[-2500:]}'
        )
        assert run.rows() > 0 or answer['verdict'] == harness.NAMED_SHORT
        run.finish(answer=answer, warn=answer['verdict'] == harness.NAMED_SHORT)


# ─── C · 热榜 (hot) ─────────────────────────────────────────────────────


def _assert_hot_rows(rows, *, minimum: int) -> None:
    """The board's own seven columns, and none of the ones its payload only fills with noise.

    「作者」 and 「评论数」 are deliberately absent from ``_hot_row``: all 30 rows carry the
    literal 「用户」 and a zero there, so a column of them is a lie a user reads as data.
    """
    assert len(rows) >= minimum, f'expected {minimum} board rows, got {len(rows)}'
    for row in rows:
        assert set(row) == set(HOT_COLUMNS), f'the board row is not its seven columns: {sorted(row)}'
        assert QUESTION_LINK.match(str(row.get('链接') or '')), f'the link was not rewritten: {row.get("链接")}'
        assert isinstance(row.get('热度'), int), f'热度 is not a number: {row}'
        assert isinstance(row.get('回答数'), int), f'回答数 is not a number: {row}'
    links = [str(row.get('链接')) for row in rows]
    assert len(set(links)) == len(links), 'the board repeated a question'
    ranks = [int(row.get('排名')) for row in rows]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks), f'排名 is not a ranking: {ranks}'


def test_c1_the_hot_board_delivers_its_thirty_rows_and_seven_columns(client, app_module, monkeypatch):
    """C1 — one in-page fetch, the whole board, no request per row."""
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(client, app_module, hot_canvas(30), case_id='C1', mode='hot', target=30) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'the board holds 30 rows and was asked for 30: {answer}'
        assert run.rows() == 30
        _assert_hot_rows(run.preview('node-1'), minimum=30)
        run.finish(answer=answer)


def test_c2_asking_the_board_for_more_than_it_holds_is_answered_out_loud(client, app_module, monkeypatch):
    """C2 — the target is the user's number and the board's size is the site's, so the
    shortfall has to be a sentence (``crawl.zhihu.hotCapped``) rather than a quiet table."""
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(client, app_module, hot_canvas(40), case_id='C2', mode='hot', target=40) as run:
        run.wait()
        assert run.rows() == 30, f'the board is 30 rows; anything else means the cap moved: {run.rows()}'
        assert harness.names_key(run.rec.text, 'crawl.zhihu.hotCapped'), 'the cap must be stated, not padded'
        _assert_hot_rows(run.preview('node-1'), minimum=30)
        answer = run.verdict()
        assert answer['verdict'] == harness.NAMED_SHORT and 'crawl.zhihu.hotCapped' in answer['reasons'], answer
        # The cap line also carries the board's own size, and the plan wants that fact read
        # off the message rather than pasted: 30 is both the row count and the {board} slot.
        assert harness.numbers_from(run.rec.lines, 'crawl.zhihu.hotCapped', 'board') == [30], (
            'the cap sentence did not state the size the crawler saw, so a future board of 52 '
            'would still be graded against a constant in this file'
        )
        run.finish(answer=answer)


def test_c3_headless_board_in_english_is_a_plain_fetch(client, app_module, monkeypatch):
    """C3 — hot reads JSON from inside one loaded document, so the throttle that costs a
    headless *search* its rows has no part to play here: FULL, and no WARN is on offer.

    This is also the matrix's English leg (``docs/live_test_plan.md`` §4: 「lang:zh 为主、至少
    一条 en 对照」). It is the right case to pay for it with: one fetch, no scroll, no expansion,
    and every assertion in this tier resolves its console lines through :mod:`i18n` in *both*
    languages — so a run narrated in English exercises exactly the path a pasted sentence would
    have broken, and the worker's thread-local ``set_lang`` has to have actually worked for the
    booking line to be findable at all.
    """
    harness.real_jar(monkeypatch, app_module)
    canvas = harness.canvas_for(PLATFORM, 'hot', settings=harness.run_settings('serial', True), target_count=30)
    with LiveRun(client, app_module, canvas, case_id='C3', mode='hot', target=30, lang='en') as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'a headless board crawl has no excuse to be short: {answer}'
        _assert_hot_rows(run.preview('node-1'), minimum=30)
        run.finish(answer=answer)


# ─── D · 评论 (comments) ────────────────────────────────────────────────


def _done_total(recorder) -> int:
    """The row figure ``comment.done`` stated, read out of the catalogue's own template.

    Not a pasted regex for the sentence: the summary is the executor's promise about what it
    filed, so the number is taken from the slot it occupies in :mod:`i18n` — which keeps both
    languages and moves with a reword instead of turning four cases red with a message that
    blames the crawler for a copy edit.
    """
    totals = harness.numbers_from(recorder.lines, 'comment.done', 'rows')
    assert len(set(totals)) <= 1, f'the summary named more than one total for one node: {sorted(set(totals))}'
    assert totals, 'the comment node never printed its summary line'
    return totals[0]


def _comment_ask(*, limit: int, urls: list) -> int:
    """What a comment node was actually asked for, as a row count.

    ``comment_limit`` is per article, so the ask is the product — never 1. An open-ended walk
    (``comment_limit: 0``, 「采集全部评论」) has no row budget the user wrote down, so the only
    number it can be graded against is one row per panel it was told to open.
    """
    return (limit or 0) * len(urls) if limit else max(1, len(urls))


def _comment_verdict(run, *, node_id: str, urls: list, limit: int, console=None, rows=None) -> dict:
    """Grade a comment crawl against the ask it really made, article by article.

    ``comment_limit`` is *per article*, so the ask is ``limit × links`` — grading it as 1 (the
    "at least one row arrived" reading) records a 2-of-40 crawl as FULL and puts 1 in the
    artifact's ``target`` column, which is the weakened assertion this tier was told not to
    write. ``limit == 0`` is 「采集全部评论」 and has no row budget at all, so the only target it
    can be held to is the total its own per-article lines reported — recorded with the verdict
    so the artifact says what was measured.

    What makes a shortfall honest is not a whitelist here but a *number*: every asked article
    printed its own line, and none of them printed zero. An article that added nothing *and*
    named nothing — no closed section, no missing panel, no blocked link — is the silent zero
    in a mode that has no other signal, and it is graded SILENT_SHORT.
    """
    text = run.rec.text if console is None else console
    reported = harness.numbers_from(run.rec.lines, 'comment.article', 'n')
    assert len(reported) == len(urls), (
        f'{len(urls)} links were asked for and {len(reported)} printed their own 「评论：…」 line: '
        f'{reported}. An article the node walked past without reporting is a silent skip.'
    )
    # A caller that already resolved WHICH record holds this node hands the count in: reading it
    # off ``run.record`` would ask workflow zero's row for another component's node, which is how
    # the serial acceptance run failed even after its records were mapped correctly.
    kept = run.rows(node_id) if rows is None else rows
    ask = (limit or 0) * len(urls)
    refused = [key for key in COMMENT_EXITS if harness.names_key(text, key)]
    if kept >= (ask or 1):
        return {'verdict': harness.FULL, 'reasons': list(refused)}
    if any(count == 0 for count in reported) and not refused:
        return {
            'verdict': harness.SILENT_SHORT,
            'reasons': [f'{reported.count(0)} of {len(urls)} articles added nothing and named no reason'],
        }
    short = f'asked {ask} across {len(urls)} links, kept {kept}' if limit else f'no row budget (全部); kept {kept}'
    return {
        'verdict': harness.NAMED_SHORT,
        'reasons': [*(refused or ['comment.article']), short],
    }


def _assert_comment_rows(rows, *, minimum: int, console: str = '') -> None:
    """What a zhihu comment table owes, measured on the page rather than assumed.

    Two of this cell's assertions used to rest on a wrong reading of the site: 评论时间 was called
    a structural blank and 点赞数 a structural zero, when in fact the product never looked
    (``crawlers/comments_zhihu.py`` wrote both constants) and the panel does carry a time —
    「14 小时前」 on a recent comment, 「2019-08-15」 on an old one. So a table where NOT ONE row
    names a moment is now read as the dead column it is, not as a site answer.

    An empty 评论者 is different: measured on one panel, 2 of 12 items answer only at an ancestor
    depth that spans their neighbours, which is how a fixed-depth climb used to name the wrong
    person. The crawler now refuses to climb past its own comment, so a genuinely anonymous row
    can come back blank — tolerated as a site answer in a minority, and convicting a whole panel
    that is blank (that is the selector dying again) or one that went unmentioned (the engine
    prints its count by name, and silence here would be the same lie in a new shape).
    """
    assert len(rows) >= minimum, f'expected {minimum} comment rows, got {len(rows)}'
    authorless = [row for row in rows if not str(row.get('评论者') or '').strip()]
    for row in rows:
        assert str(row.get('评论内容') or '').strip(), f'empty comment body: {row}'
        assert row.get('平台') == PLATFORM, f'wrong platform tag on a comment row: {row}'
    assert len(authorless) < len(rows), (
        f'none of the {len(rows)} comment rows carries an author, which is a dead read and not an '
        f'anonymous panel: {rows[0]}'
    )
    assert any(str(row.get('评论时间') or '').strip() for row in rows), (
        f'no comment row carries a moment, though the panel was measured to show one on every '
        f'item — the column is unread again: {rows[0]}'
    )
    if authorless and console:
        named = [line for line in console.splitlines() if harness.names_key(line, 'comment.zhihuNoAuthor')]
        assert named, (
            f'{len(authorless)} of {len(rows)} rows came back without an author and the console '
            'never said so — an unexplained blank is how a dead selector hides'
        )


def test_d1_two_live_answers_carry_their_comment_panels(client, app_module, monkeypatch):
    """D1 — comments picked from a live probe in the same session, by the probe's own reported
    评论数. Two 评论：… lines (one per article) and a summary whose number is the number the
    store holds — and the verdict is graded against the ask (20 per link), never against 1."""
    harness.real_jar(monkeypatch, app_module)
    pairs = _probe_answers(client, app_module, case_id='D1', keyword=KEYWORDS['D'])
    commented = _commented_pairs(pairs, need=2, keyword=KEYWORDS['D'])

    canvas = comments_canvas(commented, limit=20)
    with LiveRun(
        client,
        app_module,
        canvas,
        case_id='D1',
        mode='comments',
        target=20 * len(commented),
        timeout=COMMENT_TIMEOUT,
    ) as run:
        run.wait()
        stored = run.rows()
        assert stored > 0, f'neither of {commented} delivered a single comment:\n{run.rec.text[-2500:]}'
        articles = run.rec.counts_key('comment.article')
        assert articles == len(commented), f'{len(commented)} articles were asked for, {articles} reported back'
        assert stored == _done_total(run.rec), 'the summary line and the stored table disagree'
        _assert_comment_rows(run.preview('node-1'), minimum=1, console=run.rec.text)
        answer = _comment_verdict(run, node_id='node-1', urls=commented, limit=20)
        run.finish(answer=answer, warn=answer['verdict'] != harness.FULL)


def test_d2_a_wired_comments_node_crawls_the_links_its_parent_found(client, app_module, monkeypatch):
    """D2 — the ``fed_by`` path end to end: the upstream 链接 column replaces the textarea,
    and every comment is attributed to a link this canvas actually crawled."""
    harness.real_jar(monkeypatch, app_module)
    canvas = harness.posts_then_comments_canvas(
        PLATFORM,
        posts={'keyword': KEYWORDS['D'], 'target_count': 3, 'full_body': False},
        comments={'comment_limit': 3},
        settings=harness.run_settings('serial', False),
    )
    with LiveRun(
        client,
        app_module,
        canvas,
        case_id='D2',
        mode='comments',
        target=3 * 3,
        timeout=COMMENT_TIMEOUT,
    ) as run:
        run.wait()
        fed = run.preview('node-2')
        posts = run.preview('node-1')
        assert run.rows('node-2') > 0, f'the feed produced no comment rows:\n{run.rec.text[-2500:]}'
        # A loop over an empty table measures nothing, and `/api/data/preview` legitimately
        # answers empty when its identity lookup misses — so the size of the set that was
        # actually walked is asserted before the walk (AGENTS: report how much you measured).
        assert len(fed) == run.rows('node-2'), (
            f'the preview returned {len(fed)} rows while the store holds {run.rows("node-2")}: '
            'the attribution loop below would have proved nothing'
        )
        sources = {str(row.get('链接') or '') for row in posts}
        assert sources, 'the upstream node stored nothing for the feed to read'
        for row in fed:
            assert str(row.get('文章URL') or '') in sources, (
                f'a comment is attributed to a link this canvas never crawled: {row.get("文章URL")}'
            )
        assert run.rec.counts_key('comment.article') >= 1, 'the comments node ran without reporting a single article'
        asked = [str(row.get('链接') or '') for row in posts][:3]
        answer = _comment_verdict(run, node_id='node-2', urls=asked, limit=3)
        run.finish(answer=answer, node_id='node-2', warn=answer['verdict'] != harness.FULL)


def test_d3_headless_comments_match_the_windowed_shape(client, app_module, monkeypatch):
    """D3 — #148 measured zhihu comments 5/5 headless against 5/5 in a window and retired
    the forced window. The same links, the same expectation, no popup: the probe that finds
    them is windowed, because a headless *search* is throttled day-by-day and a comment case
    must not inherit that mode's refusal.
    """
    harness.real_jar(monkeypatch, app_module)
    pairs = _probe_answers(client, app_module, case_id='D3', keyword=KEYWORDS['D'])
    best = _commented_pairs(pairs, need=1, keyword=KEYWORDS['D'])
    canvas = comments_canvas(best, limit=10, headless=True)
    with LiveRun(
        client,
        app_module,
        canvas,
        case_id='D3',
        mode='comments',
        target=10 * len(best),
        timeout=COMMENT_TIMEOUT,
    ) as run:
        run.wait()
        stored = run.rows()
        assert stored > 0, f'a headless comment walk stored nothing:\n{run.rec.text[-2500:]}'
        assert stored == _done_total(run.rec)
        _assert_comment_rows(run.preview('node-1'), minimum=1, console=run.rec.text)
        answer = _comment_verdict(run, node_id='node-1', urls=best, limit=10)
        run.finish(answer=answer, warn=answer['verdict'] != harness.FULL)


def test_d4_no_limit_means_the_whole_panel_and_the_sum_still_ties(client, app_module, monkeypatch):
    """D4 — ``comment_limit: 0`` is 「采集全部评论」, so the promise is now checked against the
    site's own number and not only against itself: what the summary counted is what the store
    holds, and the panel's 「N 条评论」 opener is what the walk must have come away with.

    That external denominator is the whole point of this cell after the paging measurement
    (``backend/test_zhihu_comment_structure.py``): an unlimited walk used to file **12 rows of a
    panel whose button said 261**, and grade internally consistent while doing it — the summary,
    the store and the table all agreed on 12. Agreement is not completeness, so the engine now
    reports a shortfall by name (``comment.zhihuPanelShort``) and this cell refuses to be green
    while that line is in its console.
    """
    harness.real_jar(monkeypatch, app_module)
    pairs = _probe_answers(client, app_module, case_id='D4', keyword=KEYWORDS['D'])
    canvas = comments_canvas(pairs[0][0], limit=0)
    with LiveRun(client, app_module, canvas, case_id='D4', mode='comments', target=1, timeout=COMMENT_TIMEOUT) as run:
        run.wait()
        stored = run.rows()
        assert stored > 0, f'{pairs[0][0]} stored no comments:\n{run.rec.text[-2500:]}'
        assert stored == _done_total(run.rec), 'an unlimited walk must still agree with itself'
        assert run.rec.counts_key('comment.article') == 1, 'one link, one article line'
        left_short = [line for line in run.rec.lines if harness.names_key(line, 'comment.zhihuPanelShort')]
        assert not left_short, f'「采集全部评论」 left panels short of the numbers printed on the page: {left_short}'
        _assert_comment_rows(run.preview('node-1'), minimum=1, console=run.rec.text)
        answer = _comment_verdict(run, node_id='node-1', urls=[pairs[0][0]], limit=0)
        # The artifact's ask column is the figure a reader can check the table against — the
        # comment count the article itself reported — never a placeholder 1.
        run.finish(answer=answer, target=int(pairs[0][1] or stored), warn=answer['verdict'] != harness.FULL)


# ─── E · 停止 then 继续 ─────────────────────────────────────────────────


def test_e1_stop_then_e2_continue_finishes_the_same_table(client, app_module, monkeypatch):
    """The checkpoint feature measured on a real crawl, in one test.

    停止 arrives mid-walk; the record must settle ``interrupted`` with the node
    ``partial``, its rows on disk and its cursor past zero. 继续 is then *the same run id*
    (``resume_run_id``) on the same payload, because a fresh id would be a second crawl of
    the same keyword — and this pair is what the banner sells: rows already paid for are
    never paid for twice.
    """
    harness.real_jar(monkeypatch, app_module)
    canvas = posts_canvas(DEEP_TARGET, KEYWORDS['E'])

    with LiveRun(
        client, app_module, canvas, case_id='E1', mode='posts', target=DEEP_TARGET, timeout=DEEP_TIMEOUT
    ) as run:
        # The claim is "a walk cut short keeps its rows", so the trigger is the FIRST stored
        # row, not the fifth: waiting for five on a windowed 正文 crawl — browser start, a
        # possible wall back-off, per-row 展开全文 — can run the case's whole budget before the
        # button is pressed, and the assert that fires mid-crawl then leaks a live worker.
        run.wait_until(lambda: run.live_rows() >= 1, within=STOP_DEADLINE, what='the crawl stored a row')
        run.stop()
        run.wait()
        kept = run.rows()
        assert run.status['outcome'] == 'interrupted', run.status
        assert run.record['status'] == 'interrupted', run.record
        assert run.node()['status'] == 'partial', run.node()
        assert 1 <= kept < DEEP_TARGET, f'a crawl cut short is short of target; it kept {kept}'
        cursor = harness.cursor_of(run.record, 'node-1')
        assert cursor and int(cursor.get('scanned') or 0) > 0, f'the cursor must record the position reached: {cursor}'
        assert run.status['failed_nodes'] == 0, f"停止 is the user's own button, not a failure: {run.status}"
        # What the Stop prints is ONE line: ``run.nodeStopped``. ``crawl.stopped`` is the
        # *message of* the CrawlerStopped exception and ``_settle_node_as_stopped`` is handed
        # ``err=''``, so it reaches neither the console nor the record — asserting it here would
        # pay for a real 40-row crawl to discover a test bug (``tests/api/test_stop_path.py``
        # has known this all along). If the project ever wants a crawl-level "which button did
        # it" line, it goes into docs/live_test_plan.md §5 first and then into this case.
        assert harness.names_key(run.rec.text, 'run.nodeStopped'), 'the stopped node has to be named by label'
        stopped_at, finished_at = run.rec.first_index('run.nodeStopped'), run.rec.first_index('run.finished')
        assert stopped_at >= 0 and finished_at >= 0 and stopped_at < finished_at, (
            f'a stop that is not reported *before* the finish line never reached the verdict: {stopped_at}, '
            f'{finished_at}'
        )
        assert harness.names_key(run.rec.text, 'run.finished.stopped'), (
            'the finish line must count the node it cut short as stopped, not as failed'
        )
        answer = run.verdict(rows=kept)
        assert answer['verdict'] == harness.NAMED_SHORT and 'run.nodeStopped' in answer['reasons'], answer
        run.finish(answer=answer)

    # 继续: the same payload, the same run id, and no queue — a resume that queued would
    # spend its whole read budget on somebody else's console.
    with LiveRun(
        client,
        app_module,
        canvas,
        case_id='E2',
        mode='posts',
        target=DEEP_TARGET,
        timeout=DEEP_TIMEOUT,
        resume_run_id=run.run_id,
        queue=False,
    ) as again:
        again.wait()
        assert again.run_id == run.run_id, 'a resume that minted a new id is a second crawl, not 继续'
        resumed = again.verdict()
        assert resumed['verdict'] == harness.FULL, (
            f'继续 must finish what 停止 left: kept {again.rows()} of {DEEP_TARGET} with {resumed}'
        )
        assert harness.names_key(again.rec.text, 'run.resume_from'), 'the console must say it is continuing'
        assert harness.names_key(again.rec.text, 'crawl.resume_have'), 'and how many rows it started from'
        # AGENTS' third checkpoint rule, and the one that already cost a real fix (ee885f7):
        # a cursor records *position*. An id or link list smuggled back into it makes every
        # later resume re-open everything before the cut-off — or, on the platforms that key on
        # the list, permanently skip whatever failed to resolve once.
        position = harness.cursor_of(again.record, 'node-1')
        smuggled = {key: value for key, value in position.items() if isinstance(value, (list, tuple, dict))}
        assert not smuggled, f'the resume cursor stores content, not position: {smuggled}'
        rows = again.preview('node-1')
        links = [str(row.get('链接') or '') for row in rows]
        assert len(links) == DEEP_TARGET, f'the resumed table holds {len(links)} rows, not {DEEP_TARGET}'
        assert len(set(links)) == DEEP_TARGET, (
            f'the resume re-collected rows it already had: {len(set(links))} unique of {len(links)}'
        )
        _assert_post_rows(rows, minimum=DEEP_TARGET)
        again.finish(answer=resumed)


#: A 断点续跑 node crawls nothing, so it cannot come up short the way a walk does. Its honest
#: endings are its own three lines — the table it adopted, the pick that held no rows, and the
#: canvas with no stored run to read — and an empty answer that names none of them is the same
#: silent shape this tier convicts everywhere else.
RESUME_EXITS = harness.SHARED_EXITS + ('resume.loaded', 'resume.empty', 'resume.no_run')

#: The four stop/resume legs ``docs/live_test_plan.md`` §3-D still owed after E1+E2, and the
#: numbers they pay for. Every ask here is deliberately small: 停止 and 继续 are the expensive
#: half of the matrix — each leg is real crawling — and a stop that lands early is both cheaper
#: and the honest shape, since a resume is judged on the rows its first attempt paid for.
E3_TARGET = 10  # per component: two walks in one parallel run
E4_LIMIT = 10  # comments per article, over three articles
E5_TARGET = 10  # the same ask twice, one keyword apart
E6_TARGET = 10  # the number the dying session falls short of
E6_DEATH_ROWS = 3  # how far that crawl gets before the wall is answered
E7_ROWS = 6  # the donor table a later canvas adopts
DONOR_TITLE = '存量供体'


def _one_closed_one_walking(run: LiveRun) -> bool:
    """Is one component of this canvas closed with a table while another is inside its walk?

    The moment E3 presses 停止 in, and stated as a *shape* rather than as a node id because
    真排队 hands the platform's turn to whichever thread reached it first: waiting for
    「node-1 is done」 would be a bet on that order. Lose the bet and the button is pressed while
    the sibling still waits inside ``crawl_gate.hold``, where a Stop is answered by
    ``run.queueAbandoned`` and settles a *second* node as stopped — a different fact from the one
    this case is about, and one ``assert_l3`` rightly refuses.

    A row count is part of the test for the same reason: every component's 工作流命名 node is
    ``done`` from its first second, and a node that produces no rows says nothing about a crawl.
    """
    statuses = run.live_statuses()
    closed = [
        nid for nid, state in statuses.items() if state.get('status') == 'done' and int(state.get('row_count') or 0) > 0
    ]
    walking = [nid for nid, state in statuses.items() if state.get('status') == 'running' and run.live_rows(nid) > 0]
    return bool(closed) and bool(walking)


def test_e3_a_parallel_run_cut_short_convicts_one_walk_and_hands_the_lane_back(client, app_module, monkeypatch):
    """E3 — 并行中途停: 停止 inside a run of two live crawls settles exactly one node stopped,
    leaves its sibling's finished table standing, and hands the platform's turn back.

    E1 cannot cover this. A parallel run is one record whose nodes are executed on different
    threads, so the settlement has to be gathered from two unwinding workers: the killed crawl
    reports itself through ``_settle_node_as_stopped`` while the finished one has already written
    ``done``, and the single finish line has to count the cut-short node as *stopped* rather than
    failed. Both halves are asserted on the component's own console slice — a stop named in one
    workflow must not be read as a stop in the other, which is the same attribution rule the
    whole E group runs on.

    The lane claim is measured, not assumed: 真排队 is pinned on for this case (restored on the
    way out, the way G1 pins it off) because the promise is 「a crawl holds the turn until it
    finishes」 and the crawl here did NOT finish. The cheapest real crawl the matrix has — 热榜,
    one page and one in-page fetch — is then asked for the platform again: a turn the Stop failed
    to release answers it with 「等待采集时段」, with ``run.platformGateTimeout``, or with a stall.
    Overlap itself is G1's claim on this same canvas shape; E3's is what a stop leaves behind.
    """
    harness.real_jar(monkeypatch, app_module)
    canvas = _two_search_components(
        keywords=KEYWORDS['E3'], target=E3_TARGET, headless=False, use_profile=None, extra={'full_body': False}
    )
    parts = _components(canvas)
    label_of = {part['source']: part['label'] for part in parts}
    walks = [part['source'] for part in parts]
    titles = {node['id']: str(node['title']) for node in canvas['nodes'] if node['type'] == 'source'}
    before = settings_store.get_setting('same_platform_queue')
    _saved, warnings = settings_store.save_settings({'same_platform_queue': True})
    assert not warnings, warnings
    try:
        with LiveRun(
            client, app_module, canvas, case_id='E3', mode='posts', target=E3_TARGET, timeout=DEEP_TIMEOUT
        ) as run:
            run.wait_until(
                lambda: _one_closed_one_walking(run),
                within=STOP_DEADLINE,
                what='one component closed with a table and its sibling still walking',
            )
            run.stop()
            run.wait()
            run.assert_l3()
            assert run.record['status'] == 'interrupted', run.record
            assert run.status['outcome'] == 'interrupted', run.status
            assert run.record['mode'] == 'parallel', run.record
            assert int(run.record['wf_count'] or 0) == 2, f'two components, one record: {run.record}'
            assert run.record['workflow_name'] == 'A + B', run.record['workflow_name']
            assert run.status['failed_nodes'] == 0, f"停止 is the user's own button, not a failure: {run.status}"
            closed = [nid for nid in walks if harness.node_of(run.record, nid).get('status') == 'done']
            cut = [nid for nid in walks if harness.node_of(run.record, nid).get('status') == 'partial']
            states = {nid: harness.node_of(run.record, nid).get('status') for nid in walks}
            assert len(cut) == 1 and len(closed) == 1, f'停止 must convict exactly the walk in flight: {states}'
            stopped_id, finished_id = cut[0], closed[0]
            kept = harness.stored_rows(run.record, stopped_id)
            finished = harness.stored_rows(run.record, finished_id)
            assert 1 <= kept < E3_TARGET, f'the walk 停止 cut kept {kept} of its {E3_TARGET}: {states}'
            assert finished == E3_TARGET, f"the sibling's finished table did not survive the stop: {finished}"
            cursor = harness.cursor_of(run.record, stopped_id)
            assert int(cursor.get('scanned') or 0) > 0, f'the cut walk left no position to continue from: {cursor}'
            smuggled = {key: value for key, value in cursor.items() if isinstance(value, (list, tuple, dict))}
            assert not smuggled, f'the stopped walk put content in its cursor, not position: {smuggled}'
            assert run.rec.counts_key('run.nodeStopped') == 1, (
                f'one cut-short node is one console line; this run wrote {run.rec.counts_key("run.nodeStopped")}'
            )
            named = harness.slots_from(run.rec.lines, 'run.nodeStopped', 'nid')
            assert named == [f'{titles[stopped_id]} #{stopped_id}'], (
                f'the stopped node is named once, by its own label: {named} of {states}'
            )
            assert harness.names_key(run.rec.text, 'run.finished.stopped'), (
                'the finish line must count the node it cut short as stopped, not as failed'
            )
            # Attribution, not presence: the cut component's own transcript carries its stop, and
            # the finished one must not be made to read as though it had been cut too.
            assert harness.names_key(run._slice(label_of[stopped_id]), 'run.nodeStopped'), (
                'the stopped component never said so in its own workflow transcript'
            )
            assert not harness.names_key(run._slice(label_of[finished_id]), 'run.nodeStopped'), (
                "one component's stop was narrated inside the other component's transcript"
            )
            answers = [
                (
                    part['label'],
                    run.component_verdict(part['label'], run.record, part['source'], target=E3_TARGET, mode='posts'),
                )
                for part in parts
            ]
            for (label, answer), part in zip(answers, parts, strict=True):
                run.audit(
                    f'E3.{label}',
                    verdict=answer['verdict'],
                    reasons=answer['reasons'],
                    rows=harness.stored_rows(run.record, part['source']),
                    target=E3_TARGET,
                    warn=answer['verdict'] != harness.FULL,
                )
            silent = [label for label, answer in answers if answer['verdict'] == harness.SILENT_SHORT]
            assert not silent, f'a component of a stopped parallel run said nothing about itself: {silent}'
            cut_answer = dict(answers)[label_of[stopped_id]]
            assert cut_answer['verdict'] == harness.NAMED_SHORT and 'run.nodeStopped' in cut_answer['reasons'], (
                f'the walk 停止 cut has to be graded on its own stop line: {cut_answer}'
            )
            assert dict(answers)[label_of[finished_id]]['verdict'] == harness.FULL, (
                'the component that finished before the button was pressed delivered its ask'
            )
            _summary_row(run, case_id='E3', parts=parts, answers=answers, kept=kept + finished, asked=2 * E3_TARGET)
            run.close()

        with LiveRun(client, app_module, hot_canvas(30), case_id='E3.lane', mode='hot', target=30) as free:
            free.wait()
            for held in (
                'run.platformQueued',
                'run.platformStaggered',
                'run.queueAbandoned',
                'run.platformGateTimeout',
                'crawl.profile_wait',
                'crawl.profile_stuck',
                'crawl.profile_gave_up',
            ):
                assert not harness.names_key(free.rec.text, held), (
                    f'the next crawl of this platform had to wait for {held} after a parallel run was '
                    f'停止ed — the cut-short worker never gave the turn (or the profile) back:\n'
                    f'{free.rec.text[-1500:]}'
                )
            answer = free.verdict()
            assert answer['verdict'] == harness.FULL, (
                f'the crawl that asked for the released lane did not fill: {answer}'
            )
            free.finish(answer=answer)
    finally:
        settings_store.save_settings({'same_platform_queue': before})


def test_e4_a_stop_between_articles_keeps_the_panels_that_reported(client, app_module, monkeypatch):
    """E4 — 评论文章间停: a comment walk is cut between panels, and the half-table it leaves is
    exactly the panels that reported back.

    A different engine underneath, and a different set of promises. The comment loop asks 停止
    at the top of each link (``app._execute_comment_node``) and then ends *by raising*
    ``CrawlerStopped``, so the node settles ``partial`` instead of ``done`` — and its
    ``comment.done`` summary is deliberately dropped on that path, because the executor's own
    被停止 line is the one true sentence. That is why this leg does not call
    :func:`_comment_verdict`: the instrument that requires one article line per link graded a
    correctly cut walk as a silent skip, and the reconciliation here is against the per-article
    figures themselves.

    What this case cannot choose is *which* panel the button found open: the walk is minutes long
    and 停止 is asynchronous, so with three links and a press one second after the first panel
    reported, 「between articles」 is honestly measured as the last panel never having reported —
    asserted below — not as a chosen index.
    """
    harness.real_jar(monkeypatch, app_module)
    pairs = _probe_answers(client, app_module, case_id='E4', keyword=KEYWORDS['D'])
    links = _commented_pairs(pairs, need=3, keyword=KEYWORDS['D'])
    canvas = comments_canvas(links, limit=E4_LIMIT)
    ask = _comment_ask(limit=E4_LIMIT, urls=links)
    stopped_label = f'{canvas["nodes"][0]["title"]} #node-1'

    with LiveRun(client, app_module, canvas, case_id='E4', mode='comments', target=ask, timeout=COMMENT_TIMEOUT) as run:
        run.wait_until(
            lambda: run.rec.counts_key('comment.article') >= 1,
            within=STOP_DEADLINE,
            what='the first comment panel reported its rows',
        )
        run.stop()
        run.wait()
        reported = harness.numbers_from(run.rec.lines, 'comment.article', 'n')
        walked = harness.slots_from(run.rec.lines, 'comment.article', 'url')
        kept = run.rows()
        assert run.record['status'] == 'interrupted', run.record
        assert run.node()['status'] == 'partial', run.node()
        assert 1 <= len(reported) < len(links), (
            f'{len(links)} links were asked for and {len(reported)} printed a panel line: a walk cut '
            f'between articles leaves the last panel unreported, and a walk that reported every link '
            f'finished before the button was pressed'
        )
        assert kept == sum(reported), (
            f'the store holds {kept} rows while the {len(reported)} panels that reported named '
            f'{sum(reported)} — a stopped comment walk must own exactly what it said it filed'
        )
        assert kept > 0, f'nothing was kept, so 继续 has no paid-for panel to build on: {run.rec.text[-1500:]}'
        assert not harness.names_key(run.rec.text, 'comment.done'), (
            'the summary line is dropped on a Stop on purpose; printing it would report a complete '
            'table over a cut walk'
        )
        assert run.rec.counts_key('run.nodeStopped') == 1
        assert harness.slots_from(run.rec.lines, 'run.nodeStopped', 'nid') == [stopped_label], (
            'the comments node has to be the one named as stopped'
        )
        cursor = harness.cursor_of(run.record, 'node-1')
        # The offset is written *before* each article (``app._execute_comment_node`` hands over
        # ``{'url_index': idx - 1}`` for idx in 1..len(urls)), so the number that grades it is how
        # many panels reported, not how many links were asked: asked-for is an upper bound the
        # product always satisfies, whatever the cursor holds. One behind the reported panels is
        # the article that reported and finished; level with them is the one 停止 found open. One
        # ahead would restart 继续 past a panel that never reported — a silent skip of exactly the
        # kind the cursor legs exist to watch.
        offset = int(cursor.get('url_index') or 0)
        assert len(reported) - 1 <= offset <= len(reported), (
            f'{len(reported)} panels reported and the cursor points at offset {offset} of '
            f'{len(links)} links: below the reported count, 继续 re-opens a panel already paid for; '
            'above it, the cursor claims an article the walk never reached and the resume silently '
            f'skips one: {cursor}'
        )
        smuggled = {key: value for key, value in cursor.items() if isinstance(value, (list, tuple, dict))}
        assert not smuggled, f'the comment cursor stores content, not position: {smuggled}'
        answer = run.verdict(rows=kept)
        assert answer['verdict'] == harness.NAMED_SHORT and 'run.nodeStopped' in answer['reasons'], answer
        run.finish(answer=answer, target=ask)

    with LiveRun(
        client,
        app_module,
        canvas,
        case_id='E4.continue',
        mode='comments',
        target=ask,
        timeout=COMMENT_TIMEOUT,
        resume_run_id=run.run_id,
        queue=False,
    ) as again:
        again.wait()
        assert again.run_id == run.run_id, 'a comment resume that minted a new id is a second crawl'
        added = harness.numbers_from(again.rec.lines, 'comment.article', 'n')
        reopened = harness.slots_from(again.rec.lines, 'comment.article', 'url')
        total = again.rows()
        assert added, f'继续 opened no panel at all:\n{again.rec.text[-1500:]}'
        # The cursor records *position*, so a panel the stopped run finished can be opened again
        # — and must then add nothing. That is the dedupe ledger doing its job, and it is the only
        # honest reading of 「the first panel is not paid for twice」: the table grew by exactly
        # what this attempt reported as new, and every asked link appears in one of the two
        # transcripts' own per-article lines.
        assert total == kept + sum(added), f'{kept} kept + {sum(added)} reported new, but the store holds {total}'
        assert set(walked) | set(reopened) == set(links), (
            f'asked {links}, reported {sorted(set(walked) | set(reopened))} — a link never named its own panel'
        )
        # Both readers walk the same lines in the same order, so the two slot lists pair up.
        paid = dict(zip(walked, reported, strict=True))
        for url, count in dict(zip(reopened, added, strict=True)).items():
            if url in paid:
                assert count == 0, (
                    f'{url} already reported {paid[url]} rows in the stopped run and 继续 filed {count} '
                    'more on top: the panel was paid for twice'
                )
        assert _done_total(again.rec) == total, 'the resumed walk and the store disagree about the whole table'
        rows = again.preview('node-1')
        # Both transcripts count as the naming evidence: this table is the merge of two walks, and
        # the blank the resumed run inherits was spoken about by the run that crawled it. Measured
        # on the second pass — the stopped run printed 「本轮 30 条里有 2 条…没有作者链接」, the
        # 继续 run carried those two rows and printed nothing, because it never opened that panel.
        _assert_comment_rows(rows, minimum=1, console=f'{run.rec.text}\n{again.rec.text}')
        sources = {str(row.get('文章URL') or '') for row in rows}
        assert sources <= set(links), f'a comment is attributed to a link this canvas never crawled: {sources}'
        resumed = again.verdict(rows=total)
        assert resumed['verdict'] != harness.SILENT_SHORT, (
            f'继续 left the table short without naming why: kept {total} of {ask} with {resumed}'
        )
        again.finish(answer=resumed, target=ask, warn=resumed['verdict'] != harness.FULL)


def test_e5_continuing_with_a_moved_keyword_drops_the_stale_cursor(client, app_module, monkeypatch):
    """E5 — 改 keyword 后续跑: the fingerprint moved, so the rows and the cursor under the old one
    describe a different ask and must be dropped — and never carried in silently as a head start.

    ``RunStore.begin_node`` answers this: when a node's stored fingerprint is not the one it is
    being run with, it deletes that node's rows and clears its ``row_count`` *and* its cursor,
    because an old offset over a new keyword's list is an under-collect dressed as a resume (the
    bug that already cost douyin a real fix, ``ee885f7``). The drop itself has no sentence of its
    own, so the case reads it from what only a dropped cursor cannot do: seed the crawler, and
    start reading the new list from its head. ``run.resume_crawl`` and ``crawl.resume_have`` are
    printed exactly when earlier rows were handed back to the walk, and neither may appear here —
    while the walk that does run has to announce the keyword the user actually changed it to.

    What this case does not claim: that no answer can ever appear under two different keywords.
    Overlap is the site's to offer, so the discriminator is the seeding lines, the walk's own
    harvest index and the exact row count, not a set difference of links.
    """
    harness.real_jar(monkeypatch, app_module)
    canvas = posts_canvas(E5_TARGET, KEYWORDS['E5'], full_body=False)
    with LiveRun(client, app_module, canvas, case_id='E5', mode='posts', target=E5_TARGET) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'the first keyword has to fill before the second is judged: {answer}'
        first_cursor = harness.cursor_of(run.record, 'node-1')
        assert str(first_cursor.get('keyword') or '') == KEYWORDS['E5'], (
            f'the cursor is supposed to record which ask it belongs to: {first_cursor}'
        )
        run.finish(answer=answer)

    moved = copy.deepcopy(canvas)
    moved['nodes'][0]['params']['keyword'] = KEYWORDS['E5B']
    with LiveRun(
        client,
        app_module,
        moved,
        case_id='E5.continue',
        mode='posts',
        target=E5_TARGET,
        resume_run_id=run.run_id,
        queue=False,
    ) as again:
        again.wait()
        assert again.run_id == run.run_id, 'a continue that minted a new id is a second run, not 继续'
        # The console still claims the rows it is continuing *from* — that number is read before
        # any node begins — and the point of the cell is that those rows are then dropped.
        assert harness.names_key(again.rec.text, 'run.resume_from'), 'the run had to say it is continuing'
        assert not harness.names_key(again.rec.text, 'run.resume_crawl'), (
            'the executor handed this walk the old keyword rows as a head start; begin_node was '
            'supposed to delete them with the stale cursor'
        )
        assert not harness.names_key(again.rec.text, 'crawl.resume_have'), (
            f'the crawler woke up holding rows from the other keyword:\n{again.rec.text[-1500:]}'
        )
        started = harness.slots_from(again.rec.lines, 'crawl.zhihu.start', 'kw')
        assert started and started[0] == KEYWORDS['E5B'], (
            f'the walk that ran was not the one the canvas now asks for: {started}'
        )
        # The *offset* half of the drop, which the rows cannot answer: a walk that skips the first
        # ``scanned`` cards of a page still filing its target looks identical from the store. The
        # walk's own harvest index distinguishes them — ``crawl.zhihu.processed`` prints ``i=idx``,
        # and ``_harvest_cards`` starts at ``min(cursor['scanned'], len(cards)) + 1``, so a cursor
        # cleared with its rows reads card 1 while a surviving offset reads ``scanned + 1``.
        first_scanned = int(first_cursor.get('scanned') or 0)
        head = harness.numbers_from(again.rec.lines, 'crawl.zhihu.processed', 'i')
        assert head, f'the re-keyed walk never printed a harvest index:\n{again.rec.text[-1500:]}'
        assert min(head) <= first_scanned, (
            f'the new keyword was harvested from card {min(head)}, past the {first_scanned} cards the '
            'old keyword had scanned: begin_node deleted the rows and left the offset standing, so '
            '继续 skipped the head of the new list and under-collected by construction'
        )
        assert again.rows() == E5_TARGET, (
            f'a re-keyed continue must file exactly the new ask; the store holds {again.rows()} of '
            f'{E5_TARGET}, so the re-keyed walk under-collected. Whether the old keyword rows survived is '
            'not this number to answer: the two seeding lines above refuse a head start and the distinct '
            'link count below refuses a table padded with rows from the other keyword'
        )
        cursor = harness.cursor_of(again.record, 'node-1')
        assert str(cursor.get('keyword') or '') == KEYWORDS['E5B'], f'the stale cursor was not replaced: {cursor}'
        assert int(cursor.get('scanned') or 0) > 0, f'the re-keyed walk left no position: {cursor}'
        rows = again.preview('node-1')
        _assert_post_rows(rows, minimum=E5_TARGET)
        links = [str(row.get('链接') or '') for row in rows]
        assert len(set(links)) == E5_TARGET, (
            f'the re-keyed table repeats a link: {len(set(links))} unique of {len(links)}'
        )
        resumed = again.verdict()
        assert resumed['verdict'] == harness.FULL, f'the new keyword did not fill its own ask: {resumed}'
        again.finish(answer=resumed)


def test_e6_a_session_that_dies_mid_crawl_resumes_the_table_it_left(client, app_module, monkeypatch):
    """E6 — cookie 死后续: a crawl bounced to a login page under target is the designed death
    path, and 继续 completes the table without paying for the kept rows a second time.

    **What is simulated** is one boolean (:func:`live_run_harness.session_dies_after` latches
    ``Crawler.login_wall`` once the walk has kept :data:`E6_DEATH_ROWS` rows). Everything else is
    the product's own path on real zhihu rows: the executor compares rows against target, raises
    ``run.cookieExpired`` *by name*, the node settles ``partial``, the RUN goes ``failed`` so the
    banner appears, the flag rides to the browser on ``/api/workflow/status``, and 继续 resumes
    from the stored cursor. Waiting for the user's real session to expire is not a test — the
    alternative to injecting the verdict is not measuring it.

    The resume half is the promise the checkpoint feature sells: the walk starts from the rows
    already filed (``run.resume_crawl`` + ``crawl.resume_have`` name how many), the row ledger
    continues from that count rather than restarting at one, and the finished table holds
    :data:`E6_TARGET` distinct links.

    The node asks for 重新采集 (``recrawl=True``, the way the shipped 测试：知乎.json sets it on
    every source node) for exactly one reason: the executor prints ``run.recrawl`` whenever the
    switch is on **and** the attempt is not a resume, so the resume leg's absence of that line is
    the product answering "the dedupe ledger was not released here" — which is the rule, because
    on 继续 the ledger *is* the resume machinery. A canvas that never asked would let the leg
    pass without the product ever being in a position to speak.
    """
    harness.real_jar(monkeypatch, app_module)
    from crawlers.zhihu import ZhihuCrawler

    canvas = posts_canvas(E6_TARGET, KEYWORDS['E6'], full_body=False, recrawl=True)
    injected = harness.session_dies_after(monkeypatch, ZhihuCrawler, 'search', rows=E6_DEATH_ROWS)
    with LiveRun(
        client,
        app_module,
        canvas,
        case_id='E6',
        mode='posts',
        target=E6_TARGET,
        named_death_ok=True,
    ) as run:
        run.wait()
        assert injected['latched'], f'the wall was never answered, so this case measured an ordinary crawl: {injected}'
        kept = run.rows()
        assert kept == injected['rows'], f'the store holds {kept} rows while the walled walk filed {injected["rows"]}'
        assert 1 <= kept < E6_TARGET, f'a death that arrives under target is the whole premise: kept {kept}'
        assert run.status['outcome'] == 'failed', f'a dead session must fail the RUN, or no banner: {run.status}'
        assert run.record['status'] == 'failed', run.record
        assert run.node()['status'] == 'partial', run.node()
        assert run.status['cookie_expired'] is True, f'F2: the toast flag never rode to the browser: {run.status}'
        assert harness.names_key(run.rec.text, 'run.cookieExpired'), 'the death has to be named, once'
        assert run.rec.counts_key('run.cookieExpired') == 1, 'one fact, one console line'
        assert run.rec.counts_key('wf.node_failed') == 1, (
            'the refusal is raised, and the executor prints it once with the node name — a second '
            'copy of the same sentence is the 双打 plan §6 TX7 records'
        )
        assert not harness.names_key(run.rec.text, 'run.cookieExpiredOk'), (
            'a session that died at the finish line is a different answer, and the two sentences '
            'must not be interchangeable'
        )
        cursor = harness.cursor_of(run.record, 'node-1')
        assert int(cursor.get('scanned') or 0) > 0, f'the walled walk left no position to resume from: {cursor}'
        answer = run.verdict(rows=kept)
        assert answer['verdict'] == harness.NAMED_SHORT and 'run.cookieExpired' in answer['reasons'], answer
        # §6's 归因 table reads the row and the transcript together, and neither of them can say
        # on its own that this death was injected: the wall flag latches *after* the walk returns,
        # so no wall line is ever printed, and the helper narrowed the walk's own ask, so the
        # transcript announces 「目标获取 3 条」 under a record that filed an ask of
        # :data:`E6_TARGET`. Both facts go into the row, or a reader chases a phantom throttle and
        # a number that disagrees with the store.
        answer['reasons'] = [
            *answer['reasons'],
            (
                f'simulated wall (session_dies_after) after {injected["rows"]} rows; the walk budget was '
                f'narrowed to {E6_DEATH_ROWS}, so its own start line names that number rather than '
                f'{E6_TARGET} and no wall line was printed'
            ),
        ]
        run.finish(answer=answer, warn=True)

    with LiveRun(
        client,
        app_module,
        canvas,
        case_id='E6.continue',
        mode='posts',
        target=E6_TARGET,
        resume_run_id=run.run_id,
        queue=False,
    ) as again:
        again.wait()
        assert again.run_id == run.run_id, '继续 on a dead session is the same run, not a second crawl'
        assert again.status['cookie_expired'] is False, (
            f'F2: a resume opened on a fresh session must not inherit the dead one: {again.status}'
        )
        assert harness.names_key(again.rec.text, 'run.resume_crawl'), 'the executor hands back the kept rows'
        # 「重新采集」 means the same thing here as in any source crawl: it is refused on a 继续,
        # because on this path the dedupe ledger *is* the resume machinery — releasing it would
        # let the walk re-collect the rows the wall had already paid for.
        assert not harness.names_key(again.rec.text, 'run.recrawl'), (
            '继续 released the dedupe ledger, so the kept rows are no longer protected from a re-crawl'
        )
        have = harness.numbers_from(again.rec.lines, 'crawl.resume_have', 'n')
        assert have and have[0] == kept, f'the walk started from {have[:1]}, not the {kept} rows already paid for'
        # The ledger, not the page, is what says 「not re-read」: ``crawl.zhihu.processed`` carries
        # the crawler's own running count of rows in hand, so a resumed walk that re-emitted from
        # one would show it here. Card *order* is the site's to change and is not asserted.
        emitted = harness.numbers_from(again.rec.lines, 'crawl.zhihu.processed', 'n')
        assert emitted and min(emitted) > kept, (
            f'the resumed walk restarted its row count instead of continuing: {emitted[:5]}'
        )
        assert again.rows() == E6_TARGET, f'继续 left the table at {again.rows()} of {E6_TARGET}'
        rows = again.preview('node-1')
        links = [str(row.get('链接') or '') for row in rows]
        assert len(links) == E6_TARGET and len(set(links)) == E6_TARGET, (
            f'the resumed table repeats a link: {len(set(links))} unique of {len(links)}'
        )
        _assert_post_rows(rows, minimum=E6_TARGET)
        resumed = again.verdict()
        assert resumed['verdict'] == harness.FULL, f'继续 must finish what the wall stopped: {resumed}'
        again.finish(answer=resumed)


def test_e7_a_resume_node_adopts_a_stored_table_instead_of_crawling_it_again(client, app_module, monkeypatch):
    """E7 — 断点续跑节点 adopt 存量入新图: a later canvas reads another run's rows out of
    ``runs.db`` instead of buying them again, and the node it picks is named by that run's title.

    Five rules, all paid for by ONE donor crawl and then measured on canvases that never open a
    browser: an explicit pick is adopted and named (``resume.loaded``, with the donor node's own
    「标题 #id」 label, which only the *record's* title column can supply, because that node is
    not on this canvas); a pick that names a node the run never had falls back to the fullest
    node rather than answering empty; a canvas with no run to read says ``resume.no_run``; a run
    picked whose every node holds nothing says ``resume.empty`` and names both the run and the
    node it looked for; and the last of those is then resumed once, which is where 「a stored
    result with zero rows is never reused」 lives — restoring the nothing would report a node that
    produced no table as one that had already been computed.
    """
    harness.real_jar(monkeypatch, app_module)
    donor_canvas = harness.canvas_for(
        PLATFORM,
        'posts',
        title=DONOR_TITLE,
        settings=harness.run_settings('serial', False),
        keyword=KEYWORDS['E7'],
        target_count=E7_ROWS,
        full_body=False,
    )
    with LiveRun(client, app_module, donor_canvas, case_id='E7.donor', mode='posts', target=E7_ROWS) as donor:
        donor.wait()
        answer = donor.verdict()
        assert answer['verdict'] == harness.FULL, f'the table later legs adopt was never paid for: {answer}'
        stored = donor.preview('node-1')
        links = {str(row.get('链接') or '') for row in stored}
        assert len(links) == E7_ROWS, f'the donor filed {len(stored)} rows and {len(links)} distinct links'
        donor.finish(answer=answer)

    label = f'{DONOR_TITLE} #node-1'
    with LiveRun(
        client,
        app_module,
        harness.resume_canvas(run_id=donor.run_id, source_node_id='node-1', label='采纳存量'),
        case_id='E7.adopt',
        mode='resume',
        target=E7_ROWS,
    ) as adopt:
        adopt.wait()
        assert adopt.record['status'] == 'completed', adopt.record
        assert harness.stored_rows(adopt.record, 'node-1') == E7_ROWS, (
            f'the adopted table holds {adopt.rows()} rows, not the {E7_ROWS} the donor paid for'
        )
        assert harness.mentions(adopt.rec.text, 'resume.loaded', rid=donor.run_id, nid=label, n=E7_ROWS), (
            f'the adoption never named the run and node it read: {adopt.rec.text[-1500:]}'
        )
        assert not harness.names_key(adopt.rec.text, 'crawl.zhihu.start'), (
            'an adoption is not a crawl: this canvas paid for no page, and the point of the node '
            'is that the rows were already bought'
        )
        assert not harness.names_key(adopt.rec.text, 'crawl.resume_have'), 'and it is not a resume of its own cursor'
        got = {str(row.get('链接') or '') for row in adopt.preview('node-1')}
        assert got == links, 'the table that arrived is not the table that was paid for'
        answer = adopt.verdict(target=E7_ROWS, rows=E7_ROWS)
        adopt.finish(answer=answer, target=E7_ROWS)

    with LiveRun(
        client,
        app_module,
        harness.resume_canvas(run_id=donor.run_id, source_node_id='node-that-is-not-here', label='取最全的节点'),
        case_id='E7.fullest',
        mode='resume',
        target=E7_ROWS,
    ) as fullest:
        fullest.wait()
        # The pick named a node this run never had. 「Empty」 would be a plausible-looking answer
        # and a wrong one: the reuse rule is that the fullest node of that run is adopted.
        assert not harness.names_key(fullest.rec.text, 'resume.empty'), (
            'a pick with no rows was answered as an empty table instead of the fullest node: '
            f'{fullest.rec.text[-1200:]}'
        )
        assert harness.mentions(fullest.rec.text, 'resume.loaded', rid=donor.run_id, nid=label, n=E7_ROWS), (
            f'the fullest node of the run was not the one adopted: {fullest.rec.text[-1200:]}'
        )
        assert fullest.rows() == E7_ROWS, fullest.record
        answer = fullest.verdict(target=E7_ROWS, rows=E7_ROWS)
        fullest.finish(answer=answer, target=E7_ROWS)

    norun_canvas = harness.resume_canvas(label='无从采纳')
    with LiveRun(client, app_module, norun_canvas, case_id='E7.norun', mode='resume', target=1) as norun:
        norun.wait()
        assert harness.names_key(norun.rec.text, 'resume.no_run'), (
            'a resume node with no run picked must say it found nothing to read, not file an empty table'
        )
        assert norun.rows() == 0, norun.record
        answer = harness.classify_verdict(1, 0, norun.rec.text, exits=RESUME_EXITS, bug_lines=())
        assert answer['verdict'] == harness.NAMED_SHORT and 'resume.no_run' in answer['reasons'], answer
        norun.finish(answer=answer, target=1)

    # The empty answer names its pick 「标题 #id」, and the title it prints is the one THAT run
    # stored, so the label is read off the canvas whose record is being read rather than copied
    # from the builder's own default title.
    empty_label = f'{next(node["title"] for node in norun_canvas["nodes"] if node["id"] == "node-1")} #node-1'
    with LiveRun(
        client,
        app_module,
        harness.resume_canvas(run_id=norun.run_id, source_node_id='node-1', label='存量是空的'),
        case_id='E7.empty',
        mode='resume',
        target=1,
    ) as picked:
        picked.wait()
        # The run *exists* and was picked by id; every node inside it holds nothing. That is the
        # other empty answer, and it has to name the run and the node it looked for, or a user
        # reading 「no rows」 cannot tell a picked-but-empty record from a typo'd id.
        assert harness.mentions(picked.rec.text, 'resume.empty', rid=norun.run_id, nid=empty_label), (
            f'the empty adoption did not name what it found empty: {picked.rec.text[-1200:]}'
        )
        assert not harness.names_key(picked.rec.text, 'resume.no_run'), 'this canvas did pick a run'
        assert picked.rows() == 0, picked.record
        answer = harness.classify_verdict(1, 0, picked.rec.text, exits=RESUME_EXITS, bug_lines=())
        assert answer['verdict'] == harness.NAMED_SHORT and 'resume.empty' in answer['reasons'], answer
        picked.finish(answer=answer, target=1)

    with LiveRun(
        client,
        app_module,
        harness.resume_canvas(label='无从采纳'),
        case_id='E7.reuse',
        mode='resume',
        target=1,
        resume_run_id=norun.run_id,
        queue=False,
    ) as retry:
        retry.wait()
        # The attempt above settled this node ``done`` over zero rows. A stored result with no
        # rows is never reused, because an empty parent may deliver this time — so this run has
        # to re-ask the store and say the same sentence again rather than restore the nothing.
        assert not harness.names_key(retry.rec.text, 'run.restored'), (
            'a zero-row stored result was reused: the node reported the last attempt instead of asking again'
        )
        assert harness.names_key(retry.rec.text, 'resume.no_run'), (
            f'the re-ask never reported its answer: {retry.rec.text[-1200:]}'
        )
        assert retry.rows() == 0, retry.record
        answer = harness.classify_verdict(1, 0, retry.rec.text, exits=RESUME_EXITS, bug_lines=())
        assert answer['verdict'] == harness.NAMED_SHORT, answer
        retry.finish(answer=answer, target=1)


# ─── F · the cookie gate's own probe ────────────────────────────────────

DECIDED = {cookie_preflight.VALID, cookie_preflight.EXPIRED, cookie_preflight.UNKNOWN, cookie_preflight.NO_COOKIE}


def test_f1_the_preflight_probe_answers_for_zhihu_and_says_it_is_not_dead(monkeypatch):
    """The pre-run gate against the real jar, in-process.

    The fast tier swaps out the one call that buys a browser, which is right for every
    decision around it and blind to this: whether ``diagnose`` still answers what the gate
    reads off it, and whether the browser is really released. A window left holding the
    profile parks the next crawl for ``PROFILE_LOCK_TIMEOUT``.

    Risk control answering the probe is a legitimate outcome — a headless probe zhihu
    bounces has told us nothing about the session, and 「无法核对」 never blocks a run. What
    is refused here is therefore exactly one answer: ``expired``, plus the missing session
    the probe was supposed to look at.
    """
    jar = harness.real_jar(monkeypatch)
    assert harness.has_cookie(PLATFORM), f'{jar} holds no {PLATFORM} session for the probe to read'
    cookie_preflight.reset()
    profile = browser_profiles.profile_dir_for(PLATFORM)
    assert browser_profiles.is_busy(profile) is False, 'a probe may not queue behind a live crawl'
    try:
        verdict = cookie_preflight.probe(PLATFORM)
    finally:
        cookie_preflight.reset()
    assert verdict['state'] in DECIDED, verdict
    assert verdict['probed'] is True, f'a saved session was never looked at: {verdict}'
    assert verdict['state'] != cookie_preflight.EXPIRED, (
        f"the gate read the user's own session as dead, so every case in this file would be crawling a "
        f'wall: {cookie_preflight.describe(verdict)}'
    )
    assert browser_profiles.is_busy(profile) is False, 'the probe left its browser holding the profile'
    harness.audit_dump(
        'F1',
        {
            'platform': PLATFORM,
            'mode': 'preflight',
            'headless': '',
            'use_profile': '',
            'target': 1,
            'rows': 1 if verdict['state'] == cookie_preflight.VALID else 0,
            'verdict': verdict['state'],
            'reasons': [cookie_preflight.describe(verdict)],
            'wall_flags': [],
            'cookie_expired': verdict['state'] == cookie_preflight.EXPIRED,
            'seconds': '',
            'lines': [f'cookie probe {PLATFORM} -> {verdict["state"]} (blocking={verdict["blocking"]})'],
        },
    )


# ─── G · 并行, the queue and the profile ────────────────────────────────


def _two_search_components(
    *, keywords, target: int, headless: bool, use_profile, ids=('A', 'B'), extra: dict | None = None
):
    """One canvas, two independent zhihu crawls, each named — the shape 并行 is about.

    Distinct keywords are not decoration: two components with identical params share a node
    fingerprint, hence the dedupe ledger's scope, and the second would be refused rows the
    first already claimed.

    *extra* is merged into BOTH nodes' params — the one knob E3 needs (an excerpt walk, so a
    crawl cut short is cheap) — because this is the only canvas shape in this file that means
    "two workflows in one run", and a second builder for it would be a second opinion about it.
    """
    first, second = keywords
    return harness.component_canvas(
        [
            {
                'platform': PLATFORM,
                'mode': 'posts',
                'source': 'node-1',
                'label': ids[0],
                'params': dict({'keyword': first, 'target_count': target}, **(extra or {})),
            },
            {
                'platform': PLATFORM,
                'mode': 'posts',
                'source': 'node-3',
                'label': ids[1],
                'params': dict({'keyword': second, 'target_count': target}, **(extra or {})),
            },
        ],
        settings=harness.run_settings('parallel', headless, use_profile=use_profile),
    )


def _assert_both_delivered(run, *, target: int, nodes=('node-1', 'node-3')) -> None:
    for node_id in nodes:
        kept = harness.stored_rows(run.record, node_id)
        assert kept == target, f'{node_id} did not fill its target: {kept}/{target}'


def _crawl_window(rec, *, start_key='crawl.zhihu.start', end_key='crawl.zhihu.finished') -> tuple:
    """The console indexes at which the crawls of one platform were *inside* their walk.

    ``wf.executing_node`` cannot answer an overlap question: the executor prints it before
    ``_execute_node`` takes the platform's turn (``app.py`` logs, then holds the lane), so a
    canvas that queued both crawls still announces both up front. The crawler's own first and
    last lines are inside the hold, which is what makes the pair a window worth reading.
    """
    started = [i for i, line in enumerate(rec.lines) if harness.names_key(line, start_key)]
    ended = [i for i, line in enumerate(rec.lines) if harness.names_key(line, end_key)]
    return started, ended


def test_g1_parallel_with_the_queue_off_really_overlaps(client, app_module, monkeypatch):
    """G1 — 错峰 with two throwaway browsers: the one shape in which two zhihu crawls of one
    account are alive at the same moment, which is what the matrix's ``parallel_recommended``
    claims was watched to work.

    Two halves make that claim, and only one of them was here. The positive half reads the
    overlap off the *crawler's* own lines — both walks had begun before either ended — because
    the node-executing line is printed before the platform's turn is taken and so proves
    nothing. The negative half asserts the lane stayed out of the way: had the queue been on,
    the console would say 「等待采集时段」 and the run would be a serial one wearing a parallel
    label.
    """
    harness.real_jar(monkeypatch, app_module)
    # Measured, and it decides this cell's shape: a 10-row 正文 walk is alive ~10 s, while the
    # 错峰 default spaces same-platform starts by 12 s — so with the queue simply switched off,
    # the first crawl FINISHES before its sibling is allowed to begin and nothing overlaps. That
    # is the spacing working as designed, not a lane that queued; G1 is about the pool, so the
    # interval is taken out of the way here (S1 owns it) and the ask is ``DEEP_TARGET`` — a
    # multi-screen walk that is still in flight when the second one starts.
    canvas = _two_search_components(keywords=KEYWORDS['G1'], target=DEEP_TARGET, headless=False, use_profile=False)
    keys = ('same_platform_queue', 'same_platform_stagger')
    before = {key: settings_store.get_setting(key) for key in keys}
    _saved, warnings = settings_store.save_settings({'same_platform_queue': False, 'same_platform_stagger': 0})
    assert not warnings, warnings
    try:
        with LiveRun(
            client, app_module, canvas, case_id='G1', mode='posts', target=DEEP_TARGET, timeout=DEEP_TIMEOUT
        ) as run:
            run.wait()
            assert run.record['status'] == 'completed', run.record
            assert run.record['wf_count'] == 2, f'two components, one record: {run.record["wf_count"]}'
            assert run.record['workflow_name'] == 'A + B', run.record['workflow_name']
            assert run.record['mode'] == 'parallel', run.record
            _assert_both_delivered(run, target=DEEP_TARGET)
            assert not harness.names_key(run.rec.text, 'run.platformQueued'), (
                'the queue is meant to be off and a crawl still waited for its platform, so the overlap '
                'below cannot have happened'
            )
            for key in ('run.serialForced', 'run.platformGateTimeout'):
                assert not harness.names_key(run.rec.text, key), f'the lane said {key} with the queue off'
            started, ended = _crawl_window(run.rec)
            assert len(started) >= 2 and len(ended) >= 2, (
                f'two components were supposed to walk; the console shows {len(started)} starts and '
                f'{len(ended)} endings'
            )
            assert max(started[:2]) < min(ended[:2]), (
                f'the crawls never lived at the same moment: the second one began at line {max(started[:2])} '
                f'after the first had already printed its ending at line {min(ended[:2])}'
            )
            # A walk is more than one round, or "overlap" is two fast fetches that could have
            # been sequential and still interleaved by accident.
            assert run.rec.counts_key('crawl.zhihu.scroll_round') >= 4, (
                f'the two crawls printed only {run.rec.counts_key("crawl.zhihu.scroll_round")} scroll rounds '
                'between them, which is too few for either to have been in flight while the other ran'
            )
            answer = run.verdict('node-1')
            assert answer['verdict'] == harness.FULL, answer
            run.finish(answer=answer, node_id='node-1')
    finally:
        settings_store.save_settings(before)


def test_g1b_parallel_with_the_queue_on_waits_and_says_so(client, app_module, monkeypatch):
    """G1b — the default (真排队) on the same canvas: both crawls still finish, the wait is
    visible in the console, and no thread parks into ``PLATFORM_GATE_TIMEOUT``. A rate limit
    and a profile are two different collisions, and the queue is the answer the user gets to
    choose between them.

    The negative half of G1's promise, in the same currency: 真排队 holds the lane until its
    crawl *finishes*, so the second walk may not begin before the first one ended.
    """
    harness.real_jar(monkeypatch, app_module)
    canvas = _two_search_components(keywords=KEYWORDS['G1B'], target=10, headless=False, use_profile=False)
    before = settings_store.get_setting('same_platform_queue')
    _saved, warnings = settings_store.save_settings({'same_platform_queue': True})
    assert not warnings, warnings
    try:
        with LiveRun(client, app_module, canvas, case_id='G1B', mode='posts', target=10, timeout=DEEP_TIMEOUT) as run:
            run.wait()
            assert run.record['status'] == 'completed', run.record
            _assert_both_delivered(run, target=10)
            assert harness.names_key(run.rec.text, 'run.platformQueued'), (
                'one crawl had to wait behind its own platform and nothing said so'
            )
            assert not harness.names_key(run.rec.text, 'run.platformGateTimeout'), 'the lane outlasted its patience'
            started, ended = _crawl_window(run.rec)
            assert len(started) >= 2 and len(ended) >= 2, f'two walks never both narrated: {run.rec.lines[:40]}'
            assert started[1] > ended[0], (
                f'真排队 holds the lane until its crawl finishes, yet the second walk started at line '
                f'{started[1]} before the first ended at {ended[0]}'
            )
            answer = run.verdict('node-1')
            assert answer['verdict'] == harness.FULL, answer
            run.finish(answer=answer, node_id='node-1')
    finally:
        settings_store.save_settings({'same_platform_queue': before})


def test_g3_parallel_on_one_real_profile_serializes_and_finishes(client, app_module, monkeypatch):
    """G3 — 并行 on ONE shared profile directory, and this time the cell measures the profile.

    With the platform lane switched on, the lane serializes these two crawls first, the profile
    is free every time one of them arrives, and the profile lock — the thing this case is about
    — never gets asked anything. So the rate-limit queue is turned off exactly as in G1, which
    leaves the *only* serialization left standing between two browsers and one directory:
    ``browser_profiles.acquire_profile``, chromedriver's
    「failed to write prefs file」 answer to a second session in the same place.

    What a green therefore has to show is the wait itself: 「已排队 N 秒：这个 profile 同时只能
    开一个浏览器」 naming this platform's own directory, and no stuck-profile refusal under it.
    A ``ProfileUnavailableError`` here is a serialization bug in this file rather than weather,
    so the timeout stays generous instead of excusing the wait.
    """
    harness.real_jar(monkeypatch, app_module)
    canvas = _two_search_components(keywords=KEYWORDS['G3'], target=5, headless=False, use_profile=True)
    profile = browser_profiles.profile_dir_for(PLATFORM)
    assert profile, 'the tier runs with browser profiles on, so this case has no directory to wait for'
    # The 错峰 interval has to be disarmed here for the same reason it is measured in S1: at its
    # 12 s default it spaces the two starts wider than a 5-row walk lives, so the second browser
    # arrives at a profile its sibling has already released, the lock is never asked anything, and
    # this cell passes by never testing the thing it is named for.
    keys = ('same_platform_queue', 'same_platform_stagger')
    before = {key: settings_store.get_setting(key) for key in keys}
    _saved, warnings = settings_store.save_settings({'same_platform_queue': False, 'same_platform_stagger': 0})
    assert not warnings, warnings
    try:
        with LiveRun(
            client, app_module, canvas, case_id='G3', mode='posts', target=5, timeout=ACCEPTANCE_TIMEOUT
        ) as run:
            run.wait()
            assert run.record['status'] == 'completed', run.record
            _assert_both_delivered(run, target=5)
            assert not harness.names_key(run.rec.text, 'run.profileOff'), 'this case asked for the profile'
            waited = harness.slots_from(run.rec.lines, 'crawl.profile_wait', 'dir')
            assert waited, (
                'one profile is one browser, and with the platform queue off the two crawls of this '
                'canvas could only have taken turns inside the profile lock — a run that never waited '
                'did not test the thing this case exists to test'
            )
            assert str(profile) in waited, f"the wait named a directory that is not this platform's: {waited}"
            for refusal in ('crawl.profile_stuck', 'crawl.profile_gave_up', 'run.platformGateTimeout'):
                assert not harness.names_key(run.rec.text, refusal), f'the profile lane said {refusal}'
            started, ended = _crawl_window(run.rec)
            assert len(started) >= 2 and started[1] > ended[0], (
                f'the crawls overlapped anyway: the second started at line '
                f'{started[1] if len(started) > 1 else -1}, the first ended at {ended[0] if ended else -1}'
            )
            answer = run.verdict('node-1')
            assert answer['verdict'] == harness.FULL, answer
            run.finish(answer=answer, node_id='node-1')
    finally:
        settings_store.save_settings(before)


# ─── H · the shipped acceptance canvas ──────────────────────────────────


def _components(workflow: dict) -> list:
    """The canvas's own components, read out of the file rather than copied into this test.

    H1's promise is "run the file exactly as saved and name whoever sat out", so an expected
    label that is a literal here goes red over a rename with a message about missing console
    lines — and the ask each component is graded against has to be the ask the record holds,
    not a number this file remembered. Each entry is
    ``{'label', 'source', 'mode', 'ask', 'on'}``: ``label`` is the name node's label (what the
    run is filed under), ``on`` is whether the component still has all of its 启用 switches, and
    ``ask`` is the node's own number — the *user's* ask, whatever the site does with it. A
    comments node asks per article (``comment_limit``, and 0 means 「采集全部评论」 with no row
    budget at all), so its ``ask`` is the product of the limit and its links and one row per link
    when the limit is open-ended: see :func:`_comment_ask`.

    Grouping is by connected component, exactly the way the executor splits a canvas into
    workflows — following one wire in one direction is not the same thing and would miss a canvas
    whose name node hangs off the far end of a chain.
    """
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
        assert len(sources) == 1, f'{ACCEPTANCE_FILE.name} has a component with {len(sources)} sources: {group}'
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
                'ask': _comment_ask(limit=limit, urls=urls)
                if mode == 'comments'
                else int(params.get('target_count') or 0),
                'comment_limit': limit,
                'urls': urls,
                # A disabled node anywhere in the component takes the whole workflow out — that
                # is ``effective_workflow`` cascading, and it is why the file's author switches
                # off the *name* node rather than the crawler.
                'on': all(bool((nodes[nid].get('params') or {}).get('enabled', True)) for nid in group),
            }
        )
    assert out, f'{ACCEPTANCE_FILE.name} holds no component with a source to run'
    return out


def _acceptance_parts(workflow: dict) -> tuple:
    """``(enabled_labels, disabled_labels, components)`` — all three from the workflow given.

    No shape claim is made here, because the three callers ask different questions: H1 runs the
    file **as saved** and is about naming who sat out, so it needs both an on and an off side;
    H2/H3 run ``_all_enabled`` copies of it, where an empty ``off`` is the point. Asserting
    ``on and off`` in this helper made those two cases unfailable — they enabled every component
    and then demanded evidence that some were disabled.
    """
    parts = _components(workflow)
    on = [part['label'] for part in parts if part['on']]
    off = [part['label'] for part in parts if not part['on']]
    assert parts, f'{ACCEPTANCE_FILE.name} holds no components at all: {workflow}'
    return on, off, parts


def _acceptance_workflow() -> dict:
    """The user's own saved canvas, read without touching it.

    Read-only by contract: this is a workflow he made and re-runs himself, and a test that
    saved over it would destroy the thing it measures. No endpoint is used either —
    ``GET /api/workflow/load`` writes two ambient keys into the application and needs the
    workflow directory to be the real one.
    """
    loaded = json.loads(ACCEPTANCE_FILE.read_text(encoding='utf-8'))
    assert isinstance(loaded.get('nodes'), list) and loaded['nodes'], loaded
    assert isinstance(loaded.get('settings'), dict), loaded
    return loaded


def _all_enabled(workflow: dict) -> dict:
    """A deep copy with every node switched on — the shipped canvas as its author's whole test."""
    opened = copy.deepcopy(workflow)
    for node in opened['nodes']:
        node.setdefault('params', {})['enabled'] = True
    return opened


def _records_by_name(client) -> dict:
    """The panel's list, indexed by the name each component gave itself."""
    out: dict = {}
    for record in harness.read_records(client, limit=30):
        out.setdefault(str(record.get('workflow_name') or ''), record)
    return out


def _records_by_node(client, parts) -> dict:
    """Each 串行 component's own row, found by the node it owns rather than by its name.

    A serial run opens one record per workflow *as it is reached*, and a record is named by its
    ENABLED name node, falling back to the canvas's own name when that node is switched off — the
    product's documented precedence. Measured on the shipped canvas: three of its four components
    have their name node off, so three rows carry the identical 名称 and a name→record map hands
    two of them the wrong row (H2 first failed as 「run … has no node 'node-12'」 while reading the
    hot component's record). Node identity cannot collide: a component's source node exists in
    exactly one record of the run, which is what this resolves by.
    """
    records = harness.read_records(client, limit=40)
    out: dict = {}
    for part in parts:
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


#: Lines that explain a *failed* component: a wall, a dead link, a refusal the site owns.
#: A run that went ``failed`` having printed one of these has told the user what happened,
#: and the matrix's own verdict for that component (``_audit_components``) is the finding —
#: what is refused is a failure whose console names nothing at all.
NAMED_DEATHS = (
    'run.cookieExpired',
    'crawl.loginWall',
    'crawl.riskBlocked',
    'crawl.zhihu.emptyOrBlocked',
    'crawl.zhihu.hotWall',
    'crawl.zhihu.hotRefused',
    'comment.status.blocked',
    'comment.status.dead',
    'run.dedupe_all_skipped',
)


def _named_refusals(text: str) -> list:
    return [key for key in NAMED_DEATHS if harness.names_key(text, key)]


def _audit_components(run, *, records: dict, case_id: str, parts: list) -> tuple[list, int, int, list]:
    """One audit row per component, graded against that component's own console slice.

    A four-component run is four verdicts: rolling them into one number is how a half-empty
    crawl gets presented as a success, and grading them against the *whole* console is how one
    component's honest 「没有更多了」 whitewashes another component's silence. Returns the
    silent ones, the rows kept, the asks added up, and each component's own verdict — the last
    of these is what the summary row is derived from, so an index line can never read FULL
    over a run whose components did not.
    """
    silent: list = []
    answers: list = []
    kept_total = 0
    ask_total = 0
    for part in parts:
        label, node_id, mode, target = part['label'], part['source'], part['mode'], part['ask']
        record = records.get(label)
        if record is None:
            silent.append((label, 'no record was opened for this component'))
            continue
        kept = harness.stored_rows(record, node_id)
        kept_total += kept
        ask_total += target
        if mode == 'comments':
            answer = _comment_verdict(
                run,
                node_id=node_id,
                urls=part['urls'],
                limit=part['comment_limit'],
                console=run._slice(label),
                rows=kept,
            )
        else:
            answer = run.component_verdict(label, record, node_id, target=target, mode=mode)
        answers.append((label, answer))
        run.audit(
            # The node, not just the mode: the shipped acceptance canvas holds TWO 帖子
            # components, and a row named after the mode alone would overwrite the first
            # component's transcript with the second's and leave verdicts.csv with two rows
            # that no artifact can be matched to.
            f'{case_id}.{mode}.{node_id}',
            verdict=answer['verdict'],
            reasons=answer['reasons'],
            rows=kept,
            target=target,
            warn=answer['verdict'] != harness.FULL,
        )
        if answer['verdict'] == harness.SILENT_SHORT:
            silent.append((label, f'kept {kept} of {target} with no reason named, or only one that lies'))
    return silent, kept_total, ask_total, answers


def _summary_row(run, *, case_id: str, parts: list, answers: list, kept: int, asked: int) -> str:
    """Derive the case's own index row from its components — never a hard-coded FULL.

    The artifact is what a root-cause pass reads, and a line that says FULL about a run whose
    components came up short contradicts the four rows written directly above it.
    """
    verdicts = {label: answer['verdict'] for label, answer in answers}
    silent = [label for label, verdict in verdicts.items() if verdict == harness.SILENT_SHORT]
    short = [label for label, verdict in verdicts.items() if verdict == harness.NAMED_SHORT]
    missing = [part['label'] for part in parts if part['label'] not in verdicts]
    if silent or missing:
        verdict = harness.SILENT_SHORT
    elif short or run.warned():
        verdict = harness.NAMED_SHORT
    else:
        verdict = harness.FULL
    reasons = [f'{len(parts)} components, {kept} rows', *(f'silent: {label}' for label in silent + missing)]
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


def _new_exports(before: set) -> list:
    """Files :data:`Config.EXPORT_DIR` gained while a run was going, newest first."""
    from config import Config

    return sorted(
        (path for path in Path(Config.EXPORT_DIR).glob('*') if path.name not in before),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _csv_row_count(path: Path) -> tuple[int, list]:
    """How many data rows one exported CSV holds, and its header."""
    with path.open(newline='', encoding='utf-8-sig') as handle:
        rows = list(csv.reader(handle))
    return max(0, len(rows) - 1), rows[0] if rows else []


def test_h1_the_shipped_canvas_runs_exactly_as_saved(client, app_module, monkeypatch):
    """H1 — the flagship: one real 50-row 正文 crawl out of the user's file, with the components
    he switched off reported as skipped rather than silently vanished.

    The stored ``target_count`` on that canvas is the matrix's own 50, so this is also the only
    case that exercises the default ask end to end — and, because that canvas wires an output
    node behind every component, the only one that can walk the plan's L2 三一致 (approved plan
    §3-B): the exported file's rows == the rows the store holds == the rows the preview probe
    returns. A1-A3 have no output node to make a file with, and say so.

    Both label sets come out of the file itself (:func:`_acceptance_parts`), so a rename by its
    author moves the expectation with it instead of turning the flagship red over a line the
    console "never printed".
    """
    harness.real_jar(monkeypatch, app_module)
    from config import Config

    workflow = _acceptance_workflow()
    on, off, parts = _acceptance_parts(workflow)
    # H1 is the case about who sat out, so THIS file — not a copy of it — must hold both sides.
    assert on and off, f'{ACCEPTANCE_FILE.name} is not the canvas this case was written against: {parts}'
    posts = next((part for part in parts if part['mode'] == 'posts'), None)
    assert posts and posts['on'], f'{ACCEPTANCE_FILE.name} no longer runs a keyword search by default'
    assert workflow['settings']['mode'] == 'serial' and workflow['settings']['headless'] is False
    exported_before = {path.name for path in Path(Config.EXPORT_DIR).glob('*')}
    with LiveRun(
        client,
        app_module,
        workflow,
        case_id='H1',
        mode='posts',
        target=posts['ask'],
        timeout=ACCEPTANCE_TIMEOUT,
    ) as run:
        run.wait()
        assert run.record['workflow_name'] == posts['label'], run.record['workflow_name']
        assert run.record['wf_count'] == 1, f'{len(off) + 1} drawn components are not {len(off) + 1} workflows'
        assert run.record['mode'] == 'serial' and int(run.record['headless']) == 0, run.record
        assert run.record['status'] == 'completed', run.record
        named = [label for label in off if label in run.rec.text]
        assert len(named) == len(off), f'every left-out component has to be named, saw {named} of {off}'
        assert harness.names_key(run.rec.text, 'run.skippedWorkflows'), 'the skip needs its own sentence'
        skipped = str(run.record.get('skipped_workflows') or '')
        assert skipped.strip(), f'the record does not carry the skipped components at all: {run.record}'
        for label in off:
            assert label in skipped, f'{label} is missing from skipped_workflows: {skipped}'
        answer = run.verdict(posts['source'])
        assert answer['verdict'] == harness.FULL, (
            f'the acceptance canvas did not fill its stored {posts["ask"]}: {answer}'
        )
        rows = run.preview(posts['source'])
        _assert_post_rows(rows, minimum=posts['ask'])
        # The third leg: the file the user would download holds exactly what the store says.
        fresh = _new_exports(exported_before)
        assert fresh, f'the canvas ends in an output node and {Config.EXPORT_DIR} gained no file'
        count, header = _csv_row_count(fresh[0])
        assert count == run.rows(posts['source']) == len(rows) == posts['ask'], (
            f'the three counts disagree: export {fresh[0].name} holds {count} rows, the store '
            f'{run.rows(posts["source"])}, the preview {len(rows)}, the ask {posts["ask"]}'
        )
        assert list(header) == list(POST_COLUMNS), f"the exported header is not the crawler's columns: {header}"
        run.finish(answer=answer, node_id=posts['source'])


def test_h2_the_whole_shipped_canvas_completes_in_series(client, app_module, monkeypatch):
    """H2 — every component of the user's canvas, serial and windowed: the 正文 search, the
    board, an author's own list, and the comment panels he pasted.

    Serial with four components is four records, opened one at a time, so each is read back by
    its own name, graded against its own console slice, and given its own row.

    The run's status is *not* asserted blind. Two of these components run on inputs the user
    typed into the file by hand — an author token and pasted 评论 links — and those age on their
    own schedule: a blocked comment article is the designed cookie-death path (node partial, run
    failed, 继续 offered), and zhihu answers a dead session on a profile page by raising. That is
    an input-rot report, not a code failure, and the tier's product is the per-component verdict,
    so a blanket ``completed`` here would convict the crawler for the age of a URL. What stays
    unconditional is the part that is never weather: a component that came up short and said
    nothing (or said one of the lines §6 measures as a lie).
    """
    harness.real_jar(monkeypatch, app_module)
    workflow = _all_enabled(_acceptance_workflow())
    _on, _off, parts = _acceptance_parts(workflow)
    assert workflow['settings']['mode'] == 'serial'
    with LiveRun(
        client,
        app_module,
        workflow,
        case_id='H2',
        mode='mixed',
        target=sum(part['ask'] for part in parts),
        timeout=ACCEPTANCE_TIMEOUT,
        named_death_ok=True,
    ) as run:
        run.wait()
        run.assert_l3()
        records = _records_by_node(client, parts)
        silent, kept, asked, answers = _audit_components(run, records=records, case_id='H2', parts=parts)
        assert not silent, f'components under target with no honest reason named: {silent}'
        for part in parts:
            label = part['label']
            assert label in records, f'{label} never opened a record: {sorted(records)}'
            assert records[label]['status'] in ('completed', 'failed'), records[label]
            assert int(records[label].get('wf_count') or 0) == 1, records[label]
        if run.record['status'] != 'completed':
            refusals = _named_refusals(run.rec.text)
            assert refusals, (
                f'the run went {run.record["status"]} without naming a reason anywhere: {run.rec.text[-2500:]}'
            )
        _assert_post_rows(run.preview('node-6', next(p['label'] for p in parts if p['mode'] == 'posts')), minimum=50)
        _summary_row(run, case_id='H2', parts=parts, answers=answers, kept=kept, asked=asked)
        run.close()


def test_h3_the_whole_shipped_canvas_in_parallel_headless(client, app_module, monkeypatch):
    """H3 — the same canvas 并行 + 无头, where the platform lane, the profile and the
    risk-control throttle all meet at once.

    ``max_workers`` comes down from the file's 4 to 2 on purpose: four components of ONE
    platform share one lane and one profile, so two of them would only be queueing. And the
    lane switch is pinned off, the way G1 pins it, because 真排队 holds a lane until its crawl
    *finishes*: with a 50-row 正文 search and a 50-row author walk in front of a waiter, the
    fourth component would sit out ``PLATFORM_GATE_TIMEOUT`` (900 s) and fail a node for a wait
    this case invented — the same reason G1b exists to *show* that queue.

    Headless is the mode zhihu throttles day-by-day (risk 40362), so the run is judged the way
    A4 is: a component may come up short when its own console says which wall it met, with the
    line quoted into its row and the row flagged WARN — but never silently, and never on the
    strength of a reason a sibling named.
    """
    harness.real_jar(monkeypatch, app_module)
    workflow = _all_enabled(_acceptance_workflow())
    _on, _off, parts = _acceptance_parts(workflow)
    workflow['settings'] = dict(workflow['settings'], mode='parallel', headless=True, max_workers=2)
    before = settings_store.get_setting('same_platform_queue')
    _saved, warnings = settings_store.save_settings({'same_platform_queue': False})
    assert not warnings, warnings
    try:
        with LiveRun(
            client,
            app_module,
            workflow,
            case_id='H3',
            mode='mixed',
            target=sum(part['ask'] for part in parts),
            timeout=ACCEPTANCE_TIMEOUT,
            named_death_ok=True,
        ) as run:
            run.wait()
            run.assert_l3()
            assert int(run.record['headless']) == 1 and run.record['mode'] == 'parallel', run.record
            assert run.record['wf_count'] == 4, run.record
            assert not harness.names_key(run.rec.text, 'run.platformGateTimeout'), (
                'a component failed waiting for the platform lane this case invented by running '
                'four crawls of one site in parallel; that is a queue timeout, not a crawl result'
            )
            whole = _records_by_name(client).get(str(run.record['workflow_name']), run.record)
            records = {part['label']: whole for part in parts}
            silent, kept, asked, answers = _audit_components(run, records=records, case_id='H3', parts=parts)
            assert not silent, f'a headless component came up short without naming why: {silent}'
            assert kept > 0, 'a run that stored nothing across four components delivered nothing'
            if run.record['status'] != 'completed':
                refusals = _named_refusals(run.rec.text)
                assert refusals, (
                    f'the run went {run.record["status"]} naming no wall, no risk control and no dead '
                    f'session: {run.rec.text[-2500:]}'
                )
            _summary_row(run, case_id='H3', parts=parts, answers=answers, kept=kept, asked=asked)
            run.close()
    finally:
        settings_store.save_settings({'same_platform_queue': before})


# ─── S · the settings page's own switches (plan §3-C) ───────────────────

#: The 错峰 interval S1 asks the settings page for, in seconds. Two measured numbers choose it,
#: and the first pass of this tier produced the second one the hard way:
#:
#: * it must sit ABOVE the catalogue default, because the cell's whole claim is that the spacing
#:   read the settings page rather than a stale default — and the line announces the seconds it
#:   owes, so an interval at or under the default could be satisfied by the default itself. The
#:   assert below compares against ``settings_store.DEFAULTS`` instead of repeating this number;
#: * it must sit BELOW the life of one walk. Measured: a windowed 正文 search delivers 10 rows in
#:   ~10 s and 40 rows in ~24 s (``scratchpad/live_audit/20260927-223207/verdicts.csv``), so at
#:   the 40 s first drafted here — and at the 12 s default G1 and G3 also tripped on — the first
#:   crawl FINISHES before its sibling is allowed to start, and 「错峰 spaces departures, not
#:   lives」 has nothing left to overlap. S1 therefore asks for a walk big enough to outlive the
#:   gap (``S1_TARGET``) and keeps the gap the smaller of the two.
S1_STAGGER = 20

#: Rows per walk in S1. Measured, 40 rows of 正文 is alive ~24 s, so 50 clears ``S1_STAGGER`` with
#: room for a busy box — the gap must be the smaller of the two numbers or the overlap leg below
#: asks a crawl to be alive after it has already reported its last row.
S1_TARGET = 50


def test_s1_stagger_spaces_the_two_starts_and_never_queues_them(client, app_module, monkeypatch):
    """S1 — plan §3-C: 同平台排队 off with a non-zero 错峰 interval is its own branch of the
    gate, with its own sentence, and the console lines are what tell the branches apart.

    ``crawl_gate.hold`` answers 真排队 and 错峰 from the same switch: ``run.platformQueued``
    prints only in the queue branch (seat held until the crawl finishes), ``run.platformStaggered``
    only in the spacing one (``_space_the_start``, seat held for the wait and the walk, gap
    owed only while a sibling is actually in flight). So the cell is three claims. The
    positive: the second start waited, the gate says so by platform name, and the console's
    own ``[HH:MM:SS]`` stamps show the announced seconds really passing between the promise
    and that crawl's first walk line. The negative: no queue line, no serial-forced line, no
    gate timeout — the branch that serializes was never entered. And the shape: 错峰 spaces
    *departures*, so both walks must still be alive at the same moment (G1's criterion),
    which a queue could never produce.

    Cost: one more parallel canvas in the G1 shape (two throwaway browsers, no shared
    profile), plus the one spacing wait. The two settings are restored in ``finally``
    exactly as G1/G1b/G3 restore theirs.
    """
    harness.real_jar(monkeypatch, app_module)
    canvas = _two_search_components(keywords=KEYWORDS['S1'], target=S1_TARGET, headless=False, use_profile=False)
    before_queue = settings_store.get_setting('same_platform_queue')
    before_stagger = settings_store.get_setting('same_platform_stagger')
    _saved, warnings = settings_store.save_settings({'same_platform_queue': False, 'same_platform_stagger': S1_STAGGER})
    assert not warnings, warnings
    assert settings_store.get_setting('same_platform_stagger') == S1_STAGGER, 'the page did not take the number'
    try:
        with LiveRun(
            client, app_module, canvas, case_id='S1', mode='posts', target=S1_TARGET, timeout=DEEP_TIMEOUT
        ) as run:
            run.wait()
            assert run.record['status'] == 'completed', run.record
            assert run.record['wf_count'] == 2, f'two components, one record: {run.record["wf_count"]}'
            assert run.record['mode'] == 'parallel', run.record
            _assert_both_delivered(run, target=S1_TARGET)
            # The spacing branch's own line, exactly once — one fact, one console line.
            said = run.rec.counts_key('run.platformStaggered')
            assert said == 1, f'错峰 owed one spacing sentence and the console printed {said}'
            owed = harness.numbers_from(run.rec.lines, 'run.platformStaggered', 'n')
            assert owed, 'the spacing line printed without the seconds it owed'
            n = owed[0]
            # It names THIS platform, and the seconds it owes are the settings page's own number
            # minus however long the two threads actually took to reach the gate — never the
            # catalogue default's 12 s.
            assert harness.mentions(run.rec.text, 'run.platformStaggered', platform=PLATFORM, n=n), (
                f'the stagger line did not name {PLATFORM} as the console printed it'
            )
            # Two bounds, and the gap between them is the arrival skew this cell cannot control.
            # The CEILING is the product's: a spacing may never owe more than the page states, and
            # ``_space_the_start`` logs only inside ``if ahead > 0``, so the line's presence is
            # itself the proof that a positive gap was owed. The FLOOR is what proves the number
            # came from the settings page and not from the catalogue default: the wait is
            # ``interval − arrival skew``, and the skew is the two pool threads' business, so the
            # interval is set a full default above the page's ask (``S1_STAGGER`` vs
            # ``DEFAULTS``) to leave room for it. What the stamps below measure is the third
            # opinion: the seconds the line promised are the seconds that passed.
            default = settings_store.DEFAULTS['same_platform_stagger']
            assert n > default, (
                f'the page was asked for {S1_STAGGER}s and the gate announced {n}s, at or below the '
                f'{default}s the catalogue defaults to — a spacing that ignored the settings page '
                'is indistinguishable from one that honoured it'
            )
            assert n <= S1_STAGGER, (
                f'错峰 may owe at most the {S1_STAGGER}s the settings page states, and the gate '
                f'announced {n}s: the spacing did not read the settings page'
            )
            # The promised seconds are the seconds that passed, read off the console's own
            # stamps between the line and the later of the two walk-starts (the waiter's).
            line_stamps = [
                harness.stamped_second(line)
                for line in run.rec.lines
                if harness.names_key(line, 'run.platformStaggered')
            ]
            start_stamps = [
                harness.stamped_second(line) for line in run.rec.lines if harness.names_key(line, 'crawl.zhihu.start')
            ]
            assert None not in line_stamps and None not in start_stamps, (
                f'a console line arrived without its clock: {line_stamps!r} {start_stamps!r}'
            )
            waited = max(start_stamps) - line_stamps[0]
            assert n - 2 <= waited <= n + 240, (
                f'the line owed {n}s and the second crawl spoke {waited}s after it — the sleep '
                'is the setting, so a spacing this far off its own announcement grades red '
                f'(stamps: line {line_stamps[0]}, starts {start_stamps})'
            )
            # The queue branch was never entered: these lines print only there.
            for key in ('run.platformQueued', 'run.serialForced', 'run.platformGateTimeout', 'run.queueAbandoned'):
                assert not harness.names_key(run.rec.text, key), f'the lane said {key}: this is 真排队, not 错峰'
            # And 错峰 spaces departures, not lives: both walks alive at once (G1's test).
            started, ended = _crawl_window(run.rec)
            assert len(started) >= 2 and len(ended) >= 2, (
                f'two components were supposed to walk; the console shows {len(started)} starts and '
                f'{len(ended)} endings'
            )
            assert max(started[:2]) < min(ended[:2]), (
                f'the crawls never lived at the same moment: the later began at line '
                f'{max(started[:2])} after the other had ended at line {min(ended[:2])} — a spacing '
                'that serialized the walks answered for the queue branch instead'
            )
            answer = run.verdict('node-1')
            assert answer['verdict'] == harness.FULL, answer
            run.finish(answer=answer, node_id='node-1')
    finally:
        settings_store.save_settings({'same_platform_queue': before_queue, 'same_platform_stagger': before_stagger})


def test_s2_the_browser_ceiling_narrows_the_parallel_pool_to_one_walk(client, app_module, monkeypatch):
    """S2 — plan §3-C: the concurrent-browser ceiling as the parallel pool's width.

    ``_begin_run`` answers "how many workflows of one parallel run may be alive at once"
    with ``max_headless_browsers`` or ``max_visible_browsers`` — the run's 无头/窗口 choice
    picks which key, on one line — clamps it to 1..16, and the pool is then
    ``min(wf_count, that)``. A canvas carrying its own ``max_workers`` outranks the setting
    (and the shipped browser always sends 4), so the ``pop`` below is what lets the
    settings page be asked at all; that precedence is the product's stated rule.

    The limitation, stated rather than papered over: **nothing in the console or the record
    names the pool width** — it is a silent clamp, no line prints it, so this case asserts
    no sentence the product does not write. What the code does leave as evidence is
    *ordering*: with the ceiling at one, the platform gate taken entirely out of the way
    (真排队 off, 错峰 0 — the branch that would space or queue these crawls is disarmed and
    its lines asserted absent), and no shared profile to serialize for (``use_profile``
    False, ``crawl.profile_wait`` asserted absent), the only thing left that can make the
    second walk begin after the first *finished* is the pool. So the cell grades exactly
    that: the run completes, both tables deliver, and the walk windows do not overlap. The
    windowed branch is the one exercised; the headless twin is the same code selecting the
    other key, and a 40362-throttled headless search would mix the day's risk weather into
    a pool-width claim. G1 is the standing control at the other width: the same canvas
    shape with a pool that fits both workflows overlaps its walks — here it must not.

    Cost, chosen: these walks take excerpts (``full_body`` False). Ordering and delivery are
    the whole claim, and neither reads 正文, so the per-row 展开全文 clicks buy nothing here —
    unlike S1, whose first walk has to stay alive across the spacing gap and therefore keeps
    the full-body default.
    """
    harness.real_jar(monkeypatch, app_module)
    canvas = _two_search_components(
        keywords=KEYWORDS['S2'], target=5, headless=False, use_profile=False, extra={'full_body': False}
    )
    canvas['settings'].pop('max_workers', None)
    keys = ('same_platform_queue', 'same_platform_stagger', 'max_visible_browsers')
    before = {key: settings_store.get_setting(key) for key in keys}
    _saved, warnings = settings_store.save_settings(
        {'same_platform_queue': False, 'same_platform_stagger': 0, 'max_visible_browsers': 1}
    )
    assert not warnings, warnings
    assert settings_store.get_setting('max_visible_browsers') == 1, 'the ceiling did not take'
    try:
        with LiveRun(client, app_module, canvas, case_id='S2', mode='posts', target=5, timeout=DEEP_TIMEOUT) as run:
            run.wait()
            assert run.record['status'] == 'completed', run.record
            assert run.record['wf_count'] == 2, f'two components, one record: {run.record["wf_count"]}'
            # The record still says 并行 — the ceiling narrowed the pool, not the mode.
            assert run.record['mode'] == 'parallel', run.record
            _assert_both_delivered(run, target=5)
            for key in (
                'run.platformQueued',
                'run.platformStaggered',
                'run.serialForced',
                'run.platformGateTimeout',
                'crawl.profile_wait',
            ):
                assert not harness.names_key(run.rec.text, key), (
                    f'the console said {key}: something OTHER than the pool serialized these '
                    'crawls, and the ceiling this case grades went untested'
                )
            started, ended = _crawl_window(run.rec)
            assert len(started) >= 2 and len(ended) >= 2, (
                f'two components were supposed to walk; the console shows {len(started)} starts and '
                f'{len(ended)} endings'
            )
            assert started[1] > ended[0], (
                f'the ceiling is one browser at a time, yet the second walk began at line '
                f'{started[1]} before the first ended at line {ended[0]} — the pool took more '
                'workflows concurrently than the settings page allowed'
            )
            answer = run.verdict('node-1')
            assert answer['verdict'] == harness.FULL, answer
            run.finish(answer=answer, node_id='node-1')
    finally:
        settings_store.save_settings(before)
