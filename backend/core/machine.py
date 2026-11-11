"""Where the outside-world tools this app depends on live on this machine.

The packaged build carries its own Python and every library it imports, but five things always
belong to the machine rather than to the app: Chrome (which crawls), chromedriver (which drives it),
xelatex (which typesets a paper), an Ollama daemon (which answers an LLM node) and a Node runtime
plus the CatBus adapter (which is the second crawl backend). Each probe lives here exactly once,
because the desktop launcher's startup self-check and a crawler's refusal have to answer with the
same facts — two lists of candidate paths is how a user ends up reading "Chrome not found" on the
same machine where a crawl starts fine.
"""

from __future__ import annotations

import ntpath
import os
import platform
import posixpath
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit


def _path_shape(os_name: str) -> tuple:
    """The joiner and the ``PATH`` separator a GIVEN operating system uses.

    ``os.path`` would answer with the separator of the machine asking, which is right at run time and
    wrong as a test: a Windows box asking "what would a Linux box look for" has to get Linux-shaped
    strings back, or every cloud candidate path is unverifiable from here.
    """
    if os_name == 'win32':
        return ntpath.join, ';'
    return posixpath.join, ':'


#: Environment variables that may name Chrome, most-explicit first. A portable copy of Chrome, or a
# second version installed outside the usual roots, is reachable only through one of these. On a Linux
# container this is the normal case: the image installs chromium and exports ``CHROME_BIN``.
CHROME_ENV_VARS = ('CHROME_PATH', 'CHROME_BIN')

#: Windows registry-free install roots. ``LOCALAPPDATA`` is the per-user install, which is what a
# machine without admin rights gets.
CHROME_WINDOWS_ROOTS = ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')

#: Absolute locations, per OS, that no environment variable names. The names are the package names
# a user actually installed (``google-chrome-stable``, ``chromium-browser``), so a missing entry is a
# fact about that machine and not a bug here — but so is a missing LIST: one list per OS is why a
# cloud box with /usr/bin/chromium used to answer “未找到 Chrome” while the crawl worked on Windows.
CHROME_PATHS = {
    'linux': (
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
        '/opt/google/chrome/chrome',
        '/usr/lib/chromium/chromium',
        '/snap/bin/chromium',
    ),
    'darwin': (
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
    ),
    'win32': (),
}

#: Executable names looked up on ``PATH``, per OS. ``chrome`` alone is not searched: on Windows that
# name is Edge's legacy stub, and the app refuses to answer with a browser nobody chose.
CHROME_PATH_NAMES = {
    'linux': ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'),
    'darwin': ('google-chrome', 'chromium'),
    'win32': ('chrome.exe',),
}

#: Ollama's own default port, used when a configured address carries none.
OLLAMA_DEFAULT_PORT = 11434

#: What ``navigator.platform`` reads as on a real desktop Chrome of each system, keyed by the same
#: three values as every other table here.
#:
#: This exists because the headless disguise overrides the platform alongside the user agent, and a
#: hardcoded ``'Win32'`` is a *manufactured mismatch* on the two other systems this project ships to:
#: the UA is read back from this very Chrome (so a Linux box keeps ``X1; Linux x86_64`` in it) while
#: the override would answer ``Win32`` — and #148's measurement is that an invented value is itself
#: the tell. Windows reports ``Win32`` even on 64-bit builds; that is not a typo to "fix".
NAVIGATOR_PLATFORMS = {
    'win32': 'Win32',
    'linux': 'Linux x86_64',
    'darwin': 'MacIntel',
}


def navigator_platform(system: str | None = None) -> str:
    """The ``navigator.platform`` value a real Chrome reports on THIS operating system."""
    return NAVIGATOR_PLATFORMS[platform_name(system)]


def chrome_executable_name(system: str | None = None) -> str:
    """The browser executable a user on this system has to point 设置 at when nothing is found.

    Read off :data:`CHROME_PATH_NAMES` — the table the probe itself uses — so a refusal can never
    name a file this machine would not have found anyway (a Linux sentence saying ``chrome.exe`` is
    a remedy nobody can act on, and the bilingual parity check cannot see it).
    """
    names = CHROME_PATH_NAMES.get(platform_name(system)) or ()
    return names[0] if names else 'Chrome'


def driver_executable_name(system: str | None = None) -> str:
    """The chromedriver file name for this OS (one table, not a ``.exe`` written in a probe)."""
    names = DRIVER_FILE_NAMES.get(platform_name(system)) or ()
    return names[0] if names else 'chromedriver'


def node_executable_name(system: str | None = None) -> str:
    """The Node file name for this OS, from the same table the Node probe uses."""
    names = NODE_PATH_NAMES.get(platform_name(system)) or ()
    return names[0] if names else 'node'


