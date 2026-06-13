"""Tests for bot_advisor.py — price position, trend, profit, duration, recommendations."""
from __future__ import annotations

import time

import pytest

from bot_advisor import (
    _check_duration,
    _check_price_position,
    _check_profit,
    _check_trend,
    _generate_recommendation,
    assess_bot_health,
)
from config import BOT_MONITOR_CFG as BC


# ── _check_price_position ─────────────────────────────────────────────

class TestCheckPricePosition:
    def test_invalid_range_returns_unknown(self):
        result = _check_price_position(100.0, 110.0, 100.0)  # upper <= lower
        assert result["zone"] == "UNKNOWN"

    def test_below_range(self):
        result = _check_price_position(85.0, 90.0, 110.0)
        assert result["zone"] == "BELOW_RANGE"
        assert result["pct"] < 0

    def test_above_range(self):
        result = _check_price_position(115.0, 90.0, 110.0)
        assert result["zone"] == "ABOVE_RANGE"
        assert result["pct"] > 100

    def test_near_bottom(self):
        # 5% of range → NEAR_BOTTOM (< 10%)
        result = _check_price_position(91.0, 90.0, 110.0)
        assert result["zone"] == "NEAR_BOTTOM"

    def test_near_top(self):
        # 95% of range → NEAR_TOP (> 90%)
        result = _check_price_position(109.0, 90.0, 110.0)
        assert result["zone"] == "NEAR_TOP"

    def test_in_range(self):
        result = _check_price_position(100.0, 90.0, 110.0)
        assert result["zone"] == "IN_RANGE"

    def test_pct_calculation(self):
        result = _check_price_position(100.0, 90.0, 110.0)
        assert result["pct"] == pytest.approx(50.0)

    def test_result_has_required_keys(self):
        result = _check_price_position(100.0, 90.0, 110.0)
        assert {"zone", "pct", "detail"} == result.keys()


# ── _check_trend ──────────────────────────────────────────────────────

class TestCheckTrend:
    def _metrics_with_adx(self, adx_val: float) -> dict:
        return {"adx": {"adx": adx_val, "plusDI": 20.0, "minusDI": 15.0}}

    def test_high_adx_returns_not_aligned_high_severity(self):
        result = _check_trend(self._metrics_with_adx(BC["ADX_EXIT"] + 1), None)
        assert result["aligned"] is False
        assert result["severity"] == "HIGH"

    def test_medium_adx_returns_not_aligned_medium_severity(self):
        result = _check_trend(self._metrics_with_adx(26.0), None)
        assert result["aligned"] is False
        assert result["severity"] == "MEDIUM"

    def test_long_setup_signal_not_aligned(self):
        metrics = self._metrics_with_adx(15.0)
        signal = {"signal_type": {"type": "LONG_SETUP"}}
        result = _check_trend(metrics, signal)
        assert result["aligned"] is False
        assert result["severity"] == "MEDIUM"

    def test_grid_window_signal_aligned(self):
        metrics = self._metrics_with_adx(15.0)
        signal = {"signal_type": {"type": "GRID_WINDOW"}}
        result = _check_trend(metrics, signal)
        assert result["aligned"] is True
        assert result["severity"] == "NONE"

    def test_low_adx_no_signal_is_aligned(self):
        result = _check_trend(self._metrics_with_adx(15.0), None)
        assert result["aligned"] is True
        assert result["severity"] == "NONE"

    def test_none_signal_handled_gracefully(self):
        result = _check_trend(self._metrics_with_adx(10.0), None)
        assert "aligned" in result


# ── _check_profit ─────────────────────────────────────────────────────

