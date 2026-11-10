"""The macOS online installer: a small .app that downloads the full app and its optional tools.

Windows shows the shared installer page in WebView2 and asks the shell for a folder. Neither exists
on macOS, so this entry reuses the *state machine and HTTP page* from ``installer.py`` (same
catalogue, same selection rules, same progress/log fields) and swaps the three macOS-specific seams:

* the window is pywebview's Cocoa backend over the same loopback server;
* the folder picker is ``osascript``'s ``choose folder``;
* the job installs the main application from its DMG with ``hdiutil`` + ``ditto`` — a zip would lose
  the bundle's framework symlinks and executable bits — while Chrome/Node use the native extractor in
  :mod:`services.components.macos`.

There is no administrator request: the default is ``/Applications`` when the account may write it,
otherwise ``~/Applications``, and components live under ``~/Library/Application Support/CaiXiHui``.
The app bundle itself is the same one the full DMG ships; this installer only adds a downloader.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

#: A fixed port keeps localStorage (language/theme) on one origin. 3969 is the macOS sibling of the
#: Windows installer's 3968, so a machine with a shared home and a VM never fights over one port.
INSTALLER_PORT = 3969
DOCTOR_TIMEOUT = 90
APP_NAME = 'CaiXiHui'
APP_BUNDLE = 'CaiXiHui.app'
APP_BINARY = Path('Contents') / 'MacOS' / 'CaiXiHui'
DATA_ROOT_FILE = 'data-root.txt'
#: Must equal the application bundle's identifier (``desktop/caixihui_macos.spec`` and
#: ``desktop/macos_entry.py``); the installer writes the data-folder preference there.
BUNDLE_ID = 'com.caixihui.desktop'


def asset_dir() -> Path:
    bundled = getattr(sys, '_MEIPASS', None)
    return Path(bundled).resolve() if bundled else Path(__file__).resolve().parent


def _load_shared(name: str, filename: str):
    """Load a sibling module by path: these files are scripts, not an importable package."""
    candidates = [asset_dir() / filename, Path(__file__).resolve().parent / filename]
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        raise ImportError(f'{filename} is missing from the installer bundle')
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = _load_shared('installer_shared', 'installer.py')
TEXT = installer.TEXT

#: The Windows page says “domestic route” and offers to elevate. Both are wrong here: the main app
#: comes from GitHub Release, and macOS does not run a GUI app under a second elevated copy. The
#: shared keys stay; only the sentences that differ are replaced.
MAC_WORDS = {
    'zh': {
        'intro': (
            '选择安装位置和要安装的组件。主程序从 GitHub Release 下载；Chrome for Testing、chromedriver '
            '和 Node.js 默认走 npmmirror，国内可直连。'
        ),
        'dir': '安装位置（CaiXiHui.app）',
        'data_hint': (
            '工作流、运行记录、Cookie 和 Chrome/Node 组件都放在这里；程序本体装在“安装位置”，换数据目录不用重装。'
        ),
        'preset_one': '一键安装（推荐）',
        'vpn': 'Chrome / chromedriver / Node.js 走 npmmirror 与官方地址；主程序来自 GitHub Release。',
        'license': '第三方组件按各自的许可证分发；Chrome 从 Google 官方测试通道下载，不随本安装器重新分发。',
        'not_writable': (
            '没有权限写入 {path}。请改选自己主目录下的文件夹（例如 ~/Applications），或用管理员账号运行安装器。'
        ),
        'elevated_again': '这个目录仍然不可写。请换一个目录，或检查它的权限。',
        'elevate_failed': '这个目录不可写。请换一个目录，或检查它的权限。',
        'relaunching': '正在重新打开安装器…',
        'bad_path': '这个文件夹不能被写入：{path}',
        'drive_missing': '这个文件夹不可用：{path}',
        'open': '打开安装目录',
    },
    'en': {
        'intro': (
            'Choose where to install and which components. The application comes from GitHub '
            'Releases; Chrome for Testing, chromedriver and Node.js use the npmmirror mirror first.'
        ),
        'dir': 'Install location (CaiXiHui.app)',
        'data_hint': (
            'Workflows, run records, cookies and the Chrome/Node components live here. The app '
            'bundle goes to the install location; changing the data folder needs no reinstall.'
        ),
        'preset_one': 'One-click (recommended)',
        'vpn': (
            'Chrome / chromedriver / Node.js use npmmirror and the official URLs; '
            'the application comes from GitHub Releases.'
        ),
        'license': (
            'Third-party components keep their own licences; Chrome is downloaded from Google for '
            'Testing and is not redistributed here.'
        ),
        'not_writable': (
            'No permission to write {path}. Choose a folder under your home directory '
            '(for example ~/Applications), or run the installer from an administrator account.'
        ),
        'elevated_again': 'That folder is still not writable. Choose another folder or check its permissions.',
        'elevate_failed': 'That folder is not writable. Choose another folder or check its permissions.',
        'relaunching': 'Reopening the installer…',
        'bad_path': 'That folder cannot be written: {path}',
        'drive_missing': 'That folder is not available: {path}',
        'open': 'Open install folder',
    },
}

MAC_TEXT = {lang: {**TEXT[lang], **MAC_WORDS[lang]} for lang in ('zh', 'en')}


def _takes_write(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / '.write-test'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
    except OSError:
        return False
    return True


def default_app_root() -> Path:
    """``/Applications`` when this account may write it, else the user's own Applications folder."""
    system_apps = Path('/Applications')
    if _takes_write(system_apps):
        return system_apps
    return Path.home() / 'Applications'


