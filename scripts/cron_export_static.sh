#!/usr/bin/env bash
# Export static dashboard data for cron, optionally using the PostgreSQL backend.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$REPO_DIR"

if [ ! -x venv/bin/python ]; then
    echo "[$(date --iso-8601=seconds)] ERROR: venv missing; run scripts/setup_local_runtime.sh first"
    exit 1
fi

source venv/bin/activate

_env_value() {
    local key="$1"
    local file="$2"
    local line=""

    if [ -f "$file" ]; then
        line="$(grep -E "^[[:space:]]*${key}=" "$file" | tail -n 1 || true)"
    fi

    if [ -n "$line" ]; then
        line="${line#*=}"
        printf "%s" "$line" \
            | sed -e 's/^[[:space:]]*//' \
                  -e 's/[[:space:]]*$//' \
                  -e 's/^"//' \
                  -e 's/"$//' \
                  -e "s/^'//" \
                  -e "s/'$//"
    fi
}

CRON_BACKEND="${QQQ_CRON_DATA_BACKEND:-}"
if [ -z "$CRON_BACKEND" ]; then
    CRON_BACKEND="$(_env_value QQQ_CRON_DATA_BACKEND env/database.env)"
fi
if [ -z "$CRON_BACKEND" ]; then
    CRON_BACKEND="${QQQ_DATA_BACKEND:-csv}"
fi

case "$CRON_BACKEND" in
    csv|postgres)
        ;;
    *)
        echo "[$(date --iso-8601=seconds)] ERROR: unsupported QQQ_CRON_DATA_BACKEND=${CRON_BACKEND}"
        exit 1
        ;;
esac

EXPORT_JSON_FLAGS="${EXPORT_JSON_FLAGS:-}"

echo "[$(date --iso-8601=seconds)] Cron export backend: ${CRON_BACKEND}"

if [ "$CRON_BACKEND" = "postgres" ]; then
    echo "[$(date --iso-8601=seconds)] Refreshing intraday + daily price CSVs before DB backfill"
    python - <<'PY'
from data_loader import DataLoader

DataLoader().fetch_all()
PY

    echo "[$(date --iso-8601=seconds)] Backfilling refreshed CSV/static data into PostgreSQL"
    python scripts/db_backfill.py --migrate-first --apply

    echo "[$(date --iso-8601=seconds)] Checking PostgreSQL export parity against current CSV source"
    python scripts/db_export_parity.py --source csv --ignore-event-order --allow-extra-postgres-dates

    echo "[$(date --iso-8601=seconds)] Exporting static dashboard data from PostgreSQL"
    QQQ_DATA_BACKEND=postgres QQQ_POSTGRES_EXPORT_DATE_SOURCE=csv python export_json.py ${EXPORT_JSON_FLAGS}
else
    echo "[$(date --iso-8601=seconds)] Exporting static dashboard data from CSV"
    QQQ_DATA_BACKEND=csv python export_json.py ${EXPORT_JSON_FLAGS}
fi
