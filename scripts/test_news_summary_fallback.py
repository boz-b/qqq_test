#!/usr/bin/env python3
"""Regression test for related-news fallback when Gemini summaries fail."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import pandas as pd

import news_feeds


def _epoch(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp())


def main() -> None:
    os.environ["FINNHUB_API_KEY"] = "test-key"

    original_load_cache = news_feeds._load_request_cache
    original_save_cache = news_feeds._save_request_cache
    original_get_json = news_feeds._get_json_with_cache
    original_llm_config = news_feeds._llm_summary_config
    original_summarize = news_feeds.summarize_news_candidates_with_gemini
    original_financialjuice_config = news_feeds._financialjuice_feed_config
    original_existing = news_feeds._existing_news_summary_records_for_day

    def fake_get_json(url: str, headers: dict, cache: dict) -> list[dict]:
        if "company-news?symbol=QQQ" not in url:
            return []
        return [
            {
                "datetime": _epoch("2026-08-03T23:55:00-04:00"),
                "headline": "Fed inflation data drives QQQ yields lower",
                "summary": "Macro-sensitive Nasdaq story",
                "source": "Reuters",
                "related": "QQQ",
            },
            {
                "datetime": _epoch("2026-08-05T00:05:00-04:00"),
                "headline": "Apple and Nvidia lead Nasdaq megacaps",
                "summary": "Large technology stocks moved intraday",
                "source": "TestWire",
                "related": "AAPL,NVDA,QQQ",
            },
            {
                "datetime": _epoch("2026-08-05T00:10:00-04:00"),
                "headline": "Low relevance local headline",
                "summary": "No market terms",
                "source": "TestWire",
                "related": "",
            },
        ]

    def fake_llm_config() -> dict:
        return {
            "api_key": "test",
            "api_base": "https://example.com",
            "model": "models/test",
            "timeout": 5,
            "max_candidate_items": 80,
            "max_bullets": 7,
            "temperature": 0.2,
            "max_output_tokens": 256,
            "thinking_budget": 0,
            "summary_start_date": pd.Timestamp("2026-08-01").date(),
        }

    def fail_summary(scored_items: list, trade_date, config: dict) -> list[dict]:
        raise RuntimeError("simulated Gemini outage")

    news_feeds._load_request_cache = lambda: {}
    news_feeds._save_request_cache = lambda cache: None
    news_feeds._get_json_with_cache = fake_get_json
    news_feeds._llm_summary_config = fake_llm_config
    news_feeds.summarize_news_candidates_with_gemini = fail_summary
    news_feeds._financialjuice_feed_config = lambda: None
    news_feeds._existing_news_summary_records_for_day = lambda trade_date: []
    try:
        frame = news_feeds.fetch_finnhub_news(
            "2026-08-04",
            "2026-08-04",
            max_items_per_day=2,
            llm_summary_dates={pd.Timestamp("2026-08-04").date()},
        )
    finally:
        news_feeds._load_request_cache = original_load_cache
        news_feeds._save_request_cache = original_save_cache
        news_feeds._get_json_with_cache = original_get_json
        news_feeds._llm_summary_config = original_llm_config
        news_feeds.summarize_news_candidates_with_gemini = original_summarize
        news_feeds._financialjuice_feed_config = original_financialjuice_config
        news_feeds._existing_news_summary_records_for_day = original_existing

    assert len(frame) == 2
    assert set(frame["Impact"]) == {"News Summary"}
    assert set(frame["Kind"]) == {"news_summary"}
    assert all(str(event).startswith("Related news:") for event in frame["Event"])
    fallback_events = " ".join(frame["Event"].astype(str))
    assert "Fed inflation data" in fallback_events
    assert "Apple and Nvidia" in fallback_events
    assert "Low relevance local headline" not in fallback_events
    fallback_dates = frame["DateTime"].dt.tz_convert(ZoneInfo("America/New_York")).dt.date
    assert set(fallback_dates) == {pd.Timestamp("2026-08-04").date()}

    archive_columns = ["DateTime", "Currency", "Impact", "Event", "Actual", "Forecast", "Previous"]
    archive = pd.DataFrame(
        [
            ["2026-08-03T09:30:00-04:00", "USD", "News Summary", "Keep Aug 3", "", "", ""],
            ["2026-08-04T09:30:00-04:00", "USD", "News Summary", "Replace Aug 4", "", "", ""],
        ],
        columns=archive_columns,
    )
    cross_date_output = pd.DataFrame(
        [["2026-08-03T23:55:00-04:00", "USD", "News Summary", "Cross-date fallback", "", "", ""]],
        columns=archive_columns,
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        output_csv = Path(temp_dir) / "ff_events.csv"
        news_csv = Path(temp_dir) / "news.csv"
        archive.to_csv(output_csv, index=False)
        with (
            patch.object(news_feeds, "NEWS_CSV", news_csv),
            patch.object(news_feeds, "build_combined_events", return_value=cross_date_output),
        ):
            merged = news_feeds.save_combined_events("2026-08-04", "2026-08-04", output_csv=output_csv)

    assert "Keep Aug 3" in set(merged["Event"]), "an Aug 4 refresh must not replace Aug 3"
    assert "Replace Aug 4" not in set(merged["Event"]), "the explicitly requested date must be replaced"
    print("news summary fallback test passed")


if __name__ == "__main__":
    main()