def browser_version(binary: str, system: str | None = None) -> str:
    """A browser's version text, read WITHOUT starting the browser.

    ``chrome.exe --version`` prints nothing on Windows (a GUI executable has no console) and can
    hand its argument to a browser that is already running — measured: it opened a tab in the user's
    session. A probe that launches the browser is a probe that changes the machine, so Windows reads
    the executable's version resource, which is the same number the other two systems print.
    """
    if not binary:
        return ''
    if platform_name(system) == 'win32':
        return _windows_file_version(binary)
    return _console_version(binary)


def _windows_file_version(path: str) -> str:
    """``major.minor.build.patch`` from a Windows executable's version resource, or ''."""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:  # pragma: no cover - ctypes ships with CPython on every platform we run
        return ''
    try:
        version = ctypes.WinDLL('version')
        handle = wintypes.DWORD()
        target = ctypes.c_wchar_p(path)
        size = version.GetFileVersionInfoSizeW(target, ctypes.byref(handle))
        if not size:
            return ''
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(target, 0, size, buffer):
            return ''
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version.VerQueryValueW(buffer, ctypes.c_wchar_p('\\'), ctypes.byref(pointer), ctypes.byref(length)):
            return ''
        # VS_FIXEDFILEINFO: signature, struct version, then the two halves of the file version.
        fields = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
        high, low = fields[2], fields[3]
        return f'{high >> 16}.{high & 0xFFFF}.{low >> 16}.{low & 0xFFFF}'
    except (AttributeError, OSError, ValueError):
        return ''


def _console_version(binary: str) -> str:
    """``binary --version`` on a system whose browser is a console child of the shell."""
    import subprocess

    from core.procs import popen_kwargs

    try:
        result = subprocess.run([binary, '--version'], capture_output=True, timeout=10, check=False, **popen_kwargs())
    except (OSError, subprocess.SubprocessError):
        return ''
    text = ((result.stdout or b'') + (result.stderr or b'')).decode('utf-8', errors='replace').strip()
    return text.splitlines()[0] if text else ''


def installer_components_root() -> str:
    """The installer's component directory for this process, or '' when it has none.

    The launcher exports ``CIXI_COMPONENTS_DIR``. A source checkout has no launcher, so the same
    ``<data root>/components`` the component manager writes is used; a frozen bundle without the
    export has no safe guess and answers ''. This mirrors ``services.components.paths`` without
    importing it (that module imports this one).
    """
    override = str(os.environ.get('CIXI_COMPONENTS_DIR') or '').strip()
    if override:
        return override
    if is_frozen():
        return ''
    base = str(os.environ.get('CRAWLER_DATA_ROOT') or '').strip()
    if not base:
        base = str(Path(__file__).resolve().parents[2])
    # ``Config.DATA_DIR`` is ``<data root>/data``; the component manager's source layout is
    # ``<data root>/data/components`` (``services.components.paths.components_root``).
    return str(Path(base) / 'data' / 'components')


def installer_components_only() -> bool:
    """Whether this process may use only the installer's own components.

    The desktop launcher freezes the user's ``component_source`` choice in
    ``CIXI_COMPONENT_SOURCE`` before :mod:`core.config` is imported. In that mode the machine's
    own Chrome/Node/CatBus is NOT a fallback — a component the installer did not install is
    reported by name, because silently using a different browser or runtime would contradict the
    switch the user set. ``system`` restores the per-OS candidate tables.

    It is also an *installer fact*: a portable zip, a source checkout, the offline Setup and a
    cloud container carry no ``install-manifest.json``. Their component source is necessarily 本机;
    returning True there would refuse every crawl with “安装器未安装” on machines where the online
    installer was never used.
    """
    if str(os.environ.get('CIXI_COMPONENT_SOURCE') or '').strip().lower() == 'system':
        return False
    root = installer_components_root()
    if not root:
        return False
    return os.path.isfile(os.path.join(os.path.dirname(root), 'install-manifest.json'))


def inside_installer_components(path: str) -> bool:
    """Whether *path* belongs to the component tree the launcher exported.

    The exported environment variables are the only installer-owned paths this process may use in
    installer mode. Checking them against ``CIXI_COMPONENTS_DIR`` (rather than trusting the variable
    name) is what stops a stale ``CHROME_PATH``/``CIXI_NODE_BIN`` a user or an old launcher left in
    the environment from standing in for a component the installer never placed.
    """
    root = installer_components_root()
    if not root or not path:
        return False
    try:
        root_norm = os.path.normcase(os.path.realpath(root))
        path_norm = os.path.normcase(os.path.realpath(str(path)))
    except (OSError, ValueError):
        return False
    return path_norm == root_norm or path_norm.startswith(root_norm + os.sep)


