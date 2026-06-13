"""Tests for grid_calculator.py — scoring, range, and direction logic."""
from __future__ import annotations

import pytest

from config import GRID_CONFIG
from grid_calculator import (
    assess_grid_viability,
    calc_drawdown_scenario,
    calc_grid_capital_per_grid,
    calc_grid_profit_per_grid,
    calc_grid_score,
    calc_grid_stop_loss,
    calc_grid_take_profit,
    calc_range_from_atr,
    calc_recommended_grid_count,
    estimate_grid_duration,
    get_ticker_grid_profile,
    grid_headline_label,
    select_grid_direction,
    select_grid_mode,
)

FEE = GRID_CONFIG["FEE_PCT"]


# ── calc_grid_profit_per_grid ─────────────────────────────────────────

class TestCalcGridProfitPerGrid:
    def test_zero_grid_count_returns_not_viable(self):
        result = calc_grid_profit_per_grid(110.0, 90.0, 0)
        assert result["isViable"] is False
        assert result["netPct"] == 0.0

    def test_zero_range_low_returns_not_viable(self):
        result = calc_grid_profit_per_grid(110.0, 0.0, 10)
        assert result["isViable"] is False

    def test_arithmetic_gross_correct(self):
        result = calc_grid_profit_per_grid(110.0, 100.0, 10, is_geometric=False)
        expected_gross = (110.0 - 100.0) / 100.0 / 10
        assert result["grossPct"] == pytest.approx(expected_gross)

    def test_geometric_gross_correct(self):
        result = calc_grid_profit_per_grid(110.0, 100.0, 10, is_geometric=True)
        expected_gross = (110.0 / 100.0) ** (1.0 / 10) - 1.0
        assert result["grossPct"] == pytest.approx(expected_gross)

    def test_net_is_gross_minus_fee_round_trip(self):
        result = calc_grid_profit_per_grid(110.0, 100.0, 5)
        assert result["netPct"] == pytest.approx(result["grossPct"] - FEE * 2)

    def test_viable_when_net_above_min(self):
        # Wide range, few grids → large net
        result = calc_grid_profit_per_grid(200.0, 100.0, 5)
        assert result["isViable"] is True

    def test_not_viable_when_net_below_min(self):
        # Tiny range, many grids → negligible net
        result = calc_grid_profit_per_grid(100.1, 100.0, 1000)
        assert result["isViable"] is False


# ── calc_grid_capital_per_grid ────────────────────────────────────────

class TestCalcGridCapitalPerGrid:
    def test_zero_grid_count_returns_zero(self):
        assert calc_grid_capital_per_grid(300.0, 0) == 0.0

    def test_correct_division(self):
        assert calc_grid_capital_per_grid(300.0, 10) == pytest.approx(30.0)

    def test_fractional_capital(self):
        assert calc_grid_capital_per_grid(100.0, 3) == pytest.approx(100.0 / 3)


# ── calc_drawdown_scenario ────────────────────────────────────────────

class TestCalcDrawdownScenario:
    def test_zero_range_low_returns_zeros(self):
        result = calc_drawdown_scenario(1000.0, 0.0, 100.0, 50.0)
        assert result == {"coinsHeld": 0.0, "valueAtCrash": 0.0, "drawdownUSDT": 0.0, "drawdownPct": 0.0}

    def test_coins_held_correct(self):
        result = calc_drawdown_scenario(1000.0, 100.0, 100.0, 50.0)
        assert result["coinsHeld"] == pytest.approx(10.0)

    def test_value_at_crash_correct(self):
        result = calc_drawdown_scenario(1000.0, 100.0, 100.0, 50.0)
        assert result["valueAtCrash"] == pytest.approx(500.0)

    def test_drawdown_pct_correct(self):
        result = calc_drawdown_scenario(1000.0, 100.0, 100.0, 50.0)
        assert result["drawdownPct"] == pytest.approx(0.5)


# ── calc_recommended_grid_count ───────────────────────────────────────

