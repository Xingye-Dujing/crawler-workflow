"""Compile a LaTeX source to PDF with the machine's ``xelatex``.

The ``visualize`` node emits a compilable ``standalone`` document (services/charts/tikz); this turns that
source into the PDF a paper actually includes — one document, one ``xelatex`` pass. It shells out the same
best-effort way the report PDF does: no ``xelatex``, or a run that will not produce a PDF, is a named
refusal surfaced as ``{'error': …}``, never a crash and never a half-written file left in the export tree.
``ctex`` needs ``xelatex`` (not ``pdflatex``), so that is the binary sought — MiKTeX's on Windows, TeX
Live's (or MacTeX's) elsewhere, which is why the search and the refusal both ask the running OS.
"""

import contextlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
from types import SimpleNamespace

from core import machine, procs
from runtime.settings import get_setting

from i18n import t
from services.charts.tikz import LatexChartService

#: How long one compile may take. Generous on purpose — a first run builds the font cache.
COMPILE_TIMEOUT = 120

logger = logging.getLogger(__name__)


def _discard(work: str) -> None:
    """Remove the throwaway compile directory, and SAY where it is when that fails.

    ``shutil.rmtree(..., ignore_errors=True)`` was silent: on Windows a file held open by a
    surviving child process leaves ``cixi-tex-*`` in %TEMP% forever, and nothing anywhere recorded
    that a directory had been abandoned. The claim that matters is "no half-written PDF", so a
    leaked temp directory is a fact the log has to carry.
    """
    try:
        shutil.rmtree(work)
    except OSError as exc:
        logger.warning(t('api.compileTempLeft', path=work, err=exc))


def _stop_process_tree(proc) -> None:
    """Kill the compile and the children it started (``xdvipdfmx``), not just the direct child."""
    if proc is None or proc.poll() is not None:
        return
    pid = getattr(proc, 'pid', None)
    if pid:
        stopped, reason = procs.reap_process(pid)
        if not stopped:
            logger.warning(t('api.compileKillFailed', pid=pid, err=reason))
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        proc.kill()


def compose_tex(docs) -> str:
    """One standalone document merging the bodies of the given standalone sources (figure and/or table)."""
    return LatexChartService.compose_from_standalone(list(docs))


#: Where a TeX distribution puts ``xelatex`` when it is installed but the PATH of a service process does
#: not know it. Windows: MiKTeX's own tree. Linux: the alternatives symlink. macOS: MacTeX's texbin,
#: which a GUI-launched process never inherits in ``PATH``.
XELATEX_PATHS = {
    'win32': (
        r'C:\Program Files\MiKTeX\miktex\bin\x64\xelatex.exe',
        r'C:\Program Files (x86)\MiKTeX\miktex\bin\x64\xelatex.exe',
    ),
    'linux': ('/usr/bin/xelatex', '/usr/local/bin/xelatex'),
    'darwin': ('/Library/TeX/texbin/xelatex', '/usr/texbin/xelatex', '/usr/local/bin/xelatex'),
}


