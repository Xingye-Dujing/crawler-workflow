"""Self-update for the main program: version check, download, staged swap, restart.

Components change rarely and the application ships often, so this module owns only the
application payload. It never touches ``components/``, ``data/``, logs, cookies or models: the
downloaded archive is extracted into a staging folder beside the running install and a small
per-OS script swaps the program entries after this process exits.

The feed is a small ``version.json`` in the repository (served raw by Gitee, with GitHub as a
fallback), never a release API: the app only needs a version, notes and one verified asset. The
download is checked against the feed's SHA-256 before anything is staged; a mismatch is a refusal,
not a retry with an unverified file.

Three processes cooperate and none of them may assume another is alive:

* this module (inside the app) checks, records consent and hands the job over;
* ``services/update_worker.py`` — a detached copy of this same program — downloads, verifies and
  unpacks, then exits so the executable it runs from can be replaced;
* the per-OS swapper script waits for both to be gone, replaces the program files, and starts the
  new build (rolling back to the old one if it dies).

The swap used to be the whole implementation. It silently never ran: the helper was spawned with
``DETACHED_PROCESS``, which a console child does not survive (see ``core.procs.popen_kwargs``), and
the app killed itself 1.5 s later regardless. It now starts only after the helper has written a
receipt, so a helper that cannot run is a named refusal instead of a vanished program.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from core import machine, procs
from core.config import Config

from services import update_job, update_receipt
from services.components.archive import ArchiveError, safe_extract
from services.version import APP_VERSION

#: The same file two ways: Gitee is the primary network in China, GitHub the fallback. An operator
#: rehearsing a release (or running a private mirror) overrides both with ``CIXI_UPDATE_FEED``.
FEED_URLS = (
    'https://gitee.com/Xingye-Dujing/crawler-workflow/raw/main/version.json',
    'https://raw.githubusercontent.com/Xingye-Dujing/crawler-workflow/main/version.json',
)
FEED_ENV = 'CIXI_UPDATE_FEED'

#: A stale check is cheap; asking on every boot would be noise, and the feed is a static file.
FEED_TTL = 30 * 60
USER_AGENT = 'CaiXiHui-updater'

#: The version names ONE directory under ``data/updates``, so it is DATA, not a path. The value
#: arrives from the network and the next step is ``shutil.rmtree``: a version of ``..`` used to
#: resolve to ``data/`` itself, so "download the update" could delete every account's tree. A
#: dotted release number is the only shape the release script writes; anything else is refused by
#: name, and the resolved directory is asserted to be a CHILD of ``data/updates`` as a second lock.
_VERSION_RE = re.compile(r'^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$')
_SHA_RE = re.compile(r'^[0-9a-f]{64}$')

#: A package is a few hundred MB. A feed that asks for more is not an offer this machine accepts:
#: without a ceiling, one bad (or malicious) manifest fills the disk the app needs for its data.
MAX_PACKAGE_BYTES = 4 * 1024**3
#: The manifest itself is a few kilobytes; ``response.read()`` with no ceiling was a free way for a
#: wrong URL to fill memory.
MAX_FEED_BYTES = 1024 * 1024
#: Socket read timeout. A transfer that stalls this long is a named failure, not a hung updater.
STALL_TIMEOUT = 60

#: How long the swapper gets to write its receipt before the app declares the update stillborn.
HELPER_TIMEOUT = 10.0

#: Where a release-signing public key may live: the environment (PEM text or a path to one) and,
#: for a packaged install, a file beside the data root. Absent means the feed is unsigned; present
#: means a feed WITHOUT a valid signature is refused (failure closed, not "best effort").
PUBKEY_ENV = 'CIXI_UPDATE_PUBKEY'
PUBKEY_FILE = 'update-pubkey.pem'


class UpdateError(RuntimeError):
    """A refusal with a stable ``code`` the panel translates, plus the machine's own sentence."""

    def __init__(self, code: str, detail: str = '') -> None:
        super().__init__(detail or code)
        self.code = str(code or 'unknown')
        self.detail = str(detail or '')


def version_dir(version: str) -> Path:
    """The staged folder for one feed version, or a named refusal.

    Two independent answers to the same question (shape, then containment) because the cost of
    being wrong here is the whole data root.
    """
    text = str(version or '').strip()
    if not _VERSION_RE.match(text) or '..' in text:
        raise ValueError(f'发行清单里的版本号不可用：{text or "(空)"}')
    root = updates_root()
    target = root / text
    if target.resolve().parent != root.resolve():
        raise ValueError(f'发行清单里的版本号越出了更新目录：{text}')
    return target


def _require_https(url: str) -> str:
    """A download URL, or a refusal. Every hop is checked, not only the first."""
    text = str(url or '').strip()
    if not text.lower().startswith('https://'):
        raise ValueError(f'拒绝非 HTTPS 的下载地址：{text or "(空)"}')
    return text


class _HttpsRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only if the NEXT hop is still HTTPS.

    ``urllib`` happily follows a 302 to ``http://``/``ftp://``, so checking the URL before
    ``urlopen`` said "HTTPS only" while the bytes could still arrive in clear text.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _require_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpsRedirects)


