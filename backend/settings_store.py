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
                        warnings.append(f'驱动文件不存在: {v}')
                else:
                    vals[key] = DEFAULTS[key]
                    warnings.append('驱动路径为空，已恢复默认值')
            elif key == 'browser_binary':
                v = str(raw or '').strip()
                if v and not os.path.isfile(v):
                    warnings.append(f'浏览器程序不存在: {v}')
                vals[key] = v
            elif key == 'window_size':
                v = str(raw or '').strip()
                if re.fullmatch(r'\d{2,5}x\d{2,5}', v):
                    vals[key] = v
                else:
                    vals[key] = DEFAULTS[key]
                    warnings.append(f'窗口大小格式应为 宽x高（如 1920x1080），已恢复默认 {DEFAULTS[key]}')
            elif key in ('page_load_timeout', 'element_timeout'):
                try:
                    v = int(float(raw))
                except (TypeError, ValueError):
                    v = DEFAULTS[key]
                    warnings.append(f'{key} 不是数字，已恢复默认 {v}')
                lo, hi = (5, 300) if key == 'page_load_timeout' else (3, 600)
                if not lo <= v <= hi:
                    v = DEFAULTS[key]
                    warnings.append(f'{key} 超出范围 {lo}-{hi}，已恢复默认 {v}')
                vals[key] = v
            elif key == 'ollama_host':
                v = str(raw or '').strip().rstrip('/')
                if v and not re.match(r'^https?://', v):
                    vals[key] = DEFAULTS[key]
                    warnings.append('Ollama 地址需以 http:// 或 https:// 开头，已恢复默认')
                else:
                    vals[key] = v or DEFAULTS[key]
        tmp = _PATH + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(vals, f, ensure_ascii=False, indent=2)
            os.replace(tmp, _PATH)
        except OSError as e:
            warnings.append(f'设置未能写入磁盘（本次会话内仍生效）: {e}')
        return dict(vals), warnings
