# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

All source files live at the **project root** (no `src/` subdirectory):

```
qqq_test/
├── data_loader.py   # yfinance fetching + CSV caching
├── features.py      # premarket + macro feature engineering
├── labeler.py       # ground-truth W1/W2 direction labels
├── strategy.py      # rule-based classifier (W1 + W2)
├── backtester.py    # simulation engine + metrics
├── ff_scraper.py    # ForexFactory calendar scraper (CLI)
├── __init__.py
├── requirements.txt
└── CLAUDE.md
```

> **Important**: Data CSV files are written to a `data/` directory **two levels up** from the project root because `data_loader.py` uses `Path(__file__).parent.parent / "data"`. This path convention was designed for a `src/` layout. If the files are at root, `DATA_DIR` resolves to the **parent of the project root**. Keep this in mind when verifying where cached data lives.

## Common Commands

```bash
# Activate environment (always required first)
source venv/bin/activate

# Refresh all data (intraday + daily; FF events must be scraped separately)
python3 -c "from data_loader import DataLoader; DataLoader().fetch_all()"

# Fetch FF macro events for a date range
python -m ff_scraper --start YYYY-MM-DD --end YYYY-MM-DD \
  --csv data/ff_events.csv --currencies USD

# Launch notebooks
jupyter notebook

# Run a quick smoke test (no test framework — use interactive Python)
python3 -c "
from data_loader import DataLoader
from features import build_features
from labeler import build_labels
from strategy import predict_batch
from backtester import run, compute_metrics

dl = DataLoader()
intra, daily, ff = dl.load_intraday(), dl.load_daily(), dl.load_ff_events()
feat = build_features(intra, daily, ff)
labels = build_labels(intra)
preds = predict_batch(feat, labels)
trades = run(feat, labels, preds, window=1)
print(compute_metrics(trades, feat))
"
```

## Architecture

### Data Flow (one row per trading day)
```
yfinance 1-min bars → data_loader.py → features.py → strategy.py → backtester.py
ForexFactory events ↗                ↗               ↗
yfinance daily bars ──────────────→ features.py
                                    labeler.py → ground truth W1/W2 labels
```

### Key Timing Conventions
- **All timestamps are Eastern (America/New_York)**, DST-aware throughout
- **Premarket** = 8:00–9:29 ET; **W1** = 9:30–10:00 ET; **W2** = 10:00–10:30 ET
- CSV timestamps have mixed DST offsets → always load with `pd.to_datetime(..., utc=True).tz_convert(EASTERN)`

---

## Module Reference

### `data_loader.py` — Caching & Yahoo Limits

**Key constants:**
- `DATA_DIR = Path(__file__).parent.parent / "data"` — resolves relative to file location
- `INTRADAY_STALE_HOURS = 4`, daily staleness = 24 hours
- `SYMBOL = "QQQ"`

**Public API:**
- `fetch_intraday(symbol, days=28)` — downloads 1-min bars in 7-day chunks, saves to CSV
- `load_intraday(force_refresh=False)` — returns cached data or re-fetches if stale
- `fetch_daily(symbol, period="2y")` — downloads daily OHLCV
- `load_daily(force_refresh=False)` — returns cached daily bars
- `load_ff_events()` — loads ForexFactory CSV; returns empty DataFrame (correct schema) if file missing
- `DataLoader().fetch_all()` — convenience: calls `fetch_intraday()` + `fetch_daily()`, prints reminder if FF CSV is absent

**Yahoo Finance limits:**
- 1-min data: max 30 calendar days, max 7 days per request → fetched in 7-day chunks, `days` capped at 29
- Daily data: full `period` (e.g., "2y") in one request — no chunk limit

**Timezone handling:**
- `_to_eastern(df)` — converts any naive or UTC index to Eastern
- Always read CSV with `pd.to_datetime(..., utc=True).tz_convert(EASTERN)` to handle DST-mixed offsets

---

### `features.py` — One Row Per Day

**Entry point:** `build_features(intraday_df, daily_df, ff_events_df) → pd.DataFrame`

Output index = `date` (Python `date` object), one column per feature:

