#!/usr/bin/env python3
"""Backfill qqq_test CSV/static JSON data into PostgreSQL."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, time
from hashlib import sha256
from pathlib import Path
from typing import Any

import pandas as pd
from psycopg.types.json import Jsonb

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
PUBLIC_DATA_DIR = BASE_DIR / "public" / "data"
EASTERN = "America/New_York"
SYMBOL = "QQQ"
PROVIDER = "yfinance"

sys.path.insert(0, str(BASE_DIR))

from database import connect, get_database_url  # noqa: E402
from scripts.db_migrate import apply_migrations  # noqa: E402


@dataclass(frozen=True)
class PriceBar:
    ts: pd.Timestamp
    bar_seconds: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    provider: str
    adjusted: bool
    source_hash: str


@dataclass(frozen=True)
class MarketEvent:
    event_time: pd.Timestamp
    market_date: str
    kind: str
    source: str
    source_id: str
    currency: str
    impact: str
    title: str
    actual: str
    forecast: str
    previous: str
    priority: int
    event_payload: dict[str, Any]


@dataclass(frozen=True)
class NewsSummary:
    event_key: tuple[str, str, str, str]
    summary_text: str
    source_attribution: str
    model_provider: str
    model_name: str | None


@dataclass(frozen=True)
class BackfillPlan:
    intraday_bars: int
    daily_bars: int
    market_events: int
    news_summaries: int
    raw_news_rows_skipped: int
    static_json_files: int
    static_json_event_rows: int
    duplicate_event_rows_collapsed: int
    first_intraday_ts: str | None
    last_intraday_ts: str | None
    first_daily_ts: str | None
    last_daily_ts: str | None
    first_event_date: str | None
    last_event_date: str | None


def _clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _row_hash(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return sha256(text.encode("utf-8")).hexdigest()


def _source_attribution(title: str) -> str:
    match = re.search(r"\[([^\[\]]+)\]\s*$", title)
    return match.group(1).strip() if match else ""


def _event_kind(impact: str) -> str | None:
    impact_normalized = impact.strip().lower()
    if impact_normalized == "news":
        return None
    if impact_normalized == "news summary":
        return "news_summary"
    return "macro"


def _event_source(kind: str, title: str, import_source: str) -> str:
    if kind == "news_summary":
        return _source_attribution(title) or "gemini"
    attribution = _source_attribution(title).lower()
    if attribution in {"bea", "fed"}:
        return attribution
    return "macro_calendar"


def _event_priority(impact: str) -> int:
    text = impact.lower()
    if "news summary" in text:
        return 8
    if "high" in text:
        return 7
    if "medium" in text:
        return 5
    if "low" in text:
        return 3
    return 1


def _event_record_from_values(
    event_time: pd.Timestamp,
    impact: Any,
    title: Any,
    currency: Any = "USD",
    actual: Any = "",
    forecast: Any = "",
    previous: Any = "",
    import_source: str = "csv",
    extra_payload: dict[str, Any] | None = None,
) -> MarketEvent | None:
    impact_text = _clean_text(impact)
    title_text = _clean_text(title)
    if not title_text:
        return None
    kind = _event_kind(impact_text)
    if kind is None:
        return None
    event_time = pd.Timestamp(event_time)
    if event_time.tzinfo is None:
        event_time = event_time.tz_localize(EASTERN)
    event_time = event_time.tz_convert(EASTERN)
    source = _event_source(kind, title_text, import_source)
    market_date = event_time.date().isoformat()
    payload = {
        "import_source": import_source,
        "impact": impact_text,
        "title": title_text,
        "actual": _clean_text(actual),
        "forecast": _clean_text(forecast),
        "previous": _clean_text(previous),
    }
    if extra_payload:
        payload.update(extra_payload)
    source_id = _row_hash(
        {
            "event_time": event_time.isoformat(),
            "kind": kind,
            "source": source,
            "title": title_text,
        }
    )
    return MarketEvent(
        event_time=event_time,
        market_date=market_date,
        kind=kind,
        source=source,
        source_id=source_id,
        currency=_clean_text(currency) or "USD",
        impact=impact_text,
        title=title_text,
        actual=_clean_text(actual),
        forecast=_clean_text(forecast),
        previous=_clean_text(previous),
        priority=_event_priority(impact_text),
        event_payload=payload,
    )


def load_intraday_bars(path: Path = DATA_DIR / "qqq_1m.csv") -> list[PriceBar]:
    df = pd.read_csv(path)
    required = {"datetime", "open", "high", "low", "close", "volume"}
    missing = required.difference(df.columns)
    if missing:
        raise RuntimeError(f"{path} missing required columns: {sorted(missing)}")
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_convert(EASTERN)
    rows: list[PriceBar] = []
    for _, row in df.iterrows():
        payload = {column: row[column] for column in ["datetime", "open", "high", "low", "close", "volume"]}
        rows.append(
            PriceBar(
                ts=row["datetime"],
                bar_seconds=60,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                provider=PROVIDER,
                adjusted=True,
                source_hash=_row_hash(payload),
            )
        )
    return rows


def load_daily_bars(path: Path = DATA_DIR / "qqq_daily.csv") -> list[PriceBar]:
    df = pd.read_csv(path)
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required.difference(df.columns)
    if missing:
        raise RuntimeError(f"{path} missing required columns: {sorted(missing)}")
    rows: list[PriceBar] = []
    for _, row in df.iterrows():
        trade_date = pd.Timestamp(row["date"]).date()
        ts = pd.Timestamp(datetime.combine(trade_date, time(16, 0)), tz=EASTERN)
        payload = {column: row[column] for column in ["date", "open", "high", "low", "close", "volume"]}
        rows.append(
            PriceBar(
                ts=ts,
                bar_seconds=86400,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                provider=PROVIDER,
                adjusted=True,
                source_hash=_row_hash(payload),
            )
        )
    return rows


def load_csv_events(path: Path = DATA_DIR / "ff_events.csv") -> tuple[list[MarketEvent], int]:
    df = pd.read_csv(path)
    required = {"DateTime", "Currency", "Impact", "Event", "Actual", "Forecast", "Previous"}
    missing = required.difference(df.columns)
    if missing:
        raise RuntimeError(f"{path} missing required columns: {sorted(missing)}")
    df["DateTime"] = pd.to_datetime(df["DateTime"], utc=True).dt.tz_convert(EASTERN)
    events: list[MarketEvent] = []
    raw_news_rows = 0
    for _, row in df.iterrows():
        if _clean_text(row["Impact"]).lower() == "news":
            raw_news_rows += 1
            continue
        event = _event_record_from_values(
            row["DateTime"],
            row["Impact"],
            row["Event"],
            row["Currency"],
            row["Actual"],
            row["Forecast"],
            row["Previous"],
            import_source="csv",
        )
        if event is not None:
            events.append(event)
    return events, raw_news_rows


def _active_static_json_paths() -> list[Path]:
    dates_path = PUBLIC_DATA_DIR / "dates.json"
    if not dates_path.exists():
        return []
    dates = json.loads(dates_path.read_text())
    return [PUBLIC_DATA_DIR / f"{date_label}.json" for date_label in dates if (PUBLIC_DATA_DIR / f"{date_label}.json").exists()]


def load_static_json_events() -> tuple[list[MarketEvent], int, int]:
    events: list[MarketEvent] = []
    raw_news_rows = 0
    paths = _active_static_json_paths()
    for path in paths:
        payload = json.loads(path.read_text())
        trade_date = _clean_text(payload.get("date")) or path.stem
        for row_index, row in enumerate(payload.get("ff_events", [])):
            if _clean_text(row.get("impact")).lower() == "news":
                raw_news_rows += 1
                continue
            event_time = pd.Timestamp(f"{trade_date} {_clean_text(row.get('time')) or '00:00'}", tz=EASTERN)
            event = _event_record_from_values(
                event_time,
                row.get("impact"),
                row.get("event"),
                "USD",
                row.get("actual"),
                row.get("forecast"),
                row.get("previous"),
                import_source="public_json",
                extra_payload={
                    "public_json_date": trade_date,
                    "public_json_order": row_index,
                },
            )
            if event is not None:
                events.append(event)
    return events, raw_news_rows, len(paths)


def collapse_events(events: list[MarketEvent]) -> tuple[list[MarketEvent], int]:
    collapsed: dict[tuple[str, str, str, str], MarketEvent] = {}
    duplicates = 0
    for event in events:
        key = (event.event_time.isoformat(), event.kind, event.source, event.title)
        if key in collapsed:
            duplicates += 1
            existing = collapsed[key]
            payload = dict(existing.event_payload)
            sources = set(payload.get("import_sources", [payload.get("import_source", "unknown")]))
            sources.add(event.event_payload.get("import_source", "unknown"))
            payload["import_sources"] = sorted(sources)
            for metadata_key in ("public_json_date", "public_json_order"):
                if metadata_key in event.event_payload:
                    payload[metadata_key] = event.event_payload[metadata_key]
            collapsed[key] = MarketEvent(
                event_time=existing.event_time,
                market_date=existing.market_date,
                kind=existing.kind,
                source=existing.source,
                source_id=existing.source_id,
                currency=existing.currency,
                impact=existing.impact,
                title=existing.title,
                actual=existing.actual,
                forecast=existing.forecast,
                previous=existing.previous,
                priority=existing.priority,
                event_payload=payload,
            )
        else:
            collapsed[key] = event
    return list(collapsed.values()), duplicates


def news_summaries_from_events(events: list[MarketEvent]) -> list[NewsSummary]:
    summaries: list[NewsSummary] = []
    for event in events:
        if event.kind != "news_summary":
            continue
        model_provider = "heuristic_fallback" if event.title.lower().startswith("related news:") else "gemini"
        summaries.append(
            NewsSummary(
                event_key=(event.event_time.isoformat(), event.kind, event.source, event.title),
                summary_text=event.title,
                source_attribution=_source_attribution(event.title),
                model_provider=model_provider,
                model_name=None,
            )
        )
    return summaries


def build_plan() -> tuple[BackfillPlan, list[PriceBar], list[PriceBar], list[MarketEvent], list[NewsSummary]]:
    intraday_bars = load_intraday_bars()
    daily_bars = load_daily_bars()
    csv_events, csv_raw_news = load_csv_events()
    static_events, static_raw_news, static_json_files = load_static_json_events()
    events, duplicate_events = collapse_events(csv_events + static_events)
    summaries = news_summaries_from_events(events)
    event_dates = sorted({event.market_date for event in events})
    plan = BackfillPlan(
        intraday_bars=len(intraday_bars),
        daily_bars=len(daily_bars),
        market_events=len(events),
        news_summaries=len(summaries),
        raw_news_rows_skipped=csv_raw_news + static_raw_news,
        static_json_files=static_json_files,
        static_json_event_rows=len(static_events),
        duplicate_event_rows_collapsed=duplicate_events,
        first_intraday_ts=intraday_bars[0].ts.isoformat() if intraday_bars else None,
        last_intraday_ts=intraday_bars[-1].ts.isoformat() if intraday_bars else None,
        first_daily_ts=daily_bars[0].ts.isoformat() if daily_bars else None,
        last_daily_ts=daily_bars[-1].ts.isoformat() if daily_bars else None,
        first_event_date=event_dates[0] if event_dates else None,
        last_event_date=event_dates[-1] if event_dates else None,
    )
    return plan, intraday_bars, daily_bars, events, summaries


def print_plan(plan: BackfillPlan) -> None:
    print("[db_backfill] plan")
    for key, value in asdict(plan).items():
        print(f"[db_backfill] {key}={value}")


def upsert_instrument(conn) -> int:
    row = conn.execute(
        """
        INSERT INTO instruments (symbol, asset_class, exchange, currency, timezone, provider_identifiers)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol) DO UPDATE SET
            asset_class = EXCLUDED.asset_class,
            exchange = EXCLUDED.exchange,
            currency = EXCLUDED.currency,
            timezone = EXCLUDED.timezone,
            provider_identifiers = EXCLUDED.provider_identifiers,
            updated_at = now()
        RETURNING instrument_id
        """,
        (SYMBOL, "etf", "NASDAQ", "USD", EASTERN, Jsonb({"yfinance": SYMBOL})),
    ).fetchone()
    return int(row[0])


def create_ingest_run(conn, plan: BackfillPlan) -> int:
    row = conn.execute(
        """
        INSERT INTO ingest_runs (provider, job_name, status, row_count, metadata)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING ingest_run_id
        """,
        (
            "local_csv_static_json",
            "db_backfill",
            "running",
            plan.intraday_bars + plan.daily_bars + plan.market_events,
            Jsonb(asdict(plan)),
        ),
    ).fetchone()
    return int(row[0])


def finish_ingest_run(conn, ingest_run_id: int, status: str, row_count: int, error_message: str | None = None) -> None:
    conn.execute(
        """
        UPDATE ingest_runs
        SET status = %s, row_count = %s, error_message = %s, finished_at = now()
        WHERE ingest_run_id = %s
        """,
        (status, row_count, error_message, ingest_run_id),
    )


def upsert_price_bars(conn, instrument_id: int, ingest_run_id: int, bars: list[PriceBar]) -> None:
    rows = [
        (
            instrument_id,
            bar.ts.to_pydatetime(),
            bar.bar_seconds,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.provider,
            bar.adjusted,
            bar.source_hash,
            ingest_run_id,
        )
        for bar in bars
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO price_bars (
                instrument_id, ts, bar_seconds, open, high, low, close, volume,
                provider, adjusted, source_hash, ingest_run_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (instrument_id, bar_seconds, ts, provider) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                adjusted = EXCLUDED.adjusted,
                source_hash = EXCLUDED.source_hash,
                ingest_run_id = EXCLUDED.ingest_run_id
            """,
            rows,
        )


