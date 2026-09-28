"""The run-level live harness, tested in the fast tier where none of it needs a browser.

:mod:`tests.live_run_harness` is the machinery a live matrix reads its own evidence with, so
every one of its parts is a place where a wrong answer would turn a real crawl into a
comfortable lie: a console recorder that drops lines makes "the site named why it stopped"
unverifiable, a verdict classifier that accepts a silent shortfall passes the exact bug the
live tier exists to catch, and a canvas builder that drifts from the crawl matrix tests a
node shape no user can produce. None of that needs Chrome, a network or the application —
the fake poller below stands in for the status endpoint, and the matrix is imported for
real because it *is* the contract.

The audit root is redirected into ``tmp_path`` everywhere it could write, so this module
leaves the real ``scratchpad/live_audit`` exactly as it found it: the fast tier must not
grow an index of cases that never ran.
"""

import logging
from pathlib import Path

import live_run_harness as harness
import pytest

import crawl_capabilities as capabilities
import i18n

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
PLATFORM = 'zhihu'


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def get_json(self):
        return self._payload


class _FakeClient:
    """The one slice of the test client the harness uses: ``get``/``post`` returning JSON.

    Status pages are handed over as a list, so a test can script "what the endpoint said on
    poll 1, 2, 3" — which is the whole subject here. The last page repeats, because a
    recorder that kept polling a finished run must be tested against a console that
    stopped growing, not against an IndexError.
    """

    def __init__(self, pages=(), execute=None):
        self._pages = list(pages)
        self._execute = execute or {'ok': True, 'run_id': 'run-1'}
        self.reads = 0
        self.posted = []

    def get(self, path):
        assert path == '/api/workflow/status', path
        page = self._pages[min(self.reads, len(self._pages) - 1)] if self._pages else {'logs': [], 'log_total': 0}
        self.reads += 1
        return _Response(page)

    def post(self, path, json=None):
        self.posted.append((path, json))
        return _Response(self._execute)


def _page(lines, total=None):
    """A status payload shaped like the real one: a capped tail plus the running total."""
    tail = list(lines)[-harness.CONSOLE_WINDOW :]
    return {'logs': tail, 'log_total': len(lines) if total is None else total, 'outcome': '', 'running': True}


# ─── console recording ──────────────────────────────────────────────────


class TestConsoleRecorder:
    def test_every_line_arrives_exactly_once(self):
        first = ['a', 'b', 'c']
        second = ['a', 'b', 'c', 'd']
        client = _FakeClient(pages=[_page(first), _page(second), _page(second)])
        recorder = harness.ConsoleRecorder(client, mirror=False)
        try:
            recorder.snapshot()
            recorder.snapshot()
            recorder.snapshot()
            assert recorder.lines == ['a', 'b', 'c', 'd'], 'a line was missed or counted twice'
            assert recorder.snapshots == 3 and not recorder.overflow
        finally:
            recorder.close()

    def test_a_window_older_than_the_delta_is_admitted_not_hidden(self):
        """More new lines than the tail can carry: the transcript has a hole, and says so."""
        lines = [f'line-{i}' for i in range(harness.CONSOLE_WINDOW + 40)]
        client = _FakeClient(pages=[_page(lines[:20], total=20), _page(lines)])
        recorder = harness.ConsoleRecorder(client, mirror=False)
        try:
            recorder.snapshot()
            recorder.snapshot()
            assert recorder.overflow is True, 'a 240-line gap on a 200-line window was reported as complete'
            # What survived is the newest 220 of them; the 20 already read are not re-added.
            assert len(recorder.lines) == 20 + harness.CONSOLE_WINDOW
            assert recorder.lines[-1] == lines[-1]
            assert recorder.complete() is False, 'a gapped transcript must not claim the whole run'
            assert len(set(recorder.lines)) == len(recorder.lines), 'the overlap was duplicated instead of skipped'
        finally:
            recorder.close()

    def test_an_unchanged_console_adds_nothing(self):
        page = _page(['only'])
        recorder = harness.ConsoleRecorder(_FakeClient(pages=[page, page, page]), mirror=False)
        try:
            for _ in range(3):
                recorder.snapshot()
            assert recorder.lines == ['only']
            assert recorder.complete() and recorder.counted == 1
        finally:
            recorder.close()

    def test_the_transcript_proves_it_holds_every_line_the_server_counted(self):
        """``complete`` is the recorder's own evidence that nothing was lost: a case may
        assert on 900 lines because the count says all 900 are here, not because the
        transcript happened to look plausible."""
        lines = [f'l{i}' for i in range(30)]
        client = _FakeClient(pages=[_page(lines[:10]), _page(lines[:22]), _page(lines), _page(lines)])
        recorder = harness.ConsoleRecorder(client, mirror=False)
        try:
            for _ in range(4):
                recorder.snapshot()
            assert recorder.lines == lines
            assert recorder.counted == 30 and recorder.complete()
        finally:
            recorder.close()

    def test_a_run_that_began_before_the_first_look_is_reported_as_gapped(self):
        """250 lines on a 200-line tail: the head of the crawl is gone, and the transcript
        has to admit it rather than present what it caught as the whole conversation."""
        lines = [f'l{i}' for i in range(250)]
        recorder = harness.ConsoleRecorder(_FakeClient(pages=[_page(lines)]), mirror=False)
        try:
            recorder.snapshot()
            assert recorder.resets == 0, 'a first read has no previous console to reset from'
            assert recorder.overflow is True
            assert recorder.counted == 250 and len(recorder.lines) == 200
            assert recorder.complete() is False, 'a gapped transcript passed itself as the whole run'
        finally:
            recorder.close()

    def test_first_index_answers_where_not_whether(self):
        recorder = harness.ConsoleRecorder(None, mirror=False)
        recorder.lines = ['无关', i18n.t('run.started', rid='abc'), i18n.t('run.finished', done=1, total=1)]
        assert recorder.first_index('run.started') == 1
        assert recorder.first_index('run.finished') == 2
        assert recorder.first_index('crawl.zhihu.no_more') == -1, 'a missing line must not read as "first"'

    def test_a_second_run_is_counted_as_a_reset_and_kept_in_one_transcript(self):
        """A resume is one conversation across two console resets; the recorder must not
        restart its own memory, and must not report a reset as if it were nothing."""
        recorder = harness.ConsoleRecorder(
            _FakeClient(
                pages=[
                    _page(['one run', 'of lines', 'here']),
                    {'logs': ['second run'], 'log_total': 1, 'outcome': 'completed'},
                ]
            ),
            mirror=False,
        )
        try:
            recorder.snapshot()
            recorder.snapshot()
            assert recorder.resets == 1
            assert recorder.lines == ['one run', 'of lines', 'here', 'second run']
            assert recorder.complete(), 'a transcript that spans two runs must still tie to the current count'
        finally:
            recorder.close()

    def test_find_is_any_of_and_counts_are_per_line(self):
        recorder = harness.ConsoleRecorder(None, mirror=False)
        recorder.lines = ['知乎: 没有更多了', '知乎: 达到目标 10', '其他']
        assert recorder.find('没有更多', '达到目标') == ['知乎: 没有更多了', '知乎: 达到目标 10']
        assert recorder.find('') == [], 'an empty needle would match every line and prove nothing'
        assert recorder.counts('知乎') == 2 and recorder.counts('nope') == 0
        assert '其他' in recorder.text

    def test_counts_key_sees_the_line_whatever_its_parameters_were(self):
        recorder = harness.ConsoleRecorder(None, mirror=False)
        rendered = i18n.t('crawl.zhihu.no_more', i=7)
        assert rendered != 'crawl.zhihu.no_more', 'the catalogue lost the line this test is built on'
        recorder.lines = [f'[00:00:01] {rendered}', '[00:00:02] 无关', i18n.t('crawl.zhihu.no_more', i=1)]
        assert recorder.counts_key('crawl.zhihu.no_more') == 2

    def test_close_hands_the_root_logger_back(self):
        root = logging.getLogger()
        before = list(root.handlers)
        level = root.level
        recorder = harness.ConsoleRecorder(None)
        assert root.handlers != before, 'the mirror stream was never installed'
        recorder.close()
        assert list(root.handlers) == before, 'a handler left installed grows for the whole session'
        assert root.level == level, 'a level lowered here changes every later test'
        recorder.close()  # idempotent: a case that closes in finally and again is not a bug


