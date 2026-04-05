from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

COMBINED_EVENTS_CSV = DATA_DIR / "ff_events.csv"
NEWS_CSV = DATA_DIR / "news_events.csv"
FINNHUB_ENV_FILES = [BASE_DIR / ".env", BASE_DIR / ".env.finnhub"]


def _load_env() -> None:
    for env_path in FINNHUB_ENV_FILES:
        if env_path.exists():
            load_dotenv(env_path, override=False)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\xa0", " ").strip()


def _iso_to_eastern_date(dt: pd.Timestamp) -> datetime.date:
    return dt.tz_convert("America/New_York").date()


def fetch_finnhub_news(start_date: str, end_date: str, max_items_per_day: int = 5) -> pd.DataFrame:
    """Fetch top Finnhub news and normalize to event-like rows."""
    _load_env()
    api_key = os.getenv("FINNHUB_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY is missing. Put it in .env or .env.finnhub")

    start = pd.Timestamp(start_date).date()
    end = pd.Timestamp(end_date).date()

    records: list[dict[str, Any]] = []
    day = start
    while day <= end:
        url = f"https://finnhub.io/api/v1/news?category=general&minId=0"
        resp = requests.get(url, headers={"X-Finnhub-Token": api_key}, timeout=30)
        resp.raise_for_status()
        payload = resp.json()

        scored = []
        for item in payload:
            ts = item.get("datetime")
            if not ts:
                continue
            dt = pd.to_datetime(int(ts), unit="s", utc=True)
            if _iso_to_eastern_date(dt) != day:
                continue

            headline = _clean_text(item.get("headline"))
            summary = _clean_text(item.get("summary"))
            source = _clean_text(item.get("source"))
            score = 0
            text = f"{headline} {summary}".lower()
            keywords = {
                "fed": 4,
                "fomc": 4,
                "treasury": 3,
                "yield": 3,
                "inflation": 4,
                "cpi": 4,
                "ppi": 3,
                "jobs": 3,
                "payroll": 4,
                "tariff": 3,
                "trump": 2,
                "white house": 2,
                "iran": 2,
                "china": 2,
                "apple": 2,
                "microsoft": 2,
                "nvidia": 2,
                "amazon": 2,
                "alphabet": 2,
                "tesla": 2,
                "nasdaq": 2,
                "qqq": 3,
            }
            for kw, weight in keywords.items():
                if kw in text:
                    score += weight
            if source.lower() in {"reuters", "associated press", "ap news"}:
                score += 2

            scored.append((score, dt, item))

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        top = scored[:max_items_per_day]

        for score, dt, item in top:
            headline = _clean_text(item.get("headline"))
            source = _clean_text(item.get("source"))
            records.append({
                "DateTime": dt.tz_convert("America/New_York").isoformat(),
                "Currency": "USD",
                "Impact": "News",
                "Event": f"{headline} [{source}]" if source else headline,
                "Actual": "",
                "Forecast": "",
                "Previous": "",
                "Kind": "news",
                "Priority": score,
            })

        day += timedelta(days=1)

    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=["DateTime", "Currency", "Impact", "Event", "Actual", "Forecast", "Previous", "Kind", "Priority"])

    df["DateTime"] = pd.to_datetime(df["DateTime"], utc=True)
    df = df.sort_values(["DateTime", "Priority"], ascending=[True, False]).reset_index(drop=True)
    return df


