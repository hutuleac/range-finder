# Graph Report - range-finder  (2026-05-08)

## Corpus Check
- Corpus is ~42,436 words - fits in a single context window. You may not need a graph.

## Summary
- 298 nodes · 446 edges · 22 communities (18 shown, 4 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 43 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Scoring Concepts and Core Deps|Scoring Concepts and Core Deps]]
- [[_COMMUNITY_Range Finder UI Detail (Bot Monitor)|Range Finder UI Detail (Bot Monitor)]]
- [[_COMMUNITY_Signal Engine Indicators|Signal Engine Indicators]]
- [[_COMMUNITY_App UI and Router|App UI and Router]]
- [[_COMMUNITY_Technical Indicators|Technical Indicators]]
- [[_COMMUNITY_Grid Calculator and Bot Advisor|Grid Calculator and Bot Advisor]]
- [[_COMMUNITY_Data Fetching|Data Fetching]]
- [[_COMMUNITY_Signal Scanner UI|Signal Scanner UI]]
- [[_COMMUNITY_Bot Monitor and Pionex API|Bot Monitor and Pionex API]]
- [[_COMMUNITY_Core Libraries|Core Libraries]]
- [[_COMMUNITY_Range Finder Card UI|Range Finder Card UI]]
- [[_COMMUNITY_Data Persistence (SQLite)|Data Persistence (SQLite)]]
- [[_COMMUNITY_Signal Scanner Logic|Signal Scanner Logic]]
- [[_COMMUNITY_Telegram Alerts|Telegram Alerts]]
- [[_COMMUNITY_Bot Health Assessment|Bot Health Assessment]]
- [[_COMMUNITY_Bot and Exchange Concepts|Bot and Exchange Concepts]]
- [[_COMMUNITY_Phase Stubs and Telegram Dep|Phase Stubs and Telegram Dep]]
- [[_COMMUNITY_Configuration|Configuration]]
- [[_COMMUNITY_Phase 2 Trade Logger|Phase 2 Trade Logger]]
- [[_COMMUNITY_Phase 3 Telegram Stub|Phase 3 Telegram Stub]]
- [[_COMMUNITY_Phase 4 Pionex Monitor|Phase 4 Pionex Monitor]]

## God Nodes (most connected - your core abstractions)
1. `calc_setup_score()` - 21 edges
2. `get_advanced_metrics()` - 19 edges
3. `refresh_one()` - 18 edges
4. `indicators.py â€” Technical Indicators` - 15 edges
5. `Pair Analysis Card` - 10 edges
6. `render_symbol()` - 9 edges
7. `_build_restart()` - 9 edges
8. `assess_bot_health()` - 9 edges
9. `Range Finder Project` - 9 edges
10. `Urgency Ranking Table` - 9 edges

## Surprising Connections (you probably didn't know these)
- `render_symbol()` --calls--> `calc_grid_stop_loss()`  [INFERRED]
  app.py → grid_calculator.py
- `render_symbol()` --calls--> `calc_grid_take_profit()`  [INFERRED]
  app.py → grid_calculator.py
- `render_bot_monitor()` --calls--> `assess_bot_health()`  [INFERRED]
  bot_monitor.py → bot_advisor.py
- `render_bot_monitor()` --calls--> `send_bot_alert()`  [INFERRED]
  bot_monitor.py → telegram_alerts.py
- `refresh_one()` --calls--> `fetch_klines()`  [INFERRED]
  refresh_data.py → data_fetcher.py

## Hyperedges (group relationships)
- **Data Refresh Pipeline (Fetch â†’ Indicators â†’ Score â†’ Cache)** — module_data_fetcher, module_indicators, module_grid_calculator, module_signal_engine, module_refresh_data, infra_sqlite [EXTRACTED 1.00]
- **Three-View Streamlit UI (Range Finder / Signal Scanner / Bot Monitor)** — module_app, module_signal_scanner, module_bot_monitor, rangefinder_view_rangefinder, rangefinder_view_signalscanner, rangefinder_view_botmonitor [EXTRACTED 1.00]
- **Squeeze Detection (BB + Donchian + ATR â†’ Grid Window)** — concept_squeeze, indicator_bb, indicator_donchian, indicator_atr [EXTRACTED 1.00]

