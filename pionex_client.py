"""Pionex Bot API client — read-only access to spot grid bots."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from urllib.parse import urlencode

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
        # Sort params alphabetically for consistent signature
        sorted_params = sorted(params.items())
        qs = urlencode(sorted_params)
        # Signature: METHOD + PATH + ? + QUERY_STRING
        sign_str = f"{method}{path}?{qs}"
        sig = hmac.new(
            self.api_secret.encode(), sign_str.encode(), hashlib.sha256,
        ).hexdigest()
        headers = {
            "PIONEX-KEY": self.api_key,
            "PIONEX-SIGNATURE": sig,
            "Content-Type": "application/json",
        }
        return headers, qs

    def _get(self, path: str, params: dict | None = None) -> dict:
        self.last_error = ""
        params = {k: v for k, v in (params or {}).items() if v is not None}
        headers, qs = self._sign("GET", path, params)
        url = f"{_BASE}{path}?{qs}"
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
        # API param is buOrderTypes (plural), value is spot_grid (underscore)
        data = self._get("/api/v1/bot/orders", {
            "status": "running",
            "buOrderTypes": "spot_grid",
        })
        return data.get("orders", [])

    def get_bot_detail(self, order_id: str) -> dict:
        if not self.configured:
            return {}
        return self._get("/api/v1/bot/orders/spotGrid/order", {
            "buOrderId": order_id,
        })
