"""
features.py — Premarket + macro feature engineering.

Produces one row per trading day.
"""
# ↑ Docstring: This file's job is "feature engineering" — transforming raw price data
#   into meaningful numbers (features) that the trading strategy can use to make decisions.
#   "Premarket" = before the 9:30 AM market open. "Macro" = macroeconomic events (CPI, NFP, FOMC).
#   The output is one row per trading day, where each column is a different feature.

from __future__ import annotations
# ↑ Modern type hint handling. Safe to ignore as a beginner.

import warnings
# ↑ Python's built-in 'warnings' module for issuing non-fatal warnings.
#   Imported here but not directly used — kept for potential future use.

from datetime import date, time
# ↑ Imports two classes from the 'datetime' module:
#   date → a calendar date (year, month, day) — no time.
#   time → a time of day (hour, minute) — no date.

import numpy as np
# ↑ NumPy for math: np.sign() (direction of a number), np.mean() (average).

import pandas as pd
# ↑ Pandas for working with DataFrames (tables of data).

import pytz
# ↑ Timezone library for Eastern time handling.

EASTERN = pytz.timezone("America/New_York")
# ↑ The Eastern US timezone object. Handles daylight saving automatically.
#   "America/New_York" is the standard IANA timezone name for New York / Eastern time.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# ↑ These small private functions are utility tools used by the larger functions below.

def _time_slice(df: pd.DataFrame, t_start: time, t_end: time) -> pd.DataFrame:
# ↑ Filters a DataFrame to rows whose timestamps fall within [t_start, t_end).
#   Parameters:
#     df: pd.DataFrame → a price bars table with a timezone-aware DatetimeIndex.
#     t_start: time    → start of the time range (inclusive).
#     t_end: time      → end of the time range (exclusive — NOT included).
#   -> pd.DataFrame    → returns the filtered rows.
    """Return rows whose index (tz-aware Eastern) is within [t_start, t_end)."""

    idx_time = df.index.time
    # ↑ Extracts just the time portion (hour, minute, second) from each timestamp in the index.
    #   df.index is a DatetimeIndex like [2026-02-06 08:00:00-05:00, 2026-02-06 08:01:00-05:00, ...].
    #   .time returns an array of time objects: [time(8,0,0), time(8,1,0), ...].

    return df[(idx_time >= t_start) & (idx_time < t_end)]
    # ↑ Applies a time filter and returns only the matching rows.
    #   idx_time >= t_start → True/False array: True where time is at or after start.
    #   idx_time < t_end    → True/False array: True where time is before end.
    #   & (AND)             → both must be True.
    #   df[...]             → keeps only rows where both conditions are True.


def _last_close(df: pd.DataFrame, before: time) -> float | None:
# ↑ Returns the last closing price strictly BEFORE a given time.
#   Used to get "what was the price just before the market opened?" (price at 9:29 AM).
#   Parameters:
#     df: pd.DataFrame → price bars for one day.
#     before: time     → we want bars strictly before this time.
#   -> float | None    → the closing price, or None if no bars exist before that time.
    """Last close price strictly before `before` time."""

    sub = df[df.index.time < before]
    # ↑ Filters to only bars with a timestamp strictly before 'before'.
    #   e.g., before=time(9,30) → keeps all premarket bars (4:00–9:29 AM).

    if sub.empty:
        # ↑ If no bars exist before the specified time (e.g., no premarket data for this day).
        return None
        # ↑ Return None to signal "no data available".

    return float(sub["close"].iloc[-1])
    # ↑ Returns the LAST closing price before the cutoff time.
    #   sub["close"]   → the close price column.
    #   .iloc[-1]      → the last row (most recent bar before the cutoff).
    #   float(...)     → converts to plain Python decimal number.


