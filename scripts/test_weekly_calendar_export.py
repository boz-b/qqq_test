from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from news_feeds import save_calendar_only_events


def main() -> None:
    df = save_calendar_only_events("2026-03-02", "2026-04-20")
    print(f"saved {len(df)} calendar rows")


if __name__ == "__main__":
    main()
