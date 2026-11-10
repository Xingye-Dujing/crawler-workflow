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

from core import machine

#: How POSIX says "kill it now". Windows' signal module has no ``SIGKILL`` at all (measured: an
# ``AttributeError`` from the very line that was supposed to clean up a browser), which is exactly why
# the Windows branch shells out to ``taskkill`` instead — and why the name is resolved once here rather
# than written inline, so a test that asks for the Linux answer on a Windows box gets the Linux code path.
_SIGKILL = getattr(signal, 'SIGKILL', signal.SIGTERM)

#: How a Windows tree is taken down: ``/T`` includes the chrome children chromedriver spawned.
_WINDOWS_REAP = ('taskkill', '/F', '/T', '/PID')


def _decode(raw: bytes) -> str:
    """A tool's own error text, in the encoding that console actually uses.

    Windows writes these in the process's ANSI code page (cp936 on a Chinese install), so
    decoding as UTF-8 — which is what the old line did — turned the message into a run of
    ``\ufffd``. The fallback keeps it readable instead of inventing replacement characters.
    """
    for codec in ('utf-8', _console_codec()):
        try:
            return raw.decode(codec).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', 'replace').strip()


def _console_codec() -> str:
    """The code page this machine's console tools write in (UTF-8 off Windows)."""
    if not machine.is_windows():
        return 'utf-8'
    try:
        import locale

        return locale.getpreferredencoding(False) or 'cp1252'
    except Exception:
        return 'cp1252'


def reap_command(pid: int, system: str | None = None) -> list[str]:
    """The command that stops ``pid`` and its children on this OS — POSIX returns none, see below."""
    if machine.is_windows(system):
        return [*_WINDOWS_REAP, str(pid)]
    return []


def popen_kwargs(system: str | None = None, detached: bool = False) -> dict:
    """The keyword arguments that keep a spawned helper from opening a console window here.

    The app boots short-lived helper processes (the Node that runs the CatBus backend, once per
    comment link) from a server that may itself have no console. Without ``CREATE_NO_WINDOW`` the
    user watches a black window appear for every one of them. That constant exists only in Windows'
    ``subprocess`` module, so the POSIX answer is an empty dict rather than a keyword Python rejects
    — and the name is read through ``getattr`` so this module imports on a Linux box too.

    ``detached`` adds the flags that let an updater outlive the process that started it. POSIX
    callers pair this with ``start_new_session=True`` rather than a Windows creation flag.
    """
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    if detached and machine.is_windows(system):
        flags |= getattr(subprocess, 'DETACHED_PROCESS', 0x00000008)
        flags |= getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200)
    return {'creationflags': flags} if machine.is_windows(system) and flags else {}


def powershell_command(script: str, args: list[str] | None = None) -> list[str]:
    """The Windows interpreter and the arguments that run one updater script.

    One per-OS fact, beside ``popen_kwargs``: the self-updater must not spell the executable
    elsewhere in ``backend/`` (the cross-platform rule and its AST gate). Callers only reach this
    branch after asking ``machine.is_windows()``.
    """
    return ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script), *(args or [])]


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
    because “已终止” over a browser that is still holding a profile is exactly the lie that costs the
    next run fifteen minutes of ``PROFILE_LOCK_TIMEOUT``.
    """
    if pid <= 0:
        return False, f'not a process id: {pid}'
    system = machine.platform_name(system)
    if system == 'win32':
        try:
            result = subprocess.run(
                reap_command(pid, system),
                capture_output=True,
                timeout=8,
                check=False,
                **popen_kwargs(system),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)
        if result.returncode != 0:
            # ``taskkill`` exits 128 when the process it was asked to kill is not running — on
            # EVERY Windows language. Matching the English words ``not found`` in the output
            # meant a Chinese Windows reported “没有找到进程” as a FAILED reap: the console
            # printed “浏览器没能关掉” for a browser that had already closed, and the user
            # went looking for a zombie that did not exist.
            if result.returncode == 128:
                return True, ''
            tail = _decode(result.stderr or result.stdout or b'')
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
