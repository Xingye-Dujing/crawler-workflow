"""Project-local cache and temporary directories for every offline training script.

Import this module FIRST, before torch, transformers or huggingface_hub: all three read their cache
environment when they are imported, and a late assignment sends a multi-gigabyte download to the
user's home directory. The values mirror ``backend/core/cache.py``; the two are compared by
``tests/unit/foundation/test_cache_paths.py`` so a future edit cannot make them disagree.

Nothing is downloaded or deleted here. Directories are created by the script that actually writes
into them, and an explicit environment variable still wins.
"""

import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HF_HOME_DIR = ROOT / 'ml_train' / '.hf-cache'
CACHE_DIR = ROOT / 'ml_train' / '.cache'
TMP_DIR = ROOT / 'ml_train' / '.tmp'
DATASETS_DIR = ROOT / 'ml_train' / 'datasets'
MODELS_DIR = ROOT / 'ml_train' / 'models'
BACKUPS_DIR = ROOT / 'ml_train' / 'backups'
LOCKS_DIR = ROOT / 'ml_train' / '.locks'
LOGS_DIR = ROOT / 'ml_train' / 'logs'

_CACHE_VARS = {
    'HF_HOME': str(HF_HOME_DIR),
    'HF_HUB_CACHE': str(HF_HOME_DIR / 'hub'),
    'HF_XET_CACHE': str(HF_HOME_DIR / 'xet'),
    'TRANSFORMERS_CACHE': str(HF_HOME_DIR / 'hub'),
    'TORCH_HOME': str(CACHE_DIR / 'torch'),
    'SENTENCE_TRANSFORMERS_HOME': str(CACHE_DIR / 'sentence_transformers'),
    'XDG_CACHE_HOME': str(CACHE_DIR / 'xdg'),
    'MPLCONFIGDIR': str(CACHE_DIR / 'matplotlib'),
    'JOBLIB_TEMP_FOLDER': str(CACHE_DIR / 'joblib'),
    'HF_HUB_DISABLE_TELEMETRY': '1',
    'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1',
    'TOKENIZERS_PARALLELISM': 'false',
}


def setup() -> dict[str, str]:
    """Publish project-local cache paths and return the effective values.

    ``TEMP``/``TMP`` are set here too, but only for this one offline script process: ``tempfile``
    snapshots them at import, so an application process must never have them rewritten behind its
    back. Training checkpoints that spill to disk therefore stay on the project's drive as well.
    """
    for name, value in _CACHE_VARS.items():
        os.environ.setdefault(name, value)
    for name in ('TMPDIR', 'TEMP', 'TMP'):
        # Unlike the cache roots, these ARE overridden: an inherited C: temp path would put training
        # spill files on the system drive even though the script itself lives on the project drive.
        os.environ[name] = str(TMP_DIR)
    # tempfile snapshots its candidate list at import, which may have happened during interpreter
    # startup; set the module's own cache too so spill files obey this same root.
    tempfile.tempdir = str(TMP_DIR)
    # The upstream hub is unreachable from this machine; the community mirror is the working
    # default for the offline scripts. Override with CIXI_HF_ENDPOINT (or set HF_ENDPOINT first).
    mirror = str(os.environ.get('CIXI_HF_ENDPOINT') or 'https://hf-mirror.com').strip()
    os.environ.setdefault('HF_ENDPOINT', mirror)
    os.environ.setdefault('CIXI_CACHE_DIR', str(CACHE_DIR))
    return {name: os.environ[name] for name in _CACHE_VARS}


setup()