def _installer_export(values) -> list[str]:
    """Exported paths that are real executables inside the installer's component tree."""
    return [path for path in values if path and _is_executable(path) and inside_installer_components(path)]


def platform_name(system: str | None = None) -> str:
    """The OS key this module's tables are indexed by, normalized onto three values."""
    name = str(sys.platform if system is None else system)
    if name.startswith('linux'):
        return 'linux'
    if name.startswith('darwin'):
        return 'darwin'
    if name.startswith(('win', 'cygwin', 'msys')):
        return 'win32'
    return name


def platform_asset_key(system: str | None = None, machine: str | None = None) -> str:
    """The catalogue key for THIS OS *and* CPU, because a Mac app is per-architecture.

    ``platform_name`` stays one value per OS: every user-facing table (Chrome candidates, remedies,
    navigator.platform) is the same on both Macs. A downloadable archive is not — Chrome for Testing
    ships ``mac-arm64`` and ``mac-x64`` separately, and installing the wrong one produces a binary
    that cannot start. Windows keeps the bare ``win32`` key: its release is one x64 build, and the
    existing catalogue must keep validating unchanged.
    """
    os_name = platform_name(system)
    if os_name != 'darwin':
        return os_name
    value = str(platform.machine() if machine is None else machine).lower()
    if value in ('arm64', 'aarch64'):
        return 'darwin-arm64'
    if value in ('x86_64', 'amd64', 'i386', 'x86'):
        return 'darwin-x64'
    return 'darwin'


def is_windows(system: str | None = None) -> bool:
    """Whether this machine can be asked for a window, a foreground app or a system certificate store.

    One answer for every “Windows 才有的能力” gate, so a refusal and the UI that hides the entry
    cannot disagree about which platform the user is on.
    """
    return platform_name(system) == 'win32'


def app_payload_files(system: str | None = None) -> tuple[str, ...]:
    """The entries a staged application payload MUST contain on this OS.

    A hash proves the bytes are the ones the manifest named; it says nothing about what those bytes
    are. The updater refuses a package without these, so a mis-pointed manifest cannot be copied
    over an install and leave a program-shaped hole. The names live here (the per-OS table home)
    because ``.exe`` is a Windows fact, and ``tests/unit/crawlers/test_platform_rules.py`` refuses
    it anywhere else.
    """
    if is_windows(system):
        return ('CaiXiHui.exe', '_internal')
    return ()


def is_frozen() -> bool:
    """Whether this is the packaged desktop app rather than a source checkout.

    PyInstaller sets ``sys.frozen`` on the running bundle. The answer decides what a refusal is
    allowed to tell the user to DO: "pip install mitmproxy" is an instruction in a checkout and
    nonsense in an exe that has no pip and no interpreter anyone can write to.
    """
    return bool(getattr(sys, 'frozen', False))


def chrome_candidate_paths(system: str | None = None, env: dict | None = None) -> list[str]:
    """Every place Chrome could be on this OS, most-explicit first, **without** touching the disk.

    Split out of :func:`chrome_candidates` because a Windows box cannot create
    ``/usr/bin/google-chrome``: the list is the contract that says Linux and macOS were thought about,
    and only the filtering needs the real filesystem.

    The separators are the TARGET's, not this process's: a ``PATH`` of a Linux server is colon-split and
    its paths are slash-joined even when this function is being asked about Linux from a Windows test
    runner. Reading ``os.path``/``os.pathsep`` here would make the answer depend on which machine asked.
    """
    env = os.environ if env is None else env
    os_name = platform_name(system)
    join, sep = _path_shape(os_name)
    paths = [str(env.get(name) or '').strip() for name in CHROME_ENV_VARS]
    if os_name == 'win32':
        for base in (env.get(root) for root in CHROME_WINDOWS_ROOTS):
            if base:
                paths.append(join(base, 'Google', 'Chrome', 'Application', 'chrome.exe'))
    else:
        paths.extend(CHROME_PATHS.get(os_name, ()))
        home = str(env.get('HOME') or '').strip()
        if home and os_name == 'darwin':
            paths.append(join(home, 'Applications', 'Google Chrome.app', 'Contents', 'MacOS', 'Google Chrome'))
    for directory in str(env.get('PATH') or '').split(sep):
        for name in CHROME_PATH_NAMES.get(os_name, ()):
            if directory:
                paths.append(join(directory, name))
    return [path for path in paths if path]


def _is_executable(path: str) -> bool:
    """A file that exists — and, off Windows, is marked runnable.

    A Chrome found on ``PATH`` that is not executable would raise ``PermissionError`` from the
    driver, which reads as “Chrome 启动失败” rather than the truth about the file's mode.
    """
    if not os.path.isfile(path):
        return False
    return os.name == 'nt' or os.access(path, os.X_OK)


