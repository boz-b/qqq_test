"""
strategy.py — Rule-based classifier for W1 and W2 window direction.

Each rule returns (signal, rule_name) where signal ∈ {+1, -1, 0}.
Rules are evaluated in priority order; first match wins.
"""
# ↑ Docstring explaining what this file does.
#   This file contains the trading logic (the "brain" of the strategy).
#   It looks at the features for a given day and decides: Long (+1), Short (-1), or Flat (0).
#   It uses a series of "rules" checked in order — the first rule that applies wins.

from __future__ import annotations
# ↑ Enables modern type hint handling. Python reads type annotations as strings,
#   avoiding errors when a type is mentioned before it's fully defined. Safe to ignore as a beginner.

from dataclasses import dataclass
# ↑ Imports 'dataclass', a Python decorator for creating simple data-holding classes with less code.
#   (Imported here but not used directly — it was kept for potential future use.)

from typing import Tuple
# ↑ Imports 'Tuple' from Python's 'typing' module.
#   Tuple is used in type hints to say "this function returns two values together".
#   Example: Tuple[int, str] means a pair of (integer, string) — like (1, "R1_PreOpenSurpriseUp").

import numpy as np
# ↑ NumPy library, aliased as 'np'. Used here for np.sign() which returns -1, 0, or +1
#   depending on whether a number is negative, zero, or positive.

import pandas as pd
# ↑ Pandas library, aliased as 'pd'. Used for pd.Series — a single column/row of data
#   (like one row from our features table, containing all that day's feature values).


Signal = int  # +1 Long, -1 Short, 0 Flat
# ↑ Creates a type alias: 'Signal' is just another name for 'int'.
#   This is purely for readability — when you see 'Signal' in a type hint,
#   you immediately know it means one of: +1 (Long), -1 (Short), or 0 (Flat).
#   Python doesn't enforce this — it's documentation for the programmer.


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
# ↑ Section comment. The functions below are all "private" (start with _) rule functions.
#   Each one examines one row of features and returns either:
#     (signal, rule_name) — a tuple with the trade direction and a label saying which rule fired
#     None                — meaning "this rule does not apply today, try the next one"

def _rule_pre_open_event(row: pd.Series) -> Tuple[Signal, str] | None:
# ↑ RULE 1: Checks if there was a surprising macro event before the market opened.
#   Parameter:
#     row: pd.Series → one row from the features table (all features for a single trading day).
#                      pd.Series is like a dictionary of {column_name: value}.
#   -> Tuple[Signal, str] | None → returns EITHER a (signal, name) pair OR None.
#      The '|' means "or" in type hints (Python 3.10+).
    """
    RULE 1: Pre-open high-impact event with a measurable surprise.
    """
    # ↑ Docstring describing this rule.

    if not row.get("has_pre_open_high_impact", 0):
        # ↑ row.get("key", default) → safely retrieves a value from the row by column name.
        #   If "has_pre_open_high_impact" doesn't exist in the row, it returns 0 (the default).
        #   'not ...' → if the value is 0 (falsy), this condition is True → no pre-open event → skip rule.
        return None
        # ↑ Return None meaning "this rule doesn't apply today".

    score = row.get("event_surprise_score", 0.0)
    # ↑ Gets the event surprise score — how much the economic data differed from forecasts.
    #   Positive score = data came in better than expected (bullish).
    #   Negative score = data came in worse than expected (bearish).
    #   Default 0.0 if the column doesn't exist.

    if score > 0.02:
        # ↑ If the surprise was strongly positive (>2% deviation from forecast), go Long.
        return (1, "R1_PreOpenSurpriseUp")
        # ↑ Returns a tuple: signal=+1 (Long), with the rule name as a label for reporting.
        #   A tuple in Python is written with parentheses: (value1, value2).

    if score < -0.02:
        # ↑ If the surprise was strongly negative (<-2%), go Short.
        return (-1, "R1_PreOpenSurpriseDown")
        # ↑ Signal=-1 (Short), rule name for tracking.

    return (0, "R1_PreOpenNoSurprise")
    # ↑ There WAS a pre-open event, but the surprise wasn't large enough — stay Flat.


