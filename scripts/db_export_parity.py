#!/usr/bin/env python3
"""Compare PostgreSQL-generated dashboard payloads with current static JSON."""

from __future__ import annotations

import argparse
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare PostgreSQL export payloads against public/data static JSON."
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

    static_dates = _load_static_dates()
    postgres_dates = get_available_dates()
    dates_to_check = args.dates or static_dates

    if not args.dates and static_dates != postgres_dates:
        print("[db_export_parity] dates mismatch")
        print(f"[db_export_parity] static_count={len(static_dates)} postgres_count={len(postgres_dates)}")
        print(f"[db_export_parity] missing_from_postgres={sorted(set(static_dates) - set(postgres_dates))}")
        print(f"[db_export_parity] extra_in_postgres={sorted(set(postgres_dates) - set(static_dates))}")
        return 1

    checked = 0
    for date_label in dates_to_check:
        if date_label not in static_dates:
            print(f"[db_export_parity] {date_label}: missing static payload")
            return 1
        expected = _load_static_payload(date_label)
        actual = get_day_data(date_label)
        diff = _first_diff(expected, actual)
        if diff:
            print(f"[db_export_parity] {date_label}: mismatch")
            print(f"[db_export_parity] first_diff={diff}")
            return 1
        checked += 1

    print(f"[db_export_parity] dates_checked={checked}")
    print("[db_export_parity] status=success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
