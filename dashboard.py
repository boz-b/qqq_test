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
# Smoke-test: run this file directly to verify the loaders work
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Quick validation — will be replaced in Step 3 with the real server main()
    print("Loading CSVs …")
    intra  = load_intraday()
    daily  = load_daily()
    ff     = load_ff_events()
    print(f"  Intraday : {len(intra):,} rows  {intra.index[0]} → {intra.index[-1]}")
    print(f"  Daily    : {len(daily):,} rows  {daily.index[0]} → {daily.index[-1]}")
    print(f"  FF events: {len(ff):,} rows  {ff['DateTime'].min()} → {ff['DateTime'].max()}")
    print("Step 1 OK — CSV loaders work correctly.")
