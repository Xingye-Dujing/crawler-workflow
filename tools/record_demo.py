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
import sqlite3
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote

import psutil
import requests
from demo_capture import CaptureUnavailableError, capture_command, ffmpeg_binary, find_window, focus_window
from PIL import Image, ImageStat

REPO = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO / 'samples' / 'workflows' / 'manifest.json'
VIDEOS = REPO / 'samples' / 'workflows' / 'videos'
BROWSER_NAMES = {'chrome', 'msedge', 'firefox', 'chromium'}


def _browser_pids(profile_marker: str = '') -> set[int]:
    """Browser pids; with a marker, only those launched with the recorder's own profile."""
    pids = set()
    for process in psutil.process_iter(['name']):
        if (process.info.get('name') or '').split('.')[0].lower() not in BROWSER_NAMES:
            continue
        if profile_marker:
            try:
                if profile_marker not in ' '.join(process.cmdline()):
                    continue
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
        pids.add(process.pid)
    return pids


def _close_browsers_started_after(snapshot: set[int]) -> None:
    """Only close browser processes THIS script opened; never a browser the user had already open.

    A pid delta alone also caught a browser the user happened to start DURING a recording, killing
    their tabs. Match the recorder's unique user-data-dir too, so only our own processes are closed.
    """
    profile_marker = str(_absolute('scratchpad/demo_browser_profile'))
    for pid in _browser_pids(profile_marker) - snapshot:
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


def _fresh_browser_profile() -> str:
    """Recreate a pristine profile so Chrome cannot raise its 'restore pages' bubble.

    The recorder hard-kills its browser between demos, which leaves ``exit_type=Crashed`` in the
    profile and makes Chrome offer to restore pages on the next start (it covers the canvas in
    the video). A brand-new directory has no crash state to restore. Retried because Windows can
    hold a file lock for a moment after the previous browser process exits.
    """
    profile = _absolute('scratchpad/demo_browser_profile')
    path = Path(profile)
    for _ in range(12):
        if not path.exists():
            break
        try:
            shutil.rmtree(path)
            break
        except OSError:
            time.sleep(0.3)
    path.mkdir(parents=True, exist_ok=True)
    return profile


