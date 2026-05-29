# Bot Monitor — Continuous Market Monitoring Design Spec
**Date:** 2026-05-29
**Status:** Approved
**Phase:** 1 of 3 (UI + persistence; Telegram and Pionex API writes are separate future phases)

---

## Goal

Continuously monitor active Pionex grid bots every 10 minutes, persist assessment history in SQLite (survives app restarts), and surface full adjustment recommendations (range, grids, SL/TP) alongside an always-visible mini-timeline inside each existing bot card.

---

## Scope Boundaries

**In scope (this phase):**
- Background polling loop (10-min interval)
- Two new DB tables (`BotOpenSnapshot`, `BotAssessment`)
- Redesigned bot card with "At Open", "Current Conditions", "Recommendation", and "History" sections

**Out of scope (future phases):**
- Telegram notifications on recommendation changes (Phase 2)
- Pionex API writes to auto-adjust bot parameters (Phase 3 — requires new write endpoints)

---

## Data Layer

### New table: `BotOpenSnapshot` (in `pyonex.db`, `trade_logger.Base`)

Written **once** per `bot_id` — on first detection. Never overwritten. Survives restarts because it's in SQLite. If the app was down when the bot started, "captured_at" reflects "first seen" time, not true open time.

```python
class BotOpenSnapshot(Base):
    __tablename__ = "bot_open_snapshots"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    bot_id       = Column(String(64), unique=True, nullable=False, index=True)
    symbol       = Column(String(32), nullable=False)
    captured_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # From Pionex API (stable)
    open_range_low   = Column(Float, nullable=True)
    open_range_high  = Column(Float, nullable=True)
    open_grid_count  = Column(Integer, nullable=True)
    open_created_ms  = Column(Float, nullable=True)   # createTime from Pionex (epoch ms)

    # Market indicators at first detection
    open_adx         = Column(Float, nullable=True)
    open_rsi         = Column(Float, nullable=True)
    open_bb_bw       = Column(Float, nullable=True)
    open_grid_score  = Column(Float, nullable=True)
    open_setup_score = Column(Float, nullable=True)
```

### New table: `BotAssessment` (in `pyonex.db`, `trade_logger.Base`)

Written on every poll cycle. Pruned to last 50 rows per `bot_id` after each insert.

```python
class BotAssessment(Base):
    __tablename__ = "bot_assessments"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    bot_id      = Column(String(64), nullable=False, index=True)
    symbol      = Column(String(32), nullable=False)
    assessed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    # Recommendation
    action      = Column(String(16), nullable=False)   # HOLD | CLOSE_NOW | TAKE_PROFIT | WARNING | WATCH | REVIEW
    severity    = Column(String(8),  nullable=False)   # NONE | LOW | MEDIUM | HIGH | CRITICAL
    reason      = Column(String(256), nullable=True)

    # Market snapshot at assessment time
    price       = Column(Float, nullable=True)
    price_pct   = Column(Float, nullable=True)   # % position within bot range
    adx         = Column(Float, nullable=True)
    rsi         = Column(Float, nullable=True)
    bb_bw       = Column(Float, nullable=True)
    grid_score  = Column(Float, nullable=True)
    setup_score = Column(Float, nullable=True)

    # Suggested new parameters (from _build_restart)
    suggested_range_low    = Column(Float, nullable=True)
    suggested_range_high   = Column(Float, nullable=True)
    suggested_grid_count   = Column(Integer, nullable=True)
    suggested_stop_loss    = Column(Float, nullable=True)
    suggested_take_profit  = Column(Float, nullable=True)
    suggested_grid_mode    = Column(String(16), nullable=True)
    suggested_duration     = Column(String(32), nullable=True)
```

### Helper functions added to `trade_logger.py`

| Function | Behaviour |
|---|---|
| `save_open_snapshot(snapshot: BotOpenSnapshot) -> None` | Insert if bot_id not already present (no-op on duplicate) |
| `get_open_snapshot(bot_id: str) -> BotOpenSnapshot \| None` | Fetch by bot_id |
| `save_bot_assessment(assessment: BotAssessment) -> None` | Insert row, then prune to 50 per bot_id |
| `get_bot_assessments(bot_id: str, limit: int = 10) -> list[BotAssessment]` | Return last N rows, ordered newest-first |

---

## Polling Module: `bot_monitor_loop.py` (new file)

Single public function `run_bot_monitor_cycle(payloads: dict[str, dict]) -> list[dict]`:

