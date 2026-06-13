"""Profitability matrix (Phase 3) — per-strategy weighted scoring.

Additive view: produces a suitability score 0–100 for each of four strategy
columns (GRID_NEUTRAL, GRID_LONG, GRID_SHORT, DIRECTIONAL) from the indicators
range-finder already computes plus the Phase 2 regime layer. It does NOT replace
the existing grid score or touch the recommendation pipeline.

Methodology adapted from Double-main/matrix_profitability_v1.2.py:
    score(strategy) = Σ(weight × normalized) / Σ(weight) × 100
Each indicator is normalized to 0–1 with strategy-aware logic (grid columns favor
low trend / ranging regime / compression; the directional column favors trend).
The long/short bias columns add directional alignment on structure, trend, funding,
CVD and flow.

Weights live in CFG["MATRIX"]; normalization thresholds below are Double-derived
heuristics, NOT calibrated for range-finder's pairs.
"""
from __future__ import annotations

from config import CFG

STRATEGIES = ("GRID_NEUTRAL", "GRID_LONG", "GRID_SHORT", "DIRECTIONAL")


def _is_grid(strategy: str) -> bool:
    return strategy != "DIRECTIONAL"


def _dir_map(structure: str, strategy: str) -> float:
    """Directional alignment for Bullish/Bearish/Neutral fields."""
    bull = structure == "Bullish"
    bear = structure == "Bearish"
    neutral = not (bull or bear)
    if strategy == "GRID_NEUTRAL":
        return 1.0 if neutral else 0.5
    if strategy == "GRID_LONG":
        return 1.0 if bull else 0.5 if neutral else 0.2
    if strategy == "GRID_SHORT":
        return 1.0 if bear else 0.5 if neutral else 0.2
    return 0.9 if not neutral else 0.3  # DIRECTIONAL: any clean direction


def _normalize(indicator: str, c: dict, strategy: str) -> float:
    """Map one indicator's value to 0–1 for a strategy. Returns a neutral 0.5
    when an input is missing, so a gap never zeroes a column."""
    grid = _is_grid(strategy)

    if indicator == "ADX":
        v = c["adx"]
        slope = c["adx_slope"]
        if grid:  # grid favors low / falling ADX
            if v < 20:
                return 1.0
            if v < 25:
                return 0.9
            if v < 30:
                return 0.7 if slope == "FALLING" else 0.3
            if v < 35:
                return 0.5 if slope == "FALLING" else 0.2
            return 0.1
        return min(v / 50, 1.0)  # directional favors high ADX

    if indicator == "ADX_slope":
        slope = c["adx_slope"]
        if grid:
            return {"FALLING": 1.0, "PEAKED": 0.9, "FLAT": 0.5, "RISING": 0.2}.get(slope, 0.5)
        return {"RISING": 1.0, "FLAT": 0.5, "PEAKED": 0.3, "FALLING": 0.2}.get(slope, 0.5)

    if indicator == "BB_bandwidth":
        v = c["bb_bw"]
        if v < 1.5:
            return 0.6  # too compressed
        if v <= 6.0:
            return 1.0  # ideal band
        return max(0.3, 1.0 - (v - 6) / 10)  # widening = trending

    if indicator == "ATR_pct":
        v = c["atr_pct"]
        if 0.4 <= v <= 2.0:
            return 1.0
        if v < 0.4:
            return 0.5
        return max(0.3, 1.0 - (v - 2) / 3)

    if indicator == "ER":
        v = c["er"]
        if v is None:
            return 0.5
        if grid:  # grid favors ranging (low ER)
            if v < 0.3:
                return 1.0
            if v < 0.6:
                return 0.5
            return 0.2
        return min(max(v, 0.0), 1.0)  # directional favors trending (high ER)

    if indicator == "Hurst":
        v = c["hurst"]
        if v is None:
            return 0.5
        if grid:  # grid favors mean-reversion (low H)
            if v < 0.45:
                return 1.0
            if v < 0.55:
                return 0.5
            return 0.2
        return min(max(v, 0.0), 1.0)  # directional favors persistence (high H)

    if indicator == "RSI":
        v = c["rsi"]
        if grid:  # extremes = counter-trend grid opportunity
            if v < 30 or v > 70:
                return 0.9
            if v < 40 or v > 60:
                return 0.7
            return 0.5
        return min(abs(v - 50) / 25, 1.0)  # directional likes momentum off mid

    if indicator == "funding":
        v = c["funding"]
        if strategy == "GRID_LONG":
            return min(abs(v) / 0.02, 1.0) if v < 0 else 0.3
        if strategy == "GRID_SHORT":
            return min(abs(v) / 0.02, 1.0) if v > 0 else 0.3
        if strategy == "GRID_NEUTRAL":
            return max(0.2, 1.0 - min(abs(v) / 0.03, 1.0))  # near-zero = no squeeze risk
        return min(abs(v) / 0.02, 1.0)  # directional: magnitude

    if indicator == "CVD_14d":
        v = c["cvd14d"]
        sign = 1 if v > 0 else -1 if v < 0 else 0
        if strategy == "GRID_LONG":
            return 0.9 if sign > 0 else 0.2 if sign < 0 else 0.5
        if strategy == "GRID_SHORT":
            return 0.9 if sign < 0 else 0.2 if sign > 0 else 0.5
        if strategy == "GRID_NEUTRAL":
            return 0.5  # indifferent to CVD direction
        return 0.7 if sign != 0 else 0.4  # directional likes a flow lean

    if indicator == "flow":
        v = c["flow"]  # -100..100 buy/sell imbalance
        mag = min(abs(v) / 20, 1.0)
        if strategy == "GRID_LONG":
            return mag if v > 0 else 0.3
        if strategy == "GRID_SHORT":
            return mag if v < 0 else 0.3
        if strategy == "GRID_NEUTRAL":
            return max(0.2, 1.0 - mag)  # balanced flow = ranging
        return mag

    if indicator == "OI_change":
        return min(abs(c["oi_change"]) / 5, 1.0)

    if indicator == "structure":
        return _dir_map(c["structure"], strategy)

    if indicator == "trend_daily":
        return _dir_map(c["trend_daily"], strategy)

    return 0.5


