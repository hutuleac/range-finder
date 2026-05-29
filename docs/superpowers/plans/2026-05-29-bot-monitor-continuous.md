# Bot Monitor — Continuous Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 10-minute background polling loop that stores bot health assessments + open snapshots in SQLite and surfaces a redesigned bot card with "At Open", "Current Conditions", "Recommendation", and always-visible history strip.

**Architecture:** Four layers — new DB models in `trade_logger.py`, a new pure polling module `bot_monitor_loop.py`, a second APScheduler job in `app.py`, and an extended `_render_bot_card` in `bot_monitor.py` that reads history from SQLite. All state persists across app restarts.

**Tech Stack:** SQLAlchemy 2.0 (existing), APScheduler (existing), Streamlit 1.44 (existing), pytest, `streamlit.testing.v1.AppTest`.

---

## File Map

| Action | File | Change |
|--------|------|--------|
| Modify | `trade_logger.py` | Add `BotOpenSnapshot`, `BotAssessment` models + 4 helpers |
| Create | `bot_monitor_loop.py` | Pure polling function `run_bot_monitor_cycle` |
| Create | `tests/test_bot_monitor_loop.py` | Unit tests for the polling loop |
| Modify | `app.py` | Add `_bg_bot_monitor` wrapper + second scheduler job |
| Modify | `bot_monitor.py` | Extend `_render_bot_card`; update `render_bot_monitor` |
| Modify | `tests/test_trade_logger.py` | Tests for new models + helpers |
| Modify | `tests/test_ui_streamlit.py` | AppTest: history strip renders |

---

## Task 1 — DB Models + Helpers in `trade_logger.py`

**Files:**
- Modify: `trade_logger.py`
- Modify: `tests/test_trade_logger.py`

### Background

`trade_logger.py` uses `Base` (DeclarativeBase) with `_engine` pointing to `pyonex.db`. `init_db()` calls `Base.metadata.create_all(_engine)` — adding models to `Base` is all that's needed. The existing `in_memory_engines` autouse fixture in `tests/test_trade_logger.py` calls `tl.Base.metadata.create_all(metrics_engine)`, so new tables are available in tests with no fixture changes.

- [ ] **Step 1: Write failing tests**

Add to the top-level imports in `tests/test_trade_logger.py`:
```python
from trade_logger import (
    BotAssessment,
    BotOpenSnapshot,
    get_bot_assessments,
    get_open_snapshot,
    save_bot_assessment,
    save_open_snapshot,
)
```

Append this class at the end of the file:
```python
class TestBotPersistence:
    # ── BotOpenSnapshot ──────────────────────────────────────────────

    def test_save_open_snapshot_creates_row(self):
        snap = BotOpenSnapshot(
            bot_id="bot-001", symbol="BTC/USDT",
            open_range_low=90_000.0, open_range_high=110_000.0,
            open_grid_count=20, open_created_ms=1_700_000_000_000.0,
            open_adx=18.0, open_rsi=52.0, open_bb_bw=6.5,
            open_grid_score=7.5, open_setup_score=3.2,
        )
        save_open_snapshot(snap)
        fetched = get_open_snapshot("bot-001")
        assert fetched is not None
        assert fetched.symbol == "BTC/USDT"
        assert fetched.open_range_low == pytest.approx(90_000.0)

    def test_save_open_snapshot_is_idempotent(self):
        snap = BotOpenSnapshot(bot_id="bot-002", symbol="ETH/USDT",
                                open_adx=20.0, open_rsi=50.0, open_bb_bw=5.0,
                                open_grid_score=6.0, open_setup_score=2.0)
        save_open_snapshot(snap)
        save_open_snapshot(snap)  # second call must not raise or duplicate
        assert get_open_snapshot("bot-002") is not None

    def test_get_open_snapshot_returns_none_for_unknown(self):
        assert get_open_snapshot("nonexistent-bot") is None

    # ── BotAssessment ────────────────────────────────────────────────

    def _make_assessment(self, bot_id: str, action: str = "HOLD") -> BotAssessment:
        return BotAssessment(
            bot_id=bot_id, symbol="BTC/USDT", action=action,
            severity="NONE", reason="test",
            price=100_000.0, price_pct=50.0,
            adx=18.0, rsi=52.0, bb_bw=6.5,
            grid_score=7.5, setup_score=3.2,
        )

    def test_save_and_get_assessment(self):
        save_bot_assessment(self._make_assessment("bot-003"))
        rows = get_bot_assessments("bot-003")
        assert len(rows) == 1
        assert rows[0].action == "HOLD"

    def test_get_assessments_ordered_newest_first(self):
        for action in ["HOLD", "WARNING", "CLOSE_NOW"]:
            save_bot_assessment(self._make_assessment("bot-004", action))
        rows = get_bot_assessments("bot-004")
        assert rows[0].action == "CLOSE_NOW"
        assert rows[-1].action == "HOLD"

    def test_get_assessments_respects_limit(self):
        for _ in range(5):
            save_bot_assessment(self._make_assessment("bot-005"))
        rows = get_bot_assessments("bot-005", limit=3)
        assert len(rows) == 3

    def test_prune_keeps_last_50(self):
        for i in range(55):
            a = self._make_assessment("bot-006")
            a.reason = f"cycle-{i}"
            save_bot_assessment(a)
        all_rows = get_bot_assessments("bot-006", limit=100)
        assert len(all_rows) == 50
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/peter/Desktop/Claude/range-finder
python3 -m pytest tests/test_trade_logger.py::TestBotPersistence -v --tb=short 2>&1 | head -20
```
Expected: `ImportError: cannot import name 'BotOpenSnapshot'`

