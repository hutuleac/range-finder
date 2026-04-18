"""Pyonex grid math — line-by-line port of grid.js. Pure functions."""
from __future__ import annotations

from typing import Literal

from config import CFG, GRID_CONFIG

GridType = Literal["Long", "Short", "Neutral"]
Profile = Literal["stable", "moderate", "volatile"]


def calc_grid_profit_per_grid(
    range_high: float, range_low: float, grid_count: int,
    fee_pct: float = GRID_CONFIG["FEE_PCT"], is_geometric: bool = False,
) -> dict:
    if grid_count <= 0 or range_low <= 0:
        return {"grossPct": 0.0, "feeCost": fee_pct * 2, "netPct": 0.0, "isViable": False}
    if is_geometric:
        gross = (range_high / range_low) ** (1.0 / grid_count) - 1.0
    else:
        gross = (range_high - range_low) / range_low / grid_count
    fee_cost = fee_pct * 2
    net = gross - fee_cost
    return {
        "grossPct": gross,
        "feeCost": fee_cost,
        "netPct": net,
        "isViable": net >= GRID_CONFIG["MIN_NET_PCT"],
    }


def calc_grid_capital_per_grid(total_capital: float, grid_count: int) -> float:
    return total_capital / grid_count if grid_count > 0 else 0.0


def calc_drawdown_scenario(
    total_capital: float, range_low: float, current_price: float, crash_target_price: float,
) -> dict:
    if range_low <= 0:
        return {"coinsHeld": 0.0, "valueAtCrash": 0.0, "drawdownUSDT": 0.0, "drawdownPct": 0.0}
    coins = total_capital / range_low
    value = coins * crash_target_price
    dd = total_capital - value
    return {
        "coinsHeld": coins,
        "valueAtCrash": value,
        "drawdownUSDT": dd,
        "drawdownPct": dd / total_capital if total_capital else 0.0,
    }


def calc_recommended_grid_count(
    range_high: float, range_low: float,
    target_net_pct: float = GRID_CONFIG["TARGET_NET_PCT"],
    fee_pct: float = GRID_CONFIG["FEE_PCT"],
) -> dict:
    if range_low <= 0:
        return {"recommended": 1, "min": 1, "max": 1}
    total_range = (range_high - range_low) / range_low
    fee_cost = fee_pct * 2
    recommended = max(1, round(total_range / (target_net_pct + fee_cost)))

    min_g = 1
    for g in range(1, 201):
        net = total_range / g - fee_cost
        if net > 0:
            min_g = g
            break

    max_g = min(100, round(total_range / (0.001 + fee_cost)))
    return {
        "recommended": max(min_g, min(recommended, 100)),
        "min": min_g,
        "max": max(min_g, max_g),
    }


def calc_range_from_atr(
    current_price: float, atr_pct: float,
    multiplier: float = GRID_CONFIG["ATR_MULTIPLIER_DEFAULT"],
    grid_type: GridType = "Neutral",
) -> dict:
    offset = (atr_pct / 100.0) * multiplier
    if grid_type == "Long":
        range_low = current_price * (1 - offset * 2)
        range_high = current_price * (1 + offset * 0.25)
    elif grid_type == "Short":
        range_low = current_price * (1 - offset * 0.25)
        range_high = current_price * (1 + offset * 2)
    else:
        range_low = current_price * (1 - offset)
        range_high = current_price * (1 + offset)
    width_pct = (range_high - range_low) / range_low * 100 if range_low else 0.0
    return {"rangeLow": range_low, "rangeHigh": range_high, "rangeWidthPct": width_pct}


def select_grid_direction(structure4h: str, score: float) -> dict:
    d = GRID_CONFIG["DIRECTION"]
    if structure4h == "Bullish" and score >= d["LONG_MIN_SCORE"]:
        return {
            "type": "Long", "label": "Long Grid",
            "reason": "Bullish structure — range biased below price to accumulate on dips",
        }
    if structure4h == "Bearish" and score < d["SHORT_MAX_SCORE"]:
        return {
            "type": "Short", "label": "Short Grid",
            "reason": "Bearish structure — range biased above price to sell into pumps",
        }
    return {
        "type": "Neutral", "label": "Neutral Grid",
        "reason": "No strong directional bias — range straddles current price",
    }


def select_grid_mode(range_width_pct: float) -> dict:
    threshold = GRID_CONFIG["GEOMETRIC_THRESHOLD_PCT"]
    if range_width_pct >= threshold:
        return {
            "mode": "Geometric",
            "reason": f"Wide range (>={threshold}%) — geometric grids maintain consistent % profit per step",
        }
    return {
        "mode": "Arithmetic",
        "reason": f"Narrow range (<{threshold}%) — arithmetic grids are simpler and effective",
    }


def calc_grid_stop_loss(range_low: float, profile: Profile = "moderate") -> float:
    buf = GRID_CONFIG["SL_BUFFERS"].get(profile, GRID_CONFIG["SL_BUFFERS"]["moderate"])
    return range_low * (1 - buf)


