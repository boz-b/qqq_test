#!/usr/bin/env python3
"""
export_json.py — Pre-compute all dashboard data and write static JSON files.
============================================================================

Run this nightly on the Raspberry Pi via cron (after US market close):

    0 21 * * 1-5  cd /home/pi/qqq_test && venv/bin/python3 export_json.py >> logs/export.log 2>&1

What it does:
  1. Refreshes intraday + daily CSV data and reuses the latest combined news/macro CSV
  2. Imports get_available_dates() and get_day_data() from dashboard.py
  3. Writes public/data/dates.json  — array of all trading dates
  4. Writes public/data/YYYY-MM-DD.json  — one payload file per date
  5. git commit + push → GitHub → Vercel auto-deploys the updated files

The Vercel-hosted index.html fetches these static JSON files directly,
so the interactive date picker works without any server-side code.
"""

import json
import os
import subprocess
import sys
from datetime import datetime

# ── Ensure imports resolve relative to this script's directory ───────────────
# Needed when the cron job runs without the repo as the working directory.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)                   # all relative paths below are from BASE_DIR
sys.path.insert(0, BASE_DIR)

from database import load_database_env  # noqa: E402

NO_GIT = "--no-git" in sys.argv
# ↑ Let local validation write/check JSON files without committing or pushing them to GitHub.

load_database_env()
DATA_BACKEND = (os.getenv("QQQ_DATA_BACKEND") or "csv").strip().lower()
if DATA_BACKEND not in {"csv", "postgres"}:
    print(f"ERROR: unsupported QQQ_DATA_BACKEND={DATA_BACKEND!r}. Use 'csv' or 'postgres'.")
    sys.exit(1)

