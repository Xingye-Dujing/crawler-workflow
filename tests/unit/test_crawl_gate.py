"""The same-platform gate: who waits, who only waits *to start*, and what each says.

``crawl_gate`` decides whether two workflows crawling weibo collide at the site or
take turns, and the two modes it offers are genuinely different promises, so they are
tested apart:

* **真排队** (``same_platform_queue`` on) — the platform is *held* until the crawl
  finishes, so nothing of that platform runs at the same moment;
* **错峰** (off) — only the two *starts* are spaced, by the user's own
  ``same_platform_stagger``, and the crawls may still run over each other.

Whether a *rest* is owed after a crawl turned out to be an assumption worth measuring: on
2026-09-24 the live tier failed two weibo crawls that had taken turns without overlapping,
which looked exactly like "queued, but the account needed a breather" — and 14 later
crawls of that platform, including a second browser started seconds after the first
closed, were all served. The refusals were intermittent risk control, not ordering, so
this gate still adds no rest of its own.

Both failure directions are visible to the user, which is why the assertions are about
spans and about recorded sleeps rather than about a boolean somebody set: a gate that
never blocks lets the collision through (two red nodes, one account), a gate that
blocks when nothing contended charges a serial canvas seconds it never needed, and a
mode that silently *over*-serialises would take away the 并行 the user asked for.
"""

import threading