def calc_grid_take_profit(range_high: float, profile: Profile = "moderate") -> float:
    buf = GRID_CONFIG["TP_BUFFERS"].get(profile, GRID_CONFIG["TP_BUFFERS"]["moderate"])
    return range_high * (1 + buf)


def assess_grid_viability(atr_pct: float, adx: float, rsi: float, bb_bw: float, structure: str) -> dict:
    v = GRID_CONFIG["VIABILITY"]
    if adx > v["ADX_BLOCK"]:
        return {
            "viable": False,
            "reason": f"ADX={adx:.1f}: trend detected (>{v['ADX_BLOCK']}) — grid bots underperform in trending markets",
            "warning": None,
        }
    if rsi > v["RSI_BLOCK"]:
        return {
            "viable": False,
            "reason": f"RSI={rsi:.1f}: overbought (>{v['RSI_BLOCK']}) — wait for pullback before starting",
            "warning": None,
        }
    if bb_bw < v["BB_MIN"]:
        return {
            "viable": False,
            "reason": f"BB Bandwidth={bb_bw:.2f}%: too compressed (<{v['BB_MIN']}%) — insufficient volatility for grid profit",
            "warning": None,
        }
    if structure == "Bearish" and adx > v["BEARISH_ADX_BLOCK"]:
        return {
            "viable": False,
            "reason": f"Bearish structure + ADX={adx:.1f} (>{v['BEARISH_ADX_BLOCK']}): downtrend with momentum — high bot failure risk",
            "warning": None,
        }

    warnings: list[str] = []
    if atr_pct > v["ATR_WARN"]:
        warnings.append(f"ATR={atr_pct:.1f}%: elevated volatility — use Geometric mode and widen range")
    if rsi > v["RSI_WARN_HIGH"]:
        warnings.append(f"RSI={rsi:.1f}: elevated — mild overbought pressure")
    if rsi < v["RSI_WARN_LOW"]:
        warnings.append(f"RSI={rsi:.1f}: oversold — confirm structure before starting, price may continue lower")
    if structure == "Neutral":
        warnings.append("Neutral market structure — range may shift; monitor closely")

    return {
        "viable": True,
        "reason": "Market conditions suitable for grid bot",
        "warning": " | ".join(warnings) if warnings else None,
    }


def estimate_grid_duration(range_width_pct: float, atr_pct: float) -> dict:
    daily_range = atr_pct * 1.5
    if daily_range <= 0:
        return {"estDays": 0, "label": "—"}
    est_days = max(1, min(round(range_width_pct / daily_range), 30))
    if est_days <= 3:
        label = "1-3 days"
    elif est_days <= 7:
        label = "3-7 days"
    elif est_days <= 14:
        label = "1-2 weeks"
    else:
        label = "2-4 weeks"
    return {"estDays": est_days, "label": label}


def get_ticker_grid_profile(ticker: str) -> dict:
    t = ticker.split("/")[0].upper()
    profiles = {
        "BTC":  {"profile": "stable",   "rangeMultiplier": 2.5, "maxGrids": 30},
        "ETH":  {"profile": "stable",   "rangeMultiplier": 2.5, "maxGrids": 30},
        "BNB":  {"profile": "stable",   "rangeMultiplier": 2.5, "maxGrids": 30},
        "SOL":  {"profile": "moderate", "rangeMultiplier": 3.0, "maxGrids": 40},
        "TRX":  {"profile": "moderate", "rangeMultiplier": 3.0, "maxGrids": 40},
        "DOGE": {"profile": "moderate", "rangeMultiplier": 3.0, "maxGrids": 40},
        "XLM":  {"profile": "moderate", "rangeMultiplier": 3.0, "maxGrids": 40},
        "XRP":  {"profile": "moderate", "rangeMultiplier": 3.0, "maxGrids": 40},
        "SUI":  {"profile": "volatile", "rangeMultiplier": 3.5, "maxGrids": 50},
        "HYPE": {"profile": "volatile", "rangeMultiplier": 3.5, "maxGrids": 50},
    }
    return profiles.get(t, {"profile": "moderate", "rangeMultiplier": 3.0, "maxGrids": 40})