class TestCheckProfit:
    def _bot(self, grid_profit: float, realized: float = 0.0, quote_inv: float = 500.0) -> dict:
        return {
            "gridProfit":       str(grid_profit),
            "realizedProfit":   str(realized),
            "quoteInvestment":  str(quote_inv),
            "baseInvestment":   "0.0",
        }

    def test_tp_signal_when_above_threshold(self):
        # 3% on 500 = 15 → TP
        result = _check_profit(self._bot(15.0), 100.0)
        assert result["signal"] == "TP"

    def test_loss_signal_when_below_threshold(self):
        # -5% on 500 = -25 → LOSS
        result = _check_profit(self._bot(0.0, realized=-26.0), 100.0)
        assert result["signal"] == "LOSS"

    def test_ok_signal_in_normal_range(self):
        result = _check_profit(self._bot(5.0, realized=1.0), 100.0)
        assert result["signal"] == "OK"

    def test_grid_profit_pct_correct(self):
        result = _check_profit(self._bot(10.0, quote_inv=200.0), 100.0)
        assert result["gridProfitPct"] == pytest.approx(5.0)

    def test_invested_defaults_to_1_when_zero(self):
        bot = {"gridProfit": "5.0", "realizedProfit": "0", "quoteInvestment": "0", "baseInvestment": "0"}
        result = _check_profit(bot, 100.0)
        assert result["invested"] == pytest.approx(1.0)

    def test_result_has_required_keys(self):
        result = _check_profit(self._bot(5.0), 100.0)
        assert {"gridProfit", "gridProfitPct", "realized", "realizedPct", "invested", "signal", "detail"} == result.keys()


# ── _check_duration ───────────────────────────────────────────────────

class TestCheckDuration:
    def test_zero_create_time_returns_unknown(self):
        result = _check_duration({"createTime": 0})
        assert result["days"] == 0
        assert result["flag"] is False

    def test_recent_bot_not_flagged(self):
        recent_ts = int(time.time() * 1000) - 2 * 86_400_000  # 2 days ago
        result = _check_duration({"createTime": recent_ts})
        assert result["flag"] is False
        assert result["days"] == pytest.approx(2.0, abs=0.1)

    def test_old_bot_flagged(self):
        old_ts = int(time.time() * 1000) - 20 * 86_400_000  # 20 days ago
        result = _check_duration({"createTime": old_ts})
        assert result["flag"] is True

    def test_result_has_required_keys(self):
        result = _check_duration({"createTime": int(time.time() * 1000)})
        assert {"days", "flag", "detail"} == result.keys()


# ── _generate_recommendation ──────────────────────────────────────────

class TestGenerateRecommendation:
    def _pos(self, zone: str, pct: float = 50.0) -> dict:
        return {"zone": zone, "pct": pct, "detail": f"at {pct:.0f}%"}

    def _trend(self, aligned: bool, severity: str = "NONE") -> dict:
        return {"aligned": aligned, "severity": severity, "detail": "some detail"}

    def _profit(self, signal: str, pct: float = 1.0) -> dict:
        return {"signal": signal, "gridProfitPct": pct, "detail": "some detail"}

    def _dur(self, flag: bool) -> dict:
        return {"days": 20 if flag else 5, "flag": flag, "detail": "running X days"}

    def test_below_range_returns_close_now(self):
        rec = _generate_recommendation(self._pos("BELOW_RANGE"), self._trend(True), self._profit("OK"), self._dur(False))
        assert rec["action"] == "CLOSE_NOW"
        assert rec["severity"] == "CRITICAL"

    def test_above_range_returns_close_now(self):
        rec = _generate_recommendation(self._pos("ABOVE_RANGE"), self._trend(True), self._profit("OK"), self._dur(False))
        assert rec["action"] == "CLOSE_NOW"

    def test_near_bottom_unaligned_returns_close_now(self):
        rec = _generate_recommendation(self._pos("NEAR_BOTTOM"), self._trend(False, "HIGH"), self._profit("OK"), self._dur(False))
        assert rec["action"] == "CLOSE_NOW"

    def test_near_top_unaligned_returns_take_profit(self):
        rec = _generate_recommendation(self._pos("NEAR_TOP"), self._trend(False, "MEDIUM"), self._profit("OK"), self._dur(False))
        assert rec["action"] == "TAKE_PROFIT"

    def test_strong_trend_returns_warning(self):
        rec = _generate_recommendation(self._pos("IN_RANGE"), self._trend(False, "HIGH"), self._profit("OK"), self._dur(False))
        assert rec["action"] == "WARNING"

    def test_strong_trend_plus_tp_returns_take_profit(self):
        rec = _generate_recommendation(self._pos("IN_RANGE"), self._trend(False, "HIGH"), self._profit("TP", 5.0), self._dur(False))
        assert rec["action"] == "TAKE_PROFIT"

    def test_profit_target_returns_take_profit(self):
        rec = _generate_recommendation(self._pos("IN_RANGE"), self._trend(True), self._profit("TP", 5.0), self._dur(False))
        assert rec["action"] == "TAKE_PROFIT"

    def test_loss_returns_warning(self):
        rec = _generate_recommendation(self._pos("IN_RANGE"), self._trend(True), self._profit("LOSS", -6.0), self._dur(False))
        assert rec["action"] == "WARNING"

    def test_long_duration_returns_review(self):
        rec = _generate_recommendation(self._pos("IN_RANGE"), self._trend(True), self._profit("OK"), self._dur(True))
        assert rec["action"] == "REVIEW"

    def test_near_bottom_aligned_returns_watch(self):
        rec = _generate_recommendation(self._pos("NEAR_BOTTOM"), self._trend(True), self._profit("OK"), self._dur(False))
        assert rec["action"] == "WATCH"

    def test_healthy_bot_returns_hold(self):
        rec = _generate_recommendation(self._pos("IN_RANGE"), self._trend(True), self._profit("OK"), self._dur(False))
        assert rec["action"] == "HOLD"
        assert rec["severity"] == "NONE"

    def test_result_has_required_keys(self):
        rec = _generate_recommendation(self._pos("IN_RANGE"), self._trend(True), self._profit("OK"), self._dur(False))
        assert {"action", "reason", "severity"} == rec.keys()