def _first_close(df: pd.DataFrame, at_or_after: time) -> float | None:
# ↑ Returns the FIRST closing price at or after a given time.
#   Used to get "what was the first price at the market open?" (price at 9:30 AM).
#   Parameters:
#     df: pd.DataFrame  → price bars for one day.
#     at_or_after: time → we want the first bar at or after this time.
#   -> float | None     → the closing price, or None if no bars exist at or after that time.
    """First close price at or after `at_or_after` time."""

    sub = df[df.index.time >= at_or_after]
    # ↑ Filters to bars at or after the specified time.

    if sub.empty:
        # ↑ No bars found at or after this time.
        return None

    return float(sub["close"].iloc[0])
    # ↑ Returns the FIRST closing price at or after the cutoff.
    #   .iloc[0] → the first row (earliest bar at or after the cutoff).


# ---------------------------------------------------------------------------
# Premarket features (per day)
# ---------------------------------------------------------------------------

def _premarket_features(day_bars: pd.DataFrame, prior_close: float | None) -> dict:
# ↑ Computes all premarket-related features for one trading day.
#   These features describe what the market did BEFORE the 9:30 AM open.
#   Parameters:
#     day_bars: pd.DataFrame    → all 1-minute bars for this day (from ~4:00 AM to ~8:00 PM ET).
#     prior_close: float | None → the previous trading day's closing price (or None if unknown).
#   -> dict                     → returns a dictionary of feature name → value.
    """
    Compute premarket features for a single trading day.

    day_bars: 1-min bars for the full day (4:00–20:00 ET), Eastern-tz index.
    prior_close: prior trading day's regular-session close.
    """

    feats: dict = {}
    # ↑ Empty dictionary to collect all the features we compute.
    #   ': dict' is a type annotation — just for documentation, Python doesn't enforce it.

    # Price just before open (9:29 ET)
    price_929 = _last_close(day_bars, time(9, 30))
    # ↑ Gets the last price before 9:30 AM — represents the "premarket closing price".
    #   This is effectively the price at 9:29 AM (the last minute before the open).
    #   We use time(9,30) as the "before" cutoff, so we get bars up to 9:29.

    # Also grab 8:59 for reversal flag
    price_859 = _last_close(day_bars, time(9, 0))
    # ↑ Gets the last price before 9:00 AM — represents the "early morning" price.
    #   Used to detect if the market reversed direction between 8:59 and 9:29.

    # --- pm_gap_pct ---
    # ↑ "pm_gap_pct" = premarket gap percentage.
    #   The "gap" is how much the current price differs from the previous day's close.
    #   A positive gap means the market opened higher (gap up). Negative = gap down.
    if prior_close and prior_close > 0 and price_929 is not None:
        # ↑ Only calculate if we have both prices. Three conditions:
        #   prior_close          → it's not None (we have prior day data).
        #   prior_close > 0      → it's a positive price (sanity check, price can't be ≤ 0).
        #   price_929 is not None → we have premarket data for this day.
        feats["pm_gap_pct"] = (price_929 - prior_close) / prior_close * 100.0
        # ↑ Calculates the gap as a percentage of the prior close.
        #   Formula: (current_price - prior_close) / prior_close × 100.
        #   e.g., prior_close=480, price_929=483.6 → gap = (483.6-480)/480×100 = +0.75% (gap up).
        #   Multiplying by 100 converts decimal to percentage: 0.0075 → 0.75.
    else:
        feats["pm_gap_pct"] = 0.0
        # ↑ If we're missing either price, default to 0 (no gap detected).

    feats["pm_direction"] = int(np.sign(feats["pm_gap_pct"])) if feats["pm_gap_pct"] != 0 else 0
    # ↑ Converts the gap percentage to a direction: +1 (gap up), -1 (gap down), 0 (flat/unknown).
    #   np.sign(x) → returns +1.0 if x>0, -1.0 if x<0, 0.0 if x=0.
    #   int(...)   → converts NumPy float to Python integer.
    #   'if gap != 0 else 0' → handles the case where gap is exactly 0 (np.sign(0) = 0 already,
    #                          but this makes the intent clearer).

    # --- Momentum: early (8:00–8:44) vs late (8:45–9:29) ---
    # ↑ We split the premarket session into "early" and "late" halves.
    #   By comparing how much the price moved in each half, we can tell if momentum is:
    #   - ACCELERATING: late half moved MORE in the same direction than early half.
    #   - DECELERATING: late half moved less or reversed vs early half.
    early = _time_slice(day_bars, time(8, 0), time(8, 45))
    # ↑ Filters bars to the early premarket window: 8:00 AM to 8:44 AM.

    late = _time_slice(day_bars, time(8, 45), time(9, 30))
    # ↑ Filters bars to the late premarket window: 8:45 AM to 9:29 AM.

    if len(early) >= 2:
        # ↑ Need at least 2 bars to measure a price move (start price and end price).
        early_move = float(early["close"].iloc[-1]) - float(early["close"].iloc[0])
        # ↑ The raw price move during the early window.
        #   Last price - first price = total price change (positive = moved up, negative = moved down).
        #   This is an absolute dollar move, not a percentage.
    else:
        early_move = 0.0
        # ↑ Not enough data — assume no movement in the early window.

    if len(late) >= 2:
        # ↑ Same for the late window.
        late_move = float(late["close"].iloc[-1]) - float(late["close"].iloc[0])
        # ↑ Price change during the late premarket (8:45–9:29 AM).
    else:
        late_move = 0.0

    feats["pm_momentum_score"] = late_move / (abs(early_move) + 0.001)
    # ↑ Computes a "momentum score" — how much the late move compares to the early move.
    #   late_move / abs(early_move) → ratio of late to early movement.
    #   + 0.001 → a tiny constant added to avoid division by zero when early_move=0.
    #             This is called "epsilon smoothing" — a common trick.
    #   Score > 1 (same direction, late > early) → accelerating.
    #   Score < 1 (same direction, late < early) → decelerating.
    #   Score < 0 (opposite direction)            → reversing.

    # Accelerating = late move same direction AND larger magnitude
    # ↑ This block converts the momentum score into a simple +1 / -1 / 0 label.
    if early_move == 0 and late_move == 0:
        # ↑ Both windows showed zero movement — no momentum either way.
        feats["pm_momentum_accel"] = 0
        # ↑ 0 = no momentum information.

    elif np.sign(late_move) == np.sign(early_move) and abs(late_move) > abs(early_move):
        # ↑ Two conditions:
        #   np.sign(late_move) == np.sign(early_move) → both moved in the same direction.
        #   abs(late_move) > abs(early_move)           → the late move was LARGER (accelerating).
        feats["pm_momentum_accel"] = 1
        # ↑ +1 = momentum is accelerating (getting stronger into the open).

    else:
        feats["pm_momentum_accel"] = -1
        # ↑ -1 = momentum is decelerating or reversing (weakening into the open).

    # --- pm_reversal_flag ---
    # ↑ Detects if the market flipped direction between 8:59 AM and 9:29 AM.
    #   A reversal near the open is a significant signal: the "smart money" may be
    #   positioning against the initial direction right before the market opens.
    if prior_close and prior_close > 0 and price_859 is not None and price_929 is not None:
        # ↑ Only compute if we have all four required data points.

        dir_859 = int(np.sign(price_859 - prior_close))
        # ↑ Direction at 8:59 AM relative to prior close.
        #   price_859 - prior_close → positive if above prior close, negative if below.
        #   np.sign(...)            → +1 (above), -1 (below), 0 (exactly equal).
        #   int(...)                → convert to Python integer.

        dir_929 = int(np.sign(price_929 - prior_close))
        # ↑ Direction at 9:29 AM relative to prior close. Same calculation.

        feats["pm_reversal_flag"] = 1 if (dir_859 != dir_929 and dir_859 != 0) else 0
        # ↑ Sets reversal_flag to 1 if a direction flip happened, 0 if not.
        #   dir_859 != dir_929 → direction changed between 8:59 and 9:29.
        #   dir_859 != 0       → at 8:59 there WAS a clear direction (not exactly at prior close).
        #   Both conditions with 'and' → reversal only counts if we had a clear initial direction.
        #   Ternary: 'value_if_true if condition else value_if_false'.
    else:
        feats["pm_reversal_flag"] = 0
        # ↑ Missing data — assume no reversal.

    return feats
    # ↑ Returns the dictionary of all premarket features.


