#!/usr/bin/env bash
# Use Bash because this script relies on strict-mode options and Bash-compatible path expansion.

set -euo pipefail
# Stop immediately if a command fails, an unset variable is used, or a pipeline fails.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Find the absolute project root by going one folder up from this script's directory.

cd "$REPO_DIR"
# Run every later command from the project root so relative paths are predictable under cron.

echo "[$(date --iso-8601=seconds)] Starting nightly refresh in $REPO_DIR"
# Print a timestamped start marker so the cron log is easy to scan.

mkdir -p logs data
# Ensure the local log and data-cache folders exist before the refresh writes files.

if [ ! -x venv/bin/python ]; then
# Check that the project-local Python environment exists and has an executable Python.
    echo "[$(date --iso-8601=seconds)] ERROR: venv missing; run scripts/setup_local_runtime.sh first"
# Explain the exact setup command needed instead of failing with a vague Python error.
    exit 1
# Stop because running without the project-local venv would risk using global Python packages.
fi
# Finish the venv preflight check.

git pull --ff-only
# Pull the latest GitHub code/data only when it can be fast-forwarded safely.

source venv/bin/activate
# Activate the project-local Python environment so python and pip commands use local dependencies.

python scripts/prepare_local_data_cache.py
# Recreate/normalize local data caches before refreshing or exporting dashboard JSON.

read -r START_DATE END_DATE <<EOF
$(python - <<'PY'
from datetime import date, timedelta
# Import date helpers used to calculate the refresh window.

start = date.today() - timedelta(days=35)
# Start far enough back to preserve recent market/calendar overlap.

end = date.today() + timedelta(days=14)
# Extend forward so upcoming macro calendar rows are cached too.

print(start.isoformat(), end.isoformat())
# Print both dates on one line so Bash can assign START_DATE and END_DATE.
PY
)
EOF
# Capture the Python-computed date range into two Bash variables.

echo "[$(date --iso-8601=seconds)] Refreshing combined news + official macro feed: ${START_DATE} -> ${END_DATE}"
# Print the exact date window being refreshed.

python news_feeds.py
# Refresh Finnhub/news plus macro/calendar events into the local event CSV cache.

EXPORT_JSON_FLAGS="${EXPORT_JSON_FLAGS:-}"
# Allow tests to pass --no-git through the environment while cron uses the default commit/push behavior.

echo "[$(date --iso-8601=seconds)] Exporting static dashboard data"
# Print an export start marker before generating public/data JSON files.

python export_json.py ${EXPORT_JSON_FLAGS}
# Generate static dashboard JSON and, unless --no-git was supplied, commit/push public/data changes.

echo "[$(date --iso-8601=seconds)] Nightly refresh done"
# Print a timestamped success marker for the cron log.