| Feature | Description |
|---|---|
| `pm_gap_pct` | `(price_929 - prior_close) / prior_close × 100` |
| `pm_direction` | +1 / -1 / 0 — sign of the gap |
| `pm_momentum_score` | `late_move / (abs(early_move) + 0.001)` where early = 8:00–8:44, late = 8:45–9:29 |
| `pm_momentum_accel` | +1 (accelerating), -1 (decelerating/reversing), 0 (no movement) |
| `pm_reversal_flag` | 1 if direction at 8:59 vs prior close flipped by 9:29 |
| `prior_day_return` | `(prior_close - prior_open) / prior_open` |
| `has_high_impact_event` | 1 if any USD high-impact event today |
| `has_pre_open_high_impact` | 1 if high-impact event before 9:30 ET |
| `has_post_open_high_impact` | 1 if high-impact event at or after 9:30 ET |
| `is_fomc_day` | 1 for FOMC statement / rate decision / press conference |
| `is_cpi_day` | 1 for CPI / Consumer Price Index release |
| `is_nfp_day` | 1 for Non-Farm Payrolls / employment change release |
| `event_surprise_score` | Mean `(actual - forecast) / abs(forecast)` across all events with valid data |

**Private helpers:** `_time_slice()`, `_last_close()`, `_first_close()`, `_premarket_features()`, `_macro_features()`

**FOMC detection keywords:** `"fomc statement"`, `"fomc meeting minutes"`, `"federal funds rate"`, `"fomc press conference"`, `"monetary policy statement"` — routine Fed member speeches are NOT flagged.

---

### `labeler.py` — Ground Truth Labels

**Entry point:** `build_labels(intraday_df, threshold=0.0) → pd.DataFrame`

Output columns (index = `date`):

| Column | Description |
|---|---|
| `window1_return` | `(last_close - first_close) / first_close` for 9:30–10:00 |
| `window1_label` | +1 / -1 / 0 based on `window1_return` vs `threshold` |
| `window2_return` | Same calculation for 10:00–10:30 |
| `window2_label` | +1 / -1 / 0 for W2 |

**Utility:** `label_distribution(labels_df)` → small summary DataFrame with Long/Flat/Short counts and percentages for each window.

---

### `strategy.py` — Rule Priority Order

Signals: `+1` = Long, `-1` = Short, `0` = Flat. **First match wins.** Default = `(0, "DEFAULT_Flat")`.

**W1 rules** (`W1_RULES` list, evaluated in order):

| Priority | Rule | Condition | Signal |
|---|---|---|---|
| 1 | `R1_PreOpenSurpriseUp/Down/NoSurprise` | `has_pre_open_high_impact` AND `event_surprise_score > ±0.02` | follow surprise |
| 2 | `R2_ReversalFollow` | `abs(pm_gap_pct) >= 0.5` AND `pm_reversal_flag` | follow `pm_direction` |
| 3 | `R3_StrongGapAccel` | `abs(gap) >= 1.0` AND no reversal AND `pm_momentum_accel == 1` | follow gap |
| 4 | `R4_StrongGapFade` | `abs(gap) >= 1.0` AND no reversal AND `pm_momentum_accel == -1` | fade gap |
| 5 | `R5_ModerateGapMacro` | `0.3 <= abs(gap) < 1.0` AND `has_high_impact_event` | Flat |
| 6 | `R6_MeanRevertLong/Short` | `abs(gap) < 0.3` AND no macro AND `abs(prior_day_return) > 0.005` | mean-revert prior day |

**W2 rules** (`W2_RULES` list, evaluated in order):

| Priority | Rule | Condition | Signal |
|---|---|---|---|
| 1 | `R_FOMC_Flat` | `is_fomc_day` | Flat |
| 2 | `R1_PreOpenSurprise*` | same as W1 Rule 1 | follow surprise |
| 3 | `R_W2_Continuation` | `abs(window1_return) > 0.002` AND W1 direction matches `pm_direction` | continue |
| 4 | `R_W2_FadeContinue` | W1 rule was a GapFade AND `abs(window1_return) > 0.001` | continue fade |

