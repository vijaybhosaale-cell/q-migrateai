#!/bin/sh
# Daily PostgreSQL backup, kept for BACKUP_KEEP_DAYS (default 14). Runs inside the "backup" container.
set -eu
KEEP="${BACKUP_KEEP_DAYS:-14}"
mkdir -p /backups
while true; do
  STAMP=$(date -u +%Y-%m-%d_%H%M)
  FILE="/backups/qmigrate_${STAMP}.sql.gz"
  if pg_dump -h postgres -U postgres -d qmigrate --no-owner | gzip > "${FILE}.tmp"; then
    mv "${FILE}.tmp" "${FILE}"
    echo "backup written: ${FILE}"
  else
    rm -f "${FILE}.tmp"
    echo "backup FAILED at ${STAMP}" >&2
  fi
  find /backups -name 'qmigrate_*.sql.gz' -mtime "+${KEEP}" -delete
  sleep 86400
done
