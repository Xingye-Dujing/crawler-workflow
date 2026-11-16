"""What kind of host this AI workspace is running on.

A packaged desktop app, a source/local web checkout and a cloud server all serve the same page and
the same AI workspace. The workspace itself is complete on all three: remote providers, files,
search, conversations, skills and declarative plugins are not missing anywhere. What differs is
what the server can reach on the user's machine, and the server is the only place that fact is
decided.

The same object feeds three consumers, so they cannot disagree:

- the system prompt (``prompt_line``) tells the model what it may claim to have read;
- the skill list (``ai.skills.availability``) disables the one built-in skill that needs the
  repository source, and names the reason in the panel;
- the UI (``/api/ai/bootstrap``) shows the runtime chip and can hide a control the host cannot
  honour, instead of letting the click fail.
"""

import os
import sys

from core import machine
from core.config import Config

from i18n import t


def code_root() -> str:
    """The source tree the AI may read, or ``''`` when this host ships none.

    A source checkout answers the repository root. A packaged build can carry a read-only
    ``source/`` snapshot (the desktop specs collect ``backend/**/*.py`` and ``docs/**/*.md``); it is
    enough to cite a file or line, and it deliberately cannot edit the running program — the
    extension path on a desktop is the Python workspace, not a patched bundle.

    A cloud host answers ``''`` even when it runs from a checkout: ``CLOUD_MODE`` is the server's
    verdict about the host, and the deploy shape (source vs wheel) must not silently grant one
    account the server's own source. This is the single place all three consumers ask.
    """
    if Config.CLOUD_MODE:
        return ''
    if machine.is_frozen():
        base = str(getattr(sys, '_MEIPASS', '') or '')
        snapshot = os.path.join(base, 'source')
        return snapshot if os.path.isdir(snapshot) else ''
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def kind() -> str:
    """``desktop`` (frozen app), ``local_web`` (source checkout) or ``cloud`` (shared server)."""
    if Config.CLOUD_MODE:
        return 'cloud'
    if machine.is_frozen():
        return 'desktop'
    return 'local_web'


def capabilities() -> dict:
    """The workspace feature matrix for this host.

    A ``True`` here means the workspace has the feature, not that a provider supports it; provider
    capabilities stay in the provider catalog. ``local_source`` is true for a source checkout and
    for a packaged build that carries the read-only source snapshot; a cloud host never has it.
    """
    runtime = kind()
    local = runtime in ('desktop', 'local_web')
    return {
        'kind': runtime,
        'label_key': f'ai.runtime.{runtime}',
        # The workspace itself — identical on every host.
        'chat': True,
        'sessions': True,
        'skills': True,
        'declarative_plugins': True,
        'files_api': True,
        'web_search': True,
        # Host powers.
        'ollama': local,
        'user_files': local,
        'code_plugins': local,
        'python_exec': local,
        'local_source': bool(code_root()),
        # Shape flags for the page.
        'cloud': runtime == 'cloud',
        'frozen': runtime == 'desktop',
    }


def feature_words() -> str:
    """The capability names the prompt may quote, sorted so two turns read the same."""
    caps = capabilities()
    return ', '.join(key for key in sorted(caps) if caps[key] is True)


def prompt_line() -> str:
    """One environment line. It states powers, never asks the model to infer them."""
    runtime = kind()
    if runtime == 'desktop':
        return (
            "Environment: the packaged desktop app, running on the user's machine. The AI workspace "
            'is complete here: you may rely on local files the user attaches, a local Ollama daemon, '
            'local code plugins and a read-only source snapshot, plus the Python workspace when the '
            'user enabled it. You can read and cite the source snapshot, but you cannot change the '
            'running program; a reusable Python script is the extension path.'
        )
    if runtime == 'local_web':
        return (
            "Environment: the local web checkout, running on the user's machine. The AI workspace "
            'is complete here: you may rely on local files, a local Ollama daemon, local code '
            'plugins and the repository source.'
        )
    return (
        'Environment: a shared cloud host. The AI workspace is complete here through the provider '
        'APIs: remote models, uploaded files, server-side search and fetch, conversations, skills '
        'and declarative plugins. There is no local model daemon, no user-local filesystem and no '
        "repository source. Never claim to have read a file on the user's machine or started a "
        'local process; use only the supplied context and the provider APIs.'
    )


def label() -> str:
    return t(capabilities()['label_key'])
