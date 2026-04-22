"""Signal engine — leading indicator calculations for the Signal Scanner.

All functions are pure. Builds on indicators.py patterns but returns
series and divergence data instead of single scalars.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import SIGNAL_CFG as SC


# ─────────────────────────────────────────────────────────────────────
#  Series builders
# ─────────────────────────────────────────────────────────────────────
def calc_cvd_series(df: pd.DataFrame) -> np.ndarray:
    if df.empty:
        return np.array([])
    vols = df["Volume"].to_numpy()
    buy = df["BuyVol"].to_numpy()
    if float(buy.sum()) <= 0.0:
        closes = df["Close"].to_numpy()
        opens = df["Open"].to_numpy()
        factor = np.where(closes > opens, 0.55, np.where(closes < opens, 0.45, 0.50))
        buy = vols * factor
    delta = buy - (vols - buy)
    return np.cumsum(delta)


def calc_bb_bandwidth_series(df: pd.DataFrame, period: int = 20, mult: float = 2.0) -> np.ndarray:
    closes = df["Close"].to_numpy()
    n = len(closes)
    if n < period:
        return np.array([])
    bw = np.zeros(n - period + 1)
    for i in range(n - period + 1):
        slc = closes[i : i + period]
        mid = slc.mean()
        std = slc.std(ddof=0)
        upper = mid + mult * std
        lower = mid - mult * std
        bw[i] = (upper - lower) / mid * 100 if mid > 0 else 0.0
    return bw


def calc_rsi_series(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    closes = df["Close"].to_numpy()
    n = len(closes)
    if n <= period:
        return np.full(n, 50.0)
    out = np.full(n, 50.0)
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
    if avg_l == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
        if avg_l == 0:
            out[i] = 100.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    return out


def calc_macd_histogram_series(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> np.ndarray:
    closes = df["Close"].to_numpy()
    n = len(closes)
    if n < slow + signal:
        return np.array([])
    k_f = 2.0 / (fast + 1.0)
    k_s = 2.0 / (slow + 1.0)
    ema_f = np.zeros(n)
    ema_s = np.zeros(n)
    ema_f[0] = ema_s[0] = closes[0]
    for i in range(1, n):
        ema_f[i] = closes[i] * k_f + ema_f[i - 1] * (1 - k_f)
        ema_s[i] = closes[i] * k_s + ema_s[i - 1] * (1 - k_s)
    macd_line = (ema_f - ema_s)[slow - 1:]
    k_sig = 2.0 / (signal + 1.0)
    sig_arr = np.zeros(len(macd_line))
    sig_arr[0] = macd_line[0]
    for i in range(1, len(macd_line)):
        sig_arr[i] = macd_line[i] * k_sig + sig_arr[i - 1] * (1 - k_sig)
    return macd_line - sig_arr


# ─────────────────────────────────────────────────────────────────────
#  Pivot detection helper
# ─────────────────────────────────────────────────────────────────────
def _find_swing_pivots(arr: np.ndarray, pivot_bars: int = 2) -> list[tuple[int, float]]:
    """Find swing highs/lows using N-bar pivot logic.
    Returns list of (index, value) for pivots."""
    pivots: list[tuple[int, float]] = []
    n = len(arr)
    for i in range(pivot_bars, n - pivot_bars):
        is_high = all(arr[i] >= arr[i - j] and arr[i] >= arr[i + j] for j in range(1, pivot_bars + 1))
        is_low = all(arr[i] <= arr[i - j] and arr[i] <= arr[i + j] for j in range(1, pivot_bars + 1))
        if is_high or is_low:
            pivots.append((i, float(arr[i])))
    return pivots


def _find_swing_highs(highs: np.ndarray, pivot_bars: int = 2) -> list[tuple[int, float]]:
    result: list[tuple[int, float]] = []
    n = len(highs)
    for i in range(pivot_bars, n - pivot_bars):
        if all(highs[i] >= highs[i - j] and highs[i] >= highs[i + j] for j in range(1, pivot_bars + 1)):
            result.append((i, float(highs[i])))
    return result


def _find_swing_lows(lows: np.ndarray, pivot_bars: int = 2) -> list[tuple[int, float]]:
    result: list[tuple[int, float]] = []
    n = len(lows)
    for i in range(pivot_bars, n - pivot_bars):
        if all(lows[i] <= lows[i - j] and lows[i] <= lows[i + j] for j in range(1, pivot_bars + 1)):
            result.append((i, float(lows[i])))
    return result


# ─────────────────────────────────────────────────────────────────────
#  Detectors
# ─────────────────────────────────────────────────────────────────────
def detect_cvd_divergence(df: pd.DataFrame, lookback: int | None = None) -> dict:
    lookback = lookback or SC["CVD_DIV_LOOKBACK"]
    pivot_bars = SC["CVD_DIV_PIVOT_BARS"]
    default = {"type": "NONE", "strength": 0.0, "candles_ago": 0}
    if len(df) < lookback:
        return default

    window = df.tail(lookback).reset_index(drop=True)
    prices_h = window["High"].to_numpy()
    prices_l = window["Low"].to_numpy()
    cvd = calc_cvd_series(window)
    if len(cvd) < 6:
        return default

    swing_highs = _find_swing_highs(prices_h, pivot_bars)
    swing_lows = _find_swing_lows(prices_l, pivot_bars)

    # Bearish divergence: price HH + CVD LH
    if len(swing_highs) >= 2:
        (i1, p1), (i2, p2) = swing_highs[-2], swing_highs[-1]
        if p2 > p1 and cvd[i2] < cvd[i1]:
            price_diff = abs(p2 - p1) / p1 if p1 > 0 else 0
            cvd_diff = abs(cvd[i1] - cvd[i2]) / (abs(cvd[i1]) + 1e-9)
            strength = min((price_diff + cvd_diff) / 2, 1.0)
            return {"type": "BEAR_DIV", "strength": strength, "candles_ago": lookback - i2}

    # Bullish divergence: price LL + CVD HL
    if len(swing_lows) >= 2:
        (i1, p1), (i2, p2) = swing_lows[-2], swing_lows[-1]
        if p2 < p1 and cvd[i2] > cvd[i1]:
            price_diff = abs(p1 - p2) / p1 if p1 > 0 else 0
            cvd_diff = abs(cvd[i2] - cvd[i1]) / (abs(cvd[i1]) + 1e-9)
            strength = min((price_diff + cvd_diff) / 2, 1.0)
            return {"type": "BULL_DIV", "strength": strength, "candles_ago": lookback - i2}

    return default


def detect_squeeze_progression(bw_series: np.ndarray, threshold: float | None = None) -> dict:
    threshold = threshold or SC["SQ_BW_THRESHOLD"]
    default = {"phase": "FLAT", "compression_rate": 0.0, "bars_to_squeeze": 99, "percentile": 50.0, "current_bw": 0.0}
    if len(bw_series) < 10:
        return default

    current_bw = float(bw_series[-1])
    tail = bw_series[-10:]

    # Linear regression slope
    x = np.arange(10, dtype=float)
    x_mean = x.mean()
    y_mean = tail.mean()
    slope = float(np.sum((x - x_mean) * (tail - y_mean)) / (np.sum((x - x_mean) ** 2) + 1e-9))

    # Percentile vs longer history
    hist_len = min(SC["SQ_PERCENTILE_LOOKBACK"], len(bw_series))
    percentile = float(np.sum(bw_series[-hist_len:] <= current_bw) / hist_len * 100)

    if current_bw < threshold and current_bw > 0:
        phase = "SQUEEZE"
        bars_to_squeeze = 0
    elif slope < SC["SQ_COMPRESSION_SLOPE"] and current_bw < 10.0:
        phase = "COMPRESSING"
        bars_to_squeeze = max(1, int((current_bw - threshold) / abs(slope))) if slope < 0 else 99
    elif slope > abs(SC["SQ_COMPRESSION_SLOPE"]):
        phase = "EXPANDING"
        bars_to_squeeze = 99
    else:
        phase = "FLAT"
        bars_to_squeeze = 99

    return {
        "phase": phase,
        "compression_rate": slope,
        "bars_to_squeeze": bars_to_squeeze,
        "percentile": percentile,
        "current_bw": current_bw,
    }


def detect_structure_transition(df: pd.DataFrame, lookback: int | None = None) -> dict:
    lookback = lookback or SC["STRUCT_TRANS_LOOKBACK"]
    default = {"current": "Neutral", "transitioning_to": None, "confidence": 0.0, "signal": "STABLE"}
    if len(df) < lookback:
        return default

    window = df.tail(lookback).reset_index(drop=True)
    highs = window["High"].to_numpy()
    lows = window["Low"].to_numpy()
    n = len(window)

    # Find swing pivots
    swing_h = _find_swing_highs(highs, 2)
    swing_l = _find_swing_lows(lows, 2)

    # Current structure (same logic as calc_market_structure)
    if n >= 5:
        h0, h2, h4 = highs[-1], highs[-3], highs[-5]
        l0, l2, l4 = lows[-1], lows[-3], lows[-5]
        if h0 > h2 > h4 and l0 > l2 > l4:
            current = "Bullish"
        elif h0 < h2 < h4 and l0 < l2 < l4:
            current = "Bearish"
        else:
            current = "Neutral"
    else:
        current = "Neutral"

    exhaust_pct = SC["STRUCT_EXHAUSTION_PCT"] / 100

    # Trend exhaustion: highs or lows flattening
    if current == "Bullish" and len(swing_h) >= 2:
        (_, h_prev), (_, h_last) = swing_h[-2], swing_h[-1]
        diff = abs(h_last - h_prev) / h_prev if h_prev > 0 else 0
        if diff < exhaust_pct:
            conf = 1.0 - diff / exhaust_pct
            return {"current": current, "transitioning_to": "Ranging", "confidence": conf, "signal": "TREND_EXHAUSTION"}

    if current == "Bearish" and len(swing_l) >= 2:
        (_, l_prev), (_, l_last) = swing_l[-2], swing_l[-1]
        diff = abs(l_last - l_prev) / l_prev if l_prev > 0 else 0
        if diff < exhaust_pct:
            conf = 1.0 - diff / exhaust_pct
            return {"current": current, "transitioning_to": "Ranging", "confidence": conf, "signal": "TREND_EXHAUSTION"}

    # Range forming: highs and lows converging
    if len(swing_h) >= 2 and len(swing_l) >= 2:
        h_range = abs(swing_h[-1][1] - swing_h[-2][1])
        l_range = abs(swing_l[-1][1] - swing_l[-2][1])
        avg_price = (swing_h[-1][1] + swing_l[-1][1]) / 2
        if avg_price > 0:
            convergence = (h_range + l_range) / avg_price
            if convergence < exhaust_pct * 2:
                conf = max(0.0, 1.0 - convergence / (exhaust_pct * 2))
                return {"current": current, "transitioning_to": "Ranging", "confidence": conf, "signal": "RANGE_FORMING"}

    return {"current": current, "transitioning_to": None, "confidence": 0.0, "signal": "STABLE"}


def detect_momentum_divergence(
    df: pd.DataFrame,
    rsi_series: np.ndarray,
    macd_hist: np.ndarray,
    lookback: int | None = None,
) -> dict:
    lookback = lookback or SC["MOM_DIV_LOOKBACK"]
    default = {"rsi_div": "NONE", "macd_div": "NONE", "combined_strength": 0.0}
    if len(df) < lookback or len(rsi_series) < lookback:
        return default

    prices_h = df["High"].to_numpy()[-lookback:]
    prices_l = df["Low"].to_numpy()[-lookback:]
    rsi_window = rsi_series[-lookback:]
    pivot_bars = SC["CVD_DIV_PIVOT_BARS"]

    rsi_div = "NONE"
    macd_div = "NONE"
    strength = 0.0

    # RSI divergence on swing highs
    sh = _find_swing_highs(prices_h, pivot_bars)
    if len(sh) >= 2:
        (i1, p1), (i2, p2) = sh[-2], sh[-1]
        if p2 > p1 and rsi_window[i2] < rsi_window[i1]:
            rsi_div = "BEAR"
            strength += 0.5
        elif len(_find_swing_lows(prices_l, pivot_bars)) >= 2:
            sl = _find_swing_lows(prices_l, pivot_bars)
            (i1, p1), (i2, p2) = sl[-2], sl[-1]
            if p2 < p1 and rsi_window[i2] > rsi_window[i1]:
                rsi_div = "BULL"
                strength += 0.5

    # MACD histogram divergence: shrinking while price extends
    if len(macd_hist) >= 5:
        recent_hist = macd_hist[-5:]
        hist_slope = recent_hist[-1] - recent_hist[0]
        price_slope = float(df["Close"].iloc[-1] - df["Close"].iloc[-5])
        if price_slope > 0 and hist_slope < 0:
            macd_div = "BEAR"
            strength += 0.3
        elif price_slope < 0 and hist_slope > 0:
            macd_div = "BULL"
            strength += 0.3

    # Agreement bonus
    if rsi_div != "NONE" and macd_div != "NONE" and rsi_div == macd_div:
        strength += 0.2

    return {"rsi_div": rsi_div, "macd_div": macd_div, "combined_strength": min(strength, 1.0)}


def detect_volume_exhaustion(df: pd.DataFrame, lookback: int | None = None) -> dict:
    lookback = lookback or SC["VOL_EX_LOOKBACK"]
    default = {"exhaustion": False, "vol_trend_slope": 0.0, "vol_percentile": 50.0}
    if len(df) < lookback:
        return default

    vols = df["Volume"].to_numpy()[-lookback:]
    mean_vol = vols.mean()
    if mean_vol <= 0:
        return default

    # Slope as % of mean volume
    x = np.arange(lookback, dtype=float)
    x_mean = x.mean()
    y_mean = vols.mean()
    slope = float(np.sum((x - x_mean) * (vols - y_mean)) / (np.sum((x - x_mean) ** 2) + 1e-9))
    slope_pct = slope / mean_vol * 100

    # Percentile of current volume vs window
    current_vol = vols[-1]
    percentile = float(np.sum(vols <= current_vol) / lookback * 100)

    exhaustion = slope_pct < SC["VOL_EX_SLOPE"] and percentile < SC["VOL_EX_PERCENTILE"]

    return {"exhaustion": exhaustion, "vol_trend_slope": slope_pct, "vol_percentile": percentile}


# ─────────────────────────────────────────────────────────────────────
#  Scorers
# ─────────────────────────────────────────────────────────────────────
def score_cvd_divergence(div: dict, structure4h: str) -> tuple[float, str]:
    if div["type"] == "NONE":
        return 0.0, "No divergence"
    pts = 1.0
    s = div["strength"]
    if s > 0.5:
        pts += 0.5
    if s > 0.75:
        pts += 0.5
    # Structure confluence: divergence opposes current trend = grid window opening
    if (div["type"] == "BEAR_DIV" and structure4h == "Bullish") or \
       (div["type"] == "BULL_DIV" and structure4h == "Bearish"):
        pts += 0.5
    pts = min(pts, 2.5)
    label = f"{div['type'].replace('_', ' ').title()} str={s:.0%} {div['candles_ago']}bars ago"
    return pts, label


def score_squeeze_progression(sq: dict) -> tuple[float, str]:
    phase = sq["phase"]
    bars = sq["bars_to_squeeze"]
    if phase == "SQUEEZE":
        return 2.0, f"IN SQUEEZE bw={sq['current_bw']:.1f}%"
    if phase == "COMPRESSING":
        if bars <= 5:
            return 1.5, f"Imminent ~{bars} bars"
        if bars <= 15:
            return 1.0, f"Developing ~{bars} bars"
        if bars <= 30:
            return 0.5, f"Early ~{bars} bars"
    if phase == "EXPANDING":
        return 0.0, f"Expanding bw={sq['current_bw']:.1f}%"
    return 0.0, f"Flat bw={sq['current_bw']:.1f}%"


def score_structure_transition(trans: dict) -> tuple[float, str]:
    sig = trans["signal"]
    conf = trans["confidence"]
    if sig == "TREND_EXHAUSTION" and conf > 0.6:
        return 1.5, f"Exhaustion {trans['current']}→Range conf={conf:.0%}"
    if sig == "TREND_EXHAUSTION":
        return 0.5, f"Weak exhaustion conf={conf:.0%}"
    if sig == "RANGE_FORMING":
        pts = min(1.0, 1.0 * conf)
        return pts, f"Range forming conf={conf:.0%}"
    return 0.0, f"Stable {trans['current']}"


def score_funding_oi(funding: float, oi_change: float, structure4h: str) -> tuple[float, str]:
    pts = 0.0
    details: list[str] = []

    if abs(funding) > SC["FUNDING_EXTREME"]:
        pts += 0.75
        details.append(f"Extreme fund={funding:+.3f}%")
    if abs(funding) > SC["FUNDING_ELEVATED"] and oi_change > SC["OI_BUILDUP_PCT"]:
        pts += 0.5
        details.append(f"OI buildup +{oi_change:.1f}%")
    elif oi_change < SC["OI_CLEARING_PCT"] and abs(funding) < SC["FUNDING_ELEVATED"]:
        pts += 0.25
        details.append(f"OI clearing {oi_change:.1f}%")
    if (funding > SC["FUNDING_ELEVATED"] and structure4h == "Bearish") or \
       (funding < -SC["FUNDING_ELEVATED"] and structure4h == "Bullish"):
        pts += 0.25
        details.append("Contrarian signal")

    return min(pts, 1.5), " | ".join(details) if details else "Neutral"


def score_momentum_divergence(div: dict) -> tuple[float, str]:
    rsi = div["rsi_div"]
    macd = div["macd_div"]
    if rsi != "NONE" and macd != "NONE" and rsi == macd:
        return 1.5, f"RSI+MACD {rsi} div"
    if rsi != "NONE":
        return 0.75, f"RSI {rsi} div"
    if macd != "NONE":
        return 0.5, f"MACD {macd} div"
    return 0.0, "No divergence"


def score_volume_exhaustion(vol_ex: dict, structure4h: str) -> tuple[float, str]:
    if not vol_ex["exhaustion"]:
        slope = vol_ex["vol_trend_slope"]
        if slope < -1.0:
            return 0.25, f"Vol declining slope={slope:.1f}%"
        return 0.0, "Healthy volume"
    if structure4h in ("Bullish", "Bearish"):
        return 1.0, f"Trend vol dying slope={vol_ex['vol_trend_slope']:.1f}%"
    return 0.5, f"Vol exhausted slope={vol_ex['vol_trend_slope']:.1f}%"


# ─────────────────────────────────────────────────────────────────────
#  Signal classification
# ─────────────────────────────────────────────────────────────────────
def _classify_signal(
    cvd_div: dict, sq_prog: dict, struct_trans: dict,
    mom_div: dict, funding: float, structure4h: str,
) -> dict:
    # Priority 1: Grid window opening
    if sq_prog["phase"] in ("SQUEEZE", "COMPRESSING") and struct_trans["signal"] != "TREND_STARTING":
        return {"type": "GRID_WINDOW", "direction": "Neutral", "reason": "Volatility compressing — grid conditions forming"}

    # Priority 2: Long setup
    if cvd_div["type"] == "BULL_DIV" and (struct_trans["signal"] == "TREND_EXHAUSTION" and struct_trans["current"] == "Bearish"):
        return {"type": "LONG_SETUP", "direction": "Long", "reason": "Bullish CVD div + bearish exhaustion — reversal forming"}

    # Priority 3: Short setup
    if cvd_div["type"] == "BEAR_DIV" and (struct_trans["signal"] == "TREND_EXHAUSTION" and struct_trans["current"] == "Bullish"):
        return {"type": "SHORT_SETUP", "direction": "Short", "reason": "Bearish CVD div + bullish exhaustion — reversal forming"}

    # Priority 4: Squeeze play
    if abs(funding) > SC["FUNDING_EXTREME"]:
        opp_dir = "Long" if funding < 0 else "Short"
        return {"type": "SQUEEZE_PLAY", "direction": opp_dir, "reason": f"Extreme funding {funding:+.3f}% — liquidation flush likely"}

    # Priority 5: Directional from momentum divergence
    if mom_div["rsi_div"] == "BULL" or mom_div["macd_div"] == "BULL":
        return {"type": "LONG_SETUP", "direction": "Long", "reason": "Momentum divergence bullish"}
    if mom_div["rsi_div"] == "BEAR" or mom_div["macd_div"] == "BEAR":
        return {"type": "SHORT_SETUP", "direction": "Short", "reason": "Momentum divergence bearish"}

    return {"type": "NONE", "direction": "Neutral", "reason": "No setup forming"}


def _calc_urgency(score: float, sq_prog: dict, cvd_div: dict) -> dict:
    rank = score
    if sq_prog["phase"] == "SQUEEZE":
        rank += 3.0
    elif sq_prog["phase"] == "COMPRESSING" and sq_prog["bars_to_squeeze"] < 5:
        rank += 2.0
    if cvd_div["type"] != "NONE" and cvd_div["candles_ago"] <= 3:
        rank += 1.5

    thresholds = SC["URGENCY"]
    if rank >= thresholds["URGENT"]:
        level, label = "URGENT", "ACT NOW"
    elif rank >= thresholds["SOON"]:
        level, label = "SOON", "Prepare entry"
    elif rank >= thresholds["WATCH"]:
        level, label = "WATCH", "Monitor closely"
    else:
        level, label = "WAIT", "No action needed"

    return {"level": level, "label": label, "rank_value": round(rank, 1)}


def _estimate_eta(sq_prog: dict, struct_trans: dict) -> dict:
    estimates: list[int] = []
    if sq_prog["phase"] == "COMPRESSING" and sq_prog["bars_to_squeeze"] < 99:
        estimates.append(sq_prog["bars_to_squeeze"])
    if struct_trans["signal"] == "TREND_EXHAUSTION" and struct_trans["confidence"] > 0:
        estimates.append(max(1, int((1 - struct_trans["confidence"]) * 15)))

    if not estimates:
        return {"bars": None, "label": "Unknown", "confidence": 0.0}

    avg_bars = sum(estimates) / len(estimates)
    hours = avg_bars * 4
    if hours < 4:
        label = "< 4 hours"
    elif hours < 12:
        label = "4-12 hours"
    elif hours < 24:
        label = "12-24 hours"
    elif hours < 72:
        label = "1-3 days"
    else:
        label = f"~{int(hours / 24)} days"

    conf = min(1.0, sum(1 for _ in estimates) * 0.5)
    return {"bars": int(avg_bars), "label": label, "confidence": conf}


# ─────────────────────────────────────────────────────────────────────
#  Main aggregator
# ─────────────────────────────────────────────────────────────────────
def calc_setup_score(metrics: dict, df4h: pd.DataFrame) -> dict:
    """Calculate the Setup Score from leading indicators.
    Returns a dict ready to be stored in the payload as 'signalInfo'."""
    structure4h = metrics.get("structure4h", "Neutral")
    funding = metrics.get("funding", 0.0)
    oi_change = (metrics.get("oi") or {}).get("oiChange", 0.0)

    # Build series
    cvd_series = calc_cvd_series(df4h)
    bw_series = calc_bb_bandwidth_series(df4h)
    rsi_series = calc_rsi_series(df4h)
    macd_hist = calc_macd_histogram_series(df4h)

    # Detect
    cvd_div = detect_cvd_divergence(df4h)
    sq_prog = detect_squeeze_progression(bw_series)
    struct_trans = detect_structure_transition(df4h)
    mom_div = detect_momentum_divergence(df4h, rsi_series, macd_hist)
    vol_ex = detect_volume_exhaustion(df4h)

    # Score each component
    s1, d1 = score_cvd_divergence(cvd_div, structure4h)
    s2, d2 = score_squeeze_progression(sq_prog)
    s3, d3 = score_structure_transition(struct_trans)
    s4, d4 = score_funding_oi(funding, oi_change, structure4h)
    s5, d5 = score_momentum_divergence(mom_div)
    s6, d6 = score_volume_exhaustion(vol_ex, structure4h)

    total = min(round(s1 + s2 + s3 + s4 + s5 + s6, 1), 10.0)

    # Label
    label = "NO SIGNAL"
    for threshold, lbl in sorted(SC["LABELS"].items(), reverse=True):
        if total >= threshold:
            label = lbl
            break

    components = [
        {"label": "CVD Divergence", "score": s1, "max": 2.5, "detail": d1},
        {"label": "Squeeze Progress", "score": s2, "max": 2.0, "detail": d2},
        {"label": "Structure Shift", "score": s3, "max": 1.5, "detail": d3},
        {"label": "Funding/OI", "score": s4, "max": 1.5, "detail": d4},
        {"label": "Momentum Div", "score": s5, "max": 1.5, "detail": d5},
        {"label": "Vol Exhaustion", "score": s6, "max": 1.0, "detail": d6},
    ]

    signal_type = _classify_signal(cvd_div, sq_prog, struct_trans, mom_div, funding, structure4h)
    urgency = _calc_urgency(total, sq_prog, cvd_div)
    eta = _estimate_eta(sq_prog, struct_trans)

    # Chart data for the UI (compact series, last N values)
    slen = SC["CHART_SERIES_LEN"]
    chart_data = {
        "bb_bw": bw_series[-slen:].tolist() if len(bw_series) > 0 else [],
        "cvd": cvd_series[-slen:].tolist() if len(cvd_series) > 0 else [],
        "price": df4h["Close"].to_numpy()[-slen:].tolist() if not df4h.empty else [],
        "rsi": rsi_series[-slen:].tolist() if len(rsi_series) > 0 else [],
    }

    return {
        "score": total,
        "label": label,
        "components": components,
        "signal_type": signal_type,
        "urgency": urgency,
        "eta": eta,
        "chart_data": chart_data,
    }
