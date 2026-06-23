# AGENTS.md - qqq_test

This repository powers the QQQ intraday dashboard, static Vercel export, news/macro event pipeline, and optional PostgreSQL-backed export path.

## Required Startup Context

For development work, read these first:

- `CLAUDE.md`
- `ENVIRONMENT.md`
- `.agent/CONVENTIONS.md`
- `.agent/ARCHITECTURE.md`
- `.agent/WORKFLOW.md`

For database or cron work, also read:

- `db/README.md`
- `POSTGRESQL_SWITCH_GUIDE_2026-06-10.md` from the project memory repo if available

## Safety Rules

- Do not read, print, commit, or copy secrets from `env/`, `.env*`, `~/.pgpass`, or local shell history.
- Keep real Finnhub, Gemini, database, and deployment credentials out of git.
- Use only the project-local `venv/` for Python dependencies.
- Do not install Python packages globally.
- Ask before adding a new dependency to `requirements.txt`.
- Keep `public/data/` tracked; it is the static site payload.
- Keep runtime caches, logs, local env files, and repo-root legacy CSV caches out of git.
- Do not rewrite git history or force-push without explicit approval.

## Git Workflow

- Non-trivial changes should use an issue, a branch, and a pull request.
- Do not commit directly to `main` for feature, bugfix, refactor, data-pipeline, or cron changes.
- Prefer branch names like `agent/issue-123-short-slug` or `fix/issue-123-short-slug`.
- Run `make ci` before opening a PR when local data/env prerequisites are available.
- Use `scripts/agent_task.sh` for local branch/worktree and PR helpers.

## Scope Discipline

- Keep each task small enough for one PR.
- Declare expected files before implementation.
- Preserve existing cron behavior unless the task explicitly changes scheduled exports.
- Keep CSV and PostgreSQL paths compatible unless the task is specifically a backend cutover.
- If a task touches Gemini Search actuals, API quota behavior, Postgres cron export, Vercel data publishing, or historical git data, call out the operational risk in the PR.
