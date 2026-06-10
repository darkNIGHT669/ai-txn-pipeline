#!/usr/bin/env bash
set -euo pipefail

# ── Wait for PostgreSQL ────────────────────────────────────────────────────
echo "[entrypoint] Waiting for PostgreSQL at db:5432 ..."
until python -c "
import socket, sys
try:
    s = socket.create_connection(('db', 5432), timeout=2)
    s.close()
    sys.exit(0)
except OSError:
    sys.exit(1)
" 2>/dev/null; do
  echo "[entrypoint] Postgres not ready — retrying in 2s ..."
  sleep 2
done
echo "[entrypoint] PostgreSQL is ready."

# ── Wait for Redis ─────────────────────────────────────────────────────────
echo "[entrypoint] Waiting for Redis at redis:6379 ..."
until python -c "
import redis, sys
try:
    redis.Redis(host='redis', port=6379).ping()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
  echo "[entrypoint] Redis not ready — retrying in 2s ..."
  sleep 2
done
echo "[entrypoint] Redis is ready."

# ── Determine role ─────────────────────────────────────────────────────────
MODE="${MODE:-web}"

if [ "$MODE" = "worker" ]; then
  echo "[entrypoint] Starting Celery worker ..."
  exec celery -A app.tasks.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    --queues=celery
else
  echo "[entrypoint] Running database table creation ..."
  python -c "
import asyncio
from app.database import create_all_tables
asyncio.run(create_all_tables())
print('[entrypoint] Tables ready.')
"
  echo "[entrypoint] Starting FastAPI (uvicorn) ..."
  exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 2 \
    --log-level info
fi