def find_xelatex() -> str:
    """The ``xelatex`` binary: an explicit ``latex_binary`` the user set first, then PATH, then this OS's
    install locations. Empty → the compile is refused with a reason, never a stack trace. Public because
    the desktop launcher's startup self-check asks the same question, and two scans for the compiler is
    how a machine says "xelatex not found" next to a compile that works."""
    explicit = str(get_setting('latex_binary') or '').strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    found = shutil.which('xelatex') or shutil.which('miktex-xelatex')
    if found:
        return found
    local = os.environ.get('LOCALAPPDATA', '')
    candidates = [
        os.path.join(local, 'Programs', 'MiKTeX', 'miktex', 'bin', 'x64', 'xelatex.exe') if local else '',
        *XELATEX_PATHS.get(machine.platform_name(), ()),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ''


# ─── what a failed compile says back ────────────────────────────────────────
#: The two failures a reader can fix, lifted out of xelatex's own log instead of being guessed from
#: a non-zero exit. Everything else falls through to the log's first ``!`` line, which is the line a
#: TeX user reads when they open the file themselves.
_STY_MISSING = re.compile(r"File `([^']+)\.sty' not found")
_FONT_MISSING = re.compile(r'The font "([^"]+)" cannot be found', re.IGNORECASE)


def _read_log(work: str) -> str:
    """xelatex's log for this attempt; '' when there was none (a compile that never started)."""
    log_path = os.path.join(work, 'main.log')
    try:
        with open(log_path, encoding='utf-8', errors='replace') as handle:
            return handle.read()
    except OSError:
        return ''


def _error_line(log_text: str) -> str:
    """The first ``! …`` line, which is where LaTeX puts the reason it stopped."""
    for line in log_text.splitlines():
        if line.startswith('! '):
            return line.strip()
    return ''


def explain_failure(log_text: str, stderr: bytes) -> str:
    """One actionable sentence for a failed compile: the missing package, the missing font, or the log.

    A missing ``.sty`` and a missing Chinese font are the two ways this fails on a machine that has a TeX
    distribution installed, and both name themselves in the log — saying only "compilation failed" sends
    the user to search a log file they have no reason to open. Which command installs either one is an
    operating-system fact, so the remedy half of the sentence comes from :mod:`core.machine`.
    """
    package = _STY_MISSING.search(log_text)
    if package:
        return t(
            'api.compilePdfNoPackage',
            package=package.group(1),
            remedy=machine.remedy('deps.texPackage'),
        )
    font = _FONT_MISSING.search(log_text)
    if font:
        return t('api.compilePdfNoFont', font=font.group(1), remedy=machine.remedy('deps.texFont'))
    detail = _error_line(log_text) or (stderr or b'').decode('utf-8', 'replace')[-300:]
    return t('api.compilePdfFailed', err=detail)


def compile_pdf(tex: str, out_name: str, export_dir: str) -> tuple[dict, str]:
    """Compile ``tex`` and stage the PDF as ``out_name`` under ``export_dir``; return ``(result, name)``.

    ``result`` is ``{'pdf_file', 'pdf_bytes'}`` on success, or ``{'error': …}`` on any failure — no binary,
    a non-zero run, or a missing output. A throwaway working directory keeps xelatex's aux/log out of the
    export tree, and nothing half-written survives. The caller names the node's own final file, so the PDF
    it lands on is deterministic per run and simply overwritten on a re-run.
    """
    xelatex = find_xelatex()
    if not xelatex:
        return {'error': machine.remedy('deps.xelatex')}, ''
    work = tempfile.mkdtemp(prefix='cixi-tex-')
    tex_path = os.path.join(work, 'main.tex')
    try:
        os.makedirs(export_dir, exist_ok=True)
        with open(tex_path, 'w', encoding='utf-8') as handle:
            handle.write(tex)
        # ``check=False`` on purpose: xelatex's non-zero exit is this function's own ``error``
        # answer (with the log tail), which the node reports and the run survives. Raising here
        # would replace a stated refusal with a traceback out of the worker thread. The return
        # code is read below, together with "did a PDF actually appear". ``popen_kwargs`` is the
        # Windows half of "no black window flashes for every compile" — the packaged server has no
        # console of its own, and xelatex is a console program.
        #
        # Popen + wait, not ``run(timeout=…)``: on timeout ``run`` kills only the DIRECT child, and
        # xelatex starts ``xdvipdfmx`` which can outlive it holding main.pdf — the temp directory
        # then cannot be removed (silently, with ``ignore_errors``) and stays in %TEMP% for good.
        proc = subprocess.Popen(
            [xelatex, '-interaction=batchmode', '-halt-on-error', '-output-directory', work, 'main.tex'],
            cwd=work,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **procs.popen_kwargs(),
        )
        try:
            stdout, stderr = proc.communicate(timeout=COMPILE_TIMEOUT)
        except subprocess.TimeoutExpired:
            _stop_process_tree(proc)
            try:
                # Bounded: a grandchild that survived the reaper can still hold the pipe
                # open, and an unbounded ``communicate()`` then wedges the run worker forever
                # (the Stop button cannot reach this thread). Give the pipes a short second
                # chance, then abandon them and report the named timeout.
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                for stream in (proc.stdout, proc.stderr):
                    if stream is not None:
                        with contextlib.suppress(OSError):
                            stream.close()
                stdout, stderr = b'', b''
            _discard(work)
            return {'error': t('api.compilePdfTimeout', seconds=COMPILE_TIMEOUT)}, ''
        result = SimpleNamespace(returncode=proc.returncode, stdout=stdout or b'', stderr=stderr or b'')
    except (subprocess.SubprocessError, OSError) as e:
        _discard(work)
        return {'error': t('api.compilePdfFailed', err=e)}, ''
    produced = os.path.join(work, 'main.pdf')
    if result.returncode != 0 or not os.path.isfile(produced):
        # Read BEFORE the directory goes away: with ``-interaction=batchmode`` xelatex puts its
        # actual error in main.log and leaves stderr almost empty, so the log is the only place
        # where "ctex.sty not found" is still a sentence the user can act on.
        log_text = _read_log(work)
        with contextlib.suppress(OSError):
            if os.path.isfile(produced):
                os.remove(produced)
        _discard(work)
        return {'error': explain_failure(log_text, result.stderr)}, ''
    staged = os.path.join(export_dir, out_name)
    try:
        shutil.move(produced, staged)
    except OSError as e:
        _discard(work)
        return {'error': t('api.compilePdfFailed', err=e)}, ''
    _discard(work)
    name = os.path.basename(staged)
    return {'pdf_file': name, 'pdf_bytes': os.path.getsize(staged)}, name
