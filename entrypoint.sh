#!/bin/sh
set -e

echo "Running database migrations..."
uv run alembic upgrade head

echo "Starting application..."
exec uv run uvicorn contact_wrangler.api:app --host 0.0.0.0 --port 8000