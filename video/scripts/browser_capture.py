#!/usr/bin/env python3
"""Capture real browser footage for the 采析绘 promo film.

The film is not a redrawn mockup: this script drives the running app in a real
Chrome, records the page through CDP ``Page.startScreencast`` and encodes the
frames into constant-frame-rate MP4 clips with ffmpeg.

Usage
-----
    python video/scripts/browser_capture.py                 # all scenes
    python video/scripts/browser_capture.py --only canvas   # one scene
    python video/scripts/browser_capture.py --list          # list scenes
    python video/scripts/browser_capture.py --headed        # show the browser

Output
------
    video/public/real/film/clip-<scene>.mp4
    video/public/real/film/manifest.json

The script starts its own Flask server on an isolated data root (a copy of the
project's datasets + the three showcase canvases), clears only that copy's run
records before the run scene, and never touches the checkout's ``data/``.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIDEO = ROOT / 'video'
DEFAULT_OUT = VIDEO / 'public' / 'real' / 'film'
DEFAULT_DATA_ROOT = VIDEO / '.data'
DEFAULT_PORT = 5099
DEFAULT_URL = f'http://127.0.0.1:{DEFAULT_PORT}/'

PROFILES = {
    'film': {
        'width': 1600,
        'height': 900,
        # 2x supersampling: text is rendered with far more pixels, so it stays
        # legible when the 2K film downsamples it (especially the 9:16 cut).
        'scale': 2.0,
        'label': 'Promo 16:9 source (1600x900 CSS @2.0 -> 3200x1800 supersampled)',
    },
}

CHROME_CANDIDATES = [
    os.environ.get('CIXI_BROWSER_BIN', ''),
    os.environ.get('CHROME_BIN', ''),
    os.environ.get('CHROME_PATH', ''),
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
]

FFMPEG_CANDIDATES = [
    os.environ.get('CIXI_FFMPEG', ''),
    os.environ.get('FFMPEG_BIN', ''),
    'ffmpeg',
]


# --------------------------------------------------------------------------
# Environment / HTTP helpers
# --------------------------------------------------------------------------
def find_chrome() -> str:
    for path in CHROME_CANDIDATES:
        if path and Path(path).is_file():
            return path
    for name in ('google-chrome', 'chromium', 'chrome', 'microsoft-edge'):
        found = shutil.which(name)
        if found:
            return found
    sys.exit('Chrome not found; set CHROME_BIN (or CIXI_BROWSER_BIN) to the executable.')


def find_ffmpeg() -> str:
    for path in FFMPEG_CANDIDATES:
        if path and Path(path).is_file():
            return path
        if path in ('ffmpeg',) and shutil.which(path):
            return shutil.which(path) or path
    sys.exit('ffmpeg not found; set CIXI_FFMPEG (or FFMPEG_BIN) to the executable.')


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def http_json(url: str, method: str = 'GET', body: dict | None = None, timeout: float = 15) -> dict:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def wait_server(url: str, timeout: float = 40) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            http_json(url.rstrip('/') + '/api/config', timeout=2)
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    raise RuntimeError(f'server {url} did not come up within {timeout:.0f}s')


def popen_kwargs() -> dict:
    if os.name == 'nt':
        return {'creationflags': 0x08000000}  # CREATE_NO_WINDOW
    return {'start_new_session': True}


def stop_process_tree(process: subprocess.Popen, log_path: Path) -> None:
    if process.poll() is not None:
        return
    try:
        import psutil
    except ImportError:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        return
    try:
        parent = psutil.Process(process.pid)
        for child in parent.children(recursive=True):
            with contextlib.suppress(psutil.NoSuchProcess):
                child.terminate()
        parent.terminate()
        _, alive = psutil.wait_procs([parent], timeout=5)
        for item in alive:
            with contextlib.suppress(psutil.NoSuchProcess):
                item.kill()
    except psutil.NoSuchProcess:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f'  ! could not stop server cleanly: {exc}; log: {log_path}')


# --------------------------------------------------------------------------
# Threaded CDP client
# --------------------------------------------------------------------------
class _Pending:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.msg: dict = {}


class CDP:
    """One reader thread, so a screencast can keep acking while actions run."""

    def __init__(self, ws_url: str) -> None:
        try:
            import websocket
        except ImportError:
            sys.exit('websocket-client is required: pip install websocket-client')
        self.ws = websocket.create_connection(ws_url, timeout=60, suppress_origin=True)
        self._send_lock = threading.Lock()
        self._lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._id = 0
        self._stop = threading.Event()
        self._capture = False
        self.frames: list[tuple[float, str]] = []
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _send(self, obj: dict) -> None:
        with self._send_lock:
            self.ws.send(json.dumps(obj))

    def _read(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self.ws.recv()
            except Exception:  # noqa: BLE001
                break
            if not raw:
                break
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if 'id' in msg:
                with self._lock:
                    pending = self._pending.pop(msg['id'], None)
                if pending is not None:
                    pending.msg = msg
                    pending.event.set()
            elif msg.get('method') == 'Page.screencastFrame':
                params = msg['params']
                self._send(
                    {'id': -1, 'method': 'Page.screencastFrameAck', 'params': {'sessionId': params['sessionId']}}
                )
                if self._capture:
                    self.frames.append((time.monotonic(), params['data']))

    def call(self, method: str, **params):
        self._id += 1
        mid = self._id
        pending = _Pending()
        with self._lock:
            self._pending[mid] = pending
        self._send({'id': mid, 'method': method, 'params': params})
        if not pending.event.wait(timeout=60):
            raise RuntimeError(f'CDP timeout: {method}')
        msg = pending.msg
        if 'error' in msg:
            raise RuntimeError(f'{method}: {msg["error"]}')
        return msg.get('result', {})

    def js(self, expression: str):
        result = self.call('Runtime.evaluate', expression=expression, returnByValue=True, awaitPromise=True)
        if 'exceptionDetails' in result:
            detail = result['exceptionDetails']
            text = detail.get('text', '')
            desc = (detail.get('exception') or {}).get('description', '')
            raise RuntimeError(f'JS exception: {text} {desc}\n  expression: {expression[:300]}')
        return result.get('result', {}).get('value')

    def close(self) -> None:
        self._stop.set()
        with contextlib.suppress(Exception):
            self.ws.close()


# --------------------------------------------------------------------------
# Browser wrapper
# --------------------------------------------------------------------------
class Browser:
    def __init__(self, url: str, profile: str, out: Path, headless: bool = True) -> None:
        self.url = url
        self.profile = profile
        self.meta = PROFILES[profile]
        self.width = int(self.meta['width'])
        self.height = int(self.meta['height'])
        self.scale = float(self.meta['scale'])
        self.out = out
        self.proc: subprocess.Popen | None = None
        self.profile_dir = Path(tempfile.mkdtemp(prefix='cxi-promo-'))
        self.chrome = find_chrome()

        args = [
            '--disable-gpu',
            '--hide-scrollbars',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-session-crashed-bubble',
            '--force-prefers-color-scheme=light',
            # F11-equivalent: kiosk hides every browser surface (tab strip, address
            # bar, border). The viewport is then exactly the recorded frame, so no
            # browser chrome ever appears in the film.
            '--kiosk',
            '--start-fullscreen',
            '--remote-debugging-port=0',
            f'--user-data-dir={self.profile_dir}',
            f'--window-size={self.width},{self.height}',
            '--remote-allow-origins=*',
            'about:blank',
        ]
        if headless:
            args.insert(0, '--headless=new')
        self.proc = subprocess.Popen(
            [self.chrome] + args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **popen_kwargs(),
        )
        port = self._devtools_port()
        tab = self._wait_for_page(port)
        self.target_id = tab.get('id', '')
        self.cdp = CDP(tab['webSocketDebuggerUrl'])
        self.cdp.call('Page.enable')
        self.cdp.call('Runtime.enable')
        self.cdp.call(
            'Emulation.setDeviceMetricsOverride',
            width=self.width,
            height=self.height,
            deviceScaleFactor=self.scale,
            mobile=False,
        )
        self.open(url)
        self.prepare_ui()
        print(f'  browser ready: {self.width}x{self.height} @{self.scale}x -> {self.out_w}x{self.out_h}')

    @property
    def out_w(self) -> int:
        return int(round(self.width * self.scale))

    @property
    def out_h(self) -> int:
        return int(round(self.height * self.scale))

    def _devtools_port(self, timeout: float = 30.0) -> int:
        marker = self.profile_dir / 'DevToolsActivePort'
        deadline = time.time() + timeout
        while time.time() < deadline:
            if marker.is_file():
                try:
                    return int(marker.read_text(encoding='utf-8').splitlines()[0].strip())
                except (OSError, ValueError, IndexError):
                    pass
            time.sleep(0.1)
        raise RuntimeError('Chrome did not publish a DevTools port')

    def _wait_for_page(self, port: int, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                tabs = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=1).read())
                for tab in tabs:
                    if tab.get('type') == 'page' and tab.get('webSocketDebuggerUrl'):
                        return tab
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.15)
        raise RuntimeError('Chrome did not become ready')

    # ---- page setup ------------------------------------------------------
    def _wait_ready(self) -> None:
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.cdp.js('document.readyState') == 'complete':
                break
            time.sleep(0.2)
        time.sleep(1.0)

    def open(self, url: str) -> None:
        self.cdp.call('Page.navigate', url=url)
        self._wait_ready()
        self.apply_film_style()

    def apply_film_style(self) -> None:
        """Re-inject after every navigation; a page load drops the old <style>.

        The top menu's CSS reserves 48px min-height but paints its buttons in the
        top 27px, leaving a 35px dead strip. Pin it open and collapse it to its
        content height so the film has a tight, honest header. Environment-only
        chrome (status text, collapse chevron, version badge) stays hidden.
        """
        style = (
            '#status-text, #pin-btn, #dirty-indicator, #app-version, #update-badge '
            '{visibility:hidden !important;}'
            # nowrap + natural height keeps every menu button on one line; a fixed
            # height clips the wrapped second row and a 48px min-height leaves a
            # 35px dead strip under the buttons.
            '#top-menu { flex-wrap:nowrap !important; min-height:0 !important; '
            'height:auto !important; padding:3px 10px !important; '
            'transform:none !important; align-content:center !important; '
            'justify-content:flex-start !important; gap:0 !important; }'
            '#top-menu .menu-group { padding:0 5px !important; }'
            '#top-menu .menu-btn, #top-menu .menu-label '
            '{ font-size:10px !important; padding:3px 7px !important; }'
            '#top-menu.pinned { transform:none !important; }'
        )
        self.js(
            "document.documentElement.setAttribute('data-theme','light');"
            "(() => { const m=document.getElementById('top-menu');"
            "if (m) m.classList.add('pinned');"
            "const old=document.getElementById('cxi-promo-style');"
            'if (old) old.remove();'
            "const s=document.createElement('style');"
            "s.id='cxi-promo-style'; s.textContent=" + json.dumps(style) + ';'
            'document.head.appendChild(s); })()'
        )

    def prepare_ui(self) -> None:
        """Chinese, light, and only the controls the story needs.

        The status text ("爬虫工作流服务启动，端口 …") is an environment fact, not a
        product fact; hiding it keeps the bottom bar quiet. The pin chevron is
        the menu's collapse control and is never part of the film's story.
        """
        with contextlib.suppress(Exception):
            self.js("localStorage.setItem('cxi.lang', 'zh');localStorage.setItem('lang', 'zh');")
        self.js("if (typeof setLang === 'function') setLang('zh');")
        self.apply_film_style()
        time.sleep(0.5)

    # ---- interactions ----------------------------------------------------
    def js(self, expression: str):
        return self.cdp.js(expression)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def wait_js(self, expression: str, timeout: float = 20.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.js(expression):
                    return True
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.15)
        return False

    def rect(self, selector: str) -> dict | None:
        expr = (
            '(() => { const e=document.querySelector(' + json.dumps(selector) + ');'
            'if (!e) return null;'
            "e.scrollIntoView({block:'center', inline:'center'});"
            'const r=e.getBoundingClientRect();'
            'return {x:r.left+r.width/2, y:r.top+r.height/2, w:r.width, h:r.height};'
            '})()'
        )
        return self.js(expr)

    def _mouse(self, kind: str, x: float, y: float, **extra) -> None:
        params = {'type': kind, 'x': x, 'y': y, **extra}
        self.cdp.call('Input.dispatchMouseEvent', **params)

    def move(self, x: float, y: float) -> None:
        self._mouse('mouseMoved', x, y, button='none')

    def click_at(self, x: float, y: float, settle: float = 0.4) -> None:
        self.move(x, y)
        time.sleep(0.06)
        self._mouse('mousePressed', x, y, button='left', clickCount=1)
        time.sleep(0.06)
        self._mouse('mouseReleased', x, y, button='left', clickCount=1)
        time.sleep(settle)

    def click(self, selector: str, settle: float = 0.5) -> bool:
        rect = self.rect(selector)
        if not rect:
            print(f'    ! missing control: {selector}')
            return False
        self.click_at(rect['x'], rect['y'], settle=settle)
        return True

    def click_button(self, root: str, text: str, settle: float = 0.6) -> bool:
        expr = (
            '(() => { const root=document.querySelector(' + json.dumps(root) + ');'
            'if (!root) return null;'
            "const buttons=Array.from(root.querySelectorAll('button'));"
            "const b=buttons.find(x=>((x.innerText||'').trim()).includes(" + json.dumps(text) + '));'
            'if (!b) return null;'
            "b.scrollIntoView({block:'center'});"
            'const r=b.getBoundingClientRect();'
            'return {x:r.left+r.width/2, y:r.top+r.height/2};'
            '})()'
        )
        rect = self.js(expr)
        if not rect:
            print(f'    ! missing button: {root} / {text}')
            return False
        self.click_at(rect['x'], rect['y'], settle=settle)
        return True

    def type_text(self, selector: str, text: str) -> None:
        self.js(
            '(() => { const e=document.querySelector(' + json.dumps(selector) + ');'
            'if (!e) return false; e.focus(); e.select && e.select(); return true; })()'
        )
        self.cdp.call('Input.insertText', text=text)
        time.sleep(0.4)

    def key(self, key: str) -> None:
        code = {'Enter': 13, 'Escape': 27, 'Tab': 9}.get(key, 0)
        self.cdp.call(
            'Input.dispatchKeyEvent', type='keyDown', key=key, windowsVirtualKeyCode=code, nativeVirtualKeyCode=code
        )
        self.cdp.call(
            'Input.dispatchKeyEvent', type='keyUp', key=key, windowsVirtualKeyCode=code, nativeVirtualKeyCode=code
        )
        time.sleep(0.25)

    def wheel(self, x: float, y: float, delta_y: float, ctrl: bool = False, settle: float = 0.05) -> None:
        self._mouse('mouseWheel', x, y, deltaX=0, deltaY=delta_y, modifiers=2 if ctrl else 0)
        time.sleep(settle)

    def drag(
        self, x1: float, y1: float, x2: float, y2: float, duration: float = 1.5, steps: int = 24, button: str = 'left'
    ) -> None:
        buttons = 1 if button == 'left' else 2
        self.move(x1, y1)
        time.sleep(0.08)
        self._mouse('mousePressed', x1, y1, button=button, buttons=buttons, clickCount=1)
        for i in range(1, steps + 1):
            t = i / steps
            x = x1 + (x2 - x1) * t
            y = y1 + (y2 - y1) * t
            self._mouse('mouseMoved', x, y, button=button, buttons=buttons)
            time.sleep(max(0.01, duration / steps))
        self._mouse('mouseReleased', x2, y2, button=button, buttons=0, clickCount=1)
        time.sleep(0.3)

    # ---- app helpers -----------------------------------------------------
    def load_workflow(self, name: str) -> None:
        url = self.url.rstrip('/') + '/?workflow=' + urllib.parse.quote(name) + '&layout=1'
        self.cdp.call('Page.navigate', url=url)
        self._wait_ready()
        if not self.wait_js(
            "typeof canvas !== 'undefined' && canvas.nodes && Object.keys(canvas.nodes).length > 0", timeout=25
        ):
            raise RuntimeError(f'workflow {name} did not load')
        # The AI workspace and docked panels keep their open state across page
        # loads. Close them so a later scene never inherits the previous one's
        # UI (e.g. an open AI chat leaking into the graph records scene).
        self.js(
            '(() => {'
            "try { if (typeof AIWorkspace !== 'undefined' && AIWorkspace.close) AIWorkspace.close(); } catch (e) {}"
            'document.querySelectorAll(\'#ai-workspace.open, [id$="-panel"].open\').forEach(function (e) {'
            "e.classList.remove('open');});"
            '})()'
        )
        self.apply_film_style()
        time.sleep(1.4)

    def node_gear(self, node_id: str, settle: float = 0.8) -> bool:
        return self.click(f'[data-node-id="{node_id}"] .node-action-btn', settle=settle)

    def wait_run(self, timeout: float = 90) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = http_json(self.url.rstrip('/') + '/api/workflow/status')
            if not status.get('running') and not status.get('settling'):
                return status
            time.sleep(0.5)
        raise RuntimeError(f'run did not settle within {timeout:.0f}s')

    def settings_ready(self, timeout: float = 12) -> bool:
        return self.wait_js("!!document.querySelector('#node-settings.open')", timeout)

    def open_chart(self, node_id: str) -> None:
        if not self.node_gear(node_id):
            raise RuntimeError(f'chart node {node_id} has no gear')
        if not self.settings_ready():
            raise RuntimeError('node settings did not open')
        if not self.click_button('#node-settings', '预览图表', settle=0.8):
            raise RuntimeError('preview-chart button missing')
        self.wait_js("!!document.querySelector('#chart-preview-panel.open')", timeout=15)
        time.sleep(2.2)  # let the chart paint
        self.click_button('#chart-preview-panel', '全屏', settle=1.0)
        self.wait_js("!!document.querySelector('#chart-fullscreen-panel.open')", timeout=15)
        time.sleep(1.6)

    def open_data_preview(self, node_id: str) -> None:
        if not self.node_gear(node_id):
            raise RuntimeError(f'node {node_id} has no gear')
        if not self.settings_ready():
            raise RuntimeError('node settings did not open')
        if not self.click_button('#node-settings', '预览数据', settle=0.8):
            raise RuntimeError('preview-data button missing')
        self.wait_js("!!document.querySelector('#data-preview-panel.open')", timeout=15)
        time.sleep(1.0)
        rect = self.js(
            "(() => { const h=document.querySelector('#data-preview-panel .resize-handle');"
            'if (!h) return null; const r=h.getBoundingClientRect();'
            'return {x:r.left+r.width/2, y:r.top+r.height/2}; })()'
        )
        if rect:
            self.drag(rect['x'], rect['y'], rect['x'] - 360, rect['y'], duration=1.2, steps=20)
            time.sleep(0.6)

    # ---- capture ---------------------------------------------------------
    def shot_rect(self, selector: str, pad: int = 8, ratio: float | None = 16 / 9) -> dict:
        """A CDP clip rectangle framing a real panel for a local shot.

        The crop is expanded to the film's aspect ratio around the panel's centre,
        so the still fills the frame with `cover` without shrinking (blurring) or
        cropping away the very content it demonstrates. Coordinates come from the
        live DOM, never hardcoded; clamped to the viewport.
        """
        rect = self.js(
            '(() => { const e=document.querySelector(' + json.dumps(selector) + ');'
            'if (!e) return null;'
            'const r=e.getBoundingClientRect();'
            'if (r.width < 20 || r.height < 20) return null;'
            'const p=' + str(pad) + ', ratio=' + json.dumps(ratio) + ';'
            'let x=r.left-p, y=r.top-p, w=r.width+2*p, h=r.height+2*p;'
            'if (ratio) { if (w/h < ratio) { const nw=h*ratio; x-=(nw-w)/2; w=nw; }'
            'else { const nh=w/ratio; y-=(nh-h)/2; h=nh; } }'
            'x=Math.max(0, Math.min(x, innerWidth-1));'
            'y=Math.max(0, Math.min(y, innerHeight-1));'
            'w=Math.min(w, innerWidth-x); h=Math.min(h, innerHeight-y);'
            'return {x,y,width:w,height:h}; })()'
        )
        if not rect:
            raise RuntimeError(f'panel not found or too small: {selector}')
        return rect

    def shot(self, name: str, clip: dict | None = None) -> Path:
        region = clip or {'x': 0, 'y': 0, 'width': self.width, 'height': self.height}
        data = self.cdp.call(
            'Page.captureScreenshot',
            format='png',
            captureBeyondViewport=False,
            clip={**region, 'scale': self.scale},
        )
        self.out.mkdir(parents=True, exist_ok=True)
        path = self.out / name
        path.write_bytes(base64.b64decode(data['data']))
        out_w = int(round(region['width'] * self.scale))
        out_h = int(round(region['height'] * self.scale))
        print(f'    {path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB  {out_w}x{out_h}')
        return path

    def record(self, name: str, actions: Callable[[Browser], None], fps: int = 30, keep_frames: bool = False) -> Path:
        frames = Path(tempfile.mkdtemp(prefix='cxi-frames-'))
        self.cdp.frames.clear()
        self.cdp._capture = True
        try:
            self.cdp.call(
                'Page.startScreencast',
                # PNG frames are lossless: the only compression is the final x264
                # pass, so text stays as crisp as the stills in real/film/.
                format='png',
                everyNthFrame=1,
                maxWidth=self.out_w,
                maxHeight=self.out_h,
            )
            t0 = time.monotonic()
            actions(self)
            time.sleep(0.5)
            self.cdp.call('Page.stopScreencast')
            self.cdp._capture = False
            time.sleep(0.2)
            frames_got = sorted(self.cdp.frames)
        except Exception:
            self.cdp._capture = False
            raise

        if len(frames_got) < 2:
            raise RuntimeError(f'only {len(frames_got)} frames for {name}')

        lines: list[str] = []
        for i, (ts, data) in enumerate(frames_got):
            (frames / f'frame-{i:05d}.png').write_bytes(base64.b64decode(data))
            duration = frames_got[i + 1][0] - ts if i + 1 < len(frames_got) else 0.8
            duration = max(0.01, min(duration, 30.0))
            lines.append(f"file 'frame-{i:05d}.png'\nduration {duration:.4f}")
        lines.append(f"file 'frame-{len(frames_got) - 1:05d}.png'")
        (frames / 'list.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')

        self.out.mkdir(parents=True, exist_ok=True)
        target = self.out / name
        subprocess.run(
            [
                find_ffmpeg(),
                '-y',
                '-loglevel',
                'error',
                '-f',
                'concat',
                '-safe',
                '0',
                '-i',
                'list.txt',
                '-vf',
                f'fps={fps},scale={self.out_w}:{self.out_h},format=yuv420p',
                '-c:v',
                'libx264',
                '-preset',
                'slow',
                '-crf',
                '12',
                '-movflags',
                '+faststart',
                str(target),
            ],
            cwd=str(frames),
            check=True,
        )
        duration = max(ts - t0 for ts, _ in frames_got)
        print(
            f'    {target.relative_to(ROOT)}  {target.stat().st_size // 1024} KB  '
            f'{self.out_w}x{self.out_h}  ~{duration:.1f}s  {len(frames_got)} frames'
        )
        if keep_frames:
            kept = self.out / (Path(name).stem + '-frames')
            if kept.exists():
                shutil.rmtree(kept)
            shutil.move(str(frames), str(kept))
        else:
            shutil.rmtree(frames, ignore_errors=True)
        return target

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.cdp.close()
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                self.proc.kill()
        shutil.rmtree(self.profile_dir, ignore_errors=True)


# --------------------------------------------------------------------------
# Server / data root
# --------------------------------------------------------------------------
SHOWCASE_WORKFLOWS = ('showcase_biblio', 'showcase_sentiment', 'showcase_xhs')


def copy_sqlite(source: Path, target: Path) -> None:
    """Copy a live SQLite store with its WAL, not just the main file.

    The demo root keeps the CNKI datasets the bibliometrics canvas references;
    a plain file copy can miss rows still sitting in ``-wal``. SQLite's own
    backup API produces a consistent single file that the server then opens.
    """
    import sqlite3

    src = sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True)
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def prepare_data_root(source_root: Path, data_root: Path) -> None:
    """Copy only what the film reads: the dataset store and three canvases."""
    dest = data_root / 'data'
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    (dest / 'workflows').mkdir(parents=True, exist_ok=True)
    # The bibliometrics canvas references the CNKI datasets imported into the
    # showcase demo root; prefer that store when it exists (it is a superset of
    # the checkout's data/datasets.db). Fall back to the checkout's store.
    demo_store = ROOT / 'scratchpad' / 'demo_showcase_root' / 'data' / 'datasets.db'
    store = demo_store if demo_store.is_file() else source_root / 'datasets.db'
    if store.is_file():
        copy_sqlite(store, dest / 'datasets.db')
        print(f'  datasets: {store.relative_to(ROOT)}')
    for name in ('model_registry.json',):
        for candidate in (ROOT / 'scratchpad' / 'demo_showcase_root' / 'data' / name, source_root / name):
            if candidate.is_file():
                shutil.copy2(candidate, dest / name)
                break
    for name in SHOWCASE_WORKFLOWS:
        src = ROOT / 'samples' / 'workflows' / 'templates' / f'{name}.json'
        if not src.is_file():
            raise FileNotFoundError(f'missing showcase template: {src}')
        shutil.copy2(src, dest / 'workflows' / f'{name}.json')

    # A saved canvas only runs if its Upload nodes' datasets exist. The biblio
    # canvas references the four CNKI exports that live in the showcase demo
    # root; refuse by name instead of filming a red "尚未上传文件" run.
    required: set[str] = set()
    for name in SHOWCASE_WORKFLOWS:
        data = json.loads((dest / 'workflows' / f'{name}.json').read_text(encoding='utf-8'))
        for node in data.get('nodes', []):
            if node.get('type') == 'upload':
                dataset_id = str((node.get('params') or {}).get('dataset_id') or '')
                if dataset_id:
                    required.add(dataset_id)
    store = dest / 'datasets.db'
    if not store.is_file():
        raise RuntimeError(f'no dataset store at {store}; prepare the showcase data root first')
    if required:
        import sqlite3

        conn = sqlite3.connect(str(store))
        present = {row[0] for row in conn.execute('select dataset_id from datasets')}
        conn.close()
        missing = sorted(required - present)
        if missing:
            raise RuntimeError(
                'showcase datasets missing: '
                + ', '.join(missing)
                + '; run tools/record_demo.py --group showcase --no-record to build '
                + str(ROOT / 'scratchpad' / 'demo_showcase_root')
            )

    # Seed hundreds of real comments (sampled from the project's own Weibo
    # corpus) into the demo dataset, so data/analysis scenes show an honest
    # few-hundred-row table being scrolled / labelled, not a 24-row stub.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import make_demo_data

        n = make_demo_data.seed(store, n=600)
        print(f'  demo dataset: {n} real comments')
    finally:
        sys.path.pop(0)
    print(f'  data root ready: {dest}')


def start_server(data_root: Path, port: int) -> tuple[subprocess.Popen, Path]:
    log_path = data_root / 'server.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        {
            'CRAWLER_DATA_ROOT': str(data_root),
            'PORT': str(port),
            'HOST': '127.0.0.1',
            'CIXI_DEMO_AUTORUN': '1',
            'PYTHONUNBUFFERED': '1',
            'PYTHONIOENCODING': 'utf-8',
        }
    )
    with log_path.open('ab') as log:
        process = subprocess.Popen(
            [sys.executable, 'app.py'],
            cwd=str(ROOT / 'backend'),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            **popen_kwargs(),
        )
    wait_server(f'http://127.0.0.1:{port}/')
    print(f'  server ready on 127.0.0.1:{port} (log: {log_path.relative_to(ROOT)})')
    return process, log_path


def newest_report(url: str) -> str:
    """Return the newest .html report name, or '' when none exists.

    ``/api/exports/list`` is ordered newest-first by the server; only the name is
    used, so the report viewer's own route stays the single opener.
    """
    try:
        listing = http_json(url.rstrip('/') + '/api/exports/list?limit=200')
    except Exception:  # noqa: BLE001
        return ''
    for row in listing.get('exports') or []:
        name = row.get('name') or ''
        if name.endswith('.html'):
            return name
    return ''


# --------------------------------------------------------------------------
# Scenes
# --------------------------------------------------------------------------
def prepare_canvas(b: Browser) -> None:
    # Navigate BEFORE the screencast starts: a cross-document load ends it.
    b.load_workflow('showcase_xhs')
    b.sleep(1.5)


def s_canvas(b: Browser) -> None:
    # Hold the whole canvas briefly, then zoom INTO the node-dense area and stay
    # there: node text is the point of this scene, so it must be readable, not a
    # shrunken 74% overview. A real mouse wheel reaches the canvas handler; a
    # synthetic ctrl+wheel with no focused element does not.
    b.move(800, 470)
    b.sleep(0.8)
    for _ in range(14):
        b.wheel(800, 470, -50, ctrl=True, settle=0.18)
    b.sleep(1.5)
    b.drag(760, 500, 600, 440, duration=2.6, steps=30, button='right')
    b.sleep(1.0)
    b.drag(600, 440, 900, 520, duration=3.0, steps=34, button='right')
    b.sleep(1.5)


def s_data_scroll(b: Browser) -> None:
    """Click the preview's real "next page" control to page through the 600 rows."""
    b.sleep(0.8)
    for _ in range(4):
        b.click_button('#data-preview-panel', '下一页', settle=0.9)
        b.sleep(0.4)
    b.sleep(1.0)


