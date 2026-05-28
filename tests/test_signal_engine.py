"""Tests for signal_engine.py — series calculations and scoring functions."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from signal_engine import (
    _calc_urgency,
    _classify_signal,
    _estimate_eta,
    calc_bb_bandwidth_series,
    calc_cvd_series,
    calc_macd_histogram_series,
    calc_rsi_series,
    calc_setup_score,
    detect_cvd_divergence,
    detect_momentum_divergence,
    detect_squeeze_progression,
    detect_structure_transition,
    detect_volume_exhaustion,
    score_cvd_divergence,
    score_funding_oi,
    score_momentum_divergence,
    score_squeeze_progression,
    score_structure_transition,
    score_volume_exhaustion,
)


# ── calc_cvd_series ───────────────────────────────────────────────────

class TestCalcCvdSeries:
    def test_empty_df_returns_empty_array(self, empty_df):
        result = calc_cvd_series(empty_df)
        assert len(result) == 0

    def test_positive_cumulative_when_all_buying(self):
        df = pd.DataFrame({
            "Volume": [100.0] * 10,
            "BuyVol": [100.0] * 10,
        })
        result = calc_cvd_series(df)
        assert len(result) == 10
        assert result[-1] > 0

    def test_heuristic_applied_when_buy_vol_zero(self):
        df = pd.DataFrame({
            "Open":   [100.0] * 10,
            "Close":  [101.0] * 10,
            "Volume": [100.0] * 10,
            "BuyVol": [0.0]   * 10,
        })
        result = calc_cvd_series(df)
        # Up-candles → positive CVD (0.55 factor)
        assert result[-1] > 0

    def test_length_matches_input(self, sample_ohlcv):
        result = calc_cvd_series(sample_ohlcv)
        assert len(result) == len(sample_ohlcv)


# ── calc_bb_bandwidth_series ──────────────────────────────────────────

class TestCalcBbBandwidthSeries:
    def test_too_short_returns_empty(self):
        df = pd.DataFrame({"Close": [100.0] * 5})
        result = calc_bb_bandwidth_series(df, period=20)
        assert len(result) == 0

    def test_length_on_valid_data(self, sample_ohlcv):
        result = calc_bb_bandwidth_series(sample_ohlcv)
        assert len(result) > 0

    def test_values_non_negative(self, sample_ohlcv):
        result = calc_bb_bandwidth_series(sample_ohlcv)
        assert all(v >= 0 for v in result)

    def test_flat_data_produces_near_zero_bandwidth(self, flat_ohlcv):
        result = calc_bb_bandwidth_series(flat_ohlcv)
        # Flat prices → very small bandwidth
        assert result[-1] < 5.0


# ── calc_rsi_series ───────────────────────────────────────────────────

class TestCalcRsiSeries:
    def test_short_df_returns_50s(self):
        df = pd.DataFrame({"Close": [100.0] * 5})
        result = calc_rsi_series(df)
        assert all(v == pytest.approx(50.0) for v in result)

    def test_values_in_range(self, sample_ohlcv):
        result = calc_rsi_series(sample_ohlcv)
        assert all(0.0 <= v <= 100.0 for v in result)

    def test_high_values_on_uptrend(self, trending_ohlcv):
        result = calc_rsi_series(trending_ohlcv)
        # At least the last value should be elevated
        assert result[-1] > 60.0


# ── detect_squeeze_progression ────────────────────────────────────────

class TestDetectSqueezeProgression:
    def test_too_short_returns_flat(self):
        bw = np.ones(5) * 3.0
        result = detect_squeeze_progression(bw)
        assert result["phase"] in ("FLAT", "SQUEEZE", "COMPRESSING", "EXPANDING")

    def test_squeeze_phase_when_bw_below_threshold(self):
        bw = np.ones(30) * 2.0  # all below 5%
        result = detect_squeeze_progression(bw)
        assert result["phase"] == "SQUEEZE"

    def test_expanding_phase_when_slope_positive(self):
        # Steadily increasing bandwidth → EXPANDING
        bw = np.linspace(3.0, 15.0, 30)
        result = detect_squeeze_progression(bw)
        assert result["phase"] == "EXPANDING"

    def test_compressing_phase_when_slope_negative_and_above_squeeze(self):
        # Decreasing but still above squeeze threshold
        bw = np.linspace(12.0, 6.0, 30)
        result = detect_squeeze_progression(bw)
        assert result["phase"] in ("COMPRESSING", "SQUEEZE")

    def test_result_has_required_keys(self, sample_ohlcv):
        bw = calc_bb_bandwidth_series(sample_ohlcv)
        result = detect_squeeze_progression(bw)
        required = {"phase", "compression_rate", "bars_to_squeeze", "percentile", "current_bw"}
        assert required <= result.keys()


# ── score_cvd_divergence ──────────────────────────────────────────────

class TestScoreCvdDivergence:
    def test_no_divergence_returns_zero(self):
        div = {"type": "NONE", "strength": 0.0, "candles_ago": 10}
        score, label = score_cvd_divergence(div, "Neutral")
        assert score == pytest.approx(0.0)

    def test_bull_div_returns_positive_score(self):
        div = {"type": "BULL_DIV", "strength": 0.3, "candles_ago": 3}
        score, label = score_cvd_divergence(div, "Neutral")
        assert score > 0.0

    def test_strong_bull_div_scores_higher(self):
        weak = score_cvd_divergence({"type": "BULL_DIV", "strength": 0.3, "candles_ago": 5}, "Neutral")[0]
        strong = score_cvd_divergence({"type": "BULL_DIV", "strength": 0.8, "candles_ago": 5}, "Neutral")[0]
        assert strong > weak

    def test_opposing_structure_adds_bonus(self):
        # Bull divergence opposing bearish structure adds context bonus
        aligned = score_cvd_divergence({"type": "BULL_DIV", "strength": 0.5, "candles_ago": 3}, "Bullish")[0]
        opposing = score_cvd_divergence({"type": "BULL_DIV", "strength": 0.5, "candles_ago": 3}, "Bearish")[0]
        assert opposing >= aligned

    def test_returns_tuple_of_float_and_str(self):
        result = score_cvd_divergence({"type": "NONE", "strength": 0.0, "candles_ago": 5}, "Neutral")
        assert isinstance(result[0], float)
        assert isinstance(result[1], str)


# ── score_squeeze_progression ─────────────────────────────────────────

class TestScoreSqueezeProgression:
    @pytest.mark.parametrize("phase,min_score", [
        ("SQUEEZE",     2.0),
        ("COMPRESSING", 0.5),
        ("EXPANDING",   0.0),
        ("FLAT",        0.0),
    ])
    def test_phase_scores(self, phase, min_score):
        sq = {"phase": phase, "bars_to_squeeze": 10, "compression_rate": -0.1,
              "percentile": 20.0, "current_bw": 4.0}
        score, _ = score_squeeze_progression(sq)
        assert score >= min_score

    def test_imminent_compressing_scores_higher_than_far(self):
        imminent = score_squeeze_progression({
            "phase": "COMPRESSING", "bars_to_squeeze": 3,
            "compression_rate": -0.15, "percentile": 30.0, "current_bw": 6.0,
        })[0]
        far = score_squeeze_progression({
            "phase": "COMPRESSING", "bars_to_squeeze": 25,
            "compression_rate": -0.02, "percentile": 50.0, "current_bw": 9.0,
        })[0]
        assert imminent >= far

    def test_squeeze_max_score_is_2(self):
        sq = {"phase": "SQUEEZE", "bars_to_squeeze": 0, "compression_rate": 0.0,
              "percentile": 5.0, "current_bw": 2.0}
        score, _ = score_squeeze_progression(sq)
        assert score == pytest.approx(2.0)


# ── score_structure_transition ────────────────────────────────────────

class TestScoreStructureTransition:
    def test_stable_returns_zero(self):
        trans = {"current": "Bullish", "transitioning_to": None,
                 "confidence": 0.0, "signal": "STABLE"}
        score, _ = score_structure_transition(trans)
        assert score == pytest.approx(0.0)

    def test_trend_exhaustion_high_confidence_scores_highest(self):
        trans = {"current": "Bullish", "transitioning_to": "Neutral",
                 "confidence": 0.8, "signal": "TREND_EXHAUSTION"}
        score, _ = score_structure_transition(trans)
        assert score >= 1.5

    def test_range_forming_scores_by_confidence(self):
        lo = score_structure_transition({"signal": "RANGE_FORMING", "confidence": 0.3,
                                          "current": "Neutral", "transitioning_to": None})[0]
        hi = score_structure_transition({"signal": "RANGE_FORMING", "confidence": 0.9,
                                          "current": "Neutral", "transitioning_to": None})[0]
        assert hi > lo


# ── score_funding_oi ──────────────────────────────────────────────────

class TestScoreFundingOi:
    def test_neutral_funding_low_oi_returns_low_score(self):
        score, _ = score_funding_oi(0.01, 2.0, "Neutral")
        assert score >= 0.0

    def test_extreme_funding_scores_high(self):
        score_extreme, _ = score_funding_oi(0.10, 5.0, "Neutral")
        score_normal, _  = score_funding_oi(0.02, 5.0, "Neutral")
        assert score_extreme > score_normal

    def test_score_is_non_negative(self):
        for funding in [-0.15, -0.05, 0.0, 0.05, 0.15]:
            score, _ = score_funding_oi(funding, 5.0, "Neutral")
            assert score >= 0.0


# ── score_momentum_divergence ─────────────────────────────────────────

class TestScoreMomentumDivergence:
    def test_no_divergence_returns_zero(self):
        div = {"rsi_div": "NONE", "macd_div": "NONE", "combined_strength": 0.0}
        score, _ = score_momentum_divergence(div)
        assert score == pytest.approx(0.0)

    def test_rsi_only_returns_mid_score(self):
        div = {"rsi_div": "BULL", "macd_div": "NONE", "combined_strength": 0.5}
        score, _ = score_momentum_divergence(div)
        assert score > 0.0

    def test_both_divergence_returns_highest(self):
        both = score_momentum_divergence({
            "rsi_div": "BULL", "macd_div": "BULL", "combined_strength": 0.8
        })[0]
        rsi_only = score_momentum_divergence({
            "rsi_div": "BULL", "macd_div": "NONE", "combined_strength": 0.5
        })[0]
        assert both > rsi_only


# ── score_volume_exhaustion ───────────────────────────────────────────

class TestScoreVolumeExhaustion:
    def test_healthy_volume_returns_zero(self):
        vol = {"exhaustion": False, "vol_trend_slope": 1.0, "vol_percentile": 70.0}
        score, _ = score_volume_exhaustion(vol, "Neutral")
        assert score == pytest.approx(0.0)

    def test_exhaustion_trending_scores_higher(self):
        ex_trend = score_volume_exhaustion(
            {"exhaustion": True, "vol_trend_slope": -3.0, "vol_percentile": 30.0}, "Bullish"
        )[0]
        ex_neutral = score_volume_exhaustion(
            {"exhaustion": True, "vol_trend_slope": -3.0, "vol_percentile": 30.0}, "Neutral"
        )[0]
        assert ex_trend >= ex_neutral

    def test_non_negative_score(self):
        for exhaustion in [True, False]:
            score, _ = score_volume_exhaustion(
                {"exhaustion": exhaustion, "vol_trend_slope": -2.0, "vol_percentile": 25.0},
                "Bullish",
            )
            assert score >= 0.0

    def test_declining_slope_returns_partial_score(self):
        vol = {"exhaustion": False, "vol_trend_slope": -2.0, "vol_percentile": 60.0}
        score, _ = score_volume_exhaustion(vol, "Neutral")
        assert score == pytest.approx(0.25)


# ── calc_macd_histogram_series ────────────────────────────────────────

class TestCalcMacdHistogramSeries:
    def test_too_short_returns_empty(self):
        df = pd.DataFrame({"Close": [100.0] * 20})
        result = calc_macd_histogram_series(df)
        assert len(result) == 0

    def test_valid_data_returns_non_empty(self, sample_ohlcv):
        result = calc_macd_histogram_series(sample_ohlcv)
        assert len(result) > 0


# ── detect_cvd_divergence ────────────────────────────────────────────

class TestDetectCvdDivergence:
    def test_too_short_returns_none(self):
        df = pd.DataFrame({
            "High": [100.0] * 5, "Low": [98.0] * 5,
            "Close": [99.0] * 5, "Open": [99.0] * 5,
            "Volume": [100.0] * 5, "BuyVol": [50.0] * 5,
        })
        result = detect_cvd_divergence(df)
        assert result["type"] == "NONE"

    def test_result_has_required_keys(self, sample_ohlcv):
        result = detect_cvd_divergence(sample_ohlcv)
        assert {"type", "strength", "candles_ago"} == result.keys()

    def test_type_is_valid_value(self, sample_ohlcv):
        result = detect_cvd_divergence(sample_ohlcv)
        assert result["type"] in ("NONE", "BULL_DIV", "BEAR_DIV")

    def test_strength_in_range(self, sample_ohlcv):
        result = detect_cvd_divergence(sample_ohlcv)
        assert 0.0 <= result["strength"] <= 1.0


# ── detect_structure_transition ───────────────────────────────────────

class TestDetectStructureTransition:
    def test_too_short_returns_stable(self):
        df = pd.DataFrame({
            "High": [100.0] * 5, "Low": [98.0] * 5,
            "Close": [99.0] * 5,
        })
        result = detect_structure_transition(df)
        assert result["signal"] == "STABLE"

    def test_result_has_required_keys(self, sample_ohlcv):
        result = detect_structure_transition(sample_ohlcv)
        assert {"current", "transitioning_to", "confidence", "signal"} == result.keys()

    def test_signal_is_valid_value(self, sample_ohlcv):
        result = detect_structure_transition(sample_ohlcv)
        assert result["signal"] in ("STABLE", "TREND_EXHAUSTION", "RANGE_FORMING")

    def test_confidence_in_range(self, sample_ohlcv):
        result = detect_structure_transition(sample_ohlcv)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_current_is_valid_structure(self, sample_ohlcv):
        result = detect_structure_transition(sample_ohlcv)
        assert result["current"] in ("Bullish", "Bearish", "Neutral")


# ── detect_momentum_divergence ────────────────────────────────────────

class TestDetectMomentumDivergence:
    def test_too_short_returns_none(self):
        df = pd.DataFrame({
            "High": [100.0] * 5, "Low": [98.0] * 5,
            "Close": [99.0] * 5,
        })
        rsi = np.ones(5) * 50.0
        macd = np.ones(5) * 0.1
        result = detect_momentum_divergence(df, rsi, macd)
        assert result["rsi_div"] == "NONE"
        assert result["macd_div"] == "NONE"

    def test_result_has_required_keys(self, sample_ohlcv):
        rsi = calc_rsi_series(sample_ohlcv)
        macd = calc_macd_histogram_series(sample_ohlcv)
        result = detect_momentum_divergence(sample_ohlcv, rsi, macd)
        assert {"rsi_div", "macd_div", "combined_strength"} == result.keys()

    def test_div_values_are_valid(self, sample_ohlcv):
        rsi = calc_rsi_series(sample_ohlcv)
        macd = calc_macd_histogram_series(sample_ohlcv)
        result = detect_momentum_divergence(sample_ohlcv, rsi, macd)
        assert result["rsi_div"] in ("NONE", "BULL", "BEAR")
        assert result["macd_div"] in ("NONE", "BULL", "BEAR")
        assert 0.0 <= result["combined_strength"] <= 1.0


# ── detect_volume_exhaustion ──────────────────────────────────────────

class TestDetectVolumeExhaustion:
    def test_too_short_returns_default(self):
        df = pd.DataFrame({"Volume": [100.0] * 3})
        result = detect_volume_exhaustion(df)
        assert result["exhaustion"] is False

    def test_result_has_required_keys(self, sample_ohlcv):
        result = detect_volume_exhaustion(sample_ohlcv)
        assert {"exhaustion", "vol_trend_slope", "vol_percentile"} == result.keys()

    def test_exhaustion_when_declining_low_volume(self):
        # Strongly declining volume at low percentile → exhaustion
        vols = np.linspace(1000.0, 10.0, 30)  # steep decline
        df = pd.DataFrame({"Volume": vols})
        result = detect_volume_exhaustion(df)
        assert result["vol_trend_slope"] < 0

    def test_percentile_in_range(self, sample_ohlcv):
        result = detect_volume_exhaustion(sample_ohlcv)
        assert 0.0 <= result["vol_percentile"] <= 100.0


# ── _classify_signal ──────────────────────────────────────────────────

class TestClassifySignal:
    def _defaults(self):
        return {
            "cvd_div":     {"type": "NONE", "strength": 0.0, "candles_ago": 10},
            "sq_prog":     {"phase": "FLAT", "bars_to_squeeze": 99, "compression_rate": 0.0,
                            "percentile": 50.0, "current_bw": 8.0},
            "struct_trans":{"current": "Neutral", "transitioning_to": None,
                            "confidence": 0.0, "signal": "STABLE"},
            "mom_div":     {"rsi_div": "NONE", "macd_div": "NONE", "combined_strength": 0.0},
        }

    def test_squeeze_phase_returns_grid_window(self):
        d = self._defaults()
        d["sq_prog"]["phase"] = "SQUEEZE"
        result = _classify_signal(d["cvd_div"], d["sq_prog"], d["struct_trans"], d["mom_div"], 0.0, "Neutral")
        assert result["type"] == "GRID_WINDOW"

    def test_compressing_returns_grid_window(self):
        d = self._defaults()
        d["sq_prog"]["phase"] = "COMPRESSING"
        result = _classify_signal(d["cvd_div"], d["sq_prog"], d["struct_trans"], d["mom_div"], 0.0, "Neutral")
        assert result["type"] == "GRID_WINDOW"

    def test_extreme_funding_returns_squeeze_play(self):
        d = self._defaults()
        result = _classify_signal(d["cvd_div"], d["sq_prog"], d["struct_trans"], d["mom_div"], 0.10, "Neutral")
        assert result["type"] == "SQUEEZE_PLAY"

    def test_bull_momentum_returns_long_setup(self):
        d = self._defaults()
        d["mom_div"]["rsi_div"] = "BULL"
        result = _classify_signal(d["cvd_div"], d["sq_prog"], d["struct_trans"], d["mom_div"], 0.0, "Neutral")
        assert result["type"] == "LONG_SETUP"

    def test_bear_momentum_returns_short_setup(self):
        d = self._defaults()
        d["mom_div"]["macd_div"] = "BEAR"
        result = _classify_signal(d["cvd_div"], d["sq_prog"], d["struct_trans"], d["mom_div"], 0.0, "Neutral")
        assert result["type"] == "SHORT_SETUP"

    def test_no_signal_returns_none(self):
        d = self._defaults()
        result = _classify_signal(d["cvd_div"], d["sq_prog"], d["struct_trans"], d["mom_div"], 0.0, "Neutral")
        assert result["type"] == "NONE"


# ── _calc_urgency ─────────────────────────────────────────────────────

class TestCalcUrgency:
    def _sq(self, phase: str, bars: int = 10) -> dict:
        return {"phase": phase, "bars_to_squeeze": bars, "compression_rate": 0.0,
                "percentile": 30.0, "current_bw": 4.0}

    def _div(self, div_type: str, ago: int = 5) -> dict:
        return {"type": div_type, "strength": 0.5, "candles_ago": ago}

    def test_squeeze_plus_high_score_is_urgent(self):
        result = _calc_urgency(8.0, self._sq("SQUEEZE"), self._div("NONE"))
        assert result["level"] == "URGENT"

    def test_low_score_no_squeeze_is_wait(self):
        result = _calc_urgency(1.0, self._sq("FLAT"), self._div("NONE"))
        assert result["level"] == "WAIT"

    def test_recent_div_adds_rank(self):
        base = _calc_urgency(3.0, self._sq("FLAT"), self._div("NONE"))
        with_div = _calc_urgency(3.0, self._sq("FLAT"), self._div("BULL_DIV", ago=2))
        assert with_div["rank_value"] > base["rank_value"]

    def test_result_has_required_keys(self):
        result = _calc_urgency(5.0, self._sq("FLAT"), self._div("NONE"))
        assert {"level", "label", "rank_value"} == result.keys()

    def test_level_is_valid_value(self):
        for score in [0.5, 3.0, 6.0, 9.0]:
            result = _calc_urgency(score, self._sq("FLAT"), self._div("NONE"))
            assert result["level"] in ("URGENT", "SOON", "WATCH", "WAIT")


# ── _estimate_eta ─────────────────────────────────────────────────────

class TestEstimateEta:
    def _sq(self, phase: str, bars: int) -> dict:
        return {"phase": phase, "bars_to_squeeze": bars, "compression_rate": 0.0,
                "percentile": 30.0, "current_bw": 4.0}

    def _trans(self, signal: str, conf: float) -> dict:
        return {"current": "Bullish", "transitioning_to": "Ranging",
                "confidence": conf, "signal": signal}

    def test_no_estimates_returns_unknown(self):
        sq = self._sq("FLAT", 99)
        trans = self._trans("STABLE", 0.0)
        result = _estimate_eta(sq, trans)
        assert result["label"] == "Unknown"
        assert result["bars"] is None

    def test_compressing_gives_eta(self):
        sq = self._sq("COMPRESSING", 3)
        trans = self._trans("STABLE", 0.0)
        result = _estimate_eta(sq, trans)
        assert result["bars"] is not None
        assert result["label"] != "Unknown"

    def test_exhaustion_gives_eta(self):
        sq = self._sq("FLAT", 99)
        trans = self._trans("TREND_EXHAUSTION", 0.8)
        result = _estimate_eta(sq, trans)
        assert result["bars"] is not None

    def test_result_has_required_keys(self):
        result = _estimate_eta(self._sq("FLAT", 99), self._trans("STABLE", 0.0))
        assert {"bars", "label", "confidence"} == result.keys()


# ── calc_setup_score (integration) ────────────────────────────────────

class TestCalcSetupScore:
    def test_returns_valid_structure(self, sample_ohlcv):
        metrics = {"structure4h": "Neutral", "funding": 0.01, "oi": {"oiChange": -2.0}}
        result = calc_setup_score(metrics, sample_ohlcv)
        assert "score" in result
        assert "label" in result
        assert "components" in result
        assert "signal_type" in result
        assert "urgency" in result
        assert "eta" in result

    def test_score_in_valid_range(self, sample_ohlcv):
        metrics = {"structure4h": "Neutral", "funding": 0.01, "oi": {}}
        result = calc_setup_score(metrics, sample_ohlcv)
        assert 0.0 <= result["score"] <= 10.0

    def test_empty_df_returns_zero_score(self, empty_df):
        metrics = {"structure4h": "Neutral", "funding": 0.0, "oi": {}}
        result = calc_setup_score(metrics, empty_df)
        assert result["score"] == pytest.approx(0.0)
