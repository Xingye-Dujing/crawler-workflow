"""Compile a LaTeX source to PDF with the machine's ``xelatex``.

The ``visualize`` node emits a compilable ``standalone`` document (services/latex_charts); this turns that
source into the PDF a paper actually includes — one document, one ``xelatex`` pass. It shells out the same
best-effort way the report PDF does: no ``xelatex``, or a run that will not produce a PDF, is a named
refusal surfaced as ``{'error': …}``, never a crash and never a half-written file left in the export tree.
``ctex`` needs ``xelatex`` (not ``pdflatex``), so that is the binary sought — MiKTeX's on Windows, TeX
Live's (or MacTeX's) elsewhere, which is why the search and the refusal both ask the running OS.
"""

import contextlib
import os
import re
import shutil
import subprocess
import tempfile

from core import machine

from i18n import t
from services.latex_charts import LatexChartService
from settings_store import get_setting


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
        # code is read below, together with "did a PDF actually appear".
        result = subprocess.run(
            [xelatex, '-interaction=batchmode', '-halt-on-error', '-output-directory', work, 'main.tex'],
            cwd=work,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as e:
        shutil.rmtree(work, ignore_errors=True)
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
        shutil.rmtree(work, ignore_errors=True)
        return {'error': explain_failure(log_text, result.stderr)}, ''
    staged = os.path.join(export_dir, out_name)
    try:
        shutil.move(produced, staged)
    except OSError as e:
        shutil.rmtree(work, ignore_errors=True)
        return {'error': t('api.compilePdfFailed', err=e)}, ''
    shutil.rmtree(work, ignore_errors=True)
    name = os.path.basename(staged)
    return {'pdf_file': name, 'pdf_bytes': os.path.getsize(staged)}, name
