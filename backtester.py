"""
backtester.py — Simulation engine + performance metrics.

Assumptions
-----------
- Entry / exit at window open / close (market order at 1-min bar prices)
- Position size: 1% of current capital per trade (fixed-fractional)
- Slippage: 0.05% per side (applied to entry and exit)
- No commissions
- Starting capital: $100,000
- Flat signal → no trade, no cost
"""
# ↑ Docstring listing all the simulation assumptions.
#   A "backtester" simulates how a trading strategy would have performed using historical data.
#   Instead of risking real money, we replay past days and calculate hypothetical profit/loss.
#   Key terms:
#     Position size: how much money you put into each trade.
#     Slippage: the difference between the price you expect to get and the price you actually get.
#               Real markets don't let you trade at exactly the displayed price — you lose a tiny bit.
#     Fixed-fractional: always bet the same percentage of your current capital (here: 1%).

from __future__ import annotations
# ↑ Enables modern type hint evaluation. Safe to ignore as a beginner.

import numpy as np
# ↑ NumPy for math operations: np.sqrt() (square root), np.nan (Not a Number placeholder),
#   np.isnan() (check if something is NaN/missing).

import pandas as pd
# ↑ Pandas for building and manipulating the trades DataFrame (result table).


STARTING_CAPITAL = 100_000.0
# ↑ The simulated starting account balance: $100,000.
#   Python allows underscores in numbers for readability: 100_000 is the same as 100000.
#   The .0 makes it a float (decimal number) instead of an integer.

POSITION_PCT = 0.01
# ↑ Position size: 1% of current capital per trade.
#   e.g., if capital = $100,000 → position = $100,000 × 0.01 = $1,000 per trade.

SLIPPAGE_PCT = 0.0005
# ↑ Slippage per trade side: 0.05%.
#   Since we enter AND exit every trade, total slippage per trade = 2 × 0.05% = 0.10%.
#   e.g., on a $1,000 position → slippage cost = $1,000 × 0.0010 = $1.00 per trade.


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def run(features_df: pd.DataFrame,
        labels_df: pd.DataFrame,
        predictions_df: pd.DataFrame,
        window: int = 1) -> pd.DataFrame:
