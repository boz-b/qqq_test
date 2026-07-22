#!/usr/bin/env python3
"""Regression tests for Brave Search calendar actual enrichment."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

import pandas as pd
import requests

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import news_feeds


def _config(root: Path, **overrides) -> dict:
    config = {
        "provider": "brave",
        "api_key": "***",
        "api_key_fingerprint": news_feeds._api_key_fingerprint("test"),
        "api_url": "https://example.com/search",
        "allow_custom_api_url": True,
        "backoff_path": root / "backoff.json",
        "state_path": root / "state.json",
        "timeout": 5,
        "delay_minutes": 20,
        "max_events_per_day": 8,
        "max_requests_per_day": 3,
        "cache_ttl_hours": 168,
        "negative_cache_ttl_hours": 6,
        "result_count": 10,
        "country": "US",
        "search_lang": "en",
        "ui_lang": "en-US",
        "safesearch": "moderate",
        "extra_snippets": True,
        "quota_backoff_hours": 12,
    }
    config.update(overrides)
    return config


def _result(title: str, description: str, url: str, extra_snippets: list[str] | None = None) -> dict:
    return {
        "web": {
            "results": [
                {
                    "title": title,
                    "description": description,
                    "url": url,
                    "extra_snippets": extra_snippets or [],
                }
            ]
        }
    }


def _two_results(first: dict, second: dict) -> dict:
    return {"web": {"results": [first, second]}}


def _macro_row(event: str, when: str, forecast: str, previous: str) -> dict:
    return {
        "DateTime": when,
        "Currency": "USD",
        "Impact": "High Impact Expected",
        "Event": event,
        "Actual": "",
        "Forecast": forecast,
        "Previous": previous,
        "Kind": "macro",
        "Priority": 5,
    }


def _parser_cases() -> None:
    leading_candidate = {
        "event": "CB Leading Index m/m",
        "date": "2026-07-20",
        "forecast": "-0.1%",
        "previous": "0.1%",
    }
    leading_payload = _result(
        "July 20, 2026 - The Conference Board Leading Economic Index declined in June",
        "The US Leading Economic Index declined by 0.2% in June 2026 to 99.1.",
        "https://www.conference-board.org/topics/us-leading-indicators/",
    )
    assert news_feeds._parse_brave_calendar_actual(leading_payload, leading_candidate) == "-0.2%"

    claims_candidate = {
        "event": "Unemployment Claims",
        "date": "2026-07-16",
        "forecast": "216K",
        "previous": "215K",
    }
    claims_payload = _result(
        "July 16, 2026 Initial unemployment claims",
        (
            "Continuing claims fell by 16,000 to 1,805,000. "
            "The 4-week moving average was 214,250. "
            "Initial claims fell by 8,000 to 208,000 in the latest week."
        ),
        "https://www.dol.gov/ui/data.pdf",
    )
    assert news_feeds._parse_brave_calendar_actual(claims_payload, claims_candidate) == "208K"

    adp_candidate = {
        "event": "ADP Weekly Employment Change",
        "date": "2026-07-21",
        "forecast": "",
        "previous": "19.8K",
    }
    adp_payload = _result(
        "ADP weekly employment change - July 21, 2026",
        "ADP weekly employment change increased by 12,000 to 40,000.",
        "https://www.adp.com/resources/articles-and-insights.aspx",
    )
    assert news_feeds._parse_brave_calendar_actual(adp_payload, adp_candidate) == "40K"

    retail_candidate = {
        "event": "Retail Sales m/m",
        "date": "2026-07-16",
        "forecast": "0.2%",
        "previous": "0.9%",
    }
    percent_word_payload = _result(
        "Retail sales release - July 16, 2026",
        "Retail sales increased 0.6 percent in June.",
        "https://www.census.gov/retail/index.html",
    )
    assert news_feeds._parse_brave_calendar_actual(percent_word_payload, retail_candidate) == "0.6%"

    home_sales_candidate = {
        "event": "New Home Sales",
        "date": "2026-07-24",
        "forecast": "609K",
        "previous": "580K",
    }
    home_sales_payload = _result(
        "New residential sales - July 24, 2026",
        "Sales of new single-family houses in June 2026 were at a seasonally adjusted annual rate of 627,000.",
        "https://www.census.gov/construction/nrs/",
    )
    assert news_feeds._parse_brave_calendar_actual(home_sales_payload, home_sales_candidate) == "627K"

    philly_candidate = {
        "event": "Philly Fed Manufacturing Index",
        "date": "2026-07-16",
        "forecast": "12.7",
        "previous": "10.3",
    }
    philly_payload = _result(
        "Philly Fed manufacturing index - July 16, 2026",
        "The manufacturing index increased by 2.1 points to 15.2.",
        "https://www.philadelphiafed.org/surveys-and-data/regional-economic-analysis/",
    )
    assert news_feeds._parse_brave_calendar_actual(philly_payload, philly_candidate) == "15.2"

    trailing_forecast_payload = _result(
        "Retail sales release - July 16, 2026",
        "Retail sales increased 0.4% in our forecast.",
        "https://www.census.gov/retail/index.html",
    )
    assert news_feeds._parse_brave_calendar_actual(trailing_forecast_payload, retail_candidate) == ""

    stale_payload = _result(
        "Retail sales release - July 16, 2026",
        "Retail sales increased 0.4% in May. Retail sales increased 0.6% in June.",
        "https://www.census.gov/retail/index.html",
    )
    assert news_feeds._parse_brave_calendar_actual(stale_payload, retail_candidate) == "0.6%"

    stale_only_payload = _result(
        "Retail sales release - July 16, 2026",
        "Retail sales increased 0.4% in May.",
        "https://www.census.gov/retail/index.html",
    )
    assert news_feeds._parse_brave_calendar_actual(stale_only_payload, retail_candidate) == ""

    conflicting_payload = _two_results(
        {
            "title": "Retail sales - July 16, 2026",
            "description": "Retail sales increased 0.3%.",
            "url": "https://www.reuters.com/markets/us/retail-sales/",
            "extra_snippets": [],
        },
        {
            "title": "Retail sales - July 16, 2026",
            "description": "Retail sales increased 0.4%.",
            "url": "https://www.bloomberg.com/news/articles/retail-sales",
            "extra_snippets": [],
        },
    )
    assert news_feeds._parse_brave_calendar_actual(conflicting_payload, retail_candidate) == ""

    untrusted_consensus = _two_results(
        {
            "title": "Retail sales - July 16, 2026",
            "description": "Retail sales increased 0.4%.",
            "url": "https://example.com/retail-sales",
            "extra_snippets": [],
        },
        {
            "title": "Retail sales - July 16, 2026",
            "description": "Retail sales increased 0.4%.",
            "url": "https://example.net/retail-sales",
            "extra_snippets": [],
        },
    )
    assert news_feeds._parse_brave_calendar_actual(untrusted_consensus, retail_candidate) == ""


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        config = _config(root)
        calls: list[dict] = []

        def fake_call(call_config: dict, candidate: dict) -> dict:
            calls.append(candidate)
            return _result(
                "Retail sales release - January 2, 2099",
                "U.S. retail sales increased by 0.2% in December.",
                "https://www.census.gov/retail/index.html",
            )

        original_call = news_feeds._call_brave_calendar_actual
        news_feeds._call_brave_calendar_actual = fake_call
        try:
            rows = pd.DataFrame(
                [
                    _macro_row("Retail Sales m/m", "2099-01-02T09:30:00-05:00", "0.1%", "0.0%"),
                    _macro_row("Industrial Production m/m", "2099-01-02T11:30:00-05:00", "0.3%", "0.2%"),
                    _macro_row("Previous Day Event", "2099-01-01T09:30:00-05:00", "1.0%", "0.8%"),
                    {
                        **_macro_row("President Speaks", "2099-01-02T12:00:00-05:00", "", ""),
                        "Impact": "Medium Impact Expected",
                    },
                ]
            )
            now_et = datetime(2099, 1, 2, 10, 5, tzinfo=ZoneInfo("America/New_York"))
            enriched = news_feeds.enrich_calendar_actuals_with_brave(rows, now_et=now_et, config=config)
            cached = news_feeds.enrich_calendar_actuals_with_brave(rows, now_et=now_et, config=config)
        finally:
            news_feeds._call_brave_calendar_actual = original_call

        by_event = {row["Event"]: row["Actual"] for _, row in enriched.iterrows()}
        assert by_event["Retail Sales m/m"] == "0.2%"
        assert by_event["Industrial Production m/m"] == ""
        assert by_event["Previous Day Event"] == ""
        assert by_event["President Speaks"] == ""
        assert len(calls) == 1
        assert {row["Event"]: row["Actual"] for _, row in cached.iterrows()}["Retail Sales m/m"] == "0.2%"

        query = news_feeds._build_brave_calendar_actual_query(calls[0]).lower()
        assert "forecast" not in query
        assert "0.1%" not in query
        assert "0.0%" not in query

        backoff_path = Path(config["backoff_path"])
        backoff_path.write_text(
            json.dumps(
                {
                    "last_429_utc": "2099-01-02T15:00:00+00:00",
                    "provider": "brave",
                    "api_key_fingerprint": news_feeds._api_key_fingerprint("test"),
                }
            )
        )
        skipped = news_feeds.enrich_calendar_actuals_with_brave(rows, now_et=now_et, config=config)
        assert {row["Event"]: row["Actual"] for _, row in skipped.iterrows()}["Retail Sales m/m"] == ""
        backoff_path.unlink()

        _parser_cases()

        first_process_config = _config(root / "persistent", max_requests_per_day=1)
        second_process_config = _config(root / "persistent", max_requests_per_day=1)
        quota_now = datetime(2099, 1, 2, tzinfo=ZoneInfo("UTC"))
        assert news_feeds._calendar_actuals_reserve_request(first_process_config, now_utc=quota_now)
        assert not news_feeds._calendar_actuals_reserve_request(second_process_config, now_utc=quota_now)

        class QuotaResponse:
            status_code = 429
            text = '{"error":"quota"}'
            headers = {"Retry-After": "120"}

        quota_config = _config(root / "quota")
        original_get = news_feeds.requests.get
        news_feeds.requests.get = lambda *args, **kwargs: QuotaResponse()
        try:
            try:
                news_feeds._call_brave_calendar_actual(
                    quota_config,
                    {"event": "Retail Sales m/m", "date": "2099-01-02"},
                )
            except news_feeds.BraveSearchQuotaError as exc:
                assert "429" in str(exc)
            else:
                raise AssertionError("Expected Brave quota error")
        finally:
            news_feeds.requests.get = original_get
        marker = json.loads(Path(quota_config["backoff_path"]).read_text())
        assert marker["provider"] == "brave"
        assert marker["retry_after_utc"]

        guarded_config = _config(root / "guard", allow_custom_api_url=False)
        try:
            news_feeds._call_brave_calendar_actual(
                guarded_config,
                {"event": "Retail Sales m/m", "date": "2099-01-02"},
            )
        except news_feeds.BraveSearchAuthError:
            pass
        else:
            raise AssertionError("Expected custom URL guard to reject the token destination")

        insecure_config = _config(
            root / "insecure",
            api_url="http://example.com/search",
            allow_custom_api_url=True,
        )
        try:
            news_feeds._call_brave_calendar_actual(
                insecure_config,
                {"event": "Retail Sales m/m", "date": "2099-01-02"},
            )
        except news_feeds.BraveSearchAuthError:
            pass
        else:
            raise AssertionError("Expected HTTP custom URL to be rejected even with custom URLs enabled")

        class RejectedResponse:
            status_code = 400
            text = '{"error":"invalid parameter"}'
            headers = {}

        rejected_config = _config(root / "rejected")
        news_feeds.requests.get = lambda *args, **kwargs: RejectedResponse()
        try:
            try:
                news_feeds._call_brave_calendar_actual(
                    rejected_config,
                    {"event": "Retail Sales m/m", "date": "2099-01-02"},
                )
            except news_feeds.BraveSearchFatalError as exc:
                assert "400" in str(exc)
            else:
                raise AssertionError("Expected non-retryable Brave 4xx to be fatal")
        finally:
            news_feeds.requests.get = original_get

        transient_config = _config(root / "transient", max_requests_per_day=3)
        transient_calls: list[str] = []

        def transient_call(call_config: dict, candidate: dict) -> dict:
            transient_calls.append(candidate["event"])
            if candidate["event"] == "Retail Sales m/m":
                raise requests.Timeout("simulated timeout")
            return _result(
                "Industrial production release - January 2, 2099",
                "Industrial production increased 0.3 percent.",
                "https://www.federalreserve.gov/releases/g17/current/",
            )

        news_feeds._call_brave_calendar_actual = transient_call
        try:
            transient_rows = pd.DataFrame(
                [
                    _macro_row("Retail Sales m/m", "2099-01-02T09:30:00-05:00", "0.1%", "0.0%"),
                    _macro_row("Industrial Production m/m", "2099-01-02T09:31:00-05:00", "0.2%", "0.1%"),
                ]
            )
            transient_result = news_feeds.enrich_calendar_actuals_with_brave(
                transient_rows,
                now_et=datetime(2099, 1, 2, 10, 5, tzinfo=ZoneInfo("America/New_York")),
                config=transient_config,
            )
        finally:
            news_feeds._call_brave_calendar_actual = original_call
        transient_by_event = {row["Event"]: row["Actual"] for _, row in transient_result.iterrows()}
        assert transient_by_event["Retail Sales m/m"] == ""
        assert transient_by_event["Industrial Production m/m"] == "0.3%"
        assert transient_calls == ["Retail Sales m/m", "Industrial Production m/m"]

        fatal_config = _config(root / "fatal", max_requests_per_day=3)
        fatal_calls: list[str] = []

        def fatal_call(call_config: dict, candidate: dict) -> dict:
            fatal_calls.append(candidate["event"])
            raise news_feeds.BraveSearchFatalError("simulated rejected request")

        news_feeds._call_brave_calendar_actual = fatal_call
        try:
            fatal_rows = pd.DataFrame(
                [
                    _macro_row("Retail Sales m/m", "2099-01-02T09:30:00-05:00", "0.1%", "0.0%"),
                    _macro_row("Industrial Production m/m", "2099-01-02T09:31:00-05:00", "0.2%", "0.1%"),
                ]
            )
            fatal_result = news_feeds.enrich_calendar_actuals_with_brave(
                fatal_rows,
                now_et=datetime(2099, 1, 2, 10, 5, tzinfo=ZoneInfo("America/New_York")),
                config=fatal_config,
            )
        finally:
            news_feeds._call_brave_calendar_actual = original_call
        assert fatal_calls == ["Retail Sales m/m"]
        assert all(not value for value in fatal_result["Actual"].tolist())

    print("Brave calendar actual enrichment test passed")


if __name__ == "__main__":
    main()
