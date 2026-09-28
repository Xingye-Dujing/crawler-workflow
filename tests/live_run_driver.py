"""The run driver every LIVE program file shares — one real run, one audit row, no second copy.

:mod:`tests.live_run_harness` holds the *tools* (the console recorder, the verdict grader, the
canvas builders, the containment that presses 停止 for a case that died). This module holds the one
thing those tools were assembled for: the object that starts a run through the app, watches it to its
verdict, judges the transcript that belongs to it, and writes the audit row — ~450 lines of sequencing
that a second platform's program file must not re-type. The repo's own rule for a duplicated walk loop
applies to a duplicated driver just as much: two copies drift, and the drift is invisible because both
"work".

What a platform supplies is three facts, not a subclass of logic:

* :attr:`RunDriver.PLATFORM` — which cookie jar, which profile directory, which audit column;
* :attr:`RunDriver.DEFAULT_TIMEOUT` — that platform's own worst case stacked up from the product's
  timeouts (a board fetch and a per-row detail crawl are not the same budget);
* :meth:`RunDriver.vocabulary` — which console lines excuse a shortfall *in this mode and this shape*,
  and which of them are known liars. This is the only hook with real logic in it, because it *is* the
  per-platform knowledge: the same sentence is an honest exit on one platform's headless throttle and a
  documented lie on another's stalled scroll loop (``docs/live_test_plan.md`` §5).

Keeping the sequencing here is also what makes the two program files comparable: a weibo cell and a
zhihu cell grade the same way, on the same ownership proofs (presence is not ownership — see
:meth:`RunDriver.assert_l3`), with the same containment on the way out.
"""

import contextlib
import time
from pathlib import Path

import live_run_harness as harness


def window_around(text: str, needle: str, width: int = 600) -> str:
    """The lines around a culprit, because a stamped console line without its neighbours is a quote."""
    at = text.find(needle)
    return text[max(0, at - width) : at + width] if at >= 0 else text[-width:]


