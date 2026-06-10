# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Layout

This repo currently uses a **flat layout**:

- `data_loader.py`
- `ff_scraper.py`
- `features.py`
- `labeler.py`
- `strategy.py`
- `backtester.py`
- `dashboard.py`
- `export_json.py`

Do **not** assume a `src/` package exists.

## Common Commands

```bash
# Activate environment (always required first)
source venv/bin/activate

# Refresh intraday + daily price caches under data/
python3 -c "from data_loader import DataLoader; DataLoader().fetch_all()"

# Refresh ForexFactory events separately
python3 ff_scraper.py --start YYYY-MM-DD --end YYYY-MM-DD --csv data/ff_events.csv

# Export static JSON for Vercel (and commit/push if public/data changed)
python3 export_json.py

# Compare DB-generated payloads against current static JSON
python3 scripts/db_export_parity.py

# Cron-safe export helper; CSV by default, Postgres only with QQQ_CRON_DATA_BACKEND=postgres
EXPORT_JSON_FLAGS=--no-git bash scripts/cron_export_static.sh

# Launch local dashboard
python3 dashboard.py

# Quick smoke test for dashboard data loading
python3 dashboard.py --smoke-test
```

## Architecture

### Deployment flow

```text
Yahoo Finance ─┐
               ├─> data/*.csv ──> export_json.py ──> public/data/*.json ──> GitHub ──> Vercel
ForexFactory ──┘
PostgreSQL ───────> postgres_export.py --^  (only when QQQ_DATA_BACKEND=postgres)
```

- `data_loader.py` refreshes **intraday + daily** CSV caches in `data/`
- `ff_scraper.py` refreshes the ForexFactory CSV separately in `data/`
- `dashboard.py` reads the CSV caches and computes per-day payloads
- `export_json.py` writes static JSON files to `public/data/`
- only `public/data/` is intended for static-site deployment
- `db/` contains the PostgreSQL schema; the live website still defaults to the CSV/export path
- `scripts/db_backfill.py` previews or loads current CSV/static JSON data into PostgreSQL; it is idempotent and requires `--apply` before writing
- `postgres_export.py` mirrors the static JSON payload from PostgreSQL when `QQQ_DATA_BACKEND=postgres`
- `scripts/db_export_parity.py` compares the DB payloads against current `public/data/*.json` before any cutover
- `scripts/cron_export_static.sh` is the cron export gate: it uses CSV by default, and with `QQQ_CRON_DATA_BACKEND=postgres` it refreshes price CSVs, backfills PostgreSQL, checks DB-vs-CSV parity, then exports from PostgreSQL

### Important behavior notes

- All timestamps are **America/New_York**, DST-aware
- Premarket = **8:00–9:29 ET**
- W1 = **9:30–10:00 ET**
- W2 = **10:00–10:30 ET**
- `export_json.py` does **not** scrape ForexFactory by itself; it reuses the latest `data/ff_events.csv`
- `dashboard.py` prefers `data/*.csv` and keeps a repo-root CSV fallback for older checkouts
- `scripts/db_migrate.py --dry-run` validates database migrations without requiring PostgreSQL
- `scripts/db_backfill.py` dry-runs the current CSV/static JSON import without connecting to PostgreSQL
- `QQQ_DATA_BACKEND=csv` is the default; use `QQQ_DATA_BACKEND=postgres venv/bin/python export_json.py --no-git` for DB-backed export validation
- `QQQ_CRON_DATA_BACKEND=csv` is the cron default; set it to `postgres` in ignored `env/database.env` only when the local PostgreSQL service should drive cron exports
- durable news storage should use AI `News Summary` rows only, not raw provider headlines

## Data files

Canonical cache location:

- `data/qqq_1m.csv`
- `data/qqq_daily.csv`
- `data/ff_events.csv`

Generated static output:

- `public/data/dates.json`
- `public/data/YYYY-MM-DD.json`

Database scaffold:

- `db/migrations/001_initial_schema.sql`
- `scripts/db_migrate.py`
- `scripts/db_backfill.py`
- `scripts/db_export_parity.py`
- `scripts/cron_export_static.sh`
- `postgres_export.py`
- `env.example/database.env.example`

## Git hygiene

Local cache / runtime files should stay out of git:

- `venv/`
- `logs/`
- `data/*.csv`
- repo-root legacy CSV caches (`qqq_1m.csv`, `qqq_daily.csv`, `ff_events.csv`)

Keep `public/data/` tracked because Vercel deploys from the committed static JSON.
`export_json.py` prunes old `public/data/YYYY-MM-DD.json` files so GitHub only carries dates listed in `public/data/dates.json`.
