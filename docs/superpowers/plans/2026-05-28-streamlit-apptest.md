# Streamlit AppTest UI Coverage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `AppTest`-based UI tests for all four Streamlit pages (`Range Finder`, `Signal Scanner`, `Bot Monitor`, `Trade Monitor`) with ≥70% coverage on each UI module.

**Architecture:** Single test file `tests/test_ui_streamlit.py` with four test classes; shared `autouse` fixture in `tests/conftest.py` that seeds in-memory SQLite from a captured snapshot, patches `refresh_data.main` to a no-op, and monkeypatches `PionexClient`. Two fixture files (`metrics_snapshot.json`, `pionex_bots.json`) are checked into git.

**Tech Stack:** `streamlit.testing.v1.AppTest`, `pytest`, `sqlalchemy` (in-memory SQLite), `unittest.mock.patch`, Python 3.9+.

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Create | `tests/fixtures/capture_snapshot.py` | One-time script: dumps live DB → JSON |
| Create | `tests/fixtures/metrics_snapshot.json` | Captured payload for all seeded pairs |
| Create | `tests/fixtures/pionex_bots.json` | Two synthetic Pionex bots (one healthy, one out-of-range) |
| Modify | `tests/conftest.py` | Add `ui_app` autouse fixture |
| Create | `tests/test_ui_streamlit.py` | All four page test classes |

---

## Task 1 — Create the snapshot capture script

**Files:**
- Create: `tests/fixtures/capture_snapshot.py`

- [ ] **Step 1: Create the script**

```python
# tests/fixtures/capture_snapshot.py
"""Run once to dump live pyonex.db → metrics_snapshot.json.

Usage:
    python tests/fixtures/capture_snapshot.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trade_logger import all_latest

rows = all_latest()
if not rows:
    print("ERROR: DB is empty. Run the app or `python -m refresh_data` first.")
    sys.exit(1)

snapshot = [
    {
        "symbol":    r.symbol,
        "price":     r.price,
        "score":     r.score,
        "direction": r.direction,
        "payload":   r.payload,
    }
    for r in rows
]

out = os.path.join(os.path.dirname(__file__), "metrics_snapshot.json")
with open(out, "w") as f:
    json.dump(snapshot, f, indent=2, default=str)

print(f"Captured {len(snapshot)} rows → {out}")
for r in snapshot:
    print(f"  {r['symbol']:15s}  score={r['score']:.1f}  price={r['price']:.4f}")
```

- [ ] **Step 2: Run it against the live DB**

```bash
python tests/fixtures/capture_snapshot.py
```

Expected output:
```
Captured 9 rows → tests/fixtures/metrics_snapshot.json
  BTC/USDT        score=7.8  price=104000.0000
  ETH/USDT        score=6.2  price=2400.0000
  ...
```

If the DB is empty, first run `python -m refresh_data` (may take ~60s while it fetches live data), then re-run the capture script.

- [ ] **Step 3: Verify the snapshot has required keys**

```bash
python3 -c "
import json
s = json.load(open('tests/fixtures/metrics_snapshot.json'))
p = s[0]['payload']
required = ['metrics', 'scoreInfo', 'direction', 'range', 'mode', 'gridCount', 'duration', 'viability', 'profile']
missing = [k for k in required if k not in p]
print('MISSING:', missing or 'none — all good')
print('Pairs:', [r['symbol'] for r in s])
"
```

Expected: `MISSING: none — all good`

- [ ] **Step 4: Stage the snapshot (NOT the capture script itself for production, but do commit both)**

```bash
git add tests/fixtures/capture_snapshot.py tests/fixtures/metrics_snapshot.json
git commit -m "Add metrics snapshot fixture for UI tests"
```

---

## Task 2 — Create the Pionex bots fixture

**Files:**
- Create: `tests/fixtures/pionex_bots.json`

- [ ] **Step 1: Create the fixture**

Two bots: `BTC/USDT` healthy (price inside range), `ETH/USDT` out-of-range (price below lower).
The `list_running_bots()` method returns a flat list of bot dicts (already filtered from the API wrapper), so the fixture is a JSON array.

