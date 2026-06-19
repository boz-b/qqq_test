# Local environment setup

This project keeps real API keys outside git.

## Files

- `env.example/finnhub.env.example` is the safe Finnhub template committed to git.
- `env/finnhub.env` is the real local Finnhub file and is ignored by git.
- `env.example/llm_summary.env.example` is the safe optional AI-summary template committed to git.
- `env/llm_summary.env` is the real local AI-summary file and is ignored by git.
- `env.example/database.env.example` is the safe optional PostgreSQL template committed to git.
- `env/database.env` is the real local database config file and is ignored by git.
- `.env` and `.env.*` are also ignored for local-only overrides.

## Finnhub key setup

1. Copy `env.example/finnhub.env.example` to `env/finnhub.env`.
2. Put the real Finnhub key in `env/finnhub.env` only.
3. Do not commit files under `env/`.

## Gemini AI news summary setup

The daily news pipeline stores concise Gemini-generated bullet summaries instead of raw Finnhub/FinancialJuice headlines.

1. Copy `env.example/llm_summary.env.example` to `env/llm_summary.env` if the local file does not already exist.
2. Put the real Google AI Studio / Gemini API key in `GEMINI_API_KEY=...` inside `env/llm_summary.env` only.
3. Keep `LLM_SUMMARY_PROVIDER=gemini`.
4. Keep `GEMINI_MODEL=gemini-flash-latest` for the cheap/fast Gemini Flash alias, or change it to another Gemini model such as `gemini-3-flash-preview`.
5. Keep `FINANCIALJUICE_FEED_ENABLED=1` if you want Gemini to include same-day FinancialJuice breaking-news RSS items in addition to Finnhub candidates.
6. Set `LLM_SUMMARY_ENABLED=1` when you want the Tuesday/nightly cron refresh to use Gemini summaries.
7. For actual-value Search grounding, copy `env.example/calendar_actuals.env.example` to ignored `env/calendar_actuals.env` and put the separate key in `GEMINI_CALENDAR_ACTUALS_API_KEY=...`.
8. Leave `LLM_CALENDAR_ACTUALS_ENABLED=0` unless you explicitly want nightly cron to spend Gemini Search quota on released macro-calendar `Actual` values.
9. Do not commit files under `env/`.

The implementation calls Gemini's REST `generateContent` endpoint and the public FinancialJuice RSS feed with `requests`, so no extra Python SDK dependency is required. Gemini is requested with JSON mode plus a response schema; `LLM_SUMMARY_MAX_OUTPUT_TOKENS` controls how much room the model has to close the returned JSON, and `LLM_SUMMARY_THINKING_BUDGET=0` keeps hidden thinking from consuming that output budget.

If Gemini fails for a date that already has summary rows, cron preserves those existing summaries. If there is no usable summary, cron stores the top scored related-news headlines as `News Summary`-compatible fallback rows so the website still has market news. Raw provider responses are only kept briefly in ignored local `data/news_request_cache.csv`; `NEWS_REQUEST_CACHE_TTL_DAYS` controls that cache's retention window.

Macro-calendar actual lookup is opt-in and can use a separate Gemini key from `env/calendar_actuals.env`. When enabled, it runs only for the current or future target date, waits `LLM_CALENDAR_ACTUALS_DELAY_MINUTES` after the scheduled event time, and leaves `Actual` blank unless Gemini Search returns a clear released value. It does not backfill previous days. If Gemini returns HTTP 429, the pipeline writes an ignored local backoff marker tied to a non-secret key fingerprint and skips more actual lookups for `LLM_CALENDAR_ACTUALS_QUOTA_BACKOFF_HOURS`.

## PostgreSQL database backend

The database layer is available for opt-in static export validation. `QQQ_DATA_BACKEND=csv` remains the default and keeps the current website path unchanged. Use `QQQ_DATA_BACKEND=postgres` only after PostgreSQL is migrated and backfilled.

1. Copy `env.example/database.env.example` to `env/database.env` if setup has not already created it.
2. Edit `DATABASE_URL=...` in `env/database.env` for the local PostgreSQL database.
3. Validate migration files without connecting: `venv/bin/python scripts/db_migrate.py --dry-run`.
4. Apply migrations when PostgreSQL is ready: `venv/bin/python scripts/db_migrate.py`.
5. Preview the idempotent CSV/static JSON backfill: `venv/bin/python scripts/db_backfill.py`.
6. Load current local data when PostgreSQL is ready: `venv/bin/python scripts/db_backfill.py --migrate-first --apply`.
7. Verify DB export parity against current static JSON: `venv/bin/python scripts/db_export_parity.py`.
8. Test a DB-backed export without Git writes: `QQQ_DATA_BACKEND=postgres venv/bin/python export_json.py --no-git`.
9. Test the cron DB path without Git writes: `EXPORT_JSON_FLAGS=--no-git QQQ_CRON_DATA_BACKEND=postgres bash scripts/cron_export_static.sh`.

The schema is plain PostgreSQL and TimescaleDB-ready. `price_bars` uses `bar_seconds` for 1m, daily, and future shorter bars. Durable news tables store AI summary rows only, not raw provider news candidates.

`QQQ_CRON_DATA_BACKEND=csv` is the cron default and keeps the active scheduled refresh on the original CSV/export path. Set `QQQ_CRON_DATA_BACKEND=postgres` only when the local PostgreSQL service should drive cron exports; that path refreshes price CSVs, backfills the DB, checks DB-vs-CSV parity, then exports static JSON from PostgreSQL.

## Python rule

Use only the project-local `venv/` for dependencies. Do not install Python libraries globally on this computer.

## Local runtime setup

Run this from the project root after cloning or restoring the repo:

```bash
scripts/setup_local_runtime.sh
```

The script creates `data/`, `logs/`, `env/`, `env/finnhub.env`, `env/llm_summary.env`, `env/database.env`, and `venv/`, installs `requirements.txt` into `venv/`, syntax-checks the Python files, and dry-run validates DB migrations.
