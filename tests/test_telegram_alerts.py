"""Tests for telegram_alerts.py — deduplication, formatting, send logic."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

import telegram_alerts as ta
from telegram_alerts import (
    _cache_key,
    _mark_sent,
    _should_send,
    is_configured,
    send_bot_alert,
    send_signal_alert,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Reset in-memory dedup cache before every test."""
    ta._sent_cache.clear()
    yield
    ta._sent_cache.clear()


# ── _cache_key ────────────────────────────────────────────────────────

class TestCacheKey:
    def test_format_is_symbol_colon_action(self):
        assert _cache_key("BTC/USDT", "CLOSE_NOW") == "BTC/USDT:CLOSE_NOW"

    def test_different_symbols_different_keys(self):
        assert _cache_key("BTC/USDT", "HOLD") != _cache_key("ETH/USDT", "HOLD")

    def test_different_actions_different_keys(self):
        assert _cache_key("BTC/USDT", "HOLD") != _cache_key("BTC/USDT", "CLOSE_NOW")


# ── _should_send / _mark_sent ─────────────────────────────────────────

class TestShouldSendMarkSent:
    def test_fresh_key_should_send(self):
        assert _should_send("BTC/USDT", "WARNING") is True

    def test_just_sent_should_not_send(self):
        _mark_sent("BTC/USDT", "WARNING")
        assert _should_send("BTC/USDT", "WARNING") is False

    def test_expired_cooldown_should_send(self):
        ta._sent_cache[_cache_key("BTC/USDT", "WARNING")] = time.time() - 1801
        assert _should_send("BTC/USDT", "WARNING") is True

    def test_mark_sent_updates_cache(self):
        _mark_sent("ETH/USDT", "TAKE_PROFIT")
        key = _cache_key("ETH/USDT", "TAKE_PROFIT")
        assert key in ta._sent_cache
        assert ta._sent_cache[key] == pytest.approx(time.time(), abs=2.0)

    def test_different_symbols_independent(self):
        _mark_sent("BTC/USDT", "WARNING")
        assert _should_send("ETH/USDT", "WARNING") is True


# ── send_bot_alert ────────────────────────────────────────────────────

class TestSendBotAlert:
    def _advice(self, action: str, grid_pct: float = 1.0) -> dict:
        return {
            "recommendation": {"action": action, "reason": "test reason"},
            "position": {"pct": 45.0},
            "profit": {"gridProfitPct": grid_pct, "realizedPct": 0.5},
            "restart": None,
        }

    def test_non_alertable_action_returns_false(self):
        assert send_bot_alert("BTC/USDT", self._advice("HOLD")) is False
        assert send_bot_alert("BTC/USDT", self._advice("WATCH")) is False

    def test_cooldown_blocks_resend(self):
        _mark_sent("BTC/USDT", "CLOSE_NOW")
        assert send_bot_alert("BTC/USDT", self._advice("CLOSE_NOW")) is False

    @patch("telegram_alerts._send_message", return_value=True)
    def test_alertable_action_sends(self, mock_send):
        result = send_bot_alert("BTC/USDT", self._advice("CLOSE_NOW"))
        assert result is True
        mock_send.assert_called_once()

    @patch("telegram_alerts._send_message", return_value=True)
    def test_sent_cache_updated_after_send(self, mock_send):
        send_bot_alert("ETH/USDT", self._advice("WARNING"))
        assert _should_send("ETH/USDT", "WARNING") is False

    @patch("telegram_alerts._send_message", return_value=False)
    def test_failed_send_does_not_update_cache(self, mock_send):
        send_bot_alert("BTC/USDT", self._advice("TAKE_PROFIT"))
        assert _should_send("BTC/USDT", "TAKE_PROFIT") is True

    @patch("telegram_alerts._send_message", return_value=True)
    def test_restart_included_in_message_when_present(self, mock_send):
        advice = self._advice("CLOSE_NOW")
        advice["restart"] = {
            "direction": "Long", "rangeLow": 90.0, "rangeHigh": 110.0,
            "rangeWidthPct": 20.0, "grids": 10, "mode": "Arithmetic", "duration": "1-3 days",
        }
        result = send_bot_alert("BTC/USDT", advice)
        assert result is True
        call_text = mock_send.call_args[0][0]
        assert "Restart" in call_text


# ── send_signal_alert ─────────────────────────────────────────────────

class TestSendSignalAlert:
    def _signal_info(self, urgency: str, sig_type: str = "SQUEEZE_PLAY") -> dict:
        return {
            "score": 8.5,
            "label": "STRONG SETUP",
            "urgency": {"level": urgency},
            "signal_type": {"type": sig_type, "direction": "Long", "reason": "test"},
            "eta": {"label": "1-3 hours"},
        }

    def test_non_urgent_returns_false(self):
        assert send_signal_alert("BTC/USDT", self._signal_info("SOON")) is False
        assert send_signal_alert("BTC/USDT", self._signal_info("WATCH")) is False

    @patch("telegram_alerts._send_message", return_value=True)
    def test_urgent_sends(self, mock_send):
        result = send_signal_alert("BTC/USDT", self._signal_info("URGENT"))
        assert result is True
        mock_send.assert_called_once()

    def test_cooldown_blocks_urgent_resend(self):
        ta._sent_cache[_cache_key("BTC/USDT", "signal:SQUEEZE_PLAY")] = time.time()
        assert send_signal_alert("BTC/USDT", self._signal_info("URGENT")) is False


# ── _send_message (network layer) ────────────────────────────────────

class TestSendMessage:
    @patch("telegram_alerts.requests.post")
    def test_returns_true_on_200(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        # Patch config to provide valid credentials
        with patch("telegram_alerts._get_config", return_value=("tok", "chat")):
            result = ta._send_message("hello")
        assert result is True

    @patch("telegram_alerts.requests.post")
    def test_returns_false_on_non_200(self, mock_post):
        mock_post.return_value = MagicMock(status_code=429, text="Rate limited")
        with patch("telegram_alerts._get_config", return_value=("tok", "chat")):
            result = ta._send_message("hello")
        assert result is False

    @patch("telegram_alerts.requests.post")
    def test_returns_false_on_request_exception(self, mock_post):
        import requests as req
        mock_post.side_effect = req.RequestException("network error")
        with patch("telegram_alerts._get_config", return_value=("tok", "chat")):
            result = ta._send_message("hello")
        assert result is False

    def test_returns_false_when_not_configured(self):
        with patch("telegram_alerts._get_config", return_value=("", "")):
            result = ta._send_message("hello")
        assert result is False


# ── is_configured ─────────────────────────────────────────────────────

class TestIsConfigured:
    def test_true_when_both_set(self):
        with patch("telegram_alerts._get_config", return_value=("token", "chat123")):
            assert is_configured() is True

    def test_false_when_token_missing(self):
        with patch("telegram_alerts._get_config", return_value=("", "chat123")):
            assert is_configured() is False

    def test_false_when_chat_missing(self):
        with patch("telegram_alerts._get_config", return_value=("token", "")):
            assert is_configured() is False

    def test_false_when_both_missing(self):
        with patch("telegram_alerts._get_config", return_value=("", "")):
            assert is_configured() is False