# ── assess_bot_health (integration) ───────────────────────────────────

class TestAssessBotHealth:
    def test_healthy_bot_holds(self, mock_bot, mock_metrics):
        mock_metrics["currClose"] = 100.0
        result = assess_bot_health(mock_bot, mock_metrics)
        assert result["recommendation"]["action"] == "HOLD"
        assert "position" in result
        assert "trend" in result
        assert "profit" in result
        assert "duration" in result

    def test_price_below_range_closes(self, mock_bot, mock_metrics):
        mock_metrics["currClose"] = 80.0  # below lower=90
        result = assess_bot_health(mock_bot, mock_metrics)
        assert result["recommendation"]["action"] == "CLOSE_NOW"

    def test_price_above_range_closes(self, mock_bot, mock_metrics):
        mock_metrics["currClose"] = 120.0  # above upper=110
        result = assess_bot_health(mock_bot, mock_metrics)
        assert result["recommendation"]["action"] == "CLOSE_NOW"

    def test_restart_included_on_close(self, mock_bot, mock_metrics):
        mock_metrics["currClose"] = 80.0
        mock_metrics["atrPct"] = 2.5
        mock_metrics["structure4h"] = "Neutral"
        result = assess_bot_health(mock_bot, mock_metrics, symbol="ETH/USDT")
        # restart may be None if price/atr invalid, just check key exists
        assert "restart" in result

    def test_restart_direction_from_matrix(self, mock_bot, mock_metrics):
        # On a CLOSE, the restart direction is chosen by argmax over the matrix
        # grid columns injected as _matrix_scores (not the legacy grid score).
        mock_metrics["currClose"] = 80.0  # below range → CLOSE_NOW
        mock_metrics["atrPct"] = 2.5
        mock_metrics["_matrix_scores"] = {
            "GRID_NEUTRAL": 60.0, "GRID_LONG": 50.0, "GRID_SHORT": 78.0,
        }
        result = assess_bot_health(mock_bot, mock_metrics, symbol="ETH/USDT")
        assert result["restart"] is not None
        assert result["restart"]["direction"] == "Short"

    def test_result_has_all_top_level_keys(self, mock_bot, mock_metrics):
        mock_metrics["currClose"] = 100.0
        result = assess_bot_health(mock_bot, mock_metrics)
        assert {"position", "trend", "profit", "duration", "recommendation", "restart"} == result.keys()
