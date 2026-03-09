"""
data_loader.py — yfinance fetching + CSV caching.

All timestamps are stored/returned in US/Eastern timezone.
"""
# ↑ Docstring explaining what this file does:
#   It downloads price data from Yahoo Finance and saves it to CSV files (local cache).
#   Next time you run the code, it reads from the cached CSV instead of downloading again,
#   which is faster and avoids hitting Yahoo Finance's rate limits.
#   All times are in US/Eastern (New York) timezone, handling daylight saving automatically.

from __future__ import annotations
# ↑ Enables modern type hint evaluation. As a beginner, just ignore this line —
#   it prevents some obscure errors related to type annotation ordering.

import os
# ↑ Imports Python's built-in 'os' module for operating system interactions.
#   Though imported, it's not directly used in the current code — it was kept for potential future use.

from datetime import datetime, timedelta
# ↑ Imports two classes from Python's built-in 'datetime' module:
#   datetime  → represents a specific point in time (date + time together), e.g., 2026-02-06 09:31:00.
#   timedelta → represents a duration (a span of time), e.g., timedelta(days=7) = 7 days.
#   Used together to calculate date ranges, e.g., "7 days ago" = datetime.now() - timedelta(days=7).

from pathlib import Path
# ↑ Imports 'Path' from Python's built-in 'pathlib' module.
#   Path is a modern, cross-platform way to work with file paths.
#   Example: Path("data") / "qqq_1m.csv" builds the path "data/qqq_1m.csv" safely on any OS.
#   Much better than string concatenation like "data" + "/" + "qqq_1m.csv".

import pandas as pd
# ↑ Pandas library for working with tabular data (DataFrames).

import pytz
# ↑ Imports the 'pytz' library (not built-in, must be installed with pip).
#   pytz provides timezone objects for working with time zones correctly,
#   including daylight saving time (DST) transitions.
#   Example: pytz.timezone("America/New_York") gives us the Eastern timezone.

import yfinance as yf
# ↑ Imports the 'yfinance' library (Yahoo Finance), aliased as 'yf'.
#   yfinance is a third-party library (installed via pip) that lets you download
#   stock price data from Yahoo Finance for free.
#   Example: yf.download("QQQ", period="1mo", interval="1d") downloads 1 month of daily bars.

DATA_DIR = Path(__file__).parent.parent / "data"
# ↑ Builds the path to the project's 'data' folder automatically, no matter where you run the code from.
#   __file__         → the full path of THIS file (data_loader.py), e.g., "/project/src/data_loader.py".
#   Path(__file__)   → wraps it as a Path object so we can use / to navigate.
#   .parent          → goes up one level: "/project/src/" → "/project/".
#   .parent again    → goes up another level (not needed here but harmless since src's parent IS project).
#   Wait — actually: Path(__file__) = /project/src/data_loader.py
#                    .parent = /project/src/
#                    .parent.parent = /project/
#   / "data"         → appends "data" to get "/project/data".
#   Result: DATA_DIR always points to the 'data' folder inside your project.

DATA_DIR.mkdir(exist_ok=True)
# ↑ Creates the 'data' directory if it doesn't exist yet.
#   .mkdir()        → makes the directory.
#   exist_ok=True   → don't raise an error if it already exists. Without this, Python would crash
#                     with "FileExistsError" if you run the code a second time.

INTRADAY_CSV = DATA_DIR / "qqq_1m.csv"
# ↑ Full path to the 1-minute intraday bar cache file: "/project/data/qqq_1m.csv".
#   The / operator on Path objects concatenates path segments (like os.path.join).

DAILY_CSV = DATA_DIR / "qqq_daily.csv"
# ↑ Full path to the daily bar cache file: "/project/data/qqq_daily.csv".

FF_CSV = DATA_DIR / "ff_events.csv"
# ↑ Full path to the ForexFactory events cache file: "/project/data/ff_events.csv".

