# Local environment setup

This project keeps real API keys outside git.

## Files

- `env.example/finnhub.env.example` is the safe Finnhub template committed to git.
- `env/finnhub.env` is the real local Finnhub file and is ignored by git.
- `env.example/llm_summary.env.example` is the safe optional AI-summary template committed to git.
- `env/llm_summary.env` is the real local AI-summary file and is ignored by git.
- `env.example/brave_search.env.example` is the safe optional macro-actual Search template committed to git.
- `env/brave_search.env` is the real local Brave Search file and is ignored by git.
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
4. Keep production pinned to `GEMINI_MODEL=gemini-2.5-flash`. Avoid mutable `*-latest` aliases because Google may hot-swap them to a different model without changing the alias.
5. Keep `FINANCIALJUICE_FEED_ENABLED=1` if you want Gemini to include same-day FinancialJuice breaking-news RSS items in addition to Finnhub candidates.
6. Set `LLM_SUMMARY_ENABLED=1` when you want the Tuesday/nightly cron refresh to use Gemini summaries.
7. Gemini is used only for news summarization; macro-calendar actual lookup is configured separately through Brave Search.
8. Do not commit files under `env/`.

The implementation calls Gemini's REST `generateContent` endpoint and the public FinancialJuice RSS feed with `requests`, so no extra Python SDK dependency is required. Gemini is requested with JSON mode plus a response schema; `LLM_SUMMARY_MAX_OUTPUT_TOKENS` controls how much room the model has to close the returned JSON. For the compatible Gemini 2.5 Flash family, `LLM_SUMMARY_THINKING_BUDGET=0` disables thinking so visible JSON keeps the output budget. Unknown and mutable `*-latest` models omit `thinkingConfig` rather than receiving a potentially incompatible field.

If Gemini fails for a date that already has summary rows, cron preserves those existing summaries. If there is no usable summary, cron stores the top scored related-news headlines as `News Summary`-compatible fallback rows so the website still has market news. Raw provider responses are only kept briefly in ignored local `data/news_request_cache.csv`; `NEWS_REQUEST_CACHE_TTL_DAYS` controls that cache's retention window.

## Brave Search macro actual setup

Macro-calendar actual lookup uses Brave Web Search and deterministic snippet parsing; it does not require a Gemini actuals key or model call.

1. Copy `env.example/brave_search.env.example` to `env/brave_search.env` if the local file does not already exist.
2. Put the real Brave subscription token in `BRAVE_SEARCH_API_KEY=...` inside `env/brave_search.env` only.
3. Keep `LLM_CALENDAR_ACTUALS_PROVIDER=brave`.
4. Set `LLM_CALENDAR_ACTUALS_ENABLED=1` after the key has been tested.
5. Keep `BRAVE_SEARCH_MAX_REQUESTS_PER_DAY` and `LLM_CALENDAR_ACTUALS_MAX_EVENTS_PER_DAY` conservative; one Brave request is made per eligible event and the daily cap persists across repeated runs.
6. Keep the positive and negative cache TTLs conservative so manual reruns do not repeat paid searches unnecessarily.
7. Do not commit files under `env/`.

When enabled, actual lookup runs only for the current or future target date, waits `LLM_CALENDAR_ACTUALS_DELAY_MINUTES` after the scheduled event time, and scopes Brave results to the exact target release day. Acceptance requires exact release-date evidence, strong event relevance, a matching weekly/monthly reference period when one is stated, clear release language, the correct unit type, and a valid actual value. Forecast, previous, stale-period, preview, and conflicting values are rejected. A single fresh result may qualify regardless of domain; source reputation is only a confidence boost. Evidence may also be combined across fresh results, such as a dated EIA release result plus a separate target-day result containing the actual value. Forecast and previous values remain excluded from the search query. The flow does not backfill previous days. Ignored `data/calendar_actuals_search_state.json` stores daily request counts, versioned positive/negative outcomes, and source titles/URLs for auditing. Parser-versioned cache keys prevent old negative results from suppressing corrected parsing. After an HTTP 429, the provider/key-specific backoff marker also honors Brave's `Retry-After` header.

After migrating, the old ignored `env/calendar_actuals.env` Gemini credential is no longer loaded or required. Delete that local file and revoke its separate Gemini key if it will not be used elsewhere.

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

The script creates `data/`, `logs/`, `env/`, `env/finnhub.env`, `env/llm_summary.env`, `env/brave_search.env`, `env/database.env`, and `venv/`, installs `requirements.txt` into `venv/`, syntax-checks the Python files, and dry-run validates DB migrations.
