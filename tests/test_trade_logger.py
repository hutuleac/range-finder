"""Tests for trade_logger.py — SQLAlchemy models and CRUD helpers."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine

import trade_logger as tl
from trade_logger import (
    BotAssessment,
    BotOpenSnapshot,
    MetricsCache,
    SimulatedTrade,
    add_user_pair,
    all_latest,
    close_simulated_trade,
    create_simulated_trade,
    get_active_trades,
    get_all_simulated_trades,
    get_bot_assessments,
    get_open_snapshot,
    get_simulated_trade,
    get_trade_fills,
    get_user_pairs,
    latest_metrics,
    remove_user_pair,
    save_bot_assessment,
    save_open_snapshot,
    save_simulation_update,
    upsert_metrics,
)


@pytest.fixture(autouse=True)
def in_memory_engines(monkeypatch):
    """Redirect both DB engines to isolated in-memory SQLite for every test."""
    metrics_engine = create_engine("sqlite:///:memory:", future=True)
    trades_engine  = create_engine("sqlite:///:memory:", future=True)

    tl.Base.metadata.create_all(metrics_engine)
    tl.TradesBase.metadata.create_all(trades_engine)

    monkeypatch.setattr(tl, "_engine", metrics_engine)
    monkeypatch.setattr(tl, "_trades_engine", trades_engine)
    yield


def _make_trade(**overrides) -> SimulatedTrade:
    defaults = dict(
        symbol="BTC/USDT",
        entry_price=100.0,
        range_low=90.0,
        range_high=110.0,
        num_grids=10,
        direction="Neutral",
        grid_mode="Arithmetic",
        grid_score=7.5,
        stop_loss=81.0,
        take_profit=115.5,
        profile="moderate",
        inventory=[],
    )
    defaults.update(overrides)
    return SimulatedTrade(**defaults)


# ── MetricsCache: upsert / latest / all_latest ────────────────────────

class TestMetricsCache:
    def test_insert_and_retrieve(self):
        upsert_metrics("BTC/USDT", 50000.0, 8.5, "Long", {"foo": "bar"})
        row = latest_metrics("BTC/USDT")
        assert row is not None
        assert row.price == pytest.approx(50000.0)
        assert row.score == pytest.approx(8.5)
        assert row.direction == "Long"

    def test_upsert_overwrites_existing(self):
        upsert_metrics("ETH/USDT", 3000.0, 6.0, "Neutral", {})
        upsert_metrics("ETH/USDT", 3100.0, 7.0, "Long", {"updated": True})
        row = latest_metrics("ETH/USDT")
        assert row.price == pytest.approx(3100.0)
        assert row.score == pytest.approx(7.0)

    def test_latest_metrics_returns_none_for_unknown(self):
        assert latest_metrics("UNKNOWN/USDT") is None

    def test_all_latest_returns_one_row_per_symbol(self):
        upsert_metrics("BTC/USDT", 50000.0, 8.0, "Long", {})
        upsert_metrics("ETH/USDT", 3000.0,  7.0, "Neutral", {})
        upsert_metrics("SOL/USDT", 150.0,   6.0, "Short", {})
        rows = all_latest()
        symbols = {r.symbol for r in rows}
        assert symbols == {"BTC/USDT", "ETH/USDT", "SOL/USDT"}

    def test_payload_stored_as_json(self):
        payload = {"score": 8.5, "components": [{"label": "ADX", "score": 3.0}]}
        upsert_metrics("SOL/USDT", 150.0, 8.5, "Long", payload)
        row = latest_metrics("SOL/USDT")
        assert row.payload["score"] == pytest.approx(8.5)
        assert row.payload["components"][0]["label"] == "ADX"


# ── SimulatedTrade: create / get / active / all ───────────────────────

class TestSimulatedTrade:
    def test_create_and_get_round_trip(self):
        trade = _make_trade()
        trade_id = create_simulated_trade(trade)
        assert isinstance(trade_id, int)
        fetched = get_simulated_trade(trade_id)
        assert fetched is not None
        assert fetched.symbol == "BTC/USDT"
        assert fetched.entry_price == pytest.approx(100.0)

    def test_get_nonexistent_returns_none(self):
        assert get_simulated_trade(99999) is None

    def test_default_status_is_active(self):
        trade_id = create_simulated_trade(_make_trade())
        fetched = get_simulated_trade(trade_id)
        assert fetched.status == "ACTIVE"

    def test_get_active_trades_filters_correctly(self):
        id1 = create_simulated_trade(_make_trade(symbol="BTC/USDT"))
        id2 = create_simulated_trade(_make_trade(symbol="ETH/USDT"))
        close_simulated_trade(id2, "manual", 105.0)
        active = get_active_trades()
        active_symbols = {t.symbol for t in active}
        assert "BTC/USDT" in active_symbols
        assert "ETH/USDT" not in active_symbols

    def test_get_all_simulated_trades_returns_all(self):
        create_simulated_trade(_make_trade(symbol="BTC/USDT"))
        create_simulated_trade(_make_trade(symbol="ETH/USDT"))
        all_trades = get_all_simulated_trades()
        assert len(all_trades) == 2


# ── close_simulated_trade ────────────────────────────────────────────

class TestCloseSimulatedTrade:
    def test_sets_status_to_closed(self):
        trade_id = create_simulated_trade(_make_trade())
        close_simulated_trade(trade_id, "manual close", 108.0)
        trade = get_simulated_trade(trade_id)
        assert trade.status == "CLOSED"
        assert trade.close_reason == "manual close"
        assert trade.close_price == pytest.approx(108.0)

    def test_sets_custom_status(self):
        trade_id = create_simulated_trade(_make_trade())
        close_simulated_trade(trade_id, "stop hit", 89.0, status="SL_HIT")
        trade = get_simulated_trade(trade_id)
        assert trade.status == "SL_HIT"

    def test_nonexistent_id_does_not_raise(self):
        close_simulated_trade(99999, "reason", 100.0)  # should not raise


# ── save_simulation_update ────────────────────────────────────────────

class TestSaveSimulationUpdate:
    def test_updates_inventory_and_candle(self):
        trade_id = create_simulated_trade(_make_trade())
        save_simulation_update(trade_id, [0, 2, 4], 1_700_000.0, 102.5, [])
        trade = get_simulated_trade(trade_id)
        assert trade.inventory == [0, 2, 4]
        assert trade.last_candle_ts == pytest.approx(1_700_000.0)
        assert trade.last_candle_close == pytest.approx(102.5)

    def test_appends_fills(self):
        trade_id = create_simulated_trade(_make_trade())
        fills = [
            {"candle_ts": 1_000.0, "action": "BUY",  "level": 98.0, "level_idx": 2},
            {"candle_ts": 2_000.0, "action": "SELL", "level": 102.0, "level_idx": 2,
             "paired_level": 98.0, "pnl_pct": 0.8, "pnl_usd": 2.4},
        ]
        save_simulation_update(trade_id, [], 2_000.0, 102.0, fills)
        fetched_fills = get_trade_fills(trade_id)
        assert len(fetched_fills) == 2
        assert fetched_fills[0].action == "BUY"
        assert fetched_fills[1].pnl_pct == pytest.approx(0.8)

    def test_closes_trade_when_status_not_active(self):
        trade_id = create_simulated_trade(_make_trade())
        save_simulation_update(trade_id, [], 3_000.0, 89.0, [],
                               new_status="SL_HIT", close_reason="below SL", close_price=89.0)
        trade = get_simulated_trade(trade_id)
        assert trade.status == "SL_HIT"
        assert trade.close_reason == "below SL"
        assert trade.closed_at is not None

    def test_nonexistent_trade_does_not_raise(self):
        save_simulation_update(99999, [], 0.0, 0.0, [])

    def test_status_stays_active_when_not_overridden(self):
        trade_id = create_simulated_trade(_make_trade())
        save_simulation_update(trade_id, [1, 3], 500.0, 101.0, [])
        trade = get_simulated_trade(trade_id)
        assert trade.status == "ACTIVE"


# ── get_trade_fills ───────────────────────────────────────────────────

class TestGetTradeFills:
    def test_empty_fills_for_new_trade(self):
        trade_id = create_simulated_trade(_make_trade())
        assert get_trade_fills(trade_id) == []

    def test_fills_ordered_by_candle_ts(self):
        trade_id = create_simulated_trade(_make_trade())
        fills = [
            {"candle_ts": 3_000.0, "action": "BUY", "level": 100.0},
            {"candle_ts": 1_000.0, "action": "BUY", "level": 99.0},
            {"candle_ts": 2_000.0, "action": "BUY", "level": 101.0},
        ]
        save_simulation_update(trade_id, [], 3_000.0, 100.0, fills)
        fetched = get_trade_fills(trade_id)
        ts = [f.candle_ts for f in fetched]
        assert ts == sorted(ts)


# ── UserPair: custom pair management ──────────────────────────────────

class TestUserPairs:
    def test_get_user_pairs_empty(self):
        assert get_user_pairs() == []

    def test_add_and_get(self):
        add_user_pair("LINK/USDT", "crypto")
        pairs = get_user_pairs()
        assert "LINK/USDT" in pairs

    def test_add_stock_pair(self):
        add_user_pair("TSLAX/USD", "stock")
        assert "TSLAX/USD" in get_user_pairs()

    def test_add_is_idempotent(self):
        add_user_pair("LINK/USDT", "crypto")
        add_user_pair("LINK/USDT", "crypto")
        assert get_user_pairs().count("LINK/USDT") == 1

    def test_remove_existing(self):
        add_user_pair("AVAX/USDT", "crypto")
        remove_user_pair("AVAX/USDT")
        assert "AVAX/USDT" not in get_user_pairs()

    def test_remove_nonexistent_does_not_raise(self):
        remove_user_pair("DOES_NOT_EXIST/USDT")

    def test_get_returns_symbols_in_order(self):
        add_user_pair("LINK/USDT", "crypto")
        add_user_pair("AVAX/USDT", "crypto")
        pairs = get_user_pairs()
        assert pairs.index("LINK/USDT") < pairs.index("AVAX/USDT")


# ── BotOpenSnapshot + BotAssessment ──────────────────────────────────────────

class TestBotPersistence:
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
        save_open_snapshot(snap)
        assert get_open_snapshot("bot-002") is not None

    def test_get_open_snapshot_returns_none_for_unknown(self):
        assert get_open_snapshot("nonexistent-bot") is None

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
