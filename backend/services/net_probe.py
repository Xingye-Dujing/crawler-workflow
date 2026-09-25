"""Why nothing arrived: tell a network that cannot reach the site from a site that is slow.

The crawler can prove three different things and must not confuse them (the user's rule,
2026-09-25): the link is wrong or the **region** is blocked (a Chinese line cannot reach
overseas sites; a VPN'd line gets a 502 from douyin), the session is not logged in, or the
site is risk-controlling an otherwise-good session. Everything else — a page that simply
has not arrived — is *not* evidence of "no data", and must not be reported as such.

This module answers that leftover case by asking the one question the crawl itself cannot:
**is this machine able to reach that side of the internet at all right now?** It compares
the platform's declared region (`crawl_capabilities.Capability.region`) with two control
hosts, one per side, and measures a throughput figure so the message can say something the
user can act on ("switch network and re-test") instead of a bare timeout.

Deliberately cheap, bounded and read-only: a TCP connect per control host (never a request
to the crawled platform, which would be a second fingerprint of this session to the site
that just refused us), one short read of a CDN asset the app already depends on for its
chart library, all of it wrapped so a probe can never become the reason a run fails. Total
cost is a few seconds, and it runs on the failure path only.
"""

import atexit
import contextlib
import socket
import ssl
import time
from urllib.parse import urlsplit

#: One host per side of the wall, chosen for what each proves rather than for popularity:
#: ``www.google.com`` answers only on a line that can actually leave China, and
#: ``www.baidu.com`` answers only on a line that has not lost the domestic route. A
#: platform's own domain is a bad control — its own outage would be reported as the
#: network's fault.
CONTROLS = {'cn': 'www.baidu.com', 'overseas': 'www.google.com'}

#: The app's own chart CDN (``index.html`` loads ECharts from here), so this probe adds
#: no new third party to the machine's outbound traffic.
SPEED_URL = 'https://cdn.jsdmirror.com/npm/echarts@5.4.3/dist/echarts.min.js'

CONTROL_PORT = 443
CONTROL_TIMEOUT = 3.0
#: Read at most this long. A slow line finishes the whole file; a stalled one does not,
#: and in both cases the byte count over the window is the number worth reporting.
SPEED_WINDOW = 2.0
#: Bytes read before the sample counts as a measurement at all — below this the figure is
#: dominated by handshake, and a zero-byte read is a refusal, not a slow speed.
SPEED_MIN_BYTES = 4096
SPEED_CHUNK = 65536


def _classify(error: Exception) -> str:
    """One word for one failure, because the user's remedy differs per word."""
    if isinstance(error, socket.timeout) or isinstance(getattr(error, 'reason', None), TimeoutError):
        return 'timed_out'
    if isinstance(error, socket.gaierror):
        # DNS is the shape a Chinese line gives when asked for an overseas name: the
        # resolver has no answer at all, which is not the same claim as "it is slow".
        return 'unresolved'
    if isinstance(error, ConnectionRefusedError):
        return 'refused'
    if isinstance(error, ssl.SSLError):
        return 'tls_blocked'
    if isinstance(error, OSError) and getattr(error, 'errno', None) in (10051, 10065, 51, 101):
        # "Network is unreachable" / "no route to host": no interface is even trying.
        return 'no_route'
    return 'error'


