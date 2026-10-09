"""一键报告 Blueprint — the ``/api/report/*`` cluster, split out of ``app.py``.

The one-click report: gather a run's tables (from the store, or from the run this page is
holding in memory), build a self-contained HTML report into the export directory, serve it back
through a locked-down door, optionally print it to PDF with the user's own Chrome, and offer the
saved Chart-Studio pictures it can inline. The two helpers here (``_report_nodes`` gathering the
tables, ``_find_chrome`` locating the print binary) are report-only, so they moved with the routes
rather than staying in ``app``. Every dependency is reachable without importing ``app``; the
``report_service``/``export_browser`` modules stay imported lazily, exactly as before.
Paths and behaviour are unchanged.
"""

import contextlib
import os
import shutil
import subprocess
import tempfile

from flask import Blueprint, jsonify, request
from state import _results_snapshot, add_log, execution_state
from stores import get_run_store
from transport import _local_transport_refusal

from analyzers.llm_client import LLMClient
from api.http import _bad_body, _bad_param, _json_body
from config import Config
from i18n import normalize, t
from settings_store import get_setting
from utils.helpers import as_bool

bp = Blueprint('report', __name__)


def _report_nodes(data: dict) -> tuple:
    """The tables a report may describe, as ``(nodes, meta)``.

    Two sources, one shape. With a ``run_id`` the tables come out of the run
    store, so a report can be written for a run that finished hours ago (the
    titles are stored with it). Without one, the last run in this process is
    used and the browser supplies the node titles it has on the canvas — the
    store is not the only thing worth reporting on, and a user who just watched
    a run should not have to find its record first.
    """
    run_id = str(data.get('run_id') or '').strip()
    if run_id:
        store = get_run_store()
        run = store.get_run(run_id)
        if not run:
            return None, t('api.runNotFound', rid=run_id)
        nodes = [
            {
                'id': entry.get('node_id', ''),
                'title': str(entry.get('title') or entry.get('node_id') or ''),
                'rows': store.load_rows(run_id, str(entry.get('node_id') or '')),
            }
            for entry in run.get('nodes') or []
        ]
        meta = {
            'workflow_name': run.get('workflow_name') or '',
            'run_id': run_id,
            'status': run.get('status') or '',
            'started_at': run.get('started_at') or '',
            'finished_at': run.get('finished_at') or '',
        }
        return nodes, meta

    titles = {}
    for entry in data.get('nodes') or []:
        if isinstance(entry, dict) and entry.get('id'):
            titles[str(entry['id'])] = str(entry.get('title') or entry.get('id'))
    nodes = [
        {'id': nid, 'title': titles.get(nid, nid), 'rows': rows}
        for nid, rows in sorted(_results_snapshot().items())
        if isinstance(rows, list)
    ]
    meta = {
        'workflow_name': str(execution_state.get('workflow_name') or ''),
        'run_id': str(execution_state.get('run_id') or ''),
        'status': 'in-memory',
    }
    return nodes, meta


@bp.route('/api/report/generate', methods=['POST'])
def report_generate():
    """Write a self-contained HTML report of a run into the export directory.

    It lands there and nowhere else, which is what makes the export panel's
    download and delete buttons work on it without a second set of routes.
    """
    from services.report_service import ReportService, build_conclusion_prompt, summarize

    data = _json_body()
    if data is None:
        return _bad_body()
    title = data.get('title')
    if title is not None and not isinstance(title, str):
        return _bad_param('title')
    include_conclusion = as_bool(data.get('include_conclusion'))
    options = data.get('options')
    if options is not None and not isinstance(options, dict):
        return _bad_param('options')

    nodes, meta = _report_nodes(data)
    if nodes is None:
        return jsonify({'ok': False, 'error': meta}), 404
    if not any(node['rows'] for node in nodes):
        return jsonify({'ok': False, 'error': t('api.reportNoData')}), 400

    conclusion = ''
    if include_conclusion:
        cfg = data.get('llm') or {}
        if not isinstance(cfg, dict):
            return _bad_param('llm')
        provider = str(cfg.get('provider') or 'ollama')
        refusal = _local_transport_refusal(provider)
        if refusal:
            # Named rather than attempted. A connection error against a port nothing
            # listens on would be logged as 「结论生成失败」 and send the user to retry a
            # paragraph this host can never write; the report itself still ships, because
            # the deliverable was never the paragraph.
            add_log(refusal)
        else:
            try:
                client = LLMClient(
                    provider=provider,
                    model=str(cfg.get('model') or ''),
                    api_key=str(cfg.get('api_key') or ''),
                    max_tokens=600,
                    # A report request is its own call: it must not inherit the stop
                    # flag of a run that ended (or is running) in this process.
                    cancel_event=None,
                    host=(str(cfg.get('ollama_host') or '') if provider == 'ollama' else ''),
                )
                conclusion = client.chat(build_conclusion_prompt(summarize(nodes), normalize(data.get('lang'))))
            except Exception as e:
                # The report is the deliverable; a missing paragraph is a note in it.
                add_log(t('run.reportConclusionFailed', err=e))
                conclusion = ''

    workflow_name = meta.get('workflow_name') or 'workflow'
    report = ReportService(Config.EXPORT_DIR)
    name = (title or '').strip() or workflow_name
    markup = report.build(
        (title or '').strip() or t('report.default_title', name=workflow_name),
        nodes,
        meta,
        conclusion=conclusion,
        options=options,
    )
    try:
        saved = report.save(markup, name)
    except OSError as e:
        add_log(t('run.reportFailed', err=e))
        return jsonify({'ok': False, 'error': str(e)}), 500
    add_log(t('run.reportSaved', name=saved['name'], size=saved['bytes']))
    return jsonify({'ok': True, **saved, 'charts': markup.count('<figure>')})