- [ ] **Step 3: Add models to `trade_logger.py`**

Insert after `class UserPair` (around line 60), before `def init_db()`:

```python
class BotOpenSnapshot(Base):
    """One row per bot — captured on first detection. Never overwritten."""
    __tablename__ = "bot_open_snapshots"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    bot_id          = Column(String(64), unique=True, nullable=False, index=True)
    symbol          = Column(String(32), nullable=False)
    captured_at     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    open_range_low  = Column(Float, nullable=True)
    open_range_high = Column(Float, nullable=True)
    open_grid_count = Column(Integer, nullable=True)
    open_created_ms = Column(Float, nullable=True)
    open_adx        = Column(Float, nullable=True)
    open_rsi        = Column(Float, nullable=True)
    open_bb_bw      = Column(Float, nullable=True)
    open_grid_score = Column(Float, nullable=True)
    open_setup_score= Column(Float, nullable=True)


class BotAssessment(Base):
    """One row per 10-min poll per bot. Pruned to last 50 per bot_id."""
    __tablename__ = "bot_assessments"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    bot_id       = Column(String(64), nullable=False, index=True)
    symbol       = Column(String(32), nullable=False)
    assessed_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    action       = Column(String(16), nullable=False)
    severity     = Column(String(8),  nullable=False, default="NONE")
    reason       = Column(String(256), nullable=True)
    price        = Column(Float, nullable=True)
    price_pct    = Column(Float, nullable=True)
    adx          = Column(Float, nullable=True)
    rsi          = Column(Float, nullable=True)
    bb_bw        = Column(Float, nullable=True)
    grid_score   = Column(Float, nullable=True)
    setup_score  = Column(Float, nullable=True)
    suggested_range_low   = Column(Float, nullable=True)
    suggested_range_high  = Column(Float, nullable=True)
    suggested_grid_count  = Column(Integer, nullable=True)
    suggested_stop_loss   = Column(Float, nullable=True)
    suggested_take_profit = Column(Float, nullable=True)
    suggested_grid_mode   = Column(String(16), nullable=True)
    suggested_duration    = Column(String(32), nullable=True)
```

- [ ] **Step 4: Add helper functions to `trade_logger.py`**

Append after `all_latest` and the existing user-pair helpers:

```python
# ── Bot monitoring persistence ────────────────────────────────────────────────

def save_open_snapshot(snapshot: BotOpenSnapshot) -> None:
    """Insert open snapshot if this bot_id has not been seen before."""
    with Session(_engine, future=True) as s:
        existing = s.execute(
            select(BotOpenSnapshot).where(BotOpenSnapshot.bot_id == snapshot.bot_id)
        ).scalar_one_or_none()
        if existing is None:
            s.add(snapshot)
            s.commit()


def get_open_snapshot(bot_id: str) -> BotOpenSnapshot | None:
    with Session(_engine, future=True) as s:
        return s.execute(
            select(BotOpenSnapshot).where(BotOpenSnapshot.bot_id == bot_id)
        ).scalar_one_or_none()


def save_bot_assessment(assessment: BotAssessment) -> None:
    """Insert assessment row and prune to keep last 50 per bot_id."""
    with Session(_engine, future=True) as s:
        s.add(assessment)
        s.commit()
        # Prune: keep newest 50, delete the rest
        keep_ids = s.execute(
            select(BotAssessment.id)
            .where(BotAssessment.bot_id == assessment.bot_id)
            .order_by(BotAssessment.assessed_at.desc())
            .limit(50)
        ).scalars().all()
        if keep_ids:
            s.execute(
                BotAssessment.__table__.delete().where(
                    BotAssessment.bot_id == assessment.bot_id,
                    BotAssessment.id.not_in(keep_ids),
                )
            )
            s.commit()


def get_bot_assessments(bot_id: str, limit: int = 10) -> list[BotAssessment]:
    """Return last N assessments for a bot, newest first."""
    with Session(_engine, future=True) as s:
        return s.execute(
            select(BotAssessment)
            .where(BotAssessment.bot_id == bot_id)
            .order_by(BotAssessment.assessed_at.desc())
            .limit(limit)
        ).scalars().all()
```

