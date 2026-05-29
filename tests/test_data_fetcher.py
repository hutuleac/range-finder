"""Tests for data_fetcher.py — validate_pair."""
from __future__ import annotations

from unittest.mock import patch

from data_fetcher import validate_pair


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