def chrome_candidates(env: dict | None = None, system: str | None = None) -> list[str]:
    """Chrome executables that actually exist on this OS's disk, most-explicit first.

    The Windows roots are environment-variable driven; Linux and macOS have no such variable, so their
    list is literal plus a ``PATH`` scan (a container installs chromium with apt, a Mac ships a .app
    bundle). This used to be Windows-only, which made every cloud crawl refuse for a reason the machine
    could not act on — the Docker image worked only because it exports ``CHROME_BIN``.
    """
    return [path for path in dict.fromkeys(chrome_candidate_paths(system, env)) if _is_executable(path)]


def find_chrome(explicit: str = '', env: dict | None = None, system: str | None = None) -> str:
    """The browser to launch, or '' when this machine has nothing to launch.

    ``explicit`` is the user's own setting: when it is filled in it is the ANSWER, not a hint — an
    explicit path that does not exist returns '' rather than falling back to a found install, so
    the caller can name the typo instead of silently crawling a different Chrome than the one the
    user pointed at (a copied-profile Chrome is a second device to a site's risk control).
    In installer mode the manifest is the authority and is checked BEFORE ``explicit``: an old
    configured/exported path must not shadow the version the component manager currently records.
    """
    if installer_components_only():
        source = os.environ if env is None else env
        candidates = [
            installer_component_path('chrome'),
            *(str(source.get(name) or '').strip() for name in CHROME_ENV_VARS),
            str(explicit or '').strip(),
        ]
        found = [path for path in candidates if path and _is_executable(path) and inside_installer_components(path)]
        return found[0] if found else ''
    explicit = str(explicit or '').strip()
    if explicit:
        return explicit if _is_executable(explicit) else ''
    candidates = chrome_candidates(env, system)
    return candidates[0] if candidates else ''


#: The families of “缺它怎么办” answer, each with one catalogue key per OS. A remedy is a different
# sentence on each platform (Windows adds a font feature, Linux installs a distro package, macOS often
# already has the font), so the sentence is chosen here and written in ``i18n`` — and
# ``tests/unit/foundation/test_missing_dependency_messages.py`` walks THIS list times every platform, because a
# computed key nobody enumerated is how a refusal prints its own key.
REMEDY_PREFIXES = ('deps.systemFont', 'deps.texFont', 'deps.texPackage', 'deps.xelatex')
REMEDY_PLATFORMS = ('win32', 'linux', 'darwin')


def remedy_key(prefix: str, system: str | None = None) -> str:
    """``deps.texPackage`` → ``deps.texPackage.linux``: the per-OS half of a refusal."""
    return f'{prefix}.{platform_name(system)}'


def remedy(prefix: str, system: str | None = None) -> str:
    """What to install on THIS operating system, read from the bilingual catalogue.

    Used inside a “缺 X” sentence: telling a Linux user to open the MiKTeX console, or a Windows user
    to ``apt-get install``, is a refusal nobody can act on — and the catalogue's parity check cannot see
    it, because both languages said the same Windows thing.
    """
    from i18n import t

    return t(remedy_key(prefix, system))


#: A probe string that survives every Chinese-capable codepage and fails under ASCII/latin-1 — which is
# exactly the question asked below. Windows' cp936 console encodes it; a ``python:3.11-slim`` container
# with no ``LANG`` (ANSI_X3.4-1968) does not.
_HAN_PROBE = '中文'


def can_write_chinese(stream) -> bool:
    """Whether this stream's encoding represents Han characters at all."""
    encoding = str(getattr(stream, 'encoding', '') or '')
    if not encoding:
        return False
    try:
        _HAN_PROBE.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def pin_console(stream=None, name: str = 'stdout') -> str:
    """Give one console stream a chance to carry the app's own words; return the encoding it HAD, or ''.

    The program's log lines, node names and refusals are Chinese, and a stream's encoding belongs to the
    machine: a container started without ``LANG`` gets pure ASCII, where the first Chinese line raises
    ``UnicodeEncodeError`` **inside the logging handler** — logging swallows that, so the line is simply
    gone and the run looks quiet. Forcing UTF-8 unconditionally is not the answer either: a Chinese
    Windows console (cp936) writes Han correctly and would be garbled by the switch. So the rule is "only
    step in when the stream cannot write the language the program speaks", plus ``errors='replace'``
    always, because one unmappable glyph in scraped text must not cost the rest of the line.

    '' means nothing was changed (already able, or a stream with no ``reconfigure`` — a captured pipe in a
    test runner, an embedded interpreter, this app's own log tee).
    """
    target = stream if stream is not None else getattr(sys, name, None)
    reconfigure = getattr(target, 'reconfigure', None)
    if target is None or reconfigure is None:
        return ''
    before = str(getattr(target, 'encoding', '') or '')
    if can_write_chinese(target):
        reconfigure(errors='replace')
        return ''
    reconfigure(encoding='utf-8', errors='replace')
    return before or '?'


