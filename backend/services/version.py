"""The application version, and the one value the self-updater compares.

The release feed (``version.json`` at the repository root) must carry the same value for the
build that is published. A date-based number is deliberate: the main program ships often while
the components change rarely, so a monotonic build number is easier to reason about than
``1.0.0``.
"""

APP_VERSION = '2026.11.14.1'
