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

TARGET_DATE="${NEWS_TARGET_DATE:-$(python - <<'PY'
from datetime import datetime
from zoneinfo import ZoneInfo
# Use the US market date, not the Raspberry Pi's local Istanbul date.

print(datetime.now(ZoneInfo("America/New_York")).date().isoformat())
# Cron runs after the US close, so this is the one market day that needs new news summarization.
PY
)}"
# Allow manual repair runs to override NEWS_TARGET_DATE while cron uses the current New York market date.

echo "[$(date --iso-8601=seconds)] Refreshing combined news + official macro feed for market day: ${TARGET_DATE}"
# Print the exact single date being refreshed; this should produce at most one Gemini request.

python news_feeds.py --start "${TARGET_DATE}" --end "${TARGET_DATE}" --summary-date "${TARGET_DATE}"
# Gather all Finnhub + FinancialJuice items for TARGET_DATE, then make one Gemini summary request for that day.

EXPORT_JSON_FLAGS="${EXPORT_JSON_FLAGS:-}"
# Allow tests to pass --no-git through the environment while cron uses the default commit/push behavior.

echo "[$(date --iso-8601=seconds)] Exporting static dashboard data"
# Print an export start marker before generating public/data JSON files.

/usr/bin/env bash scripts/cron_export_static.sh
# Generate static dashboard JSON from CSV by default, or from PostgreSQL only when QQQ_CRON_DATA_BACKEND=postgres.

echo "[$(date --iso-8601=seconds)] Nightly refresh done"
# Print a timestamped success marker for the cron log.