def fetch_official_macro(start_date: str, end_date: str, max_items_per_day: int = 2) -> pd.DataFrame:
    """Aggregate reachable official US macro schedules from BEA and Federal Reserve."""
    start = pd.Timestamp(start_date).date()
    end = pd.Timestamp(end_date).date()
    records: list[dict[str, Any]] = []

    # BEA schedule
    bea = requests.get("https://www.bea.gov/news/schedule", timeout=30)
    bea.raise_for_status()
    soup = BeautifulSoup(bea.text, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    months = {m: i for i, m in enumerate([
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ], start=1)}
    i = 0
    while i < len(lines) - 3:
        month_day = lines[i]
        time_str = lines[i + 1]
        kind = lines[i + 2]
        event = lines[i + 3]
        parts = month_day.split()
        if len(parts) == 2 and parts[0] in months and parts[1].isdigit() and ":" in time_str:
            event_date = pd.Timestamp(year=end.year, month=months[parts[0]], day=int(parts[1]), tz="America/New_York").date()
            if start <= event_date <= end:
                importance = 3 if any(x in event.lower() for x in ["gdp", "personal income", "outlays", "trade"]) else 2
                dt = pd.Timestamp(f"{event_date} {time_str}", tz="America/New_York")
                records.append({
                    "DateTime": dt.isoformat(),
                    "Currency": "USD",
                    "Impact": "High Impact Expected" if importance >= 3 else "Medium Impact Expected",
                    "Event": f"{event} [BEA]",
                    "Actual": "",
                    "Forecast": "",
                    "Previous": "",
                    "Kind": "macro",
                    "Priority": importance,
                })
            i += 4
        else:
            i += 1

    # Federal Reserve press releases feed as macro/policy markers
    try:
        fed = requests.get("https://www.federalreserve.gov/feeds/press_all.xml", timeout=30)
        fed.raise_for_status()
        feed = BeautifulSoup(fed.text, "html.parser")
        for item in feed.find_all("item"):
            pub = item.find("pubdate") or item.find("pubDate")
            title = item.find("title")
            if not pub or not title:
                continue
            dt = pd.to_datetime(pub.text, utc=True).tz_convert("America/New_York")
            event_date = dt.date()
            if not (start <= event_date <= end):
                continue
            headline = _clean_text(title.text)
            low = headline.lower()
            if not any(k in low for k in ["fomc", "statement", "minutes", "monetary", "interest rate", "federal reserve"]):
                continue
            priority = 3 if any(k in low for k in ["fomc", "statement", "minutes", "interest rate"]) else 2
            records.append({
                "DateTime": dt.isoformat(),
                "Currency": "USD",
                "Impact": "High Impact Expected" if priority >= 3 else "Medium Impact Expected",
                "Event": f"{headline} [Fed]",
                "Actual": "",
                "Forecast": "",
                "Previous": "",
                "Kind": "macro",
                "Priority": priority,
            })
    except Exception:
        pass

    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=["DateTime", "Currency", "Impact", "Event", "Actual", "Forecast", "Previous", "Kind", "Priority"])

    df["DateTime"] = pd.to_datetime(df["DateTime"], utc=True)
    df["date"] = df["DateTime"].dt.tz_convert("America/New_York").dt.date
    df = (df.sort_values(["date", "Priority", "DateTime"], ascending=[True, False, True])
            .groupby("date", group_keys=False)
            .head(max_items_per_day)
            .drop(columns=["date"]))
    return df.reset_index(drop=True)


def build_combined_events(start_date: str, end_date: str) -> pd.DataFrame:
    news_df = fetch_finnhub_news(start_date, end_date, max_items_per_day=5)
    macro_df = fetch_official_macro(start_date, end_date, max_items_per_day=2)
    combined = pd.concat([news_df, macro_df], ignore_index=True)
    if combined.empty:
        return combined

    combined["DateTime"] = pd.to_datetime(combined["DateTime"], utc=True)
    combined["date"] = combined["DateTime"].dt.tz_convert("America/New_York").dt.date
    combined = (combined.sort_values(["date", "Kind", "Priority", "DateTime"], ascending=[True, True, False, True])
                        .groupby("date", group_keys=False)
                        .head(7)
                        .drop(columns=["date"]))
    return combined.reset_index(drop=True)


def save_combined_events(start_date: str, end_date: str, output_csv: Path | str = COMBINED_EVENTS_CSV) -> pd.DataFrame:
    df = build_combined_events(start_date, end_date)
    output_csv = Path(output_csv)
    if df.empty:
        raise RuntimeError("Combined news/macro feed is empty")
    out = df[["DateTime", "Currency", "Impact", "Event", "Actual", "Forecast", "Previous"]].copy()
    out.to_csv(output_csv, index=False)
    return out


if __name__ == "__main__":
    end = pd.Timestamp.now(tz="America/New_York").date()
    start = end - timedelta(days=14)
    df = save_combined_events(start.isoformat(), end.isoformat())
    print(f"saved {len(df)} rows -> {COMBINED_EVENTS_CSV}")
