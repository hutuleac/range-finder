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
            return val
    except Exception:
        pass
    return os.getenv(name, "")


class PionexClient:

    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key or _get_key("PIONEX_API_KEY")
        self.api_secret = api_secret or _get_key("PIONEX_API_SECRET")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _sign(self, method: str, path: str, query: str, body: str = "") -> dict:
        ts = str(int(time.time() * 1000))
        if "timestamp=" not in query:
            query = f"timestamp={ts}&{query}" if query else f"timestamp={ts}"
        msg = f"{method}{path}?{query}"
        if body:
            msg += body
        sig = hmac.new(
            self.api_secret.encode(), msg.encode(), hashlib.sha256,
        ).hexdigest()
        return {
            "PIONEX-KEY": self.api_key,
            "PIONEX-SIGNATURE": sig,
            "Content-Type": "application/json",
        }, query

    def _get(self, path: str, params: dict | None = None) -> dict:
        params = params or {}
        qs = urlencode({k: v for k, v in params.items() if v is not None})
        headers, signed_qs = self._sign("GET", path, qs)
        url = f"{_BASE}{path}?{signed_qs}"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("result"):
            log.warning("Pionex API error: %s %s", data.get("code"), data.get("message"))
            return {}
        return data.get("data", {})

    def list_running_bots(self) -> list[dict]:
        if not self.configured:
            return []
        data = self._get("/api/v1/bot/orders", {
            "status": "running",
            "orderType": "spotGrid",
        })
        return data.get("orders", [])

    def get_bot_detail(self, order_id: str) -> dict:
        if not self.configured:
            return {}
        return self._get("/api/v1/bot/orders/spotGrid/order", {
            "buOrderId": order_id,
        })
