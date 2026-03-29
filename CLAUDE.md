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
```

- `data_loader.py` refreshes **intraday + daily** CSV caches in `data/`
- `ff_scraper.py` refreshes the ForexFactory CSV separately in `data/`
- `dashboard.py` reads the CSV caches and computes per-day payloads
- `export_json.py` writes static JSON files to `public/data/`
- only `public/data/` is intended for static-site deployment

### Important behavior notes

- All timestamps are **America/New_York**, DST-aware
- Premarket = **8:00–9:29 ET**
- W1 = **9:30–10:00 ET**
- W2 = **10:00–10:30 ET**
- `export_json.py` does **not** scrape ForexFactory by itself; it reuses the latest `data/ff_events.csv`
- `dashboard.py` prefers `data/*.csv` and keeps a repo-root CSV fallback for older checkouts

## Data files

Canonical cache location:

- `data/qqq_1m.csv`
- `data/qqq_daily.csv`
- `data/ff_events.csv`

Generated static output:

- `public/data/dates.json`
- `public/data/YYYY-MM-DD.json`

## Git hygiene

Local cache / runtime files should stay out of git:

- `venv/`
- `logs/`
- `data/*.csv`

Keep `public/data/` tracked because Vercel deploys from the committed static JSON.