class TestCalcRecommendedGridCount:
    def test_zero_range_low_returns_ones(self):
        result = calc_recommended_grid_count(110.0, 0.0)
        assert result == {"recommended": 1, "min": 1, "max": 1}

    def test_recommended_at_least_one(self):
        result = calc_recommended_grid_count(110.0, 100.0)
        assert result["recommended"] >= 1

    def test_min_lte_recommended_lte_max(self):
        result = calc_recommended_grid_count(110.0, 100.0)
        assert result["min"] <= result["recommended"] <= result["max"]

    def test_wider_range_more_grids(self):
        narrow = calc_recommended_grid_count(105.0, 100.0)
        wide   = calc_recommended_grid_count(200.0, 100.0)
        assert wide["recommended"] >= narrow["recommended"]


# ── calc_range_from_atr ───────────────────────────────────────────────

class TestCalcRangeFromAtr:
    def test_neutral_range_centered_on_price(self):
        result = calc_range_from_atr(100.0, 2.0, multiplier=3.0, grid_type="Neutral")
        offset = (2.0 / 100.0) * 3.0
        assert result["rangeLow"]  == pytest.approx(100.0 * (1 - offset))
        assert result["rangeHigh"] == pytest.approx(100.0 * (1 + offset))

    def test_long_range_biased_below(self):
        neutral = calc_range_from_atr(100.0, 2.0, multiplier=3.0, grid_type="Neutral")
        long_   = calc_range_from_atr(100.0, 2.0, multiplier=3.0, grid_type="Long")
        assert long_["rangeLow"]  < neutral["rangeLow"]
        assert long_["rangeHigh"] < neutral["rangeHigh"]

    def test_short_range_biased_above(self):
        neutral = calc_range_from_atr(100.0, 2.0, multiplier=3.0, grid_type="Neutral")
        short_  = calc_range_from_atr(100.0, 2.0, multiplier=3.0, grid_type="Short")
        assert short_["rangeHigh"] > neutral["rangeHigh"]
        assert short_["rangeLow"]  > neutral["rangeLow"]

    def test_width_pct_positive(self):
        result = calc_range_from_atr(100.0, 2.0)
        assert result["rangeWidthPct"] > 0.0

    def test_result_has_required_keys(self):
        result = calc_range_from_atr(100.0, 2.0)
        assert {"rangeLow", "rangeHigh", "rangeWidthPct"} == result.keys()


# ── select_grid_direction (matrix-argmax) ─────────────────────────────

class TestSelectGridDirection:
    def test_long_column_leads_returns_long(self):
        scores = {"GRID_NEUTRAL": 70.0, "GRID_LONG": 79.0, "GRID_SHORT": 50.0}
        assert select_grid_direction(scores)["type"] == "Long"

    def test_short_column_leads_returns_short(self):
        scores = {"GRID_NEUTRAL": 70.0, "GRID_LONG": 50.0, "GRID_SHORT": 79.0}
        assert select_grid_direction(scores)["type"] == "Short"

    def test_neutral_column_leads_returns_neutral(self):
        scores = {"GRID_NEUTRAL": 85.0, "GRID_LONG": 70.0, "GRID_SHORT": 60.0}
        assert select_grid_direction(scores)["type"] == "Neutral"

    def test_directional_column_ignored(self):
        # A high DIRECTIONAL column must not pull the grid direction.
        scores = {"GRID_NEUTRAL": 80.0, "GRID_LONG": 60.0,
                  "GRID_SHORT": 60.0, "DIRECTIONAL": 99.0}
        assert select_grid_direction(scores)["type"] == "Neutral"

    def test_tie_favours_neutral(self):
        scores = {"GRID_NEUTRAL": 70.0, "GRID_LONG": 70.0, "GRID_SHORT": 70.0}
        assert select_grid_direction(scores)["type"] == "Neutral"

    def test_none_or_empty_returns_neutral(self):
        assert select_grid_direction(None)["type"] == "Neutral"
        assert select_grid_direction({})["type"] == "Neutral"

    def test_result_has_type_label_reason(self):
        result = select_grid_direction({"GRID_NEUTRAL": 60.0})
        assert {"type", "label", "reason"} <= result.keys()


# ── grid_headline_label ───────────────────────────────────────────────

class TestGridHeadlineLabel:
    @pytest.mark.parametrize("score,label", [
        (95.0, "STRONG SETUP"),
        (80.0, "STRONG SETUP"),
        (79.9, "GOOD SETUP"),
        (65.0, "GOOD SETUP"),
        (64.9, "DEVELOPING"),
        (50.0, "DEVELOPING"),
        (49.9, "AVOID"),
        (0.0, "AVOID"),
    ])
    def test_bands(self, score, label):
        assert grid_headline_label(score) == label


