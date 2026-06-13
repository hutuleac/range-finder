"""Tests for the Phase 2.5 volatility-cycle FSM (fsm.py).

This is a range-finder-native HEURISTIC, not a parity port — so these tests
verify the adapted state LOGIC (priority order, input mapping, direction
semantics) and graceful degradation, not numerical parity with Double.

Each state is reached by crafting a feature dict; the priority ladder
(COIL → EXPANSION → EXHAUSTION → TREND → NEUTRAL) means each test must also
keep the higher-priority gates from tripping (e.g. TREND keeps RSI mid and
adx_slope non-rolling so EXHAUSTION doesn't fire first).
"""
from __future__ import annotations

from fsm import (
    COIL,
    EXHAUSTION,
    EXPANSION,
    NEUTRAL,
    TREND,
    UNKNOWN,
    build_fsm,
    classify,
    extract_features,
)


def _base() -> dict:
    """A NEUTRAL-by-default feature dict; tests override specific fields."""
    return {
        "squeeze": False,
        "bb_label": "normal",
        "price": 100.0,
        "bb_upper": 110.0,
        "bb_lower": 90.0,
        "adx": 15.0,
        "adx_slope": "FLAT",
        "er_regime": "RANGING",
        "rsi": 50.0,
        "structure4h": "Neutral",
    }


class TestClassifyReachesEachState:
    def test_coil_from_squeeze_flag(self):
        f = _base()
        f["squeeze"] = True
        out = classify(f)
        assert out["state"] == COIL
        assert out["direction"] == "NEUTRAL"

    def test_coil_from_bb_label(self):
        f = _base()
        f["bb_label"] = "squeeze"
        assert classify(f)["state"] == COIL

    def test_expansion_long_break(self):
        f = _base()
        f["price"] = 115.0          # above bb_upper 110
        f["adx_slope"] = "RISING"
        f["adx"] = 22.0
        out = classify(f)
        assert out["state"] == EXPANSION
        assert out["direction"] == "LONG"

    def test_expansion_short_break(self):
        f = _base()
        f["price"] = 85.0           # below bb_lower 90
        f["adx_slope"] = "RISING"
        f["adx"] = 22.0
        out = classify(f)
        assert out["state"] == EXPANSION
        assert out["direction"] == "SHORT"

    def test_exhaustion_long_structure_reverses_short(self):
        f = _base()
        f["structure4h"] = "Bullish"
        f["rsi"] = 70.0             # stretched up
        f["adx"] = 24.0
        f["adx_slope"] = "PEAKED"   # rolling over
        out = classify(f)
        assert out["state"] == EXHAUSTION
        assert out["direction"] == "SHORT"   # reversal bias

    def test_exhaustion_short_structure_reverses_long(self):
        f = _base()
        f["structure4h"] = "Bearish"
        f["rsi"] = 30.0             # stretched down
        f["adx"] = 24.0
        f["adx_slope"] = "FALLING"
        out = classify(f)
        assert out["state"] == EXHAUSTION
        assert out["direction"] == "LONG"

    def test_trend_long(self):
        f = _base()
        f["er_regime"] = "TRENDING"
        f["adx"] = 30.0
        f["structure4h"] = "Bullish"
        f["rsi"] = 55.0             # NOT stretched → exhaustion gate skipped
        f["adx_slope"] = "RISING"   # not rolling over
        # price inside band → no expansion
        out = classify(f)
        assert out["state"] == TREND
        assert out["direction"] == "LONG"

    def test_trend_short(self):
        f = _base()
        f["er_regime"] = "TRENDING"
        f["adx"] = 30.0
        f["structure4h"] = "Bearish"
        f["rsi"] = 45.0
        out = classify(f)
        assert out["state"] == TREND
        assert out["direction"] == "SHORT"

    def test_neutral_default(self):
        out = classify(_base())
        assert out["state"] == NEUTRAL
        assert out["direction"] == "NEUTRAL"


