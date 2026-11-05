#!/bin/sh
# Container start: migrate the database, kick off the idempotent first-start setup in the background
# (loading demo data takes about a minute, so it must not delay the health check), then run the API.
# $PORT is provided by hosts such as Render; it defaults to 8000 everywhere else.
set -e
alembic upgrade head
( python -m app.cli bootstrap || echo "bootstrap failed - see the lines above" ) &
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
