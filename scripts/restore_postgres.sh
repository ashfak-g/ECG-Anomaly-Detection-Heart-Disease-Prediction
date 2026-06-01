#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: .env file not found at $ENV_FILE"
  exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: ./scripts/restore_postgres.sh <path_to_backup.dump>"
  exit 1
fi

BACKUP_FILE="$1"
if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "Error: Backup file not found: $BACKUP_FILE"
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

echo "This will replace data in database '$DB_NAME'."
read -r -p "Type 'yes' to continue: " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
  echo "Restore cancelled."
  exit 0
fi

export PGPASSWORD="$DB_PASS"
pg_restore \
  --host="$DB_HOST" \
  --port="$DB_PORT" \
  --username="$DB_USER" \
  --dbname="$DB_NAME" \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  "$BACKUP_FILE"
unset PGPASSWORD

echo "Restore completed from: $BACKUP_FILE"
