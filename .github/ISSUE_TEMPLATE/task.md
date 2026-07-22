---
name: Agent task
about: Scoped task for agent or human implementation
title: "[task] "
labels: ["agent-task"]
---

## Objective

<!-- What should change? Keep this small enough for one PR. -->

## Why

<!-- Why this matters now. Link related context if available. -->

## Scope

Expected files:

- `path/to/file.py`

Forbidden files or behavior:

- Do not read, print, or commit credentials.
- Do not rewrite git history.
- Do not change cron/backend behavior unless this task explicitly says so.

## Acceptance Criteria

- [ ] Behavior is implemented.
- [ ] Tests or focused validation cover the new or changed behavior.
- [ ] `make pre-pr` passes, or skipped checks are explained.
- [ ] Data/deployment/cron/database/API quota impact is documented in the PR.

## Verification

```bash
make pre-pr
```

## Records

- Keep task scope and acceptance criteria in this issue.
- Keep implementation/review/test details in the eventual PR.
- Update project `MEMORY.md` only for durable architecture or operational decisions.
- Update project `WORKLOG.md` only for current handoff, blockers, local-only state, or immediate next steps.

## Notes

<!-- Operational constraints, data-source assumptions, or follow-up tasks. -->