EASTERN = pytz.timezone("America/New_York")
# ↑ Creates a timezone object for US Eastern time (New York).
#   "America/New_York" is the IANA timezone database name — it automatically handles
#   daylight saving time: EST (UTC-5) in winter, EDT (UTC-4) in summer.

SYMBOL = "QQQ"
# ↑ The stock ticker symbol we're analyzing. QQQ is the Invesco NASDAQ-100 ETF —
#   a fund that tracks the top 100 non-financial companies on the NASDAQ exchange.

# Re-fetch intraday if the cache is older than this many hours
INTRADAY_STALE_HOURS = 4
# ↑ If the cached CSV file is more than 4 hours old, we re-download fresh data.
#   This prevents trading stale data while avoiding unnecessary downloads.


def _to_eastern(df: pd.DataFrame) -> pd.DataFrame:
# ↑ Private helper function that converts a DataFrame's timestamp index to Eastern timezone.
#   Parameter:
#     df: pd.DataFrame → any DataFrame with a DatetimeIndex (timestamps as row labels).
#   -> pd.DataFrame    → returns the same DataFrame with its index converted to Eastern time.
    """Convert a DataFrame with a DatetimeIndex to US/Eastern, dropping timezone."""
    # ↑ Docstring: one-line summary of what this function does.

    idx = df.index
    # ↑ Gets the index (the row labels) of the DataFrame. For price data, these are timestamps.

    if idx.tzinfo is None:
        # ↑ Checks if the index has timezone information.
        #   .tzinfo is None → the timestamps have no timezone attached (they're "naive").
        #   Yahoo Finance sometimes returns naive timestamps — we need to assume they're UTC.
        idx = idx.tz_localize("UTC")
        # ↑ .tz_localize("UTC") attaches the UTC timezone to the naive timestamps.
        #   "Localizing" means: "these timestamps ARE in UTC" (we're declaring their timezone).

    df.index = idx.tz_convert(EASTERN)
    # ↑ Converts the UTC timestamps to Eastern time.
    #   .tz_convert() changes the timezone while keeping the same absolute moment in time.
    #   e.g., "2026-02-06 14:30:00 UTC" becomes "2026-02-06 09:30:00 EST".
    #   We assign back to df.index to replace the old index with the converted one.

    return df
    # ↑ Returns the DataFrame with its index now in Eastern time.


def _is_stale(path: Path, max_age_hours: float) -> bool:
# ↑ Checks whether a file is "stale" — older than the allowed maximum age.
#   Parameters:
#     path: Path          → the file to check (e.g., INTRADAY_CSV).
#     max_age_hours: float → maximum allowed age in hours (e.g., 4.0 for 4 hours).
#   -> bool               → returns True if the file is stale (needs re-download), False if fresh.
    if not path.exists():
        # ↑ path.exists() returns True if the file exists on disk, False if it doesn't.
        #   'not' flips it: if the file does NOT exist, it's definitely "stale" (we need to fetch it).
        return True
        # ↑ Return True: the file doesn't exist, so we need to fetch fresh data.

    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    # ↑ Calculates how old the file is.
    #   path.stat()          → gets file metadata (size, modification time, etc.).
    #   .st_mtime            → the "modification time" as a Unix timestamp (seconds since Jan 1, 1970).
    #   datetime.fromtimestamp(...)  → converts that Unix timestamp to a Python datetime object.
    #   datetime.now()       → the current date and time right now.
    #   datetime.now() - datetime.fromtimestamp(...) → subtracts two datetimes, giving a timedelta.
    #   Result: 'age' is a timedelta like timedelta(hours=5, minutes=32) meaning the file is 5h32m old.

    return age > timedelta(hours=max_age_hours)
    # ↑ Returns True if the file's age exceeds the allowed maximum.
    #   timedelta(hours=max_age_hours) → creates a timedelta for the threshold (e.g., 4 hours).
    #   age > timedelta(hours=4)       → True if file is older than 4 hours, False if younger.