class RunDriver:
    """One real run: started on construction, watched to its verdict, audited on the way out.

    Subclasses set :attr:`PLATFORM`, :attr:`DEFAULT_TIMEOUT` and :meth:`vocabulary`; nothing else about
    the sequencing is platform-shaped. The recorder opens *before* the POST because the earliest lines —
    the record the run was booked against, the validation errors, 「本次跳过」 — are exactly what a case
    needs when something refused it. Leaving the ``with`` block early on a failed assertion still writes
    the audit row, still hands the root logger back, and — the part that protects the *other* cases —
    asks 停止 for a run that is still crawling.
    """

    #: Which platform this program file crawls: the cookie jar, the profile, the audit column.
    PLATFORM = ''
    #: The wall-clock budget a case gets when it does not name one.
    DEFAULT_TIMEOUT = 1200.0
    #: Set → a session death that the console *names* is this platform's ordinary answer, so the case
    #: carries it as a WARN instead of convicting it. A per-file decision, not a per-case one: on a
    #: platform measured to be bounced mid-crawl (weibo's intermittent risk wall), repeating
    #: ``named_death_ok=True`` on every cell is how one cell forgets it and a red gets re-run as a
    #: mystery. The strict checks below (one line per fact, no traceback, no lost console) stay on.
    NAMED_DEATH_OK = False

    def __init__(
        self,
        client,
        app_module,
        workflow,
        *,
        case_id,
        mode,
        target,
        timeout=None,
        resume_run_id=None,
        queue=None,
        lang='zh',
        named_death_ok=False,
        llm=None,
    ):
        """*named_death_ok* is a decision about what a dead session convicts.

        A cookie that dies mid-crawl is a designed path (AGENTS): the node settles ``partial``, the run
        goes ``failed``, ``run.cookieExpired`` is printed and 继续 offers the cursor back. For a case
        that chose its own links that outcome is evidence the session is unreliable, so
        :meth:`assert_l3` refuses it. For a case running links **the user stored** — a pasted 评论 URL
        from a file he edits by hand — it is input age, not code, and the component verdicts are what
        the case is really about. Those cases pass the flag and the audit row carries the death as a WARN.
        """
        self.client = client
        self.app = app_module
        self.case_id = case_id
        self.workflow = workflow
        self.mode = mode
        self.target = target
        self.timeout = self.DEFAULT_TIMEOUT if timeout is None else timeout
        self.lang = lang
        self._named_death_ok = bool(named_death_ok) or bool(self.NAMED_DEATH_OK)
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
        self._audited = False
        self._closed = False
        # Read BEFORE the resume is asked for, because the ownership proof this case can give is the
        # pair of numbers the resume line itself prints: how many rows it is picking up and when the
        # interrupted attempt started. Afterwards they are the *new* run's.
        self._resume_proof = harness.read_record(client, resume_run_id) if resume_run_id else None
        self._resumed = bool(resume_run_id)
        try:
            self.accepted = harness.start(
                client, workflow, resume_run_id=resume_run_id, queue=queue, lang=lang, llm=llm
            )
        except BaseException:
            self.rec.close()
            self._closed = True
            raise
        self.run_id = self.accepted['run_id']

    # ── what this platform's lines mean ─────────────────────────────────

    def vocabulary(self, mode: str, headless: bool) -> tuple[tuple, tuple]:
        """``(legitimate exits, known liars)`` for one mode and one shape.

        The subclass owns this because it is the platform's measured knowledge, not the driver's. The
        default returns the shared exits alone, which is the strict answer: a program file that never
        says otherwise can only be excused by lines the executor prints for every platform.
        """
        return harness.SHARED_EXITS, ()

    # ── watching ────────────────────────────────────────────────────────

    def wait(self) -> dict:
        """Block until the run wrote its verdict, then read the record back.

        One budget, not two: the console watch gets the stated timeout and the thread watch gets
        whatever it did not spend. A case that handed ``self.timeout`` to each would cost twice its
        stated wall clock, and on this tier the difference is minutes-to-hours of the user's own login.
        """
        self.status = self.rec.pump(self.timeout, run_id=self.run_id)
        left = max(60.0, self.timeout - self.rec.elapsed())
        harness.wait_run_finished(self.app, timeout=left)
        self.status = self.rec.drain()
        if str(self.status.get('outcome') or '') == 'rejected':
            # Validation refused this canvas, so the app returned before opening a record (``app.py``
            # never creates a row for a rejected run). Reading one here would fail as 「no record for
            # run …」 and report the product's refusal as a missing run — the sentence that convicts is
            # the one the console already printed.
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

    def wait_refused(self, *, key: str) -> dict:
        """Watch a run the app must refuse **before anything is crawled**, and return its status.

        A canvas whose ``select`` holds a value the matrix does not offer is refused by
        :meth:`WorkflowEngine.validate` inside the run thread, which returns before ``run.started``
        books the console, before a node executes, before a profile is taken and before a record row
        exists (``app.py``, right after ``engine.validate()``). So :meth:`assert_l3`'s four sentences
        were never owed here — this case's evidence is the opposite shape: the refusal names itself,
        and **nothing was paid for**. A run that got through validation is reported as the failed
        premise it is, rather than graded on a table the case never asked for.
        """
        self.status = self.rec.pump(self.timeout, run_id=self.run_id)
        left = max(60.0, self.timeout - self.rec.elapsed())
        harness.wait_run_finished(self.app, timeout=left)
        self.status = self.rec.drain()
        outcome = str(self.status.get('outcome') or '')
        assert outcome == 'rejected', (
            f'the canvas was not refused before it crawled (outcome={outcome!r}), '
            f'so the console ended with the crawl it should not have started: {self.rec.lines[-6:]!r}'
        )
        assert harness.names_key(self.rec.text, key), f'the refusal did not name {key!r}: {self.rec.lines[-6:]!r}'
        assert not harness.mentions(self.rec.text, 'run.started', rid=self.run_id), (
            f'run {self.run_id} was refused yet still booked a console, so its crawler reached the site'
        )
        assert not harness.names_key(self.rec.text, 'wf.executing_node'), (
            'a refused canvas still executed a node: the table it filed is one the user was told not to ask for'
        )
        return self.status

    def rows(self, node_id: str = 'node-1') -> int:
        return harness.stored_rows(self.refresh(), node_id)

    def live_rows(self, node_id: str = 'node-1') -> int:
        """Rows on disk *right now*: a source node's ``row_count`` column is only re-derived when the
        node settles, so a case watching a crawl fill up has to ask the rows."""
        return int(self.app.get_run_store().row_count(self.run_id, node_id))

    def live_statuses(self) -> dict:
        """The store's per-node rows *right now*, mid-crawl — status included.

        ``self.record`` is only read at the wait's end, and a node's ``row_count`` column is written by
        ``finish_node``, which a walking crawl has not reached: so "which of my two components is still
        inside its walk" is answered here, and only together with :meth:`live_rows` does it mean
        anything (a node that is ``running`` still reads 0).
        """
        return self.app.get_run_store().node_statuses(self.run_id)

    def stop(self) -> dict:
        """Press 停止 for this case's own run, and refuse a press that took no record.

        The stop cases all cut a live crawl short and the request is the same one the user's button
        makes; a second copy of the guard is how one of them ends up asserting a different answer from
        the endpoint. ``records`` is the proof the Stop found a run to own — an idle server answers
        「ok」 with nothing stopped, which is not evidence.
        """
        stopped = self.client.post('/api/workflow/stop').get_json()
        assert stopped.get('ok') and stopped.get('records'), f'停止 answered without taking a record: {stopped}'
        return stopped

    def wait_until(self, predicate, *, within: float, what: str) -> None:
        """Poll the console and the rows until *predicate* holds, or fail naming what it waited for.

        The trigger for a mid-crawl 停止 cannot be a sleep: a crawl that stored its first row at second
        40 and one that stored it at second 900 are the same test, and a fixed wait would either press
        too early (nothing to stop) or too late (a crawl that finished). One second per pass, with a
        status page read on every pass so the transcript this case later judges still holds every line
        the run wrote.

        A run that reaches its verdict first is reported as the failed premise it is, rather than being
        sat on for the whole deadline: 「there was nothing to stop」 is a different finding from 「the
        crawl never started」, and both are different from a timeout.
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
        canvas*: ``_durable_node_rows`` answers nothing rather than guessing when its identity lookup
        misses. The default is the name the run's own record carries, which is the backend's precedence
        (name node, then file name) — so a case cannot read a stranger's ``node-2`` and believe it
        measured its own.
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

        The vocabulary defaults to this case's own *mode* and *shape*: an author walk is excused by
        lines a search never prints, and a headless crawl is excused by the throttle a windowed one may
        not hide behind. *console* defaults to the whole run, which is the right slice for a
        single-component canvas and the wrong one for a four-component run — see
        :meth:`component_verdict`.
        """
        asked = self.target if target is None else target
        kept = self.rows(node_id) if rows is None else rows
        default_exits, default_liars = self.vocabulary(self.mode, self.headless)
        return harness.classify_verdict(
            asked,
            kept,
            self.rec.text if console is None else console,
            exits=default_exits if exits is None else exits,
            bug_lines=default_liars if bug_lines is None else bug_lines,
        )

    def component_verdict(self, label: str, record: dict, node_id: str, *, target: int, mode: str) -> dict:
        """This component's own verdict, graded against its own workflow's console.

        A reason named by a sibling is not this component's reason: graded on the whole transcript, a
        0-row author walk is excused by the search beside it saying 「没有更多了」, and a multi-component
        run — the shape that can hide it — could never be told apart from one that said nothing.
        """
        exits, liars = self.vocabulary(mode, self.headless)
        return harness.classify_verdict(
            target,
            harness.stored_rows(record, node_id),
            self._slice(label),
            exits=exits,
            bug_lines=liars,
        )

    def _slice(self, label: str) -> str:
        """This workflow's own transcript, and a refusal when the console has none for it.

        Falling back to the whole console would be the false green these helpers exist to prevent:
        graded on everybody's lines, a 0-row component is excused by a sibling's 「没有更多了」, and one
        component's 被停止 reads as another's — which is exactly what :meth:`component_verdict` and
        ``ConsoleRecorder.transcript_for`` warn the caller about. So a component the console never
        spoke about is reported as an attribution failure by name, not graded on evidence that belongs
        to its neighbour.
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

        Four sentences in that order, with the last one allowed to be any of the ways a node honestly
        ends. The console is the user's only view of a crawl, so a run that filed the right table while
        saying none of this has already failed at being diagnosable.

        And the transcript must be *this run's*: presence is not ownership. ``run.started`` carries the
        run id, so the booking line is matched with the id the case then reads rows for; a resume prints
        no id, so a resumed case proves it by the two numbers the resume line does carry, taken from the
        record before the continue was asked for.
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

        assert 'Traceback' not in text, f'a traceback reached the console:\n{window_around(text, "Traceback")}'
        died = harness.names_key(text, 'run.cookieExpired')
        self.cookie_expired = bool(self.status.get('cookie_expired')) or died
        if not self._named_death_ok:
            assert not died, f'the session died mid-crawl:\n{window_around(text, "cookie")}'
            assert self.status.get('cookie_expired') is False, f'the run reported a dead cookie: {self.status}'
        # "One failure, one line" is a statement about a *message*, so it is counted by key. Comparing
        # whole console entries instead compares strings that each begin with the stamping second
        # (``add_log`` writes ``[HH:MM:SS] ``), so the same refusal printed one second apart is two
        # different lines and the check can never fire — which is how a 双打 like the login-wall one
        # docs/live_test_plan.md §6 TX7 records would pass here.
        for key in ('wf.validation_error', 'run.rejected', 'run.cookieExpired'):
            said = self.rec.counts_key(key)
            assert said <= 1, f'{key} printed {said} lines; one fact is one console line'
            if key == 'run.rejected':
                assert said == 0, 'the canvas was refused by validation'
        # The two lines that carry a node id are one fact *per node*. A four-component canvas that
        # loses two of them owes two sentences; counting the key across the whole run read the
        # sibling's honest failure as a 双打 that never happened — and reported it as a console defect
        # instead of naming the two nodes that actually died.
        for key in ('wf.node_failed', 'run.nodeStopped'):
            named = harness.slots_from(self.rec.lines, key, 'nid')
            doubled = sorted({str(one) for one in named if named.count(one) > 1})
            assert not doubled, f'{key} spoke twice about the same node {doubled}: one fact, one line'
        assert not self.rec.overflow, (
            'the status window was out-run, so this transcript has gaps and cannot convict '
            f'{self.target} rows of anything'
        )

    def audit(self, case_id: str, *, verdict, reasons, rows, target, warn=False, mode=None) -> Path:
        """One audit row plus one transcript, for one crawl. A case with four components writes four.

        *mode* overrides this run's own word for a component row: an acceptance canvas runs four modes in
        one process, and a ledger whose four rows all say the case's ``mode`` cannot be matched back to the
        crawl each of them describes.
        """
        payload = {
            'recorder': self.rec,
            'platform': self.PLATFORM,
            'mode': str(mode or self.mode),
            'headless': self.headless,
            'use_profile': '' if self.use_profile is None else self.use_profile,
            'lang': self.lang,
            'target': target,
            'rows': rows,
            'verdict': f'{verdict}/WARN' if warn and verdict != harness.FULL else verdict,
            'reasons': list(reasons),
            'wall_flags': harness.wall_flags(self.rec.text),
            'cookie_expired': bool(getattr(self, 'cookie_expired', False)),
            # What containment had to do on the way out, in the row that explains why the *next* case
            # had to wait for a lane. An empty dict is the case's own answer to "the run settled
            # itself", so the column distinguishes the two instead of going blank.
            'abort': self.abort_note,
            'seconds': self.rec.elapsed(),
        }
        path = harness.audit_dump(case_id, payload)
        self._audited = True
        return path

    def warned(self) -> bool:
        """Whether this run owes a WARN: a dead session it was allowed to name, or a shortfall the site
        explained. A case that lets ``cookie_expired`` stand must say so in its row."""
        return bool(getattr(self, 'cookie_expired', False))

    def finish(self, *, answer=None, node_id: str = 'node-1', warn=False, case_id=None, target=None, rows=None):
        """The case's shared epilogue: the L3 checks, the audit row, and the recorder closed.

        ``warn`` is ORed with :meth:`warned`, so a run that was allowed to name a dead session cannot
        land a plain green row: the artifact is where a WARN must survive even when the assertions
        below it passed.
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
            # Read the table this case died holding *before* containment, so the row states what the
            # assertions saw rather than what the worker filed after they stopped looking.
            kept = 0
            with contextlib.suppress(Exception):
                kept = self.rows() if self.run_id else 0
            if self.run_id and not harness.settled(self.status):
                # The case is over and the crawl is not. Left alone, that worker keeps the platform's
                # lane and the profile directory away from every later case, keeps its browser out of
                # anyone's reach (the client teardown restores ``execution_state`` wholesale, handle
                # included), and keeps narrating lines that the *next* case will fold into its own
                # transcript — where a stranger's 「没有更多了」 can turn a real under-collection into a
                # named, legitimate one. Containment therefore happens before the row is written: the
                # row is where a leak gets reported, and a leak the next case inherits is the finding.
                with contextlib.suppress(Exception):
                    self.abort_note = harness.abort_run(
                        self.client, self.app, self.rec, budget=min(600.0, self.timeout), run_id=self.run_id
                    )
            if not self._audited:
                # A failed assertion is exactly when the transcript matters: the next attempt costs
                # minutes of real crawling and some of the account's patience.
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
