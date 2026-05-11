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
    PM reversal flag, and up to 7 combined USD news + US macro items that day
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

# Paths to the three CSV files produced/updated by data_loader.py & ff_scraper.py.
# The canonical location is BASE_DIR/data/*.csv; we keep a repo-root fallback so
# older checkouts still open without a manual migration step.
DATA_DIR = os.path.join(BASE_DIR, "data")
INTRADAY_CSV = os.path.join(DATA_DIR, "qqq_1m.csv")
DAILY_CSV    = os.path.join(DATA_DIR, "qqq_daily.csv")
FF_CSV       = os.path.join(DATA_DIR, "ff_events.csv")
LEGACY_INTRADAY_CSV = os.path.join(BASE_DIR, "qqq_1m.csv")
LEGACY_DAILY_CSV    = os.path.join(BASE_DIR, "qqq_daily.csv")
LEGACY_FF_CSV       = os.path.join(BASE_DIR, "ff_events.csv")

# IANA timezone name used for ALL timestamp conversions in this project.
# DST transitions are handled automatically by pandas / pytz.
EASTERN = "America/New_York"

# Session boundary times (Eastern, 24-hour).  These match CLAUDE.md conventions.
PREMARKET_START = "08:00"   # earliest bar shown in the chart
CHART_END       = "12:00"   # latest bar shown (captures W1 + W2 + a longer morning tail)
MARKET_OPEN     = "09:30"   # vertical annotation — W1 start / official open
W2_START        = "10:00"   # vertical annotation — W2 start

# Default HTTP port.  Can be overridden with --port.
DEFAULT_PORT = 8765


def _resolve_csv_path(primary: str, legacy: str) -> str:
    """Prefer the canonical data/ path, but tolerate older repo-root CSVs."""
    if os.path.exists(primary):
        return primary
    if os.path.exists(legacy):
        return legacy
    return primary


def _normalize_daily_dates(raw_values) -> pd.DatetimeIndex:
    """Convert daily CSV labels into clean trading-date timestamps."""
    # ↑ Daily CSVs may contain plain dates or old timezone-bearing values from before the local data was deleted.
    parsed_utc = pd.to_datetime(pd.Index(raw_values), utc=True, errors="raise")
    # ↑ Parse through UTC so pandas accepts mixed daylight-saving offsets such as -05:00 and -04:00 in one file.

    normalized_dates = pd.DatetimeIndex(parsed_utc.date)
    # ↑ Keep only the UTC calendar date, which maps old 19:00 Eastern daily labels back to the intended trading day.

    normalized_dates.name = "date"
    # ↑ Give the returned index the expected name used by the rest of the dashboard code.

    return normalized_dates
    # ↑ Return timezone-free daily labels so prior-close lookups do not depend on daylight-saving offsets.

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
    df = pd.read_csv(_resolve_csv_path(INTRADAY_CSV, LEGACY_INTRADAY_CSV))

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
    df = pd.read_csv(_resolve_csv_path(DAILY_CSV, LEGACY_DAILY_CSV))

    # Daily CSV should be interpreted as trading-day labels, not converted wall
    # times. Parse through a helper that also handles older mixed-timezone CSVs.
    df["date"] = _normalize_daily_dates(df["date"])
    # ↑ Replace the raw CSV labels with clean timezone-free trading dates before indexing.

    df = df.set_index("date").sort_index()

    return df