def _open_browser(url: str) -> None:
    """Open a clean, maximized browser window without Chrome's crash-restore bubble."""
    binary = os.environ.get('CIXI_BROWSER_BIN', '').strip()
    if not binary:
        binary = next(
            (found for name in ('chrome', 'msedge', 'chromium', 'google-chrome') if (found := shutil.which(name))), ''
        )
    if binary and os.path.isfile(binary):
        # A fresh per-project profile avoids Chrome's "restore pages" bubble and never touches the
        # user's own browser profile. It also makes the recorder's browser processes identifiable.
        profile = _fresh_browser_profile()
        subprocess.Popen(
            [
                binary,
                f'--user-data-dir={profile}',
                '--start-fullscreen',  # genuine F11-style fullscreen: no tabs, no address bar, no taskbar
                '--disable-session-crashed-bubble',
                '--disable-background-networking',  # no update check -> no "Chrome could not update" bubble
                '--no-first-run',
                '--no-default-browser-check',
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


def _clear_run_records(url: str, root: str) -> dict:
    """Wipe run history, dedupe claims AND AI conversations before a take.

    Without this the checkpoint/resume logic would see a prior run's ``done`` nodes and restore
    their results instead of really executing them — the video would show stale node states (the
    red crosses seen on a first frame) rather than a fresh execution. ``/api/runs/clear`` releases
    the item claims with the records. Old AI trace conversations are deleted too, so the workspace
    shows only the conversations this take opens. Datasets/workflows are left untouched.
    """
    answer = requests.post(url + '/api/runs/clear', json={'confirm': True}, timeout=15).json()
    if not answer.get('ok'):
        raise RuntimeError(f'could not clear run records: {answer.get("error")}')
    removed = answer.get('removed') or {}

    # Clear the AI workspace so the recorded transcript shows only THIS take's node-trace chats.
    cleared_ai = 0
    listing = requests.get(url + '/api/ai/conversations?limit=500', timeout=10).json()
    for conv in listing.get('conversations') or []:
        cid = conv.get('id')
        if cid and requests.delete(url + '/api/ai/conversations/' + quote(str(cid)), timeout=10).ok:
            cleared_ai += 1

    # Drop the row-level LLM checkpoint cache too: a replayed row would be filled from disk without
    # calling the model, so the trace conversation would show no prompt/answer and the video would
    # claim work the model never did this take. It is pure cache — the dataset itself is untouched.
    checkpoint_dir = Path(root) / 'data' / 'checkpoints'
    cleared_ckpt = 0
    if checkpoint_dir.exists():
        for item in checkpoint_dir.iterdir():
            if item.is_file():
                item.unlink(missing_ok=True)
                cleared_ckpt += 1
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
                cleared_ckpt += 1

    # /api/runs/clear deliberately KEEPS llm_cache (a cached answer is paid for by its prompt),
    # but a demo must actually call the model so the trace chat shows the real prompt/answer. The
    # cache lives in the demo root's own runs.db; a direct DELETE is safe here (WAL allows a second
    # writer) and touches no dataset. Never do this against a real user's data root.
    runs_db = Path(root) / 'data' / 'runs.db'
    cleared_llm_cache = 0
    if runs_db.exists():
        try:
            conn = sqlite3.connect(str(runs_db), timeout=10)
            count = conn.execute('SELECT COUNT(*) FROM llm_cache').fetchone()[0]
            conn.execute('DELETE FROM llm_cache')
            conn.commit()
            conn.close()
            cleared_llm_cache = int(count)
        except sqlite3.Error:
            cleared_llm_cache = -1

    print(
        f'  [clean] run records cleared: {removed.get("runs", 0)} runs, '
        f'{removed.get("item_claims", 0)} claims; AI chats: {cleared_ai}, '
        f'checkpoints: {cleared_ckpt}, llm_cache: {cleared_llm_cache}'
    )
    removed['ai_conversations'] = cleared_ai
    removed['checkpoints'] = cleared_ckpt
    removed['llm_cache'] = cleared_llm_cache
    return removed


def _wait_for_run(url: str, timeout: float, start_timeout: float = 90) -> dict:
    """Wait for the browser's autorun deep link to START, then to SETTLE.

    A short LLM run (a few rows of qualitative coding) can finish within the 0.5s poll gap, so
    ``execution_state['running']`` is already False by the time we look and would read as "never
    started". The run RECORD, however, is written for every run at its start and kept after it
    ends — so a fresh record appearing (we cleared all of them first) is the reliable start signal,
    and waiting for its status to leave 'running' is the reliable settle signal.
    """
    started = time.monotonic()
    run_id = ''
    while time.monotonic() - started < start_timeout:
        listing = requests.get(url + '/api/runs/list?limit=5', timeout=5).json()
        runs = listing.get('runs') or []
        if runs:
            run_id = runs[0].get('id') or runs[0].get('run_id') or ''
            if run_id:
                break
        time.sleep(0.3)
    else:
        raise TimeoutError(f'deep link did not start a run within {start_timeout:.0f}s')

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        listing = requests.get(url + '/api/runs/list?limit=5', timeout=5).json()
        current = next((r for r in (listing.get('runs') or []) if (r.get('id') or r.get('run_id')) == run_id), None)
        status_value = (current or {}).get('status', '')
        if status_value and status_value != 'running':
            return {'run_id': run_id, 'status': status_value}
        time.sleep(0.5)
    # A timeout here used to be returned as a settled status, so a hung demo produced a video and
    # was reported as successful. Fail loudly instead.
    raise TimeoutError(f'run {run_id} did not settle within {timeout:.0f}s')


def _focus_browser(title: str, timeout: float = 20, settle_seconds: float = 5.0) -> str:
    """Bring the freshly opened, already-fullscreen browser forward BEFORE anything else runs.

    Chrome is launched with --start-fullscreen, so it is fullscreen from its first frame. A new
    profile makes Chrome start slowly, so the window may not exist yet when we look. Waiting for it
    and focusing here (not at the end) is what keeps the desktop grab on the browser page instead
    of the host window. ``settle_seconds`` lets Chrome's transient "press Esc to exit fullscreen"
    bubble fade out before recording starts, so it never appears in the video.
    """
    deadline = time.monotonic() + timeout
    hwnd = ''
    while time.monotonic() < deadline:
        _, hwnd = find_window(title)
        if hwnd:
            break
        time.sleep(0.3)
    if hwnd:
        # Chrome was launched with --start-fullscreen; only bring it forward, never send F11.
        if focus_window(hwnd, fullscreen=False):
            print(f'  [capture] fullscreen browser foregrounded: {title!r} hwnd={hwnd}')
        else:
            print(f'  [capture] WARNING: could not foreground {title!r}; the host window may be recorded')
    else:
        print(f'  [capture] WARNING: no window matched {title!r}; recording the desktop as-is')
    # Wait out Chrome's fullscreen hint bubble so the first recorded frame is clean.
    if settle_seconds > 0:
        time.sleep(settle_seconds)
    return hwnd


def _start_recording(output: Path, fps: int, width: int):
    # MKV tolerates an abrupt stop; MP4 written by a killed ffmpeg has no moov atom and will not
    # open. The finished recording is remuxed losslessly to MP4 once the run settles.
    output = output.with_suffix('.mkv')
    output.parent.mkdir(parents=True, exist_ok=True)
    # Chrome renders a black frame to gdigrab's window-by-title path (GPU composition). With the
    # browser MAXIMIZED + F11 it covers the desktop, so a desktop grab IS the browser page and does
    # not show the host window that caused the earlier useless recordings. The browser is already
    # focused/fullscreen by _focus_browser, called right after it opened.
    command = capture_command(str(output), fps=fps, width=width)
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return process, output


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


def _ffprobe_binary() -> str:
    override = os.environ.get('CIXI_FFPROBE', '').strip()
    found = override or shutil.which('ffprobe') or ''
    if not found or not os.path.isfile(found):
        raise CaptureUnavailableError('ffprobe not found; set CIXI_FFPROBE to the executable path')
    return found


def _sample_frames(video: Path, demo_id: str, count: int = 3) -> dict:
    """Extract evenly spaced frames and flag an all-black recording.

    A screen recording that cannot be inspected is not evidence. Frames are saved next to the video
    so a human can look at them, and the grayscale standard deviation gives a cheap automated
    warning when the capture failed (a black frame has almost no variation).
    """
    if not video.exists():
        return {'frames': [], 'min_stddev': 0.0, 'ok': False}
    duration_text = subprocess.check_output(
        [_ffprobe_binary(), '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(video)],
        text=True,
    ).strip()
    duration = float(duration_text or 0)
    frame_dir = video.parent / 'frames'
    frame_dir.mkdir(parents=True, exist_ok=True)
    frames, stddevs = [], []
    for index in range(1, count + 1):
        at = max(0.5, duration * index / (count + 1))
        frame = frame_dir / f'{demo_id}_{index}.png'
        subprocess.run(
            [ffmpeg_binary(), '-y', '-ss', f'{at:.2f}', '-i', str(video), '-frames:v', '1', str(frame)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        if frame.exists():
            with Image.open(frame) as image:
                stddev = ImageStat.Stat(image.convert('L')).stddev[0]
            stddevs.append(stddev)
            frames.append({'path': str(frame.relative_to(REPO)), 'at': round(at, 1), 'stddev': round(stddev, 1)})
    minimum = min(stddevs) if stddevs else 0.0
    # A fixed grayscale-stddev floor is a HEURISTIC for "not a blank capture", not a site-derived
    # threshold: report the measured number and the floor so a human can judge instead of trusting
    # a bare ok flag.
    floor = float(os.environ.get('CIXI_FRAME_STDDEV_FLOOR') or 3.0)
    return {
        'frames': frames,
        'min_stddev': round(minimum, 1),
        'floor': floor,
        'ok': minimum > floor,
    }


def run_group(group: dict, args, manifest_path: Path) -> list[dict]:
    root = _absolute(group['data_root'])
    Path(root).mkdir(parents=True, exist_ok=True)
    port = int(group.get('port') or 5001)
    url = f'http://127.0.0.1:{port}'
    env = {
        **os.environ,
        'CRAWLER_DATA_ROOT': root,
        'PORT': str(port),
        # Only this recorder's isolated demo servers accept ?autorun=1; a user's own server never
        # starts a run from a bare link.
        'CIXI_DEMO_AUTORUN': '1',
    }
    server = None
    if not args.no_serve:
        server = subprocess.Popen(
            [sys.executable, 'app.py'],
            cwd=str(REPO / 'backend'),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    saved_dir = Path(root) / 'data' / 'workflows'
    saved_dir.mkdir(parents=True, exist_ok=True)
    try:
        _wait_for_server(url, args.startup_timeout)

        results = []
        for demo in group['demos']:
            if args.demo and demo['id'] not in args.demo:
                continue
            template = manifest_path.parent / demo['template']
            saved_name = demo.get('saved_name') or demo['id']
            shutil.copyfile(template, saved_dir / f'{saved_name}.json')
            output = VIDEOS / f'{demo["id"]}.mp4'
            recorder = None
            intermediate = None
            browser_before = _browser_pids()
            try:
                # Fresh history for every take: no checkpoint reuse, no stale node states, no
                # prior dedupe claims. Datasets and the saved canvas are left intact.
                _clear_run_records(url, root)
                if args.open_browser:
                    # The deep link loads the saved canvas into the browser and starts it there:
                    # the video shows real nodes executing, not an empty canvas or a REST call.
                    llm = group.get('llm') or {}
                    link = (
                        f'{url}/?workflow={quote(saved_name)}&autorun=1&layout=1&autorun_delay=11000'
                        f'&ai_width={int(group.get("ai_width") or 760)}'
                        f'&llm_provider={quote(str(llm.get("provider") or "ollama"))}'
                        f'&llm_model={quote(str(llm.get("model") or ""))}'
                    )
                    _open_browser(link)
                    # Focus the browser and go F11 fullscreen FIRST, before recording or any run:
                    # a slow-starting fresh profile otherwise leaves the host window in front.
                    _focus_browser(group.get('capture_title', ''))
                if not args.no_record:
                    try:
                        recorder, intermediate = _start_recording(output, args.fps, args.width)
                    except CaptureUnavailableError as exc:
                        print(f'  [capture] skipped: {exc}')
                status = _wait_for_run(url, args.run_timeout)
                print(f'  [run] {demo["id"]} settled: {status.get("run_id", "")}')
            finally:
                # Give the last rendered panel a moment before closing the video.
                if recorder is not None:
                    time.sleep(args.pad_seconds)
                    _stop_recording(recorder)
                    _remux(intermediate, output)
                if args.open_browser:
                    # Close THIS demo's browser now, not at the end of the whole group: the next
                    # demo then starts from a clean process set and a brand-new profile, so no
                    # crash-restore bubble and no leftover browser eating memory between takes.
                    _close_browsers_started_after(browser_before)
            frames = _sample_frames(output, demo['id']) if output.exists() else {'frames': [], 'ok': False}
            if not frames['ok']:
                print(f'  [capture] WARNING: {demo["id"]} frames look blank (stddev={frames["min_stddev"]})')
            results.append(
                {
                    'id': demo['id'],
                    'title': demo['title'],
                    'video': str(output.relative_to(REPO)) if output.exists() else '',
                    'run_id': status.get('run_id', ''),
                    'frames': frames,
                }
            )
        return results
    finally:
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