class TestSettled:
    @pytest.mark.parametrize(
        'payload, expected',
        [
            ({'running': True, 'outcome': 'completed'}, False),
            ({'running': False, 'stopping': True, 'outcome': 'completed'}, False),
            ({'running': False, 'settling': True, 'outcome': 'completed'}, False),
            ({'running': False, 'outcome': ''}, False),
            ({'running': False, 'outcome': 'completed'}, True),
            ({'running': False, 'outcome': 'interrupted'}, True),
            ({'running': False, 'outcome': 'rejected'}, True),
        ],
    )
    def test_only_a_written_verdict_ends_the_watch(self, payload, expected):
        """停止 clears ``running`` on the request thread while the worker still owes the
        record its conclusion, so a recorder that trusted that flag alone would read the
        console before the finish sentence existed."""
        assert harness.settled(payload) is expected


# ─── verdicts ───────────────────────────────────────────────────────────

_NAMED_LINE = i18n.t('crawl.zhihu.no_more', i=4)
_OTHER_EXITS = ('crawl.zhihu.no_more', 'crawl.zhihu.hotCapped', 'crawl.zhihu.stuck')


class TestClassifyVerdict:
    def _console(self, *extra):
        return '\n'.join(['开始搜索知乎关键词', *extra])

    @pytest.mark.parametrize(
        'target, rows, console, expected',
        [
            # rows == target and rows > target are both FULL: the target is a floor the
            # user asked for, never a ceiling the crawler is allowed to stop at.
            (10, 10, 'nothing', harness.FULL),
            (10, 40, 'nothing', harness.FULL),
            (10, 9, _NAMED_LINE, harness.NAMED_SHORT),
            (10, 0, _NAMED_LINE, harness.NAMED_SHORT),
            (10, 9, 'nothing', harness.SILENT_SHORT),
            (10, 0, 'nothing', harness.SILENT_SHORT),
            (0, 0, 'nothing', harness.FULL),
        ],
    )
    def test_the_grid(self, target, rows, console, expected):
        answer = harness.classify_verdict(target, rows, self._console(console), exits=_OTHER_EXITS)
        assert answer['verdict'] == expected, answer

    def test_full_names_no_reason_because_there_is_none_to_name(self):
        answer = harness.classify_verdict(3, 3, self._console(_NAMED_LINE), exits=_OTHER_EXITS)
        assert answer == {'verdict': harness.FULL, 'reasons': []}

    def test_a_named_short_grades_by_the_key_not_by_a_pasted_sentence(self):
        answer = harness.classify_verdict(20, 4, self._console(_NAMED_LINE), exits=_OTHER_EXITS)
        assert answer['verdict'] == harness.NAMED_SHORT
        assert answer['reasons'] == ['crawl.zhihu.no_more'], 'the audit row must cite the catalogue, not one language'

    def test_a_silent_short_says_what_is_missing_in_numbers(self):
        answer = harness.classify_verdict(20, 4, self._console(), exits=_OTHER_EXITS)
        assert answer['verdict'] == harness.SILENT_SHORT
        assert '4 of 20' in answer['reasons'][0], answer['reasons']

    def test_an_exit_outside_the_graders_vocabulary_is_not_an_exit(self):
        """A platform's own refusal must be handed over explicitly. Grading every
        platform against zhihu's message names would call a bilibili 「页数走完」 a silent
        shortfall — or, the other way round, accept zhihu's word for someone else's."""
        answer = harness.classify_verdict(10, 1, self._console(_NAMED_LINE))
        assert answer['verdict'] == harness.SILENT_SHORT, "the shared default must not know zhihu's vocabulary"

    def test_the_shared_exits_are_all_real_catalogue_lines(self):
        for key in harness.SHARED_EXITS:
            rendered = i18n.t(key, platform='zhihu', where='x', nid='n', n=1, url='u', i=1, tab='t', author='a')
            assert rendered != key, f'{key} is not in the catalogue, so it can never match a console line'
            assert harness.names_key(rendered, key), f'{key} does not match its own rendered line'

    def test_stop_is_graded_by_the_line_the_executor_actually_prints(self):
        """``crawl.stopped`` is the *message of* ``CrawlerStopped`` and ``_settle_node_as_stopped``
        is handed ``err=''``, so it reaches neither console nor record. A whitelist entry no code
        can print is how a later platform's author concludes that stopping is graded — by a line
        that never appears — while a real 停止 short-crawl reads as silent."""
        assert 'crawl.stopped' not in harness.SHARED_EXITS
        assert 'run.nodeStopped' in harness.SHARED_EXITS

    def test_a_line_the_plan_measures_as_a_lying_one_does_not_excuse_a_shortfall(self):
        """``docs/live_test_plan.md`` §5 keeps a second list beside the whitelist: sentences that
        report a site answer while reporting a walk that gave up (Z6's 「未加载新内容」, Z3's
        「为空或被拦截」). Admitted as exits they license the exact silent under-collection the
        tier exists to catch, so the grader is handed them as ``bug_lines`` instead."""
        liar = i18n.t('crawl.zhihu.stuck', n=1)
        answer = harness.classify_verdict(
            40,
            12,
            self._console(liar),
            exits=('crawl.zhihu.no_more', 'crawl.zhihu.stuck'),
            bug_lines=('crawl.zhihu.stuck',),
        )
        assert answer['verdict'] == harness.SILENT_SHORT, answer
        assert 'crawl.zhihu.stuck' in answer['reasons'][0], 'the row has to quote the liar it convicted'

    def test_a_honest_exit_beside_a_lying_one_still_explains_the_shortfall(self):
        """The liar is not a ban on the whole console: a walk that said 「没有更多了」 and also
        printed a 虚报 line on the way is still a named short — with both keys in the row."""
        answer = harness.classify_verdict(
            40,
            12,
            self._console(i18n.t('crawl.zhihu.stuck', n=1), _NAMED_LINE),
            exits=('crawl.zhihu.no_more', 'crawl.zhihu.stuck'),
            bug_lines=('crawl.zhihu.stuck',),
        )
        assert answer['verdict'] == harness.NAMED_SHORT, answer
        assert answer['reasons'] == ['crawl.zhihu.no_more', 'crawl.zhihu.stuck'], answer