def reachable(host: str, port: int = CONTROL_PORT, timeout: float = CONTROL_TIMEOUT) -> str:
    """``'ok`` or a name for why it was not: ``unresolved`` / ``refused`` / ``timed_out`` / …

    A bare TCP connect, no TLS and no request: enough to separate "routable" from "not",
    and nothing a monitoring endpoint could mistake for a client.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return 'ok'
    except Exception as exc:  # a probe must never become the failure it is diagnosing
        return _classify(exc)


def _close_quietly(handle) -> None:
    """Close a probe socket, swallowing whatever it says while doing so.

    One place, because the response is opened before the read window ends on purpose: the
    generator is abandoned mid-body, and an abandoned connection is a leaked socket on the
    error path — which is exactly when this code runs.
    """
    with contextlib.suppress(Exception):
        handle.close()


#: Held open by ``throughput`` and closed only when the process exits — see there.
_OPEN: list = []


def throughput(window: float = SPEED_WINDOW) -> int | None:
    """kB/s, or ``None`` when the line refused to be measured.

    The read is a **window**, not a download: a stalled line would otherwise block the
    diagnosis this feeds on. Bytes are counted over wall-clock seconds, which is the only
    way to report a line that trickles rather than one that fails — the two need different
    advice from the user's point of view.
    """
    response = None
    try:
        started = time.monotonic()
        response = _session().get(SPEED_URL, stream=True, timeout=window)
        if response.status_code != 200:
            return None
        read = 0
        for chunk in response.iter_content(chunk_size=SPEED_CHUNK):
            read += len(chunk)
            if time.monotonic() - started >= window:
                break
        elapsed = time.monotonic() - started
        if read < SPEED_MIN_BYTES or elapsed <= 0:
            return None
        return int(read / elapsed / 1024)
    except Exception:
        return None
    finally:
        # A streaming response holds its connection, and abandoning it mid-body would leak
        # one per diagnosis (the failure path is exactly where that adds up). Closing it
        # while the request is still unfinished is the thing that keeps the window cheap:
        # the socket is released at once and the bytes already counted stand on their own.
        if response is not None:
            _close_quietly(response)


def _host_of(value: str) -> str:
    """The hostname inside *value*, which may be a bare host or a whole address.

    Callers hand this the platform's matrix domain (``www.bilibili.com``) or the URL a
    node just failed on, and the two must not probe different things: an address carries
    a port that belongs to the *page*, while this question is whether the machine can
    route to the host at all, which is always asked on 443.
    """
    text = str(value or '').strip()
    if not text:
        return ''
    if '://' not in text:
        return text.split('/')[0]
    try:
        return urlsplit(text).hostname or ''
    except ValueError:
        return ''


def _platform_reachable(host: str) -> str:
    """Ask the platform's own host, same probe as the controls.

    The controls say what the *line* can do; this says whether the site the node asked for
    is even there. Both together are what separates "you are on the wrong network" from
    "the site is down or slow" — one of them alone gets confounded constantly.

    An unparseable host answers ``''``, which :func:`diagnose` treats as "not asked": a
    missing fact must never become the evidence for the strongest claim in the vocabulary.
    """
    return reachable(host) if host else ''


_SESSION_HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; caixihui-probe/1.0)'}


def _session():
    """One shared ``requests`` session for the speed probe.

    Kept alive across diagnoses so the measured bytes are not charged with a fresh TLS
    handshake every time, and closed at interpreter exit through ``atexit`` so the
    long-lived pool cannot outlive us holding a connection (the failure paths here are
    exactly the ones where the window ends mid-body).
    """
    global _SPEED_SESSION
    if _SPEED_SESSION is None:
        import requests

        _SPEED_SESSION = requests.Session()
        _SPEED_SESSION.headers.update(_SESSION_HEADERS)
        atexit.register(_close_quietly, _SPEED_SESSION)
    return _SPEED_SESSION


_SPEED_SESSION = None


def diagnose(region: str, platform_host: str = '') -> dict:
    """Classify a no-content outcome. Returns ``{'verdict', 'side', 'detail', 'speed_kbps'}``.

    ``verdict`` is ``'offline'`` (neither side reachable — fix the machine, not the
    network choice), ``'region'`` (the side this canvas needs is unreachable while the
    other answers — switch network and re-test), ``'blocked'`` (both sides route and the
    platform's own host does not answer, which is the shape a block takes), or ``'slow'``
    (everything connects, so the only honest remaining statement is that the page has not
    arrived yet). ``'unknown'`` when the controls themselves could not be asked.

    ``'blocked'`` is the only verdict that needs the platform's own host, and it is
    withheld when that host could not be read out of what the caller passed: a missing
    fact must never be reported as the strongest claim in this vocabulary.
    """
    needed = region if region in CONTROLS else 'cn'
    other = 'overseas' if needed == 'cn' else 'cn'
    needed_state = reachable(CONTROLS[needed])
    other_state = reachable(CONTROLS[other])
    speed = throughput() if needed_state == 'ok' else None
    detail = f'{CONTROLS[needed]}={needed_state}, {CONTROLS[other]}={other_state}'
    if needed_state == 'ok' and other_state == 'ok':
        host = _host_of(platform_host)
        if host:
            platform_state = _platform_reachable(host)
            detail += f', {host}={platform_state}'
            if platform_state and platform_state != 'ok':
                return {'verdict': 'blocked', 'side': needed, 'detail': detail, 'speed_kbps': speed}
        return {'verdict': 'slow', 'side': needed, 'detail': detail, 'speed_kbps': speed}
    if needed_state == 'ok':
        # Our own side routes, so this is not a region problem and not a dead line.
        return {'verdict': 'slow', 'side': needed, 'detail': detail, 'speed_kbps': speed}
    if other_state == 'ok':
        return {'verdict': 'region', 'side': needed, 'detail': detail, 'speed_kbps': speed}
    return {'verdict': 'offline', 'side': needed, 'detail': detail, 'speed_kbps': speed}
