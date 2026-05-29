"""Tests for data_fetcher.py — klines/OI/funding fallback chain + validate_pair.

The module talks to ccxt exchanges through three lazy getters
(_get_okx / _get_bybit / _get_binance). We patch those getters to return
MagicMock exchanges so no network I/O happens, and exercise the
OKX→Bybit→Binance fallback ordering, geo-block handling, and response parsing.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import data_fetcher as df
from data_fetcher import (
    _is_geo_blocked,
    _to_okx_symbol,
    fetch_funding,
    fetch_klines,
    fetch_oi,
    fetch_pionex_balance,
    validate_pair,
)
from indicators import OIData


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Each test starts with empty source cache and an unblocked Binance.

    These are module-level globals, so without a reset one test's cached
    source or geo-block window would leak into the next.
    """
    df._source_cache.clear()
    df._binance_blocked_until = 0.0
    yield
    df._source_cache.clear()
    df._binance_blocked_until = 0.0


# Binance-shape OHLCV row helper: [ts,o,h,l,c,v, close_ts,qv,trades, buy_base,buy_quote, ignore]
def _ccxt_ohlcv_row(ts=1, o=100, h=101, lo=99, c=100.5, v=500):
    return [ts, o, h, lo, c, v]


# ── pure helpers ──────────────────────────────────────────────────────

class TestPureHelpers:
    def test_to_okx_symbol_appends_quote_suffix(self):
        assert _to_okx_symbol("BTC/USDT") == "BTC/USDT:USDT"
        assert _to_okx_symbol("ETH/USDC") == "ETH/USDC:USDC"

    @pytest.mark.parametrize("msg,expected", [
        ("HTTP 451 restricted", True),
        ("Service unavailable from a restricted location", True),
        ("connection reset", False),
        ("timeout", False),
    ], ids=["451-code", "restricted-text", "generic", "timeout"])
    def test_is_geo_blocked(self, msg, expected):
        assert _is_geo_blocked(Exception(msg)) is expected


# ── fetch_klines ──────────────────────────────────────────────────────

class TestFetchKlines:
    def test_okx_primary_success_and_caches_source(self):
        ex = MagicMock()
        ex.fetch_ohlcv.return_value = [_ccxt_ohlcv_row()]
        with patch.object(df, "_get_okx", return_value=ex):
            rows = fetch_klines("BTC/USDT", "4h", 1)
        assert len(rows) == 1
        # Padded to 12-col Binance shape
        assert len(rows[0]) == 12
        assert df._source_cache["BTC/USDT"] == "okx"

    def test_falls_back_to_bybit_when_okx_empty(self):
        okx = MagicMock()
        okx.fetch_ohlcv.return_value = []
        bybit = MagicMock()
        bybit.fetch_ohlcv.return_value = [_ccxt_ohlcv_row()]
        with patch.object(df, "_get_okx", return_value=okx), \
             patch.object(df, "_get_bybit", return_value=bybit):
            rows = fetch_klines("ETH/USDT", "4h", 1)
        assert len(rows) == 1
        assert df._source_cache["ETH/USDT"] == "bybit"

    def test_cached_source_is_tried_first(self):
        df._source_cache["SOL/USDT"] = "bybit"
        bybit = MagicMock()
        bybit.fetch_ohlcv.return_value = [_ccxt_ohlcv_row()]
        okx = MagicMock()
        with patch.object(df, "_get_okx", return_value=okx), \
             patch.object(df, "_get_bybit", return_value=bybit):
            fetch_klines("SOL/USDT", "4h", 1)
        # OKX never consulted because cached bybit answered first
        okx.fetch_ohlcv.assert_not_called()

    def test_returns_empty_when_all_sources_fail(self):
        okx = MagicMock(); okx.fetch_ohlcv.return_value = []
        bybit = MagicMock(); bybit.fetch_ohlcv.return_value = []
        binance = MagicMock(); binance.fapiPublicGetKlines.return_value = []
        with patch.object(df, "_get_okx", return_value=okx), \
             patch.object(df, "_get_bybit", return_value=bybit), \
             patch.object(df, "_get_binance", return_value=binance):
            assert fetch_klines("FAKE/USDT", "4h", 1) == []

    def test_bybit_exception_is_swallowed(self):
        okx = MagicMock(); okx.fetch_ohlcv.return_value = []
        bybit = MagicMock(); bybit.fetch_ohlcv.side_effect = Exception("boom")
        binance = MagicMock(); binance.fapiPublicGetKlines.return_value = [
            [1, "100", "101", "99", "100.5", "500", 0, 0, 0, "300", 0, 0]
        ]
        with patch.object(df, "_get_okx", return_value=okx), \
             patch.object(df, "_get_bybit", return_value=bybit), \
             patch.object(df, "_get_binance", return_value=binance):
            rows = fetch_klines("X/USDT", "4h", 1)
        assert len(rows) == 1
        assert df._source_cache["X/USDT"] == "binance"

    def test_binance_geo_block_sets_window_and_returns_empty(self):
        okx = MagicMock(); okx.fetch_ohlcv.return_value = []
        bybit = MagicMock(); bybit.fetch_ohlcv.return_value = []
        binance = MagicMock()
        binance.fapiPublicGetKlines.side_effect = Exception("HTTP 451 restricted location")
        with patch.object(df, "_get_okx", return_value=okx), \
             patch.object(df, "_get_bybit", return_value=bybit), \
             patch.object(df, "_get_binance", return_value=binance):
            assert fetch_klines("Y/USDT", "4h", 1) == []
        assert df._binance_blocked_until > 0  # block window armed


