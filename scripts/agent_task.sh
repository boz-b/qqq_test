#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REMOTE="${AGW_REMOTE:-origin}"
BASE="${AGW_BASE:-main}"
BRANCH_PREFIX="${AGW_BRANCH_PREFIX:-agent}"
WORKTREE_ROOT="${AGW_WORKTREE_ROOT:-$(dirname "$ROOT")/qqq_test-worktrees}"

usage() {
  cat <<'USAGE'
Usage:
  scripts/agent_task.sh status
  scripts/agent_task.sh checks
  scripts/agent_task.sh start <issue-id> <slug> [--worktree] [--prefix agent|fix|feature]
  scripts/agent_task.sh open-pr [--ready] [--title <title>] [--body-file <path>]
  scripts/agent_task.sh cleanup <branch>

Examples:
  scripts/agent_task.sh start 12 news-summary-fallback
  scripts/agent_task.sh start 12 news-summary-fallback --worktree
  scripts/agent_task.sh open-pr

Environment:
  AGW_REMOTE=origin
  AGW_BASE=main
  AGW_BRANCH_PREFIX=agent
  AGW_WORKTREE_ROOT=../qqq_test-worktrees
USAGE
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

run_git() {
  git -C "$ROOT" "$@"
}

current_branch() {
  run_git branch --show-current
}

require_clean_checkout() {
  local status
  status="$(run_git status --porcelain)"
  if [ -n "$status" ]; then
    run_git status --short
    die "checkout has uncommitted changes; commit, stash, or use a clean worktree first"
  fi
}

validate_slug() {
  local slug="$1"
  case "$slug" in
    *[!a-z0-9-]* | "" | -* | *-)
      die "slug must be lowercase letters/numbers/hyphens and cannot start or end with hyphen"
      ;;
  esac
  if [ "${#slug}" -gt 48 ]; then
    die "slug must be 48 characters or fewer"
  fi
}

ensure_venv() {
  if [ ! -x "$ROOT/venv/bin/python" ]; then
    "$ROOT/scripts/setup_local_runtime.sh"
  fi
}

run_checks() {
  ensure_venv
  make pre-pr
}

cmd_status() {
  printf 'Repository: %s\n' "$ROOT"
  printf 'Remote: %s\n' "$REMOTE"
  printf 'Base: %s\n' "$BASE"
  printf 'Current branch: %s\n' "$(current_branch)"
  run_git status --short --branch
  if command -v gh >/dev/null 2>&1; then
    gh pr status || true
  else
    printf 'GitHub CLI: missing. Install gh before using open-pr automation.\n'
  fi
}

cmd_start() {
  [ "$#" -ge 2 ] || die "start requires <issue-id> <slug>"
  local issue_id="$1"
  local slug="$2"
  shift 2

  local use_worktree=0
  local prefix="$BRANCH_PREFIX"
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --worktree)
        use_worktree=1
        shift
        ;;
      --prefix)
        [ "$#" -ge 2 ] || die "--prefix requires a value"
        prefix="$2"
        shift 2
        ;;
      *)
        die "unknown start option: $1"
        ;;
    esac
  done

  validate_slug "$slug"
  case "$prefix" in
    agent | fix | feature | hotfix | experiment) ;;
    *) die "prefix must be one of: agent, fix, feature, hotfix, experiment" ;;
  esac

  local branch
  if [ "$prefix" = "experiment" ]; then
    branch="experiment/$slug"
  else
    branch="$prefix/issue-$issue_id-$slug"
  fi

  run_git fetch "$REMOTE" "$BASE"
  if run_git show-ref --verify --quiet "refs/heads/$branch"; then
    die "local branch already exists: $branch"
  fi

  if [ "$use_worktree" -eq 1 ]; then
    local worktree_path="$WORKTREE_ROOT/${branch//\//-}"
    mkdir -p "$WORKTREE_ROOT"
    run_git worktree add -b "$branch" "$worktree_path" "$REMOTE/$BASE"
    printf 'Created worktree: %s\n' "$worktree_path"
  else
    require_clean_checkout
    run_git switch -c "$branch" "$REMOTE/$BASE"
    printf 'Created branch in current checkout: %s\n' "$branch"
  fi
}

cmd_open_pr() {
  local ready=0
  local title=""
  local body_file=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --ready)
        ready=1
        shift
        ;;
      --title)
        [ "$#" -ge 2 ] || die "--title requires a value"
        title="$2"
        shift 2
        ;;
      --body-file)
        [ "$#" -ge 2 ] || die "--body-file requires a path"
        body_file="$2"
        shift 2
        ;;
      *)
        die "unknown open-pr option: $1"
        ;;
    esac
  done

  local branch
  branch="$(current_branch)"
  [ -n "$branch" ] || die "not on a branch"
  [ "$branch" != "$BASE" ] || die "refusing to open a PR from $BASE"

  require_clean_checkout
  run_git fetch "$REMOTE" "$BASE"
  if ! run_git merge-base --is-ancestor "$REMOTE/$BASE" HEAD; then
    die "branch does not include the latest $REMOTE/$BASE; update it before opening the PR"
  fi

  run_checks

  [ -n "$title" ] || title="$(run_git log -1 --pretty=%s)"
  [ -n "$body_file" ] || body_file="$ROOT/.github/PULL_REQUEST_TEMPLATE.md"
  [ -f "$body_file" ] || die "PR body file does not exist: $body_file"
  if [ "$ready" -eq 1 ] && [ "$body_file" = "$ROOT/.github/PULL_REQUEST_TEMPLATE.md" ]; then
    die "--ready requires a completed --body-file instead of the unedited default template"
  fi

  if ! command -v gh >/dev/null 2>&1; then
    printf 'GitHub CLI is not installed. Run these manually after installing/authenticating gh:\n'
    printf '  git push -u %s %s\n' "$REMOTE" "$branch"
    printf '  gh pr create --base %s --head %s --title %q --body-file %q%s\n' \
      "$BASE" "$branch" "$title" "$body_file" "$([ "$ready" -eq 1 ] || printf ' --draft')"
    exit 0
  fi

  run_git push -u "$REMOTE" "$branch"
  if [ "$ready" -eq 1 ]; then
    gh pr create --base "$BASE" --head "$branch" --title "$title" --body-file "$body_file"
  else
    gh pr create --base "$BASE" --head "$branch" --draft --title "$title" --body-file "$body_file"
  fi
}

cmd_cleanup() {
  [ "$#" -eq 1 ] || die "cleanup requires <branch>"
  local branch="$1"
  [ "$branch" != "$BASE" ] || die "refusing to cleanup $BASE"
  require_clean_checkout
  run_git fetch "$REMOTE" "$BASE"
  run_git switch "$BASE"
  run_git pull --ff-only "$REMOTE" "$BASE"
  run_git branch -d "$branch"
  run_git worktree prune
}

main() {
  [ "$#" -ge 1 ] || {
    usage
    exit 1
  }

  case "$1" in
    status)
      shift
      cmd_status "$@"
      ;;
    checks)
      shift
      run_checks "$@"
      ;;
    start)
      shift
      cmd_start "$@"
      ;;
    open-pr)
      shift
      cmd_open_pr "$@"
      ;;
    cleanup)
      shift
      cmd_cleanup "$@"
      ;;
    -h | --help | help)
      usage
      ;;
    *)
      usage
      die "unknown command: $1"
      ;;
  esac
}

main "$@"
