"""Guard: the chart studio files must be generated from the shared core.

Editing backend/static/zenviz.html or its css/js by hand makes the two products
drift again. Regenerate with third_party/zenviz-core/build.py instead.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
BUILD = REPO / 'third_party/zenviz-core/build.py'
STATIC = REPO / 'backend/static'
ARTIFACTS = (
    'zenviz.html',
    'css/zenviz.css',
    'js/zenviz-page.js',
    'js/zenviz-parse.js',
)


def test_studio_files_match_the_shared_core_generator():
    if not BUILD.is_file():
        pytest.skip('zen viz-core submodule is not checked out (set its remote URL first)')
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [sys.executable, str(BUILD), '--product', 'caixihui', '--root', tmp],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        assert result.returncode == 0, result.stderr
        generated = pathlib.Path(tmp) / 'backend/static'
        for rel in ARTIFACTS:
            assert (generated / rel).read_bytes() == (STATIC / rel).read_bytes(), (
                f'{rel} was not generated from zen viz-core; run build.py rather than editing it directly'
            )
