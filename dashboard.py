"""
dashboard.py — QQQ Intraday Dashboard
======================================
A self-contained, zero-dependency web dashboard (beyond what is already in
requirements.txt) that serves a single-page HTML/JS UI from Python's built-in
http.server.  No Flask, no FastAPI, no extra installs required.

Usage:
    source venv/bin/activate
    python3 dashboard.py            # opens on http://localhost:8765
    python3 dashboard.py --port 9000  # custom port

The page lets the user pick any trading date available in the local CSV cache
and instantly renders:
  • A 1-minute OHLC close-line chart from 8:00 AM to 11:00 AM ET
  • Vertical dashed lines at 9:30 (market open / W1 start) and 10:00 (W2 start)
  • A horizontal dashed line at the prior-day closing price
  • A left panel with: prior close, premarket gap %, PM direction/momentum/accel,
    PM reversal flag, and any USD ForexFactory events that day
"""

# ---------------------------------------------------------------------------
# Standard-library imports only — no third-party packages needed for serving
# ---------------------------------------------------------------------------
import argparse          # parse optional --port flag from the command line
import json              # serialize Python dicts → JSON for the API responses
import os                # path helpers (dirname, join)
import sys               # sys.exit on fatal errors
from http.server import BaseHTTPRequestHandler, HTTPServer  # built-in web server
from urllib.parse import urlparse, parse_qs                 # URL routing + query params

# ---------------------------------------------------------------------------
# Third-party imports — all already in requirements.txt
# ---------------------------------------------------------------------------
import pandas as pd      # CSV loading, time-zone handling, resampling
import numpy as np       # NaN checks (np.isnan / np.isfinite)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Absolute path to the directory containing this script.
# Using __file__ makes the script work regardless of where you launch it from.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Paths to the three CSV files produced/updated by data_loader.py & ff_scraper.py
INTRADAY_CSV = os.path.join(BASE_DIR, "qqq_1m.csv")   # 1-min bars, premarket included
DAILY_CSV    = os.path.join(BASE_DIR, "qqq_daily.csv") # end-of-day OHLCV, ~2 years
FF_CSV       = os.path.join(BASE_DIR, "ff_events.csv") # ForexFactory USD macro events

# IANA timezone name used for ALL timestamp conversions in this project.
# DST transitions are handled automatically by pandas / pytz.
EASTERN = "America/New_York"

# Session boundary times (Eastern, 24-hour).  These match CLAUDE.md conventions.
PREMARKET_START = "08:00"   # earliest bar shown in the chart
CHART_END       = "11:00"   # latest bar shown (captures W1 + W2 + a 30-min tail)
MARKET_OPEN     = "09:30"   # vertical annotation — W1 start / official open
W2_START        = "10:00"   # vertical annotation — W2 start

# Default HTTP port.  Can be overridden with --port.
DEFAULT_PORT = 8765

# ---------------------------------------------------------------------------
# Step 1 — Data loading helpers
# ---------------------------------------------------------------------------
# All three loaders follow the same pattern:
#   1. Read the raw CSV with pd.read_csv()
#   2. Parse the datetime column, force UTC, convert to Eastern
#   3. Return a tidy DataFrame ready for downstream functions
# Errors are intentionally propagated (not swallowed) so the operator sees a
# clear message if a CSV is missing or malformed.

def load_intraday() -> pd.DataFrame:
    """
    Load and return the 1-minute bar CSV as a DataFrame.

    Returns
    -------
    pd.DataFrame
        Index  : DatetimeTZDtype (America/New_York), name='datetime'
        Columns: open, high, low, close, volume  (float / int)
    """
    # read_csv keeps datetime as a plain string column — we fix that next
    df = pd.read_csv(INTRADAY_CSV)

    # Convert the 'datetime' column: parse → UTC → Eastern.
    # utc=True is required when the strings carry mixed UTC-offsets (e.g. both
    # -05:00 and -04:00 appear in the same file due to DST changes).
    df["datetime"] = (
        pd.to_datetime(df["datetime"], utc=True)   # parse; interpret as UTC
          .dt.tz_convert(EASTERN)                   # shift to Eastern wall-clock time
    )

    # Use the timezone-aware datetime as the index for easy .loc[] slicing later
    df = df.set_index("datetime").sort_index()

    return df


