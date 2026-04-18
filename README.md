# Pyonex v6.4 — Pionex Grid Bot Dashboard

Streamlit + Plotly dashboard that pulls live Binance/Bybit data, runs the exact indicator + grid math from the original JS engine (plus Donchian & squeeze add-ons), and recommends Pionex grid-bot configurations.

## What it does

- Scores each pair 0–10 for grid-bot suitability (ADX, BB, CVD lateral, POC-in-range, RSI, funding, squeeze bonus).
- Picks direction (Long / Short / Neutral) from 4H market structure + score.
- Derives a range from ATR%, picks Arithmetic vs Geometric, recommends grid count, estimates duration.
- Checks viability (ADX / RSI / BB / structure gates) and surfaces warnings.
- Renders a "copy-to-Pionex" card for the active recommendation.

## Files

| File | Role |
|---|---|
| `config.py` | CFG, GRID_CONFIG, SIG_TIPS, LEGENDS, default pairs |
| `indicators.py` | RSI, ATR, EMA, POC/AVWAP, CVD, Market Structure, FVG, ADX, MACD, BB, OBV, Fib, Donchian, squeeze detector, aggregator |
| `grid_calculator.py` | Range / direction / mode / viability / score / profit / drawdown |
| `data_fetcher.py` | ccxt Binance primary, Bybit fallback (klines, OI, funding) |
| `trade_logger.py` | SQLAlchemy models `MetricsCache` + `Trade` (Phase 2) |
| `refresh_data.py` | Cron entry — fills MetricsCache for every watched pair |
| `app.py` | Streamlit UI — tabs, cards, summary table, charts |
| `render.yaml` | Render blueprint (web + cron + 1 GB disk) |
| `phases/` | Empty Phase 2/3/4 stubs |

## Local run

```bash
python -m venv .venv
. .venv/Scripts/activate        # Windows bash — use source .venv/bin/activate on mac/linux
pip install -r requirements.txt

cp .env.example .env             # then edit as needed (public endpoints work without keys)

python -m refresh_data           # one-shot fill the SQLite cache
streamlit run app.py             # http://localhost:8501
```

### Python version

Tested on 3.12. If you are on 3.14 and `pandas_ta` refuses to install, you can remove it from `requirements.txt` — this codebase does not import it (all math is ported directly from JS).

## GitHub workflow

```
pyonex/
├─ app.py
├─ config.py
├─ indicators.py
├─ grid_calculator.py
├─ data_fetcher.py
├─ trade_logger.py
├─ refresh_data.py
├─ render.yaml
├─ requirements.txt
├─ README.md
├─ .env.example
├─ .gitignore
└─ phases/
    ├─ phase2_trade_logger.py
    ├─ phase3_telegram.py
    └─ phase4_pionex_monitor.py
```

`.gitignore` already excludes `.env`, `*.db`, `.claude/`, caches.

## Render.com deploy

1. Push repo to GitHub.
2. On Render → **New → Blueprint** → connect the repo. `render.yaml` creates:
   - `pyonex-dashboard` — web service running Streamlit on `$PORT`.
   - `pyonex-refresh` — cron job running `python -m refresh_data` every 5 minutes.
   - `pyonex-data` — 1 GB persistent disk shared by both (SQLite at `/var/data/pyonex.db`).
3. Set env vars on both services (only `BINANCE_API_*` / `BYBIT_API_*` if you want higher rate limits — public endpoints work otherwise).
4. Trigger the cron once manually, then open the web service URL.

### Upgrade to Postgres later

Drop `PYONEX_DB_PATH`, set `DATABASE_URL=postgres://…`, and update `trade_logger.py`'s `ENGINE_URL`. Everything else stays the same.

## Environment variables

| Name | Purpose | Required |
|---|---|---|
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | higher rate limits on Binance public endpoints | no |
| `BYBIT_API_KEY` / `BYBIT_API_SECRET` | same for Bybit | no |
| `PIONEX_API_KEY` / `PIONEX_API_SECRET` | read-only Pionex (Phase 4) | no (Phase 1) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Phase 3 alerts | no (Phase 1) |
| `PYONEX_DB_PATH` | SQLite file path | defaults to `pyonex.db` |
| `PYONEX_LOG_LEVEL` | `INFO` / `DEBUG` | defaults to `INFO` |

## Phases

- **Phase 1 (done)** — indicators, grid calc, Streamlit dashboard, SQLite cache, Render deploy.
- **Phase 2** — "Log New Trade" + monitored-trade table, close recommendations.
- **Phase 3** — Telegram alerts on STRONG SETUP transitions.
- **Phase 4** — Pionex read-only monitor; re-recommend on trend change.

## Changelog

- **v6.4** — initial Python port from JS engine. Added Donchian (20/55) + squeeze detector. Binance → Bybit fallback. Render blueprint.