class TestPriorityOrder:
    def test_coil_beats_expansion(self):
        """Compressed AND breaking out → COIL wins (compression dominates)."""
        f = _base()
        f["squeeze"] = True
        f["price"] = 115.0
        f["adx_slope"] = "RISING"
        f["adx"] = 25.0
        assert classify(f)["state"] == COIL

    def test_exhaustion_beats_trend(self):
        """A trending+high-ADX up-structure that is stretched & rolling over is
        EXHAUSTION, not TREND (ladder checks exhaustion first)."""
        f = _base()
        f["er_regime"] = "TRENDING"
        f["adx"] = 30.0
        f["structure4h"] = "Bullish"
        f["rsi"] = 70.0
        f["adx_slope"] = "PEAKED"
        assert classify(f)["state"] == EXHAUSTION


class TestGracefulDegradation:
    def test_empty_features_neutral(self):
        out = classify({})
        assert out["state"] == NEUTRAL

    def test_none_features_neutral(self):
        out = classify(None)
        assert out["state"] == NEUTRAL

    def test_missing_fields_never_raise(self):
        # Only a couple of keys present; classify must not raise.
        out = classify({"adx": 20.0})
        assert out["state"] in (NEUTRAL, COIL, EXPANSION, EXHAUSTION, TREND)

    def test_expansion_needs_rising_slope(self):
        """Band break without rising ADX is NOT expansion (falls through)."""
        f = _base()
        f["price"] = 115.0
        f["adx_slope"] = "FLAT"
        f["adx"] = 25.0
        assert classify(f)["state"] != EXPANSION

    def test_exhaustion_needs_stretched_and_rolling(self):
        """Structure + high ADX but RSI mid and slope rising → not exhaustion."""
        f = _base()
        f["structure4h"] = "Bullish"
        f["rsi"] = 55.0
        f["adx"] = 24.0
        f["adx_slope"] = "RISING"
        assert classify(f)["state"] != EXHAUSTION


class TestExtractFeatures:
    def test_pulls_nested_keys(self):
        metrics = {
            "squeeze": {"squeeze": True},
            "bb": {"label": "squeeze", "upper": 110.0, "lower": 90.0},
            "currClose": 100.0,
            "adx": {"adx": 22.0},
            "rsi": 60.0,
            "structure4h": "Bullish",
        }
        regime = {"er": {"er_regime": "TRENDING"},
                  "adxSlope": {"adx_slope": "RISING"}}
        f = extract_features(metrics, regime)
        assert f["squeeze"] is True
        assert f["bb_label"] == "squeeze"
        assert f["price"] == 100.0
        assert f["bb_upper"] == 110.0
        assert f["adx"] == 22.0
        assert f["adx_slope"] == "RISING"
        assert f["er_regime"] == "TRENDING"
        assert f["structure4h"] == "Bullish"

    def test_empty_inputs_yield_safe_defaults(self):
        f = extract_features({}, {})
        assert f["squeeze"] is False
        assert f["adx"] == 0.0
        assert f["adx_slope"] == "FLAT"
        assert f["er_regime"] == "UNKNOWN"
        assert f["structure4h"] == "Neutral"

    def test_none_inputs_do_not_raise(self):
        f = extract_features(None, None)
        assert f["price"] is None
        assert f["adx"] == 0.0


class TestBuildFsm:
    def test_end_to_end_coil(self):
        metrics = {"squeeze": {"squeeze": True}, "bb": {"label": "squeeze"},
                   "currClose": 100.0, "adx": {"adx": 10.0}, "rsi": 50.0,
                   "structure4h": "Neutral"}
        out = build_fsm(metrics, {})
        assert out["state"] == COIL

    def test_end_to_end_neutral_on_empty(self):
        out = build_fsm({}, {})
        assert out["state"] == NEUTRAL
        assert out["direction"] == "NEUTRAL"

    def test_never_raises_returns_unknown_on_hard_failure(self):
        # A metrics object whose .get blows up forces the except branch.
        class Boom:
            def get(self, *a, **k):
                raise RuntimeError("boom")

        out = build_fsm(Boom(), {})
        assert out["state"] == UNKNOWN
        assert out["direction"] == "NEUTRAL"

    def test_returns_three_keys(self):
        out = build_fsm({}, {})
        assert set(out) == {"state", "direction", "reason"}
