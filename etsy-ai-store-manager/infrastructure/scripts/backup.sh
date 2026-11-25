#!/usr/bin/env bash
# Encrypted logical backup of the application database.
#   DATABASE_URL=... BACKUP_PASSPHRASE=... ./infrastructure/scripts/backup.sh
# Cron (daily 03:17): 17 3 * * * cd /opt/esm && ./infrastructure/scripts/backup.sh >> backups/backup.log 2>&1
# Supabase Pro also provides managed daily backups/PITR; this is an extra, off-platform copy.
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL is required}"
: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE is required (backups are always encrypted)}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$BACKUP_DIR/esm-$stamp.dump.gpg"

pg_dump "$DATABASE_URL" --format=custom --no-owner --no-privileges \
  --schema=public --schema=private \
  | gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase-fd 3 -o "$out" 3<<<"$BACKUP_PASSPHRASE"

sha256sum "$out" > "$out.sha256"
find "$BACKUP_DIR" -name 'esm-*.dump.gpg*' -mtime +"$RETENTION_DAYS" -delete
echo "backup ok: $out"
