#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

mkdir -p logs data
source venv/bin/activate

read -r START_DATE END_DATE <<EOF
$(python3 - <<'PY'
from datetime import date, timedelta
start = date.today() - timedelta(days=35)
end = date.today() + timedelta(days=14)
print(start.isoformat(), end.isoformat())
PY
)
EOF

echo "[$(date --iso-8601=seconds)] Refreshing ForexFactory data: ${START_DATE} -> ${END_DATE}"
python ff_scraper.py --start "$START_DATE" --end "$END_DATE" --csv data/ff_events.csv --currencies USD

echo "[$(date --iso-8601=seconds)] Exporting static dashboard data"
python export_json.py

echo "[$(date --iso-8601=seconds)] Done"
