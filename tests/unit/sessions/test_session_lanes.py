"""One directory is one lane: the lock that keeps two browsers out of one Chrome profile.

The wait's clock is injectable, so the deadline rule is proved without spending the wait — the
reason the bookkeeping was separated from ``sessions.profiles``' path policy.
"""

import os

import pytest
from sessions import lanes

pytestmark = pytest.mark.unit


class TestTheLaneIdentity:
    def test_the_same_directory_has_one_lane_however_it_is_spelled(self, tmp_path):
        path = str(tmp_path / 'zhihu')
        assert lanes.dir_key(path) == lanes.dir_key(os.path.join(path, '.'))
        assert lanes.lock_for(path) is lanes.lock_for(os.path.join(path, '.'))

    def test_two_directories_are_two_devices(self, tmp_path):
        first = str(tmp_path / 'zhihu')
        second = str(tmp_path / 'zhihu' / 'work')
        assert lanes.lock_for(first) is not lanes.lock_for(second)

    def test_a_moved_directory_gives_its_lane_up(self, tmp_path):
        """A rename replaces the device, so the old path must not answer for the new one."""
        path = str(tmp_path / 'renamed')
        before = lanes.lock_for(path)
        lanes.forget_lock(path)
        assert lanes.lock_for(path) is not before


class TestTakingALane:
    def test_a_free_directory_is_acquired_and_given_back(self, tmp_path):
        path = str(tmp_path / 'free')
        lock = lanes.acquire(path, 1.0)
        assert lock is not None
        assert lanes.is_busy(path) is True
        lanes.release_profile(lock)
        assert lanes.is_busy(path) is False

    def test_a_held_directory_answers_none_instead_of_proceeding(self, tmp_path):
        path = str(tmp_path / 'held')
        held = lanes.acquire(path, 1.0)
        try:
            assert lanes.acquire(path, 0.01) is None
        finally:
            lanes.release_profile(held)
        assert lanes.acquire(path, 0.5) is not None

    def test_a_stop_ends_the_wait_before_it_takes_the_lane(self, tmp_path):
        """A run the user stopped must not sit out the timeout behind a browser it closed."""
        path = str(tmp_path / 'aborted')
        assert lanes.acquire(path, 5.0, abort=lambda: True) is None
        assert lanes.is_busy(path) is False

    def test_a_deadline_that_has_already_passed_does_not_wait(self, tmp_path):
        ticks = iter([0.0, 10.0])
        path = str(tmp_path / 'late')
        got = lanes.acquire(path, 5.0, abort=lambda: False, clock=lambda: next(ticks, 10.0))
        assert got is None

    def test_releasing_nothing_is_not_an_error(self):
        assert lanes.release_profile(None) is None
