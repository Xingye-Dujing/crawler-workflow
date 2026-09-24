"""The same-platform queue: who waits, who does not, and what each one says.

``crawl_gate`` is the piece that decides whether two workflows crawling weibo
collide at the site or take turns, and both failure directions are visible to the
user: a gate that never actually blocks lets the collision through (two red nodes,
one account), and a gate that blocks when there was no contention charges every
serial canvas seconds it never needed. So the assertions here are about *spans* and
about *sleeps*, not about a boolean someone set.
"""

import threading

import crawl_gate
import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Fresh locks per test, and a gap recorder that costs no wall-clock.

    ``_interruptible_sleep`` is swapped rather than ``time.sleep``: the gate holds a
    reference to the same module the test would poll on, so patching the stdlib
    function would also blind every wait in here.
    """
    crawl_gate.reset()
    gaps = []
    monkeypatch.setattr(crawl_gate, '_interruptible_sleep', lambda seconds, abort: gaps.append(seconds))
    monkeypatch.setattr(crawl_gate.Config, 'SAME_PLATFORM_STAGGER', 10.0)
    monkeypatch.setattr(crawl_gate.Config, 'PLATFORM_GATE_TIMEOUT', 0.3)
    return {'gaps': gaps}


def _on(monkeypatch):
    monkeypatch.setattr(crawl_gate, 'get_setting', lambda key: True)


def _off(monkeypatch):
    monkeypatch.setattr(crawl_gate, 'get_setting', lambda key: False)


class TestUncontended:
    def test_an_empty_platform_costs_nothing(self, monkeypatch, isolated):
        _on(monkeypatch)
        with crawl_gate.hold('weibo') as waited:
            assert waited is False
        assert isolated['gaps'] == [], 'a serial canvas must not pay for a policy that protects a parallel one'

    def test_the_setting_off_holds_no_lock_at_all(self, monkeypatch, isolated):
        _off(monkeypatch)
        inside = threading.Event()
        released = threading.Event()

        def first():
            with crawl_gate.hold('weibo'):
                inside.set()
                released.wait(5)

        thread = threading.Thread(target=first)
        thread.start()
        assert inside.wait(5)
        # Nothing is queueing this: the second caller walks in while the first is inside.
        with crawl_gate.hold('weibo') as waited:
            assert waited is False
        released.set()
        thread.join(5)


class TestContended:
    def _hold_forever(self, platform, inside, release):
        def body():
            with crawl_gate.hold(platform):
                if inside is not None:
                    inside.set()
                if release is not None:
                    release.wait(10)

        thread = threading.Thread(target=body)
        thread.start()
        return thread

    def test_the_second_crawl_waits_and_the_gap_is_paid_after_it_waited(self, monkeypatch, isolated):
        """Ordering *and* pacing. The queue is the point; the gap after a waited
        hand-off is the part the profile lock cannot give, because the site just saw
        a session of this account end seconds ago."""
        _on(monkeypatch)
        inside = threading.Event()
        release = threading.Event()
        holder = self._hold_forever('weibo', inside, release)
        assert inside.wait(5)

        answers = []
        finished = threading.Event()

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
        assert isolated['gaps'] and isolated['gaps'][0] >= 10.0, f'no gap after a waited hand-off: {isolated["gaps"]}'

    def test_a_different_platform_is_not_made_to_wait(self, monkeypatch, isolated):
        _on(monkeypatch)
        inside = threading.Event()
        release = threading.Event()
        holder = self._hold_forever('weibo', inside, release)
        assert inside.wait(5)
        with crawl_gate.hold('zhihu') as waited:
            assert waited is False, 'a gate on weibo charged zhihu for it'
        assert isolated['gaps'] == []
        release.set()
        holder.join(5)

    def test_a_wait_that_never_ends_is_refused_by_name(self, monkeypatch, isolated):
        """The ceiling exists so a browser that never closed cannot park a platform
        for the rest of the process — and the answer has to name the platform, since
        the alternative is a stack trace from inside a lock."""
        _on(monkeypatch)
        inside = threading.Event()
        release = threading.Event()
        holder = self._hold_forever('weibo', inside, release)
        assert inside.wait(5)
        try:
            with pytest.raises(RuntimeError) as caught, crawl_gate.hold('weibo'):
                pass
            assert 'weibo' in str(caught.value)
        finally:
            release.set()
            holder.join(5)

    def test_stop_cancels_the_wait_instead_of_burying_it(self, monkeypatch, isolated):
        """A wait that cannot be cancelled turns 停止 into a lie: the node keeps
        queueing, the run keeps its slot, and the console says nothing."""
        _on(monkeypatch)
        inside = threading.Event()
        release = threading.Event()
        holder = self._hold_forever('weibo', inside, release)
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
