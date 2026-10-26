"""Where the outside-world tools this app depends on live on this machine.

The packaged build carries its own Python and every library it imports, but four things always
belong to the machine rather than to the app: Chrome (which crawls), chromedriver (which drives it),
xelatex (which typesets a paper) and an Ollama daemon (which answers an LLM node). Each probe lives
here exactly once, because the desktop launcher's startup self-check and a crawler's refusal have to
answer with the same facts — two lists of candidate paths is how a user ends up reading "Chrome not
found" on the same machine where a crawl starts fine.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import socket
import sys
from urllib.parse import urlsplit


def _path_shape(os_name: str) -> tuple:
    """The joiner and the ``PATH`` separator a GIVEN operating system uses.

    ``os.path`` would answer with the separator of the machine asking, which is right at run time and
    wrong as a test: a Windows box asking 「what would a Linux box look for」 has to get Linux-shaped
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
# cloud box with /usr/bin/chromium used to answer 「未找到 Chrome」 while the crawl worked on Windows.
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


def is_windows(system: str | None = None) -> bool:
    """Whether this machine can be asked for a window, a foreground app or a system certificate store.

    One answer for every 「Windows 才有的能力」 gate, so a refusal and the UI that hides the entry
    cannot disagree about which platform the user is on.
    """
    return platform_name(system) == 'win32'


def is_frozen() -> bool:
    """Whether this is the packaged desktop app rather than a source checkout.

    PyInstaller sets ``sys.frozen`` on the running bundle. The answer decides what a refusal is
    allowed to tell the user to DO: 「pip install mitmproxy」 is an instruction in a checkout and
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
    driver, which reads as 「Chrome 启动失败」 rather than the truth about the file's mode.
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
    """
    explicit = str(explicit or '').strip()
    if explicit:
        return explicit if _is_executable(explicit) else ''
    candidates = chrome_candidates(env, system)
    return candidates[0] if candidates else ''


#: The families of 「缺它怎么办」 answer, each with one catalogue key per OS. A remedy is a different
# sentence on each platform (Windows adds a font feature, Linux installs a distro package, macOS often
# already has the font), so the sentence is chosen here and written in ``i18n`` — and
# ``tests/unit/test_missing_dependency_messages.py`` walks THIS list times every platform, because a
# computed key nobody enumerated is how a refusal prints its own key.
REMEDY_PREFIXES = ('deps.systemFont', 'deps.texFont', 'deps.texPackage', 'deps.xelatex')
REMEDY_PLATFORMS = ('win32', 'linux', 'darwin')


def remedy_key(prefix: str, system: str | None = None) -> str:
    """``deps.texPackage`` → ``deps.texPackage.linux``: the per-OS half of a refusal."""
    return f'{prefix}.{platform_name(system)}'


def remedy(prefix: str, system: str | None = None) -> str:
    """What to install on THIS operating system, read from the bilingual catalogue.

    Used inside a 「缺 X」 sentence: telling a Linux user to open the MiKTeX console, or a Windows user
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