def prepare_data(b: Browser) -> None:
    b.load_workflow('showcase_sentiment')
    # Preview the Upload node: its dataset needs no run, so the table is real
    # even on a fresh data root. The process node's result would need a run.
    b.open_data_preview('node-2')
    b.js("if (typeof closeSettings === 'function') closeSettings();")
    b.sleep(1.0)
    b.shot('still-data.png', clip=b.shot_rect('#data-preview-panel', pad=6))


def prepare_parameters(b: Browser) -> None:
    b.load_workflow('showcase_sentiment')
    b.node_gear('node-3')
    b.settings_ready()
    b.sleep(1.0)
    b.shot('still-parameters.png', clip=b.shot_rect('#node-settings', pad=6))


def prepare_run(b: Browser) -> None:
    # The run scene owns a fresh ledger: the film must show this take executing,
    # not a previous run's results restored from disk.
    http_json(b.url.rstrip('/') + '/api/runs/clear', method='POST', body={'confirm': True})
    b.load_workflow('showcase_biblio')
    b.sleep(0.8)


def s_run(b: Browser) -> None:
    b.move(880, 500)
    b.click('#btn-execute', settle=0.5)
    b.sleep(1.5)
    b.click('#btn-console', settle=0.8)
    b.wait_run(timeout=90)
    # A finished multi-chart run opens the dashboard on its own; give its six
    # ECharts cells a resize and a paint before the shot.
    b.wait_js("!!document.querySelector('#dashboard-panel.open')", timeout=10)
    b.js("window.dispatchEvent(new Event('resize'))")
    b.sleep(3.5)


