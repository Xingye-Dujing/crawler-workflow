"""Ending a browser session, whatever state it is in.

``close_login_browser`` is what a Stop, a node's ``finally`` and the login window all call.
Two older behaviours were wrong: ``quit()`` was trusted to finish (a window the user closed by
hand leaves it hanging, keeping the chromedriver process alive forever), and the stop route
answered such cases with a GLOBAL ``taskkill /IM chromedriver.exe`` that also murdered unrelated
Selenium sessions on the machine. ``quit()`` now gets a bounded grace on a side thread; if it
does not return, exactly this session's process tree — chrome children included — is killed by
the running OS's own reaper (``core.procs``).
"""

import contextlib
import logging
import os
import sys
import threading

from core import procs
from core.config import Config
from state import add_log

from crawlers.core.faults import DeadDriver
from i18n import t

logger = logging.getLogger(__name__)


def stuck_where(thread) -> str:
    """Where a side thread is standing right now — its own top frame, file and line.

    ``sys._current_frames`` is the only thing that can answer this about a thread that is
    not cooperating: the situation is a ``close()`` that never returns, so nothing it logs
    itself will ever be heard. The address of a hang is the difference between "a browser
    is wedged somewhere" and a line a developer can go and read.
    """
    frame = sys._current_frames().get(thread.ident)
    if frame is None:
        return ''
    # The frame ``_current_frames`` returns is the *innermost* one — the call that is not
    # coming back. Alone that is usually a lock or a socket inside somebody else's library,
    # which names the wait but not the crawler waiting, so three callers come along: the
    # first word is what to grep, the rest say whose browser this is.
    frames = []
    while frame is not None and len(frames) < 4:
        code = frame.f_code
        frames.append(f'{code.co_name} at {os.path.basename(code.co_filename)}:{frame.f_lineno}')
        frame = frame.f_back
    return ' ← '.join(frames)


def close_login_browser(crawler, quit_timeout: float = 5.0):
    """Close the login browser of THIS session, whatever state it is in.

    Two older behaviours were wrong: quit() was trusted to finish (a window the
    user closed by hand leaves it hanging, keeping the chromedriver process
    alive forever), and /api/workflow/stop answered such cases with a GLOBAL
    `taskkill /IM chromedriver.exe` that also murdered unrelated Selenium
    sessions on the machine. quit() now gets a bounded grace on a side thread;
    if it does not return, exactly this session's driver process tree — the
    chrome children included — is killed.
    """
    if crawler is None:
        return
    if isinstance(getattr(crawler, 'driver', None), DeadDriver):
        # One browser asked about twice — the stop thread and the worker's own finally both reach
        # this for a parallel run. There is nothing left to close, and the check has to happen
        # before the line below: reading ``driver.service.process.pid`` off a dead session raises
        # ``CrawlerStopped``, which is a ``BaseException`` and so walks straight out of the
        # ``suppress(Exception)`` guarding it, killing the thread on its way to the *next* browser.
        # Its profile is deliberately not released from here either: a lock handed back for a
        # session the worker is still scrolling in lets the next crawl of that platform open a
        # second Chrome on the same directory.
        return
    pid = None
    with contextlib.suppress(Exception):
        pid = crawler.driver.service.process.pid
    waiter = threading.Thread(target=crawler.close, daemon=True)
    waiter.start()
    waiter.join(quit_timeout)
    if waiter.is_alive() and pid:
        # The reap is asked of THIS operating system, and its outcome is printed either way. The command
        # used to be ``taskkill`` under a ``suppress`` that also swallowed the line assigning
        # ``DeadDriver``: on a Linux server nothing was killed, the worker was not freed, and the console
        # said the browser had been stopped.
        stopped, reason = procs.reap_process(pid)
        if not stopped:
            logger.warning(t('run.browserReapFailed', pid=pid, err=reason))
        # Replacing the session is what makes 停止 mean now, and it is the only reliable way to
        # do it: the reap frees the command the worker is *inside* (a dead driver resets the
        # socket, measured 1.7 s) but the worker's NEXT command opens a fresh connection to a
        # port nobody holds, and selenium's pool re-sends a failed connect four times —
        # measured 16.3 s each, which is how a mid-walk stop took 29.6 s to settle. See
        # ``crawlers.core.faults.DeadDriver`` for why the refusal is a ``BaseException``. This happens
        # whether or not the process is gone: the promise is about the session the worker holds.
        crawler.driver = DeadDriver()
    elif waiter.is_alive():
        # No process number to aim a kill at, and no promise this thread ever returns.
        # The harm is specific and has to be said: ``crawler.close()`` is what releases the
        # platform's profile lock, so that directory stays claimed until wherever it is
        # stuck unsticks — the next crawl of this platform waits up to
        # ``Config.PROFILE_LOCK_TIMEOUT`` for it. Silence here reads as "closed", while the
        # user may be looking at the window.
        domain = getattr(crawler, 'domain', '')
        add_log(t('run.browserStuck', platform=domain, seconds=int(Config.PROFILE_LOCK_TIMEOUT)))
        # ``debug`` on purpose: the console line above is the user's, and this one is for
        # whoever reads ``logs/`` — where English is what a person grepping for a hang wants,
        # and a translated frame would put a stack address through the message catalogue.
        logger.debug(
            'the browser of %s could not be closed and has no readable process id; still running at %s',
            domain,
            stuck_where(waiter),
        )
