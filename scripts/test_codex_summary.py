#!/usr/bin/env python3
"""Offline transport, credential isolation, and pipeline fallback regressions."""
from datetime import date
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import codex_summary as transport
import news_feeds as news
import pandas as pd

ROW = {"time": "09:30", "event": "Nasdaq rises with technology shares [TestWire]",
       "impact": "News Summary", "priority": 5}


class SummaryTests(unittest.TestCase):
    def test_config_needs_no_key_and_pins_model(self):
        with patch.object(news, "_load_env"), patch.dict(os.environ, {
            "LLM_SUMMARY_ENABLED": "1", "LLM_SUMMARY_PROVIDER": "codex",
            "GEMINI_MODEL": "other", "LLM_SUMMARY_TIMEOUT_SECONDS": "45",
        }, clear=True):
            config = news._llm_summary_config()
        self.assertEqual((config["model"], config["reasoning_effort"]), ("gpt-6-luna", "medium"))
        self.assertNotIn("api_key", config)
        self.assertEqual(config["timeout"], 180)

    def test_private_provider_override_precedes_gemini(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            override, legacy = root / "codex_summary.env", root / "llm_summary.env"
            override.write_text("LLM_SUMMARY_PROVIDER=codex\nLLM_SUMMARY_ENABLED=1\n")
            legacy.write_text("LLM_SUMMARY_PROVIDER=gemini\nLLM_SUMMARY_MAX_BULLETS=4\n")
            with patch.object(news, "ENV_FILES", [override, legacy]), patch.dict(os.environ, {}, clear=True):
                config = news._llm_summary_config()
                self.assertEqual(config["provider"], "codex")
                self.assertEqual(config["max_bullets"], 4)
        self.assertEqual(news.ENV_FILES[0].name, "codex_summary.env")

    def test_environment_excludes_credentials_and_overrides(self):
        with patch.dict(os.environ, {"HOME": "/safe/home", "OPENAI_API_KEY": "fake",
                                     "CODEX_API_KEY": "fake", "GEMINI_API_KEY": "fake",
                                     "DATABASE_URL": "fake", "CODEX_THREAD_ID": "fake",
                                     "BASH_ENV": "fake", "OPENAI_BASE_URL": "https://example.com"}, clear=True):
            env = transport._environment()
        self.assertEqual(set(env), {"HOME", "PATH", "LANG", "LC_ALL"})

    def test_transport_subprocess_and_invalid_output(self):
        # A real fake CLI tests stdin, spaces in executable paths, and file handling.
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "fake codex"
            binary.write_text(f'''#!{sys.executable}
import json, os, pathlib, sys
args = sys.argv[1:]
if "login" in args:
    print("Logged in using ChatGPT")
    sys.exit(0)
assert "--ignore-user-config" in args and "--ephemeral" in args
assert "--strict-config" in args and "--json" in args
assert args[args.index("--model") + 1] == "gpt-6-luna"
assert 'model_reasoning_effort="medium"' in args
assert 'forced_login_method="chatgpt"' in args
assert 'features.shell_tool=false' in args and 'agents.enabled=false' in args
assert 'web_search="disabled"' in args
assert "OPENAI_API_KEY" not in os.environ
assert "summaries" in sys.stdin.read()
assert pathlib.Path.cwd().name.startswith("qqq-summary-")
schema = json.loads(pathlib.Path(args[args.index("--output-schema") + 1]).read_text())
assert schema["additionalProperties"] is False
print(json.dumps({{"type": "turn.completed"}}))
pathlib.Path(args[args.index("--output-last-message") + 1]).write_text({json.dumps(json.dumps({'summaries': [ROW]}))})
''')
            binary.chmod(0o700)
            config = {"command": str(binary), "max_bullets": 7, "timeout": 5}
            self.assertEqual(json.loads(transport.call_codex_summary(config, "Summarize candidates")), [ROW])
            binary.write_text(f'#!{sys.executable}\nimport sys\nprint("Logged in using an API key")\n')
            with self.assertRaisesRegex(transport.CodexSummaryError, "ChatGPT subscription"):
                transport.call_codex_summary(config, "no request should be made")
        with self.assertRaisesRegex(transport.CodexSummaryError, "unavailable"):
            transport.call_codex_summary({"command": "/missing/qqq-codex"}, "unused")
        for payload in ({"summaries": []}, {"summaries": [ROW] * 8}, [],
                        {"summaries": [{**ROW, "priority": True}]},
                        {"summaries": [{**ROW, "event": ""}]}):
            with self.assertRaises(transport.CodexSummaryError):
                transport._validate_result(payload, 7)

    def test_failed_incomplete_or_tool_using_turn_is_rejected(self):
        transport._check_events(io.StringIO('{"type":"turn.completed"}\n'))
        transport._check_events(io.StringIO(
            '{"type":"item.completed","item":{"type":"error","message":"Exceeded skills context budget. All skill descriptions were removed"}}\n'
            '{"type":"turn.completed"}\n'))
        for events in ('', '{"type":"turn.failed"}', '{"type":"error"}',
                       '{"type":"item.completed","item":{"type":"command_execution"}}'):
            with self.assertRaises(transport.CodexSummaryError):
                transport._check_events(io.StringIO(events))

    def test_timeout_kills_group_and_redacts_cli_error(self):
        config = {"command": "codex", "max_bullets": 7, "timeout": 1}
        with patch.object(transport.shutil, "which", return_value="/bin/codex"), \
             patch.object(transport.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "Logged in using ChatGPT", "")), \
             patch.object(transport.subprocess, "Popen") as popen, \
             patch.object(transport.os, "killpg") as kill:
            process = popen.return_value
            process.pid = 12345
            process.communicate.side_effect = [subprocess.TimeoutExpired("hidden", 1), (None, None)]
            with self.assertRaisesRegex(transport.CodexSummaryError, "timed out"):
                transport.call_codex_summary(config, "data")
            kill.assert_called_once_with(12345, signal.SIGKILL)
            self.assertTrue(popen.call_args.kwargs["start_new_session"])
            process.communicate.side_effect = None
            process.returncode = 1
            with self.assertRaisesRegex(transport.CodexSummaryError, "exit 1"):
                transport.call_codex_summary(config, "data")

    def test_dispatch_caps_candidates_and_sanitizes_date(self):
        candidates = [(5, pd.Timestamp("2026-10-05T09:30:00-04:00"), {
            "headline": "Nasdaq technology shares rise", "source": "TestWire"})] * 3
        config = {"provider": "codex", "max_candidate_items": 2, "max_bullets": 7}
        with patch.object(transport, "call_codex_summary", return_value=json.dumps([ROW])) as call, \
             patch.object(news, "_call_gemini_summary") as gemini:
            rows = news.summarize_news_candidates(candidates, date(2026, 10, 5), config)
            self.assertEqual(call.call_args.args[1].count('"headline":'), 2)
            self.assertEqual(rows[0]["DateTime"], "2026-10-05T09:30:00-04:00")
            self.assertEqual(rows[0]["Kind"], "news_summary")
            gemini.assert_not_called()

    def test_pipeline_preserves_existing_and_falls_back_on_error_or_empty(self):
        day = date(2026, 10, 5)
        item = {"datetime": int(pd.Timestamp("2026-10-05T09:30:00-04:00").timestamp()),
                "headline": "Fed inflation news affects Nasdaq QQQ", "source": "TestWire", "related": "QQQ"}
        config = {"provider": "codex", "max_candidate_items": 80, "max_bullets": 7,
                  "summary_start_date": date(2026, 5, 14)}
        saved = news._sanitize_summary_rows([ROW], day, 7)
        with patch.object(news, "_load_env"), patch.dict(os.environ, {"FINNHUB_API_KEY": "test-key"}), \
             patch.object(news, "_load_request_cache", return_value={}), \
             patch.object(news, "_save_request_cache"), \
             patch.object(news, "_get_json_with_cache", return_value=[item]), \
             patch.object(news, "_financialjuice_feed_config", return_value=None), \
             patch.object(news, "_llm_summary_config", return_value=config), \
             patch.object(news, "_existing_news_summary_records_for_day") as existing, \
             patch.object(transport, "call_codex_summary") as call, redirect_stdout(io.StringIO()):
            for failure in (transport.CodexSummaryError("simulated failure"), None):
                call.side_effect = failure
                call.return_value = "[]"
                existing.return_value = saved
                frame = news.fetch_finnhub_news(str(day), str(day), llm_summary_dates={day})
                self.assertEqual(list(frame["Event"]), [ROW["event"]])
                existing.return_value = []
                frame = news.fetch_finnhub_news(str(day), str(day), llm_summary_dates={day})
                self.assertTrue(frame.iloc[0]["Event"].startswith("Related news:"))
            call.reset_mock()
            news.fetch_finnhub_news(str(day), str(day), llm_summary_dates={date(2026, 10, 4)})
            call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
