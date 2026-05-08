# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Range Finder ⚡** — a Streamlit + Plotly dashboard for evaluating cryptocurrency pairs for Pionex grid-bot trading.

The application pulls live Binance/Bybit market data, runs 15+ technical indicators (RSI, ATR, EMA, CVD, POC, ADX, Donchian, Squeeze, etc.), calculates grid-bot profitability, and surfaces actionable trading recommendations. All math is ported from the original JavaScript engine.

**Three views** (sidebar radio toggle):
1. **Range Finder** — scores each pair 0–10 for grid suitability using lagging indicators (ADX, BB, CVD, POC, RSI, funding). Picks direction, derives range from ATR, recommends grid count, estimates duration.
2. **Signal Scanner** — predictive system using 6 leading indicators (CVD divergence, squeeze progression, structure transition, funding/OI imbalance, momentum divergence, volume exhaustion). Detects regime transitions before they happen. Setup Score 0–10 with urgency ranking and ETA.
3. **Bot Monitor** — connects to Pionex API (read-only, `Bot reading` permission) to show active spot grid bots. Cross-references live bot P&L, range position, and market conditions to generate HOLD/CLOSE/TAKE_PROFIT/WARNING alerts.

## Architecture

### Module Responsibilities

| Module | Purpose |
|--------|---------|
| `app.py` | Streamlit UI — page router (Range Finder / Signal Scanner / Bot Monitor), metric cards, summary table, charts |
| `config.py` | CFG, GRID_CONFIG, SIGNAL_CFG, BOT_MONITOR_CFG, DEFAULT_PAIRS, LEGENDS |
| `data_fetcher.py` | CCXT wrapper — OKX primary, Bybit/Binance fallback. Fetches klines, Open Interest, funding rates |
| `indicators.py` | 15+ indicator calculations (RSI, ATR, EMA, POC, AVWAP, CVD, market structure, FVG, ADX, MACD, BB, OBV, Donchian, squeeze) |
| `grid_calculator.py` | Range, direction, mode, score, viability assessment, profit estimation, grid count logic |
| `signal_engine.py` | 6 leading indicator detectors + scorers + aggregator for the Signal Scanner (Setup Score 0–10) |
| `signal_scanner.py` | Streamlit UI for Signal Scanner — urgency table, signal detail cards, leading indicator charts |
| `pionex_client.py` | Pionex Bot API client — HMAC SHA256 auth, list running bots, get bot detail (read-only) |
| `bot_advisor.py` | Bot health assessment engine — price position, trend alignment, profitability, duration → recommendations |
| `bot_monitor.py` | Streamlit UI for Bot Monitor — portfolio summary, bot cards with range gauge, P&L, alerts |
| `trade_logger.py` | SQLAlchemy ORM models (`MetricsCache`, `Trade`); database initialization |
| `refresh_data.py` | Cron entry point — fetches fresh data, runs indicators + signal engine, populates MetricsCache |
| `phases/` | Stubs for Phase 2 (trade logging), Phase 3 (Telegram alerts) |

### Data Flow

1. **Data Refresh** (`refresh_data.py` every 20 min)
   - Fetches 4H klines, OI, funding for each pair
   - Runs all 15+ indicators via `get_advanced_metrics()`
   - Runs `calc_grid_score()` → Grid Score (lagging, 0–10)
   - Runs `calc_setup_score()` → Setup Score (leading, 0–10) via `signal_engine.py`
   - Caches full payload (metrics + scoreInfo + signalInfo) in SQLite `MetricsCache`

2. **Range Finder** (`app.py` default page)
   - Reads cached metrics from SQLite
   - Renders per-pair cards with grid setup, spot trade setup, indicator pills, score breakdown
   - Spot Trade Setup direction is tightened: Signal Scanner direction overrides naive structure logic

3. **Signal Scanner** (`signal_scanner.py`)
   - Reads `signalInfo` from cached payload
   - Urgency ranking table → signal detail cards → component bars → recommendation boxes
   - Plotly charts for BB bandwidth + CVD series
   - Cross-reference table: Grid Score vs Setup Score