def ollama_endpoint(endpoint: str) -> tuple[str, int]:
    """(host, port) of a configured Ollama address: ``http://host:port/path`` and a bare ``host`` both work."""
    text = str(endpoint or '').strip() or 'localhost'
    parts = urlsplit(text if '://' in text else f'http://{text}')
    host = parts.hostname or '127.0.0.1'
    if parts.port:
        return host, parts.port
    return host, 443 if parts.scheme == 'https' else OLLAMA_DEFAULT_PORT


def ollama_reachable(endpoint: str, timeout: float = 0.25) -> bool:
    """Whether the configured Ollama address accepts a connection — a TCP probe, never a completion.

    Short by design: this answers "is a daemon listening" for a startup line and a pre-run check,
    and a daemon that is started but still loading a model answers on the port immediately.
    """
    host, port = ollama_endpoint(endpoint)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ─── Node runtime and the CatBus backend ─────────────────────────────────────────────────────


#: Environment variables that may name a Node runtime, most-explicit first. nvm, a distro package
# and a container image each put ``node`` somewhere different, so an explicit name is the answer and
# the tables below are only the fallback — exactly like ``CHROME_ENV_VARS`` above.
NODE_ENV_VARS = ('CIXI_NODE_BIN', 'NODE_BIN')

#: Windows roots that hold a ``nodejs`` install. ``LOCALAPPDATA`` is the per-user (nvm-windows) one,
# which is what a machine without admin rights gets.
NODE_WINDOWS_ROOTS = ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')

#: Absolute Node locations per OS that no environment variable names.
NODE_PATHS = {
    'linux': ('/usr/bin/node', '/usr/local/bin/node', '/snap/bin/node'),
    'darwin': ('/usr/local/bin/node', '/opt/homebrew/bin/node'),
    'win32': (),
}

#: Names looked up on ``PATH``, per OS. Windows' file is ``node.exe``; the other two have no suffix,
# and a test that pins ``node.exe`` as the answer would pass on the machine it was written on only.
NODE_PATH_NAMES = {
    'linux': ('node',),
    'darwin': ('node',),
    'win32': ('node.exe',),
}

#: Driver and Node file names a machine's own install uses. The installer/probe ask this table
#: instead of spelling ``.exe`` outside the per-OS facts (see ``tests/unit/crawlers``).
DRIVER_FILE_NAMES = {'linux': ('chromedriver',), 'darwin': ('chromedriver',), 'win32': ('chromedriver.exe',)}

#: Where an installer component keeps its executable INSIDE its version folder. This is not the
#: same question as ``chrome_executable_name``: that one is a name a user types on PATH, while this
#: is the payload's own layout. macOS Chrome for Testing is an ``.app`` whose binary is three
#: folders down, and Node's tarball puts ``node`` under ``bin/``; probing ``chrome`` or ``node`` in
#: the component root would report a correctly installed component as missing.
COMPONENT_PAYLOAD_PATHS = {
    'chrome': {
        'darwin': ('Google Chrome for Testing.app', 'Contents', 'MacOS', 'Google Chrome for Testing'),
        'linux': ('chrome',),
        'win32': ('chrome.exe',),
    },
    'chromedriver': {
        'darwin': ('chromedriver',),
        'linux': ('chromedriver',),
        'win32': ('chromedriver.exe',),
    },
    'node': {
        'darwin': ('bin', 'node'),
        'linux': ('bin', 'node'),
        'win32': ('node.exe',),
    },
    'catbus': {
        'darwin': ('dist', 'integrations', 'crawler-workflow', 'cli.js'),
        'linux': ('dist', 'integrations', 'crawler-workflow', 'cli.js'),
        'win32': ('dist', 'integrations', 'crawler-workflow', 'cli.js'),
    },
}


def component_payload_path(component_id: str, system: str | None = None) -> str:
    """The POSIX relative path of a component's executable, or ``''`` for an unknown component."""
    parts = COMPONENT_PAYLOAD_PATHS.get(str(component_id or ''), {}).get(platform_name(system))
    return posixpath.join(*parts) if parts else ''