def load_daily() -> pd.DataFrame:
    """
    Load and return the daily OHLCV CSV.

    The 'date' column from Yahoo Finance end-of-day bars is timestamped at
    ~19:00 ET (post-market close).  We normalise it to the calendar date so
    that prior-close look-ups use simple date equality.

    Returns
    -------
    pd.DataFrame
        Index  : DatetimeTZDtype (America/New_York), name='date'
        Columns: open, high, low, close, volume
    """
    df = pd.read_csv(DAILY_CSV)

    # Same UTC → Eastern pattern as intraday
    df["date"] = (
        pd.to_datetime(df["date"], utc=True)
          .dt.tz_convert(EASTERN)
    )

    df = df.set_index("date").sort_index()

    return df


def load_ff_events() -> pd.DataFrame:
    """
    Load and return the ForexFactory macro-event CSV.

    Returns
    -------
    pd.DataFrame
        Index  : RangeIndex (not datetime — events are looked up by calendar date)
        Columns: DateTime (tz-aware Eastern), Currency, Impact, Event,
                 Actual, Forecast, Previous, date (plain date object for filtering)
    """
    df = pd.read_csv(FF_CSV)

    # Parse the 'DateTime' column; same UTC → Eastern pattern
    df["DateTime"] = (
        pd.to_datetime(df["DateTime"], utc=True)
          .dt.tz_convert(EASTERN)
    )

    # Add a plain `date` column (no time component) so callers can do:
    #   ff_events[ff_events["date"] == some_date]
    # without worrying about time-of-day alignment
    df["date"] = df["DateTime"].dt.date

    return df


# ---------------------------------------------------------------------------
# Step 2 — Module-level data cache
# ---------------------------------------------------------------------------
# Load all three CSVs once at import time.  Every HTTP request then works
# against these in-memory DataFrames rather than re-reading from disk.
# If a CSV is missing we print a warning and use an empty DataFrame so the
# server can still start (it will just show no data for that source).

def _safe_load(loader_fn, label: str) -> pd.DataFrame:
    """Call loader_fn(); on any exception log the error and return empty DF."""
    try:
        return loader_fn()
    except Exception as exc:                          # catch ANY load error
        print(f"[dashboard] WARNING: could not load {label}: {exc}", flush=True)
        return pd.DataFrame()                         # empty fallback

# These module-level names are read by get_available_dates() and get_day_data()
_INTRADAY: pd.DataFrame = _safe_load(load_intraday, "intraday CSV")
_DAILY:    pd.DataFrame = _safe_load(load_daily,    "daily CSV")
_FF:       pd.DataFrame = _safe_load(load_ff_events,"FF events CSV")

# Pre-build a dict  date → prior_close  from the daily CSV so get_day_data()
# can look up prior closes in O(1) without scanning the whole DataFrame each call.
def _build_daily_closes(daily_df: pd.DataFrame) -> dict:
    """Return {date: float} mapping every date in daily_df to its close price."""
    closes = {}
    for ts, row in daily_df.iterrows():
        # ts is a tz-aware Timestamp; .date() strips the time component
        d = ts.date() if hasattr(ts, "date") else ts
        closes[d] = float(row["close"])
    return closes

# Sorted list of dates in the daily CSV — used to find the "previous trading day"
_DAILY_CLOSES: dict = _build_daily_closes(_DAILY)
_SORTED_DAILY_DATES: list = sorted(_DAILY_CLOSES.keys())

# ---------------------------------------------------------------------------
# Step 2 — API data functions
# ---------------------------------------------------------------------------

