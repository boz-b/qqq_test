from __future__ import annotations

import os
from datetime import datetime, time, timedelta
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
REQUEST_CACHE_CSV = DATA_DIR / "news_request_cache.csv"
WEEKLY_CALENDAR_CSV = DATA_DIR / "ff_calendar_thisweek.csv"
FINNHUB_ENV_FILES = [BASE_DIR / ".env", BASE_DIR / ".env.finnhub"]
FINNHUB_WEEKLY_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.csv"
NEWS_SYMBOLS = ["QQQ", "SPY", "NVDA", "GOOGL", "META"]
MAX_MACRO_PER_DAY = 5
MAX_NEWS_PER_DAY = 2


def _load_env() -> None:
    for env_path in FINNHUB_ENV_FILES:
        if env_path.exists():
            load_dotenv(env_path, override=False)


def _load_request_cache() -> dict[str, list[dict[str, Any]]]:
    if not REQUEST_CACHE_CSV.exists():
        return {}
    try:
        df = pd.read_csv(REQUEST_CACHE_CSV)
    except Exception:
        return {}
    cache: dict[str, list[dict[str, Any]]] = {}
    for _, row in df.iterrows():
        cache[str(row["key"])] = eval(row["payload"]) if isinstance(row["payload"], str) else []
    return cache


def _save_request_cache(cache: dict[str, list[dict[str, Any]]]) -> None:
    rows = [{"key": k, "payload": repr(v)} for k, v in cache.items()]
    pd.DataFrame(rows).to_csv(REQUEST_CACHE_CSV, index=False)


def _get_json_with_cache(url: str, headers: dict[str, str], cache: dict[str, list[dict[str, Any]]], retries: int = 3) -> list[dict[str, Any]]:
    if url in cache:
        return cache[url]
    for _ in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            cache[url] = payload
            return payload
        except Exception:
            continue
    if url in cache:
        return cache[url]
    return []


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\xa0", " ").strip()


def _iso_to_eastern_date(dt: pd.Timestamp) -> datetime.date:
    return dt.tz_convert("America/New_York").date()


def _score_news_item(item: dict[str, Any]) -> tuple[int, pd.Timestamp]:
    ts = item.get("datetime")
    dt = pd.to_datetime(int(ts), unit="s", utc=True)
    headline = _clean_text(item.get("headline"))
    summary = _clean_text(item.get("summary"))
    source = _clean_text(item.get("source"))
    related = _clean_text(item.get("related"))
    score = 0
    text = f"{headline} {summary} {related}".lower()
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
        "meta": 2,
        "tesla": 2,
        "nasdaq": 2,
        "qqq": 3,
    }
    for kw, weight in keywords.items():
        if kw in text:
            score += weight
    if source.lower() in {"reuters", "associated press", "ap news"}:
        score += 2
    return score, dt


def fetch_finnhub_news(start_date: str, end_date: str, max_items_per_day: int = MAX_NEWS_PER_DAY) -> pd.DataFrame:
    """Fetch top Finnhub historical news and normalize to event-like rows."""
    _load_env()
    api_key = os.getenv("FINNHUB_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY is missing. Put it in .env or .env.finnhub")

    start = pd.Timestamp(start_date).date()
    end = pd.Timestamp(end_date).date()

    cache = _load_request_cache()
    records: list[dict[str, Any]] = []
    seen = set()
    day = start
    headers = {"X-Finnhub-Token": api_key}
    while day <= end:
        scored = []
        for symbol in NEWS_SYMBOLS:
            url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={day.isoformat()}&to={day.isoformat()}"
            payload = _get_json_with_cache(url, headers, cache)
            for item in payload:
                headline = _clean_text(item.get("headline"))
                if not headline:
                    continue
                unique_key = (day.isoformat(), headline)
                if unique_key in seen:
                    continue
                seen.add(unique_key)
                score, dt = _score_news_item(item)
                scored.append((score, dt, item))

        general_payload = _get_json_with_cache("https://finnhub.io/api/v1/news?category=general&minId=0", headers, cache)
        for item in general_payload:
            ts = item.get("datetime")
            if not ts:
                continue
            dt = pd.to_datetime(int(ts), unit="s", utc=True)
            if _iso_to_eastern_date(dt) != day:
                continue
            headline = _clean_text(item.get("headline"))
            if not headline:
                continue
            unique_key = (day.isoformat(), headline)
            if unique_key in seen:
                continue
            seen.add(unique_key)
            score, dt = _score_news_item(item)
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

    _save_request_cache(cache)
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=["DateTime", "Currency", "Impact", "Event", "Actual", "Forecast", "Previous", "Kind", "Priority"])

    df["DateTime"] = pd.to_datetime(df["DateTime"], utc=True)
    df = df.sort_values(["DateTime", "Priority"], ascending=[True, False]).reset_index(drop=True)
    return df


