"""The network probe: what this machine can say about itself when a page did not arrive.

This module exists so that "switch network" is a measurement rather than a guess: two
control hosts on opposite sides of the wall the user may be sitting behind, plus one
short throughput sample. That also makes it the one service in the backend that must
never be trusted to a real socket in the fast tier — an offline developer machine would
otherwise read as a broken test, and a test that reaches the internet on the failure
path is a test that takes ten seconds to say nothing.

Every case below therefore replaces one of the module's own two primitives
(:func:`net_probe.reachable` / :func:`net_probe.throughput`) or the socket underneath
them, and what is asserted is the *classification*, which is the part a message quotes.
"""

import contextlib
import socket

import pytest

from services import net_probe

pytestmark = pytest.mark.unit

DNS_ERROR = socket.gaierror('getaddrinfo failed')
REFUSED = ConnectionRefusedError('rejected')
NO_ROUTE = OSError(101, 'Network is unreachable')


class _UnreachableError(Exception):
    """The shape a black-holed address takes: a timeout wrapped in a urllib-style error.

    An ``Exception`` subclass because that is what it stands for here, and because
    ``raise`` refuses a plain object — a fake that is not raisable turns the branch under
    test into ``'error'`` and the test passes for the wrong reason.
    """

    def __init__(self, reason):
        super().__init__(str(reason))
        self.reason = reason


class FakeResponse:
    def __init__(self, chunks, status=200):
        self._chunks = list(chunks)
        self.status_code = status
        self.closed = False

    def iter_content(self, chunk_size=1):
        yield from self._chunks

    def close(self):
        self.closed = True


def _clock(values):
    """A monotonic() that advances by *statement*, not by waiting.

    Needed because this machine's ``time.monotonic`` has a ~16 ms tick (measured: a
    5 ms sleep leaves the reading unchanged), and ``throughput`` divides by what the
    clock says. A test that slept long enough to be visible would be slow *and* still
    timing-dependent; a test that names its own elapsed figure measures the arithmetic
    instead.
    """
    steps = iter(values)
    hold = [values[0]]

    def read():
        with contextlib.suppress(StopIteration):
            hold[0] = next(steps)
        return hold[0]

    return read


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


def _chunks(total_bytes, size=None):
    size = size or net_probe.SPEED_CHUNK
    out = []
    remaining = total_bytes
    while remaining > 0:
        piece = min(size, remaining)
        out.append(b'x' * piece)
        remaining -= piece
    return out


class TestReachingAHost:
    def test_a_connect_that_succeeds_is_the_only_ok_answer(self, monkeypatch):
        opened = []

        class _Socket:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def connect(addr, timeout):
            opened.append(addr)
            return _Socket()

        monkeypatch.setattr(net_probe.socket, 'create_connection', connect)
        assert net_probe.reachable('www.baidu.com') == 'ok'
        assert opened == [('www.baidu.com', net_probe.CONTROL_PORT)]
        assert net_probe.CONTROL_TIMEOUT <= 3.0, 'a control host may not cost the run a long wait'

    @pytest.mark.parametrize(
        ('error', 'word'),
        [
            (DNS_ERROR, 'unresolved'),
            (REFUSED, 'refused'),
            (TimeoutError('timed out'), 'timed_out'),
            (_UnreachableError(TimeoutError()), 'timed_out'),
            (NO_ROUTE, 'no_route'),
            (OSError('something else entirely'), 'error'),
        ],
    )
    def test_each_failure_keeps_its_own_name_because_each_has_its_own_remedy(self, monkeypatch, error, word):
        def raise_it(_addr, timeout=None):
            raise error

        monkeypatch.setattr(net_probe.socket, 'create_connection', raise_it)
        assert net_probe.reachable('example.com') == word

    def test_a_tls_failure_is_named_apart_from_a_refused_port(self):
        """Both mean the host answered, which is a different sentence to read than 'no route'."""
        import ssl

        assert net_probe._classify(ssl.SSLError('handshake failure')) == 'tls_blocked'

    def test_the_unreachable_errno_list_covers_both_platform_spellings(self):
        for errno in (51, 101, 10051, 10065):
            assert net_probe._classify(OSError(errno, 'no route')) == 'no_route', errno


