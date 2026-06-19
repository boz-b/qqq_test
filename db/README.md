# qqq_test Database Scaffold

This is the approved PostgreSQL scaffold for moving durable project data into PostgreSQL without changing the current website path by default.

The website still reads the existing CSV/export-generated JSON flow by default. `QQQ_DATA_BACKEND=csv` remains the safe default; `QQQ_DATA_BACKEND=postgres` is available for opt-in static export validation after the database has been migrated and backfilled.

## Setup

1. Install dependencies in the project venv:

   ```bash
   venv/bin/python -m pip install -r requirements.txt
   ```

2. Copy the database env template:

   ```bash
   cp env.example/database.env.example env/database.env
   ```

3. Edit `env/database.env` with the local PostgreSQL connection string.

4. Validate migrations without connecting:

   ```bash
   venv/bin/python scripts/db_migrate.py --dry-run
   ```

5. Apply migrations:

   ```bash
   venv/bin/python scripts/db_migrate.py
   ```

6. Preview the current CSV/static JSON backfill:

   ```bash
   venv/bin/python scripts/db_backfill.py
   ```

7. Load the backfill when PostgreSQL is ready:

   ```bash
   venv/bin/python scripts/db_backfill.py --migrate-first --apply
   ```

8. Compare PostgreSQL-generated payloads with the current committed static JSON:

   ```bash
   venv/bin/python scripts/db_export_parity.py
   ```

9. Run an opt-in PostgreSQL static export locally without committing:

   ```bash
   QQQ_DATA_BACKEND=postgres venv/bin/python export_json.py --no-git
   ```

10. Test the cron export gate without committing:

   ```bash
   venv/bin/python scripts/db_export_parity.py --source csv --ignore-event-order
   EXPORT_JSON_FLAGS=--no-git QQQ_CRON_DATA_BACKEND=postgres bash scripts/cron_export_static.sh
   ```

## Schema Intent

- `instruments`: symbols and provider identifiers.
- `price_bars`: durable OHLCV bars for 1m, daily, and future shorter intervals via `bar_seconds`.
- `market_events`: macro calendar rows and AI-summarized news rows only.
- `news_summaries`: post-AI news summaries linked to `market_events`.
- `ingest_runs`: audit trail for cron/import jobs.
- `features`, `strategy_signals`, `backtest_runs`: future analysis outputs.

## TimescaleDB Path

The initial migration is plain PostgreSQL. When shorter intervals, more symbols, or heavier analysis justify it, `price_bars` can become a TimescaleDB hypertable:

```sql
SELECT create_hypertable('price_bars', 'ts', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
```

Compression and retention can then be added for hot/warm/cold storage policies.

## News Storage Rule

Do not store raw provider payloads in PostgreSQL. Raw provider responses are short-lived local cache only. Durable news rows should be `News Summary` rows: either Gemini-generated summaries or the bounded top related-news fallback used when Gemini is unavailable for the refreshed date.

## Backfill Rule

`scripts/db_backfill.py` is idempotent. It upserts one QQQ instrument, 1m bars from `data/qqq_1m.csv`, daily bars from `data/qqq_daily.csv`, macro/news-summary events from `data/ff_events.csv`, and active static payload events from `public/data/dates.json`.

The importer skips raw `Impact=News` rows and persists `Impact=News Summary` rows into `market_events`/`news_summaries`, including the related-news fallback rows. It collapses duplicate calendar events between the CSV cache and the active static JSON files so PostgreSQL gets one durable event row per `(event_time, kind, source, title)`.

When a row is also present in active static JSON, the importer stores its `public_json_order` in `market_events.event_payload`. The PostgreSQL export path uses that display-order metadata to reproduce the current static webpage payload exactly for rows sharing the same timestamp.

## Export Parity

`postgres_export.py` mirrors `dashboard.py`'s JSON shape from PostgreSQL. `export_json.py` selects it only when `QQQ_DATA_BACKEND=postgres`; otherwise the existing CSV/dashboard path is unchanged.

Run `scripts/db_export_parity.py` before any cutover. It compares PostgreSQL-generated dates and per-day payloads against the current `public/data/*.json` files and exits non-zero on the first mismatch.

For cron, use `scripts/db_export_parity.py --source csv --ignore-event-order` after DB backfill. This checks DB payloads against the freshly refreshed CSV/dashboard source while allowing event display order to remain compatible with existing public JSON for same-timestamp events.

## Cron Backend Gate

The installed Tuesday/nightly scripts call `scripts/cron_export_static.sh` for their final export. It keeps `csv` as the default backend. When `QQQ_CRON_DATA_BACKEND=postgres` is set in ignored `env/database.env` or the cron environment, the helper:

1. Refreshes intraday and daily price CSVs with `DataLoader.fetch_all()`.
2. Runs `scripts/db_backfill.py --migrate-first --apply`.
3. Runs `scripts/db_export_parity.py --source csv --ignore-event-order`.
4. Runs `QQQ_DATA_BACKEND=postgres python export_json.py`.

If any DB step fails, the script exits before `export_json.py` can commit or push static JSON. Set `QQQ_CRON_DATA_BACKEND=csv` or remove the override to return to the CSV export path.

## Retention Rule

GitHub should only carry the static JSON dates shown by the webpage. PostgreSQL is the durable local store for expanded history. If intraday data grows materially, keep 1m bars as the hot tier and move older high-frequency bars to a local cold archive or TimescaleDB retention/compression policy; keep daily bars and AI-summarized news rows durable.