def _rule_pm_reversal(row: pd.Series) -> Tuple[Signal, str] | None:
# ↑ RULE 2: Checks if the premarket showed a reversal in direction near the open.
#   A "reversal" means the market was moving one way at 8:59 but reversed by 9:29.
    """
    RULE 2: Premarket reversal with abs gap > 0.5% — follow the 9:29 direction.
    """
    # ↑ If we see a reversal and the gap is meaningful (≥0.5%), we trust the final direction.

    gap = row.get("pm_gap_pct", 0.0)
    # ↑ pm_gap_pct = premarket gap percentage: how much the price moved overnight
    #   vs. the previous day's close. E.g., -0.8 means price is down 0.8% before open.

    if abs(gap) >= 0.5 and row.get("pm_reversal_flag", 0):
        # ↑ Two conditions must BOTH be true (Python 'and' requires both):
        #   abs(gap) >= 0.5    → the absolute value of the gap is at least 0.5% (a meaningful gap).
        #                        abs() turns negative numbers positive: abs(-0.8) = 0.8.
        #   pm_reversal_flag   → this feature is 1 if a direction reversal happened in premarket, 0 if not.
        direction = row.get("pm_direction", 0)
        # ↑ pm_direction is +1 if premarket went up, -1 if it went down (at 9:29 vs prior close).

        name = "R2_ReversalFollow"
        # ↑ A string label to identify which rule fired. Used in reporting/analysis later.

        return (direction, name)
        # ↑ Follow the final premarket direction (whatever direction the reversal ended up at).

    return None
    # ↑ Either the gap was too small or there was no reversal — this rule doesn't apply.


def _rule_strong_gap_accel(row: pd.Series) -> Tuple[Signal, str] | None:
# ↑ RULE 3: Strong gap (≥1%) that is still accelerating in the same direction — ride the momentum.
    """
    RULE 3: Strong gap (≥1%), no reversal, still accelerating — follow gap.
    """

    gap = row.get("pm_gap_pct", 0.0)
    # ↑ Gets the premarket gap percentage.

    if (abs(gap) >= 1.0
            and not row.get("pm_reversal_flag", 0)
            and row.get("pm_momentum_accel", 0) == 1):
        # ↑ Three conditions, all must be True:
        #   abs(gap) >= 1.0              → gap is at least 1% (strong gap).
        #   not pm_reversal_flag         → no reversal happened (market still moving in gap direction).
        #   pm_momentum_accel == 1       → momentum is ACCELERATING (+1 means getting faster, -1 means slowing).
        #   Parentheses () are used to split the condition across multiple lines for readability.

        direction = row.get("pm_direction", 0)
        # ↑ The direction of the gap: +1 (gap up) or -1 (gap down).

        return (direction, "R3_StrongGapAccel")
        # ↑ Follow the gap direction — momentum is still building, likely to continue.

    return None
    # ↑ Conditions not met — rule doesn't apply.


def _rule_strong_gap_decel(row: pd.Series) -> Tuple[Signal, str] | None:
# ↑ RULE 4: Strong gap (≥1%) that is DECELERATING — fade it (trade against the gap).
#   When a strong gap runs out of momentum, it often partially reverses at the open.
    """
    RULE 4: Strong gap (≥1%), decelerating — fade the gap.
    """

    gap = row.get("pm_gap_pct", 0.0)
    # ↑ Gets the premarket gap percentage.

    if (abs(gap) >= 1.0
            and not row.get("pm_reversal_flag", 0)
            and row.get("pm_momentum_accel", 0) == -1):
        # ↑ Same first two conditions as Rule 3, but now pm_momentum_accel == -1 (DECELERATING).
        #   Momentum losing steam on a big gap = likely to reverse at open.

        direction = -row.get("pm_direction", 0)  # fade
        # ↑ FADE means trade in the OPPOSITE direction of the gap.
        #   We negate (flip the sign of) pm_direction with the minus sign:
        #   If gap is up (+1), direction becomes -1 (Short — expect the gap to fill down).
        #   If gap is down (-1), direction becomes +1 (Long — expect a bounce back up).

        return (direction, "R4_StrongGapFade")
        # ↑ Return the fade signal.

    return None