# ↑ The main simulation function. Replays every trading day and calculates profit/loss.
#   Parameters:
#     features_df: pd.DataFrame    → the features table (one row per day, indexed by date).
#     labels_df: pd.DataFrame      → the actual price returns and direction labels (ground truth).
#     predictions_df: pd.DataFrame → the strategy's signals (from strategy.predict_batch).
#     window: int = 1              → which window to simulate: 1 = W1 (9:30–10:00), 2 = W2 (10:00–10:30).
#   -> pd.DataFrame                → returns a trades table with one row per day, including PnL.
    """
    Simulate trades for the given window (1 or 2).

    Parameters
    ----------
    features_df    : feature rows indexed by date
    labels_df      : window returns + labels indexed by date
    predictions_df : strategy signals indexed by date (from strategy.predict_batch)
    window         : 1 → W1, 2 → W2

    Returns
    -------
    trades_df : [date, signal, actual_label, correct, gross_ret,
                 slippage, net_ret, pnl, capital, cumulative_pnl, rule_triggered]
    """

    assert window in (1, 2), "window must be 1 or 2"
    # ↑ 'assert' checks that a condition is True. If False, it raises an AssertionError and stops.
    #   This is a "guard" — catching programmer mistakes early with a helpful message.
    #   If someone calls run(..., window=3), they get: AssertionError: window must be 1 or 2.

    pred_col  = f"w{window}_pred"
    # ↑ Builds the column name dynamically using an f-string.
    #   If window=1: pred_col = "w1_pred". If window=2: pred_col = "w2_pred".
    #   This avoids writing the same code twice for W1 and W2.

    rule_col  = f"w{window}_rule"
    # ↑ Column name for the rule that fired: "w1_rule" or "w2_rule".

    ret_col   = f"window{window}_return"
    # ↑ Column name for the actual return: "window1_return" or "window2_return".

    label_col = f"window{window}_label"
    # ↑ Column name for the actual direction label: "window1_label" or "window2_label".

    capital = STARTING_CAPITAL
    # ↑ Initialize the simulated account balance to $100,000.
    #   This will grow or shrink with each trade's profit or loss.

    records = []
    # ↑ Empty list to collect one result dictionary per trading day.

    common_dates = sorted(
        set(labels_df.index) & set(predictions_df.index) & set(features_df.index)
    )
    # ↑ Finds dates that exist in ALL THREE tables simultaneously.
    #   set(labels_df.index)       → a set of all dates in labels.
    #   & set(predictions_df.index) → intersection: keep only dates in BOTH.
    #   & set(features_df.index)    → intersection again: only dates in all three.
    #   set intersection (&) is like a Venn diagram overlap.
    #   sorted(...)                → sorts the result chronologically.
    #   This prevents errors from mismatched dates across the three tables.

    for d in common_dates:
        # ↑ Loop over every date that has data in all three tables.

        signal = int(predictions_df.loc[d, pred_col])
        # ↑ Gets the strategy's signal for this day: +1 (Long), -1 (Short), or 0 (Flat).
        #   predictions_df.loc[d, pred_col] → .loc[row, column] selects by label.
        #     d          → the date (row label).
        #     pred_col   → the column name (e.g., "w1_pred").
        #   int(...)     → converts to integer (Pandas values are sometimes NumPy types).

        rule = str(predictions_df.loc[d, rule_col])
        # ↑ Gets the rule name that fired for this day (e.g., "R3_StrongGapAccel").
        #   str(...) → converts to a plain Python string.

        actual_ret = float(labels_df.loc[d, ret_col])
        # ↑ Gets the ACTUAL price return that happened during the window (the ground truth).
        #   e.g., 0.0032 means price went up 0.32%. -0.0015 means down 0.15%.
        #   float(...) → converts to a standard Python decimal number.

        actual_label = int(labels_df.loc[d, label_col])
        # ↑ Gets the actual direction label: +1, -1, or 0.
        #   Used to determine if our prediction was correct.

        if signal == 0:
            # ↑ If the strategy said "Flat" (no trade), record the day with zero profit/loss.
            records.append({
                # ↑ Adds a dictionary to our results list for this day.
                "date":           d,
                # ↑ The trading date.
                "signal":         0,
                # ↑ Signal was 0 (Flat).
                "actual_label":   actual_label,
                # ↑ What the market actually did (+1, -1, or 0).
                "correct":        None,
                # ↑ None (null) because we didn't trade — correctness is not applicable.
                "gross_ret":      0.0,
                # ↑ No return since we didn't trade.
                "slippage":       0.0,
                # ↑ No slippage — we didn't execute any orders.
                "net_ret":        0.0,
                # ↑ Net return is also 0.
                "pnl":            0.0,
                # ↑ Profit and Loss (PnL) = $0 for a flat day.
                "capital":        capital,
                # ↑ Capital unchanged (still the same as before this day).
                "cumulative_pnl": capital - STARTING_CAPITAL,
                # ↑ Total profit/loss from the start of the simulation to now.
                #   If capital=$100,500, cumulative_pnl = 100,500 - 100,000 = $500.
                "rule_triggered": rule,
                # ↑ The rule name (e.g., "DEFAULT_Flat" for flat days).
            })
            continue
            # ↑ Skip the rest of the loop body — go to the next day.

        position_value = capital * POSITION_PCT
        # ↑ Calculates how much money to put into this trade.
        #   e.g., capital=$100,000 × 0.01 = $1,000.
        #   As capital grows or shrinks from previous trades, position size adjusts accordingly.
        #   This is the "fixed-fractional" position sizing method.

        # Gross return earned (sign adjusted for long/short)
        gross_ret = signal * actual_ret
        # ↑ Calculates the gross (before costs) return earned on this trade.
        #   signal=+1 (Long):  gross_ret = +1 × actual_ret → positive if market went up.
        #   signal=-1 (Short): gross_ret = -1 × actual_ret → positive if market went DOWN.
        #   Multiplying by signal flips the sign correctly for short trades.
        #   Example: actual_ret=-0.005 (market fell 0.5%), signal=-1 (Short) → gross_ret=+0.005 (profit!).

        # Slippage: paid on both entry and exit legs
        slippage_cost = 2 * SLIPPAGE_PCT
        # ↑ Total slippage cost = 2 sides × 0.05% = 0.10%.
        #   We pay slippage when we BUY (entry) and again when we SELL (exit).

        net_ret = gross_ret - slippage_cost
        # ↑ Net return = gross return minus slippage cost.
        #   Even a winning trade earns slightly less due to slippage.

        pnl = position_value * net_ret
        # ↑ Dollar profit/loss = position size × net return rate.
        #   e.g., position=$1,000 × net_ret=0.003 = $3.00 profit.
        #   If net_ret is negative, pnl is negative (a loss).

        capital += pnl
        # ↑ Updates the account balance with this trade's result.
        #   += is shorthand for: capital = capital + pnl.
        #   A profit increases capital; a loss decreases it.

        correct = (signal == actual_label) if actual_label != 0 else None
        # ↑ Determines if the prediction was correct.
        #   signal == actual_label → True if we predicted the right direction.
        #   'if actual_label != 0' → only meaningful when the market actually moved (not flat).
        #   'else None'            → if the market was flat (actual_label=0), correctness is ambiguous.
        #   This is another ternary expression: value_if_true if condition else value_if_false.

        records.append({
            # ↑ Records this trade day's full details.
            "date":           d,
            "signal":         signal,
            # ↑ What the strategy predicted: +1 or -1.
            "actual_label":   actual_label,
            # ↑ What the market actually did: +1, -1, or 0.
            "correct":        correct,
            # ↑ True if prediction matched reality, False if wrong, None if market was flat.
            "gross_ret":      gross_ret,
            # ↑ Return before slippage.
            "slippage":       slippage_cost,
            # ↑ Total slippage paid (0.10%).
            "net_ret":        net_ret,
            # ↑ Return after slippage.
            "pnl":            pnl,
            # ↑ Dollar profit or loss for this trade.
            "capital":        capital,
            # ↑ Account balance AFTER this trade.
            "cumulative_pnl": capital - STARTING_CAPITAL,
            # ↑ Total profit/loss since the simulation started.
            "rule_triggered": rule,
            # ↑ Which rule fired (e.g., "R3_StrongGapAccel").
        })

    return pd.DataFrame(records).set_index("date")
    # ↑ Converts the list of trade dictionaries into a DataFrame.
    #   .set_index("date") → makes the date column the row index.
    #   Returns the complete trades table.


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_metrics(trades_df: pd.DataFrame,
                    features_df: pd.DataFrame | None = None) -> dict:
