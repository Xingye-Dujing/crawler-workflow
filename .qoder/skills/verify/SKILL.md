---
name: verify
description: Verify the app can start by testing imports and the Flask server. Use before reporting the app as working.
---

0. Code quality check (Ruff):
```bash
cd backend && ../.venv/Scripts/ruff check --fix . && ../.venv/Scripts/ruff format --check .
```

If errors remain after auto‑fix, fix them manually according to the output.

1. Test imports:
```bash
cd backend && ../.venv/Scripts/python.exe -c "
import sys
sys.path.insert(0, '..')
from backend.app import app
print('All imports OK')
"
```

2. Start the server briefly and check the API:
```bash
cd backend && ../.venv/Scripts/python.exe app.py &
SERVER_PID=$!
sleep 3
curl -sf http://localhost:5000/api/config > /dev/null && echo "Server OK" || echo "Server FAILED"
kill $SERVER_PID 2>/dev/null
```

3. Common fixes:
- **Circular import in services/stats.py**: replace the stub with a proper `StatsService` class
- **Missing dependencies**: run `../.venv/Scripts/pip.exe install -r ../requirements.txt`
- **Port conflict**: set `PORT` env var to a different value
