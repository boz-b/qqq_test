# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

```bash
# Activate environment (always required first)
source venv/bin/activate

# Refresh all data (intraday + daily + FF events)
python3 -c "from src.data_loader import DataLoader; DataLoader().fetch_all()"

# Fetch FF macro events for a date range
python -m src.ff_scraper --start YYYY-MM-DD --end YYYY-MM-DD \
  --csv data/ff_events.csv --currencies USD

# Launch notebooks
jupyter notebook

# Run a quick smoke test (no test framework — use interactive Python)
python3 -c "
from src.data_loader import DataLoader
from src.features import build_features
from src.labeler import build_labels
from src.strategy import predict_batch
from src.backtester import run, compute_metrics

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

### `features.py` — One Row Per Day
`build_features(intraday_df, daily_df, ff_events_df)` produces one row per trading date with:
- **Premarket features**: `pm_gap_pct`, `pm_direction`, `pm_momentum_score`, `pm_momentum_accel` (+1 accel / -1 decel), `pm_reversal_flag`
- **Macro features** (USD only): `has_high_impact_event`, `has_pre_open_high_impact`, `is_fomc_day`, `is_cpi_day`, `is_nfp_day`, `event_surprise_score`
- **Prior day**: `prior_day_return`

### `strategy.py` — Rule Priority Order
W1 rules evaluated in order; **first match wins**, default is `(0, "DEFAULT_Flat")`:
1. Pre-open event surprise > ±2% → follow surprise direction
2. PM reversal flag + |gap| ≥ 0.5% → follow 9:29 direction
3. Gap ≥ 1% + accelerating → follow gap
4. Gap ≥ 1% + decelerating → fade gap
5. Gap 0.3–1% + macro event → Flat
6. Gap < 0.3% + no macro → mean-revert prior day

W2 rules: FOMC → Flat; W1 continuation; gap-fade continuation.

`predict_batch(features_df, labels_df=None)` → columns: `w1_pred`, `w1_rule`, `w2_pred`, `w2_rule`

### `backtester.py` — Simulation Assumptions
- Starting capital: $100,000; position size: 1% of capital (fixed-fractional)
- Slippage: 0.05% per side; no commissions; Flat signal = no trade
- Metrics: win rate, profit factor, Sharpe (annualized √252), max drawdown, per-rule breakdown

### `data_loader.py` — Caching & Yahoo Limits
- **1-min data limit**: max 30 calendar days, max 7 days per request → fetched in 7-day chunks, `days=28` default
- Staleness thresholds: intraday = 4 hours, daily = 24 hours
- `load_intraday(force_refresh=False)` / `load_daily()` use CSV cache; pass `force_refresh=True` to bypass

### `ff_scraper.py` — ForexFactory
Uses `cloudscraper` (Cloudflare bypass) + `BeautifulSoup`. No Selenium.
Impact decoded from CSS classes: `icon--ff-impact-red` = High, `-ora` = Medium, `-yel` = Low, `-gry` = Non-Economic.
Merges with existing CSV; deduplicates on `(DateTime, Currency, Event)`.

## Dependencies
See `requirements.txt`. Key packages: `yfinance`, `pandas`, `numpy`, `cloudscraper`, `beautifulsoup4`, `ipywidgets`, `jupyter`.

Jupyter kernel name: `qqq-backtest` (registered via `ipykernel install --user --name qqq-backtest`).

## Data Files (not tracked in git)
- `data/qqq_1m.csv` — 1-min bars (~14K rows, 28 calendar days, premarket included)
- `data/qqq_daily.csv` — Daily OHLCV (2 years)
- `data/ff_events.csv` — ForexFactory USD macro events
