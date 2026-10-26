"""One way to run the node harnesses — because the naive one trips the network guard.

The JS behaviour tests shell out to ``node``. Written as
``subprocess.run(..., capture_output=True)``, that emits
``UserWarning: A test tried to use socket.socket`` under ``--disable-socket``:
on Windows Python's ``subprocess`` builds an *emulated* socket pair
(``socket.socketpair()`` → two ``socket()`` objects) to hand the child its pipe
ends. No network is involved, so the warning was a false positive of the guard —
and a persistent one, at that.

Redirecting the child's output to real files instead removes both problems: no
pipes, therefore no socketpair, therefore nothing for the guard to complain
about. It is also how a large harness output should be read anyway — through a
file the test can re-open, not a buffer it has to hold.

``shutil.which('node')`` is exposed so each caller can skip with the same
wording rather than inventing its own.
"""

import os
import shutil
import subprocess
import tempfile

import pytest

#: None on a machine without node; callers skip when it is missing.
NODE = shutil.which('node')

#: The same switch the browser and the Ollama daemon have. The frontend tier is ~43 modules that all
#: ``skipif(node is None)`` — a runner (or a container image) without node therefore prints
#: "7900 passed, 43 skipped" over a suite in which **no JS behaviour was tested at all**, which is the
#: exact shape AGENTS refuses: green that means nothing. A run that MEANS to exercise the tier sets this.
REQUIRE_NODE_ENV = 'CRAWLER_REQUIRE_NODE'


def node_required(env: dict | None = None) -> bool:
    """Whether the operator asked for the frontend tier to be evidence rather than a skip."""
    env = os.environ if env is None else env
    return str(env.get(REQUIRE_NODE_ENV) or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def check_node_or_abort(env: dict | None = None) -> None:
    """Raise a usage error when node is missing AND the tier was demanded; otherwise say nothing.

    Called from ``tests/conftest.py``'s ``pytest_configure`` — before collection — so the session stops
    rather than running 7 900 cases and then reporting that the 43 that matter were skipped. The message
    names the flag, because the person who set it has to know which knob was the cause.

    The lookup is the module-level :data:`NODE` rather than a parameter: a ``None`` argument could mean
    either "ask the machine" or "the machine has nothing", and the one case that must abort is exactly
    the one a caller would have to spell ambiguously. A test changes ``NODE`` instead.
    """
    if NODE is not None or not node_required(env):
        return
    raise pytest.UsageError(
        f'{REQUIRE_NODE_ENV} is set, but `node` is not on PATH — the frontend JS harnesses would all '
        'skip and the run would look green without testing any of them'
    )


def run_node(script: str, *args: str, timeout: int = 90, tz: str | None = None) -> subprocess.CompletedProcess:
    """Run ``node script args...`` and return a CompletedProcess with ``stdout``.

    Output goes through temporary files rather than pipes (see the module
    docstring), and the encoding is pinned to UTF-8: Windows would otherwise
    decode Chinese fixture text with the locale default and fail on it.

    stdout and stderr are captured to **separate** files. Merging them — the
    obvious way to halve the file count — breaks every caller that parses the
    result as JSON, because a harness's own ``console.log`` debug line then lands
    in front of the payload.
    """
    out_handle, out_path = tempfile.mkstemp(suffix='.out')
    err_handle, err_path = tempfile.mkstemp(suffix='.err')
    os.close(out_handle)
    os.close(err_handle)
    # A tz-pinned child makes timezone-dependent harness assertions deterministic on any
    # runner: Node reads TZ at process start, before the harness touches Date.
    child_env = None if tz is None else {**os.environ, 'TZ': tz}
    try:
        with open(out_path, 'wb') as out_sink, open(err_path, 'wb') as err_sink:
            proc = subprocess.run(
                [NODE, str(script), *[str(a) for a in args]],
                stdout=out_sink,
                stderr=err_sink,
                timeout=timeout,
                env=child_env,
                # A harness that exits non-zero IS the measurement: the caller asserts on
                # ``returncode`` and prints ``stderr`` (one even asserts a *non-zero* syntax
                # check), so raising here would swallow the report instead of making it.
                check=False,
            )
        with open(out_path, encoding='utf-8', errors='replace') as produced:
            stdout = produced.read()
        with open(err_path, encoding='utf-8', errors='replace') as produced:
            stderr = produced.read()
    finally:
        os.unlink(out_path)
        os.unlink(err_path)
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