class TestSlotExtraction:
    """Reading a *number out of* a catalogue line, for the cases that tie a table to a sentence."""

    def test_a_named_slot_is_read_in_whichever_language_the_run_narrated(self):
        for lang in i18n.LANGS:
            i18n.set_lang(lang)
            try:
                lines = [
                    '[00:00:01] '
                    + i18n.t('comment.article', url='https://x/answer/1', n=7, status=i18n.t('comment.status.ok')),
                    '[00:00:02] 无关的一行',
                ]
            finally:
                i18n.set_lang('zh')
            assert harness.numbers_from(lines, 'comment.article', 'n') == [7], lang

    def test_the_sum_of_the_per_article_lines_is_what_a_comment_node_owes(self):
        """The pair the comment cases tie: 每篇 的新增数 求和 == 总数 == the stored table. Reading
        both out of the catalogue is what keeps a reworded summary from turning four cases red."""
        parts = [('https://a/answer/1', 3), ('https://a/answer/2', 5)]
        lines = [i18n.t('comment.article', url=url, n=n, status=i18n.t('comment.status.ok')) for url, n in parts]
        lines.append(
            i18n.t(
                'comment.done',
                urls=len(parts),
                ok=len(parts),
                blocked=0,
                dead=0,
                rows=sum(n for _u, n in parts),
                files=1,
            )
        )
        assert harness.numbers_from(lines, 'comment.article', 'n') == [3, 5]
        assert harness.numbers_from(lines, 'comment.done', 'rows') == [8]

    def test_an_unknown_slot_reads_nothing_rather_than_the_wrong_number(self):
        """A typo in a slot name is a visible empty result, not a silent capture of whatever the
        first widened group happened to swallow."""
        line = i18n.t('crawl.zhihu.hotCapped', board=30)
        assert harness.numbers_from([line], 'crawl.zhihu.hotCapped', 'board') == [30]
        assert harness.numbers_from([line], 'crawl.zhihu.hotCapped', 'rows') == []

    def test_a_slot_is_never_read_across_two_lines(self):
        half = i18n.MESSAGES['zh']['comment.article'].split('{n}')[0]
        other = i18n.MESSAGES['zh']['comment.article'].split('{n}')[-1]
        assert harness.numbers_from([f'{half}aaa\nbbb{other}'], 'comment.article', 'n') == []

    def test_the_text_of_a_slot_survives_a_windows_path(self):
        """``crawl.profile_wait`` names the profile directory, and G3 has to prove the wait was
        for *this* platform's — so the slot has to come back whole, backslashes and all."""
        line = i18n.t('crawl.profile_wait', seconds=12, dir='C:\\temp\\live_profiles\\zhihu')
        assert harness.slots_from([line], 'crawl.profile_wait', 'dir') == ['C:\\temp\\live_profiles\\zhihu']


class TestConsoleStamps:
    """The ``[HH:MM:SS]`` prefix ``add_log`` gives every line, read back as seconds — the only
    console-side answer to "how far apart were these two events", which S1's 错峰 spacing needs."""

    def test_a_stamped_line_becomes_seconds_since_midnight(self):
        assert harness.stamped_second('[09:30:15] 搜索完成') == 9 * 3600 + 30 * 60 + 15
        assert harness.stamped_second('[00:00:00] just past midnight') == 0.0

    def test_the_clock_is_the_prefix_and_not_somebody_text(self):
        """A line *quoting* a stamp mid-sentence must not read as if it began with one: the
        spacing a case measures would otherwise latch onto whatever the crawler printed."""
        assert harness.stamped_second('stalled at [12:00:00] exactly') is None
        assert harness.stamped_second('') is None
        assert harness.stamped_second('[99:99:99] impossible clock') is None