@bp.route('/api/report/view', methods=['GET'])
def report_view():
    """Show one generated report in the browser, without letting it execute.

    A report is built out of text crawled off the internet, and ``.html`` is on
    the export panel's refuse-to-download list precisely because a page served
    from this app's origin can read this app's pages. So it gets its own door:
    only a name carrying the report prefix resolves, and the response forbids
    script and any external resource — the inline styles and the base64 pictures
    the writer itself produced are all that can render.
    """
    from flask import send_file

    from services.export_browser import resolve_report_path

    name = request.args.get('name', '')
    path = resolve_report_path(Config.EXPORT_DIR, name)
    if not path:
        return jsonify({'ok': False, 'error': t('api.exportNotFound', name=name)}), 404
    response = send_file(path, mimetype='text/html', download_name=os.path.basename(path))
    # ``as_attachment`` stays False: the point is to read it here. Handing the
    # name to send_file rather than writing the header by hand is what makes a
    # Chinese report title survivable — Flask encodes it (filename*=UTF-8''…),
    # while a raw non-ASCII header value stops the response halfway and leaves
    # the browser waiting for a document that never arrives.
    response.headers['Content-Security-Policy'] = (
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def _find_chrome() -> str:
    """The Chrome (not chromedriver) binary used to print a report to PDF.

    The browser is a separate executable from the driver the crawler drives, so
    it is located on its own: an explicit ``browser_binary`` the user set first,
    then a ``chrome.exe`` sitting beside a configured chromedriver, then the
    platform default, then anything on PATH. Empty when none is found — PDF is
    then refused with a reason, never a stack trace.
    """
    explicit = str(get_setting('browser_binary') or '').strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    driver = str(get_setting('driver_path') or getattr(Config, 'DRIVER_PATH', '') or '').strip()
    if driver:
        sibling = os.path.join(os.path.dirname(driver), 'chrome.exe')
        if os.path.isfile(sibling):
            return sibling
    for candidate in (
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    ):
        if os.path.isfile(candidate):
            return candidate
    return shutil.which('chrome') or shutil.which('google-chrome') or shutil.which('chromium') or ''


@bp.route('/api/report/pdf', methods=['POST'])
def report_pdf():
    """Print an already-generated report to PDF with the user's own Chrome.

    A report is HTML this writer built from crawled text, and the highest-
    fidelity way to a PDF is the same engine a browser uses — so this drives a
    throwaway headless Chrome rather than adding a rendering dependency. It is
    best-effort: no Chrome, or a Chrome that will not print, becomes an error the
    panel can show, never a crash and never a half-written file left behind. The
    profile directory is fresh and deleted afterwards: a print must never touch a
    platform's real login profile.
    """
    from pathlib import Path

    from services.export_browser import resolve_report_path

    data = _json_body()
    if data is None:
        return _bad_body()
    name = str(data.get('name') or '').strip()
    html_path = resolve_report_path(Config.EXPORT_DIR, name)
    if not html_path:
        return jsonify({'ok': False, 'error': t('api.reportPdfNotFound', name=name)}), 404
    chrome = _find_chrome()
    if not chrome:
        return jsonify({'ok': False, 'error': t('api.reportPdfNoChrome')}), 500
    pdf_name = os.path.splitext(os.path.basename(html_path))[0] + '.pdf'
    pdf_path = os.path.join(os.path.dirname(html_path), pdf_name)
    profile_dir = tempfile.mkdtemp(prefix='cixi-pdf-')
    command = [
        chrome,
        '--headless=new',
        '--disable-gpu',
        '--no-sandbox',
        '--no-pdf-header-footer',
        f'--user-data-dir={profile_dir}',
        f'--print-to-pdf={pdf_path}',
        Path(html_path).as_uri(),
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=90)
    except (subprocess.SubprocessError, OSError) as e:
        shutil.rmtree(profile_dir, ignore_errors=True)
        add_log(t('run.reportPdfFailed', err=e))
        return jsonify({'ok': False, 'error': str(e)}), 500
    shutil.rmtree(profile_dir, ignore_errors=True)
    if result.returncode != 0 or not os.path.isfile(pdf_path):
        with contextlib.suppress(OSError):
            if os.path.isfile(pdf_path):
                os.remove(pdf_path)
        detail = (result.stderr or b'').decode('utf-8', 'replace')[-300:]
        add_log(t('run.reportPdfFailed', err=detail))
        return jsonify({'ok': False, 'error': t('api.reportPdfFailed', err=detail)}), 500
    add_log(t('run.reportPdfSaved', name=pdf_name, size=os.path.getsize(pdf_path)))
    return jsonify({'ok': True, 'name': pdf_name, 'bytes': os.path.getsize(pdf_path)})


@bp.route('/api/report/studio-images', methods=['GET'])
def report_studio_images():
    """Saved Chart-Studio pictures the report may inline, newest first.

    The picker offers only what the export folder actually holds as an image, so
    a report never asks to inline a file it cannot read: a spreadsheet that
    happens to live in the same folder is not a chart whatever the user clicked.
    """
    from services.export_browser import list_exports
    from services.report_service import INLINE_IMAGE_EXT

    rows = [
        {'name': row['name'], 'size': row['size'], 'mtime': row['mtime']}
        for row in list_exports(Config.EXPORT_DIR)
        if os.path.splitext(row['name'])[1].lower() in INLINE_IMAGE_EXT
    ]
    return jsonify({'ok': True, 'images': rows})