def get_available_dates() -> list[str]:
    """
    Return a sorted list of trading-date strings (YYYY-MM-DD) for which the
    intraday CSV has at least one bar in the 8:00–11:00 AM window.

    Only dates with chart-window data are included — days where the CSV has
    rows outside that window (e.g. only after-hours bars) are excluded.

    Returns
    -------
    list[str]
        e.g. ["2026-02-06", "2026-02-07", …, "2026-02-27"]
    """
    if _INTRADAY.empty:
        # No intraday data at all — return empty list so the UI can show a message
        return []

    # Filter to bars that fall within the chart window (8:00 AM – 11:00 AM).
    # We only want dates that actually have data to display.
    mask = (
        (_INTRADAY.index.hour > 8)   |              # hour > 8 → definitely inside window
        (_INTRADAY.index.hour == 8)                  # hour == 8 → also check minutes ≥ 0
    ) & (
        (_INTRADAY.index.hour < 11)  |              # hour < 11 → definitely inside window
        (_INTRADAY.index.hour == 11) & (_INTRADAY.index.minute == 0)  # exactly 11:00
    )
    # Simpler re-expression of the same bounds using .time comparison:
    # (index.time >= time(8,0)) & (index.time <= time(11,0))
    # We use .time on the index which is already Eastern-tz-aware.
    from datetime import time as dtime               # local import avoids shadowing built-in
    chart_bars = _INTRADAY[
        (_INTRADAY.index.time >= dtime(8, 0)) &
        (_INTRADAY.index.time <= dtime(11, 0))
    ]

    if chart_bars.empty:
        return []

    # .index.date gives a numpy array of datetime.date objects — one per bar.
    # dict.fromkeys() deduplicates while preserving insertion order (chronological
    # because the index is sorted).  list() converts back to a plain list.
    unique_dates = list(dict.fromkeys(chart_bars.index.date))

    # Convert each date object to an ISO 8601 string (YYYY-MM-DD) so the JSON
    # serialiser can handle it and the JS date picker can display it.
    return [d.isoformat() for d in sorted(unique_dates)]


def _prior_close(trade_date) -> float | None:
    """
    Return the closing price of the most recent trading day *before* trade_date
    using the daily CSV cache.

    Parameters
    ----------
    trade_date : datetime.date

    Returns
    -------
    float or None if no prior day exists in the daily CSV.
    """
    # _SORTED_DAILY_DATES is pre-sorted ascending; find all dates before today
    prior = [d for d in _SORTED_DAILY_DATES if d < trade_date]
    if not prior:
        return None                          # first day in the dataset — no prior close
    return _DAILY_CLOSES.get(prior[-1])      # most recent date before trade_date