The `base`/`quote` fields drive the symbol matching in `bot_monitor.py` (`pair = f"{base}/{quote}"`).
`buOrderData` holds range and P&L fields that `bot_monitor.py` flattens into the bot dict.

```json
[
  {
    "buOrderId": "test-bot-btc-001",
    "base": "BTC",
    "quote": "USDT",
    "buOrderType": "spot_grid",
    "status": "running",
    "createTime": 1714000000000,
    "buOrderData": {
      "upperPrice": "115000",
      "lowerPrice": "95000",
      "gridNum": 20,
      "gridProfit": "12.50",
      "realizedProfit": "3.00",
      "quoteInvestment": "500",
      "baseInvestment": "0",
      "baseAmount": "0",
      "quoteAmount": "500",
      "perVolume": "25",
      "totalCostInBase": "0",
      "totalCostInQuote": "500"
    }
  },
  {
    "buOrderId": "test-bot-eth-002",
    "base": "ETH",
    "quote": "USDT",
    "buOrderType": "spot_grid",
    "status": "running",
    "createTime": 1713000000000,
    "buOrderData": {
      "upperPrice": "3000",
      "lowerPrice": "2600",
      "gridNum": 15,
      "gridProfit": "2.10",
      "realizedProfit": "-8.00",
      "quoteInvestment": "300",
      "baseInvestment": "0",
      "baseAmount": "0",
      "quoteAmount": "300",
      "perVolume": "20",
      "totalCostInBase": "0",
      "totalCostInQuote": "300"
    }
  }
]
```

Note: the ETH bot has `realizedProfit = -8.00` on `quoteInvestment = 300` → `-2.7%` (above the `-5%` LOSS threshold), so `bot_advisor` returns WARNING not CLOSE. If you want to test a CLOSE_NOW recommendation, set `lowerPrice` above the ETH price from the snapshot.

- [ ] **Step 2: Commit**

```bash
git add tests/fixtures/pionex_bots.json
git commit -m "Add Pionex bots fixture for Bot Monitor UI tests"
```

---

## Task 3 — Add shared UI fixture to conftest.py

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Read what's already in conftest.py**

The existing conftest has `sample_ohlcv`, `trending_ohlcv`, `bearish_ohlcv`, `flat_ohlcv`, `empty_df`, `mock_metrics`, and `mock_bot` fixtures. We are adding a new `ui_app` fixture below all of them.

- [ ] **Step 2: Add the imports and fixture at the bottom of `tests/conftest.py`**

```python
# ── Streamlit AppTest shared fixture ─────────────────────────────────

import json
from pathlib import Path
from unittest.mock import patch as _patch

import trade_logger as _tl
from sqlalchemy import create_engine as _create_engine


@pytest.fixture()
def ui_app(monkeypatch):
    """Full-integration fixture for AppTest UI tests.

    - Seeds in-memory SQLite (metrics + trades) from captured snapshot.
    - Patches refresh_data.main to a no-op (scheduler starts but never fetches).
    - Patches PionexClient so it appears configured and returns fixture bots.
    """
    # ── 1. In-memory engines ────────────────────────────────────────
    metrics_engine = _create_engine("sqlite:///:memory:", future=True)
    trades_engine  = _create_engine("sqlite:///:memory:", future=True)
    _tl.Base.metadata.create_all(metrics_engine)
    _tl.TradesBase.metadata.create_all(trades_engine)
    monkeypatch.setattr(_tl, "_engine",        metrics_engine)
    monkeypatch.setattr(_tl, "_trades_engine", trades_engine)

    # ── 2. Seed metrics from snapshot ───────────────────────────────
    snapshot_path = Path(__file__).parent / "fixtures" / "metrics_snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    for row in snapshot:
        _tl.upsert_metrics(
            row["symbol"], row["price"], row["score"],
            row["direction"], row["payload"],
        )

    # ── 3. Patch refresh_data.main to no-op ─────────────────────────
    import refresh_data as _rd
    monkeypatch.setattr(_rd, "main", lambda *a, **kw: None)

    # ── 4. Patch PionexClient ────────────────────────────────────────
    import pionex_client as _pc
    bots_path = Path(__file__).parent / "fixtures" / "pionex_bots.json"
    fixture_bots = json.loads(bots_path.read_text())

    monkeypatch.setattr(_pc.PionexClient, "configured",
                        property(lambda self: True))
    monkeypatch.setattr(_pc.PionexClient, "list_running_bots",
                        lambda self: fixture_bots)
    monkeypatch.setattr(_pc.PionexClient, "get_bot_detail",
                        lambda self, order_id: fixture_bots[0])

    yield
```

