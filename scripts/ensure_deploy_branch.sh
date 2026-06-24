#!/usr/bin/env bash
# Keep scheduled data refreshes on the branch that Vercel deploys.

set -euo pipefail

DEPLOY_REMOTE="${QQQ_DEPLOY_REMOTE:-origin}"
DEPLOY_BRANCH="${QQQ_DEPLOY_BRANCH:-main}"

if [ "${QQQ_SKIP_DEPLOY_BRANCH_GUARD:-0}" = "1" ]; then
    echo "[$(date --iso-8601=seconds)] Deploy branch guard skipped by QQQ_SKIP_DEPLOY_BRANCH_GUARD=1"
    exit 0
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "[$(date --iso-8601=seconds)] ERROR: deploy branch guard must run inside a Git worktree"
    exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
    echo "[$(date --iso-8601=seconds)] ERROR: refusing to switch deploy branches with a dirty worktree"
    git status --short
    exit 1
fi

current_branch="$(git branch --show-current)"
if [ -z "$current_branch" ]; then
    echo "[$(date --iso-8601=seconds)] ERROR: refusing deploy refresh from detached HEAD"
    exit 1
fi

echo "[$(date --iso-8601=seconds)] Ensuring deploy branch ${DEPLOY_REMOTE}/${DEPLOY_BRANCH}"
git fetch "$DEPLOY_REMOTE" "$DEPLOY_BRANCH"

if [ "$current_branch" != "$DEPLOY_BRANCH" ]; then
    echo "[$(date --iso-8601=seconds)] Switching from ${current_branch} to ${DEPLOY_BRANCH}"
    git checkout "$DEPLOY_BRANCH"
fi

git merge --ff-only FETCH_HEAD

local_head="$(git rev-parse HEAD)"
remote_head="$(git rev-parse FETCH_HEAD)"
if [ "$local_head" != "$remote_head" ]; then
    echo "[$(date --iso-8601=seconds)] ERROR: local ${DEPLOY_BRANCH} is not exactly ${DEPLOY_REMOTE}/${DEPLOY_BRANCH}"
    echo "local:  ${local_head}"
    echo "remote: ${remote_head}"
    exit 1
fi

echo "[$(date --iso-8601=seconds)] Deploy branch ready: ${DEPLOY_BRANCH} @ ${local_head}"