def load_ff_events() -> pd.DataFrame:
    """
    Load and return the combined news/macro event CSV.

    Returns
    -------
    pd.DataFrame
        Index  : RangeIndex (not datetime — events are looked up by calendar date)
        Columns: DateTime (tz-aware Eastern), Currency, Impact, Event,
                 Actual, Forecast, Previous, date (plain date object for filtering)
    """
    df = pd.read_csv(_resolve_csv_path(FF_CSV, LEGACY_FF_CSV))

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
_FF:       pd.DataFrame = _safe_load(load_ff_events,"combined events CSV")

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
    intraday CSV has at least one bar in the 9:00 AM–12:00 PM window.

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

    # Filter to bars that fall within the chart window (9:00 AM – 12:00 PM).
    # We only want dates that actually have data to display.
    from datetime import time as dtime               # local import avoids shadowing built-in
    chart_bars = _INTRADAY[
        (_INTRADAY.index.time >= dtime(9, 0)) &
        (_INTRADAY.index.time <= dtime(12, 0))
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
    Return a list of combined USD news + macro items for *trade_date*, sorted by time.

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

    # Further restrict to the chart window [09:00, 12:00] for the chart arrays.
    # We keep the full day_bars for pm_stats (which still needs earlier premarket bars).
    chart_bars = day_bars[
        (day_bars.index.time >= dtime(9,  0)) &
        (day_bars.index.time <= dtime(12, 0))
    ]

    # Build parallel lists for Chart.js: x-axis labels + OHLC/volume arrays.
    chart_labels = [ts.strftime("%H:%M") for ts in chart_bars.index]
    chart_open = [
        round(float(p), 2) if np.isfinite(p) else None
        for p in chart_bars["open"]
    ]
    chart_high = [
        round(float(p), 2) if np.isfinite(p) else None
        for p in chart_bars["high"]
    ]
    chart_low = [
        round(float(p), 2) if np.isfinite(p) else None
        for p in chart_bars["low"]
    ]
    chart_close = [
        round(float(p), 2) if np.isfinite(p) else None
        for p in chart_bars["close"]
    ]
    chart_volume = [
        int(v) if np.isfinite(v) else 0
        for v in chart_bars["volume"]
    ]

    # ── prior close ──────────────────────────────────────────────────────────
    prev_close = _prior_close(trade_date)           # float or None

    # ── premarket stats ──────────────────────────────────────────────────────
    pm = _pm_stats(day_bars, prev_close)

    # ── Combined news + macro events ──────────────────────────────────────────
    events = _events_for_day(trade_date)

    return {
        "date":        date_str,
        "chart": {
            "labels":  chart_labels,    # ["09:00", "09:01", …, "12:00"]
            "open":    chart_open,
            "high":    chart_high,
            "low":     chart_low,
            "close":   chart_close,
            "volume":  chart_volume,    # bar volume [12345, 15002, …]
        },
        "prior_close": round(prev_close, 2) if prev_close is not None else None,
        "pm_stats":    pm,              # gap_pct, direction, momentum_*, reversal_flag
        "ff_events":   events,          # list of {time, event, impact, actual, …}
    }


# ---------------------------------------------------------------------------
# Step 3 — HTTP request handler
# ---------------------------------------------------------------------------
# Python's built-in BaseHTTPRequestHandler handles one request at a time.
# We override do_GET() to route three URL patterns:
#
#   GET /              → serve the single-page HTML app (defined in Step 4)
#   GET /api/dates     → return JSON array of available trading dates
#   GET /api/day?date= → return JSON payload for one trading day
#
# All other paths get a plain 404 response.

# HTML_PAGE is a module-level string holding the full UI.
# It is defined in Steps 4 & 5; we forward-reference it here as a global.
# Python resolves globals at call-time (not at class-definition time), so
# the handler will find HTML_PAGE even though it is defined further down.

class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the QQQ Intraday Dashboard."""

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def do_GET(self):
        """
        Entry point for every incoming GET request.

        urlparse splits the raw URL (e.g. "/api/day?date=2026-02-10") into:
            parsed.path  → "/api/day"
            parsed.query → "date=2026-02-10"
        parse_qs turns the query string into a dict of lists:
            {"date": ["2026-02-10"]}
        We then dispatch to one of three private methods based on the path.
        """
        parsed = urlparse(self.path)          # break URL into components
        path   = parsed.path                  # e.g. "/", "/api/dates", "/api/day"
        params = parse_qs(parsed.query)       # e.g. {"date": ["2026-02-10"]}

        if path == "/":
            # Root path → serve the HTML dashboard page
            self._serve_html()

        elif path == "/api/dates":
            # Returns the list of available trading dates as JSON
            self._serve_dates()

        elif path == "/api/day":
            # Returns chart data + stats for a specific date
            # The date comes from the "?date=YYYY-MM-DD" query parameter
            date_str = params.get("date", [None])[0]   # first value or None
            self._serve_day(date_str)

        else:
            # Unknown path — return 404 with a plain-text body
            self._send_json({"error": f"Unknown path: {path}"}, status=404)

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    def _send_json(self, payload: dict | list, status: int = 200):
        """
        Serialise *payload* to JSON and send it as an HTTP response.

        Parameters
        ----------
        payload : dict or list  — any JSON-serialisable Python object
        status  : int           — HTTP status code (200 OK, 400 Bad Request, etc.)

        The response includes:
          • status line   (e.g. "HTTP/1.1 200 OK")
          • Content-Type  header → "application/json"
          • Content-Length header → exact byte count (required by HTTP/1.1)
          • CORS header   → allows the page to call the API from any origin
            (useful if the user opens the HTML file directly from disk)
          • body          → UTF-8 encoded JSON bytes
        """
        body = json.dumps(payload).encode("utf-8")   # dict → JSON string → bytes

        self.send_response(status)                            # write status line
        self.send_header("Content-Type",   "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))   # byte count, not char count
        self.send_header("Access-Control-Allow-Origin", "*") # CORS: allow all origins
        self.end_headers()                                    # blank line after headers
        self.wfile.write(body)                                # send the JSON body

    def _send_html(self, html: str, status: int = 200):
        """
        Send *html* as an HTTP/HTML response.

        Parameters
        ----------
        html   : str — the complete HTML document as a Python string
        status : int — HTTP status code (normally 200)
        """
        body = html.encode("utf-8")                          # string → UTF-8 bytes

        self.send_response(status)
        self.send_header("Content-Type",   "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------
    # Route handlers
    # ------------------------------------------------------------------

    def _serve_html(self):
        """
        Serve the dashboard HTML page.

        HTML_PAGE is a module-level string defined in Steps 4 & 5.
        Python looks up globals at call time, so even though DashboardHandler
        is defined before HTML_PAGE, this method will find it when called.
        """
        self._send_html(HTML_PAGE)

    def _serve_dates(self):
        """
        Respond to GET /api/dates with a JSON array of available date strings.

        Example response body:
            ["2026-02-06", "2026-02-07", ..., "2026-02-27"]
        """
        dates = get_available_dates()   # list[str] from Step 2
        self._send_json(dates)

    def _serve_day(self, date_str: str | None):
        """
        Respond to GET /api/day?date=YYYY-MM-DD with a JSON payload.

        If the 'date' query parameter is missing, return 400 Bad Request.
        If get_day_data() returns an "error" key, forward it as 400.
        Otherwise return 200 with the full day payload.

        Parameters
        ----------
        date_str : str or None — value of the 'date' query parameter
        """
        if date_str is None:
            # Caller forgot to include ?date=… in the URL
            self._send_json({"error": "Missing required query param: date"}, status=400)
            return

        payload = get_day_data(date_str)   # dict from Step 2

        if "error" in payload:
            # get_day_data signals user errors via an "error" key rather than
            # raising exceptions, so we can forward a meaningful 400 response.
            self._send_json(payload, status=400)
        else:
            self._send_json(payload, status=200)

    # ------------------------------------------------------------------
    # Silence the default request logging
    # ------------------------------------------------------------------

    def log_message(self, fmt, *args):
        """
        Override BaseHTTPRequestHandler.log_message to produce cleaner output.

        The default implementation prints every request to stderr in Apache
        Combined Log Format.  We replace it with a compact one-liner that
        shows method, path, and status — easier to read in a terminal.
        """
        # self.command → "GET", self.path → "/api/day?date=…"
        # args[1] → status code string e.g. "200"
        print(f"  {self.command} {self.path}  →  {args[1]}", flush=True)


# ---------------------------------------------------------------------------
# Steps 4 & 5 — Single-page HTML application
# ---------------------------------------------------------------------------
# The entire UI is one Python string.  The server sends it verbatim for GET /.
# Keeping everything in one file means zero extra assets to manage.
#
# Structure of HTML_PAGE:
#   <head>  — charset, viewport, Chart.js CDN script tag, <style> block
#   <body>  — two-column flex layout:
#               #sidebar  (left  ~300 px) — date picker + info cards
#               #main     (right, flex-1) — Chart.js canvas
#   <script> — all JavaScript (Step 5)
#
# CSS conventions used throughout:
#   --bg        darkest surface (page background)
#   --surface   card / panel background
#   --border    subtle dividing lines
#   --text      primary text colour
#   --muted     secondary / label text
#   --green     positive values (gap up, accelerating)
#   --red       negative values (gap down, decelerating)
#   --yellow    caution (reversal flag, medium impact)
#   --blue      neutral highlights (prior close line, W2 annotation)

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <!-- viewport: tell mobile browsers not to zoom out — keeps layout readable -->
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>QQQ Intraday Dashboard</title>

  <!--
    Chart.js v4 from jsDelivr CDN.
    Chart.js draws the 1-minute price line, prior-close annotation, and session
    boundary lines entirely on an HTML5 <canvas> element — no SVG, no D3.
    The chartjs-plugin-annotation plugin adds the vertical/horizontal lines.
  -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>

  <style>
    /* ── CSS custom properties (variables) ──────────────────────────────── */
    :root {
      --bg:      #0d1117;   /* page background — near-black */
      --surface: #161b22;   /* sidebar + card background */
      --card:    #1c2128;   /* inner card / table row background */
      --border:  #30363d;   /* dividing lines */
      --text:    #e6edf3;   /* primary text */
      --muted:   #8b949e;   /* labels, secondary info */
      --green:   #3fb950;   /* positive: gap up, accelerating */
      --red:     #f85149;   /* negative: gap down, decelerating */
      --yellow:  #d29922;   /* caution: reversal flag, medium-impact events */
      --blue:    #58a6ff;   /* neutral: prior-close line colour */
      --purple:  #bc8cff;   /* W2 annotation colour */
    }

    /* ── Reset & base ───────────────────────────────────────────────────── */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: ui-monospace, "SFMono-Regular", "Cascadia Code",
                   "Roboto Mono", Menlo, monospace;
      /* monospace font gives the dashboard a Bloomberg-terminal feel and
         makes numbers align neatly in the stats cards */
      font-size: 13px;
      background: var(--bg);
      color: var(--text);
      height: 100vh;         /* fill the full viewport height */
      display: flex;         /* top-level flex so sidebar + main share the row */
      overflow: hidden;      /* prevent scroll on the body; each panel scrolls independently */
    }

    /* ── Sidebar (left panel) ───────────────────────────────────────────── */
    #sidebar {
      width: 300px;          /* fixed width; chart takes all remaining space */
      min-width: 300px;      /* prevent squashing on narrow viewports */
      background: var(--surface);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column; /* stack children vertically */
      overflow-y: auto;       /* scroll if content overflows vertically */
      padding: 0 0 16px 0;
    }

    /* ── Sidebar header ─────────────────────────────────────────────────── */
    #sidebar-header {
      padding: 16px 14px 12px;
      border-bottom: 1px solid var(--border);
    }
    #sidebar-header h1 {
      font-size: 14px;
      font-weight: 700;
      letter-spacing: 0.04em;
      color: var(--text);
    }
    #sidebar-header p {
      font-size: 11px;
      color: var(--muted);
      margin-top: 3px;
    }

    /* ── Date picker section ────────────────────────────────────────────── */
    .section {
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
    }
    .section-label {
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 6px;
    }

    /* The <select> element for choosing the trading date */
    #date-select {
      width: 100%;
      background: var(--card);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 6px 8px;
      font-family: inherit;
      font-size: 13px;
      cursor: pointer;
      outline: none;
      appearance: none;              /* hide native arrow */
      /* custom dropdown arrow using a base64-encoded SVG chevron */
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%238b949e' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 8px center;
      padding-right: 28px;
    }
    #date-select:focus { border-color: var(--blue); }

    /* ── Stat cards ─────────────────────────────────────────────────────── */
    /* Each card holds one group of related stats (prior close, PM stats) */
    .stat-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 10px 12px;
      margin-top: 8px;      /* space between cards inside a .section */
    }
    /* First card in a section has no top margin */
    .stat-card:first-child { margin-top: 0; }

    /* ── Individual stat rows inside a card ─────────────────────────────── */
    .stat-row {
      display: flex;
      justify-content: space-between;  /* label left, value right */
      align-items: baseline;
      padding: 3px 0;
    }
    .stat-row + .stat-row {
      border-top: 1px solid var(--border); /* thin divider between rows */
      margin-top: 3px;
      padding-top: 6px;
    }
    .stat-label {
      color: var(--muted);
      font-size: 11px;
    }
    .stat-value {
      font-size: 13px;
      font-weight: 600;
      text-align: right;
    }

    /* Colour helpers applied via JavaScript to .stat-value elements */
    .pos  { color: var(--green);  }   /* positive numbers */
    .neg  { color: var(--red);    }   /* negative numbers */
    .warn { color: var(--yellow); }   /* caution / flag */
    .neu  { color: var(--muted);  }   /* neutral / zero */
    .hi   { color: var(--blue);   }   /* highlighted neutral */

    /* ── Big prior-close number ─────────────────────────────────────────── */
    .prior-close-value {
      font-size: 22px;
      font-weight: 700;
      color: var(--blue);
      display: block;
      margin-top: 4px;
    }

    /* ── Loading / error placeholder text ───────────────────────────────── */
    .placeholder {
      color: var(--muted);
      font-size: 12px;
      font-style: italic;
    }

    /* ── ForexFactory events table ──────────────────────────────────────── */
    #events-section { flex: 1; }   /* take remaining sidebar height */

    .events-table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 6px;
      font-size: 11px;
    }
    .events-table th {
      color: var(--muted);
      text-align: left;
      font-weight: 600;
      padding: 3px 4px;
      border-bottom: 1px solid var(--border);
    }
    .events-table td {
      padding: 5px 4px;
      vertical-align: top;
      border-bottom: 1px solid var(--border);
      color: var(--text);
    }
    .events-table tr:last-child td { border-bottom: none; }

    /* Impact badge — a small coloured dot before the event name */
    .badge {
      display: inline-block;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      margin-right: 5px;
      vertical-align: middle;
      flex-shrink: 0;
    }
    .badge-high   { background: var(--red);    }
    .badge-medium { background: var(--yellow); }
    .badge-low    { background: var(--muted);  }

    /* Actual / Forecast / Previous values in the events table */
    .afp {
      color: var(--muted);
      font-size: 10px;
      margin-top: 2px;
    }
    .afp .actual { color: var(--text); font-weight: 600; }

    /* ── Main chart area (right panel) ──────────────────────────────────── */
    #main {
      flex: 1;               /* fill all horizontal space left of the sidebar */
      display: flex;
      flex-direction: column;
      overflow: hidden;
      padding: 16px;
      gap: 12px;
    }

    /* Chart title bar */
    #chart-header {
      display: flex;
      align-items: baseline;
      gap: 12px;
    }
    #chart-title {
      font-size: 16px;
      font-weight: 700;
      color: var(--text);
    }
    #chart-subtitle {
      font-size: 12px;
      color: var(--muted);
    }

    /* The canvas element fills all remaining vertical space in #main */
    #chart-wrap {
      flex: 1;               /* grow to fill remaining height */
      position: relative;    /* Chart.js needs a positioned parent to measure size */
      min-height: 0;         /* flex children must have min-height:0 to shrink */
    }
    #price-chart {
      width:  100% !important;   /* override Chart.js inline style */
      height: 100% !important;
    }

    /* ── Tooltip override — Chart.js default is adequate; just tweaking colours */
    /* (Chart.js tooltip colours are set in JS options, not CSS) */

    /* ── Responsive: if viewport < 700 px, stack panels vertically ──────── */
    @media (max-width: 700px) {
      body          { flex-direction: column; height: auto; overflow: auto; }
      #sidebar      { width: 100%; min-width: unset; border-right: none;
                      border-bottom: 1px solid var(--border); }
      #chart-wrap   { height: 55vw; min-height: 260px; }
    }
  </style>
</head>

<body>

  <!-- ═══════════════════════════════════════════════════════════════════
       LEFT SIDEBAR
       ═══════════════════════════════════════════════════════════════════ -->
  <aside id="sidebar">

    <!-- Dashboard title -->
    <div id="sidebar-header">
      <h1>QQQ Intraday</h1>
      <p>8:00 – 11:00 AM ET &nbsp;·&nbsp; 1-min bars</p>
    </div>

    <!-- ── Date picker ─────────────────────────────────────────────────── -->
    <div class="section">
      <div class="section-label">Trading Date</div>
      <!--
        The <select> is populated by JavaScript (loadDates()) with one
        <option> per available trading day.  Changing the selection triggers
        loadDay() which fetches /api/day?date=… and refreshes all panels.
      -->
      <select id="date-select">
        <option value="">Loading dates…</option>
      </select>
    </div>

    <!-- ── Prior close card ────────────────────────────────────────────── -->
    <div class="section">
      <div class="section-label">Prior Session Close</div>
      <div class="stat-card">
        <!--
          prior-close-value is a large blue number updated by JS.
          The horizontal dashed line on the chart sits at this price.
        -->
        <span id="prior-close-value" class="prior-close-value placeholder">—</span>
      </div>
    </div>

    <!-- ── Premarket stats card ─────────────────────────────────────────── -->
    <div class="section">
      <div class="section-label">Premarket Stats <span style="color:var(--muted);font-size:10px">(8:00–9:29 ET)</span></div>
      <div class="stat-card">

        <!-- Gap % vs prior close -->
        <div class="stat-row">
          <span class="stat-label">Gap vs prior close</span>
          <span id="pm-gap"       class="stat-value placeholder">—</span>
        </div>

        <!-- Direction: +1 / -1 / 0 rendered as arrow + text -->
        <div class="stat-row">
          <span class="stat-label">PM direction</span>
          <span id="pm-direction" class="stat-value placeholder">—</span>
        </div>

        <!-- Momentum score: late-PM / early-PM move ratio -->
        <div class="stat-row">
          <span class="stat-label">Momentum score</span>
          <span id="pm-momentum"  class="stat-value placeholder">—</span>
        </div>

        <!-- Momentum acceleration: +1 accelerating / -1 decelerating -->
        <div class="stat-row">
          <span class="stat-label">Momentum accel</span>
          <span id="pm-accel"     class="stat-value placeholder">—</span>
        </div>

        <!-- Reversal flag: 1 = direction flipped 8:59→9:29 -->
        <div class="stat-row">
          <span class="stat-label">Reversal flag</span>
          <span id="pm-reversal"  class="stat-value placeholder">—</span>
        </div>

      </div><!-- /.stat-card -->
    </div><!-- /.section -->

    <!-- ── ForexFactory events ─────────────────────────────────────────── -->
    <div class="section" id="events-section">
      <div class="section-label">Daily Brief <span style="color:var(--muted);font-size:10px">(max 5 news + 2 macro)</span></div>
      <!--
        #events-body is a <tbody> populated by JS with one <tr> per event.
        If there are no events, a single "No USD events" row is inserted.
      -->
      <table class="events-table">
        <thead>
          <tr>
            <th style="width:36px">Time</th>
            <th>Event</th>
            <th style="width:50px;text-align:right">Details</th>
          </tr>
        </thead>
        <tbody id="events-body">
          <tr><td colspan="3" class="placeholder">Loading…</td></tr>
        </tbody>
      </table>
    </div><!-- /.section -->

  </aside><!-- /#sidebar -->


  <!-- ═══════════════════════════════════════════════════════════════════
       RIGHT PANEL — chart (Step 5 fills this with Chart.js logic)
       ═══════════════════════════════════════════════════════════════════ -->
  <main id="main">

    <div id="chart-header">
      <!--
        #chart-title  updated by JS to show the selected date
        #chart-subtitle shows the session boundaries as a reminder
      -->
      <span id="chart-title">QQQ</span>
      <span id="chart-subtitle">Select a date to load the chart</span>
    </div>

    <div id="chart-wrap">
      <!--
        The <canvas> is where Chart.js renders the line chart.
        Width/height are set to 100% via CSS; Chart.js reads the parent
        div's pixel dimensions at render time.
      -->
      <canvas id="price-chart"></canvas>
    </div>

  </main><!-- /#main -->


  <script>
  // =========================================================================
  // Step 5 — Dashboard JavaScript
  // =========================================================================
  // Execution flow:
  //   1. loadDates()  — page load — fetches /api/dates, populates dropdown,
  //                     auto-loads the most recent date
  //   2. loadDay(d)   — on date change — fetches /api/day?date=d, calls the
  //                     three render functions below
  //   3. updateHeader / updateSidebar / updateChart — each owns one panel
  //
  // The only global mutable state is `chartInstance` (one Chart.js object).
  'use strict';

  // ── DOM element references ─────────────────────────────────────────────────
  // Cached once at startup; avoids repeated getElementById lookups in hot paths.
  const selEl      = document.getElementById('date-select');        // date dropdown
  const priorEl    = document.getElementById('prior-close-value');  // large blue $
  const gapEl      = document.getElementById('pm-gap');             // gap %
  const dirEl      = document.getElementById('pm-direction');       // ↑/↓ direction
  const momEl      = document.getElementById('pm-momentum');        // momentum score
  const accelEl    = document.getElementById('pm-accel');           // accel label
  const reversalEl = document.getElementById('pm-reversal');        // reversal flag
  const evBodyEl   = document.getElementById('events-body');        // events <tbody>
  const titleEl    = document.getElementById('chart-title');        // "QQQ — date"
  const subtitleEl = document.getElementById('chart-subtitle');     // bar count
  const canvasEl   = document.getElementById('price-chart');        // Chart.js canvas

  // ── Single Chart.js instance ───────────────────────────────────────────────
  // Kept at module scope so updateChart() can call .destroy() before recreating.
  // Without destroy() a second chart on the same canvas throws an error.
  let chartInstance = null;

  // ── Colour palette (must match CSS :root custom properties) ───────────────
  // Chart.js options live in JS, not CSS, so we pass hex values explicitly.
  const C = {
    text:    '#e6edf3',   // --text
    muted:   '#8b949e',   // --muted
    border:  '#30363d',   // --border
    green:   '#3fb950',   // --green  (positive / market open)
    red:     '#f85149',   // --red    (negative)
    yellow:  '#d29922',   // --yellow (caution / reversal)
    blue:    '#58a6ff',   // --blue   (price line / prior close)
    purple:  '#bc8cff',   // --purple (W2 annotation)
    surface: '#161b22',   // --surface (tooltip background)
  };

  // =========================================================================
  // loadDates() — called once when the page finishes loading
  // =========================================================================
  async function loadDates() {
    // async/await: 'await' pauses execution until the fetch Promise resolves,
    // then continues with the resolved value.  Errors fall into the catch block.
    try {
      const resp  = await fetch('/api/dates');    // GET /api/dates
      const dates = await resp.json();            // JSON array of "YYYY-MM-DD" strings

      if (!Array.isArray(dates) || dates.length === 0) {
        // Server returned empty array — no intraday data in the CSV
        selEl.innerHTML = '<option value="">No data available</option>';
        subtitleEl.textContent = 'No intraday data found. Run data_loader.py first.';
        return;
      }

      // Populate the dropdown.  API returns oldest-first; we reverse so the
      // most recent date is at the top and selected by default.
      selEl.innerHTML = dates
        .slice()                                   // copy — don't mutate the API array
        .reverse()                                 // newest first
        .map(d => `<option value="${d}">${d}</option>`)  // one <option> per date
        .join('');                                 // join into one HTML string

      // Auto-load the most recent date (last element before reversing)
      await loadDay(dates[dates.length - 1]);

    } catch (err) {
      // Network failure or JSON parse error
      subtitleEl.textContent = 'Error loading dates: ' + err.message;
    }
  }

  // =========================================================================
  // loadDay(dateStr) — fetch one day's data and render all three panels
  // =========================================================================
  async function loadDay(dateStr) {
    if (!dateStr) return;   // guard: empty string when no option is selected

    subtitleEl.textContent = 'Loading ' + dateStr + '\u2026';  // "Loading 2026-02-10…"

    try {
      const resp = await fetch('/api/day?date=' + dateStr);
      const data = await resp.json();

      if (data.error) {
        // API returned a structured error (400 response with {error: "..."})
        subtitleEl.textContent = 'Error: ' + data.error;
        return;
      }

      // Sync the dropdown value in case loadDay was called programmatically
      selEl.value = dateStr;

      // Render each panel with the fresh data
      updateHeader(data);     // chart title bar
      updateSidebar(data);    // prior close + PM stats + events table
      updateChart(data);      // Chart.js line chart

    } catch (err) {
      subtitleEl.textContent = 'Fetch error: ' + err.message;
    }
  }

  // =========================================================================
  // updateHeader(data) — set the chart title and bar-count subtitle
  // =========================================================================
  function updateHeader(data) {
    titleEl.textContent = 'QQQ \u2014 ' + data.date;   // em-dash: "QQQ — 2026-02-10"
    const n = data.chart.labels.length;                 // number of 1-min bars
    subtitleEl.textContent =
      n + ' bars \u00b7 8:00\u2013 11:00 AM ET';        // middle dot · and en-dash –
  }

  // =========================================================================
  // updateSidebar(data) — fill prior-close card, PM stats card, events table
  // =========================================================================
  function updateSidebar(data) {
    const pc = data.prior_close;   // float | null
    const pm = data.pm_stats;      // {gap_pct, direction, momentum_score, …}

    // ── Prior close ──────────────────────────────────────────────────────────
    if (pc !== null && pc !== undefined) {
      priorEl.textContent = '$' + pc.toFixed(2);          // "$609.65"
      priorEl.className   = 'prior-close-value hi';       // blue, non-placeholder
    } else {
      priorEl.textContent = '\u2014';                     // em-dash —
      priorEl.className   = 'prior-close-value placeholder';
    }

    // ── Gap % ─────────────────────────────────────────────────────────────────
    // Prepend '+' for positive gaps so "+0.75%" and "-1.55%" align visually.
    const gap     = pm.gap_pct;
    const gapSign = gap > 0 ? '+' : '';
    setVal(gapEl,
      gapSign + gap.toFixed(2) + '%',
      gap > 0 ? 'pos' : gap < 0 ? 'neg' : 'neu');

    // ── PM direction ──────────────────────────────────────────────────────────
    // Map integer +1 / -1 / 0 to an arrow + text + colour class.
    const dirMap = {
       '1': { text: '\u2191 Gap Up',    cls: 'pos' },   // ↑ green
      '-1': { text: '\u2193 Gap Down',  cls: 'neg' },   // ↓ red
       '0': { text: '\u2014 Flat',      cls: 'neu' },   // — muted
    };
    const dirEntry = dirMap[String(pm.direction)] || dirMap['0'];
    setVal(dirEl, dirEntry.text, dirEntry.cls);

    // ── Momentum score ────────────────────────────────────────────────────────
    // Ratio of late-PM to early-PM move; can be any real number.
    const ms = pm.momentum_score;
    setVal(momEl,
      (ms > 0 ? '+' : '') + ms.toFixed(2),
      ms > 0 ? 'pos' : ms < 0 ? 'neg' : 'neu');

    // ── Momentum acceleration ─────────────────────────────────────────────────
    const accelMap = {
       '1': { text: 'Accelerating',  cls: 'pos' },
      '-1': { text: 'Decelerating',  cls: 'neg' },
       '0': { text: '\u2014',        cls: 'neu' },
    };
    const accelEntry = accelMap[String(pm.momentum_accel)] || accelMap['0'];
    setVal(accelEl, accelEntry.text, accelEntry.cls);

    // ── Reversal flag ─────────────────────────────────────────────────────────
    // 1 = direction flipped between 8:59 and 9:29 → show warning in yellow
    if (pm.reversal_flag === 1) {
      setVal(reversalEl, '\u26a0 Yes', 'warn');    // ⚠ yellow
    } else {
      setVal(reversalEl, 'No', 'neu');
    }

    // ── Events table ──────────────────────────────────────────────────────────
    renderEvents(data.ff_events);
  }

  // ── Helper: set .textContent and colour class on a .stat-value element ─────
  function setVal(el, text, colorClass) {
    el.textContent = text;
    el.className   = 'stat-value ' + colorClass;  // e.g. "stat-value pos"
  }

  // ── Helper: map FF impact string → badge CSS class ──────────────────────────
  function badgeClass(impact) {
    const lower = (impact || '').toLowerCase();
    if (lower.includes('high'))   return 'badge-high';    // red dot
    if (lower.includes('medium')) return 'badge-medium';  // yellow dot
    return 'badge-low';                                   // grey dot
  }

  // ── Helper: HTML-escape user-visible strings (prevents XSS) ─────────────────
  // Event names from external sources could theoretically
  // contain < > & " characters that would break the HTML or allow injection.
  function esc(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g,  '&amp;')
      .replace(/</g,  '&lt;')
      .replace(/>/g,  '&gt;')
      .replace(/"/g,  '&quot;');
  }

  // ── renderEvents(events) — build event table rows ───────────────────────────
  function renderEvents(events) {
    if (!events || events.length === 0) {
      evBodyEl.innerHTML =
        '<tr><td colspan="3" class="placeholder">No news or macro items this day</td></tr>';
      return;
    }

    evBodyEl.innerHTML = events.map(ev => {
      const bc = badgeClass(ev.impact);   // CSS class for the coloured dot

      // Actual / Forecast / Previous sub-line, shown only when data is present
      const afpHtml = (ev.actual || ev.forecast)
        ? `<div class="afp">` +
            `<span class="actual">${esc(ev.actual) || '\u2014'}</span>` +
            ` / ${esc(ev.forecast) || '\u2014'}` +
            (ev.previous
              ? ` <span style="color:#555">prev ${esc(ev.previous)}</span>`
              : '') +
          `</div>`
        : '';

      return `<tr>
        <td style="color:var(--muted);font-size:10px;white-space:nowrap">
          ${esc(ev.time)}
        </td>
        <td>
          <span class="badge ${bc}"></span>${esc(ev.event)}${afpHtml}
        </td>
        <td style="text-align:right;font-size:10px;white-space:nowrap">
          ${ev.actual
            ? `<span style="color:var(--text);font-weight:600">${esc(ev.actual)}</span>`
            : ''}
          ${ev.forecast
            ? `<span style="color:var(--muted)">/ ${esc(ev.forecast)}</span>`
            : ''}
        </td>
      </tr>`;
    }).join('');
  }

  // =========================================================================
  // updateChart(data) — destroy old chart, build new Chart.js instance
  // =========================================================================
  function updateChart(data) {
    // Always destroy before creating — Chart.js keeps an internal canvas ref.
    if (chartInstance) {
      chartInstance.destroy();
      chartInstance = null;
    }

    const labels = data.chart.labels;   // ["08:00", "08:01", … "11:00"]
    const prices = data.chart.prices;   // [596.02, 596.10, …]  (null = missing bar)
    const pc     = data.prior_close;    // float | null

    // ── Annotations: vertical session lines + horizontal prior-close line ────
    const annotations = {};

    // Vertical dashed line at 09:30 — official market open / W1 start.
    // scaleID:'x' targets the category axis; value must match a label string exactly.
    annotations.openLine = {
      type:        'line',
      scaleID:     'x',
      value:       '09:30',        // label string that marks the open
      borderColor: C.green,
      borderWidth: 1,
      borderDash:  [4, 4],         // 4 px on, 4 px off
      label: {
        display:         true,
        content:         'Open 9:30',
        color:           C.green,
        font:            { size: 10, family: 'ui-monospace, monospace' },
        position:        'start',  // label at the top of the canvas
        yAdjust:         -6,       // nudge upward to clear the price line
        backgroundColor: 'transparent',
        borderWidth:     0,
      },
    };

    // Vertical dashed line at 10:00 — W2 window start.
    annotations.w2Line = {
      type:        'line',
      scaleID:     'x',
      value:       '10:00',
      borderColor: C.purple,
      borderWidth: 1,
      borderDash:  [4, 4],
      label: {
        display:         true,
        content:         'W2 10:00',
        color:           C.purple,
        font:            { size: 10, family: 'ui-monospace, monospace' },
        position:        'start',
        yAdjust:         -6,
        backgroundColor: 'transparent',
        borderWidth:     0,
      },
    };

    // Horizontal dashed line at the prior-session closing price.
    // Only added when a valid prior close exists (null on the very first date).
    if (pc !== null && pc !== undefined) {
      annotations.priorCloseLine = {
        type:        'line',
        scaleID:     'y',          // targets the price (y) axis
        value:       pc,           // price level for the horizontal line
        borderColor: C.blue,
        borderWidth: 1,
        borderDash:  [6, 3],       // longer dash than session lines
        label: {
          display:         true,
          content:         'Prev $' + pc.toFixed(2),
          color:           C.blue,
          font:            { size: 10, family: 'ui-monospace, monospace' },
          position:        'end',  // right side of the canvas
          xAdjust:         -4,     // nudge inward from the right edge
          yAdjust:         -8,     // nudge above the line to avoid overlap
          backgroundColor: 'transparent',
          borderWidth:     0,
        },
      };
    }

    // ── Chart.js configuration object ────────────────────────────────────────
    chartInstance = new Chart(canvasEl, {
      type: 'line',
      data: {
        labels:   labels,           // x-axis: time strings
        datasets: [{
          label:            'QQQ close',
          data:             prices,  // y-axis: price floats
          borderColor:      C.blue,  // blue price line
          borderWidth:      1.5,     // thin but readable
          pointRadius:      0,       // hide dots — 181 points would be cluttered
          pointHoverRadius: 4,       // but show one on hover for the tooltip
          tension:          0,       // straight segments between points
          spanGaps:         true,    // connect across null (missing 1-min bars)
          fill:             false,   // no shaded area under the line
        }],
      },

      options: {
        responsive:          true,    // resize when the container resizes
        maintainAspectRatio: false,   // height is controlled by CSS flex, not ratio

        animation: {
          duration: 200,             // fast fade-in when switching dates
        },

        layout: {
          // Top padding reserves visual space for annotation labels that appear
          // above the top edge of the plot area.
          padding: { top: 28, right: 20, bottom: 8, left: 8 },
        },

        interaction: {
          mode:      'index',        // show tooltip at the closest x-index
          intersect: false,          // fire tooltip even when not on a point
          axis:      'x',
        },

        plugins: {
          legend: { display: false },   // single dataset — legend is redundant

          tooltip: {
            backgroundColor: C.surface,
            titleColor:      C.muted,
            bodyColor:       C.text,
            borderColor:     C.border,
            borderWidth:     1,
            padding:         8,
            titleFont: { family: 'ui-monospace, monospace', size: 11 },
            bodyFont:  { family: 'ui-monospace, monospace', size: 12 },
            callbacks: {
              title: items => items[0].label,                    // "09:31"
              label: item  => ' $' + item.parsed.y.toFixed(2),  // " $481.73"
            },
          },

          // Pass annotation definitions to the plugin
          annotation: { annotations },
        },

        scales: {
          // X-axis: category scale (string labels)
          x: {
            ticks: {
              color:       C.muted,
              maxRotation: 0,      // keep labels horizontal
              font:        { family: 'ui-monospace, monospace', size: 10 },
              // Show a tick label only on exact :00 and :30 minute marks to
              // avoid crowding 181 labels onto the axis.
              callback: function(value, index) {
                const lbl = this.getLabelForValue(index);
                return (lbl && (lbl.endsWith(':00') || lbl.endsWith(':30')))
                  ? lbl : '';
              },
            },
            grid: { color: C.border },
          },

          // Y-axis: price scale, displayed on the right side (Bloomberg style)
          y: {
            position: 'right',
            ticks: {
              color:    C.muted,
              font:     { family: 'ui-monospace, monospace', size: 10 },
              callback: v => '$' + v.toFixed(0),  // "$480", "$490", …
            },
            grid: { color: C.border },
          },
        },
      },
    });
  }

  // =========================================================================
  // Initialise on page load
  // =========================================================================
  // loadDates() kicks off the whole chain:
  //   loadDates()
  //     → populates the dropdown
  //     → calls loadDay(mostRecent)
  //         → updateHeader + updateSidebar + updateChart
  loadDates();

  // Wire the dropdown: any change by the user triggers a full re-render
  selEl.addEventListener('change', () => loadDay(selEl.value));
  </script>

</body>
</html>"""


# ---------------------------------------------------------------------------
# Server entry point  (Steps 4 & 5 will keep this unchanged)
# ---------------------------------------------------------------------------

def main():
    """
    Parse command-line arguments, start the HTTP server, and block forever.

    Accepts one optional flag:
        --port INT   override the default port (8765)

    Keyboard interrupt (Ctrl-C) shuts the server down cleanly.
    """
    parser = argparse.ArgumentParser(description="QQQ Intraday Dashboard")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"TCP port to listen on (default: {DEFAULT_PORT})"
    )
    args = parser.parse_args()

    # HTTPServer binds to ("", port) which means "all interfaces" — the
    # dashboard is reachable at http://localhost:<port>/ from the same machine.
    server = HTTPServer(("", args.port), DashboardHandler)

    print(f"QQQ Dashboard running at  http://localhost:{args.port}/", flush=True)
    print("Press Ctrl-C to stop.\n", flush=True)

    try:
        server.serve_forever()      # blocks; handles one request at a time
    except KeyboardInterrupt:
        print("\nShutting down …", flush=True)
    finally:
        server.server_close()       # release the port


