#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="$REPO_DIR/logs/export.log"
mkdir -p "$REPO_DIR/logs"

CRON_CONTENT=$(cat <<EOF
0 1 * * 1 cd $REPO_DIR && /usr/bin/env bash scripts/weekly_calendar_refresh.sh >> $LOG_FILE 2>&1
45 1 * * 2-6 cd $REPO_DIR && /usr/bin/env bash scripts/nightly_refresh.sh >> $LOG_FILE 2>&1
EOF
)

( crontab -l 2>/dev/null | grep -v "$REPO_DIR" || true; printf "%s\n" "$CRON_CONTENT" ) | crontab -

echo "Installed cron schedule:"
crontab -l
