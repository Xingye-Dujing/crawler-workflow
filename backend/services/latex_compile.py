"""Compile a LaTeX source to PDF with the user's MiKTeX ``xelatex``.

The ``visualize`` node emits a compilable ``standalone`` document (services/latex_charts); this turns that
source into the PDF a paper actually includes — one document, one ``xelatex`` pass. It shells out the same
best-effort way the report PDF does: no ``xelatex``, or a run that will not produce a PDF, is a named
refusal surfaced as ``{'error': …}``, never a crash and never a half-written file left in the export tree.
``ctex`` needs ``xelatex`` (not ``pdflatex``), so that is the binary sought.
"""

import contextlib
import os
import shutil
import subprocess
import tempfile

from i18n import t
from services.latex_charts import LatexChartService
from settings_store import get_setting


def compose_tex(docs) -> str:
    """One standalone document merging the bodies of the given standalone sources (figure and/or table)."""
    return LatexChartService.compose_from_standalone(list(docs))


def _find_xelatex() -> str:
    """The MiKTeX ``xelatex`` binary: an explicit ``latex_binary`` the user set first, then PATH,
    then the common install locations. Empty → the compile is refused with a reason, never a stack trace."""
    explicit = str(get_setting('latex_binary') or '').strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    found = shutil.which('xelatex') or shutil.which('miktex-xelatex')
    if found:
        return found
    local = os.environ.get('LOCALAPPDATA', '')
    candidates = [
        os.path.join(local, 'Programs', 'MiKTeX', 'miktex', 'bin', 'x64', 'xelatex.exe') if local else '',
        r'C:\Program Files\MiKTeX\miktex\bin\x64\xelatex.exe',
        r'C:\Program Files (x86)\MiKTeX\miktex\bin\x64\xelatex.exe',
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ''


def compile_pdf(tex: str, out_name: str, export_dir: str) -> tuple[dict, str]:
    """Compile ``tex`` and stage the PDF as ``out_name`` under ``export_dir``; return ``(result, name)``.

    ``result`` is ``{'pdf_file', 'pdf_bytes'}`` on success, or ``{'error': …}`` on any failure — no binary,
    a non-zero run, or a missing output. A throwaway working directory keeps xelatex's aux/log out of the
    export tree, and nothing half-written survives. The caller names the node's own final file, so the PDF
    it lands on is deterministic per run and simply overwritten on a re-run.
    """
    xelatex = _find_xelatex()
    if not xelatex:
        return {'error': t('api.compilePdfNoXelatex')}, ''
    work = tempfile.mkdtemp(prefix='cixi-tex-')
    tex_path = os.path.join(work, 'main.tex')
    try:
        os.makedirs(export_dir, exist_ok=True)
        with open(tex_path, 'w', encoding='utf-8') as handle:
            handle.write(tex)
        result = subprocess.run(
            [xelatex, '-interaction=batchmode', '-halt-on-error', '-output-directory', work, 'main.tex'],
            cwd=work,
            capture_output=True,
            timeout=120,
        )
    except (subprocess.SubprocessError, OSError) as e:
        shutil.rmtree(work, ignore_errors=True)
        return {'error': t('api.compilePdfFailed', err=e)}, ''
    produced = os.path.join(work, 'main.pdf')
    if result.returncode != 0 or not os.path.isfile(produced):
        with contextlib.suppress(OSError):
            if os.path.isfile(produced):
                os.remove(produced)
        shutil.rmtree(work, ignore_errors=True)
        detail = (result.stderr or b'').decode('utf-8', 'replace')[-300:]
        return {'error': t('api.compilePdfFailed', err=detail)}, ''
    staged = os.path.join(export_dir, out_name)
    try:
        shutil.move(produced, staged)
    except OSError as e:
        shutil.rmtree(work, ignore_errors=True)
        return {'error': t('api.compilePdfFailed', err=e)}, ''
    shutil.rmtree(work, ignore_errors=True)
    name = os.path.basename(staged)
    return {'pdf_file': name, 'pdf_bytes': os.path.getsize(staged)}, name
