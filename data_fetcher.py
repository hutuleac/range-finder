"""Pyonex data fetcher — OKX swap primary, Bybit linear fallback, Binance USD-M last.

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
_okx: ccxt.Exchange | None = None


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


def _get_okx() -> ccxt.Exchange:
    global _okx
    if _okx is None:
        _okx = ccxt.okx({
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        })
    return _okx


def _to_okx_symbol(symbol: str) -> str:
    """BTC/USDT -> BTC/USDT:USDT (OKX linear swap format)."""
    base, quote = symbol.split("/")
    return f"{base}/{quote}:{quote}"


# symbol -> exchange name that last succeeded, so we skip repeated Binance misses
_source_cache: dict[str, str] = {}

# set True on first Binance 451 — skips Binance for all subsequent calls
_binance_blocked: bool = False


def _is_geo_blocked(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "451" in msg or "restricted location" in msg


# ─────────────────────────────────────────────────────────────────────
#  Klines — always returns Binance-style 12-col lists
#  For Bybit we pad with 0 in columns we don't have (notably index 9 = taker_buy_base_vol).
#  Downstream CVD falls back to the open/close heuristic when buy vol is 0.
# ─────────────────────────────────────────────────────────────────────
def _binance_raw_klines(symbol: str, timeframe: str, limit: int) -> list[list] | None:
    global _binance_blocked
    if _binance_blocked:
        return None
    ex = _get_binance()
    market = symbol.replace("/", "").upper()
    try:
        raw = ex.fapiPublicGetKlines({"symbol": market, "interval": timeframe, "limit": limit})
        return raw if isinstance(raw, list) else None
    except Exception as e:  # noqa: BLE001
        if _is_geo_blocked(e):
            _binance_blocked = True
            log.warning("Binance geo-blocked (451) — switching to Bybit-only for this process")
        else:
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


def _okx_ohlcv(symbol: str, timeframe: str, limit: int) -> list[list] | None:
    try:
        ex = _get_okx()
        ohlcv = ex.fetch_ohlcv(_to_okx_symbol(symbol), timeframe=timeframe, limit=limit)
        if not ohlcv:
            return None
        return [
            [row[0], row[1], row[2], row[3], row[4], row[5], 0, 0, 0, 0, 0, 0]
            for row in ohlcv
        ]
    except Exception as e:  # noqa: BLE001
        log.info("okx ohlcv %s: %s", symbol, e)
        return None


def fetch_klines(symbol: str, timeframe: str, limit: int) -> list[list]:
    """Return Binance-shape klines. OKX primary, Bybit fallback, Binance last."""
    cached = _source_cache.get(symbol)
    order: list[str] = (
        [cached, *(s for s in ["okx", "bybit", "binance"] if s != cached)]
        if cached else ["okx", "bybit", "binance"]
    )
    fetchers = {
        "binance": lambda: _binance_raw_klines(symbol, timeframe, limit),
        "bybit": lambda: _bybit_ohlcv(symbol, timeframe, limit),
        "okx": lambda: _okx_ohlcv(symbol, timeframe, limit),
    }
    for src in order:
        raw = fetchers[src]()
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
    global _binance_blocked
    if _binance_blocked:
        return None
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
        if _is_geo_blocked(e):
            _binance_blocked = True
            log.warning("Binance geo-blocked (451) — switching to Bybit-only for this process")
        else:
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


def _okx_oi(symbol: str) -> OIData | None:
    try:
        ex = _get_okx()
        hist = ex.fetch_open_interest_history(
            _to_okx_symbol(symbol), "4h", limit=CFG["OI_LIMIT"]
        )
        if not hist or len(hist) < 2:
            return None
        oi_now = float(hist[-1]["openInterestAmount"])
        oi_old = float(hist[0]["openInterestAmount"])
        change = (oi_now - oi_old) / oi_old * 100 if oi_old > 0 else 0.0
        return OIData(oiNow=oi_now, oiChange=change)
    except Exception as e:  # noqa: BLE001
        log.info("okx OI %s: %s", symbol, e)
        return None


def fetch_oi(symbol: str) -> OIData:
    cached = _source_cache.get(symbol)
    order = (
        [cached, *(s for s in ["okx", "bybit", "binance"] if s != cached)]
        if cached else ["okx", "bybit", "binance"]
    )
    fetchers = {
        "binance": lambda: _binance_oi(symbol),
        "bybit": lambda: _bybit_oi(symbol),
        "okx": lambda: _okx_oi(symbol),
    }
    for src in order:
        oi = fetchers[src]()
        if oi is not None:
            return oi
    return OIData()


# ─────────────────────────────────────────────────────────────────────
#  Funding rate (most recent)
# ─────────────────────────────────────────────────────────────────────
def fetch_funding(symbol: str) -> float:
    global _binance_blocked
    cached = _source_cache.get(symbol)
    order = (
        [cached, *(s for s in ["okx", "bybit", "binance"] if s != cached)]
        if cached else ["okx", "bybit", "binance"]
    )
    for src in order:
        if src == "binance" and _binance_blocked:
            continue
        try:
            ex = {"binance": _get_binance, "bybit": _get_bybit, "okx": _get_okx}[src]()
            sym = _to_okx_symbol(symbol) if src == "okx" else symbol
            r = ex.fetch_funding_rate(sym)
            rate = r.get("fundingRate")
            if rate is not None:
                return float(rate) * 100.0
        except Exception as e:  # noqa: BLE001
            if src == "binance" and _is_geo_blocked(e):
                _binance_blocked = True
                log.warning("Binance geo-blocked (451) — switching to Bybit-only for this process")
            else:
                log.info("%s funding %s: %s", src, symbol, e)
    return 0.0


# ─────────────────────────────────────────────────────────────────────
#  Pionex (Phase 4 stub — read-only)
# ─────────────────────────────────────────────────────────────────────
def fetch_pionex_balance() -> dict:
    """Stub — real implementation lands in phases/phase4_pionex_monitor.py."""
    return {"stub": True, "balances": [], "bots": []}
