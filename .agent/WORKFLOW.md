# Agentic Git Workflow for qqq_test

## Principle

GitHub is the durable coordination layer. Issues define tasks, branches isolate work, PRs carry implementation and review context, and CI provides the merge gate.

## Default Flow

1. Create or choose a GitHub issue with objective, scope, acceptance criteria, and verification.
2. Start a branch from the latest `origin/main`.
3. Use a separate git worktree for parallel agent work when multiple agents may edit at once.
4. Implement only the declared scope.
5. Run `make pre-pr` locally when data/env prerequisites exist.
6. Open a draft PR with the template.
7. Review the PR diff, generated data changes, operational risk, and CI output.
8. Merge only after checks pass.
9. Fast-forward the local `main`, verify the merged state, and clean up the feature branch.

## Records And Source Of Truth

- **GitHub issue:** objective, scope, forbidden changes, acceptance criteria, and planned verification.
- **Pull request:** implementation approach, changed files, review findings, test results, risks, and merge decision.
- **Project `MEMORY.md`:** durable architecture and operational decisions that remain useful after the PR is closed.
- **Project `WORKLOG.md`:** temporary handoff state, blockers, local-only runtime details, and the next action.

Do not copy a complete issue or PR narrative into `MEMORY.md` or `WORKLOG.md`. After merge, record only a concise PR/commit pointer and any durable consequence not obvious from the code.

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

Run the full pre-PR verification gate:

```bash
make pre-pr
```

Open a draft PR from the repository template:

```bash
scripts/agent_task.sh open-pr
```

Open a review-ready PR only with a completed body file:

```bash
scripts/agent_task.sh open-pr --ready --title "Short PR title" --body-file /tmp/pr-body.md
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
- verification command, usually `make pre-pr`
- data, deployment, cron, database, and API quota impact

## Merge And Cleanup

After Boz approves and merges a PR:

1. Confirm the PR is merged and checks passed.
2. Switch to `main` and fast-forward from `origin/main`.
3. Run the smallest meaningful post-merge regression/smoke check.
4. Update project memory/worklog only when there is durable or local-only context to preserve.
5. Delete the merged feature branch locally and on GitHub when safe.

Once this scaffold is merged, prefer a GitHub ruleset for `main` that requires pull requests and passing CI and blocks force-pushes. Configure the ruleset separately after CI exists on `main`.

## Human Orchestrator Mode

Boz can serve as orchestrator by deciding which issue to run next, assigning branch scope, and reviewing PRs. Agents should use GitHub issues, branches, PRs, CI, and worktrees as the coordination layer unless explicitly asked to run a separate orchestration system.
