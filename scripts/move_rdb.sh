#!/usr/bin/env bash
set -euo pipefail
ROOT="$(pwd)"
DEST="$ROOT/ops/redis"
mkdir -p "$DEST"
if [ ! -f "$ROOT/heart-anomalies-rate-limit.rdb" ]; then
  echo "No heart-anomalies-rate-limit.rdb found in project root; nothing to move." >&2
  exit 0
fi
mv "$ROOT/heart-anomalies-rate-limit.rdb" "$DEST/"
SETTINGS="$DEST/heart-anomalies-rate-limit.rdb.settings"
if [ -f "$SETTINGS" ]; then
  sed -E "s|(\"dbdir\": )\"[^\"]+\"|\\1\"$DEST\"|" "$SETTINGS" > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"
else
  echo "{\"pidfile\": \"/tmp/redis.pid\", \"unixsocket\": \"/tmp/redis.socket\", \"dbdir\": \"$DEST\", \"dbfilename\": \"heart-anomalies-rate-limit.rdb\"}" > "$SETTINGS"
fi

echo "Moved RDB to $DEST and updated settings at $SETTINGS"