# ─────────────────────────────────────────────────────────────────────
#  Grid score — port of calcGridScore (grid.js)
# ─────────────────────────────────────────────────────────────────────
def calc_grid_score(m: dict | None) -> dict:
    if not m:
        return {"score": 0.0, "label": "AVOID", "components": [], "recs": []}

    adx = (m.get("adx") or {}).get("adx", 0.0)
    bb = m.get("bb") or {}
    bb_label = bb.get("label", "normal")
    bb_bw = m.get("bbBw", 0.0)
    rsi = m.get("rsi", 50.0)
    fund = abs(m.get("funding") or 0.0)
    rng = m.get("gridRange") or {}
    poc5d = m.get("poc5d", 0.0)
    poc14d = m.get("poc14d", 0.0)
    cvd_delta = abs(m.get("cvd5d") or 0.0)
    vol5d = max(m.get("volume5d") or 1.0, 1.0)
    is_lateral = (cvd_delta / vol5d) < CFG["CVD_LATERAL_RATIO"]

    components: list[dict] = []
    score = 0.0

    # ADX (max 3.0)
    if adx < 15:
        adx_score = 3.0; adx_lbl = "ideal range"
    elif adx < 20:
        adx_score = 2.0; adx_lbl = "low"
    elif adx < 25:
        adx_score = 1.0; adx_lbl = "mild"
    else:
        adx_score = 0.0; adx_lbl = "strong trend"
    components.append({"label": "ADX Trend", "score": adx_score, "max": 3.0,
                       "detail": f"ADX {adx:.1f} — {adx_lbl}"})
    score += adx_score

    # BB Width (max 2.0)
    if bb_label == "squeeze":
        bb_score = 2.0; bb_tag = "compressed [ok]"
    elif bb_label == "normal":
        bb_score = 1.0; bb_tag = "normal"
    else:
        bb_score = 0.0; bb_tag = "expanded [x]"
    components.append({"label": "BB Width", "score": bb_score, "max": 2.0,
                       "detail": f"{bb_bw:.1f}% — {bb_tag}"})
    score += bb_score

    # CVD lateral (max 1.5)
    cvd_score = 1.5 if is_lateral else 0.0
    components.append({
        "label": "CVD Flow", "score": cvd_score, "max": 1.5,
        "detail": "Lateral — no trend pressure [ok]" if is_lateral else "Directional — trend in progress [x]",
    })
    score += cvd_score

    # POC in range (max 2.0)
    poc_score = 0.0
    poc_detail = "Range not computed"
    rl = rng.get("rangeLow")
    rh = rng.get("rangeHigh")
    if rl is not None and rh is not None and poc5d > 0:
        in5 = rl <= poc5d <= rh
        in14 = rl <= poc14d <= rh
        if in5 and in14:
            poc_score = 2.0; poc_detail = "Both POC5d+14d in range [ok]"
        elif in5 or in14:
            poc_score = 1.0; poc_detail = "One POC in range [!]"
        else:
            poc_score = 0.0; poc_detail = "No POC in range — grid may miss magnet [x]"
    components.append({"label": "POC in Range", "score": poc_score, "max": 2.0, "detail": poc_detail})
    score += poc_score

    # RSI neutral (max 1.0)
    if 40 <= rsi <= 60:
        rsi_score = 1.0; rsi_tag = "neutral zone [ok]"
    elif 35 <= rsi <= 65:
        rsi_score = 0.5; rsi_tag = "acceptable"
    else:
        rsi_score = 0.0; rsi_tag = "extreme [x]"
    components.append({"label": "RSI Neutral", "score": rsi_score, "max": 1.0,
                       "detail": f"RSI {rsi:.1f} — {rsi_tag}"})
    score += rsi_score

    # Funding neutral (max 0.5)
    fund_score = 0.5 if fund < 0.05 else 0.0
    components.append({
        "label": "Funding", "score": fund_score, "max": 0.5,
        "detail": f"{(m.get('funding') or 0.0):.3f}% — {'neutral [ok]' if fund_score > 0 else 'elevated [!]'}",
    })
    score += fund_score

    # Squeeze bonus (new — Donchian/BB-confirmed range regime)
    sq = m.get("squeeze") or {}
    if sq.get("squeeze"):
        score = min(10.0, score + 0.5)
        components.append({"label": "Squeeze", "score": 0.5, "max": 0.5,
                           "detail": "BB + Donchian tight — prime grid window"})

    rounded = round(score * 10) / 10
    if rounded >= 8:
        label = "STRONG SETUP"
    elif rounded >= 6:
        label = "GOOD SETUP"
    elif rounded >= 4:
        label = "DEVELOPING"
    else:
        label = "AVOID"

    recs: list[str] = []
    if adx_score < 2.0:
        recs.append("Wait for ADX < 20 (trend too strong)" if adx >= 25
                    else "ADX improving — watch for drop below 20")
    if bb_score < 2.0:
        recs.append("Wait for BB compression (squeeze)" if bb_label == "expanded"
                    else "Watch for BB squeeze for optimal entry")
    if not is_lateral:
        recs.append("CVD directional — wait for sideways accumulation")
    if poc_score < 2.0 and rl is not None:
        recs.append("Consider widening range to include both POC5d and POC14d")
    if rsi_score < 0.5:
        recs.append(f"RSI {rsi:.0f} extreme — wait for 40-60 range")
    if fund_score == 0:
        recs.append("Funding elevated — crowded trade, higher liquidation risk")

    return {"score": rounded, "label": label, "components": components, "recs": recs}