def _rule_moderate_gap_macro(row: pd.Series) -> Tuple[Signal, str] | None:
# ↑ RULE 5: Moderate gap (0.3–1%) on a macro event day — stay Flat.
#   When there's a macro event AND a moderate gap, the outcome is too uncertain to trade.
    """
    RULE 5: Moderate gap (0.3–1%) on a macro event day — stay flat.
    """

    gap = abs(row.get("pm_gap_pct", 0.0))
    # ↑ Takes the ABSOLUTE VALUE of the gap so we don't care about direction here,
    #   only the size. abs(-0.7) = 0.7, abs(0.5) = 0.5.

    if 0.3 <= gap < 1.0 and row.get("has_high_impact_event", 0):
        # ↑ Two conditions:
        #   0.3 <= gap < 1.0         → gap is between 0.3% and 1.0% (moderate, not extreme).
        #                              Python allows "chained comparisons" like this (very readable).
        #   has_high_impact_event    → there's a high-impact macro event today (like CPI, NFP, FOMC).
        return (0, "R5_ModerateGapMacro")
        # ↑ Stay Flat (signal=0) — the macro event makes the direction unpredictable.

    return None


def _rule_small_gap_mean_revert(row: pd.Series) -> Tuple[Signal, str] | None:
# ↑ RULE 6: Small gap (<0.3%), no macro event — trade against yesterday's big move (mean reversion).
#   Mean reversion = after a big day, the next day often partially reverses.
    """
    RULE 6: Small gap (<0.3%), no macro, mean-revert off prior day.
    """

    gap = abs(row.get("pm_gap_pct", 0.0))
    # ↑ Absolute value of the gap (size only, not direction).

    if gap < 0.3 and not row.get("has_high_impact_event", 0):
        # ↑ Both must be true:
        #   gap < 0.3              → very small overnight gap (muted premarket).
        #   not has_high_impact_event → no major macro event today (calmer environment).

        prior = row.get("prior_day_return", 0.0)
        # ↑ prior_day_return = how much the previous day's market moved (open-to-close).
        #   e.g., 0.012 = yesterday went up 1.2%. -0.008 = yesterday fell 0.8%.

        if prior > 0.005:
            # ↑ If yesterday was up more than 0.5%, expect a pullback today → go Short.
            return (-1, "R6_MeanRevertShort")
            # ↑ Short signal: sell, expecting a move down to revert yesterday's gains.

        if prior < -0.005:
            # ↑ If yesterday was down more than 0.5%, expect a bounce today → go Long.
            return (1, "R6_MeanRevertLong")
            # ↑ Long signal: buy, expecting a move up to revert yesterday's losses.

    return None
    # ↑ Either gap was too large, there's a macro event, or yesterday's move was too small
    #   to trigger mean reversion. Rule doesn't apply.


# W2 additional rules
# ↑ The rules below are specifically for Window 2 (10:00–10:30).
#   W2 has different rules because by 10:00 AM, we already KNOW what happened in W1.

def _rule_fomc_flat(row: pd.Series) -> Tuple[Signal, str] | None:
# ↑ W2 Rule: On FOMC days (Federal Reserve rate decisions), always stay Flat.
#   FOMC announcements create extreme unpredictable moves — too risky to trade.
    if row.get("is_fomc_day", 0):
        # ↑ is_fomc_day is 1 if today is a Fed rate decision day, 0 otherwise.
        return (0, "R_FOMC_Flat")
        # ↑ Return Flat (0) regardless of anything else.
    return None
    # ↑ Not an FOMC day — this rule doesn't apply.


def _rule_w2_continuation(row: pd.Series) -> Tuple[Signal, str] | None:
# ↑ W2 Rule: If W1 moved strongly in the same direction as the premarket gap,
#   the momentum is real — continue in W2.
    """
    W2 RULE: Strong W1 momentum aligned with premarket direction — continue.
    """

    w1_ret = row.get("window1_return", 0.0)
    # ↑ The actual return that happened during Window 1 (9:30–10:00).
    #   This is only available for W2 prediction because W1 has already happened.

    pm_dir = row.get("pm_direction", 0)
    # ↑ The premarket direction: +1 (gap up) or -1 (gap down).

    if abs(w1_ret) > 0.002 and int(np.sign(w1_ret)) == pm_dir and pm_dir != 0:
        # ↑ Three conditions:
        #   abs(w1_ret) > 0.002       → W1 moved more than 0.2% (meaningful move, not noise).
        #   int(np.sign(w1_ret)) == pm_dir → W1's direction matches the premarket direction.
        #                                np.sign() returns -1.0, 0.0, or +1.0 (float), int() converts to integer.
        #   pm_dir != 0               → there IS a premarket direction (not a flat/neutral open).
        return (pm_dir, "R_W2_Continuation")
        # ↑ Continue in the same direction in W2 — momentum is confirmed.

    return None