# ── Step 1: Refresh source data ───────────────────────────────────────────────
# Call the same refresh command documented in CLAUDE.md.
# This refreshes intraday + daily CSVs under data/. The combined news/macro
# feed is maintained separately by news_feeds.py; export_json.py will use
# whatever CSV is already available. If refresh fails, log a warning but
# continue — the existing CSVs are still valid; we just won't have today's data yet.
print(f"\n{'='*60}")
print(f"export_json.py  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"{'='*60}")
print(f"Data backend: {DATA_BACKEND}")

if DATA_BACKEND == "csv":
    try:
        from data_loader import DataLoader
        print("Refreshing data via DataLoader.fetch_all() …")
        DataLoader().fetch_all()
        print("Intraday + daily refresh complete.")
    except ModuleNotFoundError:
        print("data_loader not found — using existing CSV files.")
    except Exception as exc:
        print(f"WARNING: data refresh failed ({exc}) — using existing CSV files.")
else:
    print("PostgreSQL backend selected — skipping CSV price refresh.")

# ── Step 2: Import dashboard functions ────────────────────────────────────────
# dashboard.py loads the three CSVs at module level for the default path.
# postgres_export.py mirrors the same payload shape from PostgreSQL when
# QQQ_DATA_BACKEND=postgres is explicitly selected.
if DATA_BACKEND == "postgres":
    from postgres_export import get_available_dates, get_day_data   # noqa: E402
else:
    from dashboard import get_available_dates, get_day_data   # noqa: E402

dates = get_available_dates()
if not dates:
    print("ERROR: no trading dates found in intraday CSV. Exiting.")
    sys.exit(1)

print(f"Found {len(dates)} trading dates  ({dates[0]} … {dates[-1]})")

# ── Step 3: Write static JSON files ──────────────────────────────────────────
OUT_DIR = os.path.join(BASE_DIR, "public", "data")
os.makedirs(OUT_DIR, exist_ok=True)


def _is_day_payload_filename(filename: str) -> bool:
    """Return True for static day payload names such as 2026-06-08.json."""
    if not filename.endswith(".json") or filename == "dates.json":
        return False
    try:
        datetime.strptime(filename[:-5], "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _prune_stale_day_payloads(out_dir: str, active_dates: list[str]) -> list[str]:
    """Delete old day JSON files that are no longer listed in dates.json."""
    active_filenames = {f"{date_str}.json" for date_str in active_dates}
    pruned: list[str] = []
    for filename in sorted(os.listdir(out_dir)):
        if not _is_day_payload_filename(filename):
            continue
        if filename in active_filenames:
            continue
        path = os.path.join(out_dir, filename)
        os.remove(path)
        pruned.append(filename)
    return pruned


pruned_payloads = _prune_stale_day_payloads(OUT_DIR, dates)
if pruned_payloads:
    print(f"  Pruned {len(pruned_payloads)} stale day JSON file(s) from public/data/")
else:
    print("  No stale day JSON files to prune from public/data/")

# dates.json — simple array; the JS loadDates() function fetches this first
dates_path = os.path.join(OUT_DIR, "dates.json")
with open(dates_path, "w") as fh:
    json.dump(dates, fh)
print(f"  Written dates.json  ({len(dates)} entries)")

# One JSON file per trading date — payload matches exactly what /api/day returned
errors = []
for date_str in dates:
    payload = get_day_data(date_str)
    if "error" in payload:
        # Log but continue — a single bad date shouldn't abort the whole export
        print(f"  WARNING: {date_str} → {payload['error']}")
        errors.append(date_str)
        continue
    out_path = os.path.join(OUT_DIR, f"{date_str}.json")
    with open(out_path, "w") as fh:
        # separators=(',', ':') produces compact JSON (no whitespace) — smaller
        # file size means faster fetches from Vercel's CDN edge nodes.
        json.dump(payload, fh, separators=(",", ":"))
    bar_count = len(payload["chart"]["labels"])
    print(f"  {date_str}.json  ({bar_count} bars, "
          f"{payload['prior_close'] or 'no'} prior close, "
          f"{len(payload['ff_events'])} brief items)")  # `ff_events` is still the legacy JSON key for brief rows.

if errors:
    print(f"\nWARNING: {len(errors)} date(s) had errors: {errors}")

if NO_GIT:
    # ↑ If local validation requested no Git writes, stop after generating JSON files.
    print("\n--no-git supplied — generated public/data files but skipped git commit/push.")
    # ↑ Make it clear in logs that the export succeeded but deployment was intentionally skipped.
    sys.exit(0)
    # ↑ Exit successfully before the normal git staging/commit/push deployment step.

# ── Step 4: git commit + push ─────────────────────────────────────────────────
# Stage only the pre-computed data files — never the raw CSVs (they're in .gitignore).
print("\nStaging public/data/ …")
subprocess.run(["git", "add", "public/data/"], check=True)

# Check whether there is anything new to commit
status = subprocess.run(
    ["git", "status", "--porcelain", "public/data/"],
    capture_output=True, text=True, check=True
)
if not status.stdout.strip():
    print("Nothing changed — no commit needed.")
    sys.exit(0)

# Commit with a date-stamped message
commit_msg = f"data: refresh {dates[-1]}"
result = subprocess.run(
    ["git", "commit", "-m", commit_msg],
    capture_output=True, text=True
)
if result.returncode != 0:
    print(f"git commit failed:\n{result.stderr}")
    sys.exit(result.returncode)
print(f"Committed: {commit_msg}")

# Push — retry up to 4 times with exponential back-off (2s, 4s, 8s, 16s)
import time
for attempt, wait in enumerate([0, 2, 4, 8, 16], start=1):
    if wait:
        print(f"Push attempt {attempt} (waiting {wait}s) …")
        time.sleep(wait)
    push = subprocess.run(["git", "push"], capture_output=True, text=True)
    if push.returncode == 0:
        print(f"Pushed successfully on attempt {attempt}.")
        break
    print(f"Push failed: {push.stderr.strip()}")
else:
    print("ERROR: all push attempts failed.")
    sys.exit(1)

print(f"\nDone. Vercel will auto-deploy within ~30 seconds.")