def default_data_root() -> Path:
    """The same default the packaged macOS application uses."""
    return Path.home() / 'Library' / 'Application Support' / 'CaiXiHui'


def _applescript_string(value: str) -> str:
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def pick_folder(title: str) -> str:
    """The native folder chooser, through ``osascript``; ``''`` when the user cancels."""
    script = f'POSIX path of (choose folder with prompt {_applescript_string(title)})'
    try:
        result = subprocess.run(
            ['/usr/bin/osascript', '-e', script],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ''
    if result.returncode != 0:
        return ''
    return (result.stdout or '').strip().rstrip('/') or '/'


def pick_file(title: str) -> str:
    """The native file chooser (the BERT field is hidden on macOS, but the seam stays complete)."""
    script = f'POSIX path of (choose file with prompt {_applescript_string(title)})'
    try:
        result = subprocess.run(
            ['/usr/bin/osascript', '-e', script],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ''
    if result.returncode != 0:
        return ''
    return (result.stdout or '').strip()


def _run(command: list[str], what: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return
    lines = (result.stderr or result.stdout or '').strip().splitlines()
    reason = lines[-1] if lines else f'exit {result.returncode}'
    raise installer.InstallError(f'{what}: {reason}')


def _app_binary(root: Path) -> Path:
    return Path(root) / APP_BUNDLE / APP_BINARY


def _install_app(catalog, root: Path, data: Path, progress, cancel) -> Path:
    """Mount the application DMG and copy ``CaiXiHui.app`` into place, preserving the bundle."""
    component = catalog.get('app')
    asset = component.asset()
    if asset is None:
        raise installer.InstallError('app has no macOS asset in this catalogue')
    target = Path(root) / APP_BUNDLE
    marker = Path(root) / 'app-install.json'
    if target.is_dir() and _app_binary(root).is_file() and marker.is_file():
        with contextlib.suppress(OSError, ValueError):
            recorded = json.loads(marker.read_text(encoding='utf-8'))
            if isinstance(recorded, dict) and recorded.get('sha256') == asset.sha256:
                return target
    Path(root).mkdir(parents=True, exist_ok=True)
    cache = Path(data) / '.cache' / f'app-{component.version}-{asset.sha256[:12]}.dmg'
    dmg = installer.download_asset(asset, cache, progress=progress, cancel=cancel)
    if cancel():
        raise installer.DownloadError('cancelled before installing the application')
    mount = Path(tempfile.mkdtemp(prefix='caixihui-dmg-'))
    staging = Path(root) / f'.{APP_BUNDLE}.staging-{os.getpid()}'
    try:
        _run(
            [
                '/usr/bin/hdiutil',
                'attach',
                '-nobrowse',
                '-noautoopen',
                '-readonly',
                '-mountpoint',
                str(mount),
                str(dmg),
            ],
            'mounting the application image',
        )
        bundles = sorted(item for item in mount.iterdir() if item.is_dir() and item.suffix == '.app')
        if len(bundles) != 1:
            raise installer.InstallError(f'the application image contains {len(bundles)} .app bundles, expected 1')
        shutil.rmtree(staging, ignore_errors=True)
        # ditto copies a bundle AS a bundle (Contents/… inside the destination), and preserves the
        # framework symlinks and executable bits that make the .app launchable.
        _run(['/usr/bin/ditto', str(bundles[0]), str(staging)], 'copying the application bundle')
        if not (staging / APP_BINARY).is_file():
            raise installer.InstallError(f'the application image has no {APP_BINARY.as_posix()}')
        previous = Path(root) / f'{APP_BUNDLE}.previous'
        if previous.exists():
            shutil.rmtree(previous)
        if target.exists():
            os.replace(target, previous)
        try:
            os.replace(staging, target)
        except OSError:
            # Put the old bundle back: a failed swap must not leave the user with no application.
            if previous.exists() and not target.exists():
                os.replace(previous, target)
            raise
    finally:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(['/usr/bin/hdiutil', 'detach', str(mount), '-force'], capture_output=True, check=False)
        shutil.rmtree(mount, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)
    with contextlib.suppress(OSError):
        marker.write_text(
            json.dumps(
                {'version': component.version, 'sha256': asset.sha256, 'source': asset.urls[0] if asset.urls else ''},
                ensure_ascii=False,
            )
            + '\n',
            encoding='utf-8',
        )
    # Only a completed install removes the image; a cancel keeps its bytes so a retry resumes.
    with contextlib.suppress(OSError):
        dmg.unlink(missing_ok=True)
    return target


class MacInstallerState(installer.InstallerState):
    """The Windows state with a macOS job: app from a DMG, tools into the data root."""

    #: The macOS app is installed in /Applications and appears in Launchpad; a desktop .lnk is a
    #: Windows shell concept, so its page hides the checkbox.
    shortcut_supported = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Declared here as well as in the base: the doctor is written from the worker thread, and
        # pylint's W0201 guard is about this class's own __init__, not the inherited one.
        self.doctor = {'state': 'idle', 'report': {}}

    def _run_job(self, ids: list[str], root: Path, data: Path) -> None:
        total = max(1, len(ids))
        for index, component_id in enumerate(ids):
            if self.cancel.is_set():
                self._set_job(state='cancelled')
                return
            component = self.catalog.get(component_id)
            self._set_job(status_key='installing', status_params={'name': component_id})
            self._set_job(done=int(index / total * 100))
            try:

                def progress(done: int, size: int, start=index) -> None:
                    if size:
                        self._set_job(done=int((start + done / size) / total * 100))

                if component_id == 'app':
                    _install_app(self.catalog, root, data, progress, self.cancel.is_set)
                else:
                    installer.install_component(
                        self.catalog,
                        component_id,
                        data,
                        progress=progress,
                        cancel=self.cancel.is_set,
                    )
            except (
                installer.InstallError,
                installer.CatalogError,
                installer.DownloadError,
                installer.ManifestError,
                OSError,
                subprocess.SubprocessError,
            ) as exc:
                self._set_job(state='failed', error=str(exc), status_key='')
                return
            self._log(f'{component_id} {component.version} -> {root if component_id == "app" else data}')
        if self.bert:
            self._set_job(done=99, status_key='bert_installing', status_params={})
            models = Path(data) / 'bert_models'
            try:
                placed = installer.install_bert_pack(
                    self.bert,
                    root,
                    data,
                    models_dir=models,
                    root_label=models.as_posix(),
                )
            except (installer.BertPackError, OSError, ValueError) as exc:
                self._set_job(state='failed', error=str(exc), status_key='')
                return
            ledger = placed['ledger']
            for name in ledger['added']:
                self._log(f'bert registered: {name}')
            for name in ledger['skipped']:
                self._log(f'bert existing registry entry kept: {name}')
            for name in placed['skipped_folders']:
                self._log(f'bert model folder already present, kept: {name}')
            self._log(f'bert {ledger["packs"]} packs -> {models}')
        self._write_data_root(root, data)
        self._set_job(done=100, state='done', status_key='done', status_params={})
        self._run_doctor(root, data)

    def _write_data_root(self, root: Path, data: Path) -> None:
        """Record the chosen data folder, readable by a later double-click.

        Two places, because each survives a different move: ``data-root.txt`` beside the .app is
        what the launcher reads first, while the preference domain survives the bundle being dragged
        into ``~/Applications``. Neither is inside the bundle, so a signed app stays signed.
        """
        try:
            (Path(root) / DATA_ROOT_FILE).write_text(str(data), encoding='utf-8')
        except OSError as exc:
            with self.lock:
                self.job['log'].append(f'{DATA_ROOT_FILE}: {exc}')
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ['/usr/bin/defaults', 'write', BUNDLE_ID, 'CRAWLER_DATA_ROOT', str(data)],
                capture_output=True,
                check=False,
            )

    def _run_doctor(self, root: Path, data: Path) -> None:
        binary = _app_binary(root)
        if not binary.exists():
            self.doctor = {'state': 'done', 'report': {}}
            return
        self.doctor = {'state': 'running', 'report': {}}
        env = dict(os.environ)
        env['CIXI_COMPONENTS_DIR'] = str(Path(data) / 'components')
        env['CRAWLER_DATA_ROOT'] = str(data)
        env['PYTHONIOENCODING'] = 'utf-8'
        report: dict = {}
        try:
            result = subprocess.run(
                [str(binary), '--doctor'],
                capture_output=True,
                timeout=DOCTOR_TIMEOUT,
                check=False,
                env=env,
            )
            text = (result.stdout or b'').decode('utf-8-sig', errors='replace')
            start = text.find('{')
            report = json.loads(text[start:]) if start >= 0 else {}
        except (OSError, subprocess.SubprocessError, ValueError):
            report = {}
        self.doctor = {'state': 'done', 'report': report if isinstance(report, dict) else {}}


class MacHandler(installer.Handler):
    @property
    def words(self) -> dict:
        return MAC_TEXT

    pick_folder = staticmethod(pick_folder)
    pick_file = staticmethod(pick_file)

    def _start(self, state: MacInstallerState, payload: dict) -> dict:
        lang = 'en' if str(payload.get('lang')) == 'en' else 'zh'
        words = self.words[lang]
        if state.job['state'] == 'running':
            return {'ok': False, 'error': words['already_running']}
        root_text = str(payload.get('root') or '').strip()
        data_text = str(payload.get('data') or '').strip()
        if not root_text or not data_text:
            return {'ok': False, 'error': words['dir']}
        state.set_selection(payload.get('ids'))
        ids = state.effective()
        if 'app' not in ids:
            return {'ok': False, 'error': words['no_selection']}
        bert_text = str(payload.get('bert') or '').strip()
        if bert_text:
            problem = installer.bert_pack_problem(bert_text)
            if problem:
                return {'ok': False, 'error': words['bert_invalid'].format(err=problem)}
        state.set_bert(bert_text)
        root = Path(root_text).expanduser()
        data = Path(data_text).expanduser()
        for path in (root, data):
            if not _takes_write(path):
                return {'ok': False, 'error': words['not_writable'].format(path=path)}
        need = sum(state.catalog.get(item).asset().size for item in ids if state.catalog.get(item).asset())
        if state.bert:
            with contextlib.suppress(OSError):
                source = Path(state.bert)
                if source.is_file():
                    need += source.stat().st_size
        free = installer.free_space(data)
        if free and free < need + 200 * 1024 * 1024:
            return {
                'ok': False,
                'error': words['disk'].format(free=installer.human_size(free), need=installer.human_size(need)),
            }
        state.start(root, data)
        return {'ok': True, 'state': state.snapshot()}

    def _open_folder(self, root: str) -> None:
        path = Path(root)
        try:
            path.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(['/usr/bin/open', str(path)])
        except OSError:
            return

    def _launch(self, state: MacInstallerState) -> dict:
        binary = _app_binary(Path(state.root))
        if not binary.exists():
            return {'ok': False, 'error': self.words['zh']['not_installed']}
        env = dict(os.environ)
        env['CIXI_COMPONENTS_DIR'] = str(Path(state.data) / 'components')
        env['CRAWLER_DATA_ROOT'] = state.data
        try:
            subprocess.Popen([str(binary)], cwd=str(binary.parent), env=env, start_new_session=True)
        except OSError as exc:
            return {'ok': False, 'error': str(exc)}
        self.server.stop_soon(1.0)
        return {'ok': True}


class MacInstallerServer(installer.InstallerServer):
    def __init__(self, state: MacInstallerState, token: str, port: int = INSTALLER_PORT) -> None:
        super().__init__(state, token=token, port=port, handler=MacHandler)
        # Declared on this class too; main() assigns the window closer after construction.
        self.on_stop = None


_WINDOW = None


def close_window() -> None:
    window = _WINDOW
    if window is not None:
        with contextlib.suppress(Exception):
            window.destroy()


def _alert(message: str) -> None:
    script = f'display alert {_applescript_string("采析绘安装器")} message {_applescript_string(message)} as critical'
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(['/usr/bin/osascript', '-e', script], timeout=10, check=False)


def run_window(title: str, url: str, state: MacInstallerState) -> str:
    """Show the page in a Cocoa window; ``''`` on a normal close, else a named failure."""
    global _WINDOW
    try:
        import webview
    except Exception as exc:
        return f'无法加载窗口组件：{exc}'
    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
    storage = Path.home() / 'Library' / 'Application Support' / APP_NAME / 'webview-installer'
    if not _takes_write(storage):
        storage = Path(tempfile.gettempdir()) / 'CaiXiHui-installer-webview'
        _takes_write(storage)
    window = webview.create_window(
        title,
        url,
        width=1080,
        height=760,
        min_size=(920, 640),
        text_select=True,
    )
    _WINDOW = window

    def closing() -> bool:
        return bool(installer.may_close(state.job['state']))

    def closed() -> None:
        # Same rule as the Windows installer: closing the window ends the process, not just the
        # event loop. A lingering Cocoa host would keep the fixed port and the install folder busy.
        installer.native_window.terminate_process()

    window.events.closing += closing
    window.events.closed += closed
    try:
        webview.start(gui='cocoa', private_mode=False, storage_path=str(storage))
    except Exception as exc:
        return f'无法打开程序窗口：{exc}'
    finally:
        _WINDOW = None
    return ''


def _make_server(state: MacInstallerState, token: str) -> MacInstallerServer:
    try:
        return MacInstallerServer(state, token=token, port=INSTALLER_PORT)
    except OSError:
        return MacInstallerServer(state, token=token, port=0)


def _catalog_path() -> Path:
    override = str(os.environ.get('CIXI_INSTALLER_CATALOG') or '').strip()
    if override:
        return Path(override)
    bundled = asset_dir() / 'default_catalog.json'
    if bundled.is_file():
        return bundled
    return Path(__file__).resolve().parents[2] / 'backend' / 'services' / 'components' / 'default_catalog.json'


def main(argv=None) -> int:
    installer.native_window.ensure_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    options: dict[str, str] = {}
    for index, arg in enumerate(argv):
        if arg in ('--root', '--data') and index + 1 < len(argv):
            options[arg[2:]] = argv[index + 1]
    catalog = installer.Catalog(installer.load_catalog(_catalog_path()))
    state = MacInstallerState(
        catalog,
        options.get('root') or str(default_app_root()),
        options.get('data') or str(default_data_root()),
        elevated=False,
    )
    token = str(os.environ.get('CIXI_INSTALLER_TOKEN') or '').strip() or secrets.token_hex(8)
    server = _make_server(state, token)
    server.on_stop = close_window
    url = server.url
    installer.log_line(f'安装器已启动：{url}')
    threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.2}, daemon=True).start()

    no_window = os.environ.get('CIXI_NO_WINDOW') == '1' or '--no-window' in argv
    if no_window:
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever(poll_interval=0.2)
        failure = ''
    else:
        failure = run_window(MAC_TEXT['zh']['title'], url, state)
    if failure:
        installer.log_line(f'window failed: {failure}')
        _alert(failure)
    with contextlib.suppress(OSError):
        server.shutdown()
    server.server_close()
    installer.log_line('installer stopped')
    status = 1 if failure else 0
    if not no_window:
        installer.native_window.terminate_process(status)
    return status


if __name__ == '__main__':
    raise SystemExit(main())
