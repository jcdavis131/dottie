#!/usr/bin/env sh
# Solo personal project, no connection to employer, built with public/free-tier only.
#
# Nightly jarvisd SQLite backup via the online backup API (safe while the daemon runs),
# 14-day retention inside the volume, optional rclone push to R2.
#
#   ./deploy/backup.sh                                   # local only
#   RCLONE_REMOTE=r2:jarvis-backups ./deploy/backup.sh   # + rclone copy
#   KEEP_DAYS=30 ./deploy/backup.sh
#
# Run from anywhere; it cds to the repo root. Exit non-zero if the backup file was not
# produced -- a cron line that "succeeds" without a file is the failure mode to avoid.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

COMPOSE="docker compose --env-file deploy/.env -f docker-compose.jarvisd.yml"
STAMP=$(date +%F)
KEEP_DAYS=${KEEP_DAYS:-14}
NAME="jarvis-${STAMP}.db"

# .backup is atomic from the reader's side; WAL pages are folded in.
$COMPOSE exec -T jarvisd sqlite3 /data/jarvis.db ".backup /data/backup/${NAME}"
$COMPOSE exec -T jarvisd sh -c "test -s /data/backup/${NAME}" || {
    echo "backup.sh: /data/backup/${NAME} missing or empty" >&2
    exit 1
}
$COMPOSE exec -T jarvisd sh -c "find /data/backup -name 'jarvis-*.db' -mtime +${KEEP_DAYS} -delete"
SIZE=$($COMPOSE exec -T jarvisd sh -c "wc -c < /data/backup/${NAME}" | tr -d '[:space:]')
echo "backup.sh: ${NAME} (${SIZE} bytes) in volume jarvisd-data"

if [ -n "${RCLONE_REMOTE:-}" ]; then
    command -v rclone >/dev/null 2>&1 || { echo "backup.sh: rclone not installed" >&2; exit 1; }
    TMP=$(mktemp -d)
    trap 'rm -rf "$TMP"' EXIT
    $COMPOSE cp "jarvisd:/data/backup/${NAME}" "$TMP/${NAME}"
    rclone copy "$TMP/${NAME}" "${RCLONE_REMOTE}/" --s3-no-check-bucket
    echo "backup.sh: pushed ${NAME} to ${RCLONE_REMOTE}"
fi