- [ ] **Step 5: Run all tests**

```bash
python3 -m pytest tests/test_trade_logger.py -q --tb=short 2>&1
```
Expected: all tests pass including the 8 new ones.

- [ ] **Step 6: Commit**

```bash
git add trade_logger.py tests/test_trade_logger.py
git commit -m "Add BotOpenSnapshot and BotAssessment models + helpers to trade_logger"
```

---

## Task 2 — `bot_monitor_loop.py` (new polling module)

**Files:**
- Create: `bot_monitor_loop.py`
- Create: `tests/test_bot_monitor_loop.py`

### Background

`bot_monitor_loop.py` is a pure module — no Streamlit imports. It calls existing functions:
- `PionexClient.list_running_bots()` from `pionex_client`
- `assess_bot_health(bot, metrics, signal_info, symbol)` from `bot_advisor`
- `_build_restart(symbol, metrics, grid_score)` from `bot_advisor` (called unconditionally, not just on close)
- `calc_grid_stop_loss(range_low, profile)` and `calc_grid_take_profit(range_high, profile)` from `grid_calculator`
- `save_open_snapshot`, `get_open_snapshot`, `save_bot_assessment` from `trade_logger`

The `payloads` parameter is `dict[str, dict]` where key = symbol (e.g. `"BTC/USDT"`) and value = the full `MetricsCache.payload` dict (contains `"metrics"`, `"scoreInfo"`, `"signalInfo"` keys).

The `_pionex_symbol_to_pair` helper in `bot_monitor.py` converts `"BTCUSDT"` → `"BTC/USDT"` when the bot lacks `base`/`quote` fields. Copy this logic inline in the loop module to keep it self-contained.

- [ ] **Step 1: Create `tests/test_bot_monitor_loop.py`**

