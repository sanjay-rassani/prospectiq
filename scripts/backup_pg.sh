#!/usr/bin/env bash
# Nightly Postgres backup for ProspectIQ (P10-1).
# Intended to run via systemd timer on the host that can reach Postgres.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${PROSPECTIQ_BACKUP_DIR:-$ROOT/backups}"
RETENTION_DAYS="${PROSPECTIQ_BACKUP_RETENTION_DAYS:-14}"
COMPOSE_FILE="${PROSPECTIQ_COMPOSE_FILE:-$ROOT/docker-compose.yml}"
SERVICE="${PROSPECTIQ_POSTGRES_SERVICE:-db}"
DB_NAME="${POSTGRES_DB:-prospectiq}"
DB_USER="${POSTGRES_USER:-prospectiq}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$BACKUP_DIR/prospectiq_${STAMP}.sql.gz"

echo "Writing $OUT"
docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" \
  pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner --no-acl \
  | gzip -c > "$OUT"

# Retention
find "$BACKUP_DIR" -name 'prospectiq_*.sql.gz' -type f -mtime +"$RETENTION_DAYS" -print -delete || true
echo "Backup complete. Retention ${RETENTION_DAYS}d."
ls -lh "$OUT"
