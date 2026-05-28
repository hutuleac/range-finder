"""Tests for trade_logger.py — SQLAlchemy models and CRUD helpers."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine

import trade_logger as tl
from trade_logger import (
    MetricsCache,
    SimulatedTrade,
    all_latest,
    close_simulated_trade,
    create_simulated_trade,
    get_active_trades,
    get_all_simulated_trades,
    get_simulated_trade,
    get_trade_fills,
    latest_metrics,
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