# ---------------------------------------------------------------------------
# Intraday (1-minute bars, ~60-day limit)
# ---------------------------------------------------------------------------
# ↑ Section separator comment. The functions below handle 1-minute price data.

def fetch_intraday(symbol: str = SYMBOL, days: int = 28) -> pd.DataFrame:
# ↑ Downloads 1-minute price bars from Yahoo Finance and saves them to CSV.
#   Parameters:
#     symbol: str = SYMBOL → the ticker symbol (default "QQQ"). '= SYMBOL' means QQQ is the default.
#     days: int = 28       → how many calendar days of data to fetch (default 28 days).
#                            Yahoo Finance limits 1-minute data to the last ~30 calendar days.
#   -> pd.DataFrame        → returns the full intraday DataFrame.
    """
    Fetch 1-minute bars including premarket/afterhours and save to CSV.

    Yahoo Finance limits 1-minute data to the last ~30 calendar days and
    allows only ~7 days per request, so we chunk and concatenate.
    days must be ≤ 29 to stay within the Yahoo Finance 30-day window.
    """
    # ↑ Docstring explaining the Yahoo Finance constraints.

    days = min(days, 29)
    # ↑ Enforces Yahoo Finance's 30-day limit.
    #   min(days, 29) → returns whichever is smaller: the requested days or 29.
    #   If you pass days=60, it becomes 29. If you pass days=14, it stays 14.

    print(f"[data_loader] Fetching {days}d 1m intraday for {symbol} (prepost=True, chunked)…")
    # ↑ Prints a status message to the terminal so you can see progress.
    #   f"..." is an "f-string" (formatted string literal) — curly braces {} are replaced with variable values.
    #   f"Fetching {days}d" → if days=28, this prints "Fetching 28d".

    CHUNK_DAYS = 7
    # ↑ Local constant: Yahoo Finance allows maximum 7 days per single API request for 1-minute data.
    #   We'll break the full date range into 7-day chunks and fetch each one separately.

    end = datetime.now()
    # ↑ Gets the current date and time as a datetime object. This is the end of our date range.

    start = end - timedelta(days=days)
    # ↑ Calculates the start of our date range by going 'days' days back from now.
    #   e.g., if today is 2026-03-07 and days=28, start = 2026-02-07.

    chunks = []
    # ↑ Empty list to collect each downloaded chunk of data.

    chunk_start = start
    # ↑ Initialize the start of the first chunk to the overall start date.

    while chunk_start < end:
        # ↑ A while loop — keeps running as long as chunk_start hasn't reached the overall end.
        #   We advance chunk_start by CHUNK_DAYS each iteration, covering the full date range.

        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), end)
        # ↑ Calculates the end of this chunk.
        #   chunk_start + timedelta(days=7) → 7 days after the chunk start.
        #   min(..., end) → if that 7-day end would exceed our overall end date, cap it at 'end'.
        #   This ensures the last chunk doesn't go beyond "today".

        chunk = yf.download(
            # ↑ Calls Yahoo Finance to download price data.
            symbol,
            # ↑ The ticker symbol to download (e.g., "QQQ").
            start=chunk_start.strftime("%Y-%m-%d"),
            # ↑ Start date formatted as a string. .strftime("%Y-%m-%d") converts a datetime to
            #   a "YYYY-MM-DD" string that Yahoo Finance's API expects. e.g., "2026-02-07".
            end=chunk_end.strftime("%Y-%m-%d"),
            # ↑ End date as a string in the same format.
            interval="1m",
            # ↑ "1m" = 1-minute bars. Other options: "5m", "1h", "1d" etc.
            prepost=True,
            # ↑ True = include pre-market (4:00–9:29 AM) and after-hours (4:00–8:00 PM) data.
            #   We need premarket data to calculate our premarket features.
            progress=False,
            # ↑ False = don't print a download progress bar. Keeps the output clean.
        )

        if not chunk.empty:
            # ↑ chunk.empty → True if Yahoo returned zero rows (e.g., weekend or holiday range).
            #   'not chunk.empty' → True if we actually got data.
            chunks.append(chunk)
            # ↑ Add this chunk's DataFrame to our list of chunks.

        chunk_start = chunk_end
        # ↑ Move the start of the next chunk to where this one ended.
        #   This advances us forward by 7 days each iteration.

    if not chunks:
        # ↑ If the list is still empty after all chunks, Yahoo returned nothing at all.
        raise RuntimeError(f"yfinance returned no data for {symbol} 1m across all chunks")
        # ↑ 'raise' throws an exception — an error that stops the program.
        #   RuntimeError is a built-in Python error type for unexpected runtime failures.
        #   The f-string fills in the symbol name in the error message.

    df = pd.concat(chunks)
    # ↑ pd.concat() concatenates (stacks) all the chunk DataFrames into one big DataFrame.
    #   Like gluing multiple spreadsheet tables together vertically (rows from all chunks combined).

    df = df[~df.index.duplicated(keep="last")]
    # ↑ Removes duplicate rows (same timestamp appearing twice, which can happen at chunk boundaries).
    #   df.index.duplicated() → a True/False list: True where a timestamp is a duplicate.
    #   keep="last"          → when there's a duplicate, keep the LAST occurrence, drop the earlier ones.
    #   ~ (tilde)            → bitwise NOT — flips True to False and vice versa.
    #   df[~...]             → keeps only rows where duplicated is False (i.e., non-duplicates).

    df.sort_index(inplace=True)
    # ↑ Sorts all rows by their timestamp index (oldest first, newest last).
    #   inplace=True → modifies df directly instead of returning a new sorted copy.
    #   Important after concatenation because chunks may not be in perfect order.

    # Flatten multi-level columns if present (yfinance ≥ 0.2.x)
    # ↑ yfinance sometimes returns "MultiIndex" columns (a nested column structure).
    #   e.g., instead of "Close", you get ("Close", "QQQ"). We need to flatten this.
    if isinstance(df.columns, pd.MultiIndex):
        # ↑ isinstance(x, Type) → returns True if x is an instance of Type.
        #   pd.MultiIndex is the class for nested/hierarchical column headers.
        df.columns = [col[0].lower() for col in df.columns]
        # ↑ "List comprehension" — a compact loop that builds a new list.
        #   For each column (which is a tuple like ("Close", "QQQ")):
        #     col[0]   → takes the first element: "Close".
        #     .lower() → converts to lowercase: "close".
        #   Result: columns become ["open", "high", "low", "close", "volume"].
    else:
        df.columns = [c.lower() for c in df.columns]
        # ↑ If columns are already simple (not MultiIndex), just lowercase them.
        #   [c.lower() for c in df.columns] → loops over each column name and lowercases it.

    df = _to_eastern(df)
    # ↑ Converts the timestamp index to Eastern timezone using our helper function above.

    df.index.name = "datetime"
    # ↑ Gives the index a name. This name becomes the column header when we save to CSV.
    #   Without this, the CSV would have an unnamed first column.

    df.to_csv(INTRADAY_CSV)
    # ↑ Saves the DataFrame to a CSV file at the path INTRADAY_CSV.
    #   .to_csv() writes each row as a comma-separated line with headers on the first row.
    #   This is the "cache" — next time we load from this file instead of downloading again.

    print(f"[data_loader] Saved {len(df):,} rows → {INTRADAY_CSV}")
    # ↑ Prints how many rows were saved.
    #   {len(df):,} → len(df) is the row count; :, adds comma separators (e.g., 14,000 not 14000).

    return df
    # ↑ Returns the full intraday DataFrame to the caller.


