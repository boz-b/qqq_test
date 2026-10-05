"""Offline scheduler boundaries: no provider, database or Git remote access."""
from datetime import datetime
import fcntl
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import mac_publish as publisher


class MacPublishTests(unittest.TestCase):
    def test_schedule_and_new_york_date_across_dst(self):
        for month, day in ((10, 6), (11, 3)):
            now = datetime(2026, month, day, 1, tzinfo=publisher.ISTANBUL)
            self.assertEqual(publisher.scheduled_job(now),
                             (now.date().isoformat(), "tuesday_refresh.sh",
                              now.astimezone(publisher.NEW_YORK).date().isoformat()))
            self.assertEqual(now.astimezone(publisher.NEW_YORK).day, day - 1)
        self.assertEqual(publisher.scheduled_job(datetime(2026, 10, 10, 1,
                         tzinfo=publisher.ISTANBUL))[1], "nightly_refresh.sh")

    def test_missed_slots_and_unscheduled_days_do_not_catch_up(self):
        for day, hour, minute in ((5, 1, 0), (11, 1, 0), (6, 1, 1), (6, 8, 0), (6, 0, 59)):
            self.assertIsNone(publisher.scheduled_job(datetime(2026, 10, day, hour, minute,
                                                       tzinfo=publisher.ISTANBUL)))

    def test_plist_has_only_five_0100_slots_and_no_restart_loop(self):
        value = publisher.launchd_plist(Path("/fixture"))
        self.assertEqual(value["StartCalendarInterval"],
                         [{"Weekday": day, "Hour": 1, "Minute": 0} for day in range(2, 7)])
        self.assertFalse(value["RunAtLoad"])
        self.assertFalse(value["KeepAlive"])

    def test_disabled_and_late_runs_never_reach_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime(2026, 10, 6, 1, tzinfo=publisher.ISTANBUL)
            with patch.object(publisher, "preflight") as preflight:
                self.assertEqual(publisher.run(root, now), 0)
                (root / "env").mkdir()
                config = root / "env/mac-publishing.json"
                config.write_text('{"enabled": false}')
                self.assertEqual(publisher.run(root, now), 0)
                config.write_text('{"enabled": true}')
                self.assertEqual(publisher.run(root, now.replace(hour=8)), 0)
                preflight.assert_not_called()
            self.assertFalse((root / "logs").exists())

    def test_failure_is_recorded_once_and_lock_prevents_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "env").mkdir()
            (root / "env/mac-publishing.json").write_text(
                '{"enabled": true, "database_url": "fixture"}')
            now = datetime(2026, 10, 6, 1, tzinfo=publisher.ISTANBUL)
            with patch.object(publisher, "preflight"), patch.object(
                    publisher.subprocess, "run", return_value=SimpleNamespace(returncode=7)) as child:
                self.assertEqual(publisher.run(root, now), 7)
                self.assertEqual(publisher.run(root, now), 0)
                child.assert_called_once()
                self.assertEqual(child.call_args.kwargs["env"]["NEWS_TARGET_DATE"], "2026-10-05")
                self.assertEqual(child.call_args.kwargs["env"]["QQQ_CRON_DATA_BACKEND"], "postgres")
                self.assertTrue(child.call_args.kwargs["pass_fds"])
                receipt = json.loads((root / "logs/mac-publishing/2026-10-06.json").read_text())
                self.assertEqual(receipt["status"], "failed")
                with (root / "logs/mac-publishing/publisher.lock").open("a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.assertEqual(publisher.run(root, now.replace(day=7)), 0)
                child.assert_called_once()

    def test_preflight_failure_never_launches_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "env").mkdir()
            (root / "env/mac-publishing.json").write_text('{"enabled": true}')
            with patch.object(publisher, "preflight", side_effect=RuntimeError("fixture")), \
                    patch.object(publisher.subprocess, "run") as child:
                with self.assertRaises(RuntimeError):
                    publisher.run(root, datetime(2026, 10, 6, 1, tzinfo=publisher.ISTANBUL))
                child.assert_not_called()


if __name__ == "__main__":
    unittest.main()