# ---------------------------------------------------------------------------
# Smoke-test / entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # If --smoke-test flag present, run the Step 2 validation and exit.
    # Otherwise start the real server via main().
    if "--smoke-test" in sys.argv:
        print("=== Steps 1–3 smoke test ===")
        dates = get_available_dates()
        print(f"Available dates ({len(dates)}): {dates[0]} … {dates[-1]}")
        sample = dates[0]
        data = get_day_data(sample)
        assert "error" not in data, f"get_day_data error: {data['error']}"
        print(f"Date: {data['date']}  prior_close: {data['prior_close']}")
        print(f"PM stats: {data['pm_stats']}")
        print(f"Chart: {len(data['chart']['labels'])} pts  "
              f"({data['chart']['labels'][0]} → {data['chart']['labels'][-1]})")
        print(f"Volume points: {len(data['chart']['volume'])}")
        print(f"FF events: {len(data['ff_events'])}")
        # Verify the handler class is importable and has the right methods
        assert hasattr(DashboardHandler, "do_GET")
        assert hasattr(DashboardHandler, "_serve_dates")
        assert hasattr(DashboardHandler, "_serve_day")
        assert hasattr(DashboardHandler, "_serve_html")
        print("Steps 1–3 OK.")
        sys.exit(0)

    main()