def prepare_graph(b: Browser) -> None:
    b.load_workflow('showcase_biblio')
    b.open_chart('node-8')
    b.sleep(0.8)
    b.shot('still-graph.png')


def prepare_timeline(b: Browser) -> None:
    b.load_workflow('showcase_biblio')
    b.open_chart('node-9')
    b.sleep(0.8)
    b.shot('still-timeline.png')


def prepare_records(b: Browser) -> None:
    b.load_workflow('showcase_biblio')
    b.click('#btn-runs', settle=1.2)
    b.click('#runs-tabs .runs-tab:nth-child(2)', settle=0.8)
    b.wait_js("document.querySelectorAll('#runs-panel button').length > 4", timeout=12)
    b.sleep(0.8)
    b.shot('still-records.png')


def prepare_report(b: Browser) -> None:
    b.load_workflow('showcase_biblio')
    # The status-bar Report button belongs to the live canvas; after a reload the
    # stored run is the honest source, so open it from its run record instead.
    b.click('#btn-runs', settle=1.2)
    b.click('#runs-tabs .runs-tab:nth-child(2)', settle=0.8)
    b.wait_js("document.querySelectorAll('#runs-panel button').length > 4", timeout=12)
    b.sleep(0.6)
    if not b.click_button('#runs-panel', '报告', settle=0.8):
        raise RuntimeError('run-record report button missing')
    if not b.wait_js(
        "(() => { const i=document.querySelector('#dialog-input');"
        "const o=document.querySelector('#dialog-overlay');"
        "return !!i && !!o && getComputedStyle(o).display !== 'none'; })()",
        timeout=15,
    ):
        raise RuntimeError('report dialog did not open')
    b.type_text('#dialog-input', '数字媒介中的大学生恋爱与亲密关系 · 文献计量')
    b.sleep(0.8)
    b.shot('still-report-dialog.png')
    # Generate the real file for the report-page still; this happens before the
    # still scenes, so reportpage can find it.
    b.click_button('#dialog-actions', '生成 Html 报告', settle=0.8)
    for _ in range(60):
        if newest_report(b.url):
            break
        b.sleep(0.5)
    else:
        raise RuntimeError('report generation produced no .html file')