# ── select_grid_mode ──────────────────────────────────────────────────

class TestSelectGridMode:
    THRESHOLD = GRID_CONFIG["GEOMETRIC_THRESHOLD_PCT"]

    def test_geometric_when_wide(self):
        result = select_grid_mode(self.THRESHOLD)
        assert result["mode"] == "Geometric"

    def test_arithmetic_when_narrow(self):
        result = select_grid_mode(self.THRESHOLD - 1.0)
        assert result["mode"] == "Arithmetic"

    def test_result_has_mode_and_reason(self):
        result = select_grid_mode(10.0)
        assert {"mode", "reason"} <= result.keys()


# ── calc_grid_stop_loss / take_profit ─────────────────────────────────

class TestCalcGridSLTP:
    @pytest.mark.parametrize("profile,expected_buf", [
        ("stable",   GRID_CONFIG["SL_BUFFERS"]["stable"]),
        ("moderate", GRID_CONFIG["SL_BUFFERS"]["moderate"]),
        ("volatile", GRID_CONFIG["SL_BUFFERS"]["volatile"]),
    ])
    def test_stop_loss_profile(self, profile, expected_buf):
        sl = calc_grid_stop_loss(100.0, profile)
        assert sl == pytest.approx(100.0 * (1 - expected_buf))

    @pytest.mark.parametrize("profile,expected_buf", [
        ("stable",   GRID_CONFIG["TP_BUFFERS"]["stable"]),
        ("moderate", GRID_CONFIG["TP_BUFFERS"]["moderate"]),
        ("volatile", GRID_CONFIG["TP_BUFFERS"]["volatile"]),
    ])
    def test_take_profit_profile(self, profile, expected_buf):
        tp = calc_grid_take_profit(100.0, profile)
        assert tp == pytest.approx(100.0 * (1 + expected_buf))

    def test_sl_below_range_low(self):
        assert calc_grid_stop_loss(100.0) < 100.0

    def test_tp_above_range_high(self):
        assert calc_grid_take_profit(100.0) > 100.0


# ── assess_grid_viability ─────────────────────────────────────────────

class TestAssessGridViability:
    V = GRID_CONFIG["VIABILITY"]

    def test_viable_under_all_thresholds(self):
        result = assess_grid_viability(2.0, 18.0, 52.0, 5.0, "Neutral")
        assert result["viable"] is True

    def test_blocked_by_high_adx(self):
        result = assess_grid_viability(2.0, self.V["ADX_BLOCK"] + 1, 52.0, 5.0, "Neutral")
        assert result["viable"] is False
        assert "ADX" in result["reason"]

    def test_blocked_by_high_rsi(self):
        result = assess_grid_viability(2.0, 18.0, self.V["RSI_BLOCK"] + 1, 5.0, "Neutral")
        assert result["viable"] is False
        assert "RSI" in result["reason"]

    def test_blocked_by_low_bb_bw(self):
        result = assess_grid_viability(2.0, 18.0, 52.0, self.V["BB_MIN"] - 0.1, "Neutral")
        assert result["viable"] is False
        assert "BB" in result["reason"]

    def test_blocked_by_bearish_plus_adx(self):
        result = assess_grid_viability(2.0, self.V["BEARISH_ADX_BLOCK"] + 1, 52.0, 5.0, "Bearish")
        assert result["viable"] is False

    def test_warning_on_high_atr(self):
        result = assess_grid_viability(self.V["ATR_WARN"] + 1, 18.0, 52.0, 5.0, "Neutral")
        assert result["viable"] is True
        assert result["warning"] is not None

    def test_warning_on_neutral_structure(self):
        result = assess_grid_viability(2.0, 18.0, 52.0, 5.0, "Neutral")
        assert result["warning"] is not None
        assert "Neutral" in result["warning"]

    def test_no_warning_on_clean_bullish(self):
        result = assess_grid_viability(2.0, 18.0, 52.0, 5.0, "Bullish")
        assert result["viable"] is True
        assert result["warning"] is None


# ── estimate_grid_duration ────────────────────────────────────────────