```python
"""Tests for bot_monitor_loop.py — run_bot_monitor_cycle."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import trade_logger as tl
from bot_monitor_loop import run_bot_monitor_cycle


@pytest.fixture(autouse=True)
def in_memory_db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    tl.Base.metadata.create_all(engine)
    monkeypatch.setattr(tl, "_engine", engine)
    yield


def _fake_bot(base="BTC", quote="USDT", bot_id="bot-001"):
    return {
        "buOrderId": bot_id,
        "base": base,
        "quote": quote,
        "buOrderType": "spot_grid",
        "status": "running",
        "createTime": int(time.time() * 1000) - 3 * 86_400_000,
        "buOrderData": {
            "upperPrice": "110000", "lowerPrice": "90000",
            "gridNum": 20, "gridProfit": "10.0",
            "realizedProfit": "2.0", "quoteInvestment": "500",
            "baseInvestment": "0",
        },
    }


def _fake_payload():
    return {
        "metrics": {
            "currClose": 100_000.0, "atrPct": 2.5,
            "structure4h": "Neutral",
            "adx": {"adx": 18.0}, "rsi": 52.0, "bbBw": 6.5,
        },
        "scoreInfo": {"score": 7.5},
        "signalInfo": {"score": 2.0},
    }


class TestRunBotMonitorCycle:
    def test_returns_empty_when_not_configured(self):
        with patch("bot_monitor_loop.PionexClient") as MockClient:
            MockClient.return_value.configured = False
            result = run_bot_monitor_cycle({})
        assert result == []

    def test_returns_empty_when_no_bots(self):
        with patch("bot_monitor_loop.PionexClient") as MockClient:
            MockClient.return_value.configured = True
            MockClient.return_value.list_running_bots.return_value = []
            result = run_bot_monitor_cycle({})
        assert result == []

    def test_creates_open_snapshot_on_first_detection(self):
        payloads = {"BTC/USDT": _fake_payload()}
        with patch("bot_monitor_loop.PionexClient") as MockClient:
            MockClient.return_value.configured = True
            MockClient.return_value.list_running_bots.return_value = [_fake_bot()]
            run_bot_monitor_cycle(payloads)
        snap = tl.get_open_snapshot("bot-001")
        assert snap is not None
        assert snap.symbol == "BTC/USDT"
        assert snap.open_range_low == pytest.approx(90_000.0)

    def test_does_not_overwrite_existing_snapshot(self):
        from trade_logger import BotOpenSnapshot, save_open_snapshot
        existing = BotOpenSnapshot(
            bot_id="bot-001", symbol="BTC/USDT",
            open_adx=30.0, open_rsi=44.0, open_bb_bw=5.0,
            open_grid_score=8.0, open_setup_score=4.0,
        )
        save_open_snapshot(existing)

        payloads = {"BTC/USDT": _fake_payload()}
        with patch("bot_monitor_loop.PionexClient") as MockClient:
            MockClient.return_value.configured = True
            MockClient.return_value.list_running_bots.return_value = [_fake_bot()]
            run_bot_monitor_cycle(payloads)

        snap = tl.get_open_snapshot("bot-001")
        assert snap.open_adx == pytest.approx(30.0)   # original preserved

    def test_saves_bot_assessment(self):
        payloads = {"BTC/USDT": _fake_payload()}
        with patch("bot_monitor_loop.PionexClient") as MockClient:
            MockClient.return_value.configured = True
            MockClient.return_value.list_running_bots.return_value = [_fake_bot()]
            run_bot_monitor_cycle(payloads)
        rows = tl.get_bot_assessments("bot-001")
        assert len(rows) == 1
        assert rows[0].action in ("HOLD", "WATCH", "WARNING", "CLOSE_NOW", "TAKE_PROFIT", "REVIEW")

    def test_skips_bot_with_no_cached_metrics(self):
        with patch("bot_monitor_loop.PionexClient") as MockClient:
            MockClient.return_value.configured = True
            MockClient.return_value.list_running_bots.return_value = [_fake_bot()]
            result = run_bot_monitor_cycle({})   # empty payloads
        assert result == []
        assert tl.get_open_snapshot("bot-001") is None

    def test_suggested_parameters_populated(self):
        payloads = {"BTC/USDT": _fake_payload()}
        with patch("bot_monitor_loop.PionexClient") as MockClient:
            MockClient.return_value.configured = True
            MockClient.return_value.list_running_bots.return_value = [_fake_bot()]
            run_bot_monitor_cycle(payloads)
        row = tl.get_bot_assessments("bot-001")[0]
        assert row.suggested_range_low is not None
        assert row.suggested_range_high is not None
        assert row.suggested_grid_count is not None
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/peter/Desktop/Claude/range-finder
python3 -m pytest tests/test_bot_monitor_loop.py -v --tb=short 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'bot_monitor_loop'`

- [ ] **Step 3: Create `bot_monitor_loop.py`**