# ── fetch_oi ──────────────────────────────────────────────────────────

class TestFetchOI:
    def test_okx_oi_parses_change(self):
        ex = MagicMock()
        ex.fetch_open_interest_history.return_value = [
            {"openInterestAmount": 100.0},
            {"openInterestAmount": 110.0},
        ]
        with patch.object(df, "_get_okx", return_value=ex):
            oi = fetch_oi("BTC/USDT")
        assert oi.oiNow == 110.0
        assert oi.oiChange == pytest.approx(10.0)

    def test_bybit_oi_newest_first_ordering(self):
        okx = MagicMock(); okx.fetch_open_interest_history.return_value = []
        bybit = MagicMock()
        bybit.publicGetV5MarketOpenInterest.return_value = {
            "result": {"list": [
                {"openInterest": "120"},   # newest
                {"openInterest": "100"},   # oldest
            ]}
        }
        with patch.object(df, "_get_okx", return_value=okx), \
             patch.object(df, "_get_bybit", return_value=bybit):
            oi = fetch_oi("ETH/USDT")
        assert oi.oiNow == 120.0
        assert oi.oiChange == pytest.approx(20.0)

    def test_insufficient_history_skips_source(self):
        okx = MagicMock()
        okx.fetch_open_interest_history.return_value = [{"openInterestAmount": 100.0}]
        bybit = MagicMock(); bybit.publicGetV5MarketOpenInterest.return_value = {"result": {"list": []}}
        binance = MagicMock(); binance.fapiDataGetOpenInterestHist.return_value = []
        with patch.object(df, "_get_okx", return_value=okx), \
             patch.object(df, "_get_bybit", return_value=bybit), \
             patch.object(df, "_get_binance", return_value=binance):
            oi = fetch_oi("Z/USDT")
        assert oi == OIData()  # all sources exhausted → default

    def test_returns_default_when_all_fail(self):
        okx = MagicMock(); okx.fetch_open_interest_history.side_effect = Exception("x")
        bybit = MagicMock(); bybit.publicGetV5MarketOpenInterest.side_effect = Exception("x")
        binance = MagicMock(); binance.fapiDataGetOpenInterestHist.side_effect = Exception("x")
        with patch.object(df, "_get_okx", return_value=okx), \
             patch.object(df, "_get_bybit", return_value=bybit), \
             patch.object(df, "_get_binance", return_value=binance):
            assert fetch_oi("BAD/USDT") == OIData()

    def test_binance_oi_geo_block_arms_window(self):
        okx = MagicMock(); okx.fetch_open_interest_history.return_value = []
        bybit = MagicMock(); bybit.publicGetV5MarketOpenInterest.return_value = {"result": {"list": []}}
        binance = MagicMock()
        binance.fapiDataGetOpenInterestHist.side_effect = Exception("451 restricted location")
        with patch.object(df, "_get_okx", return_value=okx), \
             patch.object(df, "_get_bybit", return_value=bybit), \
             patch.object(df, "_get_binance", return_value=binance):
            fetch_oi("Y/USDT")
        assert df._binance_blocked_until > 0