1. Creates `PionexClient()` — if not configured, returns `[]` silently
2. Calls `client.list_running_bots()`
3. For each bot:
   a. Resolves `symbol` from `base`/`quote` fields
   b. Looks up cached metrics from `payloads[symbol]`
   c. If metrics missing: skip (log warning)
   d. **Open snapshot**: calls `get_open_snapshot(bot_id)` — if None, creates and saves one using current Pionex bot fields + current market indicators
   e. Calls `assess_bot_health(bot, metrics, signal_info, symbol)` (existing)
   f. Calls `_build_restart(symbol, metrics, grid_score)` (existing) — always, not just on close/review
   g. Builds a `BotAssessment` row and calls `save_bot_assessment()`
4. Returns list of assessment dicts (for testing)

### How `payloads` reaches the loop

`run_bot_monitor_cycle(payloads)` is called from within the Streamlit app where `payloads` is already available (built from `all_latest()`). The scheduler job wraps it:

```python
def _bg_bot_monitor():
    from trade_logger import all_latest
    payloads = {r.symbol: r.payload for r in all_latest()}
    run_bot_monitor_cycle(payloads)
```

---

## Scheduler Integration (`app.py`)

`_start_scheduler()` gains a second job:

```python
sched.add_job(
    _bg_bot_monitor, "interval",
    seconds=600,   # 10 minutes
    id="bg_bot_monitor",
    replace_existing=True,
    next_run_time=datetime.now(timezone.utc),
)
```

---

## Redesigned Bot Card (`bot_monitor.py`)

`_render_bot_card` is extended. New layout per card:

```
┌─────────────────────────────────────────────────────┐
│ ETH/USDT                           [CLOSE NOW chip] │
│ Created 207d ago · 68 grids · Status: open          │
│                                                     │
│ [range gauge bar]                                   │
│                                                     │
│ ── AT OPEN (first seen 2026-03-01) ─────────────── │
│ Range: 3,593.86 – 5,585.21  ·  68 grids            │
│ ADX 30.4  RSI 44.5  BB 5.9%  Grid 6.0  Setup 2.0  │
│                                                     │
│ ── CURRENT CONDITIONS ──────────────────────────── │
│ Price $2,032  (–78% of range)                      │
│ ADX 27.1  RSI 46.3  BB 7.0%  Grid 5.0  Setup 0.8  │
│ Invested $182 · Grid +1.8% · Realized +0.0%        │
│                                                     │
│ ── RECOMMENDATION ──────────────────────────────── │
│ [CLOSE NOW] Bot inactive — price 78.4% below range │
│ ↳ Neutral Grid · $1,956–$2,108 · 9g · Arithmetic  │
│    ~1-3 days · SL $1,780 · TP $2,213              │
│                                                     │
│ ── HISTORY ─────────────────────────────────────── │
│ 2h ago  [CLOSE NOW]  Price below range             │
│ 8h ago  [WARNING]    Near bottom + ADX rising      │
│ 14h ago [HOLD]       In range, grid-friendly       │
└─────────────────────────────────────────────────────┘
```

**History strip rules:**
- Always visible (no expander)
- Shows last 5 `BotAssessment` rows, newest first
- Rows where action differs from the previous row are highlighted (bold label)
- If no history yet: show "No history yet — first assessment runs at next cycle (10 min)"
- Timestamps formatted as relative ("2h ago", "3d ago")

**Data flow for the card:**
```python
def _render_bot_card(bot, metrics, advice, symbol, open_snap, history):
    ...
```
`open_snap: BotOpenSnapshot | None` and `history: list[BotAssessment]` are fetched in `render_bot_monitor` before calling `_render_bot_card`.

---

## Files Changed

| File | Change |
|---|---|
| `trade_logger.py` | Add `BotOpenSnapshot`, `BotAssessment` models; add 4 helper functions |
| `bot_monitor_loop.py` | New file — `run_bot_monitor_cycle(payloads)` |
| `app.py` | Add `_bg_bot_monitor` wrapper; add second scheduler job |
| `bot_monitor.py` | Extend `_render_bot_card` signature; add "At Open", history strip sections |

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Pionex not configured | `run_bot_monitor_cycle` returns `[]` silently, no DB writes |
| Metrics missing for a bot symbol | Skip that bot, log warning |
| `_build_restart` returns None (missing price/ATR) | `suggested_*` columns stored as None; UI shows "Restart data unavailable" |
| DB write fails | Log exception, continue loop (don't crash scheduler) |
| App restart | Open snapshots survive (SQLite). History survives. First post-restart cycle re-captures any new bots. |

---

## Testing

- `tests/test_trade_logger.py`: `save_open_snapshot` (idempotent), `save_bot_assessment` (pruning to 50), `get_bot_assessments` ordering
- `tests/test_bot_monitor_loop.py` (new): `run_bot_monitor_cycle` with mocked `PionexClient` and mocked `payloads` — verify DB writes, snapshot creation, prune logic
- `tests/test_ui_streamlit.py`: `TestBotMonitor` — seed a `BotAssessment` row, confirm history strip renders in markdown