def _public_key_pem() -> bytes | None:
    """The release-signing public key, if this machine was given one."""
    raw = str(os.environ.get(PUBKEY_ENV) or '').strip()
    if raw:
        if len(raw) > 40 and 'BEGIN PUBLIC KEY' in raw:
            return raw.encode('utf-8')
        candidate = Path(raw).expanduser()
        if candidate.is_file():
            return candidate.read_bytes()
        return None
    packaged = Path(Config.DATA_DIR) / PUBKEY_FILE
    if packaged.is_file():
        return packaged.read_bytes()
    return None


def _canonical_feed(payload: dict) -> bytes:
    """The exact bytes a signature covers: the document minus its own ``signature`` field."""
    body = {key: value for key, value in payload.items() if key != 'signature'}
    return json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('utf-8')


#: Public spelling for the release-signing tool (``tools/sign_release_feed.py``). The signature is
#: over THESE bytes, so the tool imports this function instead of re-implementing the canonical form:
#: two encoders that drift would produce signatures the client rejects with no visible cause.
canonical_feed = _canonical_feed


def verify_feed_signature(payload: dict) -> None:
    """Refuse a feed whose signature is missing or wrong, once a public key is configured.

    The SHA-256 in the manifest only says "the bytes match what the manifest claims", and the
    manifest is the thing an attacker rewrites first — so the digest alone cannot protect an
    update that ends in a program swap. With a key present, the signature is the trust root and a
    failure is a refusal. Without one the feed is still accepted (the product cannot update
    otherwise) but :func:`check` says so out loud instead of pretending the chain is verified.
    """
    key_pem = _public_key_pem()
    if key_pem is None:
        return
    signature = str(payload.get('signature') or '').strip()
    if not signature:
        raise ValueError('更新清单没有签名，本机已配置校验公钥，拒绝使用')
    try:
        from cryptography.hazmat.primitives import serialization

        key = serialization.load_pem_public_key(key_pem)
        key.verify(base64.b64decode(signature), _canonical_feed(payload))
    except ImportError as exc:  # a build without the verifier must not silently trust the feed
        raise ValueError('这份安装缺少签名校验组件（cryptography），无法核对更新清单') from exc
    except Exception as exc:
        raise ValueError(f'更新清单签名校验失败：{exc}') from exc


def current_version() -> str:
    return APP_VERSION


def version_tuple(text: str) -> tuple[int, ...]:
    """A comparable tuple; anything unparseable sorts below every real version."""
    parts = tuple(int(part) for part in re.findall(r'\d+', str(text or '')))
    return parts or (0,)


def is_newer(latest: str, current: str) -> bool:
    return version_tuple(latest) > version_tuple(current)


def updates_root() -> Path:
    return update_job.updates_root()


def _frozen() -> bool:
    return bool(getattr(sys, 'frozen', False))


def install_layout() -> tuple[str, Path | None, Path]:
    """``(mode, install root, executable)`` for the running build.

    ``app`` is the online installer's ``<root>/app/CaiXiHui.exe`` layout; anything else is a
    portable folder. ``macapp`` is the macOS bundle, whose ``.app`` is moved as one unit.
    """
    exe = Path(sys.executable).resolve()
    if machine.platform_name() == 'darwin':
        for parent in exe.parents:
            if parent.suffix == '.app':
                return 'macapp', parent, exe
        return '', None, exe
    if exe.parent.name == 'app':
        return 'app', exe.parent.parent, exe
    return 'portable', exe.parent, exe


def _platform_key() -> str:
    return machine.platform_asset_key()


def _asset(feed: dict) -> dict:
    platforms = feed.get('platforms') if isinstance(feed, dict) else None
    asset = (platforms or {}).get(_platform_key())
    return asset if isinstance(asset, dict) else {}


def _fetch(url: str, timeout: float = 8.0) -> bytes:
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_FEED_BYTES + 1)
    if len(raw) > MAX_FEED_BYTES:
        raise ValueError(f'更新清单超过 {MAX_FEED_BYTES} 字节，已拒绝')
    return raw


def feed_urls() -> tuple[str, ...]:
    """The manifest addresses to try, in order; ``CIXI_UPDATE_FEED`` replaces both when set."""
    override = str(os.environ.get(FEED_ENV) or '').strip()
    if override:
        return tuple(item.strip() for item in override.split(',') if item.strip())
    return FEED_URLS


def _valid_feed(payload) -> bool:
    if not isinstance(payload, dict) or payload.get('schema') != 1:
        return False
    version = str(payload.get('version') or '').strip()
    return bool(_VERSION_RE.match(version)) and '..' not in version and isinstance(payload.get('platforms'), dict)


_FEED_CACHE: dict = {'at': 0.0, 'feed': None, 'error': ''}


