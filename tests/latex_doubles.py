"""A stand-in for the xelatex PROCESS, for the API tests that must never shell out.

The compiler used to be launched with ``subprocess.run`` and the tests stubbed that call. It
is now launched with ``subprocess.Popen`` (a compile needs a bounded timeout and a process
tree that can be reaped without waiting on a wedged child), so a test that still patches
``subprocess.run`` silently runs the REAL xelatex — which passes on a machine that has TeX
and fails on a CI runner that does not. This double has the shape the production code
actually reads: ``communicate(timeout=...)``, ``returncode``, ``pid``, ``kill``.
"""

import os


class _FakeProcess:
    def __init__(self, command, writes: bool, returncode: int, stderr: bytes):
        self.args = list(command)
        self.returncode = returncode
        #: 0 is falsy, which is what makes the reaper skip a process it cannot own — the same
        #: branch a driver-less double exercises elsewhere.
        self.pid = 0
        self._writes = writes
        self._stderr = stderr
        self._communicated = False

    def communicate(self, timeout=None):
        if not self._communicated:
            self._communicated = True
            if self._writes:
                outdir = None
                for index, arg in enumerate(self.args):
                    if arg == '-output-directory' and index + 1 < len(self.args):
                        outdir = self.args[index + 1]
                if outdir:
                    with open(os.path.join(outdir, 'main.pdf'), 'wb') as handle:
                        handle.write(b'%PDF-1.4 fake')
        return b'', self._stderr

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        return None


def fake_popen(writes: bool = True, returncode: int = 0, stderr: bytes = b''):
    """A ``subprocess.Popen`` replacement that writes (or refuses) ``<outdir>/main.pdf``."""
    calls = []

    def popen(command, *args, **kwargs):
        process = _FakeProcess(command, writes, returncode, stderr)
        calls.append(process)
        return process

    popen.calls = calls
    return popen
