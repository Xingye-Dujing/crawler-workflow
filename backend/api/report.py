"""一键报告 Blueprint — the ``/api/report/*`` cluster, split out of ``app.py``.

The one-click report: gather a run's tables (from the store, or from the run this page is
holding in memory), build a self-contained HTML report into the export directory, serve it back
through a locked-down door, and offer the saved Chart-Studio pictures it can inline. The helper
here (``_report_nodes`` gathering the tables) is report-only, so it moved with the routes rather
than staying in ``app``. Every dependency is reachable without importing ``app``; the
``report_service``/``export_browser`` modules stay imported lazily, exactly as before.
A PDF is no longer printed from the HTML: paper output comes only from the LaTeX route, so the
figures and tables in it are the ones the run filed.
Paths and behaviour are unchanged.
"""

import os

from core.refs import as_bool
from flask import Blueprint, jsonify, request
from runtime import paths
from runtime.settings import get_setting
from runtime.state import _results_snapshot, add_log, ambient, execution_state, run_is_foreign
from runtime.stores import get_run_store
from runtime.transport import _local_transport_refusal

from analyzers.llm_client import LLMClient
from api.http import _bad_body, _bad_param, _json_body
from i18n import get_lang, normalize, t
from services.reports import jobs

bp = Blueprint('report', __name__)


def _report_nodes(data: dict, identity: dict | None = None) -> tuple:
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

    if run_is_foreign():
        # Live results belong to the account that owns the run in flight; this caller has
        # nothing of its own in memory to report on.
        return [], {'workflow_name': '', 'run_id': '', 'status': 'in-memory'}

    titles = {}
    for entry in data.get('nodes') or []:
        if isinstance(entry, dict) and entry.get('id'):
            titles[str(entry['id'])] = str(entry.get('title') or entry.get('id'))
    nodes = [
        {'id': nid, 'title': titles.get(nid, nid), 'rows': rows}
        for nid, rows in sorted(_results_snapshot().items())
        if isinstance(rows, list)
    ]
    identity = identity if identity is not None else ambient()
    meta = {
        'workflow_name': str(identity.get('workflow_name') or ''),
        'run_id': str(execution_state.get('run_id') or ''),
        'status': 'in-memory',
    }
    return nodes, meta


def _generate_report(data: dict, identity: dict) -> tuple[int, dict]:
    """The slow half: gather tables, optionally ask the model, build and save the HTML."""
    from services.reports.html import ReportService, build_conclusion_prompt, summarize

    include_conclusion = as_bool(data.get('include_conclusion'))
    options = data.get('options')
    title = data.get('title')
    nodes, meta = _report_nodes(data, identity)
    if nodes is None:
        return 404, {'ok': False, 'error': meta}
    if not any(node['rows'] for node in nodes):
        if not str(data.get('run_id') or '').strip() and run_is_foreign():
            return 409, {'ok': False, 'error': t('api.foreignRun')}
        return 400, {'ok': False, 'error': t('api.reportNoData')}

    conclusion = ''
    conclusion_error = ''
    if include_conclusion:
        cfg = data.get('llm') or {}
        if not isinstance(cfg, dict):
            return 400, {'ok': False, 'error': t('api.paramInvalid', name='llm')}
        provider = str(cfg.get('provider') or 'ollama')
        refusal = _local_transport_refusal(provider)
        if refusal:
            add_log(refusal)
            conclusion_error = refusal
        else:
            try:
                client = LLMClient(
                    provider=provider,
                    model=str(cfg.get('model') or ''),
                    api_key=str(cfg.get('api_key') or ''),
                    max_tokens=600,
                    cancel_event=None,
                    host=(get_setting('ollama_host') if provider == 'ollama' else ''),
                )
                conclusion = client.chat(build_conclusion_prompt(summarize(nodes), normalize(data.get('lang'))))
            except Exception as e:
                add_log(t('run.reportConclusionFailed', err=e))
                conclusion_error = str(e)
                conclusion = ''

    workflow_name = meta.get('workflow_name') or 'workflow'
    report = ReportService(paths.active().export_dir)
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
        return 500, {'ok': False, 'error': t('api.reportSaveFailed')}
    add_log(t('run.reportSaved', name=saved['name'], size=saved['bytes']))
    return 200, {
        'ok': True,
        **saved,
        'charts': markup.count('<figure>'),
        'conclusion_error': conclusion_error,
    }


