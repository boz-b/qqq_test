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
- [ ] `make ci` passes, or skipped checks are explained.
- [ ] Data/deployment/cron/database/API quota impact is documented in the PR.

## Verification

```bash
make ci
```

## Notes

<!-- Operational constraints, data-source assumptions, or follow-up tasks. -->