def fetch_feed(force: bool = False) -> dict | None:
    """The cached release feed, or ``None`` with the reason kept in ``_FEED_CACHE``."""
    if not force and _FEED_CACHE['feed'] and time.monotonic() - _FEED_CACHE['at'] < FEED_TTL:
        return _FEED_CACHE['feed']
    error = ''
    for url in feed_urls():
        try:
            payload = json.loads(_fetch(url).decode('utf-8'))
        except (OSError, ValueError, urllib.error.URLError) as exc:
            error = f'{url}: {exc}'
            continue
        if not _valid_feed(payload):
            error = f'{url}: not a version feed'
            continue
        try:
            verify_feed_signature(payload)
        except ValueError as exc:
            error = f'{url}: {exc}'
            continue
        _FEED_CACHE.update({'at': time.monotonic(), 'feed': payload, 'error': ''})
        return payload
    _FEED_CACHE.update({'at': time.monotonic(), 'feed': None, 'error': error or 'no feed'})
    return None


def _size_of(asset: dict) -> int:
    try:
        return int(asset.get('size') or 0)
    except (TypeError, ValueError):
        return 0


def _digest_of(asset: dict) -> str:
    return str(asset.get('sha256') or '').strip().lower()


def _asset_usable(asset: dict) -> tuple[bool, str]:
    """Whether the manifest entry describes a package this machine may install.

    A missing digest is not "unknown", it is *unverified*: the release workflow always writes one,
    so accepting its absence would only ever install bytes nobody checked.
    """
    if not asset:
        return False, '发行清单里没有这个平台的安装包'
    if not _SHA_RE.match(_digest_of(asset)):
        return False, '发行清单缺少这个平台的 SHA-256，已拒绝安装未经校验的程序'
    parts = asset.get('parts') if isinstance(asset.get('parts'), list) else []
    if parts:
        for index, part in enumerate(parts, 1):
            if not str(part.get('url') or '').strip():
                return False, f'发行清单里第 {index} 个分片没有下载地址'
            if not _SHA_RE.match(str(part.get('sha256') or '').strip().lower()):
                return False, f'发行清单里第 {index} 个分片没有 SHA-256'
    elif not str(asset.get('url') or '').strip():
        return False, '发行清单里没有这个平台的下载地址'
    if _size_of(asset) <= 0:
        return False, '发行清单缺少安装包大小'
    return True, ''


def swap_supported() -> bool:
    """Whether THIS install can replace itself; ``False`` is a fact the panel shows, not an error.

    A Linux server or a macOS build unpacked outside a bundle has no swap script, so offering
    "update now" there would end in a refusal after the download — say it before the download.
    """
    if not _frozen():
        return False
    mode, _root, _exe = install_layout()
    if machine.platform_name() == 'win32':
        return mode in ('app', 'portable')
    if machine.platform_name() == 'darwin':
        return mode == 'macapp'
    return False


# ─── Checking ────────────────────────────────────────────────


def _receipt_artifact(job: dict) -> str:
    """The package name the receipt should record; the feed URL's last segment when it has one."""
    asset = job.get('asset') if isinstance(job.get('asset'), dict) else {}
    url = str(asset.get('url') or '').strip()
    name = url.rsplit('/', 1)[-1].split('?', 1)[0]
    return name or f'CaiXiHui-{job.get("version") or ""}'


def _record_install_receipt(version: str, job: dict) -> None:
    """Rewrite the installer's pointer/receipt, or say why it could not.

    This is the one write an in-app update owes the release chain: without it the receipt keeps
    naming the version the installer put there, and an audit of "what is installed" is wrong.
    A missing ``current-version`` is a portable folder and no-ops; an I/O refusal is logged once and
    never fails the updated build's boot.
    """
    _mode, root, _exe = install_layout()
    if root is None:
        return
    try:
        written = update_receipt.record(version, root, artifact=_receipt_artifact(job))
    except (OSError, ValueError) as exc:
        update_job.log(f'安装回执没有改写：{exc}', actor='app')
        return
    if written:
        update_job.log(f'安装回执已指向 {version}', actor='app')


def _reconcile_boot(current: str) -> None:
    """Turn what the last exit left behind into a state this boot can trust."""
    job = update_job.read()
    state = job.get('state')
    version = str(job.get('version') or '')
    if state == update_job.STATE_APPLYING:
        if version and version == current:
            update_job.write(state=update_job.STATE_APPLIED, error_code='', error_detail='')
            update_job.log(f'新版本 {current} 已启动', actor='app')
            _record_install_receipt(current, job)
            return
        swapper = int(job.get('swapper_pid') or 0)
        if update_job.marker_file().exists() or procs.process_alive(swapper):
            # The swap may still be running (the launcher waits for the marker before starting us).
            return
        update_job.fail('swap_lost', '替换脚本没有完成；当前运行的是旧版本，请重试更新')
        return
    # A download or a failure for a version this install already HAS is history, not a prompt:
    # the user installed it another way (an installer, a manual copy) and a card still offering
    # "restart to finish 2026.x" would be asking them to go backwards.
    if state in (update_job.STATE_STAGED, update_job.STATE_FAILED) and version and not is_newer(version, current):
        update_job.clear()
        update_job.log(f'已清理 {version} 的旧更新任务（当前 {current}）', actor='app')


def _cleanup_updates() -> None:
    """Drop staging folders no job owns; the one in flight or awaiting a restart stays."""
    job = update_job.read()
    keep = set()
    if job.get('state') in update_job.KEEP_STATES:
        version = str(job.get('version') or '')
        if version:
            keep.add(version)
    update_job.prune(keep)


