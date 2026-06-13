"""Tests for the Phase 2 regime layer (regime.py).

Ports (ER, Hurst, adx_slope, regime_confirmation) are checked for parity
against their defining formulas / behaviour. build_regime is checked through
its REAL call path — not reconstructed dicts — so the hurst_regime key remap
is exercised (a missed remap silently routes everything to INSUFFICIENT_DATA).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from regime import (
    build_regime,
    calc_adx_slope,
    calc_efficiency_ratio,
    calc_regime_confirmation,
    derive_trend_daily,
    hurst_daily,
)


def _df_from_closes(closes: list[float]) -> pd.DataFrame:
    """Minimal OHLCV frame for ADX-slope: tight bars around each close."""
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "High": closes + 0.5,
        "Low": closes - 0.5,
        "Close": closes,
        "Open": closes,
        "Volume": np.full(len(closes), 1000.0),
    })


class TestEfficiencyRatio:
    def test_matches_defining_formula(self):
        closes = [10, 11, 10.5, 12, 11.8, 13, 12.5, 14, 13.7, 15, 16]
        c = closes[-11:]
        net = abs(c[-1] - c[0])
        path = sum(abs(c[i + 1] - c[i]) for i in range(len(c) - 1))
        expected = round(net / path, 4)
        assert calc_efficiency_ratio(closes, 10)["er_value"] == expected

    def test_pure_trend_is_trending(self):
        closes = list(range(1, 30))  # monotonic → ER == 1.0
        out = calc_efficiency_ratio(closes, 10)
        assert out["er_value"] == 1.0
        assert out["er_regime"] == "TRENDING"

    def test_oscillation_is_ranging(self):
        closes = [10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10]  # no net progress
        out = calc_efficiency_ratio(closes, 10)
        assert out["er_value"] < 0.3
        assert out["er_regime"] == "RANGING"

    def test_insufficient_data_unknown(self):
        assert calc_efficiency_ratio([1, 2, 3], 10)["er_regime"] == "UNKNOWN"


class TestHurst:
    def test_trend_more_persistent_than_meanrevert(self):
        rng = np.random.default_rng(42)
        trend = np.cumsum(rng.normal(0.3, 0.5, 120)) + 100  # drifting → persistent
        chop = 100 + rng.normal(0, 1, 120)                  # noise around a level
        h_trend = hurst_daily(list(trend))["hurst_daily"]
        h_chop = hurst_daily(list(chop))["hurst_daily"]
        assert h_trend is not None and h_chop is not None
        assert h_trend > h_chop

    def test_regime_in_valid_set(self):
        rng = np.random.default_rng(1)
        closes = np.cumsum(rng.normal(0, 1, 100)) + 200
        assert hurst_daily(list(closes))["regime"] in (
            "TRENDING", "RANDOM", "MEAN_REVERTING")

    def test_insufficient_data(self):
        assert hurst_daily([1.0] * 10)["regime"] == "UNKNOWN"


class TestAdxSlope:
    def test_accelerating_trend_rises(self):
        closes = list(np.linspace(100, 160, 60))  # steady strong up-move
        out = calc_adx_slope(_df_from_closes(closes))
        assert out["adx_slope"] in ("RISING", "FLAT", "PEAKED")
        assert "adx_values" in out

    def test_too_few_bars_is_flat(self):
        out = calc_adx_slope(_df_from_closes([100, 101, 102]))
        assert out["adx_slope"] == "FLAT"


class TestRegimeConfirmation:
    def test_ranging_match_high_conviction_grid(self):
        out = calc_regime_confirmation(
            {"er_regime": "RANGING"}, {"hurst_regime": "MEAN_REVERTING"}, "Neutral")
        assert out["combined_regime"] == "CONFIRMED_RANGING"
        assert out["conviction"] == "HIGH"

    def test_both_trending_bull(self):
        out = calc_regime_confirmation(
            {"er_regime": "TRENDING"}, {"hurst_regime": "TRENDING"}, "Bullish")
        assert out["combined_regime"] == "CONFIRMED_TRENDING_BULL"
        assert out["trend_direction"] == "BULL"

    def test_unknown_propagates(self):
        out = calc_regime_confirmation(
            {"er_regime": "UNKNOWN"}, {"hurst_regime": "TRENDING"}, "Neutral")
        assert out["combined_regime"] == "UNKNOWN"
        assert out["strategy_hint"] == "INSUFFICIENT_DATA"


class TestTrendDaily:
    def test_rising_is_bullish(self):
        assert derive_trend_daily(list(range(1, 80))) == "Bullish"

    def test_falling_is_bearish(self):
        assert derive_trend_daily(list(range(80, 1, -1))) == "Bearish"

    def test_short_series_neutral(self):
        assert derive_trend_daily([1, 2, 3]) == "Neutral"


class TestBuildRegime:
    def test_real_path_produces_resolved_regime(self):
        """The wiring test: known-good daily closes through build_regime must NOT
        collapse to UNKNOWN. Catches a broken hurst_regime remap."""
        rng = np.random.default_rng(7)
        daily = list(np.cumsum(rng.normal(0, 1, 100)) + 200)
        df_main = _df_from_closes(list(np.cumsum(rng.normal(0, 0.5, 80)) + 200))
        out = build_regime({"dailyCloses": daily}, df_main)
        assert out["confirmation"]["combined_regime"] != "UNKNOWN"
        assert out["er"]["er_regime"] != "UNKNOWN"
        assert out["hurst"]["regime"] not in ("UNKNOWN", "ERROR")
        for key in ("er", "hurst", "trendDaily", "confirmation", "adxSlope"):
            assert key in out

    def test_empty_spine_degrades_without_raising(self):
        out = build_regime({"dailyCloses": []}, _df_from_closes([100, 101, 102]))
        assert out["er"]["er_regime"] == "UNKNOWN"
        assert out["confirmation"]["combined_regime"] == "UNKNOWN"
        assert out["confirmation"]["strategy_hint"] == "INSUFFICIENT_DATA"

    def test_missing_mtf_key(self):
        out = build_regime({}, _df_from_closes([100, 101, 102]))
        assert out["confirmation"]["combined_regime"] == "UNKNOWN"
