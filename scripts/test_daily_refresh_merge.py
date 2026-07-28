#!/usr/bin/env python3
"""Regression test for preserving a recent daily bar omitted by Yahoo."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import pandas as pd

import data_loader


def _daily_frame(rows: dict[str, tuple[float, float, float, float, int]]) -> pd.DataFrame:
    return pd.DataFrame.from_dict(
        rows,
        orient="index",
        columns=["Open", "High", "Low", "Close", "Volume"],
    ).set_axis(pd.to_datetime(list(rows)), axis="index")


def main() -> None:
    cached = _daily_frame(
        {
            "2026-07-23": (694.0, 699.0, 688.0, 690.0, 40_000_000),
            "2026-07-24": (690.25, 692.63, 682.48, 684.23, 42_000_000),
        }
    )
    incomplete = _daily_frame(
        {
            "2026-07-23": (694.67, 698.66, 687.79, 691.96, 44_028_600),
            "2026-07-27": (691.72, 692.28, 675.95, 682.12, 42_144_580),
        }
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        cache_path = Path(temp_dir) / "qqq_daily.csv"
        cached.index.name = "date"
        cached.to_csv(cache_path)

        with (
            patch.object(data_loader, "DAILY_CSV", cache_path),
            patch.object(data_loader.yf, "download", side_effect=[incomplete, incomplete]) as download,
        ):
            result = data_loader.fetch_daily()

        assert download.call_count == 2, "an incomplete recent response must be retried once"
        assert result.loc[pd.Timestamp("2026-07-24"), "close"] == 684.23
        assert result.loc[pd.Timestamp("2026-07-23"), "close"] == 691.96
        assert result.loc[pd.Timestamp("2026-07-27"), "close"] == 682.12

        saved = pd.read_csv(cache_path)
        assert "2026-07-24" in set(saved["date"]), "cached missing day must remain saved"

    print("daily refresh merge regression: OK")


if __name__ == "__main__":
    main()