class TestTheSpeedSample:
    def test_the_session_is_built_rather_than_assumed(self, monkeypatch):
        """The bug this pins: ``throughput`` reached for a module global that only a
        helper creates, so the first real call was a ``NameError`` on the failure path —
        the one path where a probe is allowed to be asked at all."""
        session = FakeSession(FakeResponse(_chunks(net_probe.SPEED_MIN_BYTES * 4)))
        monkeypatch.setattr(net_probe, '_session', lambda: session)
        monkeypatch.setattr(net_probe.time, 'monotonic', _clock([0.0, 0.5, 1.0]))
        read = net_probe.SPEED_MIN_BYTES * 4
        assert net_probe.throughput() == int(read / 1.0 / 1024)
        assert len(session.calls) == 1, 'the sample was not taken through the session'

    def test_a_response_that_is_not_a_200_is_not_a_measurement(self, monkeypatch):
        monkeypatch.setattr(net_probe, '_session', lambda: FakeSession(FakeResponse([], status=404)))
        assert net_probe.throughput() is None

    def test_a_handful_of_bytes_is_reported_as_no_number_at_all(self, monkeypatch):
        """Below the floor the figure is handshake, and a message quoting it would be a
        measurement of the probe rather than of the user's line."""
        monkeypatch.setattr(net_probe, '_session', lambda: FakeSession(FakeResponse([b'x' * 64])))
        monkeypatch.setattr(net_probe.time, 'monotonic', _clock([0.0, 0.5, 1.0]))
        assert net_probe.throughput() is None

    def test_a_line_that_refuses_to_be_measured_is_none_and_not_an_error(self, monkeypatch):
        monkeypatch.setattr(net_probe, '_session', lambda: FakeSession(error=TimeoutError('stalled')))
        assert net_probe.throughput() is None

    def test_the_connection_is_released_even_when_the_window_ends_mid_body(self, monkeypatch):
        """The window is what keeps the probe cheap, and an abandoned streaming response
        is a leaked socket on exactly the path that runs repeatedly."""
        response = FakeResponse(_chunks(net_probe.SPEED_MIN_BYTES * 8))
        monkeypatch.setattr(net_probe, '_session', lambda: FakeSession(response))
        monkeypatch.setattr(net_probe.time, 'monotonic', _clock([0.0, 1.0, 2.0, 3.0]))
        assert net_probe.throughput(window=1.0) is not None
        assert response.closed is True

    def test_the_shared_session_is_built_once_and_closed_at_exit(self, monkeypatch):
        import atexit

        made = []
        monkeypatch.setattr(net_probe, '_SPEED_SESSION', None)
        monkeypatch.setattr(atexit, 'register', lambda *args, **kwargs: made.append(args[0]))
        first = net_probe._session()
        assert net_probe._session() is first, 'every diagnosis paid for a fresh TLS handshake'
        assert made, 'the pool outlived the run with no way back'


class TestNamingTheHost:
    @pytest.mark.parametrize(
        ('given', 'host'),
        [
            ('www.bilibili.com', 'www.bilibili.com'),
            ('https://www.douyin.com/hot', 'www.douyin.com'),
            ('http://127.0.0.1:8123/x', '127.0.0.1'),
            ('https://example.com:8443/', 'example.com'),
            ('', ''),
            ('not a url at all', 'not a url at all'),
        ],
    )
    def test_a_matrix_domain_and_a_full_address_ask_the_same_question(self, given, host):
        """The port belongs to the page; this asks only whether the host is routable, so
        an address carrying :8123 must not become a probe of a port nobody serves."""
        assert net_probe._host_of(given) == host