4. **Bot Monitor** (`bot_monitor.py`)
   - Fetches active spot grid bots from Pionex API (`pionex_client.py`)
   - Matches bots to cached metrics by symbol
   - Runs `assess_bot_health()` → HOLD/CLOSE/TAKE_PROFIT/WARNING/REVIEW
   - Renders portfolio summary, alert summary, per-bot cards with range gauge + P&L

### Technology Stack

- **Frontend**: Streamlit 1.44+, Plotly 5.24+
- **Data**: CCXT 4.4+ (crypto exchange connector), Pandas 2.2+, NumPy 2.2+
- **Backend**: SQLAlchemy 2.0+ (ORM), aiosqlite (async SQLite)
- **Scheduling**: Data refreshes on page load via `refresh_one()` — no external cron needed on Streamlit Cloud
- **Integrations** (Phase 3+): python-telegram-bot 21.9+

## Development Commands

### Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/Scripts/activate  # Windows bash

# Install dependencies
pip install -r requirements.txt

# Configure environment (copy example, edit as needed)
cp .env.example .env
```

### Run Locally

```bash
# One-shot refresh the SQLite cache
python -m refresh_data

# Start Streamlit dashboard (http://localhost:8501)
streamlit run app.py

# Run specific tests (once test suite is added)
pytest tests/
pytest tests/test_grid_calculator.py -v
pytest tests/test_indicators.py::test_rsi_calculation
```

### Linting & Code Quality

```bash
# Format with Black
black .

# Lint with Ruff
ruff check . --fix

# Sort imports
isort .

# Security check
bandit -r . --exclude ./tests

# Run all quality checks (pre-commit)
pre-commit run --all-files
```

### Database

```bash
# Initialize/reset SQLite
python -c "from trade_logger import Base, ENGINE; Base.metadata.create_all(ENGINE)"

# Inspect database (sqlite3 CLI)
sqlite3 pyonex.db ".tables"
sqlite3 pyonex.db "SELECT COUNT(*) FROM metrics_cache;"
```

## Key Code Patterns

### Configuration Override
`config.py` values come from `CFG` and `GRID_CONFIG` dicts. If you need to override a threshold (e.g., ADX_BLOCK), update the dict in `config.py`, not hardcoded values in other modules.

### Indicator Calculation
All indicators in `indicators.py` accept:
- `data` (DataFrame with OHLCV)
- Period/window params (e.g., `rsi_period=14`)
- Return DataFrame or scalar

Example:
```python
from indicators import calc_rsi
rsi_values = calc_rsi(ohlcv_df, period=14)
```

### Grid Recommendation
`refresh_one(symbol)` in `refresh_data.py` is the main entry point — it fetches data, runs all indicators, scores, and upserts to SQLite. For per-ticker config (rangeMultiplier, maxGrids, profile):
```python
from grid_calculator import get_ticker_grid_profile
profile = get_ticker_grid_profile("BTC/USDT")
# Returns: { 'profile': 'stable', 'rangeMultiplier': 2.5, 'maxGrids': 30 }
# Static lookup only — no data fetching.
```

### Adding a New Indicator
1. Implement in `indicators.py` (follow naming: `calc_<name>`)
2. Import in `app.py` or `grid_calculator.py`
3. Add user-facing description to `config.py` LEGENDS if needed
4. Integrate into score logic if it feeds the grid recommendation

## Deployment (Streamlit Community Cloud)

Hosted at [share.streamlit.io](https://share.streamlit.io). Single service — no cron, no persistent disk.

**How it works:**
- Streamlit Cloud runs `streamlit run app.py` directly.
- `refresh_one()` is called on each page load — no separate cron needed.
- SQLite (`pyonex.db`) lives in the system temp dir (`tempfile.gettempdir()`). Cache resets on redeployment; this is acceptable for a metrics cache.

**Secrets (set in Streamlit Cloud UI → Advanced settings → Secrets):**
```toml
# Exchange data (optional — public endpoints work without keys)
BINANCE_API_KEY = ""
BINANCE_API_SECRET = ""
BYBIT_API_KEY = ""
BYBIT_API_SECRET = ""

