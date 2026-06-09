# Local environment setup

This project keeps real API keys outside git.

## Files

- `env.example/finnhub.env.example` is the safe Finnhub template committed to git.
- `env/finnhub.env` is the real local Finnhub file and is ignored by git.
- `env.example/llm_summary.env.example` is the safe optional AI-summary template committed to git.
- `env/llm_summary.env` is the real local AI-summary file and is ignored by git.
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
7. Do not commit files under `env/`.

The implementation calls Gemini's REST `generateContent` endpoint and the public FinancialJuice RSS feed with `requests`, so no extra Python SDK dependency is required. Gemini is requested with JSON mode plus a response schema; `LLM_SUMMARY_MAX_OUTPUT_TOKENS` controls how much room the model has to close the returned JSON, and `LLM_SUMMARY_THINKING_BUDGET=0` keeps hidden thinking from consuming that output budget.

If Gemini fails for a date that already has summary rows, cron preserves those existing summaries. If there is no usable summary, cron skips news persistence for that date instead of writing raw headline fallback rows. Raw provider responses are only kept briefly in ignored local `data/news_request_cache.csv`; `NEWS_REQUEST_CACHE_TTL_DAYS` controls that cache's retention window.

## Python rule

Use only the project-local `venv/` for dependencies. Do not install Python libraries globally on this computer.

## Local runtime setup

Run this from the project root after cloning or restoring the repo:

```bash
scripts/setup_local_runtime.sh
```

The script creates `data/`, `logs/`, `env/`, `env/finnhub.env`, `env/llm_summary.env`, and `venv/`, installs `requirements.txt` into `venv/`, and syntax-checks the Python files.