def _context(metrics: dict, regime: dict) -> dict:
    metrics = metrics or {}
    regime = regime or {}
    adx = metrics.get("adx") or {}
    return {
        "adx": adx.get("adx", 0.0),
        "adx_slope": (regime.get("adxSlope") or {}).get("adx_slope", "FLAT"),
        "bb_bw": metrics.get("bbBw", 0.0),
        "atr_pct": metrics.get("atrPct", 0.0),
        "er": (regime.get("er") or {}).get("er_value"),
        "hurst": (regime.get("hurst") or {}).get("hurst_daily"),
        "rsi": metrics.get("rsi", 50.0),
        "funding": metrics.get("funding", 0.0),
        "cvd14d": metrics.get("cvd14d", 0.0),
        "flow": metrics.get("flow", 0.0),
        "oi_change": metrics.get("oiChange", 0.0),
        "structure": metrics.get("structure4h", "Neutral"),
        "trend_daily": regime.get("trendDaily", "Neutral"),
    }


def calc_matrix(metrics: dict, regime: dict | None = None) -> dict:
    """Score all four strategies. Returns scores, the winning strategy, and a
    per-strategy indicator breakdown (sorted by contribution). Never raises."""
    cfg = CFG["MATRIX"]
    weights = cfg["WEIGHTS"]
    c = _context(metrics, regime)

    scores: dict[str, float] = {}
    breakdown: dict[str, list[dict]] = {}
    for si, strategy in enumerate(STRATEGIES):
        wsum = 0.0
        total = 0.0
        rows = []
        for indicator, wlist in weights.items():
            w = wlist[si]
            n = float(_normalize(indicator, c, strategy))  # coerce: never np.float64 in JSON
            wsum += w * n
            total += w
            rows.append({
                "indicator": indicator, "weight": w,
                "normalized": round(n, 3), "contribution": round(w * n, 2),
            })
        scores[strategy] = round(wsum / total * 100, 1) if total else 0.0
        breakdown[strategy] = sorted(rows, key=lambda r: r["contribution"], reverse=True)

    winner = max(scores, key=scores.get)
    return {
        "scores": scores,
        "winner": winner,
        "winnerScore": scores[winner],
        "breakdown": breakdown,
        "version": cfg["VERSION"],
    }