def installer_component_path(component_id: str) -> str:
    """The installer's current payload for *component_id*, or '' when it has none.

    The manifest is the record the component manager maintains and the launcher exports; reading
    it here means a run still finds the installed copy when an export is missing or stale, and the
    probe and the crawler cannot disagree about which Chrome/Node/CatBus exists.
    """
    root = installer_components_root()
    if not root:
        return ''
    try:
        from services.components.manifest import Manifest, ManifestError
    except ImportError:
        return ''
    try:
        installed = Manifest(Path(root).parent).load().path_of(component_id)
    except (OSError, ValueError, ManifestError):
        return ''
    if installed is None:
        return ''
    relative = component_payload_path(component_id)
    candidate = installed / relative if relative else None
    if candidate is None:
        return ''
    inside = inside_installer_components(str(candidate))
    usable = catbus_entry_usable(str(candidate)) if component_id == 'catbus' else _is_executable(str(candidate))
    return str(candidate) if inside and usable else ''


#: The Node releases CatBus' ``engines`` field accepts, split the way a semver range actually reads:
# ``^22.22.2 || ^24.15.0`` are two *major-bound* floors (a 23.x or 25.x runtime is in neither, even
# though it is numerically larger than 22.22.2), and ``>=26.0.0`` is the one open-ended floor. Written
# as a single ``any(v >= floor)`` the gate would wave an unsupported major through, and the failure it
# prevents — a syntax error inside CatBus that names nothing — is exactly what the check exists for.
NODE_CARET_FLOORS = {22: (22, 22, 2), 24: (24, 15, 0)}
NODE_OPEN_FLOOR = (26, 0, 0)

#: The adapter entry inside a CatBus install or checkout. It is deliberately the ``.js`` and not the
# ``catbus-crawler-workflow`` bin: a global npm install drops a ``.cmd`` shim on Windows and a shell
# shim on the other two, and one executable shape across three systems is the whole point.
CATBUS_ENTRY = ('dist', 'integrations', 'crawler-workflow', 'cli.js')

#: Suffixes that mean "Node reads this file" rather than "the machine runs this file". One list,
# shared with the bridge's argv builder, so the disk test below and the spawn there cannot disagree
# about what kind of entry the user pointed at.
CATBUS_SCRIPT_SUFFIXES = ('.js', '.mjs', '.cjs')

#: Suffixes that mean "TypeScript source". Node cannot be pointed at these: type stripping drops the
#: annotations but does NOT rewrite the ``./errors.js`` specifiers CatBus' sources use, so the spawn
#: dies with ``ERR_MODULE_NOT_FOUND`` naming a file the user never mentioned. The build's ``dist``
#: twin is the entry, and :func:`catbus_source_twin` maps one to the other.
CATBUS_SOURCE_SUFFIXES = ('.ts', '.tsx', '.mts', '.cts')

#: The build output for each source suffix: CatBus' ``src/**`` compiles into ``dist/**`` unchanged
# apart from the extension.
CATBUS_BUILT_SUFFIX = {'.ts': '.js', '.tsx': '.js', '.mts': '.mjs', '.cts': '.cjs'}

#: The npm package that ships the adapter (its ``bin`` name is ``catbus``).
CATBUS_PACKAGE = 'catbus-cli'

#: Environment variables that name the adapter entry — a ``.js`` file, or any executable that runs
# it. Most-explicit first.
CATBUS_ENV_VARS = ('CIXI_CATBUS_CLI', 'CATBUS_CLI')

#: Environment variable naming a CatBus *source checkout*; the adapter is read straight out of it,
# which is how the app talks to a development copy of CatBus that was never npm-installed.
CATBUS_HOME_ENV = 'CATBUS_HOME'

#: System-wide npm global roots, per OS. ``win32`` has none: npm puts a user's global packages under
# ``%APPDATA%\npm``, which is environment-driven like the Chrome roots.
CATBUS_GLOBAL_LIBS = {
    'linux': ('/usr/local/lib/node_modules', '/usr/lib/node_modules'),
    'darwin': ('/usr/local/lib/node_modules', '/opt/homebrew/lib/node_modules'),
    'win32': (),
}

#: Roots a per-user npm prefix hangs off, per OS: ``$HOME/.npm-global`` on POSIX and
# ``%APPDATA%\npm`` on Windows — the two spellings a machine without admin rights gets.
CATBUS_USER_LIBS = {
    'linux': (('.npm-global', 'lib', 'node_modules'),),
    'darwin': (('.npm-global', 'lib', 'node_modules'),),
    'win32': (),
}


def node_candidate_paths(system: str | None = None, env: dict | None = None) -> list[str]:
    """Every place a Node runtime could be on this OS, most-explicit first, **without** touching the disk."""
    env = os.environ if env is None else env
    os_name = platform_name(system)
    join, sep = _path_shape(os_name)
    paths = [str(env.get(name) or '').strip() for name in NODE_ENV_VARS]
    paths.extend(NODE_PATHS.get(os_name, ()))
    if os_name == 'win32':
        for root in NODE_WINDOWS_ROOTS:
            base = str(env.get(root) or '').strip()
            if base:
                paths.append(join(base, 'nodejs', 'node.exe'))
    for directory in str(env.get('PATH') or '').split(sep):
        for name in NODE_PATH_NAMES.get(os_name, ()):
            if directory:
                paths.append(join(directory, name))
    return [path for path in paths if path]