class TestPerWorkflowTranscripts:
    """A four-component run is four consoles, and a verdict must read the one it belongs to."""

    @staticmethod
    def _wf(wid, name, lines, total=None):
        return {'id': wid, 'name': name, 'logs': list(lines), 'total': len(lines) if total is None else total}

    def test_each_workflow_keeps_its_own_slice_and_nothings_else(self):
        first = self._wf(0, '热榜', ['board started', 'board finished'])
        second = self._wf(1, '作者', ['author started'])
        page = {
            'logs': ['board started', 'author started', 'board finished'],
            'log_total': 3,
            'workflows': [first, second],
        }
        later = {
            'logs': ['board started', 'author started', 'board finished', 'author finished'],
            'log_total': 4,
            'workflows': [first, self._wf(1, '作者', ['author started', 'author finished'])],
        }
        recorder = harness.ConsoleRecorder(_FakeClient(pages=[page, later]), mirror=False)
        try:
            recorder.snapshot()
            recorder.snapshot()
            assert recorder.transcript_for('作者') == 'author started\nauthor finished'
            assert recorder.transcript_for('热榜') == 'board started\nboard finished'
            assert 'author finished' not in recorder.transcript_for('热榜'), 'the slice leaked the sibling'
            assert recorder.transcript_for('nobody') == '', 'an unknown name must not inherit the whole console'
        finally:
            recorder.close()

    def test_a_console_reset_clears_the_slices_with_it(self):
        """A reset is a second run: a slice that kept the first run's lines would grade a fresh
        component against its predecessor's reasons."""
        page = {
            'logs': ['one'],
            'log_total': 5,
            'workflows': [self._wf(0, '甲', ['four', 'five'], total=5)],
        }
        again = {'logs': ['two'], 'log_total': 1, 'workflows': [self._wf(0, '甲', ['two'])]}
        recorder = harness.ConsoleRecorder(_FakeClient(pages=[page, again]), mirror=False)
        try:
            recorder.snapshot()
            recorder.snapshot()
            assert recorder.resets == 1
            assert recorder.transcript_for('甲') == 'two'
        finally:
            recorder.close()


class TestAbortRun:
    """A case that dies mid-crawl must not leave the crawl running."""

    class _StopClient:
        """Answers the two routes the recorder and the abort use, and records the stop."""

        def __init__(self, pages):
            self._pages = list(pages)
            self.reads = 0
            self.stops = 0

        def get(self, path):
            page = self._pages[min(self.reads, len(self._pages) - 1)]
            self.reads += 1
            return _Response(page)

        def post(self, path, json=None):
            assert path == '/api/workflow/stop', path
            self.stops += 1
            return _Response({'ok': True, 'browsers': 1, 'records': ['r1']})

    class _Module:
        """The one attribute of ``app`` the wait reads: a thread that is not alive."""

        execution_state = {'running': False, 'thread': None, 'outcome': 'interrupted'}

    def test_a_leaked_run_is_stopped_and_its_verdict_is_read_before_letting_go(self):
        live = {'logs': ['crawl running'], 'log_total': 1, 'running': True, 'outcome': ''}
        stopped = {
            'logs': ['crawl running', 'run.nodeStopped'],
            'log_total': 2,
            'running': False,
            'outcome': 'interrupted',
        }
        client = self._StopClient([live, live, stopped, stopped])
        recorder = harness.ConsoleRecorder(client, cadence=0, mirror=False)
        try:
            payload = harness.abort_run(client, self._Module(), recorder, budget=5, run_id='r1')
            assert client.stops == 1, 'the run was never asked to stop'
            assert payload.get('outcome') == 'interrupted', payload
            assert payload.get('abort_quiet') is True, payload
            assert 'run.nodeStopped' in recorder.text, 'the transcript must reach the verdict before it is closed'
        finally:
            recorder.close()

    def test_a_stop_that_cannot_be_asked_is_reported_not_raised(self):
        class _Boom:
            def get(self, path):
                return _Response({'logs': [], 'log_total': 0})

            def post(self, path, json=None):
                raise OSError('no route')

        recorder = harness.ConsoleRecorder(_Boom(), cadence=0, mirror=False)
        try:
            payload = harness.abort_run(_Boom(), self._Module(), recorder, budget=1)
            assert 'no route' in payload['abort_error'], payload
        finally:
            recorder.close()

    def test_a_worker_that_stays_alive_is_named_with_its_state(self, monkeypatch):
        """The half of containment that actually costs the tier: 停止 was asked, the verdict was
        read, and the *thread* is still there.

        The fake module's ``execution_state['thread']`` is a live handle, which is the state the
        rest of the session pays for — the platform lane and the profile directory are still held
        by a browser nobody can reach. ``run_finished`` is patched rather than waited on: the real
        helper polls its full budget (30 s minimum) before it answers False, and this tier's
        ceiling is seconds. ``describe_state`` still reads the live handle, so the message the row
        will carry is the one the product's own state produces.
        """

        class _LiveThread:
            @staticmethod
            def is_alive():
                return True

        class _BusyModule:
            execution_state = {'running': True, 'thread': _LiveThread(), 'outcome': 'running'}
            _RUN_QUEUE: list = []

        monkeypatch.setattr(harness, 'run_finished', lambda module, timeout=30.0: False)
        stopped = {
            'logs': ['run.nodeStopped'],
            'log_total': 1,
            'running': False,
            'outcome': 'interrupted',
        }
        client = self._StopClient([stopped])
        recorder = harness.ConsoleRecorder(client, cadence=0, mirror=False)
        try:
            payload = harness.abort_run(client, _BusyModule(), recorder, budget=1, run_id='r1')
            assert client.stops == 1
            assert payload['abort_quiet'] is False, payload
            assert payload['abort_error'].startswith('the aborted worker is still alive'), payload
            assert 'thread_alive=True' in payload['abort_error'], payload
            assert harness.abort_summary(payload) == f'not contained: {payload["abort_error"]}'
        finally:
            recorder.close()

    def test_abort_summary_tells_a_leak_from_a_run_that_settled_on_its_own(self):
        """'' and 'contained' are different facts, and both are different from a leak."""
        assert harness.abort_summary(None) == ''
        assert harness.abort_summary({}) == ''
        assert harness.abort_summary({'abort_quiet': True}) == 'contained'
        assert harness.abort_summary({'abort_quiet': False, 'abort_error': 'still alive'}) == (
            'not contained: still alive'
        )
        assert harness.abort_summary({'abort_quiet': True, 'abort_error': 'the pump timed out'}) == (
            'not contained: the pump timed out'
        )
        assert harness.abort_summary({'abort_quiet': False}) == 'not contained: the worker never reported'