def load_intraday(force_refresh: bool = False) -> pd.DataFrame:
# ↑ Smart loader: returns cached data if fresh, re-downloads if stale or forced.
#   Parameter:
#     force_refresh: bool = False → if True, always re-download even if cache is fresh.
#   -> pd.DataFrame               → returns the intraday DataFrame.
    """Return cached 1-minute bars, re-fetching if stale."""

    if force_refresh or _is_stale(INTRADAY_CSV, INTRADAY_STALE_HOURS):
        # ↑ Two conditions (either one triggers a re-download):
        #   force_refresh          → caller explicitly asked for fresh data.
        #   _is_stale(...)         → the cached file is older than 4 hours.
        #   'or' means: if EITHER is True, re-download.
        return fetch_intraday()
        # ↑ Download fresh data and return it. fetch_intraday() also saves to CSV.

    df = pd.read_csv(INTRADAY_CSV, index_col="datetime", parse_dates=False)
    # ↑ Reads the cached CSV file into a DataFrame.
    #   index_col="datetime" → makes the "datetime" column the row index (not a regular column).
    #   parse_dates=False    → don't auto-parse dates yet. We'll handle timezone parsing manually below.

    df.columns = [c.lower() for c in df.columns]
    # ↑ Lowercases all column names for consistency (CSV headers might be "Close", "Open", etc.).

    df.index = pd.to_datetime(df.index, utc=True).tz_convert(EASTERN)
    # ↑ Parses the index (timestamp strings from CSV) into proper timezone-aware datetimes.
    #   pd.to_datetime(df.index, utc=True) → converts strings to datetime objects, treating them as UTC.
    #                                         utc=True handles DST-mixed offsets safely (a CSV quirk).
    #   .tz_convert(EASTERN)               → converts from UTC to Eastern time.

    df.index.name = "datetime"
    # ↑ Re-sets the index name (read_csv may not preserve it exactly).

    return df
    # ↑ Returns the loaded DataFrame.


