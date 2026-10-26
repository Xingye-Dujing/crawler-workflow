"""Stopping one process this machine owns, on the three systems the app runs on.

The only reason this is a module and not a line in ``app.py``: the previous answer was
``taskkill /F /T /PID``, which on Linux and macOS raises ``FileNotFoundError`` — and it raised it inside a
``contextlib.suppress(Exception)`` whose block also held the ``DeadDriver()`` assignment. So a cloud
server killed nothing, did not even mark the session dead, and the next crawl of that platform waited
the full ``Config.PROFILE_LOCK_TIMEOUT`` for a browser that was still running. Silence plus a promise
that was never kept.
"""

from __future__ import annotations

import os
import signal
import subprocess

from utils import machine_deps

#: How POSIX says 「kill it now」. Windows' signal module has no ``SIGKILL`` at all (measured: an
# ``AttributeError`` from the very line that was supposed to clean up a browser), which is exactly why
# the Windows branch shells out to ``taskkill`` instead — and why the name is resolved once here rather
# than written inline, so a test that asks for the Linux answer on a Windows box gets the Linux code path.
_SIGKILL = getattr(signal, 'SIGKILL', signal.SIGTERM)

#: How a Windows tree is taken down: ``/T`` includes the chrome children chromedriver spawned.
_WINDOWS_REAP = ('taskkill', '/F', '/T', '/PID')


def reap_command(pid: int, system: str | None = None) -> list[str]:
    """The command that stops ``pid`` and its children on this OS — POSIX returns none, see below."""
    if machine_deps.is_windows(system):
        return [*_WINDOWS_REAP, str(pid)]
    return []


def child_pids(proc_root: str, parent: int) -> list[int]:
    """Direct children of ``parent``, read from a ``/proc``-shaped tree.

    Linux keeps the parent's number in field 4 of ``/proc/<pid>/stat``, so a browser started by a driver
    can be taken down with it. macOS has no ``/proc``: the caller gets an empty list and kills the driver
    alone, which is still the truth reported rather than a claimed tree kill. The root is a parameter
    because a test on Windows cannot manufacture ``/proc`` — it manufactures a directory that looks
    like it, which exercises the same parsing.
    """
    children: list[int] = []
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return children
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc_root, entry, 'stat'), encoding='utf-8', errors='replace') as handle:
                fields = handle.read().split(') ', 1)[-1].split()
            if len(fields) >= 2 and int(fields[1]) == parent:
                children.append(int(entry))
        except (OSError, ValueError):
            continue
    return children


def reap_process(pid: int, system: str | None = None, proc_root: str = '/proc') -> tuple[bool, str]:
    """Kill ``pid`` (and, where it can be known, its children); return ``(stopped, machine's_own_reason)``.

    The second value is the operating system's sentence, never a translated one — the caller puts it
    inside an i18n message. And it is never silent: the caller writes the outcome to the run console,
    because 「已终止」 over a browser that is still holding a profile is exactly the lie that costs the
    next run fifteen minutes of ``PROFILE_LOCK_TIMEOUT``.
    """
    if pid <= 0:
        return False, f'not a process id: {pid}'
    system = machine_deps.platform_name(system)
    if system == 'win32':
        try:
            result = subprocess.run(
                reap_command(pid, system),
                capture_output=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or b'').decode('utf-8', 'replace').strip()
            # A process that already exited is not a failure to stop: the caller only wants the tree gone.
            if tail and 'not found' in tail.lower():
                return True, ''
            return False, tail or f'taskkill exit code {result.returncode}'
        return True, ''
    children = child_pids(proc_root, pid)
    targets = [*children, pid]
    failed = []
    for target in targets:
        try:
            os.kill(target, _SIGKILL)
        except ProcessLookupError:
            continue  # already gone is already stopped
        except OSError as exc:
            failed.append(f'{target}: {exc.strerror or exc}')
    if failed:
        return False, '; '.join(failed)
    return True, ''
