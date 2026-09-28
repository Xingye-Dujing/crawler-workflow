#!/bin/bash
set -e

# 确保数据目录存在
mkdir -p /app/data

# 预置 Linux 下的 chromedriver / chrome 路径到 settings.json。
# 仅当用户尚未设置时才写入默认值，已存在的用户设置不会被覆盖。
python - <<'PY'
import json, os
p = '/app/data/settings.json'
defaults = {
    'driver_path': '/usr/bin/chromedriver',
    'browser_binary': '/usr/bin/chromium',
}
cur = {}
if os.path.exists(p):
    try:
        cur = json.load(open(p, encoding='utf-8'))
    except Exception:
        cur = {}
cur.setdefault('driver_path', defaults['driver_path'])
cur.setdefault('browser_binary', defaults['browser_binary'])
with open(p, 'w', encoding='utf-8') as f:
    json.dump(cur, f, ensure_ascii=False, indent=2)
PY

cd /app/backend
exec python app.py