# ---------------------------------------------------------------------------
# Daily bars (unlimited history)
# ---------------------------------------------------------------------------
# ↑ The functions below handle daily (end-of-day) price bars — used for prior_day_return features.

def fetch_daily(symbol: str = SYMBOL, period: str = "2y") -> pd.DataFrame:
# ↑ Downloads daily OHLCV bars from Yahoo Finance and saves to CSV.
#   Parameters:
#     symbol: str = SYMBOL → ticker to download (default "QQQ").
#     period: str = "2y"   → how far back to go. "2y" = 2 years. Other options: "1mo", "6mo", "5y".
#   -> pd.DataFrame        → returns the daily bars DataFrame.
    """Fetch daily OHLCV bars and save to CSV."""
    # ↑ OHLCV = Open, High, Low, Close, Volume — the standard fields in a price bar.

    print(f"[data_loader] Fetching {period} daily bars for {symbol}…")
    # ↑ Status message.

    df = yf.download(symbol, period=period, interval="1d", progress=False)
    # ↑ Downloads daily bars for the full 2-year period in one shot.
    #   interval="1d" → daily bars (one row per trading day).
    #   Daily data has no 30-day limit like 1-minute data — we can get 2 years at once.

    if df.empty:
        # ↑ Checks if Yahoo returned an empty table (no data at all).
        raise RuntimeError(f"yfinance returned empty DataFrame for {symbol} daily")
        # ↑ Raise an error with a descriptive message if no data came back.

    if isinstance(df.columns, pd.MultiIndex):
        # ↑ Handle the multi-level column structure that newer yfinance versions sometimes return.
        df.columns = [col[0].lower() for col in df.columns]
        # ↑ Flatten and lowercase: ("Close", "QQQ") → "close".
    else:
        df.columns = [c.lower() for c in df.columns]
        # ↑ Simple lowercase if columns are already flat.

    df = _to_eastern(df)
    # ↑ Convert timestamp index to Eastern timezone.

    df.index.name = "date"
    # ↑ Names the index "date" (daily bars only need a date, not a full datetime).

    df.to_csv(DAILY_CSV)
    # ↑ Saves to the daily CSV cache file.

    print(f"[data_loader] Saved {len(df):,} rows → {DAILY_CSV}")
    # ↑ Prints confirmation with row count.

    return df
    # ↑ Returns the daily DataFrame.


