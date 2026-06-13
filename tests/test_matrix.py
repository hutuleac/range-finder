"""Tests for the Phase 3 profitability matrix (matrix.py).

Checks the weighted-scoring methodology, strategy-aware normalization, the
winning-strategy selection, and graceful degradation on missing inputs.
"""
from __future__ import annotations

import json

from config import CFG
from matrix import STRATEGIES, calc_matrix


def _grid_friendly() -> tuple[dict, dict]:
    """Ranging, low-trend, compressed → grid-favourable."""
    metrics = {
        "adx": {"adx": 15.0, "plusDI": 20, "minusDI": 20},
        "bbBw": 2.5, "atrPct": 1.2, "rsi": 50.0, "funding": 0.0,
        "cvd14d": 0.0, "flow": 1.0, "oiChange": -2.0, "structure4h": "Neutral",
    }
    regime = {
        "adxSlope": {"adx_slope": "FALLING"},
        "er": {"er_value": 0.15}, "hurst": {"hurst_daily": 0.40},
        "trendDaily": "Neutral",
    }
    return metrics, regime


def _trending_up() -> tuple[dict, dict]:
    """Strong persistent up-trend → directional / long-favourable."""
    metrics = {
        "adx": {"adx": 38.0, "plusDI": 30, "minusDI": 10},
        "bbBw": 9.0, "atrPct": 3.5, "rsi": 68.0, "funding": -0.015,
        "cvd14d": 500.0, "flow": 25.0, "oiChange": 8.0, "structure4h": "Bullish",
    }
    regime = {
        "adxSlope": {"adx_slope": "RISING"},
        "er": {"er_value": 0.75}, "hurst": {"hurst_daily": 0.70},
        "trendDaily": "Bullish",
    }
    return metrics, regime


class TestStructure:
    def test_scores_all_four_strategies(self):
        out = calc_matrix(*_grid_friendly())
        assert set(out["scores"]) == set(STRATEGIES)
        assert all(0 <= v <= 100 for v in out["scores"].values())

    def test_winner_is_highest_scoring(self):
        out = calc_matrix(*_grid_friendly())
        assert out["scores"][out["winner"]] == max(out["scores"].values())
        assert out["winnerScore"] == out["scores"][out["winner"]]

    def test_breakdown_present_per_strategy(self):
        out = calc_matrix(*_grid_friendly())
        for strat in STRATEGIES:
            rows = out["breakdown"][strat]
            assert len(rows) == len(CFG["MATRIX"]["WEIGHTS"])
            # sorted by contribution descending
            contribs = [r["contribution"] for r in rows]
            assert contribs == sorted(contribs, reverse=True)


class TestScoringLogic:
    def test_grid_friendly_favours_grid_neutral(self):
        out = calc_matrix(*_grid_friendly())
        assert out["scores"]["GRID_NEUTRAL"] > out["scores"]["DIRECTIONAL"]

    def test_trending_favours_directional_over_neutral_grid(self):
        out = calc_matrix(*_trending_up())
        assert out["scores"]["DIRECTIONAL"] > out["scores"]["GRID_NEUTRAL"]

    def test_bullish_context_favours_long_over_short(self):
        out = calc_matrix(*_trending_up())
        assert out["scores"]["GRID_LONG"] > out["scores"]["GRID_SHORT"]

    def test_weighted_formula_matches_breakdown(self):
        """score == Σcontribution / Σweight × 100 (the defining formula)."""
        out = calc_matrix(*_grid_friendly())
        for strat in STRATEGIES:
            rows = out["breakdown"][strat]
            wsum = sum(r["contribution"] for r in rows)
            total = sum(r["weight"] for r in rows)
            assert out["scores"][strat] == round(wsum / total * 100, 1)


class TestDegradation:
    def test_empty_inputs_do_not_raise(self):
        out = calc_matrix({}, {})
        assert set(out["scores"]) == set(STRATEGIES)
        assert all(0 <= v <= 100 for v in out["scores"].values())

    def test_missing_regime_uses_neutral_defaults(self):
        metrics, _ = _grid_friendly()
        out = calc_matrix(metrics, None)
        assert out["winner"] in STRATEGIES

    def test_output_is_json_serializable(self):
        """Scores must be plain floats — numpy types break the SQLite JSON payload."""
        out = calc_matrix(*_trending_up())
        json.dumps(out)  # raises TypeError on np.float64
        assert all(type(v) is float for v in out["scores"].values())

    def test_missing_er_hurst_score_neutral_not_zero(self):
        """A None ER/Hurst normalizes to 0.5, not 0 — never zeroes a column."""
        out = calc_matrix({"adx": {"adx": 15.0}}, {"er": {}, "hurst": {}})
        assert all(v > 0 for v in out["scores"].values())