def reconcile_after_start() -> None:
    """The boot half of :func:`check`, so the receipt is repaired even if nobody opens the panel.

    ``check()`` owns this work too, but it only runs when the update panel asks. A user who updates
    and restarts never has to open that panel, and leaving ``applying`` on disk (and the receipt
    stale) until they do would make the next successful update read as "still applying".
    """
    if not _frozen():
        return
    try:
        _reconcile_boot(current_version())
    except Exception as exc:  # a receipt/job read must never stop the server from booting
        update_job.log(f'启动时的更新核对失败：{exc}', actor='app')


def check() -> dict:
    current = current_version()
    if not _frozen():
        return {'ok': True, 'supported': False, 'current': current, 'reason': 'source'}
    _reconcile_boot(current)
    _cleanup_updates()
    job = update_job.read()
    answer = {
        'ok': True,
        'supported': True,
        'current': current,
        'apply_supported': swap_supported(),
        # Whether this machine can actually check the manifest. `False` is not a failure (the
        # product must still update), but it is a fact the panel shows instead of implying the
        # SHA-256 chain has a trust root it does not have.
        'signed': _public_key_pem() is not None,
        # The persisted job travels with every check: a page reload, a second window or a restart
        # mid-download all paint the same progress instead of offering the download again.
        'job': update_job.public(job),
        'feed_error': '',
        'platform': _platform_key(),
        'latest': current,
        'update_available': False,
        'asset_ready': False,
        'notes': '',
    }
    feed = fetch_feed()
    if feed is None:
        answer['feed_error'] = _FEED_CACHE['error'] or 'no feed'
        return answer
    latest = str(feed.get('version') or '').strip()
    asset = _asset(feed)
    usable, why = _asset_usable(asset)
    answer.update(
        {
            'latest': latest,
            'notes': str(feed.get('notes') or ''),
            'asset_ready': usable,
            'asset_problem': '' if usable else why,
            # A version with no usable asset for THIS platform is not an offer the user can act on.
            'update_available': usable and is_newer(latest, current),
        }
    )
    return answer


# ─── Downloading and unpacking (the worker's half) ───────────


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _stream(url: str, destination: Path, *, on_block=None, cancelled=None) -> int:
    """Stream one file, reporting bytes as they land and stopping when asked.

    ``timeout`` is a SOCKET read timeout, so a transfer that stops delivering bytes raises instead
    of hanging the worker for the rest of the session.
    """
    request = urllib.request.Request(_require_https(url), headers={'User-Agent': USER_AGENT})
    written = 0
    with _OPENER.open(request, timeout=STALL_TIMEOUT) as response, open(destination, 'wb') as handle:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            written += len(block)
            if written > MAX_PACKAGE_BYTES:
                raise UpdateError('size', f'下载超过上限 {MAX_PACKAGE_BYTES // 1024**3} GiB，已中止')
            handle.write(block)
            if on_block is not None:
                on_block(len(block))
            if cancelled is not None and cancelled():
                raise UpdateError('cancelled', '已取消')
    return written


def _part_ok(path: Path, expected_size: int, expected_sha: str) -> bool:
    """Whether a shard downloaded by an earlier attempt may be reused as it is."""
    try:
        if expected_size and path.stat().st_size != expected_size:
            return False
        return not expected_sha or _sha256(path) == expected_sha
    except OSError:
        return False


def download_package(asset: dict, package: Path, *, progress=None, cancelled=None) -> None:
    """Fetch the package described by ``asset`` into ``package``, refusing anything unverified.

    Shards already downloaded and verified by an earlier attempt are reused (``.ok`` sidecar), so a
    dropped connection costs one shard, not the whole 130 MB package.
    """
    parts = asset.get('parts') if isinstance(asset.get('parts'), list) else []
    total = _size_of(asset)
    done = 0

    def report(step: int) -> None:
        nonlocal done
        done += int(step)
        if progress is not None and total:
            progress(min(95, int(done * 95 / total)))

    if parts:
        verified: list[Path] = []
        for index, part in enumerate(parts, 1):
            if cancelled is not None and cancelled():
                raise UpdateError('cancelled', '已取消')
            url = str(part.get('url') or '').strip()
            expected_size = int(part.get('size') or 0)
            expected_sha = str(part.get('sha256') or '').strip().lower()
            part_path = package.with_name(f'{package.name}.part{index:03d}')
            ok_path = part_path.with_name(f'{part_path.name}.ok')
            if ok_path.is_file() and _part_ok(part_path, expected_size, expected_sha):
                verified.append(part_path)
                report(part_path.stat().st_size)
                continue
            part_path.unlink(missing_ok=True)
            ok_path.unlink(missing_ok=True)
            try:
                written = _stream(url, part_path, on_block=report, cancelled=cancelled)
            except (OSError, urllib.error.URLError) as exc:
                raise UpdateError('network', f'第 {index} 个分片下载失败：{exc}') from exc
            if expected_size and written != expected_size:
                raise UpdateError('size', f'第 {index} 个分片大小不对：{written} != {expected_size}')
            if expected_sha and _sha256(part_path) != expected_sha:
                raise UpdateError('sha', f'第 {index} 个分片校验失败')
            ok_path.write_text('ok', encoding='utf-8')
            verified.append(part_path)
        with open(package, 'wb') as output:
            for part_path in verified:
                with open(part_path, 'rb') as reader:
                    shutil.copyfileobj(reader, output, 1024 * 1024)
                part_path.unlink(missing_ok=True)
                part_path.with_name(f'{part_path.name}.ok').unlink(missing_ok=True)
    else:
        url = str(asset.get('url') or '').strip()
        if not url:
            raise UpdateError('asset', '发行清单里没有这个平台的安装包')
        try:
            _stream(url, package, on_block=report, cancelled=cancelled)
        except (OSError, urllib.error.URLError) as exc:
            raise UpdateError('network', f'下载失败：{exc}') from exc
    expected_sha = _digest_of(asset)
    if expected_sha and _sha256(package) != expected_sha:
        raise UpdateError('sha', '安装包 SHA-256 校验失败，已拒绝使用')
    expected_size = _size_of(asset)
    if expected_size and package.stat().st_size != expected_size:
        raise UpdateError('size', f'安装包大小不对：{package.stat().st_size} != {expected_size}')


