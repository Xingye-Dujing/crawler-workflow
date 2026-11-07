"""The environment matrix: which features this machine can actually run, and why not.

The installer and the app must give the same answer, so both call this module. It reads the same
settings the crawlers read (an explicit path beats a bundled one) and it never turns "I could not
check" into a green row:

- ``ok``: the dependency is present and version-compatible;
- ``degraded``: the feature runs but something is missing or will fall back (named);
- ``missing``: the feature cannot run until the named component is installed;
- ``unknown``: a check could not be completed.

Every reason is a catalogue key plus parameters, never an English sentence composed here: the
installer renders it in the user's language, and the tests can assert on the key.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from core.config import Config
from core.machine import (
    browser_version,
    chrome_executable_name,
    driver_executable_name,
    find_chrome,
    ollama_reachable,
    platform_name,
)
from core.procs import popen_kwargs

from services.components.catalog import Catalog, CatalogError, load_catalog
from services.components.manifest import Manifest, ManifestError
from services.components.paths import install_root

_VERSION = re.compile(r'(\d+)\.(\d+)')


def _setting(key: str) -> str:
    try:
        from runtime.settings import get_setting

        return str(get_setting(key) or '').strip()
    except (ImportError, AttributeError, OSError):
        # A missing settings store means "not configured"; it is not a reason to lose the report.
        return ''


def _installed_path(root: Path, component_id: str) -> Path | None:
    try:
        return Manifest(root).load().path_of(component_id)
    except ManifestError:
        return None


def _component_binary(root: Path, component_id: str, name: str) -> str:
    path = _installed_path(root, component_id)
    if path is None:
        return ''
    candidate = path / name
    return str(candidate) if candidate.is_file() else ''


def _version(binary: str) -> str:
    if not binary:
        return ''
    try:
        result = subprocess.run(
            [binary, '--version'],
            capture_output=True,
            timeout=10,
            check=False,
            **popen_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return ''
    text = (result.stdout or b'') + (result.stderr or b'')
    return text.decode('utf-8', errors='replace').strip().splitlines()[0] if text else ''


def _major(text: str) -> str:
    match = _VERSION.search(text or '')
    return match.group(1) if match else ''


def _chrome(root: Path) -> tuple[str, str]:
    explicit = _setting('browser_binary')
    if explicit:
        return find_chrome(explicit), 'settings'
    bundled = _component_binary(root, 'chrome', chrome_executable_name())
    if bundled:
        return bundled, 'component'
    found = find_chrome()
    return found, 'system' if found else 'none'


def _driver(root: Path) -> tuple[str, str]:
    explicit = _setting('driver_path')
    if explicit and Path(explicit).is_file():
        return explicit, 'settings'
    bundled = _component_binary(root, 'chromedriver', driver_executable_name())
    if bundled:
        return bundled, 'component'
    found = shutil.which('chromedriver')
    return (found or ''), 'system' if found else 'none'


def _catbus_state() -> dict:
    try:
        from services.ingest import catbus

        probe = catbus.probe(force=True)
    except (ImportError, OSError, ValueError):
        return {'state': 'unknown', 'reason_key': 'env.catbusUnknown', 'reason_params': {}}
    if probe.available:
        return {
            'state': 'ok',
            'reason_key': 'env.catbusOk',
            'reason_params': {'node': probe.node_version or '', 'entry': probe.entry},
            'node': probe.node,
            'entry': probe.entry,
        }
    return {
        'state': 'missing',
        'reason_key': probe.reason_key or 'env.catbusUnknown',
        'reason_params': dict(probe.reason_params),
    }


def _catbus_capability() -> dict:
    state = _catbus_state()
    return {
        'state': state['state'],
        'reason_key': state['reason_key'],
        'reason_params': state['reason_params'],
        'source': 'component' if state.get('entry') else 'system',
    }


def _ollama_state() -> dict:
    host = _setting('ollama_host')
    if not ollama_reachable(host):
        return {'state': 'missing', 'reason_key': 'env.ollamaMissing', 'reason_params': {'host': host}}
    try:
        from analyzers.llm_client import list_ollama_models

        models = list_ollama_models(host)
    except (OSError, ValueError, RuntimeError) as exc:
        return {'state': 'degraded', 'reason_key': 'env.ollamaUnreadable', 'reason_params': {'err': str(exc)[:160]}}
    names = [str(model) for model in models if str(model or '').strip()]
    if not names:
        return {'state': 'degraded', 'reason_key': 'env.ollamaNoModel', 'reason_params': {}}
    return {'state': 'ok', 'reason_key': 'env.ollamaOk', 'reason_params': {'models': ', '.join(names[:3])}}


def _xelatex_state() -> dict:
    try:
        from services.charts.pdf import find_xelatex

        found = find_xelatex()
    except (ImportError, OSError, ValueError):
        found = ''
    if found:
        return {'state': 'ok', 'reason_key': 'env.xelatexOk', 'reason_params': {'path': found}}
    return {'state': 'missing', 'reason_key': 'env.xelatexMissing', 'reason_params': {}}


def _font_state() -> dict:
    try:
        from services.charts.style import cjk_font

        family = cjk_font()
    except (ImportError, OSError, ValueError):
        family = ''
    if family:
        return {'state': 'ok', 'reason_key': 'env.fontOk', 'reason_params': {'family': family}}
    return {'state': 'degraded', 'reason_key': 'env.fontMissing', 'reason_params': {}}


def _bert_state() -> dict:
    if importlib.util.find_spec('onnxruntime') is None:
        return {'state': 'missing', 'reason_key': 'env.bertRuntimeMissing', 'reason_params': {}}
    try:
        from api.config import read_model_registry
    except ImportError:
        return {'state': 'unknown', 'reason_key': 'env.bertNoModels', 'reason_params': {}}
    rows = [row for row in read_model_registry() if row.get('operation') in ('sentiment', 'emotion', 'tendency')]
    if not rows:
        return {'state': 'degraded', 'reason_key': 'env.bertNoModels', 'reason_params': {}}
    roots = [Path(Config.DATA_DIR).parent, Path.cwd()]
    found = []
    for row in rows:
        path = Path(str(row.get('path') or ''))
        if any((path if path.is_absolute() else root / path).exists() for root in roots):
            found.append(str(row.get('operation')))
    if found:
        return {'state': 'ok', 'reason_key': 'env.bertOk', 'reason_params': {'models': ', '.join(sorted(set(found)))}}
    return {'state': 'degraded', 'reason_key': 'env.bertNoModels', 'reason_params': {}}


def _capability(
    capability_id: str,
    label_key: str,
    state: str,
    reason_key: str,
    reason_params: dict | None = None,
    source: str = 'none',
    **extra: Any,
) -> dict:
    return {
        'id': capability_id,
        'label_key': label_key,
        'state': state,
        'reason_key': reason_key,
        'reason_params': reason_params or {},
        'source': source,
        **extra,
    }


def _crawl_selenium(root: Path) -> dict:
    chrome, chrome_source = _chrome(root)
    driver, driver_source = _driver(root)
    if not chrome and not driver:
        return _capability('crawl_selenium', 'env.capBrowser', 'missing', 'env.browserAndDriverMissing')
    if not chrome:
        return _capability('crawl_selenium', 'env.capBrowser', 'missing', 'env.browserMissing')
    if not driver:
        return _capability(
            'crawl_selenium', 'env.capBrowser', 'missing', 'env.driverMissing', {'chrome': chrome}, chrome_source
        )
    chrome_version, driver_version = browser_version(chrome), _version(driver)
    chrome_major, driver_major = _major(chrome_version), _major(driver_version)
    params = {
        'chrome': chrome,
        'driver': driver,
        'chrome_version': chrome_version,
        'driver_version': driver_version,
    }
    if not (chrome_major and driver_major):
        # Saying "ok" here would be the module turning "I could not check" into a green row: both
        # files exist, but whether they are a matching pair is exactly what was not read.
        return _capability(
            'crawl_selenium', 'env.capBrowser', 'degraded', 'env.driverUnverified', params, driver_source
        )
    if chrome_major != driver_major:
        return _capability(
            'crawl_selenium',
            'env.capBrowser',
            'degraded',
            'env.driverMismatch',
            {**params, 'chrome_major': chrome_major, 'driver_major': driver_major},
            driver_source,
        )
    return _capability('crawl_selenium', 'env.capBrowser', 'ok', 'env.browserOk', params, driver_source)


def component_rows(root: Path, catalog: Catalog | None) -> list[dict]:
    try:
        installed = Manifest(root).load().installed()
    except ManifestError as exc:
        return [{'id': 'manifest', 'state': 'unknown', 'reason': str(exc)}]
    rows = []
    for component_id, record in sorted(installed.items()):
        latest = ''
        if catalog is not None and component_id in catalog.components:
            latest = catalog.components[component_id].version
        rows.append(
            {
                'id': component_id,
                'state': 'ok',
                'version': str(record.get('version') or ''),
                'path': str(root / str(record.get('path') or '')),
                'latest': latest,
                'update': bool(latest and latest != str(record.get('version') or '')),
                'installed_at': str(record.get('installed_at') or ''),
            }
        )
    return rows


def environment(root: str | Path | None = None, catalog_path: str | Path | None = None) -> dict:
    """The full report: capabilities, installed components, and the OS this answer is for."""
    base = install_root(root)
    try:
        catalog = Catalog(load_catalog(catalog_path))
    except (ImportError, OSError, ValueError, CatalogError):
        catalog = None
    capabilities = [
        _capability('core', 'env.capCore', 'ok', 'env.coreOk'),
        _crawl_selenium(base),
        _capability(
            'crawl_catbus',
            'env.capCatbus',
            **_catbus_capability(),
        ),
        _capability('llm_local', 'env.capLlmLocal', **_ollama_state()),
        _capability('llm_cloud', 'env.capLlmCloud', 'unknown', 'env.cloudUnknown'),
        _capability('bert', 'env.capBert', **_bert_state()),
        _capability('pdf', 'env.capPdf', **_xelatex_state()),
        _capability('cjk_font', 'env.capFont', **_font_state()),
        _capability('data_analysis', 'env.capAnalysis', 'ok', 'env.analysisOk'),
    ]
    return {
        'schema': 1,
        'os': platform_name(),
        'root': str(base),
        'capabilities': capabilities,
        'components': component_rows(base, catalog),
        'catalog': {
            'generated_at': catalog.generated_at if catalog else '',
            'components': len(catalog.components) if catalog else 0,
        },
    }