def prepare_reportpage(b: Browser) -> None:
    """Open the report viewer and take one real still before recording anything."""
    # The report dialog opens the new report with window.open; that tab takes
    # the foreground and the original tab's screencast then paints ~1 frame/s.
    # Close the extra page targets and put the recorded tab back in front.
    try:
        targets = b.cdp.call('Target.getTargets').get('targetInfos', [])
        for target in targets:
            if target.get('type') == 'page' and target.get('targetId') != b.target_id:
                b.cdp.call('Target.closeTarget', targetId=target['targetId'])
        if b.target_id:
            b.cdp.call('Target.activateTarget', targetId=b.target_id)
    except Exception:  # noqa: BLE001
        pass
    name = ''
    for _ in range(60):
        name = newest_report(b.url)
        if name:
            break
        b.sleep(0.5)
    if not name:
        raise RuntimeError('no .html report found after the report scene')
    b.cdp.call('Page.navigate', url=b.url.rstrip('/') + '/api/report/view?name=' + urllib.parse.quote(name))
    b._wait_ready()
    b.sleep(1.5)
    b.js('window.scrollTo(0, 0)')
    b.sleep(0.6)
    b.shot('still-report.png')


def prepare_covernodes(b: Browser) -> None:
    """A real canvas view for the cover: nodes and wires, not an invented diagram."""
    b.load_workflow('showcase_biblio')
    b.move(820, 460)
    # Zoom in a little so nodes and wires read clearly in the cover's small window.
    for _ in range(3):
        b.wheel(820, 460, -30, ctrl=True, settle=0.12)
    b.sleep(1.0)
    b.shot('still-covernodes.png')


