"""Tests for trade_simulator.py — grid math, P&L, and the simulation lifecycle.

Pure functions (build_grid_levels, initial_inventory, process_candle, calc_pnl)
are tested directly. The lifecycle functions (open_trade, update_simulation,
close_trade) touch the trades DB, so we redirect trade_logger's engine to an
in-memory SQLite and mock fetch_klines at the simulator boundary.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

import trade_logger as tl
import trade_simulator as sim
from trade_logger import SimulatedTrade, get_simulated_trade


@pytest.fixture(autouse=True)
def in_memory_trades_db(monkeypatch):
    trades_engine = create_engine("sqlite:///:memory:", future=True)
    tl.TradesBase.metadata.create_all(trades_engine)
    monkeypatch.setattr(tl, "_trades_engine", trades_engine)
    yield


def _candle(ts, o, h, l, c):
    """4H kline row — simulator only reads indices 0-4."""
    return [ts, o, h, l, c, 0, 0, 0, 0, 0, 0, 0]


def _payload(entry=100.0, low=90.0, high=110.0, grids=10):
    return {
        "metrics": {"currClose": entry},
        "scoreInfo": {"score": 7.5},
        "direction": {"type": "Neutral"},
        "range": {"rangeLow": low, "rangeHigh": high},
        "gridCount": {"recommended": grids},
        "mode": {"mode": "Arithmetic"},
        "signalInfo": {"setup_score": 6.0},
    }


# ── grid math ─────────────────────────────────────────────────────────

class TestGridMath:
    def test_build_grid_levels_count_and_bounds(self):
        levels = sim.build_grid_levels(90.0, 110.0, 10)
        assert len(levels) == 11          # num_grids + 1
        assert levels[0] == 90.0
        assert levels[-1] == 110.0
        # evenly spaced
        assert levels[1] - levels[0] == pytest.approx(2.0)

    def test_initial_inventory_prebuys_levels_below_entry(self):
        levels = sim.build_grid_levels(90.0, 110.0, 10)  # 90,92,...,110
        inv = sim.initial_inventory(levels, entry_price=100.0)
        # levels strictly below 100: indices 0..4 (90,92,94,96,98)
        assert inv == [0, 1, 2, 3, 4]

    def test_initial_inventory_empty_when_entry_at_bottom(self):
        levels = sim.build_grid_levels(90.0, 110.0, 10)
        assert sim.initial_inventory(levels, entry_price=90.0) == []


class TestProcessCandle:
    def test_bull_candle_buys_dip_levels(self):
        levels = sim.build_grid_levels(90.0, 110.0, 10)
        inv = []
        # open 100, dips to 96 → buy levels in [96,100): 96, 98
        fills = sim.process_candle(inv, levels, o=100, h=101, l=96, c=100.5,
                                   candle_ts=1, fee_pct=0.001, per_grid_capital=None)
        buys = [f for f in fills if f["action"] == "BUY"]
        assert {f["level"] for f in buys} == {96.0, 98.0}
        assert sorted(inv) == [3, 4]

    def test_sell_pairs_inventory_and_nets_fees(self):
        levels = sim.build_grid_levels(90.0, 110.0, 10)
        inv = [4]  # holding level idx 4 (bought at 98)
        # open 99, rises to 101 → sell at level 100 (idx 5), pairs idx 4
        fills = sim.process_candle(inv, levels, o=99, h=101, l=99, c=101,
                                   candle_ts=2, fee_pct=0.001, per_grid_capital=1000.0)
        sells = [f for f in fills if f["action"] == "SELL"]
        assert len(sells) == 1
        s = sells[0]
        assert s["paired_level"] == 98.0
        # raw pnl (100-98)/98 minus 2*fee
        raw = (100.0 - 98.0) / 98.0
        assert s["pnl_pct"] == pytest.approx(raw - 0.002)
        assert s["pnl_usd"] == pytest.approx((raw - 0.002) * 1000.0)
        assert inv == []  # position closed

    def test_no_double_buy_when_already_held(self):
        levels = sim.build_grid_levels(90.0, 110.0, 10)
        inv = [3]  # already hold level 96
        fills = sim.process_candle(inv, levels, o=100, h=100, l=96, c=99,
                                   candle_ts=3, fee_pct=0.001, per_grid_capital=None)
        bought_96 = [f for f in fills if f["action"] == "BUY" and f["level"] == 96.0]
        assert bought_96 == []  # not re-bought

    def test_bear_candle_processes_sells_before_buys(self):
        # A wide candle: open high, wick up to trigger a sell, then dip to buy.
        levels = sim.build_grid_levels(90.0, 110.0, 10)
        inv = [4]  # hold 98, sell target 100
        fills = sim.process_candle(inv, levels, o=99, h=101, l=96, c=97,
                                   candle_ts=4, fee_pct=0.0, per_grid_capital=None)
        actions = [f["action"] for f in fills]
        assert "SELL" in actions and "BUY" in actions
        # sell recorded before buys for bearish candle
        assert actions.index("SELL") < actions.index("BUY")


# ── P&L ───────────────────────────────────────────────────────────────

class TestCalcPnl:
    def test_realized_and_unrealized_combine(self):
        # Open a trade, persist a SELL fill, leave one open position.
        trade = SimulatedTrade(
            symbol="BTC/USDT", entry_price=100.0, range_low=90.0, range_high=110.0,
            num_grids=10, direction="Neutral", grid_mode="Arithmetic", grid_score=7.0,
            stop_loss=81.0, take_profit=115.5, capital=1000.0, profile="moderate",
            inventory=[4],  # holding level idx 4 = 98.0
        )
        tid = tl.create_simulated_trade(trade)
        tl.save_simulation_update(
            trade_id=tid, inventory=[4], last_candle_ts=1.0, last_candle_close=100.0,
            fills=[{
                "candle_ts": 1.0, "action": "SELL", "level_idx": 5, "level": 100.0,
                "paired_level": 98.0, "pnl_pct": 0.02, "pnl_usd": 2.0,
            }],
        )
        stored = get_simulated_trade(tid)
        out = sim.calc_pnl(stored, current_price=104.0)
        assert out["cycle_count"] == 1
        assert out["open_positions"] == 1
        assert out["realized_pct"] > 0
        assert out["unrealized_pct"] > 0  # price 104 > held level 98
        assert out["total_pct"] == pytest.approx(out["realized_pct"] + out["unrealized_pct"])
        assert out["total_usd"] is not None

    def test_no_capital_yields_none_usd(self):
        trade = SimulatedTrade(
            symbol="X/USDT", entry_price=100.0, range_low=90.0, range_high=110.0,
            num_grids=10, direction="Neutral", grid_mode="Arithmetic", grid_score=7.0,
            stop_loss=81.0, take_profit=115.5, capital=None, profile="moderate",
            inventory=[],
        )
        tid = tl.create_simulated_trade(trade)
        out = sim.calc_pnl(get_simulated_trade(tid), current_price=100.0)
        assert out["total_usd"] is None


# ── open / close ──────────────────────────────────────────────────────

class TestOpenClose:
    def test_open_trade_persists_grid_params(self):
        tid = sim.open_trade(_payload(), "BTC/USDT", capital=500.0, profile="moderate")
        t = get_simulated_trade(tid)
        assert t.symbol == "BTC/USDT"
        assert t.num_grids == 10
        assert t.range_low == 90.0 and t.range_high == 110.0
        assert t.capital == 500.0
        assert t.setup_score == 6.0
        assert t.status == "ACTIVE"
        # entry 100 over 90-110 grid → levels below 100 pre-bought
        assert t.inventory == [0, 1, 2, 3, 4]

    def test_close_trade_sets_closed_state(self):
        tid = sim.open_trade(_payload(), "ETH/USDT")
        sim.close_trade(tid, price=95.0, reason="Manual close")
        t = get_simulated_trade(tid)
        assert t.status == "CLOSED"
        assert t.close_price == 95.0
        assert t.close_reason == "Manual close"


# ── update_simulation ─────────────────────────────────────────────────

class TestUpdateSimulation:
    def test_trade_not_found(self):
        assert sim.update_simulation(9999) == {"error": "trade not found"}

    def test_non_active_short_circuits(self):
        tid = sim.open_trade(_payload(), "BTC/USDT")
        sim.close_trade(tid, price=100.0)
        out = sim.update_simulation(tid)
        assert out["status"] == "CLOSED"
        assert out["new_fills"] == 0

    def test_throttled_when_updated_recently(self):
        # Stub the loaded trade with an aware "just simulated" timestamp so the
        # throttle branch is exercised deterministically, independent of how
        # SQLite round-trips tz-aware datetimes on this host.
        from types import SimpleNamespace
        stub = SimpleNamespace(
            id=1, status="ACTIVE",
            last_simulated_at=datetime.now(timezone.utc),
        )
        with patch.object(sim, "get_simulated_trade", return_value=stub):
            out = sim.update_simulation(1)
        assert out["status"] == "throttled"

    def test_throttle_handles_naive_timestamp_from_sqlite(self):
        """Regression: SQLite returns last_simulated_at naive. as_utc must tag
        it UTC so the age is computed correctly and the throttle still fires,
        regardless of the host's local timezone."""
        from types import SimpleNamespace
        naive_now = datetime.now(timezone.utc).replace(tzinfo=None)  # as SQLite gives it back
        stub = SimpleNamespace(id=1, status="ACTIVE", last_simulated_at=naive_now)
        with patch.object(sim, "get_simulated_trade", return_value=stub):
            out = sim.update_simulation(1)
        assert out["status"] == "throttled"

    def test_no_klines_returns_error(self):
        tid = sim.open_trade(_payload(), "BTC/USDT")
        with patch.object(sim, "fetch_klines", return_value=[]):
            out = sim.update_simulation(tid)
        assert "error" in out

    def test_up_to_date_when_no_new_candles(self):
        tid = sim.open_trade(_payload(), "BTC/USDT")
        # All candles older than opened_at → none replayed
        old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp() * 1000
        with patch.object(sim, "fetch_klines", return_value=[_candle(old_ts, 100, 101, 99, 100)]):
            out = sim.update_simulation(tid)
        assert out["status"] == "up_to_date"

    def test_fills_generated_from_new_candles(self):
        tid = sim.open_trade(_payload(entry=100.0, low=90.0, high=110.0, grids=10),
                             "BTC/USDT")
        future_ts = (datetime.now(timezone.utc) + timedelta(hours=4)).timestamp() * 1000
        # Open below the held levels' sell targets (idx4 bought@98 → target 100),
        # then rise to 104 so those pre-bought positions sell.
        candle = _candle(future_ts, 99, 104, 99, 103)
        with patch.object(sim, "fetch_klines", return_value=[candle]):
            out = sim.update_simulation(tid)
        assert out["status"] == "ACTIVE"
        assert out["candles"] == 1
        assert out["sell_fills"] >= 1

    def test_stop_loss_hit_closes_trade(self):
        tid = sim.open_trade(_payload(entry=100.0, low=90.0, high=110.0, grids=10),
                             "BTC/USDT")
        t = get_simulated_trade(tid)
        future_ts = (datetime.now(timezone.utc) + timedelta(hours=4)).timestamp() * 1000
        crash = t.stop_loss - 1.0
        candle = _candle(future_ts, 100, 100, crash, crash)
        with patch.object(sim, "fetch_klines", return_value=[candle]):
            out = sim.update_simulation(tid)
        assert out["status"] == "SL_HIT"
        assert get_simulated_trade(tid).status == "SL_HIT"

    def test_take_profit_hit_closes_trade(self):
        tid = sim.open_trade(_payload(entry=100.0, low=90.0, high=110.0, grids=10),
                             "BTC/USDT")
        t = get_simulated_trade(tid)
        future_ts = (datetime.now(timezone.utc) + timedelta(hours=4)).timestamp() * 1000
        moon = t.take_profit + 1.0
        candle = _candle(future_ts, 100, moon, 100, moon)
        with patch.object(sim, "fetch_klines", return_value=[candle]):
            out = sim.update_simulation(tid)
        assert out["status"] == "TP_HIT"


# ── update_all_active ─────────────────────────────────────────────────

class TestUpdateAllActive:
    def test_aggregates_results_for_active_trades(self):
        t1 = sim.open_trade(_payload(), "BTC/USDT")
        t2 = sim.open_trade(_payload(), "ETH/USDT")
        with patch.object(sim, "update_simulation",
                          side_effect=lambda tid: {"status": "up_to_date", "new_fills": 0}):
            results = sim.update_all_active()
        ids = {r["trade_id"] for r in results}
        assert ids == {t1, t2}
        assert all("symbol" in r for r in results)

    def test_silent_swallows_errors(self):
        sim.open_trade(_payload(), "BTC/USDT")
        with patch.object(sim, "update_simulation", side_effect=RuntimeError("boom")):
            results = sim.update_all_active(silent=True)
        assert results == []  # error swallowed, nothing appended

    def test_non_silent_reraises(self):
        sim.open_trade(_payload(), "BTC/USDT")
        with patch.object(sim, "update_simulation", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                sim.update_all_active(silent=False)
