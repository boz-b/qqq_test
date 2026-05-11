#!/usr/bin/env bash
# Use Bash because this installer builds a multi-line crontab block safely.

set -euo pipefail
# Stop immediately if a command fails, an unset variable is used, or a pipeline fails.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Find the absolute project root by going one folder up from this script's directory.

WEEKLY_LOG="$REPO_DIR/logs/weekly_calendar_refresh.log"
# Store Monday weekly-calendar job output in its own log file.

NIGHTLY_LOG="$REPO_DIR/logs/nightly_refresh.log"
# Store Tuesday-through-Saturday heavier refresh output in its own log file.

mkdir -p "$REPO_DIR/logs"
# Create the log folder before cron tries to append to the log files.

CRON_CONTENT=$(cat <<EOF
# qqq_test automated refresh jobs managed by scripts/install_crons.sh
# Monday 01:00 Europe/Istanbul: refresh weekly USD calendar and export static data.
0 1 * * 1 cd $REPO_DIR && /usr/bin/env bash scripts/weekly_calendar_refresh.sh >> $WEEKLY_LOG 2>&1
# Tuesday-Saturday 01:45 Europe/Istanbul: refresh news/macro data and export static data.
45 1 * * 2-6 cd $REPO_DIR && /usr/bin/env bash scripts/nightly_refresh.sh >> $NIGHTLY_LOG 2>&1
EOF
)
# Build the exact crontab block that should exist for this project.

(
# Start a subshell so the existing-crontab filtering and new-block printing feed one pipe into crontab.
    crontab -l 2>/dev/null | grep -vF "$REPO_DIR" || true
# Print existing cron lines except older qqq_test lines that mention this project path.
    printf "%s\n" "$CRON_CONTENT"
# Append the freshly generated qqq_test cron block.
) | crontab -
# Install the filtered old crontab plus the new qqq_test block.

echo "Installed cron schedule:"
# Print a short heading before showing the resulting crontab.

crontab -l
# Show the final crontab so the operator can verify the installed schedule.
