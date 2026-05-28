# Streamlit AppTest UI Coverage — Design Spec
**Date:** 2026-05-28
**Status:** Approved

---

## Goal

Achieve UI-level test coverage for the four Streamlit pages (`Range Finder`, `Signal Scanner`, `Bot Monitor`, `Trade Monitor`) using Streamlit's built-in `AppTest` framework — no browser, no running server.

---

## Isolation Strategy

| Concern | Decision |
|---|---|
| SQLite | In-memory engine seeded from `tests/fixtures/metrics_snapshot.json` (captured from live `pyonex.db`) |
| Scheduler | Starts normally; `refresh_data.main` patched to no-op so threads spin but never fetch |
| Pionex API | `PionexClient.list_running_bots` and `get_bot_detail` monkeypatched to return `tests/fixtures/pionex_bots.json` |
| ccxt / exchange | Not called — scheduler callback is a no-op |

---

## Fixtures

### `tests/fixtures/metrics_snapshot.json`
Captured from the live `pyonex.db` via a one-time dump script. Shape:
```json
[
  {
    "symbol": "BTC/USDT",
    "price": 104000.0,
    "score": 7.8,
    "direction": "Long",
    "payload": { ... full get_advanced_metrics + scoreInfo + signalInfo ... }
  },
  ...
]
```
All 9 DEFAULT_PAIRS included. Checked into git. Refreshed manually when a new indicator is added.

### `tests/fixtures/pionex_bots.json`
Hand-crafted but realistic Pionex API payload — 2 bots, one healthy (IN_RANGE) and one out-of-range (BELOW_RANGE). Shape mirrors real Pionex `/api/v1/bot/orders` response.

---

## Test File Layout

```
tests/
  fixtures/
    metrics_snapshot.json
    pionex_bots.json
  test_ui_streamlit.py       ← all four page test classes
```

Single file keeps fixture wiring DRY. Split into separate files only if the file grows beyond ~400 lines.

---

## Shared Fixture (`conftest.py` addition)

A `ui_app` function-scoped fixture (used via `autouse` in each UI test class):

1. Creates two in-memory SQLite engines — one for `MetricsCache` (`_engine`), one for `SimulatedTrade`/`GridFill` (`_trades_engine`) — creates schemas, seeds all rows from `metrics_snapshot.json` via `upsert_metrics`.
2. Monkeypatches both `trade_logger._engine` and `trade_logger._trades_engine` to the in-memory engines.
3. Monkeypatches `refresh_data.main` → `lambda *a, **kw: None`.
4. Monkeypatches `pionex_client.PionexClient.list_running_bots` → returns parsed `pionex_bots.json`.
5. Monkeypatches `pionex_client.PionexClient.get_bot_detail` → returns first bot detail dict.
6. Yields — teardown is automatic (in-memory DB discarded).

---

## Per-Page Test Classes

### `TestRangeFinder`
Route: default (no radio selection needed).

| Test | What it asserts |
|---|---|
| `test_no_exception` | `at.exception` is empty after `at.run()` |
| `test_sidebar_pairs_populated` | `at.sidebar.multiselect[0].value` contains seeded pair symbols |
| `test_pair_cards_render` | `len(at.markdown) > 0` — at least one card block rendered |
| `test_no_error_widget` | `at.error` is empty |

### `TestSignalScanner`
Route: `at.radio[0].set_value("Signal Scanner").run()`

| Test | What it asserts |
|---|---|
| `test_no_exception` | `at.exception` is empty |
| `test_signal_table_renders` | markdown or dataframe content is non-empty |
| `test_score_labels_present` | at least one markdown block contains a score label string (e.g. "SETUP") |
| `test_no_error_widget` | `at.error` is empty |

### `TestBotMonitor`
Route: `at.radio[0].set_value("Bot Monitor").run()`
Two bots injected via monkeypatched `PionexClient`.

| Test | What it asserts |
|---|---|
| `test_no_exception` | `at.exception` is empty |
| `test_portfolio_metrics_render` | `len(at.metric) > 0` |
| `test_bot_cards_render` | markdown content is non-empty |
| `test_alert_renders_for_out_of_range_bot` | markdown contains "CLOSE" or "WARNING" for the out-of-range bot |
| `test_no_error_widget` | `at.error` is empty |

### `TestTradeMonitor`
Route: `at.radio[0].set_value("Trade Monitor").run()`

| Test | What it asserts |
|---|---|
| `test_no_exception` | `at.exception` is empty |
| `test_empty_state_renders` | markdown or info widget contains empty-state message when DB has no trades |
| `test_trade_table_renders_when_seeded` | after seeding one `SimulatedTrade` into in-memory DB, a dataframe or markdown with trade data renders |
| `test_no_error_widget` | `at.error` is empty |

---

## Snapshot Capture Script

A one-time helper (`tests/fixtures/capture_snapshot.py`) that:
1. Reads all rows from the live `pyonex.db` via `all_latest()`.
2. Serialises `payload` (JSON column) and all scalar fields to a list.
3. Writes `metrics_snapshot.json`.

Run manually: `python tests/fixtures/capture_snapshot.py`

---

## Running the Tests

```bash
# All UI tests
pytest tests/test_ui_streamlit.py -v

# With coverage
pytest tests/test_ui_streamlit.py --cov=app --cov=bot_monitor --cov=signal_scanner --cov=trade_monitor --cov-report=term-missing
```

---

## Coverage Targets

| Module | Expected after this work |
|---|---|
| `app.py` | ≥ 70% (rendering + routing paths) |
| `bot_monitor.py` | ≥ 75% |
| `signal_scanner.py` | ≥ 75% |
| `trade_monitor.py` | ≥ 70% |

Remaining uncovered lines will be edge-case render branches that only fire on specific market states not present in the snapshot — acceptable.

---

## What This Does NOT Cover

- Visual/CSS correctness (requires Playwright)
- Real Pionex API contract changes
- ccxt data fetching (covered by manual QA on deploy)
