# Range Finder ⚡ — Pionex Grid Bot Dashboard

> **Live demo → [range-finder.streamlit.app](https://range-finder.streamlit.app/)**

Streamlit + Plotly dashboard for crypto grid-bot traders. Pulls live market data from Binance / Bybit / OKX, runs 15+ technical indicators, scores grid-bot suitability 0–10, predicts regime transitions before they happen, and monitors active Pionex bots in real time.

---

## Screenshots

### Range Finder — grid-bot scoring per pair
![Range Finder](Assets/App%20view.png)

### Signal Scanner — leading indicators, urgency ranking
![Signal Scanner](Assets/Signal%20Scanner.png)

### Bot Monitor — live P&L and health alerts
![Bot Monitor](Assets/App%20view%202.png)

---

## Who is this for

- Pionex grid-bot traders who want data-driven entry decisions instead of gut feeling
- Anyone running spot grid bots and tired of manually checking whether to HOLD or CLOSE
- Builders who want a working Python reference for CCXT + Streamlit + SQLite + technical indicators

You do **not** need API keys to use the Range Finder or Signal Scanner — public exchange endpoints are enough. API keys are only required for the Bot Monitor (Pionex read-only) and for higher rate limits on Binance/Bybit.

---

## Three views

**Range Finder** — scores each pair 0–10 for grid-bot suitability using lagging indicators (ADX, BB, CVD, POC, RSI, funding). Picks direction (Long/Short/Neutral), derives range from ATR, recommends grid count, estimates cycle duration, and shows a Spot Trade Setup with entry zone, SL, TP1, TP2.

**Signal Scanner** — predictive system using 6 leading indicators to detect regime transitions *before* they happen. Setup Score 0–10 with urgency ranking, ETA, and cross-reference to grid score. Useful for timing entries — catch the setup window before the lagging score catches up.

**Bot Monitor** — connects to Pionex API (read-only, `Bot reading` permission) to show active spot grid bots. Cross-references live P&L, range position, and current market conditions to generate **HOLD / CLOSE / TAKE PROFIT / WARNING** alerts per bot.

---

## How it works

```
Binance / Bybit / OKX
        │
        ▼
  data_fetcher.py      ← klines (4H + 1H), OI, funding rate
        │
        ▼
  indicators.py        ← RSI, ATR, ADX, BB, CVD, MACD, OBV, Donchian, Squeeze, POC…
        │
  grid_calculator.py   ← score 0–10, direction, range, grid count, viability
  signal_engine.py     ← leading indicators → Setup Score 0–10
        │
        ▼
  SQLite (MetricsCache) ← refreshed every 20 min (or on page load)
        │
        ▼
  Streamlit UI          ← Range Finder / Signal Scanner / Bot Monitor
```

Data is cached in SQLite and refreshed automatically on each page load — no separate cron job needed on Streamlit Cloud.

---

## Quick start

**Requires Python 3.10+**

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env            # edit as needed — public endpoints work without keys

python -m refresh_data          # fill the SQLite cache once
streamlit run app.py            # open http://localhost:8501
```

The dashboard is usable without any API keys. Add keys to `.env` for higher rate limits or Bot Monitor access.

---

## API keys — what's needed and why

| Key | Purpose | Required? |
|---|---|---|
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | Higher rate limits on Binance public endpoints | No |
| `BYBIT_API_KEY` / `BYBIT_API_SECRET` | Higher rate limits on Bybit | No |
| `PIONEX_API_KEY` / `PIONEX_API_SECRET` | Bot Monitor — read your active spot grid bots | Only for Bot Monitor |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Phase 3 alerts (not yet active) | No |

Pionex keys: create at [pionex.com/my-account/api](https://www.pionex.com/my-account/api) with **Bot reading** permission only (read-only).

---

## Indicators

| Indicator | Used for |
|---|---|
| ADX | Trend strength gate — high ADX blocks grid (trending market) |
| RSI | Overbought/oversold gate and score component |
| ATR | Derives grid range width and cycle duration estimate |
| Bollinger Bands | Squeeze detection, bandwidth score component |
| CVD (5d/14d/30d) | Cumulative volume delta — buy vs sell pressure |
| Donchian Channel | Price compression bonus (DC/ATR ratio) |
| MACD | Momentum divergence signal |
| OBV | Volume trend confirmation |
| POC / AVWAP | Value area and anchored VWAP for structure |
| OI (Open Interest) | Derivatives positioning — liquidation risk |
| Funding Rate | Derivatives sentiment |
| Market Structure | Higher highs/lows vs lower highs/lows on 4H |
| FVG | Fair value gap detection |

All math ported from a JavaScript engine — `indicators.py` is the single source of truth.

---

## Deploy to Streamlit Community Cloud

1. Fork or push to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app** → pick repo, branch `main`, main file `app.py`.
3. Under **Advanced settings → Secrets**, paste:
   ```toml
   BINANCE_API_KEY = ""
   BINANCE_API_SECRET = ""
   BYBIT_API_KEY = ""
   BYBIT_API_SECRET = ""
   PIONEX_API_KEY = "your_key"
   PIONEX_API_SECRET = "your_secret"
   PYONEX_LOG_LEVEL = "INFO"
   ```
4. Click **Deploy**.

SQLite cache resets on each redeployment (no persistent disk on Streamlit Cloud) — this is fine, data refreshes on page load.

---

## Files

| File | Role |
|---|---|
| `app.py` | Streamlit UI — page router, Range Finder cards, spot trade setup |
| `config.py` | All thresholds and configuration (CFG, GRID_CONFIG, SIGNAL_CFG, DEFAULT_PAIRS) |
| `indicators.py` | 15+ indicator calculations |
| `grid_calculator.py` | Range / direction / mode / viability / score / profit estimation |
| `signal_engine.py` | 6 leading indicator detectors + Setup Score aggregator |
| `signal_scanner.py` | Streamlit UI for Signal Scanner |
| `pionex_client.py` | Pionex Bot API client — HMAC auth, read-only |
| `bot_advisor.py` | Bot health assessment — price position, trend, P&L, duration → alerts |
| `bot_monitor.py` | Streamlit UI for Bot Monitor |
| `data_fetcher.py` | CCXT wrapper — Binance primary, Bybit/OKX fallback |
| `trade_logger.py` | SQLAlchemy models `MetricsCache` + `Trade` |
| `refresh_data.py` | Data refresh pipeline — fetches, scores, caches |
| `phases/` | Phase 2/3 feature stubs |

---

## Roadmap

- **Phase 1 (done)** — indicators, grid calc, Streamlit dashboard, SQLite cache, Streamlit Cloud deploy
- **Phase 1.5 (done)** — Signal Scanner — predictive leading indicators, Setup Score 0–10
- **Phase 1.6 (done)** — Bot Monitor — Pionex API read-only, active bot health alerts
- **Phase 2** — "Log New Trade" UI + monitored-trade table + close recommendations
- **Phase 3** — Telegram alerts on STRONG SETUP / bot alert transitions

---

## Changelog

- **v1.6** — Bot Monitor: Pionex API integration, bot health assessment (HOLD/CLOSE/TP/WARNING), portfolio summary, range gauge
- **v1.5** — Signal Scanner: 6 leading indicators (CVD divergence, squeeze progression, structure transition, funding/OI, momentum divergence, volume exhaustion), urgency ranking, ETA estimation. Spot Trade Setup direction tightened with signal override.
- **v1.0** — Range Finder: Python port from JS engine. Donchian (20/55) + squeeze detector. OKX/Bybit/Binance fallback. Streamlit Cloud deploy.