def node_candidates(env: dict | None = None, system: str | None = None) -> list[str]:
    """Node runtimes that actually exist on this OS's disk, most-explicit first."""
    return [path for path in dict.fromkeys(node_candidate_paths(system, env)) if _is_executable(path)]


def find_node(explicit: str = '', env: dict | None = None, system: str | None = None) -> str:
    """The Node to run the CatBus adapter with, or '' when this machine has no Node at all.

    Like :func:`find_chrome`, an explicit setting that does not exist answers '' — the caller names
    the typo instead of quietly running a different runtime than the one the user pointed at — and
    in installer mode the manifest is checked before that setting.
    """
    if installer_components_only():
        source = os.environ if env is None else env
        candidates = [
            installer_component_path('node'),
            *(str(source.get(name) or '').strip() for name in NODE_ENV_VARS),
            str(explicit or '').strip(),
        ]
        found = [path for path in candidates if path and _is_executable(path) and inside_installer_components(path)]
        return found[0] if found else ''
    explicit = str(explicit or '').strip()
    if explicit:
        return explicit if _is_executable(explicit) else ''
    found = node_candidates(env, system)
    return found[0] if found else ''


def node_version_supported(text: str) -> bool:
    """Whether ``node -v`` output is a release CatBus declares it runs on.

    ``v24.21.0`` and a bare ``22.22.2`` both parse; anything unparseable is NOT supported, because an
    answer this side cannot read is not evidence that the runtime is new enough. The two caret ranges
    are checked by major, so an even-numbered release between them (23.x, 25.x) is refused the way the
    ``engines`` field refuses it — being newer than 22.22.2 is not the same as being in range.
    """
    digits = str(text or '').strip().lstrip('vV').split('-', 1)[0].split('.')
    try:
        version = tuple(int(part) for part in digits[:3])
    except ValueError:
        return False
    if len(version) < 3:
        return False
    floor = NODE_CARET_FLOORS.get(version[0])
    if floor is not None:
        return version >= floor
    return version >= NODE_OPEN_FLOOR


def catbus_candidate_paths(system: str | None = None, env: dict | None = None) -> list[str]:
    """Every place the CatBus adapter entry could be on this OS, most-explicit first, without the disk."""
    env = os.environ if env is None else env
    os_name = platform_name(system)
    join, sep = _path_shape(os_name)
    norm = ntpath.normpath if os_name == 'win32' else posixpath.normpath
    # A hand-written path may name the adapter file *or* the CatBus directory, and the two env
    # variables and the settings field all accept either spelling (see :func:`catbus_entry_at`).
    paths = [catbus_entry_at(env.get(name), os_name) for name in CATBUS_ENV_VARS]
    home = str(env.get(CATBUS_HOME_ENV) or '').strip()
    if home:
        paths.append(join(home, *CATBUS_ENTRY))
    paths.extend(join(root, CATBUS_PACKAGE, *CATBUS_ENTRY) for root in CATBUS_GLOBAL_LIBS.get(os_name, ()))
    # ``$HOME`` exists on POSIX; Windows keeps the per-user npm root in ``%APPDATA%`` instead.
    user_home = str(env.get('HOME') or '').strip()
    if os_name == 'win32':
        appdata = str(env.get('APPDATA') or '').strip()
        if appdata:
            paths.append(join(appdata, 'npm', 'node_modules', CATBUS_PACKAGE, *CATBUS_ENTRY))
    elif user_home:
        for parts in CATBUS_USER_LIBS.get(os_name, ()):
            paths.append(join(user_home, *parts, CATBUS_PACKAGE, *CATBUS_ENTRY))
    for directory in str(env.get('PATH') or '').split(sep):
        if not directory:
            continue
        # A POSIX npm prefix keeps packages in ``<prefix>/lib/node_modules`` while ``<prefix>/bin`` is
        # what is on PATH, so the parent of a ``bin`` directory is the one worth asking. Normalized, so
        # this candidate is the same string as the literal table above rather than a ``..`` twin of it.
        parent = norm(join(directory, '..', 'lib', 'node_modules'))
        paths.append(join(directory, CATBUS_PACKAGE, *CATBUS_ENTRY))
        paths.append(join(parent, CATBUS_PACKAGE, *CATBUS_ENTRY))
    return [path for path in paths if path]


