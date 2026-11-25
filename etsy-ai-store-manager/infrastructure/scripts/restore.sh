#!/usr/bin/env bash
# Restores an encrypted backup into TARGET_DATABASE_URL (use a fresh database!).
#   TARGET_DATABASE_URL=... BACKUP_PASSPHRASE=... ./infrastructure/scripts/restore.sh backups/esm-XXXX.dump.gpg
set -euo pipefail
file="${1:?backup file required}"
: "${TARGET_DATABASE_URL:?TARGET_DATABASE_URL is required}"
: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE is required}"
sha256sum -c "$file.sha256"
gpg --batch --decrypt --passphrase-fd 3 "$file" 3<<<"$BACKUP_PASSPHRASE" \
  | pg_restore --no-owner --no-privileges --dbname "$TARGET_DATABASE_URL"
echo "restore ok"