class TestTheClassification:
    """``diagnose`` is the only place the four control readings become one word."""

    def _wire(self, monkeypatch, states, speed=None, platform=''):
        def fake_reachable(host, port=net_probe.CONTROL_PORT, timeout=net_probe.CONTROL_TIMEOUT):
            if host == platform and platform:
                return states.get('platform', 'ok')
            return states.get(host, 'ok')

        monkeypatch.setattr(net_probe, 'reachable', fake_reachable)
        monkeypatch.setattr(net_probe, 'throughput', lambda window=net_probe.SPEED_WINDOW: speed)

    def test_both_sides_dead_is_the_machine_not_the_network_choice(self, monkeypatch):
        self._wire(monkeypatch, {net_probe.CONTROLS['cn']: 'unresolved', net_probe.CONTROLS['overseas']: 'unresolved'})
        assert net_probe.diagnose('cn')['verdict'] == 'offline'

    def test_the_other_side_alive_is_a_region_problem(self, monkeypatch):
        self._wire(
            monkeypatch,
            {net_probe.CONTROLS['cn']: 'unresolved', net_probe.CONTROLS['overseas']: 'ok'},
        )
        answer = net_probe.diagnose('cn')
        assert answer['verdict'] == 'region'
        assert answer['side'] == 'cn'

    def test_both_sides_alive_but_the_platform_dead_is_a_block(self, monkeypatch):
        self._wire(monkeypatch, {}, platform='www.bilibili.com')

        def reach(host, **kwargs):
            return 'refused' if host == 'www.bilibili.com' else 'ok'

        monkeypatch.setattr(net_probe, 'reachable', reach)
        assert net_probe.diagnose('cn', 'www.bilibili.com')['verdict'] == 'blocked'

    def test_everything_routing_is_called_slow_and_says_so(self, monkeypatch):
        """The honest answer, which is that nothing was found: the message that follows
        this word may not name a cause."""
        self._wire(monkeypatch, {}, speed=2048)
        answer = net_probe.diagnose('cn', 'www.bilibili.com')
        assert answer['verdict'] == 'slow'
        assert answer['speed_kbps'] == 2048

    def test_the_platform_host_is_only_asked_when_it_can_be_named(self, monkeypatch):
        """A missing fact must not become the strongest claim in the vocabulary."""
        asked = []

        def spy(host, **kwargs):
            asked.append(host)
            return 'ok'

        monkeypatch.setattr(net_probe, 'reachable', spy)
        monkeypatch.setattr(net_probe, 'throughput', lambda **kw: 100)
        assert net_probe.diagnose('cn', '')['verdict'] == 'slow'
        assert asked == [net_probe.CONTROLS['cn'], net_probe.CONTROLS['overseas']]

    def test_an_unparseable_platform_leads_to_no_block_claim(self, monkeypatch):
        self._wire(monkeypatch, {}, platform='')
        assert net_probe.diagnose('cn', '::::')['verdict'] == 'slow'

    def test_a_speed_is_only_offered_when_the_line_could_be_read(self, monkeypatch):
        self._wire(monkeypatch, {net_probe.CONTROLS['cn']: 'timed_out', net_probe.CONTROLS['overseas']: 'timed_out'})
        answer = net_probe.diagnose('cn')
        assert answer['verdict'] == 'offline'
        assert answer['speed_kbps'] is None, 'the dead line was charged a measurement'

    def test_an_unknown_region_is_answered_as_the_domestic_side(self, monkeypatch):
        """The matrix's own default is ``cn``; a probe asked about a region it does not
        know must not pick the overseas controls and report a block that is not there."""
        self._wire(monkeypatch, {net_probe.CONTROLS['overseas']: 'unresolved'})
        assert net_probe.diagnose('mars')['side'] == 'cn'

    def test_the_detail_quotes_every_host_it_asked(self, monkeypatch):
        """The sentence is advice; the detail is the evidence, and a user who disagrees
        with the advice has to be able to see what was measured."""
        self._wire(monkeypatch, {}, platform='www.douyin.com')
        monkeypatch.setattr(net_probe, 'reachable', lambda host, **kw: 'refused' if host == 'www.douyin.com' else 'ok')
        detail = net_probe.diagnose('cn', 'https://www.douyin.com/hot')['detail']
        assert 'www.baidu.com=ok' in detail and 'www.google.com=ok' in detail and 'www.douyin.com=refused' in detail

    def test_the_control_hosts_are_the_two_sides_and_not_the_platform_itself(self):
        """A platform's own outage would otherwise be reported as the network's fault,
        which is the one confusion this module was written to avoid."""
        assert set(net_probe.CONTROLS) == {'cn', 'overseas'}
        assert net_probe.CONTROLS['cn'] != net_probe.CONTROLS['overseas']
        assert not any('douyin' in host or 'weibo' in host for host in net_probe.CONTROLS.values())