def _pm_stats(day_bars: pd.DataFrame, prev_close: float | None) -> dict:
    """
    Compute the five premarket statistics displayed in the left panel.
    Logic mirrors features.py::_premarket_features() exactly so numbers
    are consistent with the backtester.

    Parameters
    ----------
    day_bars   : 1-min bars for one trading day (Eastern tz-aware index)
    prev_close : prior day's closing price, or None

    Returns
    -------
    dict with keys:
        gap_pct          – premarket gap vs prior close (%, rounded to 2 dp)
        direction        – +1 gap-up / -1 gap-down / 0 flat
        momentum_score   – late-PM move / early-PM move ratio (rounded to 2 dp)
        momentum_accel   – +1 accelerating / -1 decelerating / 0 no data
        reversal_flag    – 1 if direction flipped between 8:59 and 9:29, else 0
    """
    from datetime import time as dtime      # avoid shadowing the built-in

    # ---- helper: last close strictly before a given time ----
    def _last_close_before(df: pd.DataFrame, t) -> float | None:
        sub = df[df.index.time < t]         # bars strictly before time t
        return float(sub["close"].iloc[-1]) if not sub.empty else None

    # ---- helper: bars in [t_start, t_end) ----
    def _slice(df: pd.DataFrame, t0, t1) -> pd.DataFrame:
        return df[(df.index.time >= t0) & (df.index.time < t1)]

    # Price at 9:29 AM (last premarket bar before the open)
    p929 = _last_close_before(day_bars, dtime(9, 30))

    # Price at 8:59 AM (used for reversal detection)
    p859 = _last_close_before(day_bars, dtime(9,  0))

    # ── gap_pct & direction ──────────────────────────────────────────────────
    if prev_close and prev_close > 0 and p929 is not None:
        # Percentage gap: how far above/below prior close did premarket settle?
        gap_pct = round((p929 - prev_close) / prev_close * 100.0, 2)
    else:
        gap_pct = 0.0

    # np.sign returns +1.0 / -1.0 / 0.0; int() converts to Python integer
    direction = int(np.sign(gap_pct)) if gap_pct != 0 else 0

    # ── momentum (early 8:00–8:44 vs late 8:45–9:29) ────────────────────────
    early = _slice(day_bars, dtime(8,  0), dtime(8, 45))   # early premarket half
    late  = _slice(day_bars, dtime(8, 45), dtime(9, 30))   # late  premarket half

    # Raw dollar move in each half (last close − first close)
    early_move = (float(early["close"].iloc[-1]) - float(early["close"].iloc[0])
                  if len(early) >= 2 else 0.0)
    late_move  = (float(late["close"].iloc[-1])  - float(late["close"].iloc[0])
                  if len(late)  >= 2 else 0.0)

    # Momentum score: ratio of late move to early move magnitude.
    # +0.001 is epsilon smoothing to avoid ZeroDivisionError when early_move=0.
    momentum_score = round(late_move / (abs(early_move) + 0.001), 2)

    # Acceleration label
    if early_move == 0 and late_move == 0:
        momentum_accel = 0                             # no information
    elif (np.sign(late_move) == np.sign(early_move)   # same direction …
          and abs(late_move) > abs(early_move)):        # … AND bigger → accelerating
        momentum_accel = 1
    else:
        momentum_accel = -1                            # decelerating or reversing

    # ── reversal flag ────────────────────────────────────────────────────────
    if prev_close and prev_close > 0 and p859 is not None and p929 is not None:
        # Direction of premarket price vs prior close at two snapshot times
        dir_859 = int(np.sign(p859 - prev_close))     # direction at 8:59
        dir_929 = int(np.sign(p929 - prev_close))     # direction at 9:29
        # Reversal: direction flipped AND there was a clear initial direction
        reversal_flag = 1 if (dir_859 != dir_929 and dir_859 != 0) else 0
    else:
        reversal_flag = 0

    return {
        "gap_pct":        gap_pct,
        "direction":      direction,
        "momentum_score": momentum_score,
        "momentum_accel": momentum_accel,
        "reversal_flag":  reversal_flag,
    }


def _events_for_day(trade_date) -> list[dict]:
    """
    Return a list of ForexFactory USD events for *trade_date*, sorted by time.

    Each event dict has:
        time     – "HH:MM" Eastern (or "" if time is unknown)
        event    – event name string
        impact   – raw Impact string from the CSV (e.g. "High Impact Expected")
        actual   – string (may be empty)
        forecast – string (may be empty)
        previous – string (may be empty)
    """
    if _FF.empty:
        return []

    # Filter to rows whose plain date matches and whose currency is USD.
    # .str.upper() normalises "usd" / "USD" / "Usd" → all compare equal to "USD".
    mask = (
        (_FF["date"] == trade_date) &
        (_FF["Currency"].str.upper() == "USD")
    )
    day_ff = _FF[mask].copy()

    if day_ff.empty:
        return []

    # Sort by event time so the UI table reads chronologically
    day_ff = day_ff.sort_values("DateTime")

    events = []
    for _, row in day_ff.iterrows():
        # Format the time as "HH:MM" Eastern for display in the table
        try:
            t_str = row["DateTime"].strftime("%H:%M")   # e.g. "08:30"
        except Exception:
            t_str = ""                                   # graceful fallback

        events.append({
            "time":     t_str,
            "event":    str(row.get("Event",    "") or ""),
            "impact":   str(row.get("Impact",   "") or ""),
            "actual":   str(row.get("Actual",   "") or ""),
            "forecast": str(row.get("Forecast", "") or ""),
            "previous": str(row.get("Previous", "") or ""),
        })

    return events