def upsert_market_events(conn, ingest_run_id: int, events: list[MarketEvent]) -> dict[tuple[str, str, str, str], int]:
    event_ids: dict[tuple[str, str, str, str], int] = {}
    for event in events:
        row = conn.execute(
            """
            INSERT INTO market_events (
                event_time, market_date, kind, source, source_id, currency, impact, title,
                actual, forecast, previous, priority, event_payload, ingest_run_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_time, kind, source, title) DO UPDATE SET
                source_id = EXCLUDED.source_id,
                currency = EXCLUDED.currency,
                impact = EXCLUDED.impact,
                actual = EXCLUDED.actual,
                forecast = EXCLUDED.forecast,
                previous = EXCLUDED.previous,
                priority = EXCLUDED.priority,
                event_payload = EXCLUDED.event_payload,
                ingest_run_id = EXCLUDED.ingest_run_id,
                updated_at = now()
            RETURNING market_event_id
            """,
            (
                event.event_time.to_pydatetime(),
                event.market_date,
                event.kind,
                event.source,
                event.source_id,
                event.currency,
                event.impact,
                event.title,
                event.actual,
                event.forecast,
                event.previous,
                event.priority,
                Jsonb(event.event_payload),
                ingest_run_id,
            ),
        ).fetchone()
        event_ids[(event.event_time.isoformat(), event.kind, event.source, event.title)] = int(row[0])
    return event_ids