# ↑ Calculates performance statistics from the trades simulation results.
#   Parameters:
#     trades_df: pd.DataFrame         → the output from run() — one row per trading day.
#     features_df: pd.DataFrame | None → optional features table, used to break down
#                                        performance by macro days vs regular days.
#   -> dict                           → returns a dictionary of metric name → value.
    """
    Compute aggregate performance metrics from trades_df.

    Returns a dict with scalar metrics plus per-rule and per-event-type breakdowns.
    """

    active = trades_df[trades_df["signal"] != 0].copy()
    # ↑ Filters to only the rows where we actually traded (signal != 0).
    #   Flat days (signal=0) had no trade and contribute nothing to performance metrics.
    #   trades_df["signal"] != 0 → True/False mask: True where we placed a trade.
    #   .copy() → makes a copy to avoid the Pandas "SettingWithCopyWarning" when we modify later.

    if active.empty:
        # ↑ If there were zero active trades (strategy never fired), return an error message.
        return {"error": "No active trades found."}
        # ↑ Returns a dict with just an error key. The caller can check for this.

    wins  = active[active["net_ret"] > 0]
    # ↑ Filters to only winning trades (positive net return after slippage).
    losses = active[active["net_ret"] <= 0]
    # ↑ Filters to only losing trades (zero or negative net return).
    #   Note: a trade with exactly 0 return (very rare) is counted as a loss here.

    win_rate = len(wins) / len(active) if len(active) > 0 else 0.0
    # ↑ Win rate = number of winning trades / total trades.
    #   e.g., 4 wins out of 5 trades = 0.80 = 80%.
    #   The ternary 'if len(active) > 0 else 0.0' prevents division by zero
    #   (though we already handled the empty case above).

    gross_profit = wins["pnl"].sum()
    # ↑ Total dollar profit from all winning trades combined.
    #   wins["pnl"] → the pnl column for winning trades only.
    #   .sum()      → adds up all values in the column.

    gross_loss = abs(losses["pnl"].sum())
    # ↑ Total dollar loss from all losing trades combined, as a POSITIVE number.
    #   losses["pnl"].sum() → would be negative (e.g., -$45).
    #   abs(...) → takes the absolute value to make it positive: $45.

    profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.nan
    # ↑ Profit Factor = total wins / total losses.
    #   e.g., gross_profit=$90, gross_loss=$45 → profit_factor = 2.0 (made $2 for every $1 lost).
    #   A profit factor above 1.0 means the strategy is profitable overall.
    #   np.nan → "Not a Number" — used when there are no losses (can't divide by zero).

    # Sharpe ratio (annualised, assume ~252 trading days/year)
    # ↑ The Sharpe Ratio measures risk-adjusted return. Higher is better.
    #   A Sharpe > 1.0 is generally considered good; > 2.0 is excellent.
    #   Formula: (average daily return / standard deviation of returns) × sqrt(252).
    #   Multiplying by sqrt(252) "annualizes" the ratio from daily to yearly scale.
    daily_rets = active["net_ret"]
    # ↑ The net return for each active (traded) day — a Series of decimal returns.

    sharpe = (daily_rets.mean() / daily_rets.std() * np.sqrt(252)
              if daily_rets.std() > 0 else np.nan)
    # ↑ Calculates the annualized Sharpe Ratio.
    #   daily_rets.mean() → average daily return across all active trades.
    #   daily_rets.std()  → standard deviation of daily returns (measures volatility/risk).
    #   np.sqrt(252)      → square root of 252 ≈ 15.87 (the annualization factor).
    #   'if daily_rets.std() > 0' → prevents division by zero if all returns are identical.
    #   np.nan            → used when std=0 (Sharpe is undefined in that edge case).

    # Max drawdown on cumulative PnL curve
    # ↑ Max Drawdown = the largest peak-to-trough decline in account value during the simulation.
    #   It measures the worst losing streak the strategy experienced.
    cum = trades_df["cumulative_pnl"]
    # ↑ The cumulative PnL column — how total profit/loss changed day by day.
    #   Note: uses ALL days (including flat), not just 'active', to see the full equity curve.

    rolling_max = cum.cummax()
    # ↑ .cummax() computes the running maximum — the highest cumulative PnL seen UP TO each day.
    #   e.g., if PnL went [0, 100, 150, 120, 80, 200], cummax = [0, 100, 150, 150, 150, 200].
    #   This represents the "peak" of the equity curve up to each point in time.

    drawdown = cum - rolling_max
    # ↑ Drawdown at each day = current PnL minus the peak PnL.
    #   This is always ≤ 0 (you're always either at the peak or below it).
    #   e.g., peak=150, current=80 → drawdown = 80 - 150 = -70 (down $70 from peak).

    max_drawdown = float(drawdown.min())
    # ↑ The MAXIMUM (worst) drawdown — the most negative value in the drawdown series.
    #   .min() finds the smallest (most negative) value.
    #   float() converts from NumPy type to plain Python float.
    #   e.g., -70.0 means the strategy fell $70 from its peak at its worst point.

    total_pnl = float(trades_df["pnl"].sum())
    # ↑ Total net profit/loss across all days (both active and flat).
    #   This is the bottom-line result: positive = profitable, negative = loss.

    total_trades = int(len(active))
    # ↑ Total number of days where a trade was placed (signal != 0).
    #   int() converts from NumPy integer to plain Python int.

    metrics = {
        # ↑ Builds the main metrics dictionary. Each key is a metric name; each value is the result.
        "total_trades":  total_trades,
        # ↑ How many trades were placed in total.

        "win_rate":      round(win_rate * 100, 1),
        # ↑ Win rate as a percentage, rounded to 1 decimal place.
        #   win_rate × 100 converts decimal to percent: 0.80 → 80.0.

        "profit_factor": round(profit_factor, 2) if not np.isnan(profit_factor) else "N/A",
        # ↑ Profit factor rounded to 2 decimal places.
        #   np.isnan(profit_factor) → True if it's NaN (no losses).
        #   'if not np.isnan(...)' → only round if it's a real number; otherwise use "N/A".

        "sharpe":        round(sharpe, 2) if not np.isnan(sharpe) else "N/A",
        # ↑ Sharpe ratio rounded to 2 decimal places, or "N/A" if undefined.

        "max_drawdown":  round(max_drawdown, 2),
        # ↑ Maximum drawdown in dollars, rounded to 2 decimal places. Will be negative or 0.

        "total_pnl":     round(total_pnl, 2),
        # ↑ Total profit/loss in dollars.

        "final_capital": round(STARTING_CAPITAL + total_pnl, 2),
        # ↑ The final account balance after the simulation.
        #   e.g., $100,000 + $450 = $100,450.
    }

    # Per-rule breakdown
    # ↑ Breaks down performance by which strategy rule fired — tells us which rules work best.
    rule_breakdown = []
    # ↑ Empty list to collect one dict per rule.

    for rule, grp in active.groupby("rule_triggered"):
        # ↑ .groupby("rule_triggered") groups the active trades DataFrame by the rule name.
        #   On each iteration:
        #     rule → the rule name string (e.g., "R3_StrongGapAccel").
        #     grp  → a DataFrame containing only the rows where that rule fired.
        #   This lets us calculate stats separately for each rule.

        r_wins = grp[grp["net_ret"] > 0]
        # ↑ Filters to winning trades within this rule's group.

        rule_breakdown.append({
            "rule":      rule,
            # ↑ The rule name.
            "trades":    len(grp),
            # ↑ How many times this rule fired.
            "win_rate":  round(len(r_wins) / len(grp) * 100, 1),
            # ↑ Win rate for this specific rule (as a percentage).
            "total_pnl": round(grp["pnl"].sum(), 2),
            # ↑ Total dollar profit/loss generated by this rule.
        })

    metrics["by_rule"] = pd.DataFrame(rule_breakdown).sort_values("total_pnl", ascending=False)
    # ↑ Adds the per-rule breakdown table to the metrics dictionary.
    #   pd.DataFrame(rule_breakdown) → converts list of dicts to a DataFrame.
    #   .sort_values("total_pnl", ascending=False) → sorts by PnL, best rule first.
    #   ascending=False → largest values first (most profitable rule at the top).

    # Event-type breakdown: macro day vs regular day (requires features_df)
    # ↑ Splits performance into "macro days" (days with high-impact economic news)
    #   vs "regular days" (no major events). Tells us if we perform better or worse on news days.
    if features_df is not None and "has_high_impact_event" in features_df.columns:
        # ↑ Only calculate this if:
        #   features_df is not None          → we were given the features table.
        #   "has_high_impact_event" in ...   → the macro feature column exists in it.
        #   'and' requires BOTH to be True.

        common = trades_df.index.intersection(features_df.index)
        # ↑ Finds dates that exist in BOTH tables.
        #   .intersection() is like set intersection — keeps only shared dates.

        feat_aligned = features_df.loc[common, "has_high_impact_event"]
        # ↑ Gets the "has_high_impact_event" column for only the common dates.
        #   .loc[rows, column] → selects by label.
        #   Values are 1 (macro day) or 0 (regular day).

        for label, mask in [("macro_day",   feat_aligned == 1),
                             ("regular_day", feat_aligned != 1)]:
            # ↑ Loops over two (label, mask) pairs:
            #   ("macro_day",   feat_aligned == 1) → macro days where has_high_impact_event is 1.
            #   ("regular_day", feat_aligned != 1) → regular days where it's 0.
            #   Each iteration: 'label' is the string name, 'mask' is a True/False Series.

            sub = active[active.index.isin(feat_aligned[mask].index)]
            # ↑ Filters the active trades to only the days matching this mask.
            #   feat_aligned[mask]      → dates where the condition is True.
            #   .index                  → just the date labels.
            #   active.index.isin(...)  → True/False: is each active date in our filtered date list?
            #   active[...]             → keeps only matching active trade rows.

            if not sub.empty:
                # ↑ Only calculate if there are trades to analyze for this category.
                sw = sub[sub["net_ret"] > 0]
                # ↑ Winning trades within this category.
                metrics[f"win_rate_{label}"] = round(len(sw) / len(sub) * 100, 1)
                # ↑ Win rate for this day type, stored with a dynamic key.
                #   f"win_rate_{label}" → "win_rate_macro_day" or "win_rate_regular_day".
                metrics[f"trades_{label}"] = len(sub)
                # ↑ Trade count for this day type: "trades_macro_day" or "trades_regular_day".

    return metrics
    # ↑ Returns the complete metrics dictionary. Contains both scalar values and DataFrames.
