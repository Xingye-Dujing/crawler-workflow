"""The state root is the checkout's ``data/``, wherever the process was started from.

``backend/core/config.py`` derives the repository root from its own location. While the file lived at
``backend/config.py`` that took two ``dirname`` calls; moving it into ``core/`` kept the arithmetic
and pointed one level short — at ``backend/`` — so a run started from ``backend/`` (the documented
way to start the app) wrote ``backend/data/`` and ``backend/logs/`` beside the code while the real
``data/`` stayed untouched. Measured 2026-10-29, after a user ran a workflow and asked why a second
data folder existed: the stray root held a live Chrome profile, which the root-anchored ``data/*``
ignore rule does not cover.

Under pytest every path is redirected to a throwaway root, so the default is proved in a CHILD
process with the override removed — the same way a person starting ``python app.py`` sees it.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from core.config import BASE_DIR

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]


def _default_paths(attribute: str) -> Path:
    """``Config.<attribute>`` as a fresh process computes it, with no override in the environment."""

    env = {key: value for key, value in os.environ.items() if key != 'CRAWLER_DATA_ROOT'}
    answer = subprocess.run(
        [sys.executable, '-c', f'from core.config import Config; print(Config.{attribute})'],
        cwd=REPO / 'backend',
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,  # the returncode is asserted below, with the child's stderr in the message
    )
    assert answer.returncode == 0, answer.stderr[-600:]
    return Path(answer.stdout.strip())


def test_the_base_dir_is_the_checkout_not_the_backend_package():
    """A structural answer, so it holds whatever the checkout is called and wherever it sits."""

    assert (Path(BASE_DIR) / 'backend' / 'core' / 'config.py').is_file()
    assert Path(BASE_DIR).name != 'backend'


def test_starting_from_backend_still_lands_on_the_checkout_data():
    assert _default_paths('DATA_DIR') == REPO / 'data'


def test_the_logs_follow_the_same_root():
    assert _default_paths('LOG_DIR') == REPO / 'logs'