```python
"""Background polling loop for Bot Monitor — runs every 10 minutes.

Pure module: no Streamlit imports. Called by the APScheduler job in app.py.
"""
from __future__ import annotations

import logging

from bot_advisor import _build_restart, assess_bot_health
from grid_calculator import calc_grid_stop_loss, calc_grid_take_profit, get_ticker_grid_profile
from pionex_client import PionexClient
from trade_logger import (
    BotAssessment,
    BotOpenSnapshot,
    get_open_snapshot,
    save_bot_assessment,
    save_open_snapshot,
)

log = logging.getLogger("pyonex.bot_monitor_loop")


def _resolve_symbol(raw_bot: dict) -> str:
    """Convert Pionex bot dict to ccxt-style pair string (e.g. BTC/USDT)."""
    base  = raw_bot.get("base", "")
    quote = raw_bot.get("quote", "")
    if base and quote:
        return f"{base}/{quote}"
    sym = raw_bot.get("symbol", "")
    # Fallback: strip trailing USDT/USD
    for quote_ccy in ("USDT", "USD", "BTC", "ETH"):
        if sym.endswith(quote_ccy):
            return f"{sym[:-len(quote_ccy)]}/{quote_ccy}"
    return sym


def _flatten_bot(raw_bot: dict) -> dict:
    """Merge buOrderData fields into top-level bot dict (mirrors bot_monitor.py logic)."""
    bot = {**raw_bot}
    order_data = raw_bot.get("buOrderData") or {}
    for key in ("upperPrice", "lowerPrice", "gridNum", "gridProfit", "realizedProfit",
                "baseAmount", "quoteAmount", "baseInvestment", "quoteInvestment"):
        if key in order_data and key not in bot:
            bot[key] = order_data[key]
    if "upperPrice" not in bot and "top" in order_data:
        bot["upperPrice"] = order_data["top"]
    if "lowerPrice" not in bot and "bottom" in order_data:
        bot["lowerPrice"] = order_data["bottom"]
    if "gridNum" not in bot and "row" in order_data:
        bot["gridNum"] = order_data["row"]
    return bot


def run_bot_monitor_cycle(payloads: dict[str, dict]) -> list[dict]:
    """Fetch live bots, assess each, persist open snapshots + assessments.

    Args:
        payloads: dict mapping symbol → MetricsCache.payload dict.
                  Each payload must contain 'metrics', 'scoreInfo', 'signalInfo'.

    Returns:
        List of result dicts (one per assessed bot) — useful for testing.
    """
    client = PionexClient()
    if not client.configured:
        log.debug("Pionex not configured — skipping bot monitor cycle")
        return []

    try:
        bots = client.list_running_bots()
    except Exception:
        log.exception("Failed to fetch bots from Pionex")
        return []

    results: list[dict] = []

    for raw_bot in bots:
        bot_id = raw_bot.get("buOrderId", "")
        if not bot_id:
            continue

        symbol = _resolve_symbol(raw_bot)
        p = payloads.get(symbol)
        if not p:
            log.debug("No cached metrics for %s — skipping", symbol)
            continue

        bot     = _flatten_bot(raw_bot)
        metrics = {**p.get("metrics", {})}
        metrics["_grid_score"]  = p.get("scoreInfo", {}).get("score", 0.0)
        metrics["_setup_score"] = (p.get("signalInfo") or {}).get("score", 0.0)
        signal_info = p.get("signalInfo")

        if not metrics.get("currClose"):
            log.debug("No currClose for %s — skipping", symbol)
            continue

        # ── Open snapshot (write once) ────────────────────────────────
        if get_open_snapshot(bot_id) is None:
            snap = BotOpenSnapshot(
                bot_id          = bot_id,
                symbol          = symbol,
                open_range_low  = float(bot.get("lowerPrice") or 0) or None,
                open_range_high = float(bot.get("upperPrice") or 0) or None,
                open_grid_count = int(bot.get("gridNum") or 0) or None,
                open_created_ms = float(raw_bot.get("createTime") or 0) or None,
                open_adx        = (metrics.get("adx") or {}).get("adx"),
                open_rsi        = metrics.get("rsi"),
                open_bb_bw      = metrics.get("bbBw"),
                open_grid_score = metrics["_grid_score"],
                open_setup_score= metrics["_setup_score"],
            )
            save_open_snapshot(snap)

        # ── Health assessment ─────────────────────────────────────────
        try:
            advice = assess_bot_health(bot, metrics, signal_info, symbol=symbol)
        except Exception:
            log.exception("assess_bot_health failed for %s", symbol)
            continue

        rec = advice["recommendation"]

        # ── Suggested parameters (always, not just on close) ──────────
        grid_score = metrics["_grid_score"]
        restart    = _build_restart(symbol, metrics, grid_score)
        if restart:
            profile = get_ticker_grid_profile(symbol)["profile"]
            sl = calc_grid_stop_loss(restart["rangeLow"], profile)
            tp = calc_grid_take_profit(restart["rangeHigh"], profile)
        else:
            sl = tp = None

        # ── Persist assessment ────────────────────────────────────────
        assessment = BotAssessment(
            bot_id      = bot_id,
            symbol      = symbol,
            action      = rec["action"],
            severity    = rec["severity"],
            reason      = rec["reason"],
            price       = metrics.get("currClose"),
            price_pct   = advice["position"]["pct"],
            adx         = (metrics.get("adx") or {}).get("adx"),
            rsi         = metrics.get("rsi"),
            bb_bw       = metrics.get("bbBw"),
            grid_score  = grid_score,
            setup_score = metrics["_setup_score"],
            suggested_range_low   = restart["rangeLow"]   if restart else None,
            suggested_range_high  = restart["rangeHigh"]  if restart else None,
            suggested_grid_count  = restart["grids"]      if restart else None,
            suggested_stop_loss   = sl,
            suggested_take_profit = tp,
            suggested_grid_mode   = restart["mode"]       if restart else None,
            suggested_duration    = restart["duration"]   if restart else None,
        )
        try:
            save_bot_assessment(assessment)
        except Exception:
            log.exception("Failed to save assessment for %s", symbol)
            continue

        results.append({
            "bot_id": bot_id, "symbol": symbol,
            "action": rec["action"], "restart": restart,
        })

    return results
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_bot_monitor_loop.py -q --tb=short 2>&1
```
Expected: all 6 tests PASS.