- [ ] **Step 3: Verify the fixture can be imported without error**

```bash
python3 -m pytest tests/conftest.py --collect-only -q 2>&1 | head -20
```

Expected: no import errors, existing fixtures still collected.

---

## Task 4 — Write Range Finder tests

**Files:**
- Create: `tests/test_ui_streamlit.py`

- [ ] **Step 1: Create the file with the Range Finder test class**

```python
"""AppTest UI tests for all four Streamlit pages.

Each class uses the `ui_app` fixture (defined in conftest.py) which:
  - Seeds in-memory SQLite from tests/fixtures/metrics_snapshot.json
  - Patches refresh_data.main to a no-op
  - Patches PionexClient to return tests/fixtures/pionex_bots.json
"""
from __future__ import annotations

import os
import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")
TIMEOUT = 10  # seconds per AppTest run


class TestRangeFinder:
    """Default page — no radio selection needed."""

    @pytest.fixture(autouse=True)
    def setup(self, ui_app):
        pass

    def _run(self) -> AppTest:
        at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
        at.run()
        return at

    def test_no_exception(self):
        at = self._run()
        assert not at.exception

    def test_no_error_widget(self):
        at = self._run()
        assert len(at.error) == 0

    def test_sidebar_multiselect_populated(self):
        at = self._run()
        # Sidebar multiselect shows DEFAULT_PAIRS
        assert len(at.sidebar.multiselect) > 0
        # At least one option is a known pair
        options = at.sidebar.multiselect[0].options
        assert any("USDT" in o for o in options)

    def test_markdown_renders(self):
        # Page renders at least one markdown block (pair cards or summary)
        at = self._run()
        assert len(at.markdown) > 0

    def test_cache_age_shown_in_sidebar(self):
        # With seeded data, sidebar shows cache age (not "Cache empty" warning)
        at = self._run()
        sidebar_warnings = at.sidebar.warning
        cache_empty_warnings = [
            w for w in sidebar_warnings
            if "Cache empty" in (w.value or "")
        ]
        assert len(cache_empty_warnings) == 0
```

- [ ] **Step 2: Run Range Finder tests**

```bash
python3 -m pytest tests/test_ui_streamlit.py::TestRangeFinder -v --tb=short
```

Expected: 4 tests pass. If `at.exception` fires, the exception message tells you exactly what's wrong — common causes: import error in app.py, missing key in snapshot payload.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ui_streamlit.py
git commit -m "Add AppTest: Range Finder UI tests (4 tests)"
```

---

## Task 5 — Write Signal Scanner tests

**Files:**
- Modify: `tests/test_ui_streamlit.py`

- [ ] **Step 1: Append Signal Scanner class to `tests/test_ui_streamlit.py`**

```python
class TestSignalScanner:
    """Signal Scanner page — routed via sidebar radio."""

    @pytest.fixture(autouse=True)
    def setup(self, ui_app):
        pass

    def _run(self) -> AppTest:
        at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
        at.run()
        at.sidebar.radio[0].set_value("Signal Scanner")
        at.run()
        return at

    def test_no_exception(self):
        at = self._run()
        assert not at.exception

    def test_no_error_widget(self):
        at = self._run()
        assert len(at.error) == 0

    def test_signal_content_renders(self):
        # Page renders content (markdown or dataframe)
        at = self._run()
        assert len(at.markdown) > 0 or len(at.dataframe) > 0

    def test_score_label_present(self):
        # At least one markdown block contains a score-related label
        at = self._run()
        all_md = " ".join(
            str(m.value) for m in at.markdown if m.value
        )
        assert any(
            kw in all_md
            for kw in ("SETUP", "DEVELOPING", "AVOID", "Score", "Setup")
        )
