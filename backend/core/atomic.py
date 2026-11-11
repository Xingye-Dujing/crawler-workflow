"""One atomic-rename helper, because on Windows a READER blocks the rename.

Every durable store in this project writes ``<target>.<unique>.tmp`` and then renames it into place.
On POSIX that rename replaces whatever is there, held open or not; on Windows ``os.replace`` answers
``PermissionError`` (errno 13) while ANY other handle has the target open — a second request loading
the same workflow, the settings file being read by a panel, an antivirus scanner, the console
``.jsonl`` tail.

Two consequences follow, and both were real:

* a save racing a read raised ``PermissionError`` → an ``OSError`` → an HTTP 500 for a write that was
  perfectly valid, and the retry the user then made DID work (so it read as flakiness);
* a save racing a save could publish a truncated file instead, which is why every caller now stages
  under a unique name before this helper runs.

The retry is bounded and short: the competing handle is normally a read that closes in milliseconds.
"""

from __future__ import annotations

import os
import time

#: Total attempts before the rename is reported as a failure. Ten tries over ~0.4 s covers a reader
#: that opened the file just before the writer got there; a handle that stays open is a real error
#: and is surfaced (never swallowed) so the caller can say which file.
ATTEMPTS = 10
#: First back-off, doubled per attempt and capped so the whole retry stays short: the writer usually
#: holds a lock the UI is waiting on, and a multi-second sleep under it is worse than the 500 the
#: retry exists to remove. A genuinely stuck handle is raised after the tenth try.
BACKOFF = 0.01
MAX_DELAY = 0.05


def replace(staged, target) -> None:
    """Move ``staged`` onto ``target``, retrying Windows' reader-blocks-rename case.

    Raises the last ``OSError`` when every attempt failed, so a genuinely stuck file is still a named
    failure rather than a silent success.
    """
    delay = BACKOFF
    last: OSError | None = None
    for attempt in range(ATTEMPTS):
        try:
            os.replace(staged, target)
            return
        except PermissionError as exc:  # Windows: another handle holds the target open
            last = exc
            if attempt == ATTEMPTS - 1:
                break
            time.sleep(delay)
            delay = min(delay * 2, MAX_DELAY)
    assert last is not None  # only reachable from the branch above
    raise last