class TestWalls:
    def test_a_risk_block_is_not_a_dead_session(self):
        """The two facts wear one face in a row count and completely different ones in a
        fix: risk control says back off, a login wall says refresh the cookie."""
        risk = i18n.t('crawl.riskBlocked', platform='zhihu', where='search')
        wall = i18n.t('crawl.loginWall', platform='zhihu', where='search')
        assert harness.wall_flags(risk) == ['crawl.riskBlocked']
        assert harness.wall_flags(wall) == ['crawl.loginWall']
        assert harness.wall_flags('') == []


# ─── language ───────────────────────────────────────────────────────────


class TestLanguage:
    def test_resolve_answers_in_every_catalogue_language_and_leaves_the_thread_alone(self):
        i18n.set_lang('en')
        try:
            both = harness.resolve('crawl.zhihu.target_reached', n=10)
            assert len(both) == len(i18n.LANGS) == 2
            assert set(both) == {
                i18n.MESSAGES['zh']['crawl.zhihu.target_reached'].format(n=10),
                i18n.MESSAGES['en']['crawl.zhihu.target_reached'].format(n=10),
            }
            assert i18n.get_lang() == 'en', "the caller pinned this thread's language; a helper may not move it"
        finally:
            i18n.set_lang('zh')

    def test_a_missing_parameter_stays_visible_instead_of_matching_nothing(self):
        """``t()`` returns the raw template when a parameter is forgotten, so a case that
        drops ``{n}`` sees ``{n}`` in its own needle and fails loudly rather than quietly
        finding no such line."""
        assert '{n}' in harness.resolve('crawl.zhihu.target_reached')[0]

    def test_names_key_matches_a_rendered_line_and_rejects_an_unrelated_one(self):
        line = i18n.t('run.nodeStopped', nid='采集 #node-1', n=7)
        assert harness.names_key(line, 'run.nodeStopped')
        assert not harness.names_key(line, 'crawl.zhihu.no_more')
        assert harness.mentions(line, 'run.nodeStopped', nid='采集 #node-1', n=7)
        assert not harness.mentions(line, 'run.nodeStopped', nid='采集 #node-1', n=8)

    def test_a_slot_never_bridges_two_lines(self):
        """The matcher is built from one template's halves; with ``.*`` allowed to cross a
        newline, a login wall on one row plus a risk line on the next would read as one
        named exit."""
        half = i18n.MESSAGES['zh']['crawl.loginWall'].split('{platform}')[0]
        other = i18n.MESSAGES['zh']['crawl.loginWall'].split('{platform}')[-1]
        assert not harness.names_key(f'{half}aaa\nbbb{other}', 'crawl.loginWall')


# ─── canvases ───────────────────────────────────────────────────────────


class TestCanvasAgainstTheMatrix:
    def test_every_zhihu_mode_builds_a_node_the_matrix_accepts(self):
        """Parity, not a copy: the params block is whatever ``declared_defaults`` says, so
        a new field cannot be missing from a live canvas the way a hand-written dict would
        be missing it the week somebody adds it."""
        defaults = capabilities.declared_defaults(PLATFORM)
        for mode in capabilities.modes_for(PLATFORM):
            params = harness.params_for(PLATFORM, mode.key)
            assert params[capabilities.MODE_KEY] == mode.key
            declared = {field.key for field in capabilities.fields_for(PLATFORM, mode.key)}
            assert declared <= set(params), f'{mode.key} is missing its own fields: {declared - set(params)}'
            assert set(params) == set(defaults) | {capabilities.MODE_KEY}, 'params drifted from the matrix'
            missing = capabilities.required_missing(mode, params)
            assert [field.key for field in missing] == [f.key for f in mode.fields if f.required], (
                f'{mode.key} should be short of exactly its required fields, nothing else'
            )

    def test_a_filled_in_node_is_valid_for_every_mode(self):
        filled = {
            'keyword': '人工智能',
            'author': 'https://www.zhihu.com/people/some-one',
            'urls': 'https://www.zhihu.com/question/66165881/answer/2041877076',
        }
        for mode in capabilities.modes_for(PLATFORM):
            params = harness.params_for(PLATFORM, mode.key, **filled)
            assert capabilities.required_missing(mode, params) == [], f'{mode.key} still refuses its own node'

    def test_a_single_mode_canvas_is_the_shape_the_validator_wants(self):
        canvas = harness.canvas_for(
            PLATFORM, 'posts', settings=harness.run_settings(), keyword='人工智能', target_count=10
        )
        assert [node['type'] for node in canvas['nodes']] == ['source']
        assert canvas['connections'] == []
        assert canvas['settings']['mode'] == 'serial' and canvas['settings']['headless'] is False
        node = canvas['nodes'][0]
        assert node['params']['target_count'] == 10, 'an override must reach the crawler, not be averaged away'
        assert capabilities.crawl_kwargs(capabilities.mode_for(PLATFORM, 'posts'), node['params']) == {
            'keyword': '人工智能',
            'target_count': 10,
            'full_body': True,
        }

    def test_the_feed_canvas_wires_the_column_the_matrix_names(self):
        canvas = harness.posts_then_comments_canvas(
            PLATFORM,
            posts={'keyword': '旅游', 'target_count': 3, 'full_body': False},
            comments={'comment_limit': 3},
        )
        comments = canvas['nodes'][1]
        mode = capabilities.mode_for(PLATFORM, 'comments')
        assert [(field.key, column) for field, column in capabilities.feed_of(mode)] == [('urls', 'input_column')]
        assert comments['params']['urls'] == '', 'a fed node keeps its textarea empty; the column replaces it'
        assert comments['params']['input_column'] == harness.LINK_COLUMN
        assert capabilities.required_missing(mode, comments['params'], fed_keys=capabilities.fed_keys(mode, True)) == []
        # Without the parent table the same node IS incomplete: fed-ness comes from the wire.
        assert [f.key for f in capabilities.required_missing(mode, comments['params'])] == ['urls']

    def test_a_component_canvas_labels_its_components_without_wiring_them_together(self):
        canvas = harness.component_canvas(
            [
                {'platform': PLATFORM, 'mode': 'hot', 'label': 'A', 'source': 'node-3'},
                {
                    'platform': PLATFORM,
                    'mode': 'posts',
                    'label': 'B',
                    'source': 'node-5',
                    'params': {'keyword': '高考'},
                },
            ],
            settings=harness.run_settings(mode='parallel'),
        )
        assert canvas['settings']['mode'] == 'parallel'
        assert canvas['connections'] == [{'from': 'node-2', 'to': 'node-3'}, {'from': 'node-4', 'to': 'node-5'}]
        sources = [node for node in canvas['nodes'] if node['type'] == 'source']
        assert [node['params'][capabilities.MODE_KEY] for node in sources] == ['hot', 'posts']