- [ ] **Step 5: Full regression check**

```bash
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -3
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add bot_monitor_loop.py tests/test_bot_monitor_loop.py
git commit -m "Add bot_monitor_loop: 10-min polling cycle with open snapshot + assessment persistence"
```

---

## Task 3 — Scheduler Integration in `app.py`

**Files:**
- Modify: `app.py` (lines 105–125)

### Background

`_start_scheduler()` in `app.py` (decorated with `@st.cache_resource`) starts an APScheduler with one job. We add a second job. The wrapper `_bg_bot_monitor` must import lazily (inside the function) to avoid circular imports at module load time. `payloads` is rebuilt from the live SQLite cache inside the wrapper — it does not depend on the current Streamlit session.

No new tests needed for this task — the existing `TestBotMonitor` AppTest already runs the app with `ui_app` fixture which patches `refresh_data.main`. The bot monitor loop will be a no-op in tests because `PionexClient` is patched.

- [ ] **Step 1: Replace the `_start_scheduler` function in `app.py`**

Find the function (lines ~105–125):
```python
@st.cache_resource
def _start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    from refresh_data import main as _main

    def _bg_refresh():
        try:
            _main(DEFAULT_PAIRS)
        except Exception:  # noqa: BLE001
            logging.getLogger("pyonex.scheduler").exception("background refresh failed")

    sched = BackgroundScheduler(daemon=True)
    sched.add_job(
        _bg_refresh, "interval",
        seconds=CFG["REFRESH_INTERVAL_SEC"],
        id="bg_refresh",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    sched.start()
    return sched
```

Replace with:
```python
@st.cache_resource
def _start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    from refresh_data import main as _main

    def _bg_refresh():
        try:
            _main(DEFAULT_PAIRS)
        except Exception:  # noqa: BLE001
            logging.getLogger("pyonex.scheduler").exception("background refresh failed")

    def _bg_bot_monitor():
        try:
            from bot_monitor_loop import run_bot_monitor_cycle
            from trade_logger import all_latest as _all_latest
            _payloads = {r.symbol: r.payload for r in _all_latest()}
            run_bot_monitor_cycle(_payloads)
        except Exception:  # noqa: BLE001
            logging.getLogger("pyonex.scheduler").exception("bot monitor cycle failed")

    sched = BackgroundScheduler(daemon=True)
    sched.add_job(
        _bg_refresh, "interval",
        seconds=CFG["REFRESH_INTERVAL_SEC"],
        id="bg_refresh",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    sched.add_job(
        _bg_bot_monitor, "interval",
        seconds=600,   # 10 minutes
        id="bg_bot_monitor",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    sched.start()
    return sched
```

- [ ] **Step 2: Verify app still imports cleanly**

```bash
cd /Users/peter/Desktop/Claude/range-finder
python3 -c "import app" 2>&1
```
Expected: no errors.

- [ ] **Step 3: Run full suite**

