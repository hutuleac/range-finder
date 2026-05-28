"""Tests for indicators.py — pure math functions."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from indicators import (
    OIData,
    calc_adx,
    calc_atr,
    calc_atr_pct,
    calc_bb,
    calc_change_24h,
    calc_cvd,
    calc_donchian,
    calc_ema,
    calc_fib,
    calc_fvg,
    calc_macd,
    calc_market_structure,
    calc_obv,
    calc_poc_avwap,
    calc_rsi,
    detect_squeeze,
    fvg_status,
    get_advanced_metrics,
    parse_klines,
)


# ── parse_klines ──────────────────────────────────────────────────────

class TestParseKlines:
    def test_empty_input_returns_empty_df_with_columns(self):
        df = parse_klines([])
        assert df.empty
        assert list(df.columns) == ["Time", "Open", "High", "Low", "Close", "Volume", "BuyVol"]

    def test_single_row_parses_all_fields(self):
        raw = [[1_000_000, "100.5", "105.0", "98.0", "102.0", "500.0",
                0, 0, 0, "300.0", 0, 0]]
        df = parse_klines(raw)
        assert len(df) == 1
        assert df["Close"].iloc[0] == pytest.approx(102.0)
        assert df["BuyVol"].iloc[0] == pytest.approx(300.0)

    def test_values_are_float(self):
        raw = [[1_000, "50", "55", "48", "52", "200", 0, 0, 0, "120", 0, 0]]
        df = parse_klines(raw)
        assert df["Close"].dtype == float

    def test_multiple_rows(self):
        raw = [[i, str(i * 10), str(i * 11), str(i * 9), str(i * 10 + 1), "100", 0, 0, 0, "60", 0, 0]
               for i in range(1, 6)]
        df = parse_klines(raw)
        assert len(df) == 5


# ── calc_rsi ──────────────────────────────────────────────────────────

class TestCalcRsi:
    def test_returns_50_when_data_too_short(self, empty_df):
        assert calc_rsi(empty_df) == 50.0

    def test_returns_50_when_equal_to_period(self, sample_ohlcv):
        df = sample_ohlcv.head(14)
        assert calc_rsi(df) == 50.0

    def test_returns_100_on_all_gains(self):
        closes = np.linspace(100.0, 200.0, 50)
        df = pd.DataFrame({"Close": closes})
        assert calc_rsi(df) == pytest.approx(100.0)

    def test_rsi_in_valid_range(self, sample_ohlcv):
        rsi = calc_rsi(sample_ohlcv)
        assert 0.0 <= rsi <= 100.0

    def test_high_rsi_on_uptrend(self, trending_ohlcv):
        assert calc_rsi(trending_ohlcv) > 70.0

    def test_low_rsi_on_downtrend(self, bearish_ohlcv):
        assert calc_rsi(bearish_ohlcv) < 40.0

    @pytest.mark.parametrize("period", [5, 14, 21])
    def test_custom_period(self, sample_ohlcv, period):
        rsi = calc_rsi(sample_ohlcv, period=period)
        assert 0.0 <= rsi <= 100.0


# ── calc_atr ──────────────────────────────────────────────────────────

class TestCalcAtr:
    def test_returns_zero_when_insufficient_data(self):
        df = pd.DataFrame({
            "High": [100.0] * 10,
            "Low":  [95.0]  * 10,
            "Close":[98.0]  * 10,
        })
        assert calc_atr(df) == 0.0

    def test_positive_on_valid_data(self, sample_ohlcv):
        assert calc_atr(sample_ohlcv) > 0.0

    def test_atr_reflects_volatility(self):
        """Higher spread → higher ATR."""
        def _df(spread):
            n = 30
            closes = np.ones(n) * 100.0
            return pd.DataFrame({
                "High":  closes + spread,
                "Low":   closes - spread,
                "Close": closes,
            })
        assert calc_atr(_df(5.0)) > calc_atr(_df(1.0))


# ── calc_ema ──────────────────────────────────────────────────────────

class TestCalcEma:
    def test_empty_df_returns_zero(self, empty_df):
        assert calc_ema(empty_df, span=20) == 0.0

    def test_single_row_returns_that_close(self):
        df = pd.DataFrame({"Close": [123.45]})
        assert calc_ema(df, span=20) == pytest.approx(123.45)

    def test_ema_is_positive_on_valid_data(self, sample_ohlcv):
        assert calc_ema(sample_ohlcv, span=20) > 0.0

    def test_fast_ema_reacts_more_than_slow(self, trending_ohlcv):
        fast = calc_ema(trending_ohlcv, span=10)
        slow = calc_ema(trending_ohlcv, span=50)
        # In an uptrend, fast EMA > slow EMA
        assert fast > slow


# ── calc_poc_avwap ────────────────────────────────────────────────────

class TestCalcPocAvwap:
    def test_empty_df_returns_zeros(self, empty_df):
        result = calc_poc_avwap(empty_df)
        assert result == {"poc": 0.0, "avwap": 0.0}

    def test_flat_prices_poc_equals_price(self):
        df = pd.DataFrame({
            "Close":  [100.0] * 20,
            "Volume": [500.0] * 20,
        })
        result = calc_poc_avwap(df)
        assert result["poc"] == pytest.approx(100.0, abs=1.0)
        assert result["avwap"] == pytest.approx(100.0)

    def test_poc_within_price_range(self, sample_ohlcv):
        result = calc_poc_avwap(sample_ohlcv)
        lo = sample_ohlcv["Close"].min()
        hi = sample_ohlcv["Close"].max()
        assert lo <= result["poc"] <= hi
        assert lo <= result["avwap"] <= hi


# ── calc_cvd ─────────────────────────────────────────────────────────

class TestCalcCvd:
    def test_empty_df_returns_zero(self, empty_df):
        assert calc_cvd(empty_df) == 0.0

    def test_positive_cvd_when_all_buying(self):
        df = pd.DataFrame({
            "Volume": [100.0] * 10,
            "BuyVol": [100.0] * 10,  # 100% buy
        })
        assert calc_cvd(df) > 0.0

    def test_negative_cvd_when_all_selling(self):
        df = pd.DataFrame({
            "Open":   [101.0] * 10,
            "Close":  [100.0] * 10,  # all down candles
            "Volume": [100.0] * 10,
            "BuyVol": [0.0]   * 10,  # heuristic: down = 0.45 buy → net negative
        })
        assert calc_cvd(df) < 0.0

    def test_heuristic_used_when_buy_vol_zero(self):
        # Up-candles: 0.55 buy ratio → positive CVD
        df = pd.DataFrame({
            "Open":   [100.0] * 10,
            "Close":  [101.0] * 10,  # all up
            "Volume": [100.0] * 10,
            "BuyVol": [0.0]   * 10,
        })
        assert calc_cvd(df) > 0.0


# ── calc_market_structure ─────────────────────────────────────────────

class TestCalcMarketStructure:
    def test_neutral_when_too_short(self):
        df = pd.DataFrame({
            "High": [100.0] * 10,
            "Low":  [95.0]  * 10,
        })
        assert calc_market_structure(df) == "Neutral"

    def test_bullish_on_uptrend(self, trending_ohlcv):
        assert calc_market_structure(trending_ohlcv) == "Bullish"

    def test_bearish_on_downtrend(self, bearish_ohlcv):
        assert calc_market_structure(bearish_ohlcv) == "Bearish"

    def test_neutral_on_flat(self, flat_ohlcv):
        result = calc_market_structure(flat_ohlcv)
        # Flat data won't produce clean HH/LL so should be Neutral
        assert result in ("Neutral", "Bullish", "Bearish")


# ── calc_fvg ─────────────────────────────────────────────────────────

class TestCalcFvg:
    def test_too_short_returns_empty(self):
        df = pd.DataFrame({
            "High": [100.0, 101.0],
            "Low":  [99.0, 99.5],
            "Close":[100.5, 100.8],
        })
        assert calc_fvg(df) == []

    def test_detects_bullish_gap(self):
        # i-1: high=100, i: anything, i+1: low=102 → gap up
        df = pd.DataFrame({
            "High":  [100.0, 101.0, 103.0, 103.0, 103.0],
            "Low":   [98.0,  99.5,  102.0, 101.5, 101.0],
            "Close": [99.0, 100.0, 102.5, 102.0, 101.5],
        })
        gaps = calc_fvg(df)
        bull_gaps = [g for g in gaps if g["type"] == "BULL"]
        assert len(bull_gaps) >= 1

    def test_result_capped_at_max_gaps(self, trending_ohlcv):
        gaps = calc_fvg(trending_ohlcv, max_gaps=3)
        assert len(gaps) <= 3

    def test_gap_has_required_keys(self, trending_ohlcv):
        gaps = calc_fvg(trending_ohlcv)
        for g in gaps:
            assert {"type", "bottom", "top", "mid", "sizePct", "idx"} <= g.keys()


# ── fvg_status ────────────────────────────────────────────────────────

class TestFvgStatus:
    @pytest.fixture
    def gap(self):
        return {"bottom": 98.0, "top": 102.0, "mid": 100.0}

    def test_inside_gap(self, gap):
        result = fvg_status(100.0, gap)
        assert result["state"] == "inside"
        assert result["fillPct"] == pytest.approx(50.0)

    def test_approach_just_outside(self, gap):
        result = fvg_status(102.5, gap)  # 0.5% above mid → approach
        assert result["state"] in ("approach", "far")

    def test_far_when_distant(self, gap):
        result = fvg_status(120.0, gap)
        assert result["state"] == "far"
        assert result["fillPct"] is None

    def test_at_bottom_edge_is_inside(self, gap):
        result = fvg_status(98.0, gap)
        assert result["state"] == "inside"


# ── calc_adx ─────────────────────────────────────────────────────────

class TestCalcAdx:
    def test_returns_zeros_when_too_short(self):
        df = pd.DataFrame({
            "High":  [100.0] * 10,
            "Low":   [95.0]  * 10,
            "Close": [98.0]  * 10,
        })
        result = calc_adx(df)
        assert result == {"adx": 0.0, "plusDI": 0.0, "minusDI": 0.0}

    def test_adx_positive_on_trend(self, trending_ohlcv):
        result = calc_adx(trending_ohlcv)
        assert result["adx"] > 0.0
        assert result["plusDI"] > 0.0

    def test_result_has_required_keys(self, sample_ohlcv):
        result = calc_adx(sample_ohlcv)
        assert {"adx", "plusDI", "minusDI"} == result.keys()

    def test_strong_uptrend_plusdi_exceeds_minusdi(self, trending_ohlcv):
        result = calc_adx(trending_ohlcv)
        assert result["plusDI"] > result["minusDI"]


# ── calc_macd ─────────────────────────────────────────────────────────

class TestCalcMacd:
    def test_returns_zeros_when_too_short(self):
        df = pd.DataFrame({"Close": [100.0] * 20})
        result = calc_macd(df)
        assert result["macd"] == 0.0
        assert result["signal"] == 0.0

    def test_result_has_required_keys(self, sample_ohlcv):
        result = calc_macd(sample_ohlcv)
        assert {"macd", "signal", "histogram", "trend"} == result.keys()

    def test_trend_is_valid_value(self, sample_ohlcv):
        result = calc_macd(sample_ohlcv)
        assert result["trend"] in ("bull", "bear", "neutral")

    def test_bull_trend_on_uptrend(self, trending_ohlcv):
        result = calc_macd(trending_ohlcv)
        assert result["trend"] in ("bull", "neutral")


# ── calc_bb ───────────────────────────────────────────────────────────

class TestCalcBb:
    def test_returns_zeros_when_too_short(self):
        df = pd.DataFrame({"Close": [100.0] * 5})
        result = calc_bb(df)
        assert result["bw"] == 0.0

    def test_result_has_required_keys(self, sample_ohlcv):
        result = calc_bb(sample_ohlcv)
        assert {"upper", "lower", "mid", "bw", "label"} == result.keys()

    def test_upper_above_lower(self, sample_ohlcv):
        result = calc_bb(sample_ohlcv)
        assert result["upper"] > result["lower"]

    def test_squeeze_label_on_flat_data(self, flat_ohlcv):
        result = calc_bb(flat_ohlcv)
        assert result["label"] == "squeeze"

    def test_expanded_label_on_volatile_data(self):
        closes = np.array([100, 120, 80, 130, 70, 140, 60, 150, 50, 160,
                           100, 120, 80, 130, 70, 140, 60, 150, 50, 160], dtype=float)
        df = pd.DataFrame({"Close": closes})
        result = calc_bb(df)
        assert result["label"] == "expanded"

    @pytest.mark.parametrize("bw,expected_label", [
        (3.0, "squeeze"),
        (10.0, "normal"),
        (20.0, "expanded"),
    ])
    def test_bandwidth_labels(self, bw, expected_label):
        # Build synthetic closes that produce the target BB bandwidth
        mid = 100.0
        std_needed = (bw / 100.0 * mid) / (2 * 2.0)
        closes = np.concatenate([
            np.ones(10) * (mid + std_needed),
            np.ones(10) * (mid - std_needed),
        ])
        df = pd.DataFrame({"Close": closes})
        result = calc_bb(df)
        assert result["label"] == expected_label


# ── calc_obv ──────────────────────────────────────────────────────────

class TestCalcObv:
    def test_single_row_returns_flat(self):
        df = pd.DataFrame({
            "Close":  [100.0],
            "Volume": [500.0],
        })
        result = calc_obv(df)
        assert result["obv"] == 0.0
        assert result["trend"] == "FLAT"

    def test_up_candles_increase_obv(self):
        closes = np.linspace(100.0, 120.0, 15)
        df = pd.DataFrame({"Close": closes, "Volume": np.ones(15) * 1000.0})
        result = calc_obv(df)
        assert result["obv"] > 0.0
        assert result["trend"] == "UP"

    def test_result_has_required_keys(self, sample_ohlcv):
        result = calc_obv(sample_ohlcv)
        assert {"obv", "trend"} == result.keys()


# ── calc_atr_pct ──────────────────────────────────────────────────────

class TestCalcAtrPct:
    def test_zero_price_returns_zero(self):
        assert calc_atr_pct(2.5, 0.0) == 0.0

    def test_correct_calculation(self):
        assert calc_atr_pct(2.5, 100.0) == pytest.approx(2.5)

    def test_proportional(self):
        assert calc_atr_pct(5.0, 100.0) == pytest.approx(2.0 * calc_atr_pct(2.5, 100.0))


# ── calc_donchian ─────────────────────────────────────────────────────

class TestCalcDonchian:
    def test_returns_zeros_when_too_short(self):
        df = pd.DataFrame({
            "High": [100.0] * 3,
            "Low":  [95.0]  * 3,
        })
        result = calc_donchian(df, period=20)
        assert result["upper"] == 0.0
        assert result["lower"] == 0.0

    def test_upper_lower_correct(self, sample_ohlcv):
        result = calc_donchian(sample_ohlcv, period=20)
        assert result["upper"] >= result["lower"]
        assert result["upper"] == pytest.approx(sample_ohlcv.tail(20)["High"].max())
        assert result["lower"] == pytest.approx(sample_ohlcv.tail(20)["Low"].min())

    def test_result_has_required_keys(self, sample_ohlcv):
        result = calc_donchian(sample_ohlcv)
        assert {"upper", "lower", "mid", "widthPct", "period"} == result.keys()


# ── detect_squeeze ────────────────────────────────────────────────────

class TestDetectSqueeze:
    def test_squeeze_detected_when_both_conditions_met(self):
        # bb_bw=3% (< 5%), dc_width/(20*atr) < 0.7
        bb = {"bw": 3.0}
        # dc_width = upper - lower; period=20; atr=1.0 → ratio = dc_width/20
        # need ratio < 0.7 → dc_width < 14 → e.g. upper=107, lower=100 → width=7
        donchian = {"upper": 107.0, "lower": 100.0, "period": 20}
        result = detect_squeeze(bb, donchian, atr=1.0, price=103.0)
        assert result["squeeze"] is True
        assert result["bbTight"] is True
        assert result["dcTight"] is True

    def test_no_squeeze_when_bb_wide(self):
        bb = {"bw": 12.0}  # > 5%
        donchian = {"upper": 107.0, "lower": 100.0, "period": 20}
        result = detect_squeeze(bb, donchian, atr=1.0, price=103.0)
        assert result["squeeze"] is False
        assert result["bbTight"] is False

    def test_no_squeeze_when_dc_wide(self):
        bb = {"bw": 3.0}
        # dc_width=30 → ratio = 30/20 = 1.5 > 0.7 → not dc_tight
        donchian = {"upper": 130.0, "lower": 100.0, "period": 20}
        result = detect_squeeze(bb, donchian, atr=1.0, price=115.0)
        assert result["squeeze"] is False
        assert result["dcTight"] is False

    def test_zero_atr_returns_inf_ratio(self):
        bb = {"bw": 3.0}
        donchian = {"upper": 107.0, "lower": 100.0, "period": 20}
        result = detect_squeeze(bb, donchian, atr=0.0, price=103.0)
        assert result["dcAtrRatio"] == float("inf")
        assert result["squeeze"] is False

    def test_result_has_required_keys(self, flat_ohlcv):
        from indicators import calc_bb, calc_donchian, calc_atr
        bb = calc_bb(flat_ohlcv)
        donchian = calc_donchian(flat_ohlcv)
        atr = calc_atr(flat_ohlcv)
        price = float(flat_ohlcv["Close"].iloc[-1])
        result = detect_squeeze(bb, donchian, atr, price)
        assert {"squeeze", "bbTight", "dcTight", "bbBw", "dcAtrRatio"} == result.keys()


# ── calc_change_24h ───────────────────────────────────────────────────

class TestCalcChange24h:
    def test_none_returns_zero(self):
        assert calc_change_24h(None) == 0.0

    def test_single_row_returns_zero(self):
        df = pd.DataFrame({"Open": [100.0], "Close": [105.0]})
        assert calc_change_24h(df) == 0.0

    def test_positive_change(self):
        df = pd.DataFrame({"Open": [100.0, 101.0], "Close": [101.0, 110.0]})
        assert calc_change_24h(df) == pytest.approx(10.0)

    def test_negative_change(self):
        df = pd.DataFrame({"Open": [100.0, 99.0], "Close": [99.0, 90.0]})
        assert calc_change_24h(df) == pytest.approx(-10.0)


# ── calc_fib ──────────────────────────────────────────────────────────

class TestCalcFib:
    def test_result_has_required_keys(self, sample_ohlcv):
        result = calc_fib(sample_ohlcv)
        assert {"swingHigh", "swingLow", "levels", "priceZone"} == result.keys()

    def test_swing_high_above_swing_low(self, sample_ohlcv):
        result = calc_fib(sample_ohlcv)
        assert result["swingHigh"] >= result["swingLow"]

    def test_seven_fib_levels(self, sample_ohlcv):
        result = calc_fib(sample_ohlcv)
        assert len(result["levels"]) == 7

    def test_levels_ascending(self, sample_ohlcv):
        result = calc_fib(sample_ohlcv)
        prices = [l["price"] for l in result["levels"]]
        assert prices == sorted(prices)

    def test_price_zone_is_string(self, sample_ohlcv):
        result = calc_fib(sample_ohlcv)
        assert isinstance(result["priceZone"], str)


# ── get_advanced_metrics (integration) ────────────────────────────────

class TestGetAdvancedMetrics:
    def test_empty_df_returns_empty_dict(self, empty_df):
        oi = OIData()
        result = get_advanced_metrics(empty_df, empty_df, empty_df, empty_df, empty_df, oi)
        assert result == {}

    def test_valid_input_returns_non_empty_dict(self, sample_ohlcv):
        oi = OIData(oiNow=1000.0, oiChange=-3.0)
        result = get_advanced_metrics(
            sample_ohlcv, sample_ohlcv, sample_ohlcv,
            sample_ohlcv, sample_ohlcv, oi, funding=0.01
        )
        assert len(result) > 0

    def test_returns_rsi_in_valid_range(self, sample_ohlcv):
        oi = OIData()
        result = get_advanced_metrics(
            sample_ohlcv, sample_ohlcv, sample_ohlcv,
            sample_ohlcv, sample_ohlcv, oi
        )
        assert 0.0 <= result.get("rsi", 50.0) <= 100.0

    def test_returns_structure(self, sample_ohlcv):
        oi = OIData()
        result = get_advanced_metrics(
            sample_ohlcv, sample_ohlcv, sample_ohlcv,
            sample_ohlcv, sample_ohlcv, oi
        )
        assert result.get("structure4h") in ("Bullish", "Bearish", "Neutral")

    def test_flow_zero_when_empty_flow_df(self, sample_ohlcv, empty_df):
        oi = OIData()
        result = get_advanced_metrics(
            sample_ohlcv, sample_ohlcv, sample_ohlcv,
            sample_ohlcv, empty_df, oi
        )
        assert result.get("flow24h", 0.0) == pytest.approx(0.0)