class TestResumeCanvas:
    """The 断点续跑 node is the canvas's only way to hand a run another run's stored rows, so
    the three param names are a contract with ``canvas.js`` and ``app._execute_resume_node``,
    and the two blanks are meanings a live case has to be able to ask for on purpose."""

    def test_the_node_carries_the_three_names_the_panel_writes(self):
        node = harness.resume_node('node-1', run_id='abc123', source_node_id='node-2', limit=10)
        assert node['type'] == 'resume'
        assert node['params'] == {'resume_run_id': 'abc123', 'resume_node_id': 'node-2', 'resume_limit': 10}

    def test_a_blank_pick_is_a_question_not_a_guess(self):
        """Empty run id means "the newest resumable run of THIS canvas's fingerprint" and an
        empty node id means "the fullest node of that run". A helper that filled in ``node-1``
        would make every adoption address one node by accident — and a bare node id repeated
        on another canvas is exactly the stranger's table this filter exists to refuse."""
        assert harness.resume_node('node-1')['params'] == {
            'resume_run_id': '',
            'resume_node_id': '',
            'resume_limit': 0,
        }

    def test_the_canvas_labels_its_own_record_and_wires_the_name_node_inward(self):
        canvas = harness.resume_canvas(run_id='abc123', label='存量入图')
        assert [node['type'] for node in canvas['nodes']] == ['name', 'resume']
        # A name node with nothing downstream is refused by validate(), so the wire's
        # direction is the difference between a labelled record and a canvas that never ran.
        assert canvas['connections'] == [{'from': canvas['nodes'][0]['id'], 'to': 'node-1'}]
        assert canvas['settings'] == harness.run_settings()

    def test_an_unlabelled_resume_canvas_is_one_node_and_no_wires(self):
        canvas = harness.resume_canvas(node_id='node-7', source_node_id='node-2')
        assert canvas['nodes'][0]['id'] == 'node-7'
        assert canvas['connections'] == []
        assert canvas['nodes'][0]['params']['resume_node_id'] == 'node-2'

    def test_the_resume_canvas_validates_as_a_workflow(self):
        """The engine's own refusal is the last thing a live case may discover after paying
        for the donor crawl: a canvas that validates as nothing is a canvas that never ran."""
        from engine.workflow import WorkflowEngine

        for canvas in (
            harness.resume_canvas(run_id='abc123', label='存量入图'),
            harness.resume_canvas(run_id='abc123', source_node_id='node-2'),
            harness.resume_canvas(),
        ):
            assert WorkflowEngine(canvas).validate() == [], WorkflowEngine(canvas).validate()


class TestSessionDiesAfter:
    """The cookie-death path is designed, and waiting for the user's real session to expire is
    not a test. These cases pin that the injected fact is exactly the one the page would have
    set — and that nothing else about the crawl was touched."""

    class _Crawler:
        """The crawl shape the seam works on: a row budget, a stored position, live rows."""

        def __init__(self):
            self.login_wall = False
            self.asked = []

        def search(self, keyword='', target_count=20, limit=20, full_body=True, resume=None, **_kwargs):
            self.asked.append({'target_count': target_count, 'limit': limit, 'resume': resume})
            budget = min(target_count, limit)
            return [{'链接': f'https://www.zhihu.com/q/{index}'} for index in range(budget)]

    def _armed(self, monkeypatch, crawler, **kwargs):
        state = harness.session_dies_after(monkeypatch, type(crawler), 'search', **kwargs)
        return state, crawler

    def test_the_first_crawl_keeps_real_rows_and_latches_only_the_wall(self, monkeypatch):
        crawler = self._Crawler()
        state, crawler = self._armed(monkeypatch, crawler, rows=3)
        first = crawler.search(keyword='人工智能', target_count=20)
        assert len(first) == 3, 'the walk is asked for the wall budget, and every row it kept is real'
        assert crawler.login_wall is True, 'the injected fact is precisely the flag the executor reads'
        assert state == {'latched': True, 'rows': 3, 'calls': 1}

    def test_the_resumed_attempt_crawls_for_real(self, monkeypatch):
        """A latch that survived into 继续 would make the case measure its own fixture."""
        crawler = self._Crawler()
        state, crawler = self._armed(monkeypatch, crawler, rows=3)
        crawler.search(keyword='人工智能', target_count=20)
        crawler.login_wall = False
        again = crawler.search(keyword='人工智能', target_count=20, resume={'scanned': 3})
        assert len(again) == 20, 'the resume is the half of the cell that has to actually crawl'
        assert crawler.login_wall is False, 'the latch is one-shot'
        assert state == {'latched': True, 'rows': 3, 'calls': 2}

    def test_a_crawl_that_kept_nothing_never_claims_a_death(self, monkeypatch):
        """An empty answer is the site refusing, not a session dying. Latching on it would let
        a 0-row crawl pass as the designed death path, which is the false green this whole tier
        exists to refuse — so the seam stays armed, and the executor's own collision retry (the
        second call of the same attempt) still gets its wall."""

        class _EmptyThenRows(TestSessionDiesAfter._Crawler):
            def __init__(self, pages):
                super().__init__()
                self._pages = list(pages)

            def search(self, keyword='', target_count=20, **kwargs):
                self.asked.append({'target_count': target_count, 'resume': kwargs.get('resume')})
                return self._pages.pop(0) if self._pages else []

        crawler = _EmptyThenRows([[], [{'链接': 'https://www.zhihu.com/q/1'}, {'链接': 'https://www.zhihu.com/q/2'}]])
        state, crawler = self._armed(monkeypatch, crawler, rows=3)
        assert crawler.search(keyword='人工智能', target_count=20) == []
        assert crawler.login_wall is False, 'an empty crawl may not report a dead session'
        assert state == {'latched': False, 'rows': 0, 'calls': 1}
        assert len(crawler.search(keyword='人工智能', target_count=20)) == 2
        assert crawler.login_wall is True and state == {'latched': True, 'rows': 2, 'calls': 2}

    def test_the_seam_narrows_the_budget_the_case_names(self, monkeypatch):
        """``comment_limit`` is per article and ``target_count`` is a walk's total: a hard-coded
        name would ignore the case that needed the seam for the other mode, and leave the user's
        own number untouched where the wall was supposed to land."""
        crawler = self._Crawler()
        state, crawler = self._armed(monkeypatch, crawler, rows=2, budget_kw='limit')
        crawler.search(keyword='人工智能', target_count=20, limit=40)
        assert crawler.asked[0]['target_count'] == 20, 'the number this seam was not told about stays the user'
        assert crawler.asked[0]['limit'] == 2
        assert state['rows'] == 2


