#!/bin/sh
set -e
python - <<'PY'
import os
import socket
import time
from urllib.parse import urlparse

raw = os.environ.get("DATABASE_URL", "")
parsed = urlparse(raw.replace("postgresql+asyncpg", "postgresql", 1))
host = parsed.hostname or "localhost"
port = parsed.port or 5432
for _ in range(60):
    try:
        with socket.create_connection((host, port), 2):
            break
    except OSError:
        time.sleep(2)
else:
    raise SystemExit(f"database {host}:{port} did not accept connections")
PY
alembic upgrade head
exec uvicorn api.main:app --host 0.0.0.0 --port 8000
