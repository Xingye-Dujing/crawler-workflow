"""A `?autorun=1` deep link may start a run only on a host that explicitly opted in.

A cross-site top-level navigation to the app would otherwise execute a saved workflow — spending
the user's crawler accounts and API keys — with no click. The capability is a server fact so JS
holds no second opinion; only the demo recorder sets the environment flag.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]


def _flag(value):
    env = {k: v for k, v in os.environ.items() if k != 'CIXI_DEMO_AUTORUN'}
    if value is not None:
        env['CIXI_DEMO_AUTORUN'] = value
    answer = subprocess.run(
        [sys.executable, '-c', 'from core.config import Config; print(Config.DEMO_AUTORUN)'],
        cwd=REPO / 'backend',
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return answer.stdout.strip()


def test_demo_autorun_defaults_off():
    assert _flag(None) == 'False'


def test_demo_autorun_can_be_enabled_for_isolated_recorders():
    assert _flag('1') == 'True'
    assert _flag('true') == 'True'


def test_api_config_publishes_the_capability(monkeypatch):
    from core.config import Config

    value = Config.DEMO_AUTORUN
    assert isinstance(value, bool)
    # The key is present in /api/config so the page can gate autorun on the server's answer.
    source = (REPO / 'backend' / 'api' / 'config.py').read_text(encoding='utf-8')
    assert "'demo_autorun': Config.DEMO_AUTORUN" in source
