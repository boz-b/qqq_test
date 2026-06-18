#!/usr/bin/env python3
"""Small regression test for future-only Gemini calendar actual enrichment."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import news_feeds


def main() -> None:
    calls: list[str] = []
    backoff_path = news_feeds.CALENDAR_ACTUALS_BACKOFF_JSON
    original_backoff = backoff_path.read_text() if backoff_path.exists() else None

    def fake_call(config: dict, prompt: str) -> str:
        calls.append(prompt)
        return (
            '[{"id":1,"event":"Retail Sales m/m","actual":"0.2%",'
            '"confidence":"high","source":"Test Source","source_url":"https://example.com"}]'
        )

    original_call = news_feeds._call_gemini_calendar_actuals
    news_feeds._call_gemini_calendar_actuals = fake_call
    try:
        rows = pd.DataFrame(
            [
                {
                    "DateTime": "2099-01-02T09:30:00-05:00",
                    "Currency": "USD",
                    "Impact": "High Impact Expected",
                    "Event": "Retail Sales m/m",
                    "Actual": "",
                    "Forecast": "0.1%",
                    "Previous": "0.0%",
                    "Kind": "macro",
                    "Priority": 5,
                },
                {
                    "DateTime": "2099-01-02T11:30:00-05:00",
                    "Currency": "USD",
                    "Impact": "High Impact Expected",
                    "Event": "Industrial Production m/m",
                    "Actual": "",
                    "Forecast": "0.3%",
                    "Previous": "0.2%",
                    "Kind": "macro",
                    "Priority": 5,
                },
                {
                    "DateTime": "2099-01-01T09:30:00-05:00",
                    "Currency": "USD",
                    "Impact": "High Impact Expected",
                    "Event": "Previous Day Event",
                    "Actual": "",
                    "Forecast": "1.0%",
                    "Previous": "0.8%",
                    "Kind": "macro",
                    "Priority": 5,
                },
                {
                    "DateTime": "2099-01-02T12:00:00-05:00",
                    "Currency": "USD",
                    "Impact": "Medium Impact Expected",
                    "Event": "President Speaks",
                    "Actual": "",
                    "Forecast": "",
                    "Previous": "",
                    "Kind": "macro",
                    "Priority": 5,
                },
            ]
        )

        enriched = news_feeds.enrich_calendar_actuals_with_gemini(
            rows,
            now_et=datetime(2099, 1, 2, 10, 5, tzinfo=ZoneInfo("America/New_York")),
            config={
                "api_key": "test",
                "api_key_fingerprint": news_feeds._api_key_fingerprint("test"),
                "api_base": "https://example.com",
                "model": "models/test",
                "timeout": 5,
                "delay_minutes": 20,
                "max_events_per_day": 8,
                "max_output_tokens": 256,
                "thinking_budget": 0,
                "quota_backoff_hours": 12,
            },
        )

        backoff_path.write_text(json.dumps({
            "last_429_utc": "2099-01-02T15:00:00+00:00",
            "api_key_fingerprint": news_feeds._api_key_fingerprint("test"),
        }))
        skipped = news_feeds.enrich_calendar_actuals_with_gemini(
            rows,
            now_et=datetime(2099, 1, 2, 10, 5, tzinfo=ZoneInfo("America/New_York")),
            config={
                "api_key": "test",
                "api_key_fingerprint": news_feeds._api_key_fingerprint("test"),
                "api_base": "https://example.com",
                "model": "models/test",
                "timeout": 5,
                "delay_minutes": 20,
                "max_events_per_day": 8,
                "max_output_tokens": 256,
                "thinking_budget": 0,
                "quota_backoff_hours": 12,
            },
        )
    finally:
        news_feeds._call_gemini_calendar_actuals = original_call
        if original_backoff is None:
            backoff_path.unlink(missing_ok=True)
        else:
            backoff_path.write_text(original_backoff)

    by_event = {row["Event"]: row["Actual"] for _, row in enriched.iterrows()}
    assert by_event["Retail Sales m/m"] == "0.2%"
    assert by_event["Industrial Production m/m"] == ""
    assert by_event["Previous Day Event"] == ""
    assert by_event["President Speaks"] == ""
    assert len(calls) == 1
    skipped_by_event = {row["Event"]: row["Actual"] for _, row in skipped.iterrows()}
    assert skipped_by_event["Retail Sales m/m"] == ""
    assert len(calls) == 1
    print("calendar actual enrichment test passed")


if __name__ == "__main__":
    main()
