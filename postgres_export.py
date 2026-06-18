"""PostgreSQL-backed dashboard payload builder.

This module mirrors the JSON shape produced by dashboard.py, but reads durable
bars and summary-only events from PostgreSQL. It is intentionally opt-in via
QQQ_DATA_BACKEND=postgres; the CSV/dashboard path remains the default.
"""

from __future__ import annotations

from datetime import date as ddate, time as dtime
from typing import Any

import numpy as np
import pandas as pd
from psycopg.rows import dict_row

from database import connect
from dashboard import _pm_stats, _repair_chart_ohlc_anomalies

EASTERN = "America/New_York"
SYMBOL = "QQQ"
PROVIDER = "yfinance"


def _load_price_bars(bar_seconds: int) -> pd.DataFrame:
    """Load one bar interval from PostgreSQL into a dashboard-style DataFrame."""
    with connect(row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT pb.ts, pb.open, pb.high, pb.low, pb.close, pb.volume
            FROM price_bars pb
            JOIN instruments i ON i.instrument_id = pb.instrument_id
            WHERE i.symbol = %s
              AND pb.bar_seconds = %s
              AND pb.provider = %s
            ORDER BY pb.ts
            """,
            (SYMBOL, bar_seconds, PROVIDER),
        ).fetchall()
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(EASTERN)
    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.rename(columns={"ts": "datetime"}).set_index("datetime").sort_index()
    return df[["open", "high", "low", "close", "volume"]]


def _load_intraday() -> pd.DataFrame:
    return _load_price_bars(60)


def _load_daily() -> pd.DataFrame:
    bars = _load_price_bars(86400)
    if bars.empty:
        return bars
    daily = bars.copy()
    daily.index = pd.DatetimeIndex(daily.index.date, name="date")
    return daily


def _load_events() -> pd.DataFrame:
    """Load durable macro and AI news-summary events from PostgreSQL."""
    with connect(row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT
                market_event_id,
                event_time,
                market_date,
                currency,
                impact,
                title,
                actual,
                forecast,
                previous,
                event_payload
            FROM market_events
            WHERE currency = 'USD'
              AND kind IN ('macro', 'news_summary')
            ORDER BY event_time, market_event_id
            """
        ).fetchall()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["DateTime"] = pd.to_datetime(df["event_time"], utc=True).dt.tz_convert(EASTERN)
    df["date"] = pd.to_datetime(df["market_date"]).dt.date
    return df


_INTRADAY: pd.DataFrame = _load_intraday()
_DAILY: pd.DataFrame = _load_daily()
_EVENTS: pd.DataFrame = _load_events()


def _build_daily_closes(daily_df: pd.DataFrame) -> dict:
    closes = {}
    for ts, row in daily_df.iterrows():
        closes[ts.date() if hasattr(ts, "date") else ts] = float(row["close"])
    return closes


_DAILY_CLOSES: dict = _build_daily_closes(_DAILY)
_SORTED_DAILY_DATES: list = sorted(_DAILY_CLOSES.keys())


def get_available_dates() -> list[str]:
    """Return trading dates with chart-window intraday bars."""
    if _INTRADAY.empty:
        return []

    chart_bars = _INTRADAY[
        (_INTRADAY.index.time >= dtime(9, 0)) &
        (_INTRADAY.index.time <= dtime(12, 0))
    ]
    if chart_bars.empty:
        return []

    unique_dates = list(dict.fromkeys(chart_bars.index.date))
    return [day.isoformat() for day in sorted(unique_dates)]


def _prior_close(trade_date) -> float | None:
    prior = [day for day in _SORTED_DAILY_DATES if day < trade_date]
    if not prior:
        return None
    return _DAILY_CLOSES.get(prior[-1])


def _event_text(value: Any, missing: str = "") -> str:
    if value is None:
        return missing
    try:
        if pd.isna(value):
            return missing
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return missing
    return text


def _events_for_day(trade_date) -> list[dict]:
    if _EVENTS.empty:
        return []

    day_events = _EVENTS[_EVENTS["date"] == trade_date].copy()
    if day_events.empty:
        return []

    def _public_order(payload: Any) -> int | None:
        if not isinstance(payload, dict):
            return None
        value = payload.get("public_json_order")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    day_events["public_json_order"] = day_events["event_payload"].map(_public_order)
    day_events["public_json_order_missing"] = day_events["public_json_order"].isna()
    day_events = day_events.sort_values(
        ["DateTime", "public_json_order_missing", "public_json_order", "market_event_id"]
    )
    events = []
    for _, row in day_events.iterrows():
        try:
            time_label = row["DateTime"].strftime("%H:%M")
        except Exception:
            time_label = ""
        events.append(
            {
                "time": time_label,
                "event": _event_text(row.get("title"), missing=""),
                "impact": _event_text(row.get("impact"), missing=""),
                "actual": _event_text(row.get("actual")),
                "forecast": _event_text(row.get("forecast")),
                "previous": _event_text(row.get("previous")),
            }
        )
    return events


def get_day_data(date_str: str) -> dict:
    """Return one dashboard payload using PostgreSQL as the data source."""
    try:
        trade_date = ddate.fromisoformat(date_str)
    except ValueError:
        return {"error": f"Invalid date format: {date_str!r}. Expected YYYY-MM-DD."}

    if _INTRADAY.empty:
        return {"error": "PostgreSQL intraday data not loaded."}

    day_bars = _INTRADAY[_INTRADAY.index.date == trade_date]
    if day_bars.empty:
        return {"error": f"No intraday data for {date_str}."}

    chart_bars = day_bars[
        (day_bars.index.time >= dtime(9, 0)) &
        (day_bars.index.time <= dtime(12, 0))
    ]
    chart_bars = _repair_chart_ohlc_anomalies(chart_bars)

    chart_labels = [ts.strftime("%H:%M") for ts in chart_bars.index]
    chart_open = [
        round(float(price), 2) if np.isfinite(price) else None
        for price in chart_bars["open"]
    ]
    chart_high = [
        round(float(price), 2) if np.isfinite(price) else None
        for price in chart_bars["high"]
    ]
    chart_low = [
        round(float(price), 2) if np.isfinite(price) else None
        for price in chart_bars["low"]
    ]
    chart_close = [
        round(float(price), 2) if np.isfinite(price) else None
        for price in chart_bars["close"]
    ]
    chart_volume = [
        int(volume) if np.isfinite(volume) else 0
        for volume in chart_bars["volume"]
    ]

    prev_close = _prior_close(trade_date)

    return {
        "date": date_str,
        "chart": {
            "labels": chart_labels,
            "open": chart_open,
            "high": chart_high,
            "low": chart_low,
            "close": chart_close,
            "volume": chart_volume,
        },
        "prior_close": round(prev_close, 2) if prev_close is not None else None,
        "pm_stats": _pm_stats(day_bars, prev_close),
        "ff_events": _events_for_day(trade_date),
    }