import crawl_gate
import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Fresh locks, a fake clock, and a wait that costs no wall-clock.

    The clock moves *because* the recorded wait says so: 错峰 arithmetic is arithmetic
    about time passing, and a stub that made every wait instant would have three crawls
    scheduled 10 s apart report gaps of 10, 20, 30 — which a test asserting on the
    numbers would then be proving about its own stub.

    ``_interruptible_sleep`` is swapped rather than ``time.sleep``: the gate holds a
    reference to the same function the test would poll on, so patching the stdlib would
    also blind every wait in here.
    """
    crawl_gate.reset()
    waits = []
    clock = {'now': 1000.0}
    monkeypatch.setattr(crawl_gate, '_now', lambda: clock['now'])

    def _sleep(seconds, abort):
        waits.append(seconds)
        clock['now'] += seconds

    monkeypatch.setattr(crawl_gate, '_interruptible_sleep', _sleep)
    monkeypatch.setattr(crawl_gate.Config, 'PLATFORM_GATE_TIMEOUT', 0.3)
    return {'waits': waits, 'clock': clock}


def _settings(monkeypatch, *, queue, stagger=10.0):
    """Pin both knobs at once: the mode is a setting and so is the wait it pays."""
    values = {'same_platform_queue': queue, 'same_platform_stagger': stagger}
    monkeypatch.setattr(crawl_gate, 'get_setting', lambda key: values[key])


def _holder(platform, inside, release):
    """A crawl that occupies *platform* until the test lets it out."""

    def body():
        with crawl_gate.hold(platform):
            if inside is not None:
                inside.set()
            if release is not None:
                release.wait(10)

    thread = threading.Thread(target=body)
    thread.start()
    return thread


def _enter(platform):
    """Take the turn and report the answer the caller gets — so a thread can hand it back."""
    with crawl_gate.hold(platform) as waited:
        return waited


class TestStrictQueue:
    def test_an_empty_platform_costs_nothing(self, monkeypatch, isolated):
        _settings(monkeypatch, queue=True)
        with crawl_gate.hold('weibo') as waited:
            assert waited is False
        assert isolated['waits'] == [], 'a serial canvas must not pay for a policy that protects a parallel one'

    def test_the_second_crawl_cannot_start_until_the_first_finishes(self, monkeypatch, isolated):
        """The definition of 真排队, measured as a thread still alive while the first
        holds the turn — not as a flag."""
        _settings(monkeypatch, queue=True)
        inside, release = threading.Event(), threading.Event()
        holder = _holder('weibo', inside, release)
        assert inside.wait(5)

        answers, finished = [], threading.Event()

        def waiter():
            with crawl_gate.hold('weibo') as waited:
                answers.append(waited)
            finished.set()

        second = threading.Thread(target=waiter)
        second.start()
        second.join(0.2)
        assert second.is_alive(), 'the second crawl got in while the first still held the platform'
        release.set()
        holder.join(5)
        assert finished.wait(5), 'the queued crawl never came out of its wait'
        second.join(5)
        assert answers == [True], 'it waited but was not told it had queued'

    def test_the_gap_after_a_waited_hand_off_is_the_user_s_number(self, monkeypatch, isolated):
        """The account just ended a session seconds ago, so a turn changing hands is
        followed by the spacing wait as well — and the length is the setting, which the
        user can raise to 60 or drop to 0 without touching code.

        The second crawl enters the gate from a thread *while the first is still inside*,
        so "did it queue?" is settled by the lock rather than by which thread the OS woke
        first after the release.
        """
        _settings(monkeypatch, queue=True, stagger=42.0)
        inside, release = threading.Event(), threading.Event()
        holder = _holder('weibo', inside, release)
        assert inside.wait(5)
        answers = []
        second = threading.Thread(target=lambda: answers.append(_enter('weibo')))
        second.start()
        second.join(0.2)
        assert second.is_alive(), 'the hand-off never actually handed off'
        release.set()
        holder.join(5)
        assert second.join(5) is None, 'the queued crawl never came out of its wait'
        assert answers == [True], 'it waited but was not told it had queued'
        assert isolated['waits'] and isolated['waits'][0] >= 42.0, isolated['waits']

    def test_zero_gap_still_queues_and_sleeps_for_nothing(self, monkeypatch, isolated):
        """0 means "do not pad the hand-off", not "stop queueing" — the two are separate
        promises and a user must be able to make one without breaking the other."""
        _settings(monkeypatch, queue=True, stagger=0.0)
        inside, release = threading.Event(), threading.Event()
        holder = _holder('weibo', inside, release)
        assert inside.wait(5)
        release.set()
        with crawl_gate.hold('weibo') as waited:
            assert waited is True
        holder.join(5)
        assert isolated['waits'] == [], f'0 seconds still slept: {isolated["waits"]}'

    def test_a_different_platform_is_not_made_to_wait(self, monkeypatch, isolated):
        _settings(monkeypatch, queue=True)
        inside, release = threading.Event(), threading.Event()
        holder = _holder('weibo', inside, release)
        assert inside.wait(5)
        with crawl_gate.hold('zhihu') as waited:
            assert waited is False, 'a gate on weibo charged zhihu for it'
        assert isolated['waits'] == []
        release.set()
        holder.join(5)

    def test_a_wait_that_never_ends_is_refused_by_name(self, monkeypatch, isolated):
        """The ceiling exists so a browser that never closed cannot park a platform for
        the rest of the process — and the answer names it, since the alternative is a
        stack trace from inside a lock."""
        _settings(monkeypatch, queue=True)
        inside, release = threading.Event(), threading.Event()
        holder = _holder('weibo', inside, release)
        assert inside.wait(5)
        try:
            with pytest.raises(RuntimeError) as caught, crawl_gate.hold('weibo'):
                pass
            assert 'weibo' not in str(caught.value) and ('微博' in str(caught.value) or 'Weibo' in str(caught.value))
        finally:
            release.set()
            holder.join(5)

    def test_stop_cancels_the_wait_instead_of_burying_it(self, monkeypatch, isolated):
        _settings(monkeypatch, queue=True)
        inside, release = threading.Event(), threading.Event()
        holder = _holder('weibo', inside, release)
        assert inside.wait(5)
        stopped = threading.Event()
        stopped.set()
        try:
            with pytest.raises(RuntimeError) as caught, crawl_gate.hold('weibo', abort=lambda: stopped.is_set()):
                pass
            text = str(caught.value)
            assert '取消' in text or 'cancel' in text.lower(), f'not the cancellation line: {text}'
        finally:
            release.set()
            holder.join(5)


class TestStaggerOnly:
    """The mode 真排队 off selects: space the starts, keep the parallelism."""

    def test_a_running_crawl_does_not_hold_the_next_one_back(self, monkeypatch, isolated):
        """The line this mode must not cross: if the second crawl could not get in
        while the first was inside, the switch would be a queue wearing another name."""
        _settings(monkeypatch, queue=False, stagger=10.0)
        inside, release = threading.Event(), threading.Event()
        holder = _holder('weibo', inside, release)
        assert inside.wait(5)
        try:
            with crawl_gate.hold('weibo') as waited:
                assert waited is True, 'it started on top of another crawl and was not told it had waited'
                assert inside.is_set(), 'the first crawl had already left — that overlap was not measured'
        finally:
            release.set()
            holder.join(5)

    def test_the_wait_is_exactly_the_rest_of_the_gap(self, monkeypatch, isolated):
        """A caller that arrives at once should be told to wait for the *remaining*
        spacing, not for a fresh whole interval on top of the one already elapsed."""
        _settings(monkeypatch, queue=False, stagger=10.0)
        with crawl_gate.hold('weibo'):
            pass
        with crawl_gate.hold('weibo'):
            pass
        assert len(isolated['waits']) == 1, isolated['waits']
        assert 9.0 < isolated['waits'][0] <= 10.0, isolated['waits']

    def test_three_crawls_leave_three_spaced_starts(self, monkeypatch, isolated):
        """The schedule is recorded at each crawl's *planned* start, so a queue of three
        does not all measure its gap from the first one's departure."""
        _settings(monkeypatch, queue=False, stagger=10.0)
        for _round in range(3):
            with crawl_gate.hold('weibo'):
                pass
        assert len(isolated['waits']) == 2, f'three crawls should pay two gaps: {isolated["gaps"]}'
        assert all(9.0 < gap <= 10.0 for gap in isolated['waits']), isolated['waits']

    def test_a_quiet_platform_never_pays_the_gap(self, monkeypatch, isolated):
        """Spacing is measured from the last start, so the first crawl after a long
        pause is not made to wait for a company that left ages ago."""
        _settings(monkeypatch, queue=False, stagger=10.0)
        crawl_gate._LAST_START['weibo'] = 0.0
        with crawl_gate.hold('weibo') as waited:
            assert waited is False
        assert isolated['waits'] == []

    def test_zero_gap_means_no_ordering_at_all(self, monkeypatch, isolated):
        _settings(monkeypatch, queue=False, stagger=0.0)
        inside, release = threading.Event(), threading.Event()
        holder = _holder('weibo', inside, release)
        assert inside.wait(5)
        with crawl_gate.hold('weibo') as waited:
            assert waited is False
            assert isolated['waits'] == []
        release.set()
        holder.join(5)

    def test_a_different_platform_is_not_spaced_either(self, monkeypatch, isolated):
        """Spacing is per platform, so the one wait in here must be weibo waiting for
        weibo — a gate that keyed on the directory or on nothing at all would charge
        zhihu for somebody else's schedule."""
        _settings(monkeypatch, queue=False, stagger=10.0)
        for _round in range(2):
            with crawl_gate.hold('weibo'):
                pass
        with crawl_gate.hold('zhihu') as waited:
            assert waited is False
        assert len(isolated['waits']) == 1, f'zhihu paid for weibo: {isolated["waits"]}'

    def test_stop_cancels_a_spacing_wait_too(self, monkeypatch, isolated):
        """The wait in this mode can be minutes long, and 停止 has to reach it — the
        same promise the queue makes, for a different reason."""
        _settings(monkeypatch, queue=False, stagger=60.0)
        real_sleep = crawl_gate._interruptible_sleep
        slept = []

        def sleeping(seconds, abort):
            slept.append(seconds)
            real_sleep(seconds, abort)

        monkeypatch.setattr(crawl_gate, '_interruptible_sleep', sleeping)
        monkeypatch.setattr(crawl_gate.Config, 'PLATFORM_GATE_TIMEOUT', 5.0)
        with crawl_gate.hold('weibo'):
            pass
        stopped = threading.Event()
        stopped.set()
        with crawl_gate.hold('weibo', abort=lambda: stopped.is_set()) as waited:
            assert waited is True
        assert slept, 'the gap was skipped instead of waited-and-cancelled'


class TestModeIsolation:
    def test_the_two_modes_do_not_share_a_lock(self, monkeypatch, isolated):
        """A strict turn is held for a whole crawl and a spacing lock for a wait; one
        lock serving both would let a mid-run mode switch park a crawl behind a run the
        new mode says it may overlap."""
        _settings(monkeypatch, queue=True)
        inside, release = threading.Event(), threading.Event()
        holder = _holder('weibo', inside, release)
        assert inside.wait(5)
        _settings(monkeypatch, queue=False, stagger=1.0)
        try:
            with crawl_gate.hold('weibo'):
                pass  # 错峰 says this may enter while the strict holder is still inside
        finally:
            release.set()
            holder.join(5)

    def test_an_unnamed_platform_is_passed_through(self, monkeypatch, isolated):
        _settings(monkeypatch, queue=True)
        with crawl_gate.hold('') as waited:
            assert waited is False
        assert isolated['waits'] == []
