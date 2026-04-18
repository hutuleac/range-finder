"""Pyonex data fetcher — Binance USD-M futures primary, Bybit linear fallback.

Exposes:
    fetch_klines(symbol, timeframe, limit) -> list[list]  (12-col Binance shape)
    fetch_oi(symbol) -> OIData
    fetch_funding(symbol) -> float  (percent, already scaled)
    fetch_pionex_balance() -> dict  (Phase 4 stub)
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Literal

import ccxt
from dotenv import load_dotenv

from config import CFG
from indicators import OIData

load_dotenv()
log = logging.getLogger("pyonex.data")

# ─────────────────────────────────────────────────────────────────────
#  Exchange clients — lazy singletons
# ─────────────────────────────────────────────────────────────────────
_binance: ccxt.Exchange | None = None
_bybit: ccxt.Exchange | None = None


def _get_binance() -> ccxt.Exchange:
    global _binance
    if _binance is None:
        _binance = ccxt.binanceusdm({
            "enableRateLimit": True,
            "apiKey": os.getenv("BINANCE_API_KEY") or None,
            "secret": os.getenv("BINANCE_API_SECRET") or None,
            "options": {"defaultType": "future"},
        })
    return _binance


def _get_bybit() -> ccxt.Exchange:
    global _bybit
    if _bybit is None:
        _bybit = ccxt.bybit({
            "enableRateLimit": True,
            "apiKey": os.getenv("BYBIT_API_KEY") or None,
            "secret": os.getenv("BYBIT_API_SECRET") or None,
            "options": {"defaultType": "linear"},
        })
    return _bybit


# symbol -> exchange name that last succeeded, so we skip repeated Binance misses
_source_cache: dict[str, str] = {}


# ─────────────────────────────────────────────────────────────────────
#  Klines — always returns Binance-style 12-col lists
#  For Bybit we pad with 0 in columns we don't have (notably index 9 = taker_buy_base_vol).
#  Downstream CVD falls back to the open/close heuristic when buy vol is 0.
# ─────────────────────────────────────────────────────────────────────
def _binance_raw_klines(symbol: str, timeframe: str, limit: int) -> list[list] | None:
    ex = _get_binance()
    # bypass unified API to keep the full 12-col array
    market = symbol.replace("/", "").upper()
    try:
        raw = ex.fapiPublicGetKlines({"symbol": market, "interval": timeframe, "limit": limit})
        return raw if isinstance(raw, list) else None
    except Exception as e:  # noqa: BLE001
        log.info("binance raw klines %s: %s", symbol, e)
        return None


def _bybit_ohlcv(symbol: str, timeframe: str, limit: int) -> list[list] | None:
    ex = _get_bybit()
    try:
        ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not ohlcv:
            return None
        # Pad to Binance 12-col shape: [ts, o, h, l, c, v, close_ts, qv, trades, buy_base, buy_quote, ignore]
        padded = [
            [row[0], row[1], row[2], row[3], row[4], row[5], 0, 0, 0, 0, 0, 0] for row in ohlcv
        ]
        return padded
    except Exception as e:  # noqa: BLE001
        log.info("bybit ohlcv %s: %s", symbol, e)
        return None


def fetch_klines(symbol: str, timeframe: str, limit: int) -> list[list]:
    """Return Binance-shape klines. Tries cached source first, falls back across."""
    key = f"{symbol}:{timeframe}"
    order: list[Literal["binance", "bybit"]] = ["binance", "bybit"]
    if _source_cache.get(symbol) == "bybit":
        order = ["bybit", "binance"]
    for src in order:
        raw = _binance_raw_klines(symbol, timeframe, limit) if src == "binance" \
              else _bybit_ohlcv(symbol, timeframe, limit)
        if raw:
            _source_cache[symbol] = src
            return raw
    log.warning("no klines for %s %s from any source", symbol, timeframe)
    return []


# ─────────────────────────────────────────────────────────────────────
#  Open Interest
#  Binance: /fapi/v1/openInterestHist   (period=4h, limit=42)
#  Bybit:   /v5/market/open-interest    (intervalTime=4h)
# ─────────────────────────────────────────────────────────────────────
def _binance_oi(symbol: str) -> OIData | None:
    try:
        ex = _get_binance()
        market = symbol.replace("/", "").upper()
        hist = ex.fapiDataGetOpenInterestHist({
            "symbol": market,
            "period": CFG["OI_PERIOD"],
            "limit": CFG["OI_LIMIT"],
        })
        if not hist or len(hist) < 2:
            return None
        oi_now = float(hist[-1]["sumOpenInterest"])
        oi_old = float(hist[0]["sumOpenInterest"])
        change = (oi_now - oi_old) / oi_old * 100 if oi_old > 0 else 0.0
        return OIData(oiNow=oi_now, oiChange=change)
    except Exception as e:  # noqa: BLE001
        log.info("binance OI %s: %s", symbol, e)
        return None


def _bybit_oi(symbol: str) -> OIData | None:
    try:
        ex = _get_bybit()
        market = symbol.replace("/", "").upper()
        resp = ex.publicGetV5MarketOpenInterest({
            "category": "linear",
            "symbol": market,
            "intervalTime": "4h",
            "limit": CFG["OI_LIMIT"],
        })
        items = (resp.get("result") or {}).get("list") or []
        if len(items) < 2:
            return None
        # Bybit returns newest first
        oi_now = float(items[0]["openInterest"])
        oi_old = float(items[-1]["openInterest"])
        change = (oi_now - oi_old) / oi_old * 100 if oi_old > 0 else 0.0
        return OIData(oiNow=oi_now, oiChange=change)
    except Exception as e:  # noqa: BLE001
        log.info("bybit OI %s: %s", symbol, e)
        return None


def fetch_oi(symbol: str) -> OIData:
    order: list[Literal["binance", "bybit"]] = ["binance", "bybit"]
    if _source_cache.get(symbol) == "bybit":
        order = ["bybit", "binance"]
    for src in order:
        oi = _binance_oi(symbol) if src == "binance" else _bybit_oi(symbol)
        if oi is not None:
            return oi
    return OIData()


# ─────────────────────────────────────────────────────────────────────
#  Funding rate (most recent)
# ─────────────────────────────────────────────────────────────────────
def fetch_funding(symbol: str) -> float:
    for src, getter in (("binance", _get_binance), ("bybit", _get_bybit)):
        try:
            ex = getter()
            r = ex.fetch_funding_rate(symbol)
            rate = r.get("fundingRate")
            if rate is not None:
                return float(rate) * 100.0  # to percent
        except Exception as e:  # noqa: BLE001
            log.info("%s funding %s: %s", src, symbol, e)
    return 0.0


# ─────────────────────────────────────────────────────────────────────
#  Pionex (Phase 4 stub — read-only)
# ─────────────────────────────────────────────────────────────────────
def fetch_pionex_balance() -> dict:
    """Stub — real implementation lands in phases/phase4_pionex_monitor.py."""
    return {"stub": True, "balances": [], "bots": []}
