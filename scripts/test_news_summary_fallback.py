#!/usr/bin/env python3
"""Regression test for related-news fallback when Gemini summaries fail."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
import sys
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
                "datetime": _epoch("2099-01-02T10:00:00-05:00"),
                "headline": "Fed inflation data drives QQQ yields lower",
                "summary": "Macro-sensitive Nasdaq story",
                "source": "Reuters",
                "related": "QQQ",
            },
            {
                "datetime": _epoch("2099-01-02T10:05:00-05:00"),
                "headline": "Apple and Nvidia lead Nasdaq megacaps",
                "summary": "Large technology stocks moved intraday",
                "source": "TestWire",
                "related": "AAPL,NVDA,QQQ",
            },
            {
                "datetime": _epoch("2099-01-02T10:10:00-05:00"),
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
            "summary_start_date": pd.Timestamp("2099-01-01").date(),
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
            "2099-01-02",
            "2099-01-02",
            max_items_per_day=2,
            llm_summary_dates={pd.Timestamp("2099-01-02").date()},
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
    assert "Fed inflation data" in frame.iloc[0]["Event"]
    assert "Apple and Nvidia" in frame.iloc[1]["Event"]
    assert frame["DateTime"].dt.tz_convert(ZoneInfo("America/New_York")).dt.date.iloc[0].isoformat() == "2099-01-02"
    print("news summary fallback test passed")


if __name__ == "__main__":
    main()