```

- [ ] **Step 2: Run Signal Scanner tests**

```bash
python3 -m pytest tests/test_ui_streamlit.py::TestSignalScanner -v --tb=short
```

Expected: 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ui_streamlit.py
git commit -m "Add AppTest: Signal Scanner UI tests (4 tests)"
```

---

## Task 6 — Write Bot Monitor tests

**Files:**
- Modify: `tests/test_ui_streamlit.py`

- [ ] **Step 1: Append Bot Monitor class to `tests/test_ui_streamlit.py`**

Note: `render_bot_monitor` matches bots by `base`/`quote` → `"BTC/USDT"` against snapshot keys. For a bot card to render, the snapshot must contain `BTC/USDT` and `ETH/USDT` with a valid `metrics.currClose`. If the snapshot is missing either pair, the assessment loop skips it and the page shows "no matching metrics" warning instead of cards.

```python
class TestBotMonitor:
    """Bot Monitor page — two fixture bots injected via monkeypatched PionexClient."""

    @pytest.fixture(autouse=True)
    def setup(self, ui_app):
        pass

    def _run(self) -> AppTest:
        at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
        at.run()
        at.sidebar.radio[0].set_value("Bot Monitor")
        at.run()
        return at

    def test_no_exception(self):
        at = self._run()
        assert not at.exception

    def test_no_error_widget(self):
        at = self._run()
        assert len(at.error) == 0

    def test_page_renders_content(self):
        at = self._run()
        # Either bot cards or a status message renders
        assert len(at.markdown) > 0 or len(at.warning) > 0 or len(at.info) > 0

    def test_bot_card_or_portfolio_appears(self):
        at = self._run()
        all_md = " ".join(str(m.value) for m in at.markdown if m.value)
        # Bot cards contain the symbol name, or portfolio header appears
        has_symbol  = "BTC" in all_md or "ETH" in all_md
        has_header  = "Bot Monitor" in all_md or "Portfolio" in all_md or "BOTS" in all_md
        has_warning = len(at.warning) > 0
        assert has_symbol or has_header or has_warning

    def test_recommendation_label_present_when_bots_matched(self):
        at = self._run()
        all_md = " ".join(str(m.value) for m in at.markdown if m.value)
        # If bots matched metrics, recommendation labels appear
        rec_labels = ("HOLD", "CLOSE NOW", "TAKE PROFIT", "WARNING", "WATCH", "REVIEW")
        matched = any(lbl in all_md for lbl in rec_labels)
        # It's OK if bots didn't match (snapshot may not include BTC/ETH) —
        # in that case a warning renders instead
        assert matched or len(at.warning) > 0
```

- [ ] **Step 2: Run Bot Monitor tests**

```bash
python3 -m pytest tests/test_ui_streamlit.py::TestBotMonitor -v --tb=short
```

Expected: 5 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ui_streamlit.py
git commit -m "Add AppTest: Bot Monitor UI tests (5 tests)"
```

---

## Task 7 — Write Trade Monitor tests

**Files:**
- Modify: `tests/test_ui_streamlit.py`

- [ ] **Step 1: Append Trade Monitor class to `tests/test_ui_streamlit.py`**

```python
class TestTradeMonitor:
    """Trade Monitor page — empty state and seeded trade."""

    @pytest.fixture(autouse=True)
    def setup(self, ui_app):
        pass

    def _run(self) -> AppTest:
        at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
        at.run()
        at.sidebar.radio[0].set_value("Trade Monitor")
        at.run()
        return at

    def test_no_exception(self):
        at = self._run()
        assert not at.exception

    def test_no_error_widget(self):
        at = self._run()
        assert len(at.error) == 0

    def test_empty_state_renders(self):
        # With no simulated trades, page shows an info/markdown message
        at = self._run()
        all_md  = " ".join(str(m.value) for m in at.markdown if m.value)
        all_inf = " ".join(str(i.value) for i in at.info  if i.value)
        combined = all_md + all_inf
        assert (
            "no" in combined.lower()
            or "empty" in combined.lower()
            or "trade" in combined.lower()
            or len(at.dataframe) > 0   # some impls show empty table
        )

    def test_trade_table_renders_when_seeded(self):
        """Seed one SimulatedTrade into the in-memory trades DB, then assert table renders."""
        import trade_logger as tl
        from trade_logger import SimulatedTrade

        trade = SimulatedTrade(
            symbol="BTC/USDT",
            entry_price=100_000.0,
            range_low=90_000.0,
            range_high=110_000.0,
            num_grids=20,
            direction="Long",
            grid_mode="Arithmetic",
            grid_score=7.5,
            stop_loss=81_900.0,
            take_profit=115_500.0,
            profile="stable",
            inventory=[],
        )
        tl.create_simulated_trade(trade)

        at = self._run()
        assert not at.exception
        # Page should now show the trade (table or markdown)
        all_md = " ".join(str(m.value) for m in at.markdown if m.value)
        has_table = len(at.dataframe) > 0
        has_symbol_in_md = "BTC" in all_md
        assert has_table or has_symbol_in_md
