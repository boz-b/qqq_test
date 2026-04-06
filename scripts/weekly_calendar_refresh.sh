#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

mkdir -p logs data
source venv/bin/activate

read -r START_DATE END_DATE <<EOF
$(python3 - <<'PY'
from datetime import date, timedelta

today = date.today()
start = today - timedelta(days=35)
end = today + timedelta(days=14)
print(start.isoformat(), end.isoformat())
PY
)
EOF

echo "[$(date --iso-8601=seconds)] Refreshing weekly USD calendar only: ${START_DATE} -> ${END_DATE}"
python3 - <<PY
from news_feeds import save_calendar_only_events
save_calendar_only_events("${START_DATE}", "${END_DATE}")
PY

echo "[$(date --iso-8601=seconds)] Exporting static dashboard data"
python3 export_json.py

echo "[$(date --iso-8601=seconds)] Weekly calendar refresh done"
