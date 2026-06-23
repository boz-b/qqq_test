#!/usr/bin/env python3
"""Validate committed static dashboard payloads without local runtime caches."""

from __future__ import annotations

import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
PUBLIC_DATA_DIR = BASE_DIR / "public" / "data"


def _load_json(path: Path):
    return json.loads(path.read_text())


def main() -> None:
    dates_path = PUBLIC_DATA_DIR / "dates.json"
    assert dates_path.exists(), "public/data/dates.json is missing"

    dates = _load_json(dates_path)
    assert isinstance(dates, list) and dates, "dates.json must contain at least one date"
    assert dates == sorted(dates), "dates.json must be sorted ascending"

    for date_label in dates:
        payload_path = PUBLIC_DATA_DIR / f"{date_label}.json"
        assert payload_path.exists(), f"missing static payload for {date_label}"

        payload = _load_json(payload_path)
        assert payload.get("date") == date_label, f"{payload_path} has wrong date"
        chart = payload.get("chart")
        assert isinstance(chart, dict), f"{payload_path} is missing chart"

        labels = chart.get("labels")
        assert isinstance(labels, list) and labels, f"{payload_path} has no chart labels"
        for key in ("open", "high", "low", "close", "volume"):
            values = chart.get(key)
            assert isinstance(values, list), f"{payload_path} chart.{key} is not a list"
            assert len(values) == len(labels), f"{payload_path} chart.{key} length mismatch"

        assert "prior_close" in payload, f"{payload_path} is missing prior_close"
        assert isinstance(payload.get("pm_stats"), dict), f"{payload_path} is missing pm_stats"
        assert isinstance(payload.get("ff_events"), list), f"{payload_path} is missing ff_events"

    extra_payloads = sorted(
        path.stem
        for path in PUBLIC_DATA_DIR.glob("*.json")
        if path.name != "dates.json" and path.stem not in dates
    )
    assert not extra_payloads, f"stale public/data payloads not listed in dates.json: {extra_payloads}"
    print(f"static public data test passed for {len(dates)} day payload(s)")


if __name__ == "__main__":
    main()