class TestRunSettings:
    def test_an_unstated_profile_choice_is_absent_not_false(self):
        """AGENTS: absence means "follow the setting", never coerce missing to False. A
        helper that wrote ``False`` here would make every live run a throwaway browser
        because one case forgot an argument."""
        assert 'use_profile' not in harness.run_settings()
        assert harness.run_settings(use_profile=True)['use_profile'] is True
        assert harness.run_settings(use_profile=False)['use_profile'] is False

    def test_the_headless_switch_is_a_bool_not_a_string_of_one(self):
        assert harness.run_settings(headless=0)['headless'] is False
        assert harness.run_settings(mode='serial', headless=True)['mode'] == 'serial'


class TestLaneSwitches:
    """``lane_switches`` is the only way a cell can say which lane it measured.

    Both switches are read through ``settings_store`` by ``crawl_gate``, never from the canvas, so a case
    that wants real overlap has to change the machine's settings — and put them back, because the tier's
    settings file is session-wide: a leaked ``same_platform_queue=False`` would have a later platform
    crawling two-at-a-time and blaming the site when it answers with a wall.
    """

    def test_the_two_switches_are_set_for_the_block_and_restored_after(self, monkeypatch):
        import settings_store

        writes = []
        monkeypatch.setattr(settings_store, 'get_setting', lambda key: 'saved-value')
        monkeypatch.setattr(
            settings_store,
            'save_settings',
            lambda payload: writes.append(dict(payload)) or (payload, []),
        )
        with harness.lane_switches(queue=False, stagger=0):
            pass
        assert [sorted(one) for one in writes] == [
            sorted(['same_platform_queue', 'same_platform_stagger']),
            sorted(['same_platform_queue', 'same_platform_stagger']),
        ], f'the block set or restored something other than the two lane switches: {writes}'
        assert writes[0]['same_platform_queue'] is False and writes[0]['same_platform_stagger'] == 0
        assert all(one['same_platform_queue'] == 'saved-value' for one in writes[1:]), (
            f"the restore did not put the user's own values back: {writes}"
        )

    def test_a_case_that_dies_inside_the_block_still_restores_it(self, monkeypatch):
        """Containment is the point: a failed assertion must not leave the lane switched off."""
        import settings_store

        writes = []
        monkeypatch.setattr(settings_store, 'get_setting', lambda key: 'saved-value')
        monkeypatch.setattr(
            settings_store,
            'save_settings',
            lambda payload: writes.append(dict(payload)) or (payload, []),
        )
        with pytest.raises(RuntimeError), harness.lane_switches(queue=False, stagger=0):
            raise RuntimeError('the crawl refused mid-cell')
        assert writes[-1]['same_platform_queue'] == 'saved-value', writes

    def test_a_rejected_write_is_refused_loudly_instead_of_running_the_wrong_test(self, monkeypatch):
        """``save_settings`` returns warnings when a key is off its allowed shape.

        Swallowing them would let a cell measure the default lane while its docstring claimed the other.
        """
        import settings_store

        monkeypatch.setattr(settings_store, 'get_setting', lambda key: True)
        monkeypatch.setattr(settings_store, 'save_settings', lambda payload: (payload, ['bad value']))
        with pytest.raises(AssertionError, match='bad value'), harness.lane_switches(queue=False, stagger=0):
            pass


# ─── records and the wire ───────────────────────────────────────────────


class TestRecordReaders:
    _RECORD = {
        'run_id': 'r1',
        'nodes': [
            {'node_id': 'node-1', 'status': 'done', 'row_count': 12, 'cursor': {'scanned': 20}},
            {'node_id': 'node-2', 'status': 'partial', 'row_count': None, 'cursor': None},
        ],
    }

    def test_row_count_is_read_as_a_number_even_when_the_store_left_it_null(self):
        assert harness.stored_rows(self._RECORD, 'node-1') == 12
        assert harness.stored_rows(self._RECORD, 'node-2') == 0

    def test_a_missing_node_is_named_instead_of_returning_zero(self):
        """``row_count = 0`` for a node the record never had would read as "the crawl
        collected nothing", which is a different claim and a wrong one."""
        with pytest.raises(AssertionError) as refused:
            harness.node_of(self._RECORD, 'node-9')
        assert 'node-9' in str(refused.value)

    def test_a_cursor_absent_from_the_record_is_an_empty_position(self):
        assert harness.cursor_of(self._RECORD, 'node-1') == {'scanned': 20}
        assert harness.cursor_of(self._RECORD, 'node-2') == {}


class TestStart:
    def test_the_body_carries_only_what_the_case_stated(self):
        client = _FakeClient()
        body = harness.start(client, {'nodes': [], 'connections': [], 'settings': {}}, lang='zh')
        assert body == {'ok': True, 'run_id': 'run-1'}
        path, posted = client.posted[0]
        assert path == '/api/workflow/execute'
        assert posted['lang'] == 'zh' and posted['workflow']['nodes'] == []
        assert 'workflow_name' not in posted, 'a name node-less canvas has no name to send'
        assert 'resume_run_id' not in posted and 'queue' not in posted, 'an unstated resume must not be sent as one'

    def test_a_resume_is_sent_the_way_the_banner_sends_it(self):
        client = _FakeClient()
        harness.start(client, {'nodes': []}, workflow_name='知乎', resume_run_id='abc', queue=False, lang='en')
        _path, posted = client.posted[0]
        assert posted['resume_run_id'] == 'abc' and posted['queue'] is False
        assert posted['workflow_name'] == '知乎' and posted['lang'] == 'en'

    def test_a_refusal_fails_the_case_rather_than_returning_it(self):
        refused = _FakeClient(execute={'ok': False, 'error': 'busy'})
        with pytest.raises(AssertionError) as raised:
            harness.start(refused, {'nodes': []})
        assert 'busy' in str(raised.value)

    def test_a_queued_run_is_refused_loudly(self):
        """A queued request has no ``run_id`` and no console of its own: a live case that
        accepted it would poll somebody else's run to its timeout."""
        queued = _FakeClient(execute={'ok': True, 'queued': True, 'position': 2})
        with pytest.raises(AssertionError) as raised:
            harness.start(queued, {'nodes': []})
        assert 'queue' in str(raised.value).lower()

    def test_a_non_200_is_reported_with_its_body(self):
        with pytest.raises(AssertionError) as raised:
            harness.start(_FakeClient(execute={'ok': False, 'error': 'shape'}), {'nodes': []})
        assert 'shape' in str(raised.value)


