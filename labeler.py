"""
labeler.py — Ground truth window direction labels from 1-minute bars.

W1: 9:30–10:00 ET  →  label ∈ {+1 Long, -1 Short, 0 Flat}
W2: 10:00–10:30 ET →  label ∈ {+1 Long, -1 Short, 0 Flat}
"""
# ↑ This is a "docstring" — a block of text between triple quotes that documents the file.
#   It is not executed as code; it is purely for humans reading the file.
#   It explains what this file does: it reads 1-minute price bars and decides whether
#   the market went up (+1 Long), down (-1 Short), or stayed neutral (0 Flat)
#   for two specific time windows each trading day.

from __future__ import annotations
# ↑ This line imports a special "future" feature from Python itself.
#   It changes how Python reads "type hints" (the labels like ': float' or '-> int' in function definitions).
#   Without this, some type hints would cause errors in older Python versions.
#   With it, Python reads them as plain text strings instead of evaluating them immediately.
#   As a beginner, just treat this as a required line at the top of modern Python files — ignore it otherwise.

from datetime import time
# ↑ Imports the 'time' class from Python's built-in 'datetime' module.
#   'datetime' is a standard library for working with dates and times.
#   The 'time' class (lowercase) represents a time-of-day only — no date attached.
#   Example: time(9, 30) means "9 hours and 30 minutes" = 9:30 AM.
#   Example: time(10, 0) means "10 hours and 0 minutes" = 10:00 AM.

import numpy as np
# ↑ Imports the NumPy library and gives it the short nickname 'np'.
#   NumPy is the standard math library for Python — it provides fast numerical operations.
#   We use it here specifically for np.sign(), which returns:
#     +1 if a number is positive
#     -1 if a number is negative
#      0 if the number is zero

import pandas as pd
# ↑ Imports the Pandas library with the short nickname 'pd'.
#   Pandas is the standard Python library for working with tables of data.
#   A "DataFrame" in Pandas is like an Excel spreadsheet — rows and named columns.
#   We use it here to work with our table of 1-minute price bars.

# Window boundaries (Eastern time)
# ↑ This is a plain comment (starts with #). Comments are ignored by Python — they are
#   just notes for the human reader. This comment tells us that the four lines below
#   define the start/end times of our two trading windows.

W1_START = time(9, 30)
# ↑ Creates a constant named W1_START representing 9:30 AM Eastern time.
#   time(9, 30) = 9 hours, 30 minutes → the opening bell of the US stock market.
#   "UPPER_CASE" names are a Python convention for constants — values that never change.

W1_END = time(10, 0)
# ↑ Window 1 ends at 10:00 AM. time(10, 0) = 10 hours, 0 minutes.

W2_START = time(10, 0)
# ↑ Window 2 starts right where Window 1 ends: 10:00 AM.

W2_END = time(10, 30)
# ↑ Window 2 ends at 10:30 AM. time(10, 30) = 10 hours, 30 minutes.


def _label(ret: float, threshold: float = 0.0) -> int:
# ↑ Defines a function named '_label'.
#   The leading underscore '_' is a Python convention meaning "private" —
#   this function is for internal use within this file, not meant to be called from outside.
#   Parameters (inputs the function receives):
#     ret: float           → the return (price change as a decimal). 'float' means a decimal number.
#                            e.g., 0.005 means the price moved up 0.5%.
#     threshold: float = 0.0 → the minimum move size to count as Long or Short.
#                              '= 0.0' means the default value is 0 if the caller doesn't provide one.
#   -> int                 → the function returns an integer: +1, -1, or 0.
    """Convert a return to +1 / -1 / 0."""
    # ↑ Docstring: a one-line summary of what this function does.

    if ret > threshold:
        # ↑ If the return is greater than the threshold, the price went up enough to call it Long.
        return 1
        # ↑ Return the integer +1, meaning "Long" (bullish, price moved up).

    if ret < -threshold:
        # ↑ If the return is below negative threshold, price went down enough to call it Short.
        #   -threshold flips the sign: if threshold=0.0, -threshold is also 0.0.
        #   If threshold=0.003, -threshold is -0.003.
        return -1
        # ↑ Return -1, meaning "Short" (bearish, price moved down).

    return 0
    # ↑ If neither condition matched (return is between -threshold and +threshold),
    #   return 0, meaning "Flat" — no clear direction, no trade.


def _window_return(day_bars: pd.DataFrame,
                   t_start: time,
                   t_end: time) -> float:
