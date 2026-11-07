"""The online installer: choose a folder and components, download from domestic mirrors, launch.

This is the small Windows-only counterpart to ``CaiXiHui-Setup.exe``. It is one file, does not need
admin rights and downloads only portable archives; the application itself is just another catalogue
entry. The novice preset is deliberately the no-VPN route: the bundled catalogue puts npmmirror and
Gitee first, so a user in China can finish without a proxy.

The UI is Tkinter because it ships with CPython and the build already uses PyInstaller. Download,
verification, extraction and the environment report are the same modules the running app uses, so
the installer cannot disagree with the app about what is installed.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

TEXT = {
    'zh': {
        'title': '采析绘安装器',
        'intro': '选择安装位置和要安装的组件。默认是“国内直连”，不需要翻墙。',
        'dir': '安装位置',
        'browse': '浏览…',
        'preset': '安装方式',
        'preset_one': '一键安装（推荐，国内直连）',
        'preset_all': '全部组件',
        'preset_app': '仅主程序',
        'components': '组件',
        'size': '需要下载：{size}',
        'install': '开始安装',
        'launch': '启动采析绘',
        'open': '打开安装目录',
        'cancel': '取消',
        'installing': '正在安装 {name}…',
        'done': '安装完成。正在检查环境…',
        'failed': '安装失败：{err}',
        'no_selection': '至少选择主程序。',
        'disk': '目标磁盘剩余 {free}，需要 {need}。请换一个磁盘或减少组件。',
        'doctor_title': '环境检查',
        'doctor_head': '这台机器现在可以做什么：',
        'doctor_missing': '缺少：{what}',
        'doctor_running': '正在检查环境…',
        'doctor_empty': '没有拿到环境报告：应用没有返回结果。可以打开“环境与组件”重新检测。',
        'close': '关闭',
        'need_admin': '这个目录不可写，请换一个目录（推荐“浏览…”选 D 盘）。',
        'license': '第三方组件按各自的许可证分发；Chrome 从 Google 官方测试通道下载，不随本安装器重新分发。',
        'vpn': '默认使用国内镜像（npmmirror / Gitee）；不需要翻墙。',
    },
    'en': {
        'title': 'CaiXiHui Installer',
        'intro': 'Choose where to install and which components. The default is the domestic route; no VPN needed.',
        'dir': 'Install folder',
        'browse': 'Browse…',
        'preset': 'Preset',
        'preset_one': 'One-click (recommended, domestic)',
        'preset_all': 'All components',
        'preset_app': 'Application only',
        'components': 'Components',
        'size': 'Download size: {size}',
        'install': 'Install',
        'launch': 'Launch CaiXiHui',
        'open': 'Open folder',
        'cancel': 'Cancel',
        'installing': 'Installing {name}…',
        'done': 'Installed. Checking the environment…',
        'failed': 'Install failed: {err}',
        'no_selection': 'Select at least the application.',
        'disk': 'The target drive has {free} free but needs {need}. Choose another drive or fewer components.',
        'doctor_title': 'Environment check',
        'doctor_head': 'This machine can now:',
        'doctor_missing': 'Missing: {what}',
        'doctor_running': 'Checking the environment…',
        'doctor_empty': 'No environment report came back. Open 环境与组件 in the app to check again.',
        'close': 'Close',
        'need_admin': 'That folder is not writable; choose another one (D: is fine).',
        'license': (
            'Third-party components keep their own licences; Chrome is downloaded from Google for '
            'Testing and is not redistributed here.'
        ),
        'vpn': 'Domestic mirrors (npmmirror / Gitee) are tried first; no VPN is needed.',
    },
}

STATE_LABEL = {
    'zh': {'ok': '可用', 'degraded': '可用（有降级）', 'missing': '不可用', 'unknown': '无法核对'},
    'en': {'ok': 'available', 'degraded': 'available (degraded)', 'missing': 'unavailable', 'unknown': 'not checked'},
}


def _backend_on_path() -> None:
    """Make ``services.components`` importable without importing the application's package root.

    ``backend/services/__init__.py`` exports CookieManager/StatsService/WorkflowManager, which pull
    the whole analysis stack. The installer only needs the component core, so a synthetic package
    object is put in ``sys.modules`` first: importing the subpackage then skips that eager root.
    """
    bundle = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    candidates = [
        bundle / 'backend',
        bundle,
        Path(__file__).resolve().parents[2] / 'backend',
        Path(__file__).resolve().parents[1] / 'backend',
    ]
    backend = next((item for item in candidates if (item / 'services' / 'components').is_dir()), None)
    if backend is None:
        return
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    import types

    if 'services' not in sys.modules:
        package = types.ModuleType('services')
        package.__path__ = [str(backend / 'services')]
        sys.modules['services'] = package
    if 'services.components' not in sys.modules:
        component = types.ModuleType('services.components')
        component.__path__ = [str(backend / 'services' / 'components')]
        sys.modules['services.components'] = component


_backend_on_path()

_CATALOG = importlib.import_module('services.components.catalog')
_INSTALL = importlib.import_module('services.components.install')
_PLAN_SPEC = importlib.util.spec_from_file_location('installer_plan', Path(__file__).with_name('plan.py'))
assert _PLAN_SPEC and _PLAN_SPEC.loader
_PLAN = importlib.util.module_from_spec(_PLAN_SPEC)
_PLAN_SPEC.loader.exec_module(_PLAN)
Catalog = _CATALOG.Catalog
CatalogError = _CATALOG.CatalogError
load_catalog = _CATALOG.load_catalog
_DOWNLOAD = importlib.import_module('services.components.fetch')
DownloadError = _DOWNLOAD.DownloadError
_MANIFEST = importlib.import_module('services.components.manifest')
ManifestError = _MANIFEST.ManifestError
InstallError = _INSTALL.InstallError
install_component = _INSTALL.install_component
default_root = _PLAN.default_root
free_space = _PLAN.free_space
human_size = _PLAN.human_size


def _selected_ids(preset: str, chosen: dict[str, tk.BooleanVar], catalog: Catalog) -> list[str]:
    downloadable = list(catalog.downloadable())
    return _PLAN.selected_ids(preset, {key: var.get() for key, var in chosen.items()}, downloadable)


class Installer(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.lang = 'zh'
        self.catalog = Catalog(load_catalog())
        self.root_dir = tk.StringVar(value=str(default_root()))
        self.preset = tk.StringVar(value='one')
        self.message: queue.Queue[tuple] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel = threading.Event()
        self.chosen: dict[str, tk.BooleanVar] = {}
        self._build()
        self._poll()

    # ── UI ──────────────────────────────────────────────────────
    def t(self, key: str, **values) -> str:
        text = TEXT[self.lang].get(key, key)
        try:
            return text.format(**values)
        except (KeyError, IndexError):
            return text

    def _build(self) -> None:
        self.title(self.t('title'))
        self.geometry('820x640')
        self.minsize(760, 560)
        frame = ttk.Frame(self, padding=18)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text=self.t('intro'), wraplength=760).pack(anchor='w')
        top = ttk.Frame(frame)
        top.pack(fill='x', pady=(12, 4))
        ttk.Label(top, text=self.t('dir')).pack(side='left')
        ttk.Entry(top, textvariable=self.root_dir).pack(side='left', fill='x', expand=True, padx=8)
        ttk.Button(top, text=self.t('browse'), command=self._browse).pack(side='left')

        preset = ttk.LabelFrame(frame, text=self.t('preset'), padding=10)
        preset.pack(fill='x', pady=10)
        for value, key in (('one', 'preset_one'), ('all', 'preset_all'), ('app', 'preset_app')):
            ttk.Radiobutton(preset, text=self.t(key), value=value, variable=self.preset, command=self._refresh).pack(
                anchor='w'
            )

        components = ttk.LabelFrame(frame, text=self.t('components'), padding=10)
        components.pack(fill='both', expand=True)
        for component in self.catalog.components.values():
            row = ttk.Frame(components)
            row.pack(fill='x', pady=1)
            asset = component.asset()
            variable = tk.BooleanVar(value=component.default and asset is not None)
            self.chosen[component.id] = variable
            if asset is None:
                ttk.Checkbutton(row, text=f'{component.id} — {component.summary}', state='disabled').pack(side='left')
            else:
                ttk.Checkbutton(
                    row,
                    text=f'{component.id} {component.version} — {component.summary}',
                    variable=variable,
                    command=self._refresh,
                ).pack(side='left')
                ttk.Label(row, text=human_size(asset.size)).pack(side='right')

        ttk.Label(frame, text=self.t('vpn')).pack(anchor='w', pady=(8, 0))
        ttk.Label(frame, text=self.t('license'), wraplength=760, foreground='#666').pack(anchor='w')
        self.size_label = ttk.Label(frame, text='')
        self.size_label.pack(anchor='w', pady=(8, 0))

        self.progress = ttk.Progressbar(frame, mode='determinate')
        self.progress.pack(fill='x', pady=(8, 4))
        self.status = ttk.Label(frame, text='')
        self.status.pack(anchor='w')
        self.log = tk.Text(frame, height=7, state='disabled')
        self.log.pack(fill='both', expand=True, pady=(6, 6))

        actions = ttk.Frame(frame)
        actions.pack(fill='x')
        self.install_button = ttk.Button(actions, text=self.t('install'), command=self._start)
        self.install_button.pack(side='left')
        self.cancel_button = ttk.Button(actions, text=self.t('cancel'), command=self._cancel, state='disabled')
        self.cancel_button.pack(side='left', padx=6)
        ttk.Button(actions, text=self.t('open'), command=self._open_folder).pack(side='right')
        self._refresh()

    def _refresh(self) -> None:
        selected = self._selected_ids()
        total = sum(self.catalog.get(item).asset().size for item in selected if self.catalog.get(item).asset())
        self.size_label.config(text=self.t('size', size=human_size(total)))

    def _selected_ids(self) -> list[str]:
        return _selected_ids(self.preset.get(), self.chosen, self.catalog)

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.root_dir.get() or str(Path.home()))
        if chosen:
            self.root_dir.set(chosen)

    def _open_folder(self) -> None:
        path = Path(self.root_dir.get())
        path.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            os.startfile(path)
        else:
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])

    def _say(self, line: str) -> None:
        self.log.configure(state='normal')
        self.log.insert('end', line + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    # ── install ─────────────────────────────────────────────────
    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        selected = self._selected_ids()
        if 'app' not in selected:
            messagebox.showwarning(self.t('title'), self.t('no_selection'))
            return
        root = Path(self.root_dir.get())
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / '.write-test'
            probe.write_text('ok', encoding='utf-8')
            probe.unlink()
        except OSError:
            messagebox.showerror(self.t('title'), self.t('need_admin'))
            return
        need = sum(self.catalog.get(item).asset().size for item in selected if self.catalog.get(item).asset())
        free = free_space(root)
        if free and free < need + 200 * 1024 * 1024:
            messagebox.showerror(self.t('title'), self.t('disk', free=human_size(free), need=human_size(need)))
            return
        self.cancel.clear()
        self.install_button.config(state='disabled')
        self.cancel_button.config(state='normal')
        self.progress.config(value=0, maximum=100)
        self.worker = threading.Thread(target=self._run_install, args=(root, selected), daemon=True)
        self.worker.start()

    def _run_install(self, root: Path, selected: list[str]) -> None:
        total = max(1, len(selected))
        for index, component_id in enumerate(selected):
            if self.cancel.is_set():
                self.message.put(('failed', 'cancelled'))
                return
            component = self.catalog.get(component_id)
            self.message.put(('status', self.t('installing', name=component_id)))
            self.message.put(('progress', int(index / total * 100)))
            try:

                def progress(done: int, size: int, start=index) -> None:
                    if size:
                        self.message.put(('progress', int((start + done / size) / total * 100)))

                install_component(self.catalog, component_id, root, progress=progress, cancel=self.cancel.is_set)
            except (InstallError, CatalogError, DownloadError, ManifestError, OSError) as exc:
                # A network failure is a DownloadError, which is not an OSError: without it here the
                # worker thread died silently and the window sat on "installing" with the button off.
                self.message.put(('failed', str(exc)))
                return
            self.message.put(('log', f'{component_id} {component.version} → {root}'))
        self.message.put(('progress', 100))
        self.message.put(('done', ''))

    # ── result ──────────────────────────────────────────────────
    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.message.get_nowait()
                if kind == 'progress':
                    self.progress.config(value=payload)
                elif kind == 'status':
                    self.status.config(text=payload)
                elif kind == 'log':
                    self._say(payload)
                elif kind == 'failed':
                    self._finish()
                    self.status.config(text=self.t('failed', err=payload))
                    messagebox.showerror(self.t('title'), self.t('failed', err=payload))
                elif kind == 'done':
                    self._finish()
                    self.status.config(text=self.t('done'))
                    self.after(200, self._doctor)
                elif kind == 'doctor':
                    self.status.config(text='')
                    self._doctor_window(payload)
        except queue.Empty:
            pass
        self.after(150, self._poll)

    def _finish(self) -> None:
        self.install_button.config(state='normal')
        self.cancel_button.config(state='disabled')

    def _cancel(self) -> None:
        self.cancel.set()
        self.status.config(text=self.t('cancel'))

    def _doctor(self) -> None:
        exe = Path(self.root_dir.get()) / 'app' / ('CaiXiHui.exe' if os.name == 'nt' else 'CaiXiHui')
        if not exe.exists():
            return
        self.status.config(text=self.t('doctor_running'))
        # The report is a subprocess of the packaged app (up to 90 s next to a live Ollama); it runs
        # off the UI thread so the window keeps painting, and comes back through the same queue.
        threading.Thread(target=self._doctor_worker, args=(exe, Path(self.root_dir.get())), daemon=True).start()

    def _doctor_worker(self, exe: Path, root: Path) -> None:
        env = dict(os.environ)
        env['CIXI_COMPONENTS_DIR'] = str(root / 'components')
        report: dict = {}
        try:
            result = subprocess.run([str(exe), '--doctor'], capture_output=True, timeout=90, check=False, env=env)
            text = (result.stdout or b'').decode('utf-8', errors='replace')
            # The launcher may print a note about the data root before the report (a fallback is
            # always stated aloud), so the JSON starts at the first brace rather than at byte 0.
            start = text.find('{')
            report = json.loads(text[start:]) if start >= 0 else {}
        except (OSError, subprocess.SubprocessError, ValueError):
            report = {}
        self.message.put(('doctor', report if isinstance(report, dict) else {}))

    def _doctor_window(self, report: dict) -> None:
        window = tk.Toplevel(self)
        window.title(self.t('doctor_title'))
        window.geometry('720x460')
        ttk.Label(window, text=self.t('doctor_head'), padding=12).pack(anchor='w')
        body = ttk.Frame(window, padding=12)
        body.pack(fill='both', expand=True)
        labels = STATE_LABEL[self.lang]
        rows = report.get('capabilities') or ()
        if not rows:
            ttk.Label(body, text=self.t('doctor_empty'), wraplength=660).pack(anchor='w')
        for row in rows:
            state = labels.get(row.get('state'), row.get('state'))
            label = row.get('label_text') or row.get('label_key')
            text = f'[{state}] {label}'
            if row.get('reason_key'):
                text += f' — {self._reason(row)}'
            ttk.Label(body, text=text, wraplength=660).pack(anchor='w', pady=1)
        buttons = ttk.Frame(window, padding=12)
        buttons.pack(fill='x')
        exe = Path(self.root_dir.get()) / 'app' / ('CaiXiHui.exe' if os.name == 'nt' else 'CaiXiHui')
        ttk.Button(buttons, text=self.t('launch'), command=lambda: self._launch(exe)).pack(side='left')
        ttk.Button(buttons, text=self.t('close'), command=window.destroy).pack(side='right')

    def _reason(self, row: dict) -> str:
        # The packaged app renders the sentence with its own catalogue; the installer keeps no
        # second copy of those words. A row without text (an older build) falls back to the key
        # and its parameters rather than inventing a sentence.
        text = row.get('reason_text')
        if text:
            return str(text)
        reason = str(row.get('reason_key') or '')
        params = row.get('reason_params') or {}
        return reason + (f' ({params})' if params else '')

    def _launch(self, exe: Path) -> None:
        env = dict(os.environ)
        env['CIXI_COMPONENTS_DIR'] = str(Path(self.root_dir.get()) / 'components')
        subprocess.Popen([str(exe)], cwd=str(exe.parent), env=env)
        self.destroy()


def main() -> int:
    app = Installer()
    app.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
