#!/usr/bin/env bash
# Nightly Postgres backup for the prod stack.
#   - dumps the db container with pg_dump, gzips to ~/hamyon-backups
#   - keeps the last 14 dumps (rotation)
#   - if BACKUP_GCS_BUCKET is set in .env.prod and gsutil is available,
#     uploads off-site to GCS (survives full VM loss)
#
# Run from anywhere; cron example (nightly 03:00):
#   0 3 * * * /home/$USER/hamyon/deploy/backup.sh >> /home/$USER/hamyon-backups/backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."                 # repo root (~/hamyon)
DC="sudo docker compose --env-file .env.prod -f docker-compose.prod.yml"
OUT="$HOME/hamyon-backups"
KEEP=14
mkdir -p "$OUT"

# DB creds from .env.prod (+ optional BACKUP_GCS_BUCKET)
set -a; . ./.env.prod; set +a

TS="$(date +%Y%m%d-%H%M%S)"
FILE="$OUT/hamyon-$TS.sql.gz"

echo "[$(date -Is)] dumping ${DB_NAME} ..."
$DC exec -T db pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$FILE"
echo "[$(date -Is)] wrote $FILE ($(du -h "$FILE" | cut -f1))"

# rotation: keep newest $KEEP
ls -1t "$OUT"/hamyon-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

# off-site copy
if [ -n "${BACKUP_GCS_BUCKET:-}" ] && command -v gsutil >/dev/null 2>&1; then
  if gsutil -q cp "$FILE" "gs://$BACKUP_GCS_BUCKET/"; then
    echo "[$(date -Is)] uploaded to gs://$BACKUP_GCS_BUCKET/"
  else
    echo "[$(date -Is)] WARN: GCS upload failed (local copy kept)"
  fi
fi
