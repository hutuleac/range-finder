"""Pionex Bot API client — read-only access to spot grid bots.

Auth reference: https://www.pionex.com/docs/api-docs/bot-api/general-info/authentication
Signing: sort params alphabetically, join with &, prepend METHOD+PATH+?, HMAC SHA256.
Values in the signature string must NOT be URL-encoded.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time

import requests

log = logging.getLogger("pyonex.pionex")

_BASE = "https://api.pionex.com"


def _get_key(name: str) -> str:
    try:
        import streamlit as st
        val = st.secrets.get(name, "")
        if val:
            return str(val)
    except Exception:
        pass
    return os.getenv(name, "")


class PionexClient:

    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key or _get_key("PIONEX_API_KEY")
        self.api_secret = api_secret or _get_key("PIONEX_API_SECRET")
        self.last_error: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _sign(self, method: str, path: str, params: dict) -> tuple[dict, str]:
        ts = str(int(time.time() * 1000))
        params["timestamp"] = ts
        # Sort alphabetically by key, join as key=value with &
        # Per docs: "signature related value must not be URL-encoded"
        sorted_keys = sorted(params.keys())
        qs = "&".join(f"{k}={params[k]}" for k in sorted_keys)
        # Sign string: METHOD + PATH + ? + sorted_query (no space, no encoding)
        sign_str = f"{method}{path}?{qs}"
        sig = hmac.new(
            self.api_secret.encode(), sign_str.encode(), hashlib.sha256,
        ).hexdigest()
        headers = {
            "PIONEX-KEY": self.api_key,
            "PIONEX-SIGNATURE": sig,
        }
        return headers, qs

    def _get(self, path: str, params: dict | None = None) -> dict:
        self.last_error = ""
        params = {k: v for k, v in (params or {}).items() if v is not None}
        headers, qs = self._sign("GET", path, params)
        url = f"{_BASE}{path}?{qs}"
        log.debug("Pionex GET %s", url)
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            self.last_error = f"HTTP error: {e}"
            log.warning("Pionex request failed: %s", e)
            return {}
        data = resp.json()
        if not data.get("result"):
            self.last_error = f"{data.get('code', 'UNKNOWN')}: {data.get('message', 'No message')}"
            log.warning("Pionex API error: %s", self.last_error)
            return {}
        return data.get("data", {})

    def list_running_bots(self) -> list[dict]:
        if not self.configured:
            self.last_error = "API keys not configured"
            return []
        # First try: fetch all running bots (no type filter), filter client-side
        data = self._get("/api/v1/bot/orders", {"status": "running"})
        all_bots = data.get("results", [])
        # Filter to spot_grid only
        return [b for b in all_bots if b.get("buOrderType") == "spot_grid"]

    def get_bot_detail(self, order_id: str) -> dict:
        if not self.configured:
            return {}
        return self._get("/api/v1/bot/orders/spotGrid/order", {
            "buOrderId": order_id,
        })

    def validate_symbol(self, symbol: str) -> bool | None:
        """Check if a symbol is listed on Pionex. No authentication required.

        Returns True if found, False if not found, None on network/API error.
        Note: symbol format uses '_' separator (e.g. BTC_USDT).
        Response shape: {"result": true, "data": {"tickers": [...]}}
        """
        try:
            resp = requests.get(
                f"{_BASE}/api/v1/market/tickers",
                params={"symbol": symbol.replace("/", "_")},
                timeout=10,
            )
            data = resp.json()
            if not data.get("result"):
                return False
            tickers = data.get("data", {})
            if isinstance(tickers, dict):
                tickers = tickers.get("tickers", [])
            return bool(tickers)
        except requests.RequestException:
            return None
