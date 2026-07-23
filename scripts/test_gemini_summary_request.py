#!/usr/bin/env python3
"""Regression tests for model-aware Gemini summary request bodies."""

from __future__ import annotations

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import news_feeds


def _config(model: str) -> dict:
    return {
        "api_key": "test-key",
        "api_base": "https://generativelanguage.googleapis.com/v1beta",
        "model": model,
        "timeout": 5,
        "temperature": 0.2,
        "max_output_tokens": 2048,
        "thinking_budget": 0,
    }


def main() -> None:
    captured: list[dict] = []
    original_post = news_feeds.requests.post

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "[]"}]}}
                ]
            }

    def fake_post(url: str, headers: dict, json: dict, timeout: int) -> Response:
        captured.append({
            "url": url,
            "headers": headers,
            "json": json,
            "timeout": timeout,
        })
        return Response()

    news_feeds.requests.post = fake_post
    try:
        for model in (
            "gemini-2.5-flash",
            "models/gemini-flash-latest",
            "gemini-2.5-pro",
            "gemini-unknown-model",
        ):
            assert news_feeds._call_gemini_summary(_config(model), "Summarize safely") == "[]"
    finally:
        news_feeds.requests.post = original_post

    assert news_feeds.GEMINI_MODEL_DEFAULT == "gemini-2.5-flash"
    assert len(captured) == 4

    pinned_generation = captured[0]["json"]["generationConfig"]
    assert pinned_generation["thinkingConfig"] == {"thinkingBudget": 0}
    assert captured[0]["url"].endswith("/models/gemini-2.5-flash:generateContent")

    for request in captured[1:]:
        assert "thinkingConfig" not in request["json"]["generationConfig"]

    for request in captured:
        body = request["json"]
        generation = body["generationConfig"]
        assert body["contents"] == [{"parts": [{"text": "Summarize safely"}]}]
        assert generation["temperature"] == 0.2
        assert generation["maxOutputTokens"] == 2048
        assert generation["responseMimeType"] == "application/json"
        schema = generation["responseSchema"]
        assert schema["type"] == "ARRAY"
        item = schema["items"]
        assert item["type"] == "OBJECT"
        assert item["required"] == ["time", "event", "impact", "priority"]
        assert item["properties"] == {
            "time": {"type": "STRING"},
            "event": {"type": "STRING"},
            "impact": {"type": "STRING"},
            "priority": {"type": "INTEGER"},
        }

    print("Gemini summary request test passed")


if __name__ == "__main__":
    main()
