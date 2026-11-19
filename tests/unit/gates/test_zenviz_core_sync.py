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
        pytest.skip('zen viz-core submodule is not checked out (run git submodule update --init)')
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [sys.executable, str(BUILD), '--product', 'caixihui', '--root', tmp],
            capture_output=True,
            text=True,
            cwd=REPO,
            check=False,  # the assertion below reads returncode; a non-zero exit is the test's subject
        )
        assert result.returncode == 0, result.stderr
        generated = pathlib.Path(tmp) / 'backend/static'
        for rel in ARTIFACTS:
            # Windows checkouts turn the generated LF files into CRLF; compare
            # content, not the working-tree line endings.
            expected = (generated / rel).read_bytes().replace(b'\r\n', b'\n')
            actual = (STATIC / rel).read_bytes().replace(b'\r\n', b'\n')
            assert expected == actual, (
                f'{rel} was not generated from zen viz-core; run build.py rather than editing it directly'
            )
