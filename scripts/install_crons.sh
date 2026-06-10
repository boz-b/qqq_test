#!/usr/bin/env bash
# Use Bash because this installer builds a multi-line crontab block safely.

set -euo pipefail
# Stop immediately if a command fails, an unset variable is used, or a pipeline fails.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Find the absolute project root by going one folder up from this script's directory.

TUESDAY_LOG="$REPO_DIR/logs/tuesday_refresh.log"
# Store the Tuesday combined weekly-calendar + Finnhub refresh output in its own log file.

NIGHTLY_LOG="$REPO_DIR/logs/nightly_refresh.log"
# Store Wednesday-through-Saturday Finnhub refresh output in its own log file.

mkdir -p "$REPO_DIR/logs"
# Create the log folder before cron tries to append to the log files.

CRON_CONTENT=$(cat <<EOF
# BEGIN qqq_test automated refresh jobs managed by scripts/install_crons.sh
# Tuesday 02:00 local computer time: refresh weekly USD calendar first, then run Finnhub/news refresh and final Vercel export.
# Export uses CSV by default; set QQQ_CRON_DATA_BACKEND=postgres in ignored env/database.env for the parity-checked DB path.
0 2 * * 2 cd $REPO_DIR && /usr/bin/env bash scripts/tuesday_refresh.sh >> $TUESDAY_LOG 2>&1
# Wednesday-Saturday 02:00 local computer time: run Finnhub/news refresh and final Vercel export.
# Export uses CSV by default; set QQQ_CRON_DATA_BACKEND=postgres in ignored env/database.env for the parity-checked DB path.
0 2 * * 3-6 cd $REPO_DIR && /usr/bin/env bash scripts/nightly_refresh.sh >> $NIGHTLY_LOG 2>&1
# END qqq_test automated refresh jobs managed by scripts/install_crons.sh
EOF
)
# Build the exact crontab block that should exist for this project.

(
# Start a subshell so the existing-crontab filtering and new-block printing feed one pipe into crontab.
    crontab -l 2>/dev/null \
        | grep -vF "$REPO_DIR" \
        | grep -vF "qqq_test" \
        | grep -vF "Monday 01:00 Europe/Istanbul" \
        | grep -vF "Tuesday-Saturday 01:45 Europe/Istanbul" \
        | grep -vF "Tuesday 02:00 local computer time" \
        | grep -vF "Wednesday-Saturday 02:00 local computer time" \
        || true
# Print existing cron lines except older qqq_test lines/comments from any previous installer version.
    printf "%s\n" "$CRON_CONTENT"
# Append the freshly generated qqq_test cron block.
) | crontab -
# Install the filtered old crontab plus the new qqq_test block.

echo "Installed cron schedule:"
# Print a short heading before showing the resulting crontab.

crontab -l
# Show the final crontab so the operator can verify the installed schedule.
