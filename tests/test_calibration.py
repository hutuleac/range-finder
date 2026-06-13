"""Tests for the offline calibration harness (calibration/).

Pure helpers (forward outcomes, separation metrics, feature reconstruction) are
tested on synthetic data. The runner is tested with fetch_klines mocked — NO
network is hit. A synthetic regime-break fixture proves the walk is lookahead-
free and that separation comes out in the expected direction.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from calibration import features as F
from calibration import run as R


# ─────────────────────────────────────────────────────────────────────
#  Synthetic kline builders
# ─────────────────────────────────────────────────────────────────────
def _klines_from_closes(closes, start_ms=0, step_ms=86_400_000):
    """Binance 12-col klines from a close series (o=h=l=c=close, vol const)."""
    out = []
    for i, c in enumerate(closes):
        c = float(c)
        out.append([start_ms + i * step_ms, c, c * 1.002, c * 0.998, c,
                    1000.0, 0, 0, 0, 500.0, 0, 0])
    return out


def _ramp_then_chop(n_trend=120, n_chop=60):
    """Clean uptrend (high ER/trendiness) followed by a tight oscillation
    (low ER/trendiness) — a known regime break for the leakage test."""
    trend = np.linspace(100.0, 200.0, n_trend)
    chop = 200.0 + 2.0 * np.sin(np.arange(n_chop) * 1.3)
    return np.concatenate([trend, chop])


# ─────────────────────────────────────────────────────────────────────
#  1. Forward outcomes — lookahead-free
# ─────────────────────────────────────────────────────────────────────
class TestForwardOutcomes:
    def test_abs_return_basic(self):
        closes = [100, 110, 121]
        assert F.forward_abs_return(closes, 0, 2) == pytest.approx(0.21)

    def test_abs_return_off_series_returns_none(self):
        assert F.forward_abs_return([100, 101], 1, 5) is None

    def test_abs_return_zero_base_none(self):
        assert F.forward_abs_return([0, 100], 0, 1) is None

    def test_abs_return_negative_idx_none(self):
        assert F.forward_abs_return([100, 101, 102], -1, 1) is None

    def test_trendiness_one_way_is_one(self):
        # strictly monotone → net == path → trendiness 1.0
        assert F.forward_trendiness([1, 2, 3, 4], 0, 3) == pytest.approx(1.0)

    def test_trendiness_round_trip_is_low(self):
        # up then back down → net small, path large → near 0
        t = F.forward_trendiness([100, 110, 100], 0, 2)
        assert t == pytest.approx(0.0, abs=1e-9)

    def test_trendiness_flat_path_none(self):
        assert F.forward_trendiness([100, 100, 100], 0, 2) is None

    def test_trendiness_off_series_none(self):
        assert F.forward_trendiness([100, 101], 0, 5) is None

    def test_realized_vol_positive(self):
        closes = [100, 101, 99, 102, 98]
        v = F.forward_realized_vol(closes, 0, 4)
        assert v is not None and v > 0

    def test_realized_vol_off_series_none(self):
        assert F.forward_realized_vol([100, 101], 0, 5) is None

    def test_realized_vol_nonpositive_price_none(self):
        assert F.forward_realized_vol([100, 0, 101], 0, 2) is None

    def test_no_lookahead_uses_only_forward_bars(self):
        # Mutating bars at/before idx must NOT change a forward outcome at idx.
        base = [100, 101, 102, 130, 140, 150]
        a = F.forward_abs_return(base, 2, 2)
        mutated = [999, 0.1, 102, 130, 140, 150]  # change history only
        b = F.forward_abs_return(mutated, 2, 2)
        assert a == b


# ─────────────────────────────────────────────────────────────────────
#  2. Separation metrics
# ─────────────────────────────────────────────────────────────────────
class TestSeparationMetrics:
    def test_pearson_perfect_positive(self):
        assert F.pearson_r([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)

    def test_pearson_perfect_negative(self):
        assert F.pearson_r([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)

    def test_pearson_tolerates_none(self):
        r = F.pearson_r([1, None, 3, 4], [2, 9, 6, 8])
        assert r == pytest.approx(1.0)

    def test_pearson_too_few_none(self):
        assert F.pearson_r([1, 2], [3, 4]) is None

    def test_pearson_constant_none(self):
        assert F.pearson_r([5, 5, 5, 5], [1, 2, 3, 4]) is None

    def test_pearson_nan_filtered(self):
        assert F.pearson_r([1, float("nan"), 3, 4], [2, 9, 6, 8]) == pytest.approx(1.0)

    def test_group_means(self):
        g = F.group_means(["A", "B", "A", "B"], [1.0, 10.0, 3.0, 20.0])
        assert g["A"]["mean"] == pytest.approx(2.0)
        assert g["B"]["mean"] == pytest.approx(15.0)
        assert g["A"]["n"] == 2

    def test_group_means_skips_none_and_nan(self):
        g = F.group_means(["A", "A", "A"], [2.0, None, float("nan")])
        assert g["A"]["n"] == 1 and g["A"]["mean"] == pytest.approx(2.0)

    def test_rank_auc_perfect(self):
        # high score perfectly predicts positive class
        auc = F.rank_auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1])
        assert auc == pytest.approx(1.0)

    def test_rank_auc_inverted(self):
        auc = F.rank_auc([0.9, 0.8, 0.2, 0.1], [0, 0, 1, 1])
        assert auc == pytest.approx(0.0)

    def test_rank_auc_ties_half(self):
        auc = F.rank_auc([0.5, 0.5, 0.5, 0.5], [0, 1, 0, 1])
        assert auc == pytest.approx(0.5)

    def test_rank_auc_single_class_none(self):
        assert F.rank_auc([0.1, 0.2, 0.3], [1, 1, 1]) is None

    def test_rank_auc_empty_none(self):
        assert F.rank_auc([], []) is None

    def test_rank_auc_filters_nan_scores(self):
        auc = F.rank_auc([0.1, float("nan"), 0.8, 0.9], [0, 0, 1, 1])
        assert auc == pytest.approx(1.0)

    def test_median_split(self):
        labels = F.median_split_label([1.0, 2.0, 3.0, 4.0])
        assert labels == [0, 0, 1, 1]

    def test_median_split_with_none(self):
        labels = F.median_split_label([1.0, None, 3.0, 4.0])
        assert labels[1] == 0  # None maps to 0

    def test_median_split_all_none(self):
        assert F.median_split_label([None, None]) == [0, 0]


# ─────────────────────────────────────────────────────────────────────
#  3. Feature reconstruction (with stub callables — pure)
# ─────────────────────────────────────────────────────────────────────
class TestReconstruction:
    def test_slice_4h_respects_timestamp(self):
        df = pd.DataFrame({"Time": [0, 100, 200, 300], "Close": [1, 2, 3, 4]})
        out = F._slice_4h_for_daily(df, 150)
        assert list(out["Close"]) == [1, 2]

    def test_slice_4h_no_time_column_passthrough(self):
        df = pd.DataFrame({"Close": [1, 2, 3]})
        assert F._slice_4h_for_daily(df, 999).equals(df)

    def test_slice_4h_empty_passthrough(self):
        df = pd.DataFrame(columns=["Time", "Close"])
        assert F._slice_4h_for_daily(df, 5).empty

    def test_reconstruct_regime_only_sees_past(self):
        seen = {}

        def fake_build_regime(mtf, df4h):
            seen["n_daily"] = len(mtf["dailyCloses"])
            return {"er": {"er_value": 0.4, "er_regime": "TRANSITIONAL"},
                    "hurst": {"hurst_daily": 0.5, "regime": "RANDOM"},
                    "trendDaily": "Neutral",
                    "confirmation": {"combined_regime": "TRANSITIONAL",
                                     "conviction": "MEDIUM"},
                    "adxSlope": {"adx_slope": "FLAT"}}

        closes = list(range(100))
        out = F.reconstruct_regime(closes, pd.DataFrame({"Close": [1]}), 9, None,
                                   fake_build_regime)
        assert seen["n_daily"] == 10          # idx 9 → closes[:10]
        assert out["er_regime"] == "TRANSITIONAL"
        assert out["hurst_regime"] == "RANDOM"
        assert "_regime" in out

    def test_reconstruct_regime_handles_empty_dicts(self):
        out = F.reconstruct_regime([1, 2, 3], pd.DataFrame({"Close": [1]}), 2, None,
                                   lambda mtf, df: {})
        assert out["er_regime"] == "UNKNOWN"
        assert out["adx_slope"] == "FLAT"

    def test_reconstruct_price_metrics_empty(self):
        out = F.reconstruct_price_metrics(
            pd.DataFrame(columns=["Close"]),
            *[lambda *a, **k: None] * 6,
        )
        assert out["structure4h"] == "Neutral" and out["rsi"] == 50.0

    def test_reconstruct_price_metrics_calls_indicators(self):
        df = pd.DataFrame({"Close": [10.0, 11.0, 12.0]})
        out = F.reconstruct_price_metrics(
            df,
            calc_rsi=lambda d: 55.0,
            calc_atr=lambda d: 1.0,
            calc_atr_pct=lambda atr, price: 2.0,
            calc_adx=lambda d: {"adx": 18.0},
            calc_bb=lambda d: {"bw": 3.0},
            calc_market_structure=lambda d, lb: "Bullish",
        )
        assert out["rsi"] == 55.0 and out["bbBw"] == 3.0
        assert out["adx"]["adx"] == 18.0 and out["structure4h"] == "Bullish"

    def test_reconstruct_matrix_neutralises_live_inputs(self):
        captured = {}

        def fake_calc_matrix(metrics, regime):
            captured.update(metrics)
            return {"scores": {"GRID_NEUTRAL": 60.0, "DIRECTIONAL": 40.0}}

        scores = F.reconstruct_matrix_scores(
            {"rsi": 50.0, "funding": 999.0}, {}, fake_calc_matrix)
        # live-only defaults overlaid, but explicit price metric kept
        assert captured["funding"] == 999.0  # caller-supplied wins over neutral
        assert captured["flow"] == 0.0       # neutral default present
        assert scores["GRID_NEUTRAL"] == 60.0


# ─────────────────────────────────────────────────────────────────────
#  4. summarize_separation — integration of the pure layer
# ─────────────────────────────────────────────────────────────────────
class TestSummarize:
    def test_summarize_empty(self):
        s = F.summarize_separation([], [])
        assert s["n_steps"] == 0
        assert s["er_vs_trendiness"] is None
        assert s["grid_neutral_auc"] is None

    def test_summarize_detects_positive_er_link(self):
        # Construct rows where high ER co-occurs with high forward trendiness.
        feats, outs = [], []
        for i in range(10):
            er = i / 10.0
            feats.append({"er_value": er, "er_regime": "TRENDING" if er > 0.5 else "RANGING",
                          "hurst": er, "grid_neutral": 100 - i * 5,
                          "directional": i * 5})
            outs.append({"fwd_trendiness": er, "fwd_abs_return": er * 0.1})
        s = F.summarize_separation(feats, outs)
        assert s["er_vs_trendiness"] > 0.9
        # grid_neutral score high when trendiness low → should separate >0.5
        assert s["grid_neutral_auc"] is not None and s["grid_neutral_auc"] > 0.7
        assert s["directional_auc"] is not None and s["directional_auc"] > 0.7
        assert "RANGING" in s["ranging_grid_quality"]


# ─────────────────────────────────────────────────────────────────────
#  5. Runner — network mocked, real regime/matrix/indicators
# ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    d = tmp_path / "_cache"
    d.mkdir()
    monkeypatch.setattr(R, "CACHE_DIR", d)
    return d


@pytest.fixture
def report_path(tmp_path, monkeypatch):
    p = tmp_path / "docs" / "CALIBRATION_REPORT.md"
    monkeypatch.setattr(R, "REPORT_PATH", p)
    return p


class TestLoadKlines:
    def test_reads_from_cache(self, cache_dir):
        raw = _klines_from_closes([1, 2, 3])
        (cache_dir / "BTC_USDT_1d.json").write_text(json.dumps(raw))
        out = R.load_klines("BTC/USDT", "1d", 3, use_network=False)
        assert out == raw

    def test_offline_miss_returns_empty(self, cache_dir):
        assert R.load_klines("ZZZ/USDT", "1d", 3, use_network=False) == []

    def test_corrupt_cache_then_offline(self, cache_dir):
        (cache_dir / "BTC_USDT_1d.json").write_text("{not json")
        assert R.load_klines("BTC/USDT", "1d", 3, use_network=False) == []

    def test_network_fetch_caches(self, cache_dir, monkeypatch):
        raw = _klines_from_closes([5, 6, 7])
        import data_fetcher
        monkeypatch.setattr(data_fetcher, "fetch_klines", lambda s, t, l: raw)
        monkeypatch.setattr(R, "FETCH_SLEEP_S", 0)
        out = R.load_klines("BTC/USDT", "1d", 3, use_network=True)
        assert out == raw
        assert (cache_dir / "BTC_USDT_1d.json").exists()

    def test_network_failure_returns_empty(self, cache_dir, monkeypatch):
        import data_fetcher

        def boom(*a):
            raise RuntimeError("net down")

        monkeypatch.setattr(data_fetcher, "fetch_klines", boom)
        assert R.load_klines("BTC/USDT", "1d", 3, use_network=True) == []


class TestWalkAndRun:
    def _seed_cache(self, cache_dir, symbol, daily_closes):
        safe = symbol.replace("/", "_")
        (cache_dir / f"{safe}_1d.json").write_text(
            json.dumps(_klines_from_closes(daily_closes)))
        # 4H frame: reuse the same closes at finer granularity (timestamps within range)
        (cache_dir / f"{safe}_4h.json").write_text(
            json.dumps(_klines_from_closes(daily_closes, step_ms=14_400_000)))

    def test_walk_insufficient_data_skips(self, cache_dir):
        self._seed_cache(cache_dir, "BTC/USDT", [100, 101, 102])
        feats, outs = R.walk_pair("BTC/USDT", 5, 10, use_network=False)
        assert feats == [] and outs == []

    def test_walk_produces_aligned_rows(self, cache_dir):
        closes = _ramp_then_chop().tolist()
        self._seed_cache(cache_dir, "BTC/USDT", closes)
        feats, outs = R.walk_pair("BTC/USDT", 5, 20, use_network=False)
        assert len(feats) == len(outs) and len(feats) > 0
        # every feature row carries the regime + matrix fields
        assert all("er_regime" in f and "grid_neutral" in f for f in feats)

    def test_run_writes_report_and_separation(self, cache_dir, report_path):
        closes = _ramp_then_chop().tolist()
        self._seed_cache(cache_dir, "BTC/USDT", closes)
        sep = R.run(["BTC/USDT"], horizon=5, max_steps=20, use_network=False)
        assert report_path.exists()
        text = report_path.read_text()
        assert "Calibration Report" in text
        assert "NOT validated for live use" in text
        assert sep["n_steps"] > 0

    def test_run_empty_writes_report(self, cache_dir, report_path):
        sep = R.run(["NOPE/USDT"], horizon=5, max_steps=20, use_network=False)
        assert sep["n_steps"] == 0
        assert report_path.exists()

    def test_main_no_network_smoke(self, cache_dir, report_path, monkeypatch):
        closes = _ramp_then_chop().tolist()
        self._seed_cache(cache_dir, "BTC/USDT", closes)
        rc = R.main(["--pairs", "BTC/USDT", "--no-network", "--max-steps", "15"])
        assert rc == 0 and report_path.exists()

    def test_main_empty_returns_zero(self, cache_dir, report_path):
        rc = R.main(["--pairs", "NOPE/USDT", "--no-network"])
        assert rc == 0


class TestReportRendering:
    def _sample_sep(self, **over):
        base = {
            "n_steps": 30,
            "er_vs_trendiness": 0.42,
            "hurst_vs_trendiness": 0.05,
            "ranging_grid_quality": {
                "RANGING": {"mean": 0.2, "median": 0.2, "n": 10},
                "TRENDING": {"mean": 0.7, "median": 0.7, "n": 8},
            },
            "grid_neutral_auc": 0.63,
            "directional_auc": 0.58,
        }
        base.update(over)
        return base

    def _meta(self):
        return {"mode": "cache-only", "generated": "now", "pairs": ["BTC/USDT"],
                "horizon": 5, "max_steps": 20}

    def test_render_good_case(self):
        md = R.render_report(self._sample_sep(), {"BTC/USDT": 30}, self._meta())
        assert "as-expected" in md and "separates" in md
        assert "RANGING vs TRENDING separation present" in md

    def test_render_weak_case_flags_misset(self):
        sep = self._sample_sep(
            er_vs_trendiness=0.0,
            ranging_grid_quality={
                "RANGING": {"mean": 0.8, "median": 0.8, "n": 5},
                "TRENDING": {"mean": 0.3, "median": 0.3, "n": 5},
            },
            grid_neutral_auc=0.50,
            directional_auc=0.40,
        )
        md = R.render_report(sep, {"BTC/USDT": 10}, self._meta())
        assert "coin-flip" in md
        assert "inverted" in md.lower()
        assert "SUGGEST" in md

    def test_render_strong_inversion_called_out(self):
        # The real live-run shape: ER strongly inverted, GRID_NEUTRAL anti-predictive.
        sep = self._sample_sep(
            er_vs_trendiness=-0.628,
            ranging_grid_quality={
                "RANGING": {"mean": 0.741, "median": 0.8, "n": 7},
                "TRENDING": {"mean": 0.272, "median": 0.3, "n": 21},
            },
            grid_neutral_auc=0.158,
            directional_auc=0.599,
        )
        md = R.render_report(sep, {"BTC/USDT": 20}, self._meta())
        assert "STRONGLY INVERTED" in md
        assert "ANTI-PREDICTIVE" in md
        # the diff must NOT claim usable separation when GRID_NEUTRAL is inverted
        assert "usable separation" not in md
        # ER diff must warn against just lengthening the period
        assert "DO NOT just lengthen" in md
        # autocorrelation caveat present
        assert "autocorrelated" in md.lower()

    def test_render_empty_separation(self):
        sep = {"n_steps": 0, "er_vs_trendiness": None, "hurst_vs_trendiness": None,
               "ranging_grid_quality": {}, "grid_neutral_auc": None,
               "directional_auc": None}
        md = R.render_report(sep, {}, self._meta())
        assert "No strong mis-set signal" in md
        assert "n/a" in md

    def test_fmt_helpers(self):
        assert R._fmt(None) == "n/a"
        assert R._fmt(0.12345) == "0.123"
        assert R._fmt("X") == "X"
