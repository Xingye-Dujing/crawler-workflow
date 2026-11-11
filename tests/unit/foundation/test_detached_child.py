"""A helper spawned for a job that outlives the app must really run and really survive.

The self-updater's swapper is a CONSOLE program (PowerShell), started by a program that then ends
itself. ``CREATE_NO_WINDOW`` is the only flag it needs; ``DETACHED_PROCESS`` — whose name suggests
exactly this — makes such a child exit before its first statement. Measured on Windows 11: the
marker file below appeared under ``CREATE_NO_WINDOW`` and never under ``DETACHED_PROCESS``, with or
without the standard handles redirected. An assertion on flag bits cannot see that; this one spawns
the child, kills the parent, and looks for the marker.
"""

import os
import shutil
import subprocess
import sys
import time

import pytest
from core import procs

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.name != 'nt', reason='the Windows creation flags are the subject'),
]


def test_a_detached_console_child_runs_and_outlives_its_parent(tmp_path):
    marker = tmp_path / 'alive.txt'
    child = f"import pathlib, time; time.sleep(2); pathlib.Path(r'{marker}').write_text('ran', encoding='utf-8')"
    flags = procs.popen_kwargs('win32', detached=True)
    assert flags.get('creationflags'), 'a Windows child needs CREATE_NO_WINDOW'
    parent = (
        'import subprocess, sys, os\n'
        f'subprocess.Popen([sys.executable, "-c", {child!r}], close_fds=True, creationflags={flags["creationflags"]})\n'
        'os._exit(0)\n'
    )
    subprocess.run([sys.executable, '-c', parent], timeout=60, check=True)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.2)
    assert marker.is_file(), 'the console child never ran: it was spawned and died'
    assert marker.read_text(encoding='utf-8') == 'ran'


def test_the_powershell_swapper_runs_under_the_product_flags(tmp_path):
    """The exact program the updater spawns, with the exact flags, from a parent that exits."""
    marker = tmp_path / 'ps.txt'
    script = tmp_path / 'probe.ps1'
    script.write_text(
        f"Set-Content -LiteralPath '{marker}' -Value 'ran'\n",
        encoding='utf-8',
    )
    flags = procs.popen_kwargs('win32', detached=True)['creationflags']
    parent = (
        'import subprocess, sys, os\n'
        f'command = {procs.powershell_command(str(script))!r}\n'
        f'subprocess.Popen(command, close_fds=True, creationflags={flags})\n'
        'os._exit(0)\n'
    )
    subprocess.run([sys.executable, '-c', parent], timeout=60, check=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.2)
    if shutil.which('powershell') is None:
        pytest.skip('powershell is not on PATH')
    assert marker.is_file(), 'powershell never ran: this is the bug that broke every update'
    assert marker.read_text(encoding='utf-8').strip() == 'ran'


def test_the_flags_never_ask_for_a_process_that_cannot_start():
    flags = procs.popen_kwargs('win32', detached=True).get('creationflags', 0)
    assert flags & 0x08000000, 'CREATE_NO_WINDOW keeps a black console off the screen'
    assert flags & 0x00000200, 'CREATE_NEW_PROCESS_GROUP keeps the child out of the parent console'
    assert not flags & 0x00000008, 'DETACHED_PROCESS is the flag that killed the updater'