# Pionex Bot Monitor (required for Bot Monitor page)
PIONEX_API_KEY = "your_key"
PIONEX_API_SECRET = "your_secret"

PYONEX_LOG_LEVEL = "INFO"
```

Pionex keys need `Bot reading` permission only. Create at https://www.pionex.com/my-account/api.
Secrets are read via `st.secrets` (primary) with `os.getenv()` fallback for local `.env` files.

## Testing Strategy

No test suite yet. When adding tests:
- Unit tests: `tests/test_indicators.py`, `tests/test_grid_calculator.py`, etc. (use pytest)
- Integration tests: test end-to-end data fetch → cache → recommendation flow
- Minimum 70% coverage (enforced by CI)

Mock `ccxt` and database in unit tests; use real data fixtures for integration tests.

## Phases & Status

- **Phase 1 (done)** — indicators, grid calc, Streamlit dashboard, SQLite, Streamlit Cloud deploy
- **Phase 1.5 (done)** — Signal Scanner (predictive leading indicators, Setup Score 0–10)
- **Phase 1.6 (done)** — Bot Monitor (Pionex API read-only, active bot health alerts)
- **Phase 1.7 (done)** — Spot Trade Setup tightened (Signal Scanner direction overrides naive structure)
- **Phase 2** — "Log New Trade" UI + monitored-trade table + close recommendations
- **Phase 3** — Telegram alerts on STRONG SETUP / bot alert transitions

## Common Debugging

### "No data available for pair X"
- Check `data_fetcher.py` — Binance may have delisted it or CCXT mapping is stale
- Verify `DEFAULT_PAIRS` in `config.py` matches the pair name on Binance (e.g., `BTC/USDT`)
- Try switching to Bybit fallback by checking `data_fetcher.py` logic

### "Grid score too low"
- Check `calc_grid_score()` in `grid_calculator.py` and thresholds in `config.py`
- ADX too high? RSI at extreme? CVD too directional? Each suppresses score.
- Increase `SCORE_BOT_MIN` in `GRID_CONFIG` to see lower-confidence recommendations

### "SQLite locked"
- If running both cron and dashboard simultaneously on same DB, aiosqlite should handle locking
- If stuck: stop all processes, delete `.db-journal`, restart

## Notes for Future Contributors

- The original JS engine is the source of truth for math; any porting must match its results exactly
- Indicator thresholds are tuned for crypto perp pairs on 4H timeframe; different markets may need adjustment
- The codebase is intentionally kept simple (no heavy frameworks, no ORM migrations) to ease deployment on Streamlit Community Cloud
- Streamlit's automatic rerun on any file change is useful for rapid iteration but can slow the dashboard — consider `st.cache_data` for expensive operations


  ┌─────────────────────┬────────┬───────┬────────────────────────────────────────────────────────────────┐
  │       Setting       │ Before │ After │                             Reason                             │
  ├─────────────────────┼────────┼───────┼────────────────────────────────────────────────────────────────┤
  │ ADX_BLOCK           │ 22     │ 25    │ Alts often trend at 22–25 without killing grid                 │
  ├─────────────────────┼────────┼───────┼────────────────────────────────────────────────────────────────┤
  │ RSI_BLOCK           │ 68     │ 72    │ Less conservative gate, crypto can sustain higher RSI          │
  ├─────────────────────┼────────┼───────┼────────────────────────────────────────────────────────────────┤
  │ BB_MIN              │ 2.0%   │ 1.5%  │ Alts compress tighter; 2% was blocking valid setups            │
  ├─────────────────────┼────────┼───────┼────────────────────────────────────────────────────────────────┤
  │ BEARISH_ADX_BLOCK   │ 18     │ 21    │ Was too quick to block short grids                             │
  ├─────────────────────┼────────┼───────┼────────────────────────────────────────────────────────────────┤
  │ RSI_WARN_HIGH       │ 58     │ 62    │ Fewer false "overbought" warnings                              │
  ├─────────────────────┼────────┼───────┼────────────────────────────────────────────────────────────────┤
  │ ATR_MULTIPLIER      │ 2.5×   │ 3.0×  │ Wider default ranges, fewer whipsaws                           │
  ├─────────────────────┼────────┼───────┼────────────────────────────────────────────────────────────────┤
  │ RSI full score zone │ 40–60  │ 35–65 │ Crypto sits outside 40–60 frequently without being extreme     │
  ├─────────────────────┼────────┼───────┼────────────────────────────────────────────────────────────────┤
  │ RSI half score zone │ 35–65  │ 28–72 │ Catches accumulation/distribution zones before reversal        │
  ├─────────────────────┼────────┼───────┼────────────────────────────────────────────────────────────────┤
  │ LONG_MIN_SCORE      │ 6.5    │ 6.0   │ More Long setups in aggressive posture                         │
  ├─────────────────────┼────────┼───────┼────────────────────────────────────────────────────────────────┤
  │ DC_ATR_RATIO_MAX    │ 1.0    │ 0.7   │ Tighter squeeze definition = bonus only on genuine compression │
  └─────────────────────┴────────┴───────┴────────────────────────────────────────────────────────────────┘


All indicators explained:

  ┌──────────────┬────────────┬───────────────────────────────────────────────────────────────────────────────────────┐
  │  Indicator   │   Value    │                                        Meaning                                        │
  ├──────────────┼────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
  │ Range        │ 2,213 –    │ Derived from ATR × 3.0, centered on current price. Grid operates within this band.    │
  │              │ 2,399      │                                                                                       │
  ├──────────────┼────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
  │ 8.4% width   │ —          │ Range is 8.4% of price. Arithmetic mode (< 20% threshold).                            │
  ├──────────────┼────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
  │ 8 grids      │ —          │ Optimal count: 8.4% ÷ (0.8% target + 0.1% fees) ≈ 8 steps.                            │
  ├──────────────┼────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
  │ ~1-3 days    │ —          │ Estimated cycle time: range ÷ (ATR × 1.5 daily).                                      │
  ├──────────────┼────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
  │ SQUEEZE      │ —          │ BB bandwidth < 5% AND Donchian/ATR ratio < 0.7. Compressed price = prime grid window  │
  │              │            │ before breakout.                                                                      │
  ├──────────────┼────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
  │ ✓ Viable     │ —          │ ADX < 25, RSI < 72, BB > 1.5% — all gates pass.                                       │
  ├──────────────┼────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
  │ 5d/14d/30d   │ —          │ CVD positive across all three horizons = more buying than selling on all timeframes.  │
  │ ACC          │            │ Accumulation in progress.                                                             │
  ├──────────────┼────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
  │ OI -7.6%     │ —          │ Open Interest fell 7.6% in 7 days. Positions being closed — reduces                   │
  │              │            │ squeeze/liquidation cascade risk, grid-friendly.                                      │
  ├──────────────┼────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
  │ Fund         │ —          │ Slightly negative funding = shorts paying longs. Mild bearish derivatives sentiment,  │
  │ -0.0059%     │            │ but near zero = neutral effectively.                                                  │
  ├──────────────┼────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
  │ SL 2,080.77  │ —          │ Range low (2,213.59) × (1 − 9% moderate buffer). If price drops here, bot exits.      │
  ├──────────────┼────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
  │ TP 2,494.91  │ —          │ Range high (2,398.95) × (1 + 5% moderate buffer). Take profit target above range.     │
  └──────────────┴────────────┴───────────────────────────────────────────────────────────────────────────────────────┘

  CVD + Bearish structure conflict is worth noting: price structure is Bearish (lower highs/lows) but CVD shows
  accumulation on all horizons. This divergence often precedes a reversal — smart money accumulating while price structure
   still looks weak. Grid bots love this setup because the range stays tight while the under-the-surface pressure builds.


