#!/usr/bin/env python3
"""Compare PostgreSQL-generated dashboard payloads with another export source."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
PUBLIC_DATA_DIR = BASE_DIR / "public" / "data"

sys.path.insert(0, str(BASE_DIR))


def _first_diff(expected: Any, actual: Any, path: str = "$") -> str | None:
    if type(expected) is not type(actual):
        return f"{path}: type {type(expected).__name__} != {type(actual).__name__}"
    if isinstance(expected, dict):
        expected_keys = set(expected)
        actual_keys = set(actual)
        if expected_keys != actual_keys:
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            return f"{path}: keys differ missing={missing} extra={extra}"
        for key in expected:
            diff = _first_diff(expected[key], actual[key], f"{path}.{key}")
            if diff:
                return diff
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path}: list length {len(expected)} != {len(actual)}"
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            diff = _first_diff(expected_item, actual_item, f"{path}[{index}]")
            if diff:
                return diff
        return None
    if expected != actual:
        return f"{path}: {expected!r} != {actual!r}"
    return None


def _load_static_dates() -> list[str]:
    dates_path = PUBLIC_DATA_DIR / "dates.json"
    return json.loads(dates_path.read_text(encoding="utf-8"))


def _load_static_payload(date_label: str) -> dict:
    path = PUBLIC_DATA_DIR / f"{date_label}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_payload(payload: dict, ignore_event_order: bool) -> dict:
    if not ignore_event_order:
        return payload
    normalized = copy.deepcopy(payload)
    normalized["ff_events"] = sorted(
        normalized.get("ff_events", []),
        key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")),
    )
    return normalized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare PostgreSQL export payloads against static JSON or the CSV dashboard source."
    )
    parser.add_argument(
        "--source",
        choices=("static", "csv"),
        default="static",
        help="Reference source to compare against. Defaults to current public/data static JSON.",
    )
    parser.add_argument(
        "--ignore-event-order",
        action="store_true",
        help="Compare daily brief rows as a set. Useful for cron when DB export preserves existing public JSON order.",
    )
    parser.add_argument(
        "--date",
        action="append",
        dest="dates",
        help="Limit comparison to one date. Can be passed multiple times.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    from postgres_export import get_available_dates, get_day_data

    if args.source == "csv":
        from dashboard import get_available_dates as get_csv_available_dates
        from dashboard import get_day_data as get_csv_day_data

        reference_dates = get_csv_available_dates()

        def load_reference_payload(date_label: str) -> dict:
            return get_csv_day_data(date_label)

    else:
        reference_dates = _load_static_dates()

        def load_reference_payload(date_label: str) -> dict:
            return _load_static_payload(date_label)

    postgres_dates = get_available_dates()
    dates_to_check = args.dates or reference_dates

    if not args.dates and reference_dates != postgres_dates:
        print("[db_export_parity] dates mismatch")
        print(f"[db_export_parity] source={args.source}")
        print(f"[db_export_parity] reference_count={len(reference_dates)} postgres_count={len(postgres_dates)}")
        print(f"[db_export_parity] missing_from_postgres={sorted(set(reference_dates) - set(postgres_dates))}")
        print(f"[db_export_parity] extra_in_postgres={sorted(set(postgres_dates) - set(reference_dates))}")
        return 1

    checked = 0
    for date_label in dates_to_check:
        if date_label not in reference_dates:
            print(f"[db_export_parity] {date_label}: missing {args.source} payload")
            return 1
        expected = _normalize_payload(load_reference_payload(date_label), args.ignore_event_order)
        actual = _normalize_payload(get_day_data(date_label), args.ignore_event_order)
        diff = _first_diff(expected, actual)
        if diff:
            print(f"[db_export_parity] {date_label}: mismatch")
            print(f"[db_export_parity] source={args.source}")
            print(f"[db_export_parity] first_diff={diff}")
            return 1
        checked += 1

    print(f"[db_export_parity] source={args.source}")
    print(f"[db_export_parity] ignore_event_order={args.ignore_event_order}")
    print(f"[db_export_parity] dates_checked={checked}")
    print("[db_export_parity] status=success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