def load_daily(force_refresh: bool = False) -> pd.DataFrame:
# ↑ Smart loader for daily bars: uses cache if <24 hours old, re-downloads otherwise.
#   Parameter:
#     force_refresh: bool = False → force re-download even if cache is fresh.
#   -> pd.DataFrame               → returns the daily bars DataFrame.
    """Return cached daily bars, re-fetching if >24 h old."""

    if force_refresh or _is_stale(DAILY_CSV, 24):
        # ↑ Re-download if forced or if the daily cache is older than 24 hours.
        return fetch_daily()

    df = pd.read_csv(DAILY_CSV, index_col="date", parse_dates=False)
    # ↑ Reads cached daily CSV. index_col="date" → the "date" column becomes the index.

    df.columns = [c.lower() for c in df.columns]
    # ↑ Lowercase all column names.

    # Parse index robustly: use utc=True to handle DST-mixed offsets, then convert
    # ↑ Comment explaining WHY we use utc=True (the CSV stores timestamps with mixed DST offsets).
    df.index = pd.to_datetime(df.index, utc=True).tz_convert(EASTERN)
    # ↑ Same safe parsing pattern: parse as UTC first, then convert to Eastern.

    df.index.name = "date"
    # ↑ Restore the index name.

    return df
    # ↑ Returns the loaded daily DataFrame.


# ---------------------------------------------------------------------------
# ForexFactory events
# ---------------------------------------------------------------------------
# ↑ Section for loading the ForexFactory macro events CSV.

