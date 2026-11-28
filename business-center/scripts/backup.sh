#!/usr/bin/env bash
# Veritabanı yedeği: sıkıştırılmış pg_dump, 14 günlük saklama.
# Supabase'in kendi günlük yedeklerine EK olarak, kendi kontrolünüzdeki bir yere alınır.
# Kullanım (cron, her gece 03:15):  15 3 * * * BACKUP_DIR=/var/backups/bizcenter /opt/bizcenter/scripts/backup.sh
set -euo pipefail
: "${BC_DATABASE_URL:?BC_DATABASE_URL gerekli}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p "$BACKUP_DIR"
file="$BACKUP_DIR/bizcenter-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
pg_dump --no-owner --no-privileges --schema=public --schema=app "$BC_DATABASE_URL" | gzip -9 > "$file.tmp"
mv "$file.tmp" "$file"
find "$BACKUP_DIR" -name 'bizcenter-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
echo "yedek: $file ($(du -h "$file" | cut -f1))"