# ↑ Defines function '_window_return'. This calculates how much the price moved
#   between the start and end of a given time window.
#   Parameters:
#     day_bars: pd.DataFrame → a table of 1-minute price bars for one full trading day.
#                              Each row is one minute, with columns like 'open', 'high', 'low', 'close'.
#     t_start: time          → the start of the window (e.g., time(9, 30) for 9:30 AM).
#     t_end: time            → the end of the window (e.g., time(10, 0) for 10:00 AM).
#   -> float                 → returns the percentage return as a decimal (e.g., 0.0032 = +0.32%).
    """
    Compute (last_close - first_close) / first_close for bars in [t_start, t_end).
    """
    # ↑ Docstring: the formula is (ending price - starting price) / starting price.
    #   [t_start, t_end) means the range includes t_start but NOT t_end (standard math interval notation).

    bars = day_bars[(day_bars.index.time >= t_start) & (day_bars.index.time < t_end)]
    # ↑ This line filters the day's bars to only those within the time window.
    #   Let's break it down piece by piece:
    #   day_bars.index         → the DatetimeIndex of the table (timestamps like "2026-02-06 09:31:00 ET").
    #   day_bars.index.time    → extracts just the time portion from every timestamp (e.g., 09:31:00).
    #   >= t_start             → creates a True/False list: True where the bar's time is at or after start.
    #   < t_end                → creates another True/False list: True where time is strictly before end.
    #   & (ampersand)          → combines both conditions with AND — both must be True to keep the row.
    #   day_bars[...]          → uses the True/False mask to select only matching rows.
    #   Result: 'bars' is a smaller table with only the rows that fall inside the window.

    if len(bars) < 2:
        # ↑ len(bars) returns the number of rows in 'bars'.
        #   If there are fewer than 2 rows, we can't calculate a start-to-end move (we need at least 2 points).
        return 0.0
        # ↑ Return 0.0 (no movement) as a safe default when there's not enough data.

    first = float(bars["close"].iloc[0])
    # ↑ Gets the closing price of the FIRST bar inside the window.
    #   bars["close"]  → selects the 'close' column from the table — a list of closing prices.
    #   .iloc[0]       → selects the item at integer position 0 (the first row). 'iloc' = "integer location".
    #   float(...)     → converts the value to a standard Python decimal number (in case it's a NumPy type).

    last = float(bars["close"].iloc[-1])
    # ↑ Gets the closing price of the LAST bar inside the window.
    #   .iloc[-1] → in Python, index -1 always means "the last item" in a list or table.

    return (last - first) / first if first != 0 else 0.0
    # ↑ Computes the percentage return: (end_price - start_price) / start_price.
    #   This is a Python "ternary expression" — a compact one-line if/else:
    #     "compute the formula  IF  first != 0  ELSE  return 0.0"
    #   We check that first != 0 to avoid "ZeroDivisionError" — dividing by zero would crash Python.
    #   Example: if first=480.0 and last=481.5, the return = (481.5 - 480.0) / 480.0 = 0.003125 (+0.31%).


def build_labels(intraday_df: pd.DataFrame, threshold: float = 0.0) -> pd.DataFrame:
# ↑ This is the main PUBLIC function of this file — the one other files will call.
#   It processes the entire intraday dataset and produces a table of labels for every trading day.
#   Parameters:
#     intraday_df: pd.DataFrame → the full table of 1-minute bars for ALL days (e.g., 14,000 rows).
#     threshold: float = 0.0    → minimum return to classify as Long/Short (0.0 means any move counts).
#   -> pd.DataFrame             → returns a new table with one row per day.
    """
    Compute W1 and W2 labels for every trading day found in intraday_df.

    Parameters
    ----------
    intraday_df : 1-min bars with Eastern-tz DatetimeIndex and 'close' column
    threshold   : |return| must exceed this to be labelled Long/Short (default 0 = any move)

    Returns
    -------
    DataFrame with index = date, columns:
        window1_return, window1_label, window2_return, window2_label
    """
    # ↑ Docstring explaining inputs and outputs in detail. The "Parameters" and "Returns"
    #   sections follow the NumPy docstring format — a common Python documentation style.

    trading_dates = sorted(set(intraday_df.index.date))
    # ↑ Builds a sorted list of all unique trading dates found in the intraday data.
    #   Let's break it down:
    #   intraday_df.index       → the index of the table — a list of full timestamps.
    #   intraday_df.index.date  → extracts just the date part (no time) from each timestamp.
    #                             Since there are ~390 bars per day, "2026-02-06" appears ~390 times.
    #   set(...)                → removes duplicates. A set only keeps unique values.
    #                             So "2026-02-06" appears exactly once.
    #   sorted(...)             → sorts the unique dates from oldest to newest (chronological order).
    #   Result: a list like [date(2026,2,6), date(2026,2,7), date(2026,2,10), ...]

    rows = []
    # ↑ Creates an empty Python list. We will collect one dictionary per trading day,
    #   then convert the whole list into a DataFrame at the end.
    #   [] is the syntax for an empty list in Python.

    for d in trading_dates:
        # ↑ A for loop — Python repeats the indented block for each item in 'trading_dates'.
        #   On each pass, 'd' takes the value of the next date (e.g., date(2026, 2, 6)).

        day_bars = intraday_df[intraday_df.index.date == d]
        # ↑ Filters the full intraday table to only the rows for this specific day 'd'.
        #   intraday_df.index.date == d  → creates a True/False mask: True where the date matches d.
        #   intraday_df[...]             → applies the mask, keeping only matching rows.
        #   Result: 'day_bars' is a smaller table with ~390 rows (one per minute for that day).

        # Sanity: skip days with no regular session bars
        # ↑ "Sanity check" means a quick test to catch data problems.
        regular = day_bars[(day_bars.index.time >= W1_START) & (day_bars.index.time < W2_END)]
        # ↑ From this day's bars, filters to only those during market hours (9:30 to 10:30).
        #   Uses the same time-filtering technique as in _window_return above.

        if regular.empty:
            # ↑ .empty is a Pandas property — it's True if the DataFrame has zero rows.
            #   If this day has no regular-session bars at all, it's probably a data gap or holiday.
            continue
            # ↑ 'continue' is a Python keyword that immediately skips to the next iteration
            #   of the for loop — it skips processing this day and moves on to the next date.

        w1_ret = _window_return(day_bars, W1_START, W1_END)
        # ↑ Calls our helper function to compute the price return during Window 1 (9:30–10:00).
        #   Stores the result (a decimal like 0.0032) in the variable 'w1_ret'.

        w2_ret = _window_return(day_bars, W2_START, W2_END)
        # ↑ Same for Window 2 (10:00–10:30). Result stored in 'w2_ret'.

        rows.append({
            # ↑ .append() adds one item to the end of the 'rows' list.
            #   We're appending a dictionary {} — a Python structure of key: value pairs.
            #   Think of it like one row in a spreadsheet, where keys are column names.

            "date":           d,
            # ↑ The trading date for this row (a Python date object like 2026-02-06).

            "window1_return": w1_ret,
            # ↑ The raw price return for W1 (e.g., 0.003125 means +0.31%).

            "window1_label":  _label(w1_ret, threshold),
            # ↑ The direction label for W1: calls _label() to convert the return to +1, -1, or 0.

            "window2_return": w2_ret,
            # ↑ The raw price return for W2.

            "window2_label":  _label(w2_ret, threshold),
            # ↑ The direction label for W2.
        })

    labels_df = pd.DataFrame(rows).set_index("date")
    # ↑ Converts the list of dictionaries into a Pandas DataFrame (a proper table).
    #   pd.DataFrame(rows)  → builds the table. Each dict in 'rows' becomes one row;
    #                          dict keys ("date", "window1_return", etc.) become column names.
    #   .set_index("date")  → moves the "date" column to become the row index (the row's identifier),
    #                          so you can look up a row by date like: labels_df.loc[date(2026, 2, 6)].

    return labels_df
    # ↑ Returns the completed DataFrame to whoever called this function.


