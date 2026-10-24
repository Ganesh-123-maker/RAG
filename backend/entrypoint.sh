#!/bin/sh
# Backend container entrypoint (Phase A): apply Alembic migrations, then
# start the API. Schema is owned by migrations, not by create_all().
set -e
echo "Running database migrations..."
alembic upgrade head
echo "Starting API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info
