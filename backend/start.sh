#!/bin/sh
# Container start: migrate the database, kick off the idempotent first-start setup in the background
# (loading demo data takes about a minute, so it must not delay the health check), then run the API.
# $PORT is provided by hosts such as Render; it defaults to 8000 everywhere else.
set -e
alembic upgrade head
( python -m app.cli bootstrap || echo "bootstrap failed - see the lines above" ) &
# Optional: run the scheduled jobs inside this container (for hosts with no free background workers, e.g. Render free).
# Uses more memory: leave it off unless the plan has room.
if [ "${RUN_WORKER:-false}" = "true" ]; then
  celery -A app.workers.celery_app worker -B -l info -Q default,ingestion --concurrency 1 &
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
