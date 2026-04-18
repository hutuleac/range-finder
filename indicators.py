"""Pyonex indicators — faithful port of indicators.js.

All functions are pure. DataFrame layout expected:
    columns = ['Time', 'Open', 'High', 'Low', 'Close', 'Volume', 'BuyVol']
Time is UTC ms. BuyVol may be 0 when the source exchange does not expose
taker-buy volume; in that case CVD is approximated with a heuristic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from config import CFG


# ─────────────────────────────────────────────────────────────────────
#  Kline parsing
# ─────────────────────────────────────────────────────────────────────
def parse_klines(raw: list[list]) -> pd.DataFrame:
    """Parse Binance-style 12-element klines into DataFrame.

    Raw shape: [ts, o, h, l, c, vol, close_ts, quote_vol, trades,
                taker_buy_base_vol, taker_buy_quote_vol, ignore]
    """
    if not raw:
        return pd.DataFrame(columns=["Time", "Open", "High", "Low", "Close", "Volume", "BuyVol"])
    arr = np.asarray(raw, dtype=object)
    out = pd.DataFrame({
        "Time": arr[:, 0].astype(np.int64),
        "Open": arr[:, 1].astype(float),
        "High": arr[:, 2].astype(float),
        "Low": arr[:, 3].astype(float),
        "Close": arr[:, 4].astype(float),
        "Volume": arr[:, 5].astype(float),
        "BuyVol": arr[:, 9].astype(float) if arr.shape[1] > 9 else 0.0,
    })
    return out


# ─────────────────────────────────────────────────────────────────────
#  Core indicators (ported line-by-line from indicators.js)
# ─────────────────────────────────────────────────────────────────────
def calc_rsi(df: pd.DataFrame, period: int = 14) -> float:
    n = len(df)
    if n <= period:
        return 50.0
    closes = df["Close"].to_numpy()
    avg_g = 0.0
    avg_l = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d > 0:
            avg_g += d
        else:
            avg_l -= d
    avg_g /= period
    avg_l /= period
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
    if avg_l == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_g / avg_l)


def calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    n = len(df)
    if n < period + 1:
        return 0.0
    h = df["High"].to_numpy()
    l = df["Low"].to_numpy()
    c = df["Close"].to_numpy()
    tr_sum = 0.0
    for i in range(1, period + 1):
        tr_sum += max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr = tr_sum / period
    for i in range(period + 1, n):
        tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        atr = (atr * (period - 1) + tr) / period
    return atr


def calc_ema(df: pd.DataFrame, span: int) -> float:
    if df.empty:
        return 0.0
    k = 2.0 / (span + 1.0)
    closes = df["Close"].to_numpy()
    ema = closes[0]
    for i in range(1, len(closes)):
        ema = closes[i] * k + ema * (1.0 - k)
    return float(ema)


def calc_poc_avwap(df: pd.DataFrame, nbins: int = 15) -> dict:
    if df.empty:
        return {"poc": 0.0, "avwap": 0.0}
    closes = df["Close"].to_numpy()
    vols = df["Volume"].to_numpy()
    lo, hi = float(closes.min()), float(closes.max())
    sum_v = float(vols.sum())
    if lo == hi:
        avwap = float((closes * vols).sum() / sum_v) if sum_v > 0 else lo
        return {"poc": lo, "avwap": avwap}
    bsz = (hi - lo) / nbins
    bins = np.zeros(nbins)
    for price, v in zip(closes, vols):
        idx = int((price - lo) // bsz)
        if idx >= nbins:
            idx = nbins - 1
        bins[idx] += v
    poc_idx = int(bins.argmax())
    poc = lo + (poc_idx + 0.5) * bsz
    avwap = float((closes * vols).sum() / sum_v) if sum_v > 0 else poc
    return {"poc": float(poc), "avwap": avwap}


def calc_cvd(df: pd.DataFrame) -> float:
    """Cumulative Volume Delta. Uses BuyVol if present (Binance), else
    heuristic (up-bar = buy, down-bar = sell) for fallback exchanges."""
    if df.empty:
        return 0.0
    vols = df["Volume"].to_numpy()
    buy = df["BuyVol"].to_numpy()
    if float(buy.sum()) <= 0.0:
        closes = df["Close"].to_numpy()
        opens = df["Open"].to_numpy()
        # up candle: 0.55 of vol is buy; down: 0.45; flat: 0.50
        factor = np.where(closes > opens, 0.55, np.where(closes < opens, 0.45, 0.50))
        buy = vols * factor
    return float((buy - (vols - buy)).sum())


def calc_market_structure(df: pd.DataFrame, lookback: int = 20) -> Literal["Bullish", "Bearish", "Neutral"]:
    if len(df) < lookback + 2:
        return "Neutral"
    s = df.tail(lookback).reset_index(drop=True)
    n = len(s)

    def H(i: int) -> float:
        return float(s["High"].iloc[n - 1 - i])

    def L(i: int) -> float:
        return float(s["Low"].iloc[n - 1 - i])

    if H(0) > H(2) and H(2) > H(4) and L(0) > L(2) and L(2) > L(4):
        return "Bullish"
    if H(0) < H(2) and H(2) < H(4) and L(0) < L(2) and L(2) < L(4):
        return "Bearish"
    return "Neutral"


def calc_fvg(df: pd.DataFrame, max_gaps: int = 5) -> list[dict]:
    n = len(df)
    if n < 3:
        return []
    h = df["High"].to_numpy()
    l = df["Low"].to_numpy()
    last_close = float(df["Close"].iloc[-1])
    gaps: list[dict] = []
    for i in range(1, n - 1):
        # Bullish FVG
        if l[i + 1] > h[i - 1]:
            g_bot, g_top = float(h[i - 1]), float(l[i + 1])
            intact = True
            for j in range(i + 1, n):
                if l[j] < g_bot:
                    intact = False
                    break
            if intact:
                gaps.append({
                    "type": "BULL",
                    "bottom": g_bot, "top": g_top,
                    "mid": (g_bot + g_top) / 2,
                    "sizePct": (g_top - g_bot) / g_bot * 100 if g_bot else 0.0,
                    "idx": i,
                })
        # Bearish FVG
        if h[i + 1] < l[i - 1]:
            g_bot, g_top = float(h[i + 1]), float(l[i - 1])
            intact = True
            for j in range(i + 1, n):
                if h[j] > g_top:
                    intact = False
                    break
            if intact:
                gaps.append({
                    "type": "BEAR",
                    "bottom": g_bot, "top": g_top,
                    "mid": (g_bot + g_top) / 2,
                    "sizePct": (g_top - g_bot) / g_bot * 100 if g_bot else 0.0,
                    "idx": i,
                })
    gaps.sort(key=lambda g: abs(g["mid"] - last_close))
    return gaps[:max_gaps]


def fvg_status(price: float, g: dict) -> dict:
    if g["bottom"] <= price <= g["top"]:
        size = g["top"] - g["bottom"]
        fill = (price - g["bottom"]) / size * 100 if size > 0 else 0.0
        return {"state": "inside", "distPct": 0.0, "fillPct": fill}
    dist_pct = abs(price - g["mid"]) / price * 100 if price else 0.0
    return {
        "state": "approach" if dist_pct < 1.0 else "far",
        "distPct": dist_pct,
        "fillPct": None,
    }


# ─────────────────────────────────────────────────────────────────────
#  Extra indicators
# ─────────────────────────────────────────────────────────────────────
def calc_adx(df: pd.DataFrame, period: int = 14) -> dict:
    n = len(df)
    if n < period + 2:
        return {"adx": 0.0, "plusDI": 0.0, "minusDI": 0.0}
    h = df["High"].to_numpy()
    l = df["Low"].to_numpy()
    c = df["Close"].to_numpy()
    tr_arr, plus_arr, minus_arr = [], [], []
    for i in range(1, n):
        tr_arr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
        up = h[i] - h[i - 1]
        dn = l[i - 1] - l[i]
        plus_arr.append(up if (up > dn and up > 0) else 0.0)
        minus_arr.append(dn if (dn > up and dn > 0) else 0.0)
    atr_s = sum(tr_arr[:period])
    p_s = sum(plus_arr[:period])
    m_s = sum(minus_arr[:period])
    dx_arr: list[dict] = []
    for i in range(period, len(tr_arr)):
        atr_s = atr_s - atr_s / period + tr_arr[i]
        p_s = p_s - p_s / period + plus_arr[i]
        m_s = m_s - m_s / period + minus_arr[i]
        p_di = p_s / atr_s * 100 if atr_s > 0 else 0.0
        m_di = m_s / atr_s * 100 if atr_s > 0 else 0.0
        denom = p_di + m_di
        dx = abs(p_di - m_di) / denom * 100 if denom > 0 else 0.0
        dx_arr.append({"dx": dx, "pDI": p_di, "mDI": m_di})
    if len(dx_arr) < period:
        return {"adx": 0.0, "plusDI": 0.0, "minusDI": 0.0}
    adx = sum(d["dx"] for d in dx_arr[:period]) / period
    for i in range(period, len(dx_arr)):
        adx = (adx * (period - 1) + dx_arr[i]["dx"]) / period
    last = dx_arr[-1]
    return {"adx": adx, "plusDI": last["pDI"], "minusDI": last["mDI"]}


def calc_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    if len(df) < slow + signal:
        return {"macd": 0.0, "signal": 0.0, "histogram": 0.0, "trend": "neutral"}

    def ema_arr(arr: np.ndarray, p: int) -> np.ndarray:
        k = 2.0 / (p + 1.0)
        out = np.zeros_like(arr, dtype=float)
        out[0] = arr[0]
        for i in range(1, len(arr)):
            out[i] = arr[i] * k + out[i - 1] * (1 - k)
        return out

    closes = df["Close"].to_numpy()
    f_arr = ema_arr(closes, fast)
    s_arr = ema_arr(closes, slow)
    macd_line = (f_arr - s_arr)[slow - 1:]
    sig_arr = ema_arr(macd_line, signal)
    last_macd = float(macd_line[-1])
    last_sig = float(sig_arr[-1])
    hist = last_macd - last_sig
    threshold = 0.0001 * float(closes[-1])
    if abs(hist) < threshold:
        trend = "neutral"
    elif hist > 0:
        trend = "bull"
    else:
        trend = "bear"
    return {"macd": last_macd, "signal": last_sig, "histogram": hist, "trend": trend}


def calc_bb(df: pd.DataFrame, period: int = 20, mult: float = 2.0) -> dict:
    if len(df) < period:
        return {"upper": 0.0, "lower": 0.0, "mid": 0.0, "bw": 0.0, "label": "normal"}
    slc = df["Close"].to_numpy()[-period:]
    mid = float(slc.mean())
    std = float(np.sqrt(((slc - mid) ** 2).mean()))
    upper = mid + mult * std
    lower = mid - mult * std
    bw = (upper - lower) / mid * 100 if mid > 0 else 0.0
    label = "squeeze" if bw < 5 else "expanded" if bw > 15 else "normal"
    return {"upper": upper, "lower": lower, "mid": mid, "bw": bw, "label": label}


def calc_obv(df: pd.DataFrame) -> dict:
    n = len(df)
    if n < 2:
        return {"obv": 0.0, "trend": "FLAT"}
    closes = df["Close"].to_numpy()
    vols = df["Volume"].to_numpy()
    obv_arr = [0.0]
    obv = 0.0
    for i in range(1, n):
        if closes[i] > closes[i - 1]:
            obv += vols[i]
        elif closes[i] < closes[i - 1]:
            obv -= vols[i]
        obv_arr.append(obv)
    lookback = min(10, len(obv_arr) - 1)
    obv_old = obv_arr[-1 - lookback]
    obv_now = obv_arr[-1]
    diff_pct = abs((obv_now - obv_old) / abs(obv_old)) * 100 if obv_old != 0 else 0.0
    if diff_pct < 2:
        trend = "FLAT"
    else:
        trend = "UP" if obv_now > obv_old else "DOWN"
    return {"obv": obv_now, "trend": trend}


def calc_fib(df: pd.DataFrame, lookback: int = 50) -> dict:
    slc = df.tail(lookback)
    swing_high = float(slc["High"].max())
    swing_low = float(slc["Low"].min())
    rng = swing_high - swing_low
    fibs = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    levels = [{"ratio": f, "price": swing_low + f * rng} for f in fibs]
    price = float(df["Close"].iloc[-1])
    zone = "Below 0"
    if price > levels[-1]["price"]:
        zone = "Above 786"
    else:
        for i in range(len(levels) - 1):
            if levels[i]["price"] <= price <= levels[i + 1]["price"]:
                zone = f"{round(fibs[i] * 1000)}-{round(fibs[i + 1] * 1000)}"
                break
    return {"swingHigh": swing_high, "swingLow": swing_low, "levels": levels, "priceZone": zone}


def calc_change_24h(df_fl: pd.DataFrame) -> float:
    if df_fl is None or len(df_fl) < 2:
        return 0.0
    first_open = float(df_fl["Open"].iloc[0])
    last_close = float(df_fl["Close"].iloc[-1])
    return (last_close - first_open) / first_open * 100 if first_open > 0 else 0.0


def calc_atr_pct(atr: float, price: float) -> float:
    return atr / price * 100 if price > 0 else 0.0


# ─────────────────────────────────────────────────────────────────────
#  Donchian + squeeze (new additions from Pyonex.txt CFG)
# ─────────────────────────────────────────────────────────────────────
def calc_donchian(df: pd.DataFrame, period: int | None = None) -> dict:
    period = period or CFG["DONCHIAN_PERIOD_SHORT"]
    if len(df) < period:
        return {"upper": 0.0, "lower": 0.0, "mid": 0.0, "widthPct": 0.0, "period": period}
    slc = df.tail(period)
    upper = float(slc["High"].max())
    lower = float(slc["Low"].min())
    mid = (upper + lower) / 2
    width_pct = (upper - lower) / mid * 100 if mid > 0 else 0.0
    return {"upper": upper, "lower": lower, "mid": mid, "widthPct": width_pct, "period": period}


def detect_squeeze(bb: dict, donchian: dict, atr: float, price: float) -> dict:
    """True if BB width is tight AND Donchian channel is small vs ATR."""
    bb_bw = bb.get("bw", 0.0)
    dc_width = donchian["upper"] - donchian["lower"]
    dc_atr_ratio = dc_width / atr if atr > 0 else float("inf")
    sq = CFG["SQUEEZE"]
    bb_tight = 0 < bb_bw < sq["BB_WIDTH_MAX"]
    dc_tight = dc_atr_ratio < sq["DC_ATR_RATIO_MAX"] * (
        CFG["DONCHIAN_PERIOD_SHORT"]
    )
    # relax: DC/ATR threshold expressed per candle; use simpler: dc_width/(period*atr)
    period = donchian.get("period", CFG["DONCHIAN_PERIOD_SHORT"])
    norm_ratio = dc_width / (period * atr) if atr > 0 and period > 0 else float("inf")
    dc_tight = norm_ratio < sq["DC_ATR_RATIO_MAX"]
    return {
        "squeeze": bool(bb_tight and dc_tight),
        "bbTight": bool(bb_tight),
        "dcTight": bool(dc_tight),
        "bbBw": bb_bw,
        "dcAtrRatio": norm_ratio,
    }


# ─────────────────────────────────────────────────────────────────────
#  Aggregator — mirrors getAdvancedMetrics
# ─────────────────────────────────────────────────────────────────────
@dataclass
class OIData:
    oiNow: float = 0.0
    oiChange: float = 0.0


def get_advanced_metrics(
    df4h_main: pd.DataFrame,
    df5d: pd.DataFrame,
    df14d: pd.DataFrame,
    df30d: pd.DataFrame,
    df_flow: pd.DataFrame,
    oi: OIData,
    funding: float = 0.0,
) -> dict:
    """Port of getAdvancedMetrics. Consumes pre-fetched DataFrames, returns
    a dict with every field referenced by calcScore / calcGridScore /
    interpret_signals. Pure — no I/O."""
    if df4h_main.empty:
        return {}

    last_close = float(df4h_main["Close"].iloc[-1])

    rsi = calc_rsi(df4h_main, CFG["RSI_PERIOD"])
    atr = calc_atr(df4h_main, CFG["ATR_PERIOD"])
    ema_fast = calc_ema(df4h_main, CFG["EMA_FAST"])
    ema_slow = calc_ema(df4h_main, CFG["EMA_SLOW"])

    # Vol spike
    vol_window = CFG["VOL_AVG_WINDOW"]
    if len(df4h_main) >= vol_window + 1:
        vol_avg = float(df4h_main["Volume"].iloc[-(vol_window + 1):-1].sum()) / vol_window
    else:
        vol_avg = float(df4h_main["Volume"].mean())
    vol_curr = float(df4h_main["Volume"].iloc[-1])
    vol_spike = vol_curr >= CFG["VOL_SPIKE_MULT"] * vol_avg

    # Liquidity sweep
    last = df4h_main.iloc[-1]
    prev = df4h_main.iloc[:-1]
    prev_high = float(prev["High"].max()) if not prev.empty else float("-inf")
    prev_low = float(prev["Low"].min()) if not prev.empty else float("inf")
    sweep = "Neutral"
    if last["High"] > prev_high and last["Close"] < prev_high:
        sweep = "BUY_SWP"
    elif last["Low"] < prev_low and last["Close"] > prev_low:
        sweep = "SELL_SWP"

    # Multi-timeframe POC/AVWAP
    pv5 = calc_poc_avwap(df5d)
    pv14 = calc_poc_avwap(df14d)
    pv30 = calc_poc_avwap(df30d)

    # CVD
    cvd5d = calc_cvd(df5d)
    cvd14d = calc_cvd(df14d)
    cvd30d = calc_cvd(df30d)

    # Structure
    s4h = calc_market_structure(df4h_main, CFG["STRUCT_LOOKBACK_4H"])
    s30d = calc_market_structure(df30d, CFG["STRUCT_LOOKBACK_30D"])

    # FVG on last 100 candles
    fvg_window = df4h_main.tail(CFG["KLINES_FVG"])
    fvg_list = calc_fvg(fvg_window, CFG["FVG_MAX_GAPS"])

    # 24h flow
    if not df_flow.empty:
        sum_buy = float(df_flow["BuyVol"].sum())
        sum_total = float(df_flow["Volume"].sum())
        if sum_buy <= 0.0 and sum_total > 0.0:
            # heuristic if BuyVol absent
            up_mask = df_flow["Close"].to_numpy() > df_flow["Open"].to_numpy()
            sum_buy = float(df_flow["Volume"].to_numpy()[up_mask].sum()) * 0.55 + \
                      float(df_flow["Volume"].to_numpy()[~up_mask].sum()) * 0.45
        flow = (sum_buy - (sum_total - sum_buy)) / sum_total * 100 if sum_total > 0 else 0.0
    else:
        flow = 0.0

    adx_data = calc_adx(df4h_main)
    macd_data = calc_macd(df4h_main)
    bb_data = calc_bb(df4h_main)
    obv_data = calc_obv(df4h_main)
    fib_data = calc_fib(df4h_main)
    change_24h = calc_change_24h(df_flow)
    atr_pct = calc_atr_pct(atr, last_close)

    donchian_s = calc_donchian(df4h_main, CFG["DONCHIAN_PERIOD_SHORT"])
    donchian_l = calc_donchian(df4h_main, CFG["DONCHIAN_PERIOD_LONG"])
    squeeze = detect_squeeze(bb_data, donchian_s, atr, last_close)

    # Volume 5d for grid score (sum of 5d volume)
    volume5d = float(df5d["Volume"].sum()) if not df5d.empty else 0.0

    return {
        "currClose": last_close,
        "rsi": rsi, "atr": atr, "atrPct": atr_pct,
        "emaFast": ema_fast, "emaSlow": ema_slow,
        "volAvg": vol_avg, "volCurr": vol_curr, "volSpike": vol_spike,
        "sweep": sweep, "flow": flow,
        "poc5d": pv5["poc"], "avwap5d": pv5["avwap"],
        "poc14d": pv14["poc"], "avwap14d": pv14["avwap"],
        "poc30d": pv30["poc"], "avwap30d": pv30["avwap"],
        "cvd5d": cvd5d, "cvd14d": cvd14d, "cvd30d": cvd30d,
        "structure4h": s4h, "structure30d": s30d,
        "fvgList": fvg_list,
        "oiNow": oi.oiNow, "oiChange": oi.oiChange,
        "adx": adx_data, "macd": macd_data, "bb": bb_data, "bbBw": bb_data["bw"],
        "obv": obv_data, "fib": fib_data, "change24h": change_24h,
        "donchianShort": donchian_s, "donchianLong": donchian_l, "squeeze": squeeze,
        "funding": funding, "volume5d": volume5d,
    }