def catbus_entry_usable(path: str) -> bool:
    """Whether this path can be the adapter: a script must be readable, a program must be runnable.

    :func:`_is_executable` is the wrong test for ``cli.js``. An npm-installed or git-checked-out JS
    file is mode 644 — Node *reads* it, the kernel never executes it — so demanding the executable bit
    reported "no CatBus" on every Linux and macOS box and silently removed the whole second backend
    from the panel. A path without a script suffix is a wrapper the bridge spawns directly, so it
    keeps the executable rule; there the mode is what decides whether the call works. TypeScript
    source is never usable, even on Windows where the “any file is a program” branch would wave it
    through: Node cannot resolve its build-style imports, and the spawn then fails with a stack
    trace naming an unrelated file instead of saying “this is source, build it”.
    """
    if not os.path.isfile(path):
        return False
    lowered = path.lower()
    if lowered.endswith(CATBUS_SOURCE_SUFFIXES):
        return False
    if lowered.endswith(CATBUS_SCRIPT_SUFFIXES):
        return os.access(path, os.R_OK)
    return os.name == 'nt' or os.access(path, os.X_OK)


def catbus_candidates(env: dict | None = None, system: str | None = None) -> list[str]:
    """CatBus adapter entries that actually exist on this OS's disk, most-explicit first."""
    return [path for path in dict.fromkeys(catbus_candidate_paths(system, env)) if catbus_entry_usable(path)]


def catbus_source_twin(path: str, system: str | None = None) -> str:
    """The built entry a TypeScript source path names, or '' when the path is not source.

    “Point it at the adapter” naturally means the file the checkout contains, and in a CatBus
    development copy that file is ``src/integrations/crawler-workflow/cli.ts``. Node cannot run it
    (see :data:`CATBUS_SOURCE_SUFFIXES`), so the honest answer is the twin the build produced:
    ``src`` becomes ``dist`` and the suffix becomes the one Node runs. Only the *last* ``src``
    segment is rewritten, because a checkout may itself live under a directory called ``src``.

    '' means "not a source path"; a non-empty answer may still not exist on disk, which is how the
    caller tells “build the checkout” apart from “no CatBus here at all”.
    """
    path = str(path or '').strip()
    if not path or not path.lower().endswith(CATBUS_SOURCE_SUFFIXES):
        return ''
    os_name = platform_name(system)
    mod = ntpath if os_name == 'win32' else posixpath
    norm = mod.normpath(path)
    suffix = mod.splitext(norm)[1].lower()
    drive, tail = mod.splitdrive(norm)
    rooted = tail.startswith(mod.sep)
    parts = [part for part in tail.split(mod.sep) if part]
    for index in range(len(parts) - 1, -1, -1):
        if parts[index].lower() == 'src':
            parts[index] = 'dist'
            break
    parts[-1] = mod.splitext(parts[-1])[0] + CATBUS_BUILT_SUFFIX[suffix]
    if drive or rooted:
        return mod.join(drive + mod.sep, *parts)
    return mod.join(*parts)


def catbus_entry_at(path: str, system: str | None = None) -> str:
    """The adapter entry a hand-written path points at: a file as given, a checkout root resolved.

    Both spellings are natural and both come from the settings panel: “指到那个 cli.js” and
    “指到 CatBus 的目录”. A directory is the second one, so it gains the one suffix that makes it
    the entry — which is also what ``CATBUS_HOME`` has always meant here. Joined with the TARGET's
    separator, so a Linux answer asked from this box still reads as a Linux path.

    A ``.ts`` path is source, never the entry, so it is answered with its built twin: pointing the
    box at ``src/.../cli.ts`` is what a developer does, and refusing it as “no CatBus” hid a
    checkout that had simply been built one directory over.
    """
    path = str(path or '').strip()
    if not path:
        return ''
    if os.path.isdir(path):
        join, _sep = _path_shape(platform_name(system))
        return join(path, *CATBUS_ENTRY)
    return catbus_source_twin(path, system) or path


def find_catbus_cli(explicit: str = '', env: dict | None = None, system: str | None = None) -> str:
    """The adapter entry to call, or '' when this machine has no CatBus.

    '' is a reason, not a failure: the CatBus backend then simply is not offered, and it is offered
    nowhere in the UI either (see ``services/ingest/catbus.py``).
    """
    if installer_components_only():
        source = os.environ if env is None else env
        candidates = [
            installer_component_path('catbus'),
            *(catbus_entry_at(source.get(name), system) for name in CATBUS_ENV_VARS),
            catbus_entry_at(explicit, system),
        ]
        found = [
            path for path in candidates if path and catbus_entry_usable(path) and inside_installer_components(path)
        ]
        return found[0] if found else ''
    explicit = catbus_entry_at(explicit, system)
    if explicit:
        return explicit if catbus_entry_usable(explicit) else ''
    found = catbus_candidates(env, system)
    return found[0] if found else ''