class TestEstimateGridDuration:
    def test_zero_atr_returns_zero_days(self):
        result = estimate_grid_duration(10.0, 0.0)
        assert result["estDays"] == 0
        assert result["label"] == "—"

    def test_days_positive_on_valid_data(self):
        result = estimate_grid_duration(10.0, 2.0)
        assert result["estDays"] >= 1

    def test_clamped_to_max_30(self):
        result = estimate_grid_duration(100.0, 0.1)
        assert result["estDays"] <= 30

    @pytest.mark.parametrize("width,atr,expected_label", [
        (3.0, 2.0, "1-3 days"),   # 3/(2*1.5)=1 → 1-3 days
        (7.5, 1.0, "3-7 days"),   # 7.5/1.5=5 → 3-7 days
    ])
    def test_label_matches_duration(self, width, atr, expected_label):
        result = estimate_grid_duration(width, atr)
        assert result["label"] == expected_label


# ── get_ticker_grid_profile ───────────────────────────────────────────

class TestGetTickerGridProfile:
    @pytest.mark.parametrize("ticker,profile", [
        ("BTC/USDT", "stable"),
        ("ETH/USDT", "stable"),
        ("SOL/USDT", "moderate"),
        ("SUI/USDT", "volatile"),
        ("HYPE/USDT", "volatile"),
        ("TRX/USDT", "stable"),
    ])
    def test_known_tickers(self, ticker, profile):
        result = get_ticker_grid_profile(ticker)
        assert result["profile"] == profile

    def test_unknown_ticker_returns_moderate(self):
        result = get_ticker_grid_profile("UNKNOWN/USDT")
        assert result["profile"] == "moderate"

    def test_result_has_required_keys(self):
        result = get_ticker_grid_profile("BTC/USDT")
        assert {"profile", "rangeMultiplier", "maxGrids", "targetNetPct", "minNetPct"} <= result.keys()


# ── calc_grid_score ───────────────────────────────────────────────────

class TestCalcGridScore:
    def test_none_metrics_returns_avoid(self):
        result = calc_grid_score(None)
        assert result["score"] == 0.0
        assert result["label"] == "AVOID"
        assert result["components"] == []

    def test_empty_dict_returns_avoid(self):
        result = calc_grid_score({})
        assert result["label"] == "AVOID"

    def test_score_with_valid_metrics(self, mock_metrics):
        result = calc_grid_score(mock_metrics)
        assert 0.0 <= result["score"] <= 10.0
        assert result["label"] in ("STRONG SETUP", "GOOD SETUP", "DEVELOPING", "AVOID")
        assert len(result["components"]) > 0

    def test_low_adx_gives_high_adx_score(self, mock_metrics):
        mock_metrics["adx"] = {"adx": 10.0, "plusDI": 15.0, "minusDI": 10.0}
        result = calc_grid_score(mock_metrics)
        adx_comp = next(c for c in result["components"] if c["label"] == "ADX Trend")
        assert adx_comp["score"] == pytest.approx(3.0)

    def test_high_adx_gives_zero_adx_score(self, mock_metrics):
        mock_metrics["adx"] = {"adx": 30.0, "plusDI": 35.0, "minusDI": 20.0}
        result = calc_grid_score(mock_metrics)
        adx_comp = next(c for c in result["components"] if c["label"] == "ADX Trend")
        assert adx_comp["score"] == pytest.approx(0.0)

    def test_squeeze_bonus_applied(self, mock_metrics):
        score_no_sq = calc_grid_score(mock_metrics)["score"]
        mock_metrics["squeeze"] = {
            "squeeze": True, "bbTight": True, "dcTight": True,
            "bbBw": 3.0, "dcAtrRatio": 0.5,
        }
        score_sq = calc_grid_score(mock_metrics)["score"]
        assert score_sq > score_no_sq

    def test_score_capped_at_10(self, mock_metrics):
        mock_metrics["adx"] = {"adx": 5.0}
        mock_metrics["bb"] = {"label": "squeeze"}
        mock_metrics["bbBw"] = 3.0
        mock_metrics["rsi"] = 50.0
        mock_metrics["funding"] = 0.0
        mock_metrics["squeeze"] = {"squeeze": True, "bbBw": 3.0, "dcAtrRatio": 0.4}
        result = calc_grid_score(mock_metrics)
        assert result["score"] <= 10.0

    def test_recs_is_a_list(self, mock_metrics):
        result = calc_grid_score(mock_metrics)
        assert isinstance(result["recs"], list)