# ---------------------------------------------------------------------------
# Macro features (per day from FF events)
# ---------------------------------------------------------------------------

def _macro_features(day_events: pd.DataFrame) -> dict:
# ↑ Computes macroeconomic features for one trading day from ForexFactory event data.
#   "Macro" features capture whether a major economic report is being released today,
#   which significantly affects how the market behaves.
#   Parameter:
#     day_events: pd.DataFrame → rows from the FF events table for this specific date,
#                                pre-filtered to USD currency events only.
#   -> dict                    → returns a dictionary of feature name → value.
    """
    Compute macro features for a single trading day from ForexFactory events.

    day_events: rows from ff_events for this date, filtered to USD.
    """

    feats: dict = {
        # ↑ Start with a dictionary of default values (all 0 or 0.0).
        #   If there are no events for this day, all macro features will remain at their defaults.
        "has_high_impact_event":    0,
        # ↑ 1 if there's any High Impact event today, 0 otherwise.
        "has_pre_open_high_impact": 0,
        # ↑ 1 if a High Impact event happens BEFORE the 9:30 AM market open.
        "has_post_open_high_impact": 0,
        # ↑ 1 if a High Impact event happens AFTER the 9:30 AM open (during trading hours).
        "is_fomc_day":             0,
        # ↑ 1 if today is a Federal Reserve rate decision day.
        "is_cpi_day":              0,
        # ↑ 1 if today has a Consumer Price Index (inflation) report.
        "is_nfp_day":              0,
        # ↑ 1 if today has a Non-Farm Payrolls (jobs) report.
        "event_surprise_score":    0.0,
        # ↑ A decimal measuring how much economic data deviated from forecasts.
        #   Positive = data better than expected (bullish), negative = worse (bearish).
    }

    if day_events.empty:
        # ↑ If there are no ForexFactory events for this day, return the all-zero defaults.
        return feats

    high = day_events[day_events["impact"] == "high"]
    # ↑ Filters to only "high impact" events (the most market-moving ones).
    #   day_events["impact"] == "high" → True/False mask where impact equals "high".
    #   day_events[...]                → keeps only those rows.
    #   Note: "high" is lowercase because data_loader.py normalizes impact to lowercase.

    feats["has_high_impact_event"] = int(len(high) > 0)
    # ↑ Sets to 1 if there's at least one high-impact event, 0 if none.
    #   len(high) > 0 → True if count > 0, False if 0.
    #   int(True) = 1, int(False) = 0. This converts boolean to 0/1 integer.

    if "datetime" in high.columns and not high.empty:
        # ↑ Only calculate pre/post open split if:
        #   "datetime" in high.columns → the datetime column exists in our high-impact events.
        #   not high.empty             → there ARE high-impact events (redundant check, but safe).

        open_time = time(9, 30)
        # ↑ Market open time: 9:30 AM.

        pre = high[high["datetime"].dt.time < open_time]
        # ↑ Filters high-impact events to those occurring BEFORE market open.
        #   high["datetime"]     → the datetime column (full timestamp for each event).
        #   .dt.time             → extracts just the time portion from each datetime.
        #   < open_time          → True where the event time is before 9:30 AM.
        #   .dt is the "datetime accessor" — it unlocks datetime methods on a Pandas Series.

        post = high[high["datetime"].dt.time >= open_time]
        # ↑ High-impact events at or after the open (during trading hours).

        feats["has_pre_open_high_impact"]  = int(len(pre) > 0)
        # ↑ 1 if there's a high-impact event before the open (like 8:30 AM jobs report).
        feats["has_post_open_high_impact"] = int(len(post) > 0)
        # ↑ 1 if there's a high-impact event during trading hours (like 10:00 AM FOMC).

    # Specific event flags (case-insensitive substring match)
    # ↑ We look for specific well-known events by checking if their keywords appear in event names.
    all_events = " ".join(day_events["event"].fillna("").str.lower().tolist())
    # ↑ Creates one long string containing all event names for this day, joined with spaces.
    #   day_events["event"]  → the event name column (e.g., "Non-Farm Employment Change").
    #   .fillna("")          → replaces any NaN (missing) values with empty strings.
    #   .str.lower()         → converts all event names to lowercase for case-insensitive matching.
    #   .tolist()            → converts the Pandas Series to a plain Python list of strings.
    #   " ".join([...])      → joins all event names into one big string, separated by spaces.
    #   e.g., "non-farm employment change average hourly earnings fomc statement".
    #   We can then do: "fomc statement" in all_events → True/False.

    # is_fomc_day: actual rate decision or minutes only — NOT routine member speeches
    fomc_keywords = ("fomc statement", "fomc meeting minutes", "federal funds rate",
                     "fomc press conference", "monetary policy statement")
    # ↑ A tuple of keyword phrases that indicate a REAL FOMC decision event.
    #   Tuples () are like lists [] but cannot be changed after creation (immutable).
    #   We only flag FOMC days for actual rate decisions, not routine Fed member speeches.

    feats["is_fomc_day"] = int(any(kw in all_events for kw in fomc_keywords))
    # ↑ Sets is_fomc_day to 1 if ANY of the FOMC keywords appears in today's events.
    #   'kw in all_events for kw in fomc_keywords' → a generator: True/False for each keyword.
    #   any(...)  → True if at least one of those is True (any keyword matched).
    #   int(...)  → convert True/False to 1/0.

    feats["is_cpi_day"] = int("cpi" in all_events or "consumer price index" in all_events)
    # ↑ 1 if today has a CPI (Consumer Price Index = inflation) report.
    #   'in' checks if the substring exists anywhere in all_events.
    #   'or' means: True if EITHER keyword is found.

    feats["is_nfp_day"] = int("non-farm" in all_events or "nonfarm" in all_events
                               or "employment change" in all_events)
    # ↑ 1 if today has an NFP (Non-Farm Payrolls = jobs report) event.
    #   Checks multiple spellings: "non-farm", "nonfarm", "employment change".

    # Surprise score
    # ↑ Calculates how much actual economic data differed from analyst forecasts.
    #   Positive surprise = data beat expectations (bullish). Negative = missed expectations (bearish).
    surprises = []
    # ↑ Empty list to collect surprise values for each event that has both actual and forecast values.

    for _, row in day_events.iterrows():
        # ↑ Loops over each event row for this day.
        #   .iterrows() yields (index, row) pairs. We use _ to ignore the index (not needed here).
        #   row → a Series with the event's data (currency, event, actual, forecast, previous).

        try:
            # ↑ 'try' block — the string-to-number conversion might fail (e.g., if actual is empty).
            #   We use try/except to handle failures gracefully without crashing.

            actual = float(str(row.get("actual", "")).replace("%", "").replace("K", "")
                           .replace("M", "").replace("B", "").strip())
            # ↑ Extracts and cleans the "actual" value (what was really reported).
            #   row.get("actual", "") → gets the actual value, defaulting to "" if missing.
            #   str(...)              → ensures it's a string.
            #   .replace("%", "")     → removes % signs: "2.5%" → "2.5".
            #   .replace("K", "")     → removes K (thousands): "227K" → "227".
            #   .replace("M", "")     → removes M (millions): "1.2M" → "1.2".
            #   .replace("B", "")     → removes B (billions).
            #   .strip()              → removes whitespace.
            #   float(...)            → converts the cleaned string to a decimal number.

            forecast = float(str(row.get("forecast", "")).replace("%", "").replace("K", "")
                             .replace("M", "").replace("B", "").strip())
            # ↑ Same cleaning process for the "forecast" value (what analysts expected).

            if abs(forecast) > 1e-6:
                # ↑ Only compute a surprise if the forecast is meaningfully non-zero.
                #   1e-6 = 0.000001 (scientific notation). This avoids division by near-zero.
                #   abs(forecast) → absolute value (handles negative forecasts).
                surprises.append((actual - forecast) / abs(forecast))
                # ↑ Computes the relative surprise: (actual - forecast) / |forecast|.
                #   e.g., forecast=170, actual=227 → surprise = (227-170)/170 = 0.335 (+33.5% beat!).
                #   .append() adds this surprise value to our list.

        except (ValueError, TypeError):
            # ↑ Catches two types of errors:
            #   ValueError  → float() received a string it can't convert (e.g., "N/A", "--").
            #   TypeError   → row.get() returned something unexpected (e.g., None).
            #   'pass' → do nothing and skip this event. We just won't include it in the surprises list.
            pass

    if surprises:
        # ↑ If we collected any valid surprise values (list is not empty).
        feats["event_surprise_score"] = float(np.mean(surprises))
        # ↑ Sets the surprise score to the AVERAGE of all individual event surprises.
        #   np.mean(surprises) → computes the arithmetic mean of all values in the list.
        #   float(...)         → converts NumPy float to plain Python float.

    return feats
    # ↑ Returns the completed macro features dictionary.


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_features(intraday_df: pd.DataFrame,
                   daily_df: pd.DataFrame,
                   ff_events_df: pd.DataFrame) -> pd.DataFrame:
