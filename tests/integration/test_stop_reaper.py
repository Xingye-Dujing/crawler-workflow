"""Real Chrome: what a crawl pays for its NEXT command after 停止 had to reap the browser (#134).

The offline suite can prove the crawler was handed a session that refuses; only a browser can prove
the thing being avoided is real. Measured here and in ``backend/test_dead_driver.py`` (payload
``scratchpad/dead_driver.json``, Chrome 148 / selenium 4.45 / urllib3 2.7):

====================================== ==========  =========================================
what one command does                    seconds   why
====================================== ==========  =========================================
the command in flight when the kill lands    1.72 s  a dead driver resets the socket, and a
                                                    request already written is never re-sent
the next command, on the old session        16.3 s  a fresh connect to a port nobody holds, and
                                                    selenium's pool carries ``Retry(total=3)``
the next command, on the reaped session      0.00 s  refused by name, before any socket is opened
====================================== ==========  =========================================

Four attempts at ~4.07 s is the 16.3 s, and a walk sends several commands per row — that is where the
measured 29.6 s of a mid-walk 停止 came from. Both directions are asserted below, because a control
that stopped reproducing the ladder would silently make the first assertion worth nothing.

Local pages only: this tier reaches no site and writes nothing to the server's data directory.
"""

import threading
import time

import pytest

from crawlers import get_crawler
from crawlers.base import CrawlerStopped, DeadDriver

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

#: How long the worker's command wants to run. Nothing here waits for it: the kill is what ends it.
HANG_MS = 60000
#: The grace a browser gets to close itself, and therefore what the reap costs. Kept small so the
#: measured interval is the socket, not this number.
QUIT_GRACE = 0.3
#: A refusal must be immediate. Generous next to the 0.00 s measured, tight next to the 16.3 s avoided.
REFUSE_BUDGET = 1.0
#: The control only: if a dead session answers this fast, the machine is not reproducing the ladder
#: and the comparison above has lost its meaning.
CONTROL_FLOOR = 5.0


def _launch():
    """A crawler browser, or a skip: this tier is not applicable without Chrome."""
    try:
        return get_crawler('bilibili', headless=True, use_profile=False)
    except Exception as e:
        pytest.skip(f'Chrome/chromedriver unavailable: {e}')


def _hang_one_command(driver, box):
    """Put a real command in flight — the position a page load or an in-page fetch leaves a crawl in."""
    thread = threading.Thread(
        target=lambda: _run_command(driver, box),
        daemon=True,
    )
    thread.start()
    time.sleep(1.0)
    assert thread.is_alive(), f'the worker already came back: {box}'
    return thread


def _run_command(driver, box):
    started = time.monotonic()
    try:
        driver.execute_async_script(f'window.setTimeout(function(){{arguments[0](1);}}, {HANG_MS});')
        box['outcome'] = 'answered'
    except BaseException as e:
        box['outcome'] = type(e).__name__
    box['seconds'] = round(time.monotonic() - started, 3)


def _one_command(driver):
    """Time a single command however it ends: the exception it answers with and its cost are the
    measurement, and the cost is only meaningful next to the other one."""
    started = time.monotonic()
    answer = None
    try:
        driver.execute_script('return 1;')
    except BaseException as e:
        answer = e
    return answer, round(time.monotonic() - started, 3)


def test_a_reaped_browser_leaves_a_session_that_refuses_faster_than_a_dead_port_can_be_tried(app_module):
    # ``app_module`` is not a convenience here: it is the fixture that has already redirected every
    # write path into a tmp dir. Importing ``app`` at module level instead would beat that fixture
    # (pytest imports every collected module before any fixture runs, marker filters do not help),
    # and the module-level import is what makes the backend cache the REAL ``data/cookies`` — so a
    # test of the stop path would then write fake cookies into the user's own cookie directory.
    crawler = _launch()
    driver = crawler.driver
    try:
        driver.get('about:blank')
        driver.set_script_timeout(HANG_MS // 1000 + 5)
        box = {}
        worker = _hang_one_command(driver, box)

        reaped_at = time.monotonic()
        app_module._close_login_browser(crawler, quit_timeout=QUIT_GRACE)
        reap_cost = round(time.monotonic() - reaped_at, 3)
        worker.join(HANG_MS / 1000 + 30)
        assert not worker.is_alive(), f'the kill did not free the command in flight: {box}'
        assert box['seconds'] < 10.0, f'the in-flight command took {box["seconds"]} s to come back: {box}'

        assert isinstance(crawler.driver, DeadDriver), (
            f'停止 reaped the browser but left the crawler holding it (reap took {reap_cost} s), so '
            'every later command of this crawl is a retry ladder against a dead port'
        )
        refused, refused_in = _one_command(crawler.driver)
        assert isinstance(refused, CrawlerStopped), (
            f'the reaped session answered {refused!r} instead of refusing the way a stop is refused'
        )
        assert refused_in < REFUSE_BUDGET, f'the refusal cost {refused_in} s, budget {REFUSE_BUDGET} s'

        # The control, on the object that owned the session: measured 16.3 s, and worth nothing if it
        # is not reproduced here, because then "instant" would only be this machine being fast.
        answered, took = _one_command(driver)
        assert took > CONTROL_FLOOR, (
            f'the dead session answered in {took} s ({answered!r}), so the 16.3 s ladder is not '
            'reproducing on this machine and the refusal above proves nothing about it'
        )
        assert not isinstance(answered, CrawlerStopped), (
            'the old session refused like the new one, so the two objects measured the same thing'
        )
    finally:
        crawler.close()