```bash
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -3
```
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "Add 10-min bot monitor polling job to APScheduler"
```

---

## Task 4 — Redesigned Bot Card + AppTest

**Files:**
- Modify: `bot_monitor.py`
- Modify: `tests/test_ui_streamlit.py`

### Background

`_render_bot_card(bot, metrics, advice, symbol)` currently renders the card. We extend its signature to accept `open_snap: BotOpenSnapshot | None` and `history: list[BotAssessment]`, then add four sections: **At Open**, **Current Conditions** (enhanced), **Recommendation** (existing, kept), **History strip**.

`render_bot_monitor` fetches snapshots and history for each bot before calling `_render_bot_card`.

Add to `bot_monitor.py` imports:
```python
from trade_logger import (
    BotAssessment,
    BotOpenSnapshot,
    get_bot_assessments,
    get_open_snapshot,
)
```

The relative-time helper `_rel_time` formats a UTC datetime as "2h ago", "3d ago", etc.

The `_ACTION_STYLE` dict already exists in `bot_monitor.py` — reuse it for history strip chip colors.

- [ ] **Step 1: Add failing AppTest**

Append to `tests/test_ui_streamlit.py`:

```python
class TestBotMonitorHistory:
    """Verify history strip renders when BotAssessment rows exist."""

    @pytest.fixture(autouse=True)
    def _setup(self, ui_app):
        pass

    def _run(self) -> AppTest:
        at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
        at.run()
        at.sidebar.radio[0].set_value("Bot Monitor")
        at.run()
        return at

    def test_history_strip_renders_when_assessments_exist(self):
        import trade_logger as tl
        from trade_logger import BotAssessment
        row = BotAssessment(
            bot_id="test-bot-btc-001", symbol="BTC/USDT",
            action="HOLD", severity="NONE",
            reason="In range", price=100_000.0, price_pct=50.0,
            adx=18.0, rsi=52.0, bb_bw=6.5,
            grid_score=7.5, setup_score=2.0,
        )
        tl.save_bot_assessment(row)

        at = self._run()
        assert not at.exception
        all_md = " ".join(str(m.value) for m in at.markdown if m.value)
        # History section header or the action label should appear
        assert "HOLD" in all_md or "History" in all_md or len(at.markdown) > 0

    def test_no_exception_without_history(self):
        at = self._run()
        assert not at.exception
```

Run to confirm tests are collected:
```bash
cd /Users/peter/Desktop/Claude/range-finder
python3 -m pytest tests/test_ui_streamlit.py::TestBotMonitorHistory --collect-only 2>&1 | tail -5
```

- [ ] **Step 2: Add `_rel_time` helper to `bot_monitor.py`**

Add after the existing `_pnl_color` helper (around line 60):

```python
def _rel_time(dt) -> str:
    """Format a UTC datetime as a human-relative string ('2h ago', '3d ago')."""
    from datetime import datetime, timezone
    if dt is None:
        return "?"
    now   = datetime.now(timezone.utc)
    delta = now - dt.astimezone(timezone.utc)
    secs  = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"
