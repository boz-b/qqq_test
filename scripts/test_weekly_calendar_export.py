from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from news_feeds import load_weekly_usd_calendar


def main() -> None:
    calendar = load_weekly_usd_calendar()
    out = calendar[["DateTime", "Currency", "Impact", "Event", "Actual", "Forecast", "Previous"]].copy()
    out["DateTime"] = pd.to_datetime(out["DateTime"], utc=True).dt.strftime("%Y-%m-%d %H:%M:%S%z")
    out.to_csv("data/ff_events.csv", index=False)
    print(f"wrote {len(out)} rows to data/ff_events.csv")


if __name__ == "__main__":
    main()
