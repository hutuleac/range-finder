"""Tests for pionex_client.py — auth, signing, and API calls."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pionex_client import PionexClient


@pytest.fixture
def client():
    return PionexClient(api_key="test-key", api_secret="test-secret")


@pytest.fixture
def unconfigured_client():
    return PionexClient(api_key="", api_secret="")


# ── configured property ───────────────────────────────────────────────

class TestConfigured:
    def test_true_when_both_keys_set(self, client):
        assert client.configured is True

    def test_false_when_no_key(self):
        assert PionexClient(api_key="", api_secret="secret").configured is False

    def test_false_when_no_secret(self):
        assert PionexClient(api_key="key", api_secret="").configured is False

    def test_false_when_both_empty(self, unconfigured_client):
        assert unconfigured_client.configured is False


# ── _sign ─────────────────────────────────────────────────────────────

class TestSign:
    def test_returns_headers_and_qs(self, client):
        headers, qs = client._sign("GET", "/api/v1/test", {"foo": "bar"})
        assert "PIONEX-KEY" in headers
        assert "PIONEX-SIGNATURE" in headers
        assert "foo=bar" in qs

    def test_headers_contain_correct_key(self, client):
        headers, _ = client._sign("GET", "/api/v1/test", {})
        assert headers["PIONEX-KEY"] == "test-key"

    def test_signature_is_hex_string(self, client):
        headers, _ = client._sign("GET", "/api/v1/test", {})
        sig = headers["PIONEX-SIGNATURE"]
        # HMAC-SHA256 produces 64-char hex
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_params_sorted_alphabetically_in_qs(self, client):
        _, qs = client._sign("GET", "/api/v1/test", {"z": "last", "a": "first"})
        # 'a' should appear before 'z' in query string
        assert qs.index("a=") < qs.index("z=")

    def test_timestamp_injected_into_params(self, client):
        params = {}
        _, qs = client._sign("GET", "/api/v1/test", params)
        assert "timestamp=" in qs
        assert "timestamp" in params


# ── _get ──────────────────────────────────────────────────────────────

class TestGet:
    @patch("pionex_client.requests.get")
    def test_returns_data_on_success(self, mock_get, client):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": True, "data": {"results": [{"buOrderType": "spot_grid"}]}},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        result = client._get("/api/v1/bot/orders", {"status": "running"})
        assert "results" in result

    @patch("pionex_client.requests.get")
    def test_returns_empty_on_http_error(self, mock_get, client):
        from requests import RequestException
        mock_get.return_value.raise_for_status.side_effect = RequestException("timeout")
        mock_get.return_value.status_code = 503
        result = client._get("/api/v1/test")
        assert result == {}
        assert client.last_error != ""

    @patch("pionex_client.requests.get")
    def test_returns_empty_on_api_error(self, mock_get, client):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": False, "code": "INVALID_KEY", "message": "bad key"},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        result = client._get("/api/v1/test")
        assert result == {}
        assert "INVALID_KEY" in client.last_error


# ── list_running_bots ─────────────────────────────────────────────────

class TestListRunningBots:
    def test_unconfigured_returns_empty_list(self, unconfigured_client):
        result = unconfigured_client.list_running_bots()
        assert result == []
        assert unconfigured_client.last_error != ""

    @patch("pionex_client.requests.get")
    def test_filters_spot_grid_only(self, mock_get, client):
        all_bots = [
            {"buOrderType": "spot_grid", "id": "1"},
            {"buOrderType": "futures_grid", "id": "2"},
            {"buOrderType": "spot_grid", "id": "3"},
        ]
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": True, "data": {"results": all_bots}},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        result = client.list_running_bots()
        assert len(result) == 2
        assert all(b["buOrderType"] == "spot_grid" for b in result)

    @patch("pionex_client.requests.get")
    def test_returns_empty_list_when_api_fails(self, mock_get, client):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": False, "code": "ERR", "message": "fail"},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        result = client.list_running_bots()
        assert result == []


# ── get_bot_detail ────────────────────────────────────────────────────

class TestGetBotDetail:
    def test_unconfigured_returns_empty_dict(self, unconfigured_client):
        result = unconfigured_client.get_bot_detail("order-123")
        assert result == {}

    @patch("pionex_client.requests.get")
    def test_returns_detail_on_success(self, mock_get, client):
        detail = {"buOrderId": "order-123", "status": "running"}
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": True, "data": detail},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        result = client.get_bot_detail("order-123")
        assert result == detail
