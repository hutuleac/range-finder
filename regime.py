"""Regime layer (Phase 2) — Efficiency Ratio × Hurst, cross-validated.

Faithful ports from Double-main/core/indicators.py:
    calc_efficiency_ratio   — Kaufman ER on daily closes
    hurst_daily / _hurst_rs — R/S Hurst on daily log-returns
    calc_adx_slope          — ADX direction-of-change on the 4H series
    calc_regime_confirmation — direction-aware ER × Hurst cross-validation

`build_regime` is the glue: it consumes the Phase 1 daily spine (mtf) plus the
existing 4H metrics, derives a daily trend, and returns one regime verdict.

Thresholds live in CFG["REGIME"] and are Double-derived heuristics — NOT
calibrated for range-finder's pairs (see IMPROVEMENT_PLAN.md).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import CFG


# ─────────────────────────────────────────────────────────────────────
#  Efficiency Ratio (Kaufman) — port. Adapted to accept a closes list.
# ─────────────────────────────────────────────────────────────────────
def calc_efficiency_ratio(closes: list[float], period: int = 10) -> dict:
    """ER → 1.0 = efficient single-direction move (trend); → 0.0 = noise (range)."""
    try:
        closes = list(closes)
        if len(closes) < period + 1:
            return {"er_value": None, "er_regime": "UNKNOWN"}
        c = np.asarray(closes[-(period + 1):], dtype=float)
        net = abs(c[-1] - c[0])
        path = float(np.sum(np.abs(np.diff(c))))
        er = round(net / path if path > 0 else 0.0, 4)

        if er >= 0.6:
            regime = "TRENDING"
            grid_signal = "AVOID_GRIDS — price moving efficiently, grids get stranded"
            dir_signal = "FOLLOW_TREND — high ER confirms directional momentum"
        elif er >= 0.3:
            regime = "TRANSITIONAL"
            grid_signal = "CAUTION — mixed regime, monitor direction"
            dir_signal = "REDUCED_CONFIDENCE — wait for ER to resolve"
        else:
            regime = "RANGING"
            grid_signal = "IDEAL_FOR_GRIDS — price oscillating, grids fill rounds"
            dir_signal = "MEAN_REVERSION_FAVORED — low ER = no directional edge"

        return {"er_value": er, "er_regime": regime,
                "grid_signal": grid_signal, "dir_signal": dir_signal}
    except Exception as e:  # noqa: BLE001
        return {"er_value": None, "er_regime": "UNKNOWN", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────
#  Hurst exponent (R/S on log-returns) — port.
# ─────────────────────────────────────────────────────────────────────
def _hurst_rs(closes: list[float]) -> float:
    """R/S Hurst core. Log-returns first to avoid trend non-stationarity bias."""
    prices = np.array(closes, dtype=float)
    arr = np.log(prices[1:] / prices[:-1])
    max_lag = min(40, len(arr) // 3)
    if max_lag < 2:
        raise ValueError("INSUFFICIENT_DATA")
    rs_values = []
    for lag in range(2, max_lag + 1):
        n_chunks = len(arr) // lag
        if n_chunks < 1:
            continue
        rs_chunk = []
        for i in range(n_chunks):
            chunk = arr[i * lag:(i + 1) * lag]
            if len(chunk) < 2:
                continue
            devs = chunk - np.mean(chunk)
            cumdev = np.cumsum(devs)
            R = np.max(cumdev) - np.min(cumdev)
            S = np.std(chunk, ddof=1)
            if S > 0:
                rs_chunk.append(R / S)
        if rs_chunk:
            rs_values.append((lag, np.mean(rs_chunk)))
    if len(rs_values) < 3:
        raise ValueError("INSUFFICIENT_DATA")
    lags = np.log([v[0] for v in rs_values])
    rs = np.log([v[1] for v in rs_values])
    return float(np.polyfit(lags, rs, 1)[0])


def _classify_hurst(h: float) -> str:
    if h > 0.6:
        return "TRENDING"
    if h < 0.45:
        return "MEAN_REVERTING"
    return "RANDOM"


def hurst_daily(closes_daily: list[float], window: int = 90) -> dict:
    """Hurst R/S on last `window` daily closes.
    >0.6 TRENDING | 0.45–0.6 RANDOM | <0.45 MEAN_REVERTING."""
    try:
        series = list(closes_daily)[-window:]
        if len(series) < 30:
            return {"hurst_daily": None, "window_days": window,
                    "regime": "UNKNOWN", "signal": "INSUFFICIENT_DATA"}
        h = _hurst_rs(series)
        regime = _classify_hurst(h)
        signal = {
            "TRENDING": "MOMENTUM_FAVORED — trend persistent on daily",
            "MEAN_REVERTING": "FADE_EXTREMES — mean-reversion dominant on daily",
            "RANDOM": "NO_EDGE — random walk on daily timeframe",
        }[regime]
        return {"hurst_daily": round(h, 4), "window_days": window,
                "regime": regime, "signal": signal}
    except Exception as e:  # noqa: BLE001
        return {"hurst_daily": None, "window_days": window,
                "regime": "ERROR", "signal": str(e)}


# ─────────────────────────────────────────────────────────────────────
#  ADX slope (direction-of-change) — port. Runs on the 4H series.
# ─────────────────────────────────────────────────────────────────────
def calc_adx_slope(df: pd.DataFrame, period: int = 14, lookback: int = 5) -> dict:
    """RISING (accelerating) | FALLING (exhausting) | PEAKED (just rolled over) | FLAT."""
    try:
        high, low, close = df["High"], df["Low"], df["Close"]
        hl = high - low
        hcp = (high - close.shift(1)).abs()
        lcp = (low - close.shift(1)).abs()
        tr = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
        up = high.diff()
        dn = -low.diff()
        pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index, dtype=float)
        mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index, dtype=float)

        def wilder(s: pd.Series, n: int) -> pd.Series:
            out = pd.Series(np.nan, index=s.index, dtype=float)
            if len(s) <= n:
                return out
            out.iloc[n] = s.iloc[1:n + 1].sum()
            for i in range(n + 1, len(s)):
                out.iloc[i] = out.iloc[i - 1] - out.iloc[i - 1] / n + s.iloc[i]
            return out

        tr_w, pdm_w, mdm_w = wilder(tr, period), wilder(pdm, period), wilder(mdm, period)
        pdi = 100 * pdm_w / tr_w
        mdi = 100 * mdm_w / tr_w
        denom = (pdi + mdi).replace(0, np.nan)
        dx = 100 * (pdi - mdi).abs() / denom
        adx = dx.rolling(period).mean()

        vals = adx.dropna().iloc[-lookback:].values
        if len(vals) < 3:
            return {"adx_slope": "FLAT", "adx_values": [], "adx_delta": 0.0}
        vals_list = [round(float(v), 2) for v in vals]
        delta = vals_list[-1] - vals_list[0]
        mid = len(vals_list) // 2
        was_rising = vals_list[mid] > vals_list[0] + 0.5
        now_falling = vals_list[-1] < vals_list[mid] - 0.5
        if was_rising and now_falling:
            slope = "PEAKED"
        elif delta > 1.5:
            slope = "RISING"
        elif delta < -1.5:
            slope = "FALLING"
        else:
            slope = "FLAT"
        return {"adx_slope": slope, "adx_values": vals_list, "adx_delta": round(delta, 2)}
    except Exception:  # noqa: BLE001
        return {"adx_slope": "FLAT", "adx_values": [], "adx_delta": 0.0}


# ─────────────────────────────────────────────────────────────────────
#  Regime confirmation — ER × Hurst cross-validation — port.
#  NOTE: expects hurst dict keyed "hurst_regime" (build_regime remaps this).
# ─────────────────────────────────────────────────────────────────────
def calc_regime_confirmation(er: dict, hurst: dict, trend_daily: str = "Neutral") -> dict:
    """Direction-aware. Hurst measures persistence, not direction — a persistent
    bear confirms shorts. trend_daily supplies the BULL/BEAR routing."""
    er_r = er.get("er_regime", "UNKNOWN")
    hurst_r = hurst.get("hurst_regime", "UNKNOWN")

    if "UNKNOWN" in (er_r, hurst_r) or "ERROR" in (er_r, hurst_r):
        return {"aligned": False, "conviction": "UNKNOWN",
                "combined_regime": "UNKNOWN", "trend_direction": trend_daily,
                "strategy_hint": "INSUFFICIENT_DATA"}

    trend_dir = {"Bullish": "BULL", "Bearish": "BEAR"}.get(trend_daily, "NEUTRAL")

    both_trending = (er_r == "TRENDING" and hurst_r == "TRENDING")
    ranging_match = (er_r == "RANGING" and hurst_r == "MEAN_REVERTING")
    trans_match = (er_r == "TRANSITIONAL" and hurst_r in ("RANDOM", "TRENDING"))
    er_trend_h_mean = (er_r == "TRENDING" and hurst_r == "MEAN_REVERTING")
    er_range_h_tren = (er_r == "RANGING" and hurst_r == "TRENDING")

    if both_trending:
        if trend_dir == "BULL":
            return {"aligned": True, "conviction": "HIGH",
                    "combined_regime": "CONFIRMED_TRENDING_BULL", "trend_direction": trend_dir,
                    "strategy_hint": "MOMENTUM_LONG — trail stops, follow trend up"}
        if trend_dir == "BEAR":
            return {"aligned": True, "conviction": "HIGH",
                    "combined_regime": "CONFIRMED_TRENDING_BEAR", "trend_direction": trend_dir,
                    "strategy_hint": "MOMENTUM_SHORT — trail stops, follow trend down"}
        return {"aligned": True, "conviction": "MEDIUM",
                "combined_regime": "CONFIRMED_TRENDING_NEUTRAL", "trend_direction": trend_dir,
                "strategy_hint": "TRENDING but no daily direction — wait for structure"}
    if ranging_match:
        return {"aligned": True, "conviction": "HIGH",
                "combined_regime": "CONFIRMED_RANGING", "trend_direction": trend_dir,
                "strategy_hint": "GRID — fade extremes, mean reversion optimal"}
    if trans_match:
        return {"aligned": True, "conviction": "MEDIUM",
                "combined_regime": "TRANSITIONAL", "trend_direction": trend_dir,
                "strategy_hint": "REDUCED_SIZE — regime changing, wait for clarity"}
    if er_trend_h_mean:
        return {"aligned": False, "conviction": "LOW",
                "combined_regime": "SHORT_TERM_SPIKE", "trend_direction": trend_dir,
                "strategy_hint": "FADE — recent spike against mean-reverting character"}
    if er_range_h_tren:
        return {"aligned": False, "conviction": "MEDIUM",
                "combined_regime": "CONSOLIDATION_IN_TREND", "trend_direction": trend_dir,
                "strategy_hint": "ACCUMULATE — consolidation in larger trend, prepare entry"}
    return {"aligned": False, "conviction": "LOW",
            "combined_regime": "CONFLICTING", "trend_direction": trend_dir,
            "strategy_hint": "MINIMAL_SIZE — ER and Hurst disagree"}


# ─────────────────────────────────────────────────────────────────────
#  Daily trend + glue
# ─────────────────────────────────────────────────────────────────────
def derive_trend_daily(closes: list[float]) -> str:
    """Daily EMA-fast vs EMA-slow with a neutral band. Drives regime_confirmation's
    BULL/BEAR routing. Uses the Phase 1 daily spine (not the 4H structure)."""
    rc = CFG["REGIME"]
    fast, slow, band = rc["TREND_EMA_FAST"], rc["TREND_EMA_SLOW"], rc["TREND_NEUTRAL_BAND"]
    closes = list(closes)
    if len(closes) < slow:
        return "Neutral"
    s = pd.Series(closes, dtype=float)
    ef = float(s.ewm(span=fast, adjust=False).mean().iloc[-1])
    es = float(s.ewm(span=slow, adjust=False).mean().iloc[-1])
    if ef > es * (1 + band):
        return "Bullish"
    if ef < es * (1 - band):
        return "Bearish"
    return "Neutral"


def build_regime(mtf: dict, df_main: pd.DataFrame) -> dict:
    """Assemble the regime verdict from the daily spine + 4H series.

    Degrades gracefully: missing daily closes → ER/Hurst UNKNOWN →
    confirmation INSUFFICIENT_DATA, never raises.
    """
    rc = CFG["REGIME"]
    daily = (mtf or {}).get("dailyCloses") or []

    er = calc_efficiency_ratio(daily, rc["ER_PERIOD"])
    hurst = hurst_daily(daily, rc["HURST_WINDOW"])
    trend_daily = derive_trend_daily(daily)
    # Remap key for the cross-validator (hurst_daily returns "regime").
    confirmation = calc_regime_confirmation(
        er, {"hurst_regime": hurst.get("regime", "UNKNOWN")}, trend_daily,
    )
    adx_slope = calc_adx_slope(df_main, lookback=rc["ADX_SLOPE_LOOKBACK"])

    return {
        "er": er,
        "hurst": hurst,
        "trendDaily": trend_daily,
        "confirmation": confirmation,
        "adxSlope": adx_slope,
    }
