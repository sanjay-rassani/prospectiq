#!/usr/bin/env bash
# Restore ProspectIQ from a gzipped pg_dump (P10-3).
# WARNING: replaces the target database contents.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 path/to/prospectiq_YYYYMMDD.sql.gz" >&2
  exit 1
fi

DUMP="$1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${PROSPECTIQ_COMPOSE_FILE:-$ROOT/docker-compose.yml}"
SERVICE="${PROSPECTIQ_POSTGRES_SERVICE:-db}"
DB_NAME="${POSTGRES_DB:-prospectiq}"
DB_USER="${POSTGRES_USER:-prospectiq}"

if [[ ! -f "$DUMP" ]]; then
  echo "Dump not found: $DUMP" >&2
  exit 1
fi

echo "Restoring $DUMP into ${DB_NAME} (service=${SERVICE})"
gunzip -c "$DUMP" | docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" \
  psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1
echo "Restore finished. Run: .venv/bin/alembic upgrade head"