**Public API:**
- `predict_w1(row: pd.Series) → (signal, rule_name)`
- `predict_w2(row: pd.Series) → (signal, rule_name)` — row must include `window1_return`, `w1_pred`, `w1_rule`
- `predict_batch(features_df, labels_df=None) → pd.DataFrame` with columns `w1_pred`, `w1_rule`, `w2_pred`, `w2_rule`

---

### `backtester.py` — Simulation Assumptions

**Constants:**
- Starting capital: `$100,000` (`STARTING_CAPITAL`)
- Position size: 1% of current capital (`POSITION_PCT = 0.01`)
- Slippage: 0.05% per side, 0.10% round-trip (`SLIPPAGE_PCT = 0.0005`)
- No commissions; Flat signal = no trade, no cost

**`run(features_df, labels_df, predictions_df, window=1) → pd.DataFrame`**

Output columns: `signal`, `actual_label`, `correct`, `gross_ret`, `slippage`, `net_ret`, `pnl`, `capital`, `cumulative_pnl`, `rule_triggered`

**`compute_metrics(trades_df, features_df=None) → dict`**

Scalar keys: `total_trades`, `win_rate` (%), `profit_factor`, `sharpe` (annualized √252), `max_drawdown` ($), `total_pnl` ($), `final_capital` ($)

Composite keys:
- `by_rule` — `pd.DataFrame` with per-rule `trades`, `win_rate`, `total_pnl`, sorted by PnL
- `win_rate_macro_day` / `win_rate_regular_day` — split by `has_high_impact_event` (requires `features_df`)

---

### `ff_scraper.py` — ForexFactory Calendar Scraper

Uses `cloudscraper` (Cloudflare bypass) + `BeautifulSoup`. No Selenium, no ChromeDriver.

**Impact CSS class decoding:**

| CSS class | Impact level |
|---|---|
| `icon--ff-impact-red` | High Impact Expected |
| `icon--ff-impact-ora` | Medium Impact Expected |
| `icon--ff-impact-yel` | Low Impact Expected |
| `icon--ff-impact-gry` | Non-Economic |

**Public API:**
- `fetch_day(scraper, day) → list[dict]` — fetches one calendar day
- `scrape_range(start, end, output_csv, currencies=["USD"], delay=2.0) → pd.DataFrame` — full date-range scrape; merges with existing CSV, deduplicates on `(DateTime, Currency, Event)`

**CLI usage** (run from project root):
```bash
python -m ff_scraper --start 2026-02-06 --end 2026-02-27 \
  --csv data/ff_events.csv --currencies USD
```

**Output CSV columns:** `DateTime` (ISO 8601 with TZ), `Currency`, `Impact`, `Event`, `Actual`, `Forecast`, `Previous`

---

## Dependencies

See `requirements.txt`. Key packages:

| Package | Purpose |
|---|---|
| `yfinance >= 0.2.38` | Yahoo Finance price data |
| `pandas >= 2.1.0` | DataFrames, CSV I/O |
| `numpy >= 1.26.0` | Math (sign, mean, sqrt, etc.) |
| `pytz >= 2024.1` | Timezone handling (Eastern/DST) |
| `cloudscraper >= 1.2.71` | Cloudflare-bypass HTTP sessions |
| `beautifulsoup4 >= 4.12.0` | HTML parsing for FF scraper |
| `matplotlib >= 3.8.0` | Plotting |
| `seaborn >= 0.13.0` | Statistical visualization |
| `ipywidgets >= 8.1.0` | Jupyter interactive widgets |
| `jupyter >= 1.0.0` | Notebook server |
| `ipykernel >= 6.29.0` | Jupyter kernel registration |
| `python-dotenv >= 1.0.0` | `.env` file loading |

Jupyter kernel name: `qqq-backtest` (registered via `ipykernel install --user --name qqq-backtest`).

## Data Files

Data CSVs are **not tracked in git**. The scraper/loader writes them to `DATA_DIR` (see path note above).

| File | Contents |
|---|---|
| `qqq_1m.csv` | 1-min OHLCV bars (~14K rows, 28 calendar days, premarket included) |
| `qqq_daily.csv` | Daily OHLCV bars (2 years) |
| `ff_events.csv` | ForexFactory USD macro events |
