"""Tests for refresh_data.py — the cron orchestration entry point.

refresh_one() wires together data fetch → indicators → grid scoring → cache
upsert. We mock only the I/O boundary (fetch_klines / fetch_oi / fetch_funding
and upsert_metrics) and let the *real* indicator and grid-calculator math run
on synthetic candles. That keeps the test an honest integration check of the
wiring rather than a mock-everything tautology.
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

import refresh_data
from indicators import OIData


def _raw_klines(n: int, start: float = 100.0) -> list[list]:
    """n Binance-shape 12-col rows following a mild random walk."""
    rng = np.random.default_rng(7)
    closes = start + np.cumsum(rng.normal(0, 0.4, n))
    rows = []
    for i, c in enumerate(closes):
        o = c - rng.uniform(-0.3, 0.3)
        h = max(o, c) + abs(rng.normal(0, 0.3))
        lo = min(o, c) - abs(rng.normal(0, 0.3))
        vol = abs(rng.normal(1000, 100))
        buy = vol * 0.5
        rows.append([i * 14_400_000, o, h, lo, c, vol, 0, 0, 0, buy, 0, 0])
    return rows


@pytest.fixture
def patched_io():
    """Patch the data-fetch boundary + DB upsert; capture upsert args."""
    captured = {}

    def _fake_upsert(symbol, price, score, direction, payload):
        captured.update(symbol=symbol, price=price, score=score,
                        direction=direction, payload=payload)

    with patch.object(refresh_data, "fetch_klines", side_effect=lambda s, tf, n: _raw_klines(n)), \
         patch.object(refresh_data, "fetch_oi", return_value=OIData(oiNow=1000.0, oiChange=-3.0)), \
         patch.object(refresh_data, "fetch_funding", return_value=-0.005), \
         patch.object(refresh_data, "upsert_metrics", side_effect=_fake_upsert):
        yield captured


class TestRefreshOne:
    def test_returns_payload_with_expected_keys(self, patched_io):
        payload = refresh_data.refresh_one("BTC/USDT")
        assert payload is not None
        for key in ("metrics", "profile", "scoreInfo", "direction", "range",
                    "mode", "gridCount", "duration", "viability", "signalInfo",
                    "mtf"):
            assert key in payload

    def test_payload_includes_daily_weekly_closes(self, patched_io):
        payload = refresh_data.refresh_one("BTC/USDT")
        mtf = payload["mtf"]
        assert len(mtf["dailyCloses"]) == refresh_data.CFG["KLINES_DAILY"]
        assert len(mtf["weeklyCloses"]) == refresh_data.CFG["KLINES_WEEKLY"]
        assert all(isinstance(c, float) for c in mtf["dailyCloses"])

    def test_upserts_cache_with_consistent_values(self, patched_io):
        payload = refresh_data.refresh_one("ETH/USDT")
        # The values written to the cache must match the returned payload
        assert patched_io["symbol"] == "ETH/USDT"
        assert patched_io["score"] == payload["scoreInfo"]["score"]
        assert patched_io["direction"] == payload["direction"]["type"]
        assert patched_io["price"] == payload["metrics"]["currClose"]

    def test_returns_none_when_no_klines(self):
        with patch.object(refresh_data, "fetch_klines", return_value=[]), \
             patch.object(refresh_data, "fetch_oi", return_value=OIData()), \
             patch.object(refresh_data, "fetch_funding", return_value=0.0), \
             patch.object(refresh_data, "upsert_metrics") as mock_upsert:
            assert refresh_data.refresh_one("DEAD/USDT") is None
            mock_upsert.assert_not_called()

    def test_grid_count_is_positive_integer(self, patched_io):
        payload = refresh_data.refresh_one("SOL/USDT")
        gc = payload["gridCount"]
        # calc_recommended_grid_count returns {recommended, min, max}.
        assert isinstance(gc["recommended"], int)
        assert gc["recommended"] >= 1


class TestBuildMtf:
    def test_returns_closes_for_both_timeframes(self):
        with patch.object(refresh_data, "fetch_klines",
                          side_effect=lambda s, tf, n: _raw_klines(n)):
            mtf = refresh_data.build_mtf("BTC/USDT")
        assert len(mtf["dailyCloses"]) == refresh_data.CFG["KLINES_DAILY"]
        assert len(mtf["weeklyCloses"]) == refresh_data.CFG["KLINES_WEEKLY"]

    def test_empty_lists_when_fetch_fails(self):
        """A daily/weekly fetch miss degrades to empty lists, never raises —
        so the regime layer can fall back to UNKNOWN without blanking the card."""
        with patch.object(refresh_data, "fetch_klines", return_value=[]):
            mtf = refresh_data.build_mtf("DEAD/USDT")
        assert mtf == {"dailyCloses": [], "weeklyCloses": []}


class TestMain:
    def test_returns_zero_when_at_least_one_pair_ok(self):
        with patch.object(refresh_data, "init_db"), \
             patch.object(refresh_data, "refresh_one", return_value={"ok": True}) as r:
            rc = refresh_data.main(["BTC/USDT", "ETH/USDT"])
        assert rc == 0
        assert r.call_count == 2

    def test_returns_one_when_all_pairs_fail(self):
        with patch.object(refresh_data, "init_db"), \
             patch.object(refresh_data, "refresh_one", return_value=None):
            assert refresh_data.main(["BTC/USDT"]) == 1

    def test_exception_in_one_pair_does_not_abort_others(self):
        calls = []

        def _side_effect(sym):
            calls.append(sym)
            if sym == "BAD/USDT":
                raise RuntimeError("boom")
            return {"ok": True}

        with patch.object(refresh_data, "init_db"), \
             patch.object(refresh_data, "refresh_one", side_effect=_side_effect):
            rc = refresh_data.main(["BAD/USDT", "GOOD/USDT"])
        # GOOD still processed after BAD raised → overall success
        assert rc == 0
        assert calls == ["BAD/USDT", "GOOD/USDT"]

    def test_defaults_to_config_pairs(self):
        with patch.object(refresh_data, "init_db"), \
             patch.object(refresh_data, "refresh_one", return_value={"ok": True}) as r, \
             patch.object(refresh_data, "DEFAULT_PAIRS", ["AAA/USDT", "BBB/USDT"]):
            refresh_data.main()
        assert r.call_count == 2
