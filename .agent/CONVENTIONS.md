# qqq_test Agent Conventions

## Development Model

- Use the project-local virtual environment at `venv/`.
- Do not install Python packages globally.
- Add dependencies only after explicit approval.
- Prefer stdlib or existing project dependencies for tests and helpers.
- Use `make ci` as the local verification gate.

## Python Style

- This repo currently uses a flat Python layout; do not assume a `src/` package exists.
- Keep pipeline functions explicit and testable.
- Prefer deterministic parsing, filtering, and validation before LLM calls.
- Avoid broad exception swallowing. Expected data/API failures should leave clear logs and safe fallbacks.
- Add comments only where they explain data-source behavior, quota handling, cron safety, or non-obvious compatibility constraints.

## Data And Secrets

- Never read or print real values from `env/*.env`, `.env*`, `~/.pgpass`, or provider dashboards.
- Keep `public/data/` tracked because it drives the deployed static site.
- Keep `data/*.csv`, `logs/`, `venv/`, and repo-root legacy CSV caches ignored.
- If generated `public/data/` changes are part of a PR, explain why and mention the date range affected.

## Pipeline Safety

- CSV export remains the conservative default path unless a task explicitly changes backend behavior.
- PostgreSQL export must keep parity checks before scheduled publish.
- Gemini news summaries must preserve existing summaries on transient failures.
- Gemini Search calendar actuals must remain opt-in and quota-aware.
- Cron scripts should fail before export/commit/push if prerequisite refresh, backfill, or parity checks fail.

## Tests

- Project regression scripts live under `scripts/test_*.py`.
- Dashboard smoke validation is `venv/bin/python dashboard.py --smoke-test`.
- Database migration dry-run is `venv/bin/python scripts/db_migrate.py --dry-run`.
- Shell scripts should pass `bash -n scripts/*.sh`.
- Behavior changes to fallback, export, cron, or database parity need focused regression coverage.

## PR Expectations

- PRs must describe what changed, why, test evidence, and operational impact.
- Mention skipped checks and why.
- List files outside the original task scope if any were changed.
- Call out any change that affects public data, scheduled cron, database export, API quota, or deployment.
