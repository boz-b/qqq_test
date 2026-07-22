# qqq_test Architecture

## Purpose

This repo maintains a QQQ intraday dashboard and static website. It combines market price data, macro calendar events, and AI-summarized market news into committed `public/data/*.json` payloads deployed by Vercel.

## Current Boundaries

- `data_loader.py` refreshes intraday and daily QQQ price CSV caches.
- `news_feeds.py` builds the daily brief from weekly USD macro calendar data, optional Brave Search actual enrichment, Finnhub, FinancialJuice RSS, and optional Gemini news summaries.
- `dashboard.py` loads local data and builds per-day dashboard payloads.
- `export_json.py` writes static JSON under `public/data/` and can commit/push export changes.
- `postgres_export.py` mirrors dashboard payloads from PostgreSQL when `QQQ_DATA_BACKEND=postgres`.
- `database.py`, `db/migrations/`, and `scripts/db_*.py` own the optional PostgreSQL path.
- `scripts/cron_export_static.sh` is the cron export gate for CSV or PostgreSQL scheduled exports.
- `public/index.html` is the deployed static frontend.

## Data Flow

```text
Yahoo Finance price data ──> data/*.csv ──┐
Weekly USD calendar CSV ───> data/ff_events.csv ─┐
Brave Search ──────────────> released macro actuals ─┤
Finnhub / FinancialJuice ──> Gemini news summaries ──┼─> dashboard.py ─> export_json.py ─> public/data/*.json
PostgreSQL optional store ───────────────────────────┘                 └> GitHub/Vercel
```

## Backend Modes

- `QQQ_DATA_BACKEND=csv` is the default manual/export mode.
- `QQQ_DATA_BACKEND=postgres` exports payloads through `postgres_export.py`.
- `QQQ_CRON_DATA_BACKEND=csv` keeps scheduled export on CSV.
- `QQQ_CRON_DATA_BACKEND=postgres` refreshes CSVs, backfills PostgreSQL, runs parity, then exports from PostgreSQL.

## Operational Invariants

- `public/data/dates.json` is the active deployed date list.
- `export_json.py` prunes stale static day files outside the active date list.
- Raw provider news should not be published as durable daily brief rows; use `News Summary` rows.
- Missing macro `Actual`, `Forecast`, or `Previous` values should export as blanks, not `nan`.
- Cron should not run competing CSV and PostgreSQL export helpers in parallel because both write shared local caches.