def prepare_ai(b: Browser) -> None:
    b.load_workflow('showcase_xhs')
    b.click('#btn-ai-workspace', settle=1.4)
    b.wait_js("!!document.querySelector('#ai-workspace.open')", timeout=15)
    b.sleep(1.0)
    b.shot('still-ai.png')


def prepare_ai_chat(b: Browser) -> None:
    """Open the AI workspace on local Ollama, ready to send a real question."""
    b.load_workflow('showcase_xhs')
    b.click('#btn-ai-workspace', settle=1.4)
    b.wait_js("!!document.querySelector('#ai-workspace.open')", timeout=15)
    b.sleep(0.8)
    # Switch provider to local Ollama (no API key needed — a real local model).
    b.js(
        "(() => { const s=document.getElementById('ai-ws-provider');"
        "const o=Array.from(s.options).find(x=>x.text.includes('Ollama'));"
        "if(o){ s.value=o.value; s.dispatchEvent(new Event('change',{bubbles:true})); } })()"
    )
    b.sleep(2.0)
    # Type a real question about the loaded canvas.
    b.js("(() => { const t=document.getElementById('ai-input'); t.focus(); })()")
    b.cdp.call('Input.insertText', text='用一句话说明这个画布在做什么？')
    b.sleep(0.5)