def _rule_w2_fade(row: pd.Series) -> Tuple[Signal, str] | None:
# ↑ W2 Rule: If W1 was a gap-fade trade (Rule 4 fired), continue fading in W2.
#   Gap fades often play out over the full first hour, not just the first 30 minutes.
    """
    W2 RULE: W1 was a gap-fade day — continue fading in W2.
    """

    w1_rule = row.get("w1_rule", "")
    # ↑ The name of the rule that was triggered in W1 (e.g., "R4_StrongGapFade").
    #   Default empty string "" if not available.

    w1_ret = row.get("window1_return", 0.0)
    # ↑ The actual W1 return — used to confirm the fade is working.

    if "GapFade" in str(w1_rule) and abs(w1_ret) > 0.001:
        # ↑ Two conditions:
        #   "GapFade" in str(w1_rule) → checks if the string "GapFade" appears anywhere in the rule name.
        #                               'in' tests for substring membership. str() ensures it's a string.
        #   abs(w1_ret) > 0.001       → W1 actually moved (>0.1%), confirming the fade is working.
        return (int(np.sign(w1_ret)), "R_W2_FadeContinue")
        # ↑ Continue in the same direction as W1's move (the fade is continuing).
        #   np.sign(w1_ret) gives the direction of the W1 move; int() converts it to -1, 0, or +1.

    return None


# ---------------------------------------------------------------------------
# Core classifiers
# ---------------------------------------------------------------------------
# ↑ The two lists below define the ORDER in which rules are evaluated.
#   This is the key design decision: rules listed first have higher priority.

W1_RULES = [
    # ↑ A Python list [] containing the 6 W1 rule functions in priority order.
    #   Note: we store the FUNCTIONS themselves (no parentheses) — not their results.
    #   This lets us call each function later inside the predict loop.
    _rule_pre_open_event,      # Priority 1: macro surprise before open
    _rule_pm_reversal,         # Priority 2: premarket direction reversal
    _rule_strong_gap_accel,    # Priority 3: strong gap + accelerating = follow
    _rule_strong_gap_decel,    # Priority 4: strong gap + decelerating = fade
    _rule_moderate_gap_macro,  # Priority 5: moderate gap + macro event = flat
    _rule_small_gap_mean_revert, # Priority 6: small gap, no macro = mean revert
]

W2_RULES = [
    # ↑ The 4 W2 rules in priority order.
    _rule_fomc_flat,          # Priority 1: FOMC days are always flat
    _rule_pre_open_event,     # Priority 2: macro event still matters for W2
    _rule_w2_continuation,    # Priority 3: W1 momentum continuing
    _rule_w2_fade,            # Priority 4: W1 gap-fade continuing
]


def predict_w1(row: pd.Series) -> Tuple[Signal, str]:
# ↑ Runs all W1 rules on a single day's feature row and returns the first matching rule's signal.
#   Parameter:
#     row: pd.Series → one row from the features table (all features for one day).
#   -> Tuple[Signal, str] → always returns a (signal, rule_name) pair (never None).
    """Return (signal, rule_name) for Window 1."""

    for rule in W1_RULES:
        # ↑ Loops through the list of rule functions one by one.
        #   'rule' is each function object on each iteration.

        result = rule(row)
        # ↑ CALLS the rule function, passing the row as the argument.
        #   If rule is _rule_pre_open_event, this is equivalent to: _rule_pre_open_event(row).
        #   result is either a (signal, name) tuple or None.

        if result is not None:
            # ↑ If the rule returned something (not None), it matched — we have our signal.
            return result
            # ↑ Return immediately. The first matching rule wins. No lower-priority rules are checked.

    return (0, "DEFAULT_Flat")
    # ↑ If we reach here, no rule matched — default to Flat (no trade).
    #   This is the safety net: when nothing applies, do nothing.