## Communities (22 total, 4 thin omitted)

### Community 0 - "Scoring Concepts and Core Deps"
Cohesion: 0.09
Nodes (30): Grid Score (0-10, Lagging), Setup Score (0-10, Leading), Squeeze Detection, CCXT >=4.4.92, SQLAlchemy >=2.0.38, Binance Exchange, Bybit Exchange, OKX Exchange (+22 more)

### Community 1 - "Range Finder UI Detail (Bot Monitor)"
Cohesion: 0.09
Nodes (28): ADX Trend Bar (15.8 â€” low), Arithmetic Grid Mode, ATR Pill (1.54%), BB BW Pill (5.14%), BB Squeeze Alert (Watch for BB squeeze for optimal entry), BB Width Bar (5.1% â€” normal), CVD Flow Bar (Lateral â€” no trend pressure [ok]), Dark Theme Dashboard Layout (+20 more)

### Community 2 - "Signal Engine Indicators"
Cohesion: 0.15
Nodes (25): calc_bb_bandwidth_series(), calc_cvd_series(), calc_macd_histogram_series(), calc_rsi_series(), calc_setup_score(), _calc_urgency(), _classify_signal(), detect_cvd_divergence() (+17 more)

### Community 3 - "App UI and Router"
Cohesion: 0.12
Nodes (13): chip(), comp_bar_color(), context_chip(), Pyonex Streamlit dashboard — Phase 1., Spot directional trade card — entry zone, SL, TP1, TP2, R/R.      Direction lo, render_symbol(), render_trade_setup(), rsi_color() (+5 more)

### Community 4 - "Technical Indicators"
Cohesion: 0.15
Nodes (21): calc_adx(), calc_atr(), calc_atr_pct(), calc_bb(), calc_change_24h(), calc_cvd(), calc_donchian(), calc_ema() (+13 more)

### Community 5 - "Grid Calculator and Bot Advisor"
Cohesion: 0.16
Nodes (16): _build_restart(), Build a restart recommendation with fresh ATR-derived range., assess_grid_viability(), calc_grid_score(), calc_range_from_atr(), calc_recommended_grid_count(), estimate_grid_duration(), get_ticker_grid_profile() (+8 more)

### Community 6 - "Data Fetching"
Cohesion: 0.2
Nodes (20): _binance_oi(), _binance_raw_klines(), _bybit_ohlcv(), _bybit_oi(), fetch_funding(), fetch_klines(), fetch_oi(), fetch_pionex_balance() (+12 more)

### Community 7 - "Signal Scanner UI"
Cohesion: 0.12
Nodes (20): Action Label Column, Component Indicator Bars, Signal Detail Panel, Direction Column, FTA Column (First Target Area), Funding/OI Imbalance Indicator, Grid Score Column, Momentum Divergence Indicator (+12 more)

### Community 8 - "Bot Monitor and Pionex API"
Cohesion: 0.18
Nodes (11): _chip(), _pionex_symbol_to_pair(), _pnl_color(), Bot Monitor — Streamlit UI for active Pionex grid bot monitoring., _render_alert_summary(), _render_bot_card(), render_bot_monitor(), _render_portfolio_summary() (+3 more)

### Community 9 - "Core Libraries"
Cohesion: 0.17
Nodes (13): aiosqlite >=0.20.0, NumPy >=2.2.3, Pandas >=2.2.3, Plotly >=5.24.0, Streamlit >=1.44.0, Streamlit Community Cloud, app.py â€” Streamlit UI Router, bot_monitor.py â€” Bot Monitor UI (+5 more)