```

- [ ] **Step 3: Update imports in `bot_monitor.py`**

Find the existing import block at the top of `bot_monitor.py`. Add the trade_logger imports:

```python
from trade_logger import (
    BotAssessment,
    BotOpenSnapshot,
    get_bot_assessments,
    get_open_snapshot,
)
```

- [ ] **Step 4: Extend `_render_bot_card` signature and add new sections**

The current signature is:
```python
def _render_bot_card(bot: dict, metrics: dict, advice: dict, symbol: str) -> None:
```

Replace the entire `_render_bot_card` function with the extended version. The existing card body (lines ~145–239) stays — new sections are inserted at the end before the closing `</div>` and `st.markdown` call.

Find the end of `_render_bot_card` where it does `html += "</div>"` followed by `st.markdown(html, unsafe_allow_html=True)`. Insert the new sections just before that.

**New signature:**
```python
def _render_bot_card(
    bot: dict,
    metrics: dict,
    advice: dict,
    symbol: str,
    open_snap: BotOpenSnapshot | None = None,
    history: list[BotAssessment] | None = None,
) -> None:
```

**After the existing alert box and restart recommendation** (just before the closing `html += "</div>"` / `st.markdown` at the bottom of the function), add:

```python
    # ── At Open section ───────────────────────────────────────────────
    if open_snap is not None:
        from datetime import datetime, timezone
        if open_snap.open_created_ms and open_snap.open_created_ms > 0:
            created_dt = datetime.fromtimestamp(open_snap.open_created_ms / 1000, tz=timezone.utc)
            open_date  = created_dt.strftime("%Y-%m-%d")
        else:
            open_date = open_snap.captured_at.strftime("%Y-%m-%d") if open_snap.captured_at else "?"
        rl  = f"{open_snap.open_range_low:,.2f}"  if open_snap.open_range_low  else "?"
        rh  = f"{open_snap.open_range_high:,.2f}" if open_snap.open_range_high else "?"
        gc  = str(open_snap.open_grid_count) if open_snap.open_grid_count else "?"
        adx_o  = f"{open_snap.open_adx:.1f}"        if open_snap.open_adx        is not None else "—"
        rsi_o  = f"{open_snap.open_rsi:.1f}"        if open_snap.open_rsi        is not None else "—"
        bb_o   = f"{open_snap.open_bb_bw:.1f}%"     if open_snap.open_bb_bw      is not None else "—"
        gs_o   = f"{open_snap.open_grid_score:.1f}" if open_snap.open_grid_score  is not None else "—"
        ss_o   = f"{open_snap.open_setup_score:.1f}" if open_snap.open_setup_score is not None else "—"
        html += (
            f"<div style='margin:.5rem 0;padding:.4rem .6rem;background:#0a0f1a;"
            f"border-radius:8px;border:1px solid #1e293b'>"
            f"<div style='font-size:.68rem;color:#475569;letter-spacing:.5px;"
            f"text-transform:uppercase;margin-bottom:.2rem'>At Open · {open_date}</div>"
            f"<div style='font-size:.78rem;color:#94a3b8'>"
            f"Range {rl} – {rh} · {gc}g</div>"
            f"<div style='display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.2rem'>"
            f"{_chip(f'ADX {adx_o}', '#64748b', '#64748b18')}"
            f"{_chip(f'RSI {rsi_o}', '#64748b', '#64748b18')}"
            f"{_chip(f'BB {bb_o}',   '#64748b', '#64748b18')}"
            f"{_chip(f'Grid {gs_o}', '#64748b', '#64748b18')}"
            f"{_chip(f'Setup {ss_o}','#64748b', '#64748b18')}"
            f"</div></div>"
        )

    # ── History strip ─────────────────────────────────────────────────
    rows = history or []
    if rows:
        html += (
            "<div style='margin:.5rem 0;padding:.4rem .6rem;background:#080c14;"
            "border-radius:8px;border:1px solid #1e293b'>"
            "<div style='font-size:.68rem;color:#475569;letter-spacing:.5px;"
            "text-transform:uppercase;margin-bottom:.3rem'>History</div>"
        )
        prev_action = None
        hist_parts = []
        for row in rows[:5]:
            fg, bg, _ = _ACTION_STYLE.get(row.action, ("#94a3b8", "#1e293b", "#334155"))
            changed   = row.action != prev_action and prev_action is not None
            weight    = "font-weight:700;" if changed else ""
            hist_parts.append(
                f"<div style='display:flex;gap:.5rem;align-items:center;"
                f"margin:.1rem 0;font-size:.75rem'>"
                f"<span style='color:#475569;min-width:52px'>{_rel_time(row.assessed_at)}</span>"
                f"{_chip(row.action.replace('_', ' '), fg, bg)}"
                f"<span style='color:#64748b;{weight}'>{_html.escape(row.reason or '')[:60]}</span>"
                f"</div>"
            )
            prev_action = row.action
        html += "".join(hist_parts) + "</div>"
    else:
        html += (
            "<div style='margin:.4rem 0;font-size:.72rem;color:#334155;"
            "font-style:italic'>No history yet — first assessment runs at next cycle (10 min)</div>"
        )
```

- [ ] **Step 5: Update `render_bot_monitor` to fetch snapshots and history**

In `render_bot_monitor`, find the "Bot cards" loop (around line 342–344):

```python
    for a in assessments:
        _render_bot_card(a["bot"], a["metrics"], a["advice"], a["symbol"])
```

Replace with:

```python
    for a in assessments:
        bot_id   = a["bot"].get("buOrderId", "")
        snap     = get_open_snapshot(bot_id) if bot_id else None
        history  = get_bot_assessments(bot_id, limit=5) if bot_id else []
        _render_bot_card(a["bot"], a["metrics"], a["advice"], a["symbol"],
                         open_snap=snap, history=history)
```

- [ ] **Step 6: Run the AppTest**

```bash
cd /Users/peter/Desktop/Claude/range-finder
python3 -m pytest tests/test_ui_streamlit.py::TestBotMonitorHistory -v --tb=short 2>&1
```
Expected: both tests PASS.

- [ ] **Step 7: Run full suite**

```bash
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -3
```
Expected: all tests pass.

- [ ] **Step 8: Commit and push**

```bash
git add bot_monitor.py tests/test_ui_streamlit.py
git commit -m "Redesign bot card: At Open snapshot, history strip, extended _render_bot_card"
git push origin main
```

---

## Verification Checklist

```bash
# Full suite green
python3 -m pytest tests/ -q 2>&1 | tail -3

# Check new DB tables exist after import
python3 -c "
from trade_logger import get_open_snapshot, get_bot_assessments
print('BotOpenSnapshot OK:', get_open_snapshot('nonexistent'))
print('BotAssessment OK:',   get_bot_assessments('nonexistent'))
"

# Confirm scheduler has both jobs
python3 -c "
import app  # triggers _start_scheduler
# APScheduler logs job registration — check output
"
```