def load_ff_events() -> pd.DataFrame:
# ↑ Loads the ForexFactory economic calendar events from the local CSV file.
#   No parameters — it always reads from the fixed FF_CSV path.
#   -> pd.DataFrame → returns the events table.
    """
    Load Forex Factory events from CSV.

    Expected columns (case-insensitive):
        date, time, currency, event, impact, actual, forecast, previous
    """
    # ↑ Docstring listing the expected CSV columns.

    if not FF_CSV.exists():
        # ↑ If the FF events CSV doesn't exist yet (scraper hasn't been run), handle gracefully.
        print(f"[data_loader] WARNING: {FF_CSV} not found — macro features will be empty.")
        # ↑ Warn the user but don't crash — the strategy will just have no macro features.
        return pd.DataFrame(columns=["date", "time", "currency", "event",
                                     "impact", "actual", "forecast", "previous"])
        # ↑ Returns an EMPTY DataFrame with the correct column names.
        #   This lets the rest of the code work without crashing even when no FF data exists.

    df = pd.read_csv(FF_CSV)
    # ↑ Reads the ForexFactory CSV into a DataFrame.

    df.columns = [c.lower().strip() for c in df.columns]
    # ↑ Lowercases and strips whitespace from all column names.
    #   .lower()  → "DateTime" → "datetime".
    #   .strip()  → removes leading/trailing spaces: " datetime " → "datetime".

    # Parse datetime
    # ↑ The CSV may store dates and times in separate columns OR as a single "datetime" column.
    #   We handle both formats.
    if "date" in df.columns and "time" in df.columns:
        # ↑ Format 1: separate "date" and "time" columns exist.
        df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str),
                                        errors="coerce")
        # ↑ Combines date and time strings and parses them into datetime objects.
        #   df["date"].astype(str)          → converts the date column to strings (in case it's not already).
        #   + " " +                         → string concatenation: "2026-02-06" + " " + "08:30am" = "2026-02-06 08:30am".
        #   pd.to_datetime(..., errors="coerce") → parses the combined string to datetime.
        #                                          errors="coerce" → if parsing fails, put NaT (Not a Time) instead of crashing.

        df["datetime"] = df["datetime"].dt.tz_localize(EASTERN, ambiguous="infer",
                                                        nonexistent="shift_forward")
        # ↑ Attaches the Eastern timezone to the parsed datetimes.
        #   .dt.tz_localize(EASTERN)     → declares these timestamps are in Eastern time.
        #   ambiguous="infer"            → during DST "fall back" hour when clocks repeat,
        #                                  try to infer whether it's DST or standard time.
        #   nonexistent="shift_forward"  → during DST "spring forward", times that don't exist
        #                                  are shifted forward to the next valid time.

        df["date"] = df["datetime"].dt.date
        # ↑ Extracts just the date part (no time) from the datetime and stores it in "date".
        #   .dt.date → accesses the date portion of each datetime in a Series.

    elif "datetime" in df.columns:
        # ↑ Format 2: a single "datetime" column already exists (ISO format strings).
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce", utc=True).dt.tz_convert(EASTERN)
        # ↑ Parses the datetime column safely:
        #   utc=True         → treats all timestamps as UTC (handles mixed DST offsets in ISO strings).
        #   .dt.tz_convert() → converts from UTC to Eastern time.
        df["date"] = df["datetime"].dt.date
        # ↑ Extracts the date portion.

    # Normalise impact: "High Impact Expected" → "high", etc.
    # ↑ The impact column may have verbose values like "High Impact Expected".
    #   We simplify them to just "high", "medium", or "low" for easy comparison later.
    if "impact" in df.columns:
        # ↑ Only process if the "impact" column exists in the CSV.
        imp = df["impact"].str.lower().str.strip()
        # ↑ Lowercases and strips whitespace from every value in the impact column.
        #   .str.lower()  → applies .lower() to every string in the column.
        #   .str.strip()  → applies .strip() to remove extra spaces.

        df["impact"] = imp.str.extract(r'(high|medium|low)', expand=False).fillna(imp)
        # ↑ Uses a regular expression to extract just "high", "medium", or "low" from the string.
        #   imp.str.extract(r'(high|medium|low)') → searches each string for one of those words.
        #     r'...'       → "raw string" — backslashes are treated literally (important for regex).
        #     (high|medium|low) → regex "group" matching any of those three words.
        #   expand=False   → return a Series (not a DataFrame).
        #   .fillna(imp)   → if extraction failed (no match), keep the original value.
        #   Result: "High Impact Expected" → "high", "Medium Impact Expected" → "medium".
    else:
        df["impact"] = ""
        # ↑ If no impact column, create one filled with empty strings (no impact info available).

    return df
    # ↑ Returns the cleaned ForexFactory events DataFrame.


# ---------------------------------------------------------------------------
# Convenience: fetch everything
# ---------------------------------------------------------------------------
# ↑ A simple class that bundles the fetch functions into one convenient call.

class DataLoader:
# ↑ Defines a class named 'DataLoader'.
#   A class is a blueprint for creating objects. Think of it as a custom data type.
#   You use it like: DataLoader().fetch_all() — creates a DataLoader object and calls fetch_all on it.

    def fetch_all(self) -> None:
    # ↑ A method (a function that belongs to a class).
    #   'self' is always the first parameter of a method — it refers to the object itself.
    #   You don't pass 'self' manually; Python passes it automatically.
    #   -> None → this method returns nothing (it just runs actions and prints messages).
        fetch_intraday()
        # ↑ Downloads and caches fresh 1-minute intraday data.

        fetch_daily()
        # ↑ Downloads and caches fresh daily bars.

        # FF events must be scraped separately via the CLI tool
        # ↑ ForexFactory data requires the web scraper (ff_scraper.py). We can't auto-fetch it here.
        if not FF_CSV.exists():
            # ↑ Checks if the FF events file exists.
            print(f"[data_loader] Reminder: run the ForexFactory scraper to generate {FF_CSV}")
            # ↑ Reminds the user to run the scraper if the file is missing.
