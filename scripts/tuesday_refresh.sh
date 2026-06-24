#!/usr/bin/env bash
# Use Bash because this script coordinates two existing Bash refresh scripts safely.

set -euo pipefail
# Stop immediately if any step fails so cron logs show the real failing command.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Find the absolute project root by going one folder up from this script's directory.

cd "$REPO_DIR"
# Run every later command from the project root so relative paths are predictable under cron.

echo "[$(date --iso-8601=seconds)] Starting Tuesday combined weekly + Finnhub refresh in $REPO_DIR"
# Print a timestamped start marker so the Tuesday cron log is easy to scan.

mkdir -p logs data
# Ensure local runtime folders exist before either child script writes files.

/usr/bin/env bash scripts/ensure_deploy_branch.sh
# Switch to the configured deploy branch once before the coordinated Tuesday refresh starts.

echo "[$(date --iso-8601=seconds)] Step 1/2: refresh weekly USD calendar without exporting yet"
# Explain that the calendar cache updates first, but the final deploy waits for the Finnhub refresh.

SKIP_EXPORT_JSON=1 /usr/bin/env bash scripts/weekly_calendar_refresh.sh
# Update the weekly macro-calendar CSV/cache and skip its export so Tuesday deploy happens once at the end.

echo "[$(date --iso-8601=seconds)] Step 2/2: run Finnhub/news refresh and final export/deploy"
# Explain that the heavier daily job now sees the freshly updated weekly calendar data.

/usr/bin/env bash scripts/nightly_refresh.sh
# Run the normal daily Finnhub/news refresh; this performs the final export_json.py commit/push for Vercel.

echo "[$(date --iso-8601=seconds)] Tuesday combined weekly + Finnhub refresh done"
# Print a timestamped success marker for the Tuesday cron log.
