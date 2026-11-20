"""Keep every model download, cache and intermediate artefact inside this checkout.

A library that downloads a weight calls ``os.getenv('HF_HOME')`` when it is imported, not when the
first file is needed. Setting that variable in a node executor is therefore too late: the topic
step's ``sentence-transformers`` had already filled ``~/.cache/huggingface`` on this machine before
any code of ours could object. This module is imported by ``core.config`` before any heavy package,
so the decision is made once, at process start, for the whole tree.

The roots are derived from this file's location, never from the current directory, and an explicit
``CIXI_CACHE_DIR`` wins so a deployment can move the tree. Nothing here imports a third-party
package or creates a directory: a boot must stay cheap, and a test that redirects the data root
must not be surprised by writes at import time.
"""

import os
import sys

#: Non-Hugging-Face caches and the folder each one gets below the general cache root. The Hugging
#: Face variables are handled separately because their historical home is ``ml_train/.hf-cache``.
CACHE_VARS = {
    'TORCH_HOME': 'torch',
    'SENTENCE_TRANSFORMERS_HOME': 'sentence_transformers',
    'XDG_CACHE_HOME': 'xdg',
    'MPLCONFIGDIR': 'matplotlib',
    'JOBLIB_TEMP_FOLDER': 'joblib',
}

#: Fixed facts, not paths: telemetry is useless on an offline analysis box.
FIXED_ENV = {
    'HF_HUB_DISABLE_TELEMETRY': '1',
    'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1',
}


def project_root() -> str:
    """The checkout root, or the installed application's folder in a frozen build."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def cache_root(root: str | None = None) -> str:
    """The one directory every download below this process may write to.

    Source runs keep the existing ``ml_train/.hf-cache`` layout for Hugging Face weights and put the
    other caches beside it under ``ml_train/.cache``. A packaged build has no ``ml_train/`` tree, so
    everything goes under ``<app dir>/cache`` instead.
    """
    override = str(os.environ.get('CIXI_CACHE_DIR') or '').strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    base = os.path.abspath(os.path.expanduser(str(root if root is not None else project_root())))
    if getattr(sys, 'frozen', False):
        return os.path.join(base, 'cache')
    return os.path.join(base, 'ml_train', '.cache')


def hf_home(root: str | None = None) -> str:
    """The Hugging Face cache, kept at its historical project-local path."""
    override = str(os.environ.get('HF_HOME') or '').strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    base = os.path.abspath(os.path.expanduser(str(root if root is not None else project_root())))
    if getattr(sys, 'frozen', False):
        return os.path.join(base, 'cache', 'hf')
    return os.path.join(base, 'ml_train', '.hf-cache')


def setup(root: str | None = None) -> dict[str, str]:
    """Publish the cache paths into ``os.environ`` and return what was chosen.

    ``setdefault`` is deliberate: an operator who exports ``HF_HOME`` for a shared mirror still gets
    that mirror. The value returned is the *effective* path, so a startup report or a test can show
    where files will really land instead of repeating the default.
    """
    general = cache_root(root)
    weights = hf_home(root)
    hf_vars = {
        'HF_HOME': weights,
        'HF_HUB_CACHE': os.path.join(weights, 'hub'),
        'HF_XET_CACHE': os.path.join(weights, 'xet'),
        'TRANSFORMERS_CACHE': os.path.join(weights, 'hub'),
    }
    chosen = {}
    for name, value in {**hf_vars, **{key: os.path.join(general, rel) for key, rel in CACHE_VARS.items()}}.items():
        os.environ.setdefault(name, value)
        chosen[name] = os.environ[name]
    for name, value in FIXED_ENV.items():
        os.environ.setdefault(name, value)
    # A mirror is an opt-in: the default endpoint is the upstream one, and a bad mirror must be a
    # choice someone made rather than a silent rewrite of every download.
    mirror = str(os.environ.get('CIXI_HF_ENDPOINT') or 'https://hf-mirror.com').strip()
    os.environ.setdefault('HF_ENDPOINT', mirror)
    os.environ.setdefault('CIXI_CACHE_DIR', general)
    chosen['CIXI_CACHE_DIR'] = os.environ['CIXI_CACHE_DIR']
    return chosen