def predict_w2(row: pd.Series) -> Tuple[Signal, str]:
# ↑ Same pattern as predict_w1 but uses the W2 rules list.
#   The row should contain W1 result columns (window1_return, w1_pred, w1_rule)
#   because W2 rules can look at what happened in W1.
    """
    Return (signal, rule_name) for Window 2.

    row should include W1 result columns: window1_return, w1_pred, w1_rule.
    """

    for rule in W2_RULES:
        # ↑ Loop through W2 rules in priority order.
        result = rule(row)
        # ↑ Call the rule function with the enriched row.
        if result is not None:
            # ↑ First match wins.
            return result

    return (0, "DEFAULT_Flat")
    # ↑ Default: Flat if no W2 rule matches.


def predict_batch(features_df: pd.DataFrame,
                  labels_df: pd.DataFrame | None = None) -> pd.DataFrame:
# ↑ The main public function — runs the entire strategy over ALL trading days at once.
#   Parameters:
#     features_df: pd.DataFrame      → the full features table (one row per day).
#     labels_df: pd.DataFrame | None → the actual W1 returns (optional).
#                                      '| None' means this argument can be None (not provided).
#                                      '= None' means None is the default if caller doesn't pass it.
#   -> pd.DataFrame                  → returns a table of predictions for every day.
    """
    Run classifier over all dates in features_df.

    If labels_df is provided, actual W1 return is included as a W2 input
    (simulating real-time W2 prediction made at 10:00 after observing W1).

    Returns DataFrame: [date, w1_pred, w1_rule, w2_pred, w2_rule]
    """
    # ↑ Important note: when we predict W2, we "cheat" slightly in a realistic way —
    #   we use the actual W1 return (which we know at 10:00 AM) to inform the W2 decision.
    #   This simulates real trading: at 10:00 AM you DO know what happened in the 9:30–10:00 window.

    records = []
    # ↑ Empty list to collect one dict per day (will become the output table).

    for d, row in features_df.iterrows():
        # ↑ .iterrows() iterates over the DataFrame row by row.
        #   On each pass:
        #     d   → the index value (the date, e.g., date(2026, 2, 6)).
        #     row → a pd.Series containing all feature values for that day.

        row = row.copy()
        # ↑ Makes a COPY of the row so we can safely add new columns to it without
        #   modifying the original features_df. In Pandas, modifying a slice can
        #   cause a "SettingWithCopyWarning" — .copy() prevents that.

        # W1
        w1_pred, w1_rule = predict_w1(row)
        # ↑ Calls predict_w1() to get the W1 signal and rule name.
        #   Python "tuple unpacking": if predict_w1 returns (1, "R3_StrongGapAccel"),
        #   then w1_pred = 1 and w1_rule = "R3_StrongGapAccel" simultaneously.

        # W2: enrich row with W1 prediction + actual W1 return (if available)
        # ↑ Before predicting W2, we add W1 results into the row so W2 rules can use them.
        row["w1_pred"] = w1_pred
        # ↑ Adds the W1 prediction as a new field in the row dictionary-like Series.

        row["w1_rule"] = w1_rule
        # ↑ Adds the W1 rule name to the row.

        if labels_df is not None and d in labels_df.index:
            # ↑ Two conditions:
            #   labels_df is not None → we were given actual labels (we have real W1 returns).
            #   d in labels_df.index  → this specific date exists in the labels table.
            #   'in' checks membership — does 'd' appear as a row index in labels_df?
            row["window1_return"] = labels_df.loc[d, "window1_return"]
            # ↑ Adds the ACTUAL W1 return to the row.
            #   labels_df.loc[d, "window1_return"] → .loc[] selects by label: row 'd', column "window1_return".
        else:
            row["window1_return"] = 0.0
            # ↑ No actual labels available — default W1 return to 0.0.

        w2_pred, w2_rule = predict_w2(row)
        # ↑ Now predict W2, using the enriched row that includes W1 information.

        records.append({
            # ↑ Build one result dictionary for this day.
            "date":    d,
            # ↑ The trading date.
            "w1_pred": w1_pred,
            # ↑ W1 signal: +1, -1, or 0.
            "w1_rule": w1_rule,
            # ↑ Which rule fired for W1 (e.g., "R3_StrongGapAccel").
            "w2_pred": w2_pred,
            # ↑ W2 signal: +1, -1, or 0.
            "w2_rule": w2_rule,
            # ↑ Which rule fired for W2.
        })

    return pd.DataFrame(records).set_index("date")
    # ↑ Converts list of dicts to a DataFrame, makes 'date' the index, and returns it.
    #   Result: one row per trading day, columns = w1_pred, w1_rule, w2_pred, w2_rule.
