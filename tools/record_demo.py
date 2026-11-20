"""Reusable demo runner + recorder.

One command runs the demos listed in ``samples/workflows/manifest.json`` in one data root at a time,
starts/stops its own Flask server, opens the page in a REAL browser, captures that browser WINDOW
(not the host window), and saves one MP4 per demo. Re-run this script after any UI change; nothing
is hand-assembled any more.

Usage:
    python tools/record_demo.py --group model --demo demo1
    python tools/record_demo.py --group showcase
    python tools/record_demo.py --group model --no-record       # just verify the runs
"""

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import psutil
import requests
from demo_capture import CaptureUnavailableError, capture_command, ffmpeg_binary, find_window, focus_window

REPO = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO / 'samples' / 'workflows' / 'manifest.json'
VIDEOS = REPO / 'samples' / 'workflows' / 'videos'
BROWSER_NAMES = {'chrome', 'msedge', 'firefox', 'chromium'}


def _browser_pids() -> set[int]:
    return {
        process.pid
        for process in psutil.process_iter(['name'])
        if (process.info.get('name') or '').split('.')[0].lower() in BROWSER_NAMES
    }


def _close_browsers_started_after(snapshot: set[int]) -> None:
    """Only close browser processes THIS script opened; never a browser the user had already open."""
    for pid in _browser_pids() - snapshot:
        try:
            process = psutil.Process(pid)
            process.terminate()
            process.wait(timeout=5)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            with contextlib.suppress(psutil.NoSuchProcess):
                psutil.Process(pid).kill()


def _absolute(value: str) -> str:
    path = Path(value)
    return str(path if path.is_absolute() else REPO / path)


