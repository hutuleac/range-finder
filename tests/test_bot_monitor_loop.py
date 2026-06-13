"""Tests for bot_monitor_loop.py — run_bot_monitor_cycle."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import trade_logger as tl
import bot_monitor_loop as bml
from bot_monitor_loop import _flatten_bot, _resolve_symbol, run_bot_monitor_cycle


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
        "matrix": {"scores": {"GRID_NEUTRAL": 72.0, "GRID_LONG": 80.0,
                              "GRID_SHORT": 50.0, "DIRECTIONAL": 40.0}},
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
        assert snap.open_adx == pytest.approx(30.0)

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
            result = run_bot_monitor_cycle({})
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


def _configured_client(bots):
    """Build a patched PionexClient context returning the given bots."""
    mock = patch("bot_monitor_loop.PionexClient")
    return mock, bots


class TestResolveSymbol:
    def test_prefers_base_quote_fields(self):
        assert _resolve_symbol({"base": "ETH", "quote": "USDT"}) == "ETH/USDT"

    @pytest.mark.parametrize("symbol,expected", [
        ("BTCUSDT", "BTC/USDT"),
        ("ETHBTC", "ETH/BTC"),
        ("SOLUSD", "SOL/USD"),
    ], ids=["usdt", "btc-quote", "usd"])
    def test_splits_symbol_suffix_when_no_base_quote(self, symbol, expected):
        assert _resolve_symbol({"symbol": symbol}) == expected

    def test_returns_raw_symbol_when_unrecognised(self):
        assert _resolve_symbol({"symbol": "WEIRDPAIR"}) == "WEIRDPAIR"


class TestFlattenBot:
    def test_uses_top_bottom_row_aliases(self):
        raw = {"buOrderData": {"top": "110", "bottom": "90", "row": 15}}
        bot = _flatten_bot(raw)
        assert bot["upperPrice"] == "110"
        assert bot["lowerPrice"] == "90"
        assert bot["gridNum"] == 15

    def test_top_level_values_take_precedence(self):
        raw = {"upperPrice": "999", "buOrderData": {"upperPrice": "110", "top": "120"}}
        assert _flatten_bot(raw)["upperPrice"] == "999"


class TestCycleEdgeCases:
    def test_list_bots_exception_returns_empty(self):
        with patch("bot_monitor_loop.PionexClient") as MockClient:
            MockClient.return_value.configured = True
            MockClient.return_value.list_running_bots.side_effect = RuntimeError("api down")
            assert run_bot_monitor_cycle({"BTC/USDT": _fake_payload()}) == []

    def test_bot_without_id_is_skipped(self):
        bot = _fake_bot()
        bot["buOrderId"] = ""
        with patch("bot_monitor_loop.PionexClient") as MockClient:
            MockClient.return_value.configured = True
            MockClient.return_value.list_running_bots.return_value = [bot]
            assert run_bot_monitor_cycle({"BTC/USDT": _fake_payload()}) == []

    def test_skips_when_no_curr_close(self):
        payload = _fake_payload()
        payload["metrics"]["currClose"] = 0.0
        with patch("bot_monitor_loop.PionexClient") as MockClient:
            MockClient.return_value.configured = True
            MockClient.return_value.list_running_bots.return_value = [_fake_bot()]
            result = run_bot_monitor_cycle({"BTC/USDT": payload})
        assert result == []
        # snapshot not written because currClose check precedes it
        assert tl.get_open_snapshot("bot-001") is None

    def test_assess_failure_skips_bot(self):
        with patch("bot_monitor_loop.PionexClient") as MockClient, \
             patch("bot_monitor_loop.assess_bot_health", side_effect=ValueError("bad")):
            MockClient.return_value.configured = True
            MockClient.return_value.list_running_bots.return_value = [_fake_bot()]
            result = run_bot_monitor_cycle({"BTC/USDT": _fake_payload()})
        assert result == []
        assert tl.get_bot_assessments("bot-001") == []

    def test_no_restart_leaves_suggested_params_none(self):
        with patch("bot_monitor_loop.PionexClient") as MockClient, \
             patch("bot_monitor_loop._build_restart", return_value=None):
            MockClient.return_value.configured = True
            MockClient.return_value.list_running_bots.return_value = [_fake_bot()]
            run_bot_monitor_cycle({"BTC/USDT": _fake_payload()})
        row = tl.get_bot_assessments("bot-001")[0]
        assert row.suggested_range_low is None
        assert row.suggested_stop_loss is None
        assert row.suggested_grid_count is None

    def test_save_assessment_failure_skips_bot(self):
        with patch("bot_monitor_loop.PionexClient") as MockClient, \
             patch("bot_monitor_loop.save_bot_assessment", side_effect=RuntimeError("db")):
            MockClient.return_value.configured = True
            MockClient.return_value.list_running_bots.return_value = [_fake_bot()]
            result = run_bot_monitor_cycle({"BTC/USDT": _fake_payload()})
        assert result == []
