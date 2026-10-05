#!/usr/bin/env python3
"""Opt-in Mac publisher. Rendering the launchd plist never installs a job."""
from __future__ import annotations

import argparse
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ISTANBUL = ZoneInfo("Europe/Istanbul")
NEW_YORK = ZoneInfo("America/New_York")
LABEL = "com.boz.qqq-publish"


def scheduled_job(now):
    """Accept only the scheduled minute; wake/login must not replay old slots."""
    local = now.astimezone(ISTANBUL)
    if local.hour != 1 or local.minute != 0 or local.weekday() not in range(1, 6):
        return None
    script = "tuesday_refresh.sh" if local.weekday() == 1 else "nightly_refresh.sh"
    return local.date().isoformat(), script, local.astimezone(NEW_YORK).date().isoformat()


def launchd_plist(root):
    # Calendar triggers use the host timezone. Activation requires Istanbul;
    # the runtime gate independently refuses any other actual local time.
    return {
        "Label": LABEL,
        "ProgramArguments": [str(root / "venv/bin/python"),
                             str(root / "scripts/mac_publish.py"), "--run"],
        "WorkingDirectory": str(root),
        "StartCalendarInterval": [{"Weekday": day, "Hour": 1, "Minute": 0}
                                  for day in range(2, 7)],
        "RunAtLoad": False,
        "KeepAlive": False,
        "EnvironmentVariables": {"TZ": "Europe/Istanbul",
                                 "PATH": "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "StandardOutPath": str(root / "logs/mac-publishing.log"),
        "StandardErrorPath": str(root / "logs/mac-publishing.log"),
    }


def git_output(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def preflight(root, config):
    if sys.platform != "darwin":
        raise RuntimeError("Mac publisher requires Darwin")
    if not str(Path("/etc/localtime").resolve()).endswith("/Europe/Istanbul"):
        raise RuntimeError("Host timezone must remain Europe/Istanbul")
    if git_output(root, "branch", "--show-current") != "main":
        raise RuntimeError("Publisher requires a dedicated main checkout")
    if git_output(root, "status", "--porcelain"):
        raise RuntimeError("Publisher checkout is dirty; review before retry")
    if not (root / "venv/bin/python").is_file():
        raise RuntimeError("Project Python is missing")
    # Only check presence; provider values are loaded by the established pipeline.
    for name in ("finnhub.env", "llm_summary.env", "brave_search.env"):
        if not (root / "env" / name).is_file():
            raise RuntimeError("Required operator provider configuration is missing")
    # A stopped/read-only DB must fail before paid provider calls. Never start
    # PostgreSQL or change its role defaults from this scheduler.
    import psycopg
    with psycopg.connect(config["database_url"], connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_read_only")
            if cursor.fetchone()[0] != "off":
                raise RuntimeError("Publishing DB remains read-only")


def run(root, now):
    config_path = root / "env/mac-publishing.json"
    if not config_path.is_file():
        print("DISABLED: activation configuration absent")
        return 0
    config = json.loads(config_path.read_text())
    if config.get("enabled") is not True:
        print("DISABLED: awaiting reviewed activation")
        return 0
    job = scheduled_job(now)
    if job is None:
        print("SKIPPED: outside 01:00 Istanbul slot; missed runs require review")
        return 0
    day, script, market_day = job
    state = root / "logs/mac-publishing"
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    # The lock spans calendar/news/backfill/export/Git, not each child in turn.
    with (state / "publisher.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("SKIPPED: another publisher owns the lock")
            return 0
        attempt = state / (day + ".json")
        if attempt.exists():
            print("SKIPPED: slot already attempted; failure/retry requires review")
            return 0
        preflight(root, config)
        # Persist the attempt before any provider/write path. A crash never
        # becomes permission to repeat requests automatically on the same day.
        with attempt.open("x") as receipt:
            json.dump({"status": "started", "market_date": market_day}, receipt)
            receipt.flush()
            os.fsync(receipt.fileno())
        env = os.environ.copy()
        for key in ("QQQ_SKIP_DEPLOY_BRANCH_GUARD", "EXPORT_JSON_FLAGS",
                    "SKIP_EXPORT_JSON", "PGOPTIONS"):
            env.pop(key, None)
        env.update(TZ="Europe/Istanbul", NEWS_TARGET_DATE=market_day,
                   QQQ_DEPLOY_REMOTE="origin", QQQ_DEPLOY_BRANCH="main",
                   QQQ_CRON_DATA_BACKEND="postgres", QQQ_DATA_BACKEND="csv",
                   GIT_TERMINAL_PROMPT="0")
        env["DATABASE_URL"] = config["database_url"]
        # Keep the lock held by the shell if the Python supervisor exits early.
        result = subprocess.run(["/bin/bash", str(root / "scripts" / script)],
                                cwd=root, env=env, pass_fds=(lock.fileno(),))
        with attempt.open("w") as receipt:
            json.dump({"status": "passed" if result.returncode == 0 else "failed",
                       "returncode": result.returncode, "market_date": market_day}, receipt)
            receipt.flush()
            os.fsync(receipt.fileno())
        return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--render-plist", type=Path, metavar="PUBLISHER_ROOT")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.render_plist:
        sys.stdout.buffer.write(plistlib.dumps(launchd_plist(args.render_plist.resolve())))
        return 0
    try:
        return run(ROOT, datetime.now(ISTANBUL))
    except Exception as error:
        # Connection/config exceptions can embed credentials; log only the type.
        print("FAILED: publisher preflight/execution; review locally (" + type(error).__name__ + ")")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
