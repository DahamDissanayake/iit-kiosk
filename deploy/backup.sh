#!/usr/bin/env bash
# Nightly SQLite backup (knowledge base, stats, settings). Keeps 7 days on the Pi and
# copies the newest to BACKUP_TARGET (e.g. daham@laptop:/backups/kiosk) when set in .env.
set -euo pipefail

DATA=${KIOSK_DATA_DIR:-/var/lib/kiosk}
DEST=$DATA/backups
mkdir -p "$DEST"
file=$DEST/kiosk-$(date +%F).db
sqlite3 "$DATA/kiosk.db" ".backup '$file'"
find "$DEST" -name 'kiosk-*.db' -type f | sort | head -n -7 | xargs -r rm --

target=$(sed -n 's/^BACKUP_TARGET=//p' "$DATA/.env" 2>/dev/null || true)
if [[ -n $target ]]; then
  rsync -a "$file" "$target/"
  echo "backup copied to $target"
else
  echo "BACKUP_TARGET not set: backup kept on the Pi only" >&2
fi