def _stage_macos(package: Path, staging: Path) -> Path:
    """Mount the DMG and copy the one ``.app`` out of it; returns the staged bundle."""
    staging.mkdir(parents=True, exist_ok=True)
    mount = staging / 'mnt'
    mount.mkdir()
    try:
        subprocess.run(
            ['hdiutil', 'attach', '-nobrowse', '-readonly', '-mountpoint', str(mount), str(package)],
            check=True,
            capture_output=True,
            timeout=120,
            **procs.popen_kwargs(),
        )
        try:
            bundles = sorted(mount.glob('*.app'))
            if not bundles:
                raise UpdateError('shape', 'DMG 里没有 .app')
            target = staging / 'CaiXiHui.app'
            if target.exists():
                shutil.rmtree(target)
            subprocess.run(
                ['ditto', str(bundles[0]), str(target)],
                check=True,
                timeout=600,
                **procs.popen_kwargs(),
            )
            return target
        finally:
            subprocess.run(
                ['hdiutil', 'detach', str(mount)],
                check=False,
                capture_output=True,
                timeout=60,
                **procs.popen_kwargs(),
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateError('extract', f'展开 macOS 安装包失败：{exc}') from exc


def verify_staged(staged: Path, *, platform: str = '') -> None:
    """Refuse a payload that does not look like THIS program.

    The hash only says the bytes are the ones the manifest named; a manifest that points at the
    wrong archive would otherwise be copied over the install and leave a program-shaped hole.
    """
    if platform == 'darwin':
        if not (staged / 'Contents' / 'MacOS' / 'CaiXiHui').is_file():
            raise UpdateError('shape', '更新包里的 .app 缺少可执行文件')
        return
    required = machine.app_payload_files(platform or None)
    missing = [name for name in required if not (staged / name).exists()]
    if missing:
        raise UpdateError('shape', '更新包里没有这个程序的入口文件：' + '、'.join(missing))


def stage_package(package: Path, root: Path) -> Path:
    """Unpack ``package`` into ``root/staged`` (replacing anything an old attempt left)."""
    staged = root / 'staged'
    if staged.exists():
        shutil.rmtree(staged, ignore_errors=True)
    platform = machine.platform_name()
    if platform == 'darwin':
        target = _stage_macos(package, staged)
        verify_staged(target, platform=platform)
        return target
    try:
        safe_extract(package, staged, archive_type='zip', strip_prefix='CaiXiHui')
    except ArchiveError as exc:
        raise UpdateError('extract', f'展开安装包失败：{exc}') from exc
    verify_staged(staged, platform=platform)
    return staged


# ─── Starting the download worker ───────────


def worker_command(job_file: Path) -> list[str]:
    """How a detached copy of this program becomes the download worker.

    The packaged build is one folder, so its own executable is the cheapest interpreter that
    already has every dependency and the already-resolved data root in its environment. A source
    run never reaches here (:func:`prepare` refuses before).
    """
    return [str(sys.executable), '--update-worker', str(job_file)]


def _spawn_worker(job_file: Path) -> int:
    child = subprocess.Popen(
        worker_command(job_file),
        cwd=str(Path(sys.executable).resolve().parent),
        close_fds=True,
        **procs.popen_kwargs(detached=True),
    )
    return int(child.pid)


def prepare() -> dict:
    """Start (or resume) the download and unpacking of the newest release.

    Everything here is a decision the app can still refuse: a platform without a swapper, a
    manifest without a digest, a worker that will not start. Once the worker is running the app
    may be closed — the job survives on disk and the worker finishes it.
    """
    if not _frozen():
        return {'ok': False, 'error': '源码运行不执行自更新'}
    if not swap_supported():
        return {'ok': False, 'error': '当前平台不支持应用内更新，请用安装器安装新版本'}
    job = update_job.read()
    if job.get('state') in update_job.WORKER_STATES:
        if update_job.worker_alive(job):
            return {'ok': True, 'job': update_job.public(job), 'resumed': True}
        job = update_job.fail('worker', '上一次的更新进程已经退出，任务没有完成，可以重试')
    feed = fetch_feed()
    if feed is None:
        return {'ok': False, 'error': f'无法读取更新清单：{_FEED_CACHE["error"] or "no feed"}'}
    latest = str(feed.get('version') or '').strip()
    asset = _asset(feed)
    usable, why = _asset_usable(asset)
    if not usable:
        return {'ok': False, 'error': why}
    if job.get('state') == update_job.STATE_STAGED and job.get('version') == latest:
        if Path(str(job.get('staged') or '')).is_dir():
            return {'ok': True, 'job': update_job.public(job), 'ready': True}
        update_job.fail('staged_missing', '已下载的更新包不见了，需要重新下载')
        job = update_job.read()
    resumable = job.get('state') == update_job.STATE_FAILED and job.get('version') == latest
    if resumable:
        job = update_job.write(
            state=update_job.STATE_DOWNLOADING,
            progress=0,
            error_code='',
            error_detail='',
            cancel=False,
            owner_pid=os.getpid(),
            worker_pid=0,
            attempts=int(job.get('attempts') or 0) + 1,
        )
        update_job.log(f'重试下载 {latest}（第 {job.get("attempts")} 次）', actor='app')
    else:
        try:
            shutil.rmtree(version_dir(latest), ignore_errors=True)
        except ValueError as exc:
            return {'ok': False, 'error': str(exc)}
        job = update_job.start(version=latest, asset=asset, from_version=current_version())
        update_job.log(f'开始下载 {latest}', actor='app')
    try:
        pid = _spawn_worker(update_job.job_file())
    except OSError as exc:
        update_job.fail('worker', f'下载进程没能启动：{exc}')
        return {'ok': False, 'error': f'下载进程没能启动：{exc}'}
    update_job.write(worker_pid=pid)
    update_job.log(f'下载进程 pid={pid}', actor='app')
    return {'ok': True, 'job': update_job.public(update_job.read())}


def status() -> dict:
    """The job as the panel should see it, with a dead worker reported as a named failure."""
    job = update_job.read()
    if job.get('state') in update_job.WORKER_STATES and not update_job.worker_alive(job):
        job = update_job.fail('worker', '下载进程意外退出，任务没有完成，可以重试')
    return update_job.public(job)


def cancel() -> dict:
    """Stop the job in flight, or throw away a package that is already staged."""
    job = update_job.read()
    state = job.get('state')
    if state in update_job.WORKER_STATES:
        if update_job.worker_alive(job):
            update_job.write(cancel=True)
            update_job.log('已请求取消下载', actor='app')
            return {'ok': True, 'job': update_job.public()}
        job = update_job.read()
    if state in (
        update_job.STATE_DOWNLOADING,
        update_job.STATE_STAGING,
        update_job.STATE_STAGED,
        update_job.STATE_FAILED,
        update_job.STATE_APPLIED,
    ):
        _remove_version_dir(job)
        update_job.clear()
        update_job.log('更新已取消，暂存文件已删除', actor='app')
        return {'ok': True, 'job': update_job.public()}
    return {'ok': False, 'error': '现在没有可以取消的更新'}


def _remove_version_dir(job: dict) -> None:
    try:
        shutil.rmtree(version_dir(str(job.get('version') or '')), ignore_errors=True)
    except ValueError:
        return


# ─── Swapping (the script) ───────────


_WINDOWS_SCRIPT = r"""
param([int]$AppPid,[int]$WorkerPid,[string]$InstallRoot,[string]$Staged,[string]$Exe,[string]$Mode,
      [string]$Receipt,[string]$Log,[string]$Marker,[int]$VerifySeconds = 15)
$ErrorActionPreference = 'Stop'
function Write-Log([string]$Line) {
  try { Add-Content -LiteralPath $Log -Value ((Get-Date).ToString('s') + ' ' + $Line) } catch {}
}
try { Set-Content -LiteralPath $Receipt -Value ('started ' + (Get-Date).ToString('s')) } catch {}
try { Set-Content -LiteralPath $Marker -Value ('' + $PID) } catch {}
Write-Log ('swapper: start app=' + $AppPid + ' worker=' + $WorkerPid + ' mode=' + $Mode)
foreach ($peer in @($AppPid, $WorkerPid)) {
  if ($peer -gt 0) { try { Wait-Process -Id $peer -Timeout 300 -ErrorAction SilentlyContinue } catch {} }
}
Start-Sleep -Milliseconds 500
$targetRoot = if ($Mode -eq 'app') { Join-Path $InstallRoot 'app' } else { $InstallRoot }
New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
$previous = Join-Path $InstallRoot 'app.previous'
if (Test-Path -LiteralPath $previous) { Remove-Item -LiteralPath $previous -Recurse -Force }
New-Item -ItemType Directory -Force -Path $previous | Out-Null
$preserve = @('Data','data','logs','mplconfig','components','install-manifest.json',
  'bert_models','portable.txt','data-root.txt','instance.json','webview-profile',
  'drivers','updates','app.previous')
$moved = @()
$added = @()
function Try-Step([scriptblock]$Action) {
  for ($i = 0; $i -lt 40; $i++) {
    try { & $Action; return $true } catch { Start-Sleep -Milliseconds 500 }
  }
  return $false
}
function Remove-IfExists([string]$Path) {
  if (Test-Path -LiteralPath $Path) {
    Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
  }
}
function Restore-Program {
  foreach ($name in $added) { Remove-IfExists (Join-Path $targetRoot $name) }
  foreach ($name in $moved) {
    $backup = Join-Path $previous $name
    $target = Join-Path $targetRoot $name
    if (Test-Path -LiteralPath $backup) {
      Remove-IfExists $target
      Move-Item -LiteralPath $backup -Destination $target -Force
    }
  }
}
try {
  Get-ChildItem -LiteralPath $Staged -Force | ForEach-Object {
    $name = $_.Name
    $source = $_.FullName
    if ($preserve -contains $name) { return }
    $old = Join-Path $targetRoot $name
    if (Test-Path -LiteralPath $old) {
      if (-not (Try-Step { Move-Item -LiteralPath $old -Destination (Join-Path $previous $name) -Force })) {
        throw ('cannot move old ' + $name)
      }
      $moved += $name
    }
    if (-not (Try-Step { Copy-Item -LiteralPath $source -Destination $old -Recurse -Force })) {
      throw ('cannot write new ' + $name)
    }
    $added += $name
  }
} catch {
  Write-Log ('swapper: replace failed, rolling back: ' + $_.Exception.Message)
  Restore-Program
  Start-Process -FilePath $Exe
  try { Remove-Item -LiteralPath $Marker -Force -ErrorAction SilentlyContinue } catch {}
  exit 1
}
Write-Log 'swapper: files replaced, starting the new build'
$new = Start-Process -FilePath $Exe -PassThru
Start-Sleep -Seconds $VerifySeconds
$alive = $false
try { $new.Refresh(); $alive = -not $new.HasExited } catch { $alive = $false }
if (-not $alive) {
  Write-Log 'swapper: the new build exited right after launch, rolling back'
  Restore-Program
  Start-Process -FilePath $Exe
  try { Remove-Item -LiteralPath $Marker -Force -ErrorAction SilentlyContinue } catch {}
  exit 1
}
Write-Log 'swapper: new build running'
try { Remove-Item -LiteralPath $Marker -Force -ErrorAction SilentlyContinue } catch {}
"""

_MACOS_SCRIPT = """#!/bin/bash
# Replace the .app, verify the new build stays up, and roll back otherwise.
# The receipt is written FIRST: the app waits for it before it ends itself, so a script that
# cannot run is a named refusal instead of a program that closes and never comes back.
set -u
APP_PID="$1"
WORKER_PID="$2"
APP="$3"
STAGED="$4"
RECEIPT="$5"
LOG="$6"
MARKER="$7"
VERIFY="${8:-15}"

log() { printf '%s %s\\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$1" >> "$LOG" 2>/dev/null || true; }
printf 'started %s\\n' "$(date '+%Y-%m-%dT%H:%M:%S')" > "$RECEIPT" 2>/dev/null || true
printf '%s\\n' "$$" > "$MARKER" 2>/dev/null || true
log "swapper: start app=$APP_PID worker=$WORKER_PID"

for peer in "$APP_PID" "$WORKER_PID"; do
  if [ "${peer:-0}" -gt 0 ] 2>/dev/null; then
    while kill -0 "$peer" 2>/dev/null; do sleep 0.5; done
  fi
done
sleep 0.5

rollback() {
  log "swapper: rolling back: $1"
  rm -rf "$APP"
  if [ -d "$APP.previous" ]; then mv "$APP.previous" "$APP"; fi
  open "$APP" 2>/dev/null || true
  rm -f "$MARKER"
  exit 1
}

rm -rf "$APP.previous"
if ! mv "$APP" "$APP.previous"; then log 'swapper: cannot move the old bundle'; exit 1; fi
if ! ditto "$STAGED" "$APP"; then rollback 'ditto failed'; fi
log 'swapper: files replaced, starting the new build'
if ! open "$APP"; then rollback 'open failed'; fi
sleep "$VERIFY"
if ! pgrep -f "$APP/Contents/MacOS/" >/dev/null 2>&1; then rollback 'the new build is not running'; fi
log 'swapper: new build running'
rm -f "$MARKER"
"""


def _writable(path: Path) -> bool:
    try:
        probe = path / '.update-write-test'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
        return True
    except OSError:
        return False


def _swap_targets() -> dict:
    """Where the swap would write, or the named reason it may not."""
    mode, root, exe = install_layout()
    if not root or not exe.exists():
        return {'ok': False, 'error': '无法定位当前安装目录'}
    if mode == 'macapp':
        writable = _writable(root.parent)
    elif mode == 'app':
        writable = _writable(root) and _writable(root / 'app')
    else:
        writable = _writable(root)
    if not writable:
        return {'ok': False, 'error': '安装目录不可写；请用安装器更新，或把程序放到有写权限的文件夹'}
    expected = {'macapp': 'darwin'}.get(mode, 'win32')
    if machine.platform_name() != expected:
        return {'ok': False, 'error': '当前平台不支持应用内更新'}
    return {'ok': True, 'mode': mode, 'root': root, 'exe': exe}


def _spawn_script(script: Path, args: list[str]) -> int:
    """Run the swapper so it OUTLIVES this server, on every OS.

    ``popen_kwargs(detached=True)`` answers both halves (Windows creation flags, POSIX
    ``start_new_session``) from one place — and, importantly, no longer asks for
    ``DETACHED_PROCESS``, which killed the console child before its first statement.
    """
    if machine.platform_name() == 'win32':
        command = procs.powershell_command(str(script), args)
    else:
        command = ['/bin/bash', str(script), *args]
    child = subprocess.Popen(command, close_fds=True, **procs.popen_kwargs(detached=True))
    return int(child.pid)


def _await_helper(receipt: Path, timeout: float = HELPER_TIMEOUT) -> bool:
    """Wait for the swapper's own receipt: proof that the script really is running."""
    deadline = time.monotonic() + max(0.1, float(timeout))
    while time.monotonic() < deadline:
        if receipt.exists():
            return True
        time.sleep(0.1)
    return False


def spawn_swapper(job: dict, *, wait: bool) -> dict:
    """Write and start the per-OS swap script for a staged job.

    ``wait`` is the difference between the two callers: the 重启 button waits for the receipt and
    refuses on silence (the window is still open, so the user can be told); a window close cannot
    wait, and a swapper that fails to start there leaves the job staged for the next launch.
    """
    target = _swap_targets()
    if not target.get('ok'):
        return target
    staged = Path(str(job.get('staged') or ''))
    if not staged.is_dir():
        return {'ok': False, 'error': '更新包已经不在了，请重新下载'}
    try:
        script_dir = version_dir(str(job.get('version') or ''))
    except ValueError as exc:
        return {'ok': False, 'error': str(exc)}
    script_dir.mkdir(parents=True, exist_ok=True)
    receipt = script_dir / 'helper.started'
    receipt.unlink(missing_ok=True)
    marker = update_job.marker_file()
    log_path = update_job.log_file()
    root = Path(str(target['root']))
    exe = Path(str(target['exe']))
    mode = str(target['mode'])
    app_pid = int(job.get('owner_pid') or os.getpid())
    worker_pid = int(job.get('worker_pid') or 0)
    if machine.platform_name() == 'win32':
        script = script_dir / 'apply.ps1'
        script.write_text(_WINDOWS_SCRIPT, encoding='utf-8')
        args = [
            '-AppPid',
            str(app_pid),
            '-WorkerPid',
            str(worker_pid),
            '-InstallRoot',
            str(root),
            '-Staged',
            str(staged),
            '-Exe',
            str(exe),
            '-Mode',
            mode,
            '-Receipt',
            str(receipt),
            '-Log',
            str(log_path),
            '-Marker',
            str(marker),
        ]
    else:
        script = script_dir / 'apply.sh'
        script.write_text(_MACOS_SCRIPT, encoding='utf-8')
        script.chmod(0o755)
        args = [str(app_pid), str(worker_pid), str(root), str(staged), str(receipt), str(log_path), str(marker)]
    try:
        pid = _spawn_script(script, args)
    except OSError as exc:
        update_job.log(f'替换脚本没能启动：{exc}', actor='app')
        return {'ok': False, 'error': f'替换脚本没能启动：{exc}'}
    update_job.write(swapper_pid=pid, state=update_job.STATE_APPLYING)
    update_job.log(f'替换脚本已启动 pid={pid}', actor='app')
    if wait and not _await_helper(receipt):
        update_job.write(state=update_job.STATE_STAGED, swapper_pid=0)
        update_job.log('替换脚本 10 秒内没有回执，已取消本次更新', actor='app')
        return {'ok': False, 'error': '更新程序没能启动（10 秒内没有回执）；已取消本次更新，程序不会退出'}
    return {'ok': True, 'restarting': True}


def request_restart() -> dict:
    """Hand a staged job to the swapper and ask for the restart."""
    job = update_job.read()
    if job.get('state') == update_job.STATE_APPLYING:
        if procs.process_alive(int(job.get('swapper_pid') or 0)):
            return {'ok': True, 'restarting': True}
        job = update_job.fail('swap_lost', '替换脚本已经退出，更新没有完成，请重试')
    if job.get('state') != update_job.STATE_STAGED:
        return {'ok': False, 'error': '更新包还没有下载完成'}
    return spawn_swapper(job, wait=True)


def on_app_close() -> None:
    """The window is going away: hand a staged update to the swapper first.

    This is the one place where "closing the window quits the program" and "the update must still
    finish" meet. The job already holds the user's consent, the package is verified, and the
    swapper outlives this process by construction — so the close simply gives it the go-ahead
    instead of cancelling anything. A failure is logged (never a dialog in a closing window): the
    job stays ``staged`` and the next launch offers the restart again.
    """
    try:
        job = update_job.read()
        if job.get('state') != update_job.STATE_STAGED:
            return
        result = spawn_swapper(job, wait=False)
        if result.get('ok'):
            update_job.log('窗口关闭，已把更新交给替换脚本', actor='app')
        else:
            update_job.log(f'窗口关闭时没能启动替换脚本：{result.get("error", "")}', actor='app')
    except Exception:  # a close must never fail on the updater's account
        return