### Community 10 - "Range Finder Card UI"
Cohesion: 0.22
Nodes (13): Current Price Display, Grid Score Metric, Grid Setup Block, Indicator Pills Row, Main Content Area, Market Condition Narrative, Pair Analysis Card, Pair Symbol Header (+5 more)

### Community 11 - "Data Persistence (SQLite)"
Cohesion: 0.26
Nodes (11): DeclarativeBase, all_latest(), Base, init_db(), latest_metrics(), MetricsCache, Pyonex persistence — SQLAlchemy models + helpers.  Phase 1 uses MetricsCache o, Phase 2 — not used in Phase 1 but schema is stable. (+3 more)

### Community 12 - "Signal Scanner Logic"
Cohesion: 0.33
Nodes (10): _bar_color(), _chip(), _cross_ref(), Signal Scanner — Streamlit UI for the predictive signal system., _render_comparison_table(), _render_leading_chart(), _render_signal_detail(), render_signal_scanner() (+2 more)

### Community 13 - "Telegram Alerts"
Cohesion: 0.36
Nodes (10): _cache_key(), _get_config(), is_configured(), _mark_sent(), Telegram alerts for bot events and signal transitions.  Sends a message when a, Alert when Signal Scanner detects a high-urgency setup., send_bot_alert(), _send_message() (+2 more)

### Community 14 - "Bot Health Assessment"
Cohesion: 0.36
Nodes (8): assess_bot_health(), _check_duration(), _check_price_position(), _check_profit(), _check_trend(), _generate_recommendation(), Bot advisor — health assessment and recommendations for active grid bots., Main entry point. Returns full health assessment for one bot.

### Community 15 - "Bot and Exchange Concepts"
Cohesion: 0.5
Nodes (4): Bot Alerts (HOLD/CLOSE/TAKE_PROFIT/WARNING), Pionex Exchange (Bot API), bot_advisor.py â€” Bot Health Engine, pionex_client.py â€” Pionex API Client

### Community 16 - "Phase Stubs and Telegram Dep"
Cohesion: 0.5
Nodes (4): python-telegram-bot >=21.9, phases/ â€” Phase 2/3 Feature Stubs, Phase 2 â€” Trade Logging UI, Phase 3 â€” Telegram Alerts

## Knowledge Gaps
- **82 isolated node(s):** `Pyonex Streamlit dashboard — Phase 1.`, `Spot directional trade card — entry zone, SL, TP1, TP2, R/R.      Direction lo`, `Bot advisor — health assessment and recommendations for active grid bots.`, `Build a restart recommendation with fresh ATR-derived range.`, `Main entry point. Returns full health assessment for one bot.` (+77 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `refresh_one()` connect `Grid Calculator and Bot Advisor` to `Signal Engine Indicators`, `Data Persistence (SQLite)`, `Technical Indicators`, `Data Fetching`?**
  _High betweenness centrality (0.236) - this node is a cross-community bridge._
- **Why does `_build_restart()` connect `Grid Calculator and Bot Advisor` to `Bot Health Assessment`?**
  _High betweenness centrality (0.146) - this node is a cross-community bridge._
- **Why does `assess_bot_health()` connect `Bot Health Assessment` to `Bot Monitor and Pionex API`, `Grid Calculator and Bot Advisor`?**
  _High betweenness centrality (0.136) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `refresh_one()` (e.g. with `fetch_klines()` and `parse_klines()`) actually correct?**
  _`refresh_one()` has 16 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Pyonex Streamlit dashboard — Phase 1.`, `Spot directional trade card — entry zone, SL, TP1, TP2, R/R.      Direction lo`, `Bot advisor — health assessment and recommendations for active grid bots.` to the rest of the system?**
  _82 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Scoring Concepts and Core Deps` be split into smaller, more focused modules?**
  _Cohesion score 0.09 - nodes in this community are weakly interconnected._
- **Should `Range Finder UI Detail (Bot Monitor)` be split into smaller, more focused modules?**
  _Cohesion score 0.09 - nodes in this community are weakly interconnected._