def _open_browser(url: str) -> None:
    """Open a clean, maximized browser window without Chrome's crash-restore bubble."""
    binary = os.environ.get('CIXI_BROWSER_BIN', '').strip()
    if not binary:
        binary = next(
            (found for name in ('chrome', 'msedge', 'chromium', 'google-chrome') if (found := shutil.which(name))), ''
        )
    if binary and os.path.isfile(binary):
        # A per-project profile avoids Chrome's "restore pages" bubble and never touches the
        # user's own browser profile. It also makes the recorder's browser processes identifiable.
        profile = _absolute('scratchpad/demo_browser_profile')
        Path(profile).mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            [
                binary,
                f'--user-data-dir={profile}',
                '--start-maximized',
                '--disable-session-crashed-bubble',
                '--no-first-run',
                '--new-window',
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    webbrowser.open(url)


def _wait_for_server(url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if requests.get(url + '/api/config', timeout=1).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.4)
    raise RuntimeError(f'{url} did not come up within {timeout:.0f}s')


def _wait_for_run(url: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = requests.get(url + '/api/workflow/status', timeout=5).json()
        if not status.get('running'):
            return status
        time.sleep(0.5)
    raise TimeoutError(f'run did not settle within {timeout:.0f}s')


def _start_recording(output: Path, title: str, fps: int, width: int):
    # MKV tolerates an abrupt stop; MP4 written by a killed ffmpeg has no moov atom and will not
    # open. The finished recording is remuxed losslessly to MP4 once the run settles.
    output = output.with_suffix('.mkv')
    output.parent.mkdir(parents=True, exist_ok=True)
    exact_title, hwnd = find_window(title)
    # MAXIMIZE then F11: a small browser window is exactly what made the earlier recordings useless.
    focus_window(hwnd, fullscreen=True)
    # Chrome renders a black frame to gdigrab's window-by-title path (GPU composition). With the
    # browser MAXIMIZED + F11 it covers the desktop, so a desktop grab IS the browser page and does
    # not show the host window that caused the earlier useless recordings.
    command = capture_command(str(output), fps=fps, width=width)
    if not exact_title and not hwnd:
        print(f'  [capture] no window matched {title!r}; recording the desktop as-is')
    else:
        print(f'  [capture] desktop grab of F11 fullscreen window {exact_title!r} hwnd={hwnd}')
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return process, output, hwnd


def _stop_recording(process) -> None:
    """Ask ffmpeg to finalise the MP4 (a forced kill leaves a file with no moov atom)."""
    if process is None:
        return
    try:
        process.stdin.write(b'q\n')
        process.stdin.flush()
        process.wait(timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        process.kill()
        process.wait(timeout=5)


def _remux(source: Path, target: Path) -> None:
    """Losslessly turn the crash-safe MKV into a normal MP4, then drop the intermediate file."""
    if not source.exists():
        return
    subprocess.run(
        [ffmpeg_binary(), '-y', '-i', str(source), '-c', 'copy', str(target)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    source.unlink(missing_ok=True)


def run_group(group: dict, args, manifest_path: Path) -> list[dict]:
    root = _absolute(group['data_root'])
    Path(root).mkdir(parents=True, exist_ok=True)
    port = int(group.get('port') or 5001)
    url = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'CRAWLER_DATA_ROOT': root, 'PORT': str(port)}
    server = None
    if not args.no_serve:
        server = subprocess.Popen(
            [sys.executable, 'app.py'],
            cwd=str(REPO / 'backend'),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    browser_before = _browser_pids()
    try:
        _wait_for_server(url, args.startup_timeout)
        if args.open_browser:
            _open_browser(url)
            time.sleep(3)

        results = []
        for demo in group['demos']:
            if args.demo and demo['id'] not in args.demo:
                continue
            template = manifest_path.parent / demo['template']
            workflow = json.loads(template.read_text(encoding='utf-8'))
            output = VIDEOS / f'{demo["id"]}.mp4'
            recorder = None
            intermediate = None
            window = ''
            if not args.no_record:
                try:
                    recorder, intermediate, window = _start_recording(
                        output, group.get('capture_title', ''), args.fps, args.width
                    )
                except CaptureUnavailableError as exc:
                    print(f'  [capture] skipped: {exc}')
            try:
                answer = requests.post(
                    url + '/api/workflow/execute',
                    json={
                        'workflow': workflow,
                        'llm': group.get('llm') or {},
                        'lang': 'zh',
                        'workflow_name': workflow.get('name') or demo['title'],
                    },
                    timeout=15,
                ).json()
                if not answer.get('ok'):
                    raise RuntimeError(f'{demo["id"]} refused: {answer.get("error")}')
                status = _wait_for_run(url, args.run_timeout)
                print(f'  [run] {demo["id"]} settled: {status.get("run_id", "")}')
            finally:
                # Give the last rendered panel a moment before closing the video.
                if recorder is not None:
                    time.sleep(args.pad_seconds)
                    _stop_recording(recorder)
                    if window:
                        focus_window(window, fullscreen=True)  # leave F11 fullscreen
                    _remux(intermediate, output)
            results.append(
                {
                    'id': demo['id'],
                    'title': demo['title'],
                    'video': str(output.relative_to(REPO)) if output.exists() else '',
                    'run_id': status.get('run_id', ''),
                }
            )
        return results
    finally:
        if args.open_browser:
            _close_browsers_started_after(browser_before)
        if server is not None:
            # Flask spawns a child on some setups; terminating only the parent leaves a live
            # port holder. Kill the whole tree the recorder created, nobody else's server.
            try:
                parent = psutil.Process(server.pid)
                for child in parent.children(recursive=True):
                    with contextlib.suppress(psutil.NoSuchProcess):
                        child.terminate()
                parent.terminate()
                _, alive = psutil.wait_procs([parent], timeout=5)
                for process in alive:
                    with contextlib.suppress(psutil.NoSuchProcess):
                        process.kill()
            except psutil.NoSuchProcess:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--manifest', default=str(DEFAULT_MANIFEST))
    parser.add_argument('--group', action='append', default=[])
    parser.add_argument('--demo', action='append', default=[])
    parser.add_argument('--no-record', action='store_true', help='only run the workflows, do not record')
    parser.add_argument('--no-serve', action='store_true', help='use servers already listening on the manifest ports')
    parser.add_argument('--no-browser', dest='open_browser', action='store_false', help='do not open the page')
    parser.add_argument('--fps', type=int, default=12)
    parser.add_argument('--width', type=int, default=0, help='0 keeps the fullscreen browser at its native size')
    parser.add_argument('--pad-seconds', type=float, default=2.0)
    parser.add_argument('--startup-timeout', type=float, default=30)
    parser.add_argument('--run-timeout', type=float, default=180)
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = REPO / manifest_path
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    groups = [group for group in manifest['groups'] if not args.group or group['id'] in args.group]
    if not groups:
        raise SystemExit(f'no group matched {args.group}; available: {[g["id"] for g in manifest["groups"]]}')

    summary = []
    for group in groups:
        print(f'[group] {group["id"]} -> {group["data_root"]}:{group["port"]}')
        summary.extend(run_group(group, args, manifest_path))
    print(json.dumps({'ok': True, 'demos': summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
