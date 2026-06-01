#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
BACKUP_DIR="$ROOT_DIR/backups"
mkdir -p "$BACKUP_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: .env file not found at $ENV_FILE"
  exit 1
fi

# Load DATABASE_URL from .env
set -a
source "$ENV_FILE"
set +a

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "Error: DATABASE_URL is not set in .env"
  exit 1
fi

# Parse PostgreSQL URL safely (supports URL-encoded password)
readarray -t DB_PARTS < <(python - <<'PY'
import os
from urllib.parse import urlparse, unquote

url = os.environ["DATABASE_URL"]
parsed = urlparse(url)
print(parsed.hostname or "")
print(parsed.port or 5432)
print(parsed.username or "")
print(unquote(parsed.password or ""))
print((parsed.path or "/").lstrip("/"))
PY
)

DB_HOST="${DB_PARTS[0]}"
DB_PORT="${DB_PARTS[1]}"
DB_USER="${DB_PARTS[2]}"
DB_PASS="${DB_PARTS[3]}"
DB_NAME="${DB_PARTS[4]}"

if [[ -z "$DB_HOST" || -z "$DB_USER" || -z "$DB_NAME" ]]; then
  echo "Error: Could not parse DATABASE_URL correctly"
  exit 1
fi

TIMESTAMP="$(date +"%Y%m%d_%H%M%S")"
BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_backup_${TIMESTAMP}.dump"

export PGPASSWORD="$DB_PASS"
pg_dump \
  --host="$DB_HOST" \
  --port="$DB_PORT" \
  --username="$DB_USER" \
  --format=custom \
  --file="$BACKUP_FILE" \
  "$DB_NAME"
unset PGPASSWORD

echo "Backup completed: $BACKUP_FILE"
