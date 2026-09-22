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

#: None on a machine without node; callers skip when it is missing.
NODE = shutil.which('node')


def run_node(script: str, *args: str, timeout: int = 90) -> subprocess.CompletedProcess:
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
    try:
        with open(out_path, 'wb') as out_sink, open(err_path, 'wb') as err_sink:
            proc = subprocess.run(
                [NODE, str(script), *[str(a) for a in args]],
                stdout=out_sink,
                stderr=err_sink,
                timeout=timeout,
            )
        with open(out_path, encoding='utf-8', errors='replace') as produced:
            stdout = produced.read()
        with open(err_path, encoding='utf-8', errors='replace') as produced:
            stderr = produced.read()
    finally:
        os.unlink(out_path)
        os.unlink(err_path)
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