def label_distribution(labels_df: pd.DataFrame) -> pd.DataFrame:
# ↑ A utility function that summarizes the label counts — useful for quick analysis.
#   It answers: "How many days were Long, Short, or Flat in each window?"
#   Parameter:
#     labels_df: pd.DataFrame → the table produced by build_labels() above.
#   -> pd.DataFrame           → returns a small summary table.
    """Return count + pct of Long/Flat/Short for each window."""
    # ↑ Docstring: one line summarizing what the function returns.

    rows = []
    # ↑ Empty list to collect one dict per window (W1 and W2).

    for col in ["window1_label", "window2_label"]:
        # ↑ Loops over the two column names we want to summarize.
        #   On the first pass, col = "window1_label". On the second, col = "window2_label".

        vc = labels_df[col].value_counts().reindex([1, 0, -1], fill_value=0)
        # ↑ Counts how many times each label value (+1, 0, -1) appears in the column.
        #   labels_df[col]         → selects one column (a Series — a list with an index).
        #   .value_counts()        → counts occurrences of each unique value.
        #                            Result might be: {1: 9, -1: 6} (9 Long days, 6 Short days).
        #   .reindex([1, 0, -1])   → forces the result to always have rows for +1, 0, -1 in that order,
        #                            even if one of them has zero occurrences.
        #   fill_value=0           → if a label (e.g., 0 = Flat) has no count, fill it with 0 (not NaN).

        total = len(labels_df)
        # ↑ The total number of trading days — used to compute percentages.
        #   len() on a DataFrame returns the number of rows.

        rows.append({
            "window": col.replace("_label", ""),
            # ↑ Creates a clean window name by removing "_label" from the column name.
            #   col.replace(old, new) → replaces all occurrences of 'old' with 'new' in a string.
            #   "window1_label".replace("_label", "") → "window1".

            "long":  int(vc[1]),
            # ↑ Count of Long (+1) days. vc[1] looks up the count for value 1.
            #   int() converts it to a plain Python integer (from NumPy integer type).

            "flat":  int(vc[0]),
            # ↑ Count of Flat (0) days.

            "short": int(vc[-1]),
            # ↑ Count of Short (-1) days. vc[-1] looks up value -1 (the key is -1, not the last item).

            "long_pct":  round(vc[1]  / total * 100, 1),
            # ↑ Percentage of Long days, e.g. 9/15*100 = 60.0%.
            #   round(number, 1) rounds to 1 decimal place.

            "flat_pct":  round(vc[0]  / total * 100, 1),
            # ↑ Percentage of Flat days.

            "short_pct": round(vc[-1] / total * 100, 1),
            # ↑ Percentage of Short days.
        })

    return pd.DataFrame(rows)
    # ↑ Converts the list of 2 dicts (one per window) into a clean summary DataFrame and returns it.
