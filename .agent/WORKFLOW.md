# Agentic Git Workflow for qqq_test

## Principle

GitHub is the durable coordination layer. Issues define tasks, branches isolate work, PRs carry implementation and review context, and CI provides the merge gate.

## Default Flow

1. Create or choose a GitHub issue with objective, scope, acceptance criteria, and verification.
2. Start a branch from the latest `origin/main`.
3. Use a separate git worktree for parallel agent work when multiple agents may edit at once.
4. Implement only the declared scope.
5. Run `make ci` locally when data/env prerequisites exist.
6. Open a draft PR with the template.
7. Review the PR diff, generated data changes, operational risk, and CI output.
8. Merge only after checks pass.

## Branch Names

Use:

```text
agent/issue-123-short-slug
fix/issue-123-short-slug
feature/issue-123-short-slug
experiment/short-slug
```

Use `agent/` for normal agent implementation work and `fix/` for narrowly scoped defects.

## Helper Commands

Check repo state:

```bash
make agent-status
```

Create a normal branch in the current checkout:

```bash
scripts/agent_task.sh start 123 news-summary-fallback
```

Create a separate worktree for parallel work:

```bash
scripts/agent_task.sh start 123 news-summary-fallback --worktree
```

Run the local verification gate:

```bash
make ci
```

Open a draft PR when GitHub CLI is installed and authenticated:

```bash
scripts/agent_task.sh open-pr
```

Clean up a merged local branch:

```bash
scripts/agent_task.sh cleanup agent/issue-123-news-summary-fallback
```

## Task Scope Template

Every agent task should include:

- issue ID or explicit task ID
- objective
- expected files to edit
- files that must not be edited
- acceptance criteria
- verification command, usually `make ci`
- data, deployment, cron, database, and API quota impact

## Human Orchestrator Mode

Boz can serve as orchestrator by deciding which issue to run next, assigning branch scope, and reviewing PRs. Agents should use GitHub issues, branches, PRs, CI, and worktrees as the coordination layer unless explicitly asked to run a separate orchestration system.
