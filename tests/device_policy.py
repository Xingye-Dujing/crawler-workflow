"""The device tier's skip-or-fail policy, in one importable place.

This lives here rather than in ``tests/integration/conftest.py`` for the reason
``isolation_guard.py`` documents: pytest loads a ``conftest.py`` per directory, so ``import conftest``
resolves to whichever of the four was imported first — a test that thinks it is asking the device
policy may be asking the root one. The policy has to be importable to be used, and it has to be
*one* object to be the policy.

Why it exists at all: skipping an unavailable device is right by default (a machine without Chrome
should still run everything else) and dangerous in exactly one situation — the run that MEANT to
exercise this tier. The closure rule says "nothing skipped", so a tier that skips its browser cases
can print a passing number for a tier that never ran. When the operator sets the flag, an
unavailable device is an error.
"""

import os

import pytest

#: Set these to make an unavailable device FAIL the tier instead of skipping it.
REQUIRE_BROWSER_ENV = 'CRAWLER_REQUIRE_BROWSER'
REQUIRE_OLLAMA_ENV = 'CRAWLER_REQUIRE_OLLAMA'
#: The second crawl backend is a device too: no Node, or no adapter checkout, means the cases that
#: prove the real CLI speaks this contract did not run — and `capabilities`/`preflight` are the only
#: place the manifest shape is checked against something that is not a stub.
REQUIRE_CATBUS_ENV = 'CIXI_REQUIRE_CATBUS'


def flag_set(name: str) -> bool:
    """``as_bool`` for the environment: blank is off, and so is every spelling of no."""
    return str(os.environ.get(name) or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def unavailable(reason: str, flag: str) -> None:
    """Report a device precondition as unmet — a skip normally, a failure when the tier was demanded.

    Every device case that catches a driver/daemon failure must come through here. Its own
    ``pytest.skip`` is the hole this module exists to close: the session-level probe in
    ``tests/integration/conftest.py`` proves Chrome can start ONCE, and a launch that fails later
    (a profile still held by the previous case, the machine busy) would otherwise skip quietly while
    ``CRAWLER_REQUIRE_BROWSER=1`` is set and the run still reads green.
    """
    if flag_set(flag):
        pytest.fail(f'{reason} — {flag} is set, so an unavailable device is an error, never a silent skip')
    pytest.skip(reason)