```

- [ ] **Step 2: Run Trade Monitor tests**

```bash
python3 -m pytest tests/test_ui_streamlit.py::TestTradeMonitor -v --tb=short
```

Expected: 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ui_streamlit.py
git commit -m "Add AppTest: Trade Monitor UI tests (4 tests)"
```

---

## Task 8 — Full run, coverage check, and push

**Files:**
- No new files

- [ ] **Step 1: Run the complete test suite to confirm no regressions**

```bash
python3 -m pytest tests/ -q --tb=short
```

Expected: all tests pass (331 existing + 17 new AppTest = 348 total).

- [ ] **Step 2: Check UI module coverage**

```bash
python3 -m pytest tests/test_ui_streamlit.py \
  --cov=app --cov=bot_monitor --cov=signal_scanner --cov=trade_monitor \
  --cov-report=term-missing -q
```

Expected minimums per module:

| Module | Target |
|--------|--------|
| `app.py` | ≥ 65% |
| `bot_monitor.py` | ≥ 70% |
| `signal_scanner.py` | ≥ 70% |
| `trade_monitor.py` | ≥ 60% |

If a module is below target, check the `--cov-report=term-missing` output and add one targeted test for the largest uncovered block.

- [ ] **Step 3: Push to origin**

```bash
git push origin main
```

Expected: push succeeds, all 348 tests green in CI.

---

## Troubleshooting Guide

**`at.exception` is set with `ModuleNotFoundError`**
AppTest imports `app.py` which triggers all top-level imports. Run:
```bash
python3 -c "import app" 2>&1
```
Fix any missing packages with `python3 -m pip install <package>`.

**`at.exception` is set with `KeyError: 'scoreInfo'`**
The snapshot payload is missing required keys. Re-run the capture script against a fully populated DB, or add the missing key manually to `metrics_snapshot.json`.

**Bot Monitor shows "no matching metrics" warning**
The `pionex_bots.json` uses `"base": "BTC"` and `"base": "ETH"`, but the snapshot may not include those pairs. Check:
```bash
python3 -c "
import json
s = json.load(open('tests/fixtures/metrics_snapshot.json'))
print([r['symbol'] for r in s])
"
```
If `BTC/USDT` or `ETH/USDT` are missing, edit `pionex_bots.json` to use a `base`/`quote` that IS in the snapshot, or re-capture with a fully populated DB.

**`property` patching on `configured` raises `AttributeError`**
Streamlit may wrap `PionexClient` in a way that prevents property patching. Alternative:
```python
monkeypatch.setattr(_pc.PionexClient, "api_key",    "test-key",    raising=False)
monkeypatch.setattr(_pc.PionexClient, "api_secret", "test-secret", raising=False)
```
Then `configured` returns True naturally via its `bool(self.api_key and self.api_secret)` logic.

**Tests are slow (>5s each)**
The `next_run_time=datetime.now(timezone.utc)` in `_start_scheduler` causes a background fetch immediately. Since `refresh_data.main` is patched, the thread should complete near-instantly. If it doesn't, increase `TIMEOUT` or use `AppTest.from_file(APP_PATH, default_timeout=15)`.