@bp.route('/api/report/generate', methods=['POST'])
def report_generate():
    """Start the self-contained HTML report job and answer its id at once.

    The conclusion is a model call and the build reads every node's table; neither belongs on
    the request thread, where a slow daemon used to hold a Flask worker for minutes with no way
    to stop it. The body the job produces is exactly the body this route used to return.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    title = data.get('title')
    if title is not None and not isinstance(title, str):
        return _bad_param('title')
    options = data.get('options')
    if options is not None and not isinstance(options, dict):
        return _bad_param('options')
    if not str(data.get('run_id') or '').strip() and run_is_foreign():
        # A worker would read the same foreign state, but the refusal belongs to the request:
        # the caller learns why before anything is queued.
        return jsonify({'ok': False, 'error': t('api.foreignRun')}), 409

    identity = ambient()
    job = jobs.start('report_html', lambda: _generate_report(data, identity), lang=get_lang())
    if job is None:
        return jsonify({'ok': False, 'error': t('report.jobBusy')}), 429
    if job['state'] == 'done':
        return jsonify(job['result']), job.get('status', 200)
    return jsonify({'ok': True, 'job': job}), 202


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

    from services.exports.browser import resolve_report_path

    name = request.args.get('name', '')
    path = resolve_report_path(paths.active().export_dir, name)
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


@bp.route('/api/report/latex', methods=['POST'])
def report_latex():
    """One paper document from a run: its registered figures, its three-line tables, and a method
    section that states the parameters the run actually used.

    The request carries a ``run_id`` and a title, nothing else — the sources are read out of the
    run's own file ledger, the same rule the chart panel's “编译为 PDF” button follows. Re-rendering
    charts here would let the paper's figure and the preview's figure disagree, and accepting LaTeX
    from the browser would hand ``xelatex`` a document chosen by the page.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    run_id = str(data.get('run_id') or '').strip()
    title = str(data.get('title') or '').strip()[:120]
    job = jobs.start('report_pdf', lambda: _latex_work(run_id, title), lang=get_lang())
    if job is None:
        return jsonify({'ok': False, 'error': t('report.jobBusy')}), 429
    if job['state'] == 'done':
        return jsonify(job['result']), job.get('status', 200)
    return jsonify({'ok': True, 'job': job}), 202


def _latex_work(run_id: str, title: str) -> tuple[int, dict]:
    """The slow half: assemble the LaTeX from the run ledger and compile it."""
    from services.reports import paper

    export_dir = paths.active().export_dir
    store = get_run_store()
    result = paper.generate(run_id, title=title, store=store, export_dir=export_dir)
    produced_tex = str(result.get('tex_file') or '')
    if produced_tex:
        store.record_file(run_id, '', os.path.join(export_dir, produced_tex), 'latex_doc')
    if result.get('error'):
        add_log(t('run.reportLatexFailed', err=result['error']))
        return 400, {'ok': False, 'error': result['error'], 'tex': produced_tex or None}
    store.record_file(run_id, '', os.path.join(export_dir, result['pdf_file']), 'report_pdf')
    add_log(t('run.reportLatexSaved', name=result['pdf_file'], figures=result['figures'], tables=result['tables']))
    return 200, {
        'ok': True,
        'name': result['pdf_file'],
        'tex': result['tex_file'],
        'figures': result['figures'],
        'tables': result['tables'],
    }


@bp.route('/api/jobs/<job_id>', methods=['GET'])
def document_job(job_id: str):
    """Poll one document job. Its owner is the account that started it; everyone else is 404."""
    job = jobs.get(job_id)
    if job is None:
        return jsonify({'ok': False, 'error': t('report.jobMissing')}), 404
    return jsonify({'ok': True, 'job': job})


@bp.route('/api/report/studio-images', methods=['GET'])
def report_studio_images():
    """Saved Chart-Studio pictures the report may inline, newest first.

    The picker offers only what the export folder actually holds as an image, so
    a report never asks to inline a file it cannot read: a spreadsheet that
    happens to live in the same folder is not a chart whatever the user clicked.
    """
    from services.exports.browser import list_exports
    from services.reports.html import INLINE_IMAGE_EXT

    rows = [
        {'name': row['name'], 'size': row['size'], 'mtime': row['mtime']}
        for row in list_exports(paths.active().export_dir)
        if os.path.splitext(row['name'])[1].lower() in INLINE_IMAGE_EXT
    ]
    return jsonify({'ok': True, 'images': rows})