def _normalize_impact(raw: Any) -> str:
    impact = _clean_text(raw).lower()
    if "holiday" in impact:
        return "Holiday"
    if "high" in impact:
        return "High Impact Expected"
    if "medium" in impact:
        return "Medium Impact Expected"
    if "low" in impact:
        return "Low Impact Expected"
    return _clean_text(raw) or "Event"


def _parse_calendar_time(raw: Any) -> time:
    text = _clean_text(raw).lower()
    if not text:
        return time(0, 0)
    try:
        return datetime.strptime(text, "%I:%M%p").time()
    except ValueError:
        pass
    for fmt in ("%H:%M", "%I%p", "%I:%M %p"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return time(0, 0)


def download_weekly_calendar(output_csv: Path | str = WEEKLY_CALENDAR_CSV) -> Path:
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(FINNHUB_WEEKLY_CALENDAR_URL, timeout=30)
    resp.raise_for_status()
    output_path.write_bytes(resp.content)
    return output_path


def load_weekly_usd_calendar(calendar_csv: Path | str = WEEKLY_CALENDAR_CSV, auto_download: bool = False) -> pd.DataFrame:
    calendar_path = Path(calendar_csv)
    if auto_download or not calendar_path.exists():
        download_weekly_calendar(calendar_path)

    df = pd.read_csv(calendar_path)
    if df.empty:
        return pd.DataFrame(columns=["DateTime", "Currency", "Impact", "Event", "Actual", "Forecast", "Previous", "Kind", "Priority"])

    df.columns = [str(c).strip() for c in df.columns]
    country_col = "Country" if "Country" in df.columns else "country"
    df = df[df[country_col].astype(str).str.upper().eq("USD")].copy()
    if df.empty:
        return pd.DataFrame(columns=["DateTime", "Currency", "Impact", "Event", "Actual", "Forecast", "Previous", "Kind", "Priority"])

    df["Date"] = pd.to_datetime(df["Date"], format="%m-%d-%Y", errors="coerce")
    df["parsed_time"] = df["Time"].apply(_parse_calendar_time)
    df = df.dropna(subset=["Date"])

    dt_series = [
        pd.Timestamp(datetime.combine(d.date(), t), tz="America/New_York")
        for d, t in zip(df["Date"], df["parsed_time"])
    ]

    result = pd.DataFrame({
        "DateTime": [dt.isoformat() for dt in dt_series],
        "Currency": "USD",
        "Impact": df["Impact"].apply(_normalize_impact),
        "Event": df["Title"].apply(_clean_text),
        "Actual": "",
        "Forecast": df.get("Forecast", pd.Series([""] * len(df))).fillna("").astype(str),
        "Previous": df.get("Previous", pd.Series([""] * len(df))).fillna("").astype(str),
        "Kind": "macro",
        "Priority": 5,
    })
    result["DateTime"] = pd.to_datetime(result["DateTime"], utc=True)
    result = result.sort_values("DateTime").reset_index(drop=True)
    return result


def fetch_official_macro(start_date: str, end_date: str, max_items_per_day: int = MAX_MACRO_PER_DAY) -> pd.DataFrame:
    """Aggregate reachable official US macro schedules from BEA and Federal Reserve."""
    start = pd.Timestamp(start_date).date()
    end = pd.Timestamp(end_date).date()
    records: list[dict[str, Any]] = []

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
    df = (
        df.sort_values(["date", "Priority", "DateTime"], ascending=[True, False, True])
        .groupby("date", group_keys=False)
        .head(max_items_per_day)
        .drop(columns=["date"])
    )
    return df.reset_index(drop=True)


def _filter_date_range(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    if df.empty:
        return df
    start = pd.Timestamp(start_date).date()
    end = pd.Timestamp(end_date).date()
    out = df.copy()
    out["DateTime"] = pd.to_datetime(out["DateTime"], utc=True)
    mask = out["DateTime"].dt.tz_convert("America/New_York").dt.date.between(start, end)
    return out.loc[mask].sort_values("DateTime").reset_index(drop=True)


def build_calendar_only_events(start_date: str, end_date: str, auto_download: bool = False) -> pd.DataFrame:
    weekly_calendar_df = load_weekly_usd_calendar(auto_download=auto_download)
    if weekly_calendar_df.empty:
        macro_df = fetch_official_macro(start_date, end_date, max_items_per_day=MAX_MACRO_PER_DAY)
        return _filter_date_range(macro_df, start_date, end_date)
    return _filter_date_range(weekly_calendar_df, start_date, end_date)


def build_combined_events(start_date: str, end_date: str) -> pd.DataFrame:
    news_df = fetch_finnhub_news(start_date, end_date, max_items_per_day=MAX_NEWS_PER_DAY)
    macro_df = build_calendar_only_events(start_date, end_date, auto_download=False)

    combined = pd.concat([news_df, macro_df], ignore_index=True)
    if combined.empty:
        return combined

    combined["DateTime"] = pd.to_datetime(combined["DateTime"], utc=True)
    combined["date"] = combined["DateTime"].dt.tz_convert("America/New_York").dt.date

    out_frames = []
    for _, group in combined.groupby("date"):
        macros = group[group["Kind"] == "macro"].sort_values(["Priority", "DateTime"], ascending=[False, True])
        news = group[group["Kind"] == "news"].sort_values(["Priority", "DateTime"], ascending=[False, True]).head(MAX_NEWS_PER_DAY)
        merged = pd.concat([macros, news], ignore_index=True).sort_values(["DateTime", "Priority"], ascending=[True, False])
        out_frames.append(merged)

    combined = pd.concat(out_frames, ignore_index=True).drop(columns=["date"], errors="ignore")
    return combined.reset_index(drop=True)


def _merge_event_archive(out: pd.DataFrame, output_csv: Path | str) -> pd.DataFrame:
    output_csv = Path(output_csv)
    archive = pd.DataFrame(columns=out.columns)
    if NEWS_CSV.exists():
        try:
            archive = pd.read_csv(NEWS_CSV)
        except Exception:
            archive = pd.DataFrame(columns=out.columns)

    merged = pd.concat([archive, out], ignore_index=True)
    merged["DateTime"] = pd.to_datetime(merged["DateTime"], utc=True, errors="coerce")
    merged = merged.dropna(subset=["DateTime", "Event"])
    merged = merged.drop_duplicates(subset=["DateTime", "Event"], keep="last")
    merged = merged.sort_values("DateTime").reset_index(drop=True)
    merged_out = merged.copy()
    merged_out["DateTime"] = merged_out["DateTime"].dt.strftime("%Y-%m-%d %H:%M:%S%z")
    merged_out.to_csv(NEWS_CSV, index=False)
    merged_out.to_csv(output_csv, index=False)
    return merged_out


def save_calendar_only_events(start_date: str, end_date: str, output_csv: Path | str = COMBINED_EVENTS_CSV) -> pd.DataFrame:
    df = build_calendar_only_events(start_date, end_date, auto_download=True)
    if df.empty:
        raise RuntimeError("Weekly USD calendar feed is empty")
    out = df[["DateTime", "Currency", "Impact", "Event", "Actual", "Forecast", "Previous"]].copy()
    return _merge_event_archive(out, output_csv)


def save_combined_events(start_date: str, end_date: str, output_csv: Path | str = COMBINED_EVENTS_CSV) -> pd.DataFrame:
    df = build_combined_events(start_date, end_date)
    if df.empty:
        raise RuntimeError("Combined news/macro feed is empty")
    out = df[["DateTime", "Currency", "Impact", "Event", "Actual", "Forecast", "Previous"]].copy()
    return _merge_event_archive(out, output_csv)


if __name__ == "__main__":
    end = pd.Timestamp.now(tz="America/New_York").date()
    start = end - timedelta(days=14)
    df = save_combined_events(start.isoformat(), end.isoformat())
    print(f"saved {len(df)} rows -> {COMBINED_EVENTS_CSV}")
