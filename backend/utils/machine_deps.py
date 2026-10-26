"""Where the outside-world tools this app depends on live on this machine.

The packaged build carries its own Python and every library it imports, but four things always
belong to the machine rather than to the app: Chrome (which crawls), chromedriver (which drives it),
xelatex (which typesets a paper) and an Ollama daemon (which answers an LLM node). Each probe lives
here exactly once, because the desktop launcher's startup self-check and a crawler's refusal have to
answer with the same facts — two lists of candidate paths is how a user ends up reading "Chrome not
found" on the same machine where a crawl starts fine.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit

#: Environment variables that may name Chrome, most-explicit first. A portable copy of Chrome, or a
# second version installed outside the usual roots, is reachable only through one of these.
CHROME_ENV_VARS = ('CHROME_PATH', 'CHROME_BIN')

#: Where a Windows installer puts Chrome. ``LOCALAPPDATA`` is the per-user install, which is what a
# machine without admin rights gets.
CHROME_INSTALL_ROOTS = ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')

#: Ollama's own default port, used when a configured address carries none.
OLLAMA_DEFAULT_PORT = 11434


def is_frozen() -> bool:
    """Whether this is the packaged desktop app rather than a source checkout.

    PyInstaller sets ``sys.frozen`` on the running bundle. The answer decides what a refusal is
    allowed to tell the user to DO: 「pip install mitmproxy」 is an instruction in a checkout and
    nonsense in an exe that has no pip and no interpreter anyone can write to.
    """
    return bool(getattr(sys, 'frozen', False))


def chrome_candidates(env: dict | None = None) -> list[str]:
    """Chrome executables that actually exist on disk, most-explicit first."""
    env = os.environ if env is None else env
    paths = [str(env.get(name) or '') for name in CHROME_ENV_VARS]
    for base in (env.get(root) for root in CHROME_INSTALL_ROOTS):
        if base:
            paths.append(str(Path(base) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe'))
    return [path for path in dict.fromkeys(paths) if path and os.path.isfile(path)]


def find_chrome(explicit: str = '', env: dict | None = None) -> str:
    """The browser to launch, or '' when this machine has nothing to launch.

    ``explicit`` is the user's own setting: when it is filled in it is the ANSWER, not a hint — an
    explicit path that does not exist returns '' rather than falling back to a found install, so
    the caller can name the typo instead of silently crawling a different Chrome than the one the
    user pointed at (a copied-profile Chrome is a second device to a site's risk control).
    """
    explicit = str(explicit or '').strip()
    if explicit:
        return explicit if os.path.isfile(explicit) else ''
    candidates = chrome_candidates(env)
    return candidates[0] if candidates else ''


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