def s_ai_chat(b: Browser) -> None:
    """Compose the AI demo from two real frames: the question sent, and the
    finished local-model answer. The minutes of "generating..." waiting are cut
    out — only the two meaningful moments are joined with a short crossfade.
    Writes clip-ai-chat.mp4 directly (a compose scene, no screencast).
    """
    tmp = Path(tempfile.mkdtemp(prefix='cxi-ai-'))
    try:
        ask = tmp / 'ask.png'
        answer = tmp / 'answer.png'
        # Frame 1: the question, just sent (start generating).
        b.click('#ai-send-btn', settle=0.4)
        b.sleep(0.6)
        # shot() writes into b.out, so capture there then move into the temp dir.
        b.out.mkdir(parents=True, exist_ok=True)
        b.shot('ai-ask-frame.png')
        shutil.copy2(b.out / 'ai-ask-frame.png', ask)
        (b.out / 'ai-ask-frame.png').unlink(missing_ok=True)

        # Wait until the answer is fully settled (text stops growing).
        deadline = time.time() + 150
        last_len = 0
        stable = 0
        while time.time() < deadline:
            b.sleep(1.0)
            cur = b.js("document.getElementById('ai-workspace').innerText.length")
            if cur > 800:
                if cur == last_len:
                    stable += 1
                    if stable >= 4:
                        break
                else:
                    stable = 0
                last_len = cur
        b.sleep(1.0)

        # Frame 2: the finished answer.
        b.shot('ai-answer-frame.png')
        shutil.copy2(b.out / 'ai-answer-frame.png', answer)
        (b.out / 'ai-answer-frame.png').unlink(missing_ok=True)

        # Join: 3s on the question, 0.6s crossfade, then hold the answer.
        target = b.out / 'clip-ai-chat.mp4'
        subprocess.run(
            [
                find_ffmpeg(),
                '-y',
                '-loglevel',
                'error',
                '-loop',
                '1',
                '-t',
                '3.6',
                '-i',
                str(ask),
                '-loop',
                '1',
                '-t',
                '9',
                '-i',
                str(answer),
                '-filter_complex',
                '[0:v]scale=3200:1800,setsar=1,fps=30[a];'
                '[1:v]scale=3200:1800,setsar=1,fps=30[b];'
                '[a][b]xfade=transition=fade:duration=0.6:offset=3[v]',
                '-map',
                '[v]',
                '-c:v',
                'libx264',
                '-preset',
                'slow',
                '-crf',
                '12',
                '-pix_fmt',
                'yuv420p',
                '-movflags',
                '+faststart',
                str(target),
            ],
            check=True,
        )
        print(
            f'    {target.relative_to(ROOT)}  {target.stat().st_size // 1024} KB  '
            'composed from 2 real frames (waiting removed)'
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def prepare_source(b: Browser) -> None:
    """A Data Source node's settings: the platform list, engine (incl. CatBus),
    modes and account. One real panel covers both 9-platform collection and CatBus.
    """
    b.load_workflow('showcase_xhs')
    # Add a source node via the palette (a real in-app action) so we can open its
    # honest settings; no showcase template ships a source node.
    b.js(
        "(() => { if (typeof canvas!=='undefined' && canvas.addNode) {"
        "canvas.addNode('source', 700, 300); return true; } return false; })()"
    )
    b.sleep(1.0)
    src = b.js(
        "(() => { const k=Object.keys(canvas.nodes).find(id=>canvas.nodes[id].type==='source');return k || ''; })()"
    )
    if not src:
        raise RuntimeError('could not add a source node')
    b.node_gear(src)
    b.settings_ready()
    b.sleep(1.2)
    b.shot('still-source.png', clip=b.shot_rect('#node-settings', pad=6))


def prepare_source_platforms(b: Browser) -> None:
    """Same panel with the platform <select> expanded, showing the whole list."""
    prepare_source(b)
    # Expand the platform dropdown (native select -> click opens the option list).
    rect = b.js(
        "(() => { const p=document.querySelector('#node-settings select');"
        'if(!p) return null; const r=p.getBoundingClientRect();'
        'return {x:r.left+r.width/2,y:r.top+r.height/2}; })()'
    )
    if rect:
        b.click_at(rect['x'], rect['y'], settle=0.6)
        b.sleep(0.5)
    b.shot('still-source-platforms.png')


def prepare_datasets(b: Browser) -> None:
    b.load_workflow('showcase_biblio')
    b.click('#btn-datasets', settle=1.2)
    b.sleep(1.0)
    b.shot('still-datasets.png', clip=b.shot_rect('#dataset-panel', pad=6))


def prepare_exports(b: Browser) -> None:
    b.load_workflow('showcase_biblio')
    b.click('#btn-exports', settle=1.2)
    b.sleep(1.0)
    b.shot('still-exports.png', clip=b.shot_rect('#exports-panel', pad=6))


def prepare_schedules(b: Browser) -> None:
    b.load_workflow('showcase_biblio')
    b.click('#btn-schedules-dock', settle=1.2)
    b.sleep(1.0)
    b.shot('still-schedules.png', clip=b.shot_rect('#schedules-panel', pad=6))


def prepare_dashboard(b: Browser) -> None:
    b.load_workflow('showcase_xhs')
    b.js("if (typeof dashboard!=='undefined' && dashboard.open) dashboard.open();")
    b.sleep(2.5)
    b.js("window.dispatchEvent(new Event('resize'))")
    b.sleep(1.2)
    b.shot('still-dashboard.png', clip=b.shot_rect('#dashboard-panel', pad=6))


def prepare_biblio(b: Browser) -> None:
    b.load_workflow('showcase_biblio')
    b.click('#btn-biblio-dock', settle=1.2)
    b.sleep(1.0)
    b.shot('still-biblio.png', clip=b.shot_rect('#biblio-panel', pad=6))


def prepare_settings(b: Browser) -> None:
    """Settings panel: model provider / account & exit pools live here."""
    b.load_workflow('showcase_xhs')
    b.click('#btn-settings', settle=1.4)
    b.wait_js("!!document.querySelector('#settings-panel.open')", timeout=12)
    b.sleep(1.0)
    b.shot('still-settings.png', clip=b.shot_rect('#settings-panel', pad=6))


SCENES: dict[str, Callable[[Browser], None]] = {
    'canvas': s_canvas,
    'data-scroll': s_data_scroll,
    'run': s_run,
}

# A compose scene writes its own clip from real screenshots (no screencast):
# the AI demo joins the "question sent" and "answer finished" frames, cutting
# the long model-waiting interval entirely.
COMPOSE: dict[str, Callable[[Browser], None]] = {
    'ai-chat': s_ai_chat,
}

# A scene that is a real page still, not a screencast: a static panel paints one
# frame, and a screencast would have nothing to move. The film pans/zooms these
# stills; the pixels are still the app's own.
STILL_SCENES: dict[str, str] = {
    'covernodes': 'still-covernodes.png',
    'source': 'still-source.png',
    'source-platforms': 'still-source-platforms.png',
    'parameters': 'still-parameters.png',
    'datasets': 'still-datasets.png',
    'exports': 'still-exports.png',
    'schedules': 'still-schedules.png',
    'settings': 'still-settings.png',
    'dashboard': 'still-dashboard.png',
    'graph': 'still-graph.png',
    'timeline': 'still-timeline.png',
    'records': 'still-records.png',
    'biblio': 'still-biblio.png',
    'report': 'still-report-dialog.png',
    'reportpage': 'still-report.png',
    'ai': 'still-ai.png',
}

# A scene that needs a different document prepares it BEFORE the screencast:
# a cross-document navigation during recording ends the screencast.
PREPARE: dict[str, Callable[[Browser], None]] = {
    'canvas': prepare_canvas,
    'ai-chat': prepare_ai_chat,
    'covernodes': prepare_covernodes,
    'source': prepare_source,
    'source-platforms': prepare_source_platforms,
    'data-scroll': prepare_data,
    'parameters': prepare_parameters,
    'run': prepare_run,
    'datasets': prepare_datasets,
    'exports': prepare_exports,
    'schedules': prepare_schedules,
    'settings': prepare_settings,
    'dashboard': prepare_dashboard,
    'graph': prepare_graph,
    'timeline': prepare_timeline,
    'records': prepare_records,
    'biblio': prepare_biblio,
    'report': prepare_report,
    'reportpage': prepare_reportpage,
    'ai': prepare_ai,
}


def capture(
    url: str,
    out: Path,
    only: list[str] | None,
    headless: bool,
    keep_frames: bool,
    fps: int,
    data_root: Path | None,
    server: tuple[subprocess.Popen, Path] | None,
) -> None:
    all_keys = list(SCENES) + [k for k in STILL_SCENES if k not in SCENES] + [k for k in COMPOSE if k not in SCENES]
    selected = [k for k in all_keys if only is None or k in only]
    if not selected:
        print('  no matching scenes')
        return
    browser = Browser(url, 'film', out, headless=headless)
    manifest: dict = {'profile': 'film', 'width': browser.out_w, 'height': browser.out_h, 'scenes': []}
    try:
        for key in selected:
            print(f'  scene: {key}')
            prepare = PREPARE.get(key)
            if prepare is not None:
                prepare(browser)
            if key in STILL_SCENES:
                manifest['scenes'].append({'key': key, 'kind': 'still', 'file': STILL_SCENES[key], 'seconds': 0})
                continue
            if key in COMPOSE:
                start = time.monotonic()
                COMPOSE[key](browser)
                manifest['scenes'].append(
                    {
                        'key': key,
                        'kind': 'compose',
                        'file': f'clip-{key}.mp4',
                        'seconds': round(time.monotonic() - start, 2),
                    }
                )
                continue
            start = time.monotonic()
            browser.record(f'clip-{key}.mp4', SCENES[key], fps=fps, keep_frames=keep_frames)
            manifest['scenes'].append(
                {
                    'key': key,
                    'file': f'clip-{key}.mp4',
                    'seconds': round(time.monotonic() - start, 2),
                }
            )
    finally:
        browser.close()
        out.mkdir(parents=True, exist_ok=True)
        (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if server is not None:
            stop_process_tree(*server)
            print('  server stopped')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--profile', choices=sorted(PROFILES), default='film')
    parser.add_argument('--url', default=None, help='existing server URL (implies --no-server)')
    parser.add_argument('--port', type=int, default=0, help='server port; 0 picks a free one (default)')
    parser.add_argument(
        '--source-root', type=Path, default=ROOT / 'data', help='read datasets/model registry from here'
    )
    parser.add_argument(
        '--data-root', type=Path, default=DEFAULT_DATA_ROOT, help='isolated data root for the capture server'
    )
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--only', default=None, help='comma-separated scene keys')
    parser.add_argument('--list', action='store_true', help='list scenes and exit')
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--no-server', action='store_true', help='use --url instead of starting a server')
    parser.add_argument('--keep-data', action='store_true', help='reuse video/.data instead of re-preparing it')
    parser.add_argument('--headed', action='store_true')
    parser.add_argument('--keep-frames', action='store_true')
    args = parser.parse_args()

    if args.list:
        for key in SCENES:
            print(f'{key:12s} clip')
        for key in STILL_SCENES:
            print(f'{key:12s} still')
        for key in COMPOSE:
            print(f'{key:12s} compose')
        return 0

    if args.url:
        url = args.url.rstrip('/') + '/'
        server = None
        data_root = None
    else:
        if args.no_server:
            sys.exit('--no-server needs --url')
        data_root = args.data_root.resolve()
        if args.keep_data:
            if not (data_root / 'data').is_dir():
                sys.exit(f'--keep-data: {data_root} has no data/ to reuse')
            print(f'  reusing data root: {data_root}')
        else:
            prepare_data_root(args.source_root.resolve(), data_root)
        port = args.port or free_port()
        server = start_server(data_root, port)
        url = f'http://127.0.0.1:{port}/'

    only = [s.strip() for s in args.only.split(',')] if args.only else None
    try:
        capture(url, args.out.resolve(), only, not args.headed, args.keep_frames, args.fps, data_root, server)
    except Exception:
        if server is not None:
            stop_process_tree(*server)
        raise
    return 0


if __name__ == '__main__':
    sys.exit(main())