def get_day_data(date_str: str) -> dict:
    """
    Return all data needed to render one day's dashboard panel as a JSON-safe dict.

    Parameters
    ----------
    date_str : str  — ISO date, e.g. "2026-02-10"

    Returns
    -------
    dict with keys:
        date        – echo of the requested date
        chart       – {"labels": ["08:00",…], "prices": [596.02,…]}
        prior_close – float or null
        pm_stats    – dict from _pm_stats()
        ff_events   – list of event dicts from _events_for_day()
        error       – present only on failure; value is an error message string
    """
    from datetime import date as ddate, time as dtime

    # ── parse & validate the date string ────────────────────────────────────
    try:
        trade_date = ddate.fromisoformat(date_str)   # "2026-02-10" → date(2026,2,10)
    except ValueError:
        # Return an error payload instead of raising — the HTTP handler will
        # send this as a 400 JSON response.
        return {"error": f"Invalid date format: {date_str!r}. Expected YYYY-MM-DD."}

    # ── slice intraday bars for this day, chart window only ──────────────────
    if _INTRADAY.empty:
        return {"error": "Intraday CSV not loaded."}

    # Boolean mask: rows where the date portion of the tz-aware index == trade_date
    day_mask = _INTRADAY.index.date == trade_date
    day_bars  = _INTRADAY[day_mask]                 # all bars for this day

    if day_bars.empty:
        return {"error": f"No intraday data for {date_str}."}

    # Further restrict to the chart window [08:00, 11:00] for the chart arrays.
    # We keep the full day_bars for pm_stats (which needs 8:45, 8:59, 9:29 bars).
    chart_bars = day_bars[
        (day_bars.index.time >= dtime(8,  0)) &
        (day_bars.index.time <= dtime(11, 0))
    ]

    # Build parallel lists for Chart.js: x-axis labels + y-axis prices.
    # strftime("%H:%M") converts each Timestamp to "HH:MM" Eastern string.
    chart_labels = [ts.strftime("%H:%M") for ts in chart_bars.index]
    chart_prices = [
        round(float(p), 2) if np.isfinite(p) else None   # None serialises to JSON null
        for p in chart_bars["close"]
    ]

    # ── prior close ──────────────────────────────────────────────────────────
    prev_close = _prior_close(trade_date)           # float or None

    # ── premarket stats ──────────────────────────────────────────────────────
    pm = _pm_stats(day_bars, prev_close)

    # ── ForexFactory events ───────────────────────────────────────────────────
    events = _events_for_day(trade_date)

    return {
        "date":        date_str,
        "chart": {
            "labels":  chart_labels,    # ["08:00", "08:01", …, "11:00"]
            "prices":  chart_prices,    # [596.02, 596.10, …]
        },
        "prior_close": round(prev_close, 2) if prev_close is not None else None,
        "pm_stats":    pm,              # gap_pct, direction, momentum_*, reversal_flag
        "ff_events":   events,          # list of {time, event, impact, actual, …}
    }


# ---------------------------------------------------------------------------
# Smoke-test: run this file directly to verify Steps 1 & 2
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Step 2 smoke test ===")
    dates = get_available_dates()
    print(f"Available dates ({len(dates)}): {dates[0]} … {dates[-1]}")

    # Test get_day_data on the first available date
    sample = dates[0]
    data = get_day_data(sample)
    if "error" in data:
        print(f"ERROR for {sample}: {data['error']}")
        sys.exit(1)

    print(f"\nDate        : {data['date']}")
    print(f"Prior close : {data['prior_close']}")
    print(f"PM stats    : {data['pm_stats']}")
    print(f"Chart pts   : {len(data['chart']['labels'])} labels, "
          f"{len(data['chart']['prices'])} prices")
    print(f"Chart window: {data['chart']['labels'][0]} → {data['chart']['labels'][-1]}")
    print(f"FF events   : {len(data['ff_events'])} USD events")
    for ev in data["ff_events"]:
        print(f"  {ev['time']:5s}  {ev['impact'][:4]}  {ev['event']}")
    print("\nStep 2 OK.")