def upsert_news_summaries(
    conn,
    instrument_id: int,
    ingest_run_id: int,
    summaries: list[NewsSummary],
    event_ids: dict[tuple[str, str, str, str], int],
) -> None:
    rows = [
        (
            event_ids[summary.event_key],
            instrument_id,
            summary.summary_text,
            summary.source_attribution,
            summary.model_provider,
            summary.model_name,
            ingest_run_id,
        )
        for summary in summaries
        if summary.event_key in event_ids
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO news_summaries (
                market_event_id, instrument_id, summary_text, source_attribution,
                model_provider, model_name, ingest_run_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (market_event_id) DO UPDATE SET
                instrument_id = EXCLUDED.instrument_id,
                summary_text = EXCLUDED.summary_text,
                source_attribution = EXCLUDED.source_attribution,
                model_provider = EXCLUDED.model_provider,
                model_name = EXCLUDED.model_name,
                ingest_run_id = EXCLUDED.ingest_run_id
            """,
            rows,
        )


def apply_backfill(database_url: str | None, migrate_first: bool = False) -> BackfillPlan:
    plan, intraday_bars, daily_bars, events, summaries = build_plan()
    if migrate_first:
        apply_migrations(database_url)
    total_rows = plan.intraday_bars + plan.daily_bars + plan.market_events
    with connect(database_url, autocommit=False) as conn:
        ingest_run_id = create_ingest_run(conn, plan)
        try:
            instrument_id = upsert_instrument(conn)
            upsert_price_bars(conn, instrument_id, ingest_run_id, intraday_bars + daily_bars)
            event_ids = upsert_market_events(conn, ingest_run_id, events)
            upsert_news_summaries(conn, instrument_id, ingest_run_id, summaries, event_ids)
            finish_ingest_run(conn, ingest_run_id, "success", total_rows)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise RuntimeError(f"Backfill failed before commit: {exc}") from exc
    return plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill qqq_test CSV/static JSON data into PostgreSQL.")
    parser.add_argument("--apply", action="store_true", help="Write to PostgreSQL. Omit for a dry-run plan only.")
    parser.add_argument("--migrate-first", action="store_true", help="Apply schema migrations before the backfill.")
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL for this run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.apply:
        plan, *_ = build_plan()
        print_plan(plan)
        configured = bool(args.database_url or get_database_url(required=False))
        print(f"[db_backfill] database_url_configured={configured}")
        print("[db_backfill] dry_run=true")
        return 0
    if not (args.database_url or get_database_url(required=False)):
        raise RuntimeError("DATABASE_URL is required for --apply. Copy env.example/database.env.example to env/database.env and edit it.")
    plan = apply_backfill(args.database_url, migrate_first=args.migrate_first)
    print_plan(plan)
    print("[db_backfill] dry_run=false")
    print("[db_backfill] status=success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
