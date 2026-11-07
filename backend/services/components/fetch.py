"""Downloading a component, with the three properties an installer cannot do without.

1. **Resume instead of restart** — a 1.5 GB Ollama archive over a home connection is not a file
   anybody wants to fetch twice. A ``Range`` request continues the partial file; a server that
   ignores it simply restarts, which is still correct.
2. **Verify before use** — every mirror is untrusted, including a friendly one. The SHA-256 in the
   catalogue is checked after the download (and after concatenating Gitee's parts), and a mismatch
   deletes the bytes and names the URL rather than installing something unexpected.
3. **Try the next mirror** — the official address first, domestic mirrors after it, in catalogue
   order. A failure on one is not a failure of the installation.

The module is standard-library only for the same reason as :mod:`catalog`: the bootstrap installer
uses it before the application is installed.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from services.components.catalog import Asset

Progress = Callable[[int, int], None]
Cancel = Callable[[], bool]
CHUNK = 1024 * 1024
TIMEOUT = 30
USER_AGENT = 'CaiXiHui-installer'
_CONTENT_RANGE = re.compile(r'bytes\s+(\d+)-', re.IGNORECASE)


class DownloadError(Exception):
    """A download that could not be completed or verified; the sentence names what failed."""


class DownloadCancelledError(DownloadError):
    """The user stopped the download.

    The bytes so far are kept, and a retry resumes from them: deleting a half-fetched 1.5 GB archive
    because somebody pressed 取消 is the opposite of what the button means.
    """


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def _request(url: str, start: int = 0) -> urllib.request.Request:
    headers = {'User-Agent': USER_AGENT}
    if start:
        headers['Range'] = f'bytes={start}-'
    return urllib.request.Request(url, headers=headers)


def _checked(url: str, allow_insecure: bool) -> None:
    lowered = url.lower()
    allowed = lowered.startswith('https://')
    if allow_insecure and (lowered.startswith('http://') or lowered.startswith('file://')):
        allowed = True
    if not allowed:
        raise DownloadError(f'refusing a non-HTTPS download: {url}')


def _download_one(
    url: str,
    dest: Path,
    expected: int,
    progress: Progress | None,
    cancel: Cancel | None,
    allow_insecure: bool,
    timeout: float,
) -> None:
    _checked(url, allow_insecure)
    start = dest.stat().st_size if dest.exists() else 0
    if expected and start > expected:
        dest.unlink()
        start = 0
    if expected and start == expected:
        return
    try:
        with urllib.request.urlopen(_request(url, start), timeout=timeout) as response:
            mode = 'ab' if start and response.status == 206 else 'wb'
            if mode == 'wb':
                start = 0
            total = expected
            if not total and response.headers.get('Content-Length'):
                total = int(response.headers['Content-Length']) + start
            with open(dest, mode) as handle:
                done = start
                while True:
                    if cancel and cancel():
                        raise DownloadCancelledError(f'cancelled while downloading {url}')
                    block = response.read(CHUNK)
                    if not block:
                        break
                    handle.write(block)
                    done += len(block)
                    if progress:
                        progress(done, total)
    except urllib.error.HTTPError as exc:
        raise DownloadError(f'HTTP {exc.code} from {url}') from exc
    except (urllib.error.URLError, OSError) as exc:
        raise DownloadError(f'network error from {url}: {exc}') from exc
    if expected and dest.stat().st_size != expected:
        raise DownloadError(f'{url} returned {dest.stat().st_size} bytes, expected {expected}')


def _verify(path: Path, expected: str, size: int) -> None:
    if size and path.stat().st_size != size:
        raise DownloadError(f'{path.name} is {path.stat().st_size} bytes, expected {size}')
    actual = sha256_file(path)
    if actual.lower() != expected.lower():
        raise DownloadError(f'{path.name} has SHA-256 {actual}, expected {expected}')


def download_asset(
    asset: Asset,
    dest: str | Path,
    *,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
    allow_insecure: bool = False,
    timeout: float = TIMEOUT,
) -> Path:
    """Fetch ``asset`` into ``dest``, trying every mirror and verifying the result.

    ``dest`` is complete only on success; a failed or unverified file is removed so a later retry
    does not silently reuse it. A **cancel** is the exception: it keeps the partial file (and the
    completed parts) and raises :class:`DownloadCancelledError`, so the next attempt resumes.
    """
    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        try:
            _verify(target, asset.sha256, asset.size)
            return target
        except DownloadError:
            target.unlink()
    errors: list[str] = []
    if asset.parts:
        for index, part in enumerate(asset.parts, 1):
            part_path = target.with_name(f'{target.name}.part{index:02d}')
            try:
                _download_one(part.url, part_path, part.size, progress, cancel, allow_insecure, timeout)
                _verify(part_path, part.sha256, part.size)
            except DownloadCancelledError:
                raise
            except DownloadError as exc:
                errors.append(str(exc))
                part_path.unlink(missing_ok=True)
                break
        else:
            with open(target, 'wb') as handle:
                for index in range(1, len(asset.parts) + 1):
                    piece = target.with_name(f'{target.name}.part{index:02d}')
                    with open(piece, 'rb') as source:
                        shutil.copyfileobj(source, handle, CHUNK)
                    piece.unlink(missing_ok=True)
            try:
                _verify(target, asset.sha256, asset.size)
                return target
            except DownloadError as exc:
                errors.append(str(exc))
                target.unlink(missing_ok=True)
    else:
        for url in asset.urls:
            try:
                _download_one(url, target, asset.size, progress, cancel, allow_insecure, timeout)
                _verify(target, asset.sha256, asset.size)
                return target
            except DownloadCancelledError:
                raise
            except DownloadError as exc:
                errors.append(str(exc))
                target.unlink(missing_ok=True)
    raise DownloadError('; '.join(errors) or 'no download source')