# ─── audit ──────────────────────────────────────────────────────────────


class TestAuditDump:
    def test_the_transcript_and_the_index_row_land_together(self, tmp_path):
        recorder = harness.ConsoleRecorder(None, mirror=False)
        recorder.lines = ['第一条', '第二条']
        recorder.overflow = True
        recorder.mirror_lines = ['urllib3 chatter']
        path = harness.audit_dump(
            'A1',
            {
                'recorder': recorder,
                'platform': PLATFORM,
                'mode': 'posts',
                'headless': False,
                'use_profile': '',
                'lang': 'zh',
                'target': 10,
                'rows': 10,
                'verdict': harness.FULL,
                'reasons': [],
                'wall_flags': [],
                'cookie_expired': False,
                'abort': {},
                'seconds': 41.5,
            },
            root=tmp_path,
            pass_id='p1',
        )
        text = path.read_text(encoding='utf-8')
        assert path.name == 'A1.console.txt'
        assert '# pass p1' in text
        assert '# console lines 2' in text and '# overflow YES' in text
        assert '# containment not attempted' in text, 'a run that settled itself is a different fact from a leak'
        assert '第一条' in text and 'urllib3 chatter' in text, 'the unfiltered mirror belongs in the audit'
        index = (tmp_path / 'verdicts.csv').read_text(encoding='utf-8')
        header, row = index.strip().splitlines()
        assert header.split(',') == list(harness.VERDICT_COLUMNS)
        assert row.startswith('p1,A1,zhihu,posts,False,,zh,10,10,FULL,,,False,,41.5'), row

    def test_a_worker_that_survived_containment_is_named_in_both_artifacts(self, tmp_path):
        """The row is where a leak is reported, and the next row is where it otherwise shows up.

        A case that died with a crawl still inside its browser costs the rest of the tier: the
        platform lane and the profile directory stay taken, and the surviving worker's lines fold
        into the next case's transcript. ``abort_run`` already answers "did it go quiet" — this is
        the promise that the answer reaches ``scratchpad/live_audit/`` instead of being discarded
        with the exception.
        """
        note = {'abort_quiet': False, 'abort_error': 'the aborted worker is still alive: running=True'}
        harness.audit_dump('E1', {'lines': ['x'], 'verdict': 'ABORTED', 'abort': note}, root=tmp_path)
        row = (tmp_path / 'verdicts.csv').read_text(encoding='utf-8').strip().splitlines()[1]
        assert 'not contained: the aborted worker is still alive: running=True' in row, row
        transcript = (tmp_path / harness.PASS_ID / 'E1.console.txt').read_text(encoding='utf-8')
        assert '# containment not contained: the aborted worker is still alive' in transcript

    def test_a_contained_worker_is_reported_as_contained_not_blank(self, tmp_path):
        """An empty cell would read as "the case never looked", which is a third state."""
        harness.audit_dump('E2', {'lines': ['x'], 'verdict': 'ABORTED', 'abort': {'abort_quiet': True}}, root=tmp_path)
        row = (tmp_path / 'verdicts.csv').read_text(encoding='utf-8').strip().splitlines()[1]
        assert ',contained,' in f',{row},', row

    def test_a_second_pass_keeps_the_first_ones_transcript(self, tmp_path):
        """The closure gate IS a re-run, and the evidence a previous red was root-caused from
        cannot be the thing the second pass overwrites. The index says which row is current."""
        payload = {'lines': ['第一次的 console'], 'verdict': harness.SILENT_SHORT, 'reasons': ['kept 0 of 10']}
        first = harness.audit_dump('A1', payload, root=tmp_path, pass_id='p1')
        second = harness.audit_dump(
            'A1', {'lines': ['第二次的 console'], 'verdict': harness.FULL}, root=tmp_path, pass_id='p2'
        )
        assert first != second and first.exists() and second.exists()
        assert '第一次的 console' in first.read_text(encoding='utf-8')
        assert '第二次的 console' in second.read_text(encoding='utf-8')
        rows = (tmp_path / 'verdicts.csv').read_text(encoding='utf-8').strip().splitlines()[1:]
        assert [row.split(',')[0] for row in rows] == ['p1', 'p2'], rows

    def test_a_second_case_appends_without_repeating_the_header(self, tmp_path):
        payload = {'lines': ['x'], 'verdict': harness.SILENT_SHORT, 'reasons': ['no exit', 'kept 0 of 10']}
        harness.audit_dump('A2', payload, root=tmp_path)
        harness.audit_dump('A3', payload, root=tmp_path)
        lines = (tmp_path / 'verdicts.csv').read_text(encoding='utf-8').strip().splitlines()
        assert len(lines) == 3, lines
        assert sum(1 for line in lines if line.startswith(harness.VERDICT_COLUMNS[0])) == 1
        assert 'no exit; kept 0 of 10' in lines[1], 'a list of reasons must survive as one readable cell'

    def test_the_fast_tier_never_touches_the_real_audit_root(self, tmp_path):
        """The whole point of the ``root`` parameter: the closure run's index is built by
        live cases, and a fast-tier test writing rows into it would fabricate evidence."""
        real = Path(harness.AUDIT_ROOT)
        assert REPO_ROOT / 'scratchpad' in real.parents, 'the audit root must sit in the gitignored scratchpad'
        harness.audit_dump('probe-case', {'lines': []}, root=tmp_path)
        assert not (real / 'probe-case.console.txt').exists(), 'the real index gained a case that never crawled'
        assert not (tmp_path.parent / 'probe-case.console.txt').exists()
        assert not (real / harness.PASS_ID / 'probe-case.console.txt').exists()