# ── fetch_funding ─────────────────────────────────────────────────────

class TestFetchFunding:
    def test_scales_rate_to_percent(self):
        ex = MagicMock()
        ex.fetch_funding_rate.return_value = {"fundingRate": 0.0001}
        with patch.object(df, "_get_okx", return_value=ex):
            assert fetch_funding("BTC/USDT") == pytest.approx(0.01)

    def test_falls_through_to_next_source_on_none_rate(self):
        okx = MagicMock(); okx.fetch_funding_rate.return_value = {"fundingRate": None}
        bybit = MagicMock(); bybit.fetch_funding_rate.return_value = {"fundingRate": 0.0002}
        with patch.object(df, "_get_okx", return_value=okx), \
             patch.object(df, "_get_bybit", return_value=bybit):
            assert fetch_funding("ETH/USDT") == pytest.approx(0.02)

    def test_skips_binance_while_blocked(self):
        import time
        df._binance_blocked_until = time.time() + 1000
        df._source_cache["SOL/USDT"] = "binance"  # would normally try binance first
        okx = MagicMock(); okx.fetch_funding_rate.return_value = {"fundingRate": 0.0003}
        binance = MagicMock()
        with patch.object(df, "_get_okx", return_value=okx), \
             patch.object(df, "_get_binance", return_value=binance):
            assert fetch_funding("SOL/USDT") == pytest.approx(0.03)
        binance.fetch_funding_rate.assert_not_called()

    def test_returns_zero_when_all_fail(self):
        okx = MagicMock(); okx.fetch_funding_rate.side_effect = Exception("x")
        bybit = MagicMock(); bybit.fetch_funding_rate.side_effect = Exception("x")
        binance = MagicMock(); binance.fetch_funding_rate.side_effect = Exception("x")
        with patch.object(df, "_get_okx", return_value=okx), \
             patch.object(df, "_get_bybit", return_value=bybit), \
             patch.object(df, "_get_binance", return_value=binance):
            assert fetch_funding("BAD/USDT") == 0.0


# ── misc ──────────────────────────────────────────────────────────────

class TestMisc:
    def test_pionex_balance_stub(self):
        out = fetch_pionex_balance()
        assert out["stub"] is True
        assert out["balances"] == [] and out["bots"] == []


class TestValidatePair:
    def test_returns_true_when_klines_non_empty(self):
        fake_candle = [[1, "100", "101", "99", "100.5", "500", 0, 0, 0, "300", 0, 0]]
        with patch("data_fetcher.fetch_klines", return_value=fake_candle):
            assert validate_pair("LINK/USDT") is True

    def test_returns_false_when_klines_empty(self):
        with patch("data_fetcher.fetch_klines", return_value=[]):
            assert validate_pair("FAKE/USDT") is False

    def test_returns_false_on_exception(self):
        with patch("data_fetcher.fetch_klines", side_effect=Exception("network")):
            assert validate_pair("BAD/USDT") is False
