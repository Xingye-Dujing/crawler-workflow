"""Runtime-editable app settings, persisted to ``data/settings.json``.

Everything in here used to be a hardcoded constant (the chromedriver path was
baked into ``config.py``), which meant "move the driver" required editing
source. The frontend settings panel reads these via ``GET /api/settings`` and
writes them via ``POST /api/settings``; each crawler / LLM call then pulls the
current value through :func:`get_setting`, so a save takes effect on the next
execution without a server restart.

Only things that are genuinely machine-local live here. Behaviour the user
already controls per-run (headless, parallel workers, AI provider/key) keeps
its existing flow.
"""

import json
import os
import re
import threading

from config import Config
from i18n import t

_PATH = os.path.join(Config.DATA_DIR, 'settings.json')
_lock = threading.Lock()

DEFAULTS = {
    # Selenium chromedriver executable. Was Config.DRIVER_PATH.
    'driver_path': Config.DRIVER_PATH,
    # Chrome executable itself; empty = let Selenium find the default install.
    'browser_binary': '',
    # "--window-size=WxH" passed to every crawler browser.
    'window_size': '1920x1080',
    # driver.set_page_load_timeout — how long a page may take to load.
    'page_load_timeout': 40,
    # Default for Crawler.wait_for_element (was a hardcoded 15 in base.py).
    'element_timeout': 15,
    # Local Ollama daemon (was OLLAMA_HOST env-only, with no UI).
    'ollama_host': Config.OLLAMA_HOST,
    # Ask "is the cookie still fresh?" before every run that contains a
    # crawler node. Long crawls can outlive a cookie; the prompt points the
    # user at refresh + resume BEFORE burning time, and can be turned off.
    'cookie_confirm_before_run': True,
    # Give every platform its own Chrome profile so the crawl browser stays the same
    # device across runs. Off = the old behaviour (a blank profile plus a planted
    # snapshot), which sites that rotate their session cookie punish.
    'use_browser_profile': True,
    # Empty = the app-managed ``data/chrome_profile``. A custom path is for a profile
    # the user created *for this tool* — never their daily Chrome profile, which Chrome
    # locks while it runs and encrypts against other processes (see browser_profiles).
    'browser_profile_dir': '',
}

_values = None


def _load() -> dict:
    global _values
    if _values is None:
        vals = dict(DEFAULTS)
        try:
            with open(_PATH, encoding='utf-8') as f:
                stored = json.load(f)
            for k in DEFAULTS:
                if k in stored and stored[k] is not None:
                    vals[k] = stored[k]
        except (OSError, ValueError):
            pass  # first run / corrupt file → defaults
        _values = vals
    return _values


def all_settings() -> dict:
    with _lock:
        return dict(_load())


def get_setting(key: str):
    with _lock:
        return _load().get(key, DEFAULTS.get(key))


def save_settings(patch: dict) -> tuple[dict, list]:
    """Validate + merge ``patch``, persist, and return (values, warnings).

    Validation never rejects a whole save: a mistyped value falls back to its
    default and a warning comes back so the panel can show it. A missing
    driver file is only a warning — the user may be configuring a machine
    where the file will exist later.
    """
    warnings = []
    with _lock:
        vals = _load()
        for key in DEFAULTS:
            if key not in patch:
                continue
            raw = patch[key]
            if key == 'driver_path':
                v = str(raw or '').strip()
                if v:
                    vals[key] = v
                    if not os.path.isfile(v):
                        warnings.append(t('set.driverMissing', path=v))
                else:
                    vals[key] = DEFAULTS[key]
                    warnings.append(t('set.driverEmpty'))
            elif key == 'browser_binary':
                v = str(raw or '').strip()
                if v and not os.path.isfile(v):
                    warnings.append(t('set.browserMissing', path=v))
                vals[key] = v
            elif key == 'window_size':
                v = str(raw or '').strip()
                if re.fullmatch(r'\d{2,5}x\d{2,5}', v):
                    vals[key] = v
                else:
                    vals[key] = DEFAULTS[key]
                    warnings.append(t('set.badWindow', default=DEFAULTS[key]))
            elif key in ('page_load_timeout', 'element_timeout'):
                # ``setting=`` rather than ``key=``: i18n.t() owns a parameter
                # called ``key`` itself and the kwarg collision used to raise
                # TypeError right here, 500-ing the panel that was only trying
                # to report a warning. The value reported back is the submitted
                # one — a warning quoting the restored default tells nothing.
                try:
                    v = int(float(raw))
                except (TypeError, ValueError, OverflowError):
                    # OverflowError is 'inf'/'1e400': float() accepts them and
                    # int() refuses — the same trap _safe_int documents.
                    warnings.append(t('set.badNumber', setting=key, value=raw))
                    v = DEFAULTS[key]
                else:
                    lo, hi = (5, 300) if key == 'page_load_timeout' else (3, 600)
                    if not lo <= v <= hi:
                        warnings.append(t('set.outOfRange', setting=key, lo=lo, hi=hi, value=v))
                        v = DEFAULTS[key]
                vals[key] = v
            elif key == 'ollama_host':
                v = str(raw or '').strip().rstrip('/')
                if v and not re.match(r'^https?://', v):
                    vals[key] = DEFAULTS[key]
                    warnings.append(t('set.badOllamaHost'))
                else:
                    vals[key] = v or DEFAULTS[key]
            elif key in ('cookie_confirm_before_run', 'use_browser_profile'):
                # The browser may send a real bool or the 'true'/'false' string
                # the checkbox helpers historically produced; anything else
                # falls back to the default rather than guessing.
                if isinstance(raw, bool):
                    vals[key] = raw
                elif str(raw).strip().lower() in ('true', 'false'):
                    vals[key] = str(raw).strip().lower() == 'true'
                else:
                    vals[key] = DEFAULTS[key]
                    warnings.append(t('set.badFlag', setting=key))
            elif key == 'browser_profile_dir':
                # Empty means "use the app-managed directory". A path is accepted as
                # written and created on first use (Chrome makes its own user-data-dir,
                # so only an unusable *shape* is refused here — refusing a path whose
                # parent exists but whose leaf does not would punish the normal case).
                v = str(raw or '').strip().strip('"')
                if not v:
                    vals[key] = ''
                elif not os.path.isabs(v):
                    vals[key] = DEFAULTS[key]
                    warnings.append(t('set.badProfileDir', value=v))
                else:
                    vals[key] = v
        tmp = _PATH + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(vals, f, ensure_ascii=False, indent=2)
            os.replace(tmp, _PATH)
        except OSError as e:
            warnings.append(t('set.saveFailed', err=e))
        return dict(vals), warnings
