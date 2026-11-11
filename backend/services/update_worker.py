"""The detached half of the self-updater: download, verify, unpack — then get out of the way.

It runs as ``CaiXiHui --update-worker <job.json>``: the same pack, no window, no Flask app, no
instance mutex. That shape is the whole point — the app may be closed at any moment (and the user
asked for exactly that: closing the window ends the program) while the work they consented to
finishes anyway, and the executable must be released before the swap can replace it.

What it does NOT do is touch the install: the swap script runs after this process is gone, because
on Windows a running image cannot be moved. Everything it knows lives in the job file, so a crash
here is a readable ``failed`` state rather than a mystery.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from core import machine, procs

from services import update, update_job


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print('usage: --update-worker <job.json>', file=sys.stderr)
        return 2
    return run(Path(args[0]))


def run(job_file: Path) -> int:
    """Do the one job in flight. Returns the process status (0 = staged)."""
    job = update_job.read()
    state = job.get('state')
    if state not in update_job.WORKER_STATES:
        update_job.log(f'worker: 没有需要下载的更新任务（{state or "空"}）', actor='worker')
        return 1
    if not update_job.claim(os.getpid()):
        update_job.log('worker: 另一个更新进程已经在运行', actor='worker')
        return 1
    version = str(job.get('version') or '')
    try:
        update_job.write(worker_pid=os.getpid())
        update_job.log(f'worker: 开始处理 {version}（任务 {job_file.name}）', actor='worker')
        staged = _download_and_stage(job, version)
        if staged is None:
            return 1
        if _cancelled():
            # A cancel that landed while the package was being unpacked: honour it rather than
            # offering a restart the user already withdrew.
            shutil.rmtree(update.version_dir(version), ignore_errors=True)
            update_job.clear()
            update_job.log('worker: 用户在展开完成后取消了更新', actor='worker')
            return 1
        update_job.write(
            state=update_job.STATE_STAGED,
            staged=str(staged),
            progress=100,
            error_code='',
            error_detail='',
            cancel=False,
        )
        update_job.log('worker: 已完成校验与展开，等待重启', actor='worker')
        _hand_off()
        return 0
    finally:
        update_job.release(os.getpid())


def _reporter():
    """Throttled progress: one write per whole percent, never per megabyte."""
    last = [-1]

    def report(percent) -> None:
        value = max(0, min(100, int(percent)))
        if value == last[0]:
            return
        last[0] = value
        try:
            update_job.write(progress=value)
        except OSError:
            return

    return report


def _cancelled() -> bool:
    return bool(update_job.read().get('cancel'))


def _download_and_stage(job: dict, version: str) -> Path | None:
    """The one pipeline; every failure is recorded with a code the panel has words for."""
    try:
        root = update.version_dir(version)
    except ValueError as exc:
        update_job.fail('version', str(exc))
        return None
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        update_job.fail('disk', f'无法创建暂存目录：{exc}')
        return None
    package = root / ('package.dmg' if machine.platform_name() == 'darwin' else 'package.zip')
    asset = job.get('asset') if isinstance(job.get('asset'), dict) else {}
    try:
        update_job.write(state=update_job.STATE_DOWNLOADING, progress=0)
        update.download_package(asset, package, progress=_reporter(), cancelled=_cancelled)
        update_job.write(state=update_job.STATE_STAGING)
        update_job.log('worker: 校验通过，开始展开', actor='worker')
        return update.stage_package(package, root)
    except update.UpdateError as exc:
        if exc.code == 'cancelled':
            shutil.rmtree(root, ignore_errors=True)
            update_job.clear()
            update_job.log('worker: 用户取消了下载', actor='worker')
            return None
        update_job.fail(exc.code, exc.detail)
        return None
    except OSError as exc:
        update_job.fail('disk', f'写入暂存目录失败：{exc}')
        return None


def _hand_off() -> None:
    """Start the swap now when nobody is left to press 重启.

    Two callers own the swap: the app (its 重启 button, or its window close) and this hand-off.
    The hand-off only fires when the app that asked for the update is already gone — a download
    that outlived its window — so the update still ends with the new build running.
    """
    job = update_job.read()
    owner = int(job.get('owner_pid') or 0)
    if owner and procs.process_alive(owner):
        return
    result = update.spawn_swapper(job, wait=False)
    if result.get('ok'):
        update_job.log('worker: 应用已经关闭，直接把更新交给替换脚本', actor='worker')
    else:
        update_job.log(f'worker: 替换脚本没能启动：{result.get("error", "")}', actor='worker')