# ↑ The main public function of this file — combines everything into one feature table.
#   Takes raw data from three different sources and produces a clean feature table
#   with one row per trading day.
#   Parameters:
#     intraday_df: pd.DataFrame  → 1-minute price bars (all days, premarket included).
#     daily_df: pd.DataFrame     → daily OHLCV bars (2 years of end-of-day data).
#     ff_events_df: pd.DataFrame → ForexFactory macro events (currency, impact, etc.).
#   -> pd.DataFrame              → one row per trading day, one column per feature.
    """
    Build one feature row per trading day.

    Parameters
    ----------
    intraday_df  : 1-min bars, Eastern-tz DatetimeIndex, columns include 'close'
    daily_df     : daily bars, Eastern-tz DatetimeIndex, columns include 'close'
    ff_events_df : FF events, must have 'date', 'currency', 'impact', 'event',
                   'actual', 'forecast', 'datetime' columns

    Returns
    -------
    pd.DataFrame with one row per trading day, index = date (Python date object)
    """

    # Identify trading days from intraday data (regular session: 9:30–16:00)
    # ↑ We define a "trading day" as any day that has bars during regular market hours (9:30–4:00 PM).
    #   This automatically excludes weekends and holidays (no market data on those days).
    regular = _time_slice(intraday_df, time(9, 30), time(16, 0))
    # ↑ Filters all 1-minute bars to only those during regular market hours (9:30 AM – 4:00 PM).
    #   This excludes premarket and after-hours bars.

    trading_dates = sorted(regular.index.date)
    # ↑ Extracts the date from each regular-session bar's timestamp.
    #   .date → gives the date portion of each timestamp.
    #   sorted() → sorts chronologically.
    #   This gives us a list of all dates that had regular trading sessions.
    #   Note: each date appears ~390 times (one per minute) — we deduplicate in the next line.

    trading_dates = list(dict.fromkeys(trading_dates))
    # ↑ Removes duplicates while PRESERVING the original order.
    #   dict.fromkeys(iterable) → creates a dict using items as keys (dicts can't have duplicate keys).
    #                             Since keys are unique, duplicates are removed. The order is preserved.
    #   list(...)               → converts back to a list.
    #   This is a Python idiom for "deduplicate while keeping order".
    #   Alternative: sorted(set(...)) would work too but doesn't guarantee original order.

    # Build prior-day close lookup from daily_df
    # ↑ We need "yesterday's close" for each trading day to compute the premarket gap.
    #   We build a dictionary mapping date → closing price for quick lookups.
    daily_closes: dict[date, float] = {}
    # ↑ An empty dictionary that will map date → close price.
    #   ': dict[date, float]' is a type annotation: keys are date objects, values are floats.

    for ts, row in daily_df.iterrows():
        # ↑ Loops over each row in the daily bars table.
        #   ts  → the timestamp index (e.g., 2026-02-05 00:00:00-05:00).
        #   row → a Series with that day's OHLCV values.

        d = ts.date() if hasattr(ts, "date") else ts
        # ↑ Extracts the date part from the timestamp.
        #   hasattr(ts, "date") → True if ts has a .date() method (it's a datetime/Timestamp).
        #   ts.date()           → extracts just the date: 2026-02-05.
        #   else ts             → if ts doesn't have .date() (it's already a date), use it directly.
        #   This handles both Timestamp and date objects safely.

        daily_closes[d] = float(row["close"])
        # ↑ Stores the closing price in our lookup dictionary.
        #   daily_closes[d] = ... → sets the value for key d.
        #   float(row["close"])   → the closing price as a plain Python float.

    # USD events only
    # ↑ ForexFactory has events for many currencies (EUR, GBP, JPY, etc.).
    #   We only care about USD events since we're trading QQQ (a US stock index).
    if not ff_events_df.empty and "currency" in ff_events_df.columns:
        # ↑ Two conditions:
        #   not ff_events_df.empty             → the events table has data (not empty).
        #   "currency" in ff_events_df.columns → the table has a "currency" column.
        usd_events = ff_events_df[ff_events_df["currency"].str.upper() == "USD"].copy()
        # ↑ Filters to only USD currency events.
        #   .str.upper()     → converts all currency values to uppercase for safe comparison.
        #   == "USD"         → True/False mask: True where currency is "USD".
        #   ff_events_df[...] → keeps only matching rows.
        #   .copy()          → makes a copy to avoid SettingWithCopyWarning later.
    else:
        usd_events = pd.DataFrame(columns=ff_events_df.columns)
        # ↑ If the events table is empty or has no currency column, create an empty table
        #   with the same column structure (so later code doesn't crash on missing columns).

    rows = []
    # ↑ Empty list to collect one feature dictionary per trading day.

    sorted_dates = sorted(daily_closes.keys())
    # ↑ All dates in the daily_closes dictionary, sorted chronologically.
    #   .keys() → gets all the date keys from the dictionary.
    #   sorted() → sorts them from oldest to newest.
    #   Used to look up "what was the most recent trading day BEFORE day d?".

    for d in trading_dates:
        # ↑ Main loop: processes one trading day at a time.

        # Get prior trading day close
        # ↑ We need yesterday's close to compute the premarket gap.
        prior_dates = [x for x in sorted_dates if x < d]
        # ↑ List comprehension: builds a list of all dates in sorted_dates that are BEFORE d.
        #   [x for x in sorted_dates if x < d] → like a filtered loop:
        #     for x in sorted_dates  → go through each date.
        #     if x < d              → keep it only if it's before our current date.
        #   Result: all previous trading dates (that have daily data) before day d.

        prior_close = daily_closes.get(prior_dates[-1]) if prior_dates else None
        # ↑ Gets the closing price of the most recent prior trading day.
        #   prior_dates[-1]          → the last item (most recent date before d).
        #   daily_closes.get(...)    → looks up the closing price for that date.
        #   'if prior_dates else None' → if prior_dates is empty (d is the very first day),
        #                               return None (no prior close available).

        # Day's 1-min bars
        day_bars = intraday_df[intraday_df.index.date == d].copy()
        # ↑ Filters the full intraday table to only bars for this specific trading day d.
        #   .copy() → makes a copy to avoid modifying the original data.

        # Prior day return from daily_df
        # ↑ Computes how much the market moved yesterday (open-to-close return).
        #   Used in the mean-reversion rule: after a big day, we expect a partial reversal.
        if prior_dates:
            # ↑ Only if we have a prior trading day to look at.
            prior_day = daily_df[daily_df.index.date == prior_dates[-1]]
            # ↑ Gets all daily bar rows for the most recent prior trading day.
            #   daily_df.index.date → date portion of each timestamp.
            #   == prior_dates[-1]  → True where the date matches the prior day.

            if not prior_day.empty:
                # ↑ If we found data for the prior day.
                pc_open  = float(prior_day["open"].iloc[0])
                # ↑ The prior day's opening price.
                #   prior_day["open"] → the open column.
                #   .iloc[0]          → the first (and typically only) row for that day.
                pc_close = float(prior_day["close"].iloc[0])
                # ↑ The prior day's closing price.

                prior_day_return = (pc_close - pc_open) / pc_open if pc_open != 0 else 0.0
                # ↑ Prior day's open-to-close return.
                #   Formula: (close - open) / open.
                #   e.g., open=480, close=486 → return = (486-480)/480 = 0.0125 (+1.25%).
                #   Ternary: only divide if open != 0 (avoid division by zero).
            else:
                prior_day_return = 0.0
                # ↑ No prior day data found — default to 0.
        else:
            prior_day_return = 0.0
            # ↑ No prior trading days at all (first day in dataset) — default to 0.

        pm_feats = _premarket_features(day_bars, prior_close)
        # ↑ Calls our premarket feature function to get all premarket-related features for this day.
        #   Returns a dictionary like {"pm_gap_pct": 0.75, "pm_direction": 1, ...}.

        # Macro features
        day_usd = usd_events[usd_events["date"] == d] if not usd_events.empty else pd.DataFrame()
        # ↑ Filters USD events to only those for this specific trading day d.
        #   usd_events["date"] == d → True/False mask matching this day.
        #   'if not usd_events.empty' → only filter if the table has data; otherwise use empty DataFrame.
        #   pd.DataFrame() → an empty table as the fallback.

        macro_feats = _macro_features(day_usd)
        # ↑ Calls the macro feature function with this day's events.
        #   Returns a dictionary like {"has_high_impact_event": 1, "is_nfp_day": 1, ...}.

        row = {"date": d, "prior_day_return": prior_day_return}
        # ↑ Starts building this day's feature row as a dictionary.
        #   Begins with the date and the prior day return.

        row.update(pm_feats)
        # ↑ .update() adds all key-value pairs from pm_feats into the row dictionary.
        #   It's like merging two dictionaries: row now contains all premarket features too.
        #   e.g., adds "pm_gap_pct", "pm_direction", "pm_momentum_score", etc.

        row.update(macro_feats)
        # ↑ Same thing for macro features: adds "has_high_impact_event", "is_fomc_day", etc.

        rows.append(row)
        # ↑ Adds this complete feature row to our list.

    features_df = pd.DataFrame(rows).set_index("date")
    # ↑ Converts the list of feature dictionaries into a DataFrame.
    #   pd.DataFrame(rows)  → each dict in 'rows' becomes one row; dict keys become column names.
    #   .set_index("date")  → makes the "date" column the row index for easy date-based lookup.

    return features_df
    # ↑ Returns the completed feature table: one row per trading day, many feature columns.
