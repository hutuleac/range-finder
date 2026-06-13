"""fsm.py — Phase 2.5 volatility-cycle regime classifier (range-finder-native).

States (the volatility cycle):  COIL → EXPANSION → TREND → EXHAUSTION → NEUTRAL

This is a range-finder-native HEURISTIC, adapted from Double-main/core/regime_fsm.py.
It is NOT a parity port. Double's FSM consumes inputs range-finder does not have
(1H ADX, swing_phase, compression_ratio, 4H BB-band break). We substitute the
available 4H inputs and INVENT thresholds — they are UNCALIBRATED, with no ground
truth to parity-test against (see IMPROVEMENT_PLAN.md "Phase 2.5 / FSM reclassified").

Role: a SLOW regime FRAME (grid-vs-directional bias + a multi-day directional read),
NOT a fast entry trigger. The state is allowed to lag a few hours; timing belongs to
the Signal Scanner. Use it to frame "is this a grid window or a directional window",
not to fire entries.

Input adaptations (4H substitutes for Double's 1H/snapshot fields):
    COIL       ← metrics["squeeze"]["squeeze"] / metrics["bb"]["label"]=="squeeze"
                 (compression proxy; Double used compression_ratio < 0.40)
    EXPANSION  ← price vs metrics["bb"] upper/lower band (4H)
                 + regime["adxSlope"]["adx_slope"]=="RISING" + 4H ADX above a floor
    TREND      ← regime["er"]["er_regime"]=="TRENDING" + high 4H ADX
                 + a directional read from metrics["structure4h"]
    EXHAUSTION ← directional metrics["structure4h"] + metrics["rsi"] stretched
                 + adx_slope PEAKED/FALLING  (Double used 1H ADX + swing_phase)

Priority order (faithful to Double's classify() if-ladder — NOTE this differs from
the cycle NAME order): COIL → EXPANSION → EXHAUSTION → TREND → NEUTRAL.
Compression dominates; a fresh break overrides; a late+stretched+rolling-over trend
is EXHAUSTION before it is TREND; strong clean directional is TREND; else NEUTRAL.

Pure logic, no I/O. Thresholds live in CFG["FSM"] and are commented as heuristics.
"""
from __future__ import annotations

from config import CFG

# ── States ───────────────────────────────────────────────────────────────────
COIL       = "COIL"        # compressed / coiling — low vol, no trend (the spring)
EXPANSION  = "EXPANSION"   # the break — vol releasing, price past the band, ADX rising
TREND      = "TREND"       # established directional move — high ADX, trending ER
EXHAUSTION = "EXHAUSTION"  # trend ending — stretched RSI + ADX rolling over
NEUTRAL    = "NEUTRAL"     # range / chop — the default
UNKNOWN    = "UNKNOWN"     # hard failure / un-buildable inputs

STATES = (COIL, EXPANSION, TREND, EXHAUSTION, NEUTRAL)


def _struct_dir(structure: str) -> str:
    """LONG/SHORT/'' from a 4H market-structure label."""
    s = (structure or "").lower()
    if "bull" in s:
        return "LONG"
    if "bear" in s:
        return "SHORT"
    return ""


def classify(features: dict) -> dict:
    """Label one symbol from its FSM feature dict.

    Returns {state, direction, reason}. `direction` is LONG/SHORT for the
    directional states (the FSM's bias) and NEUTRAL for COIL / NEUTRAL.

    For EXHAUSTION, `direction` is the REVERSAL bias (opposite of the exhausting
    trend) — faithful to Double's regime_fsm (a stretched, rolling-over uptrend
    biases SHORT). Tolerant of missing fields: anything un-resolvable falls
    through to NEUTRAL; never raises.

    Priority (Double's if-ladder, not the cycle name order):
    COIL → EXPANSION → EXHAUSTION → TREND → NEUTRAL.
    """
    f = features or {}
    fc = CFG["FSM"]

    squeeze = bool(f.get("squeeze"))
    bb_squeeze = f.get("bb_label") == "squeeze"
    price = f.get("price")
    bb_upper = f.get("bb_upper")
    bb_lower = f.get("bb_lower")
    adx = f.get("adx") or 0.0
    adx_slope = (f.get("adx_slope") or "FLAT").upper()
    er_regime = (f.get("er_regime") or "").upper()
    rsi = f.get("rsi")
    struct_dir = _struct_dir(f.get("structure4h", "Neutral"))

    # 1) COIL — compressed / coiling (compression proxy dominates).
    if squeeze or bb_squeeze:
        return {"state": COIL, "direction": "NEUTRAL",
                "reason": "compressed (squeeze/bb-tight)"}

    # 2) EXPANSION — the break: price past the 4H band while ADX is rising.
    brk = ""
    if price and bb_upper and price > bb_upper:
        brk = "LONG"
    elif price and bb_lower and price < bb_lower:
        brk = "SHORT"
    if brk and adx_slope == "RISING" and adx >= fc["ADX_FLOOR"]:
        return {"state": EXPANSION, "direction": brk,
                "reason": f"bb-break {brk} + ADX rising ({adx:.0f})"}

    # 3) EXHAUSTION — directional structure, RSI stretched, ADX rolling over.
    stretched = rsi is not None and (
        (struct_dir == "LONG" and rsi >= fc["RSI_HIGH"]) or
        (struct_dir == "SHORT" and rsi <= fc["RSI_LOW"]))
    rolling_over = adx_slope in ("PEAKED", "FALLING")
    if struct_dir and adx >= fc["ADX_FLOOR"] and stretched and rolling_over:
        rev = "SHORT" if struct_dir == "LONG" else "LONG"   # reversal bias
        return {"state": EXHAUSTION, "direction": rev,
                "reason": f"{struct_dir} structure stretched (RSI {rsi:.0f}) + ADX {adx_slope}"}

    # 4) TREND — established directional: trending ER + high ADX + a structure read.
    if er_regime == "TRENDING" and adx >= fc["ADX_HIGH"] and struct_dir:
        return {"state": TREND, "direction": struct_dir,
                "reason": f"ER trending + ADX {adx:.0f} + {struct_dir}"}

    # 5) NEUTRAL — range / chop (default).
    return {"state": NEUTRAL, "direction": "NEUTRAL",
            "reason": f"no coil/break/trend (adx {adx:.0f}, er {er_regime or 'n/a'})"}


def extract_features(metrics: dict, regime: dict) -> dict:
    """Range-finder-native feature extraction (NOT Double's extract_features).

    Pulls only keys range-finder produces. Tolerant of missing blocks — a lean or
    older cached payload yields Nones that classify() degrades to NEUTRAL.
    """
    m = metrics or {}
    r = regime or {}
    bb = m.get("bb") or {}
    sq = m.get("squeeze") or {}
    adx_block = m.get("adx") or {}
    er = r.get("er") or {}
    adx_slope = r.get("adxSlope") or {}

    return {
        "squeeze": bool(sq.get("squeeze")),
        "bb_label": bb.get("label"),
        "price": m.get("currClose"),
        "bb_upper": bb.get("upper"),
        "bb_lower": bb.get("lower"),
        "adx": adx_block.get("adx", 0.0),
        "adx_slope": adx_slope.get("adx_slope", "FLAT"),
        "er_regime": er.get("er_regime", "UNKNOWN"),
        "rsi": m.get("rsi"),
        "structure4h": m.get("structure4h", "Neutral"),
    }


def build_fsm(metrics: dict, regime: dict) -> dict:
    """Assemble the FSM verdict from the 4H metrics + the Phase 2 regime layer.

    Returns {state, direction, reason}. Wrapped so a hard failure degrades to
    state="UNKNOWN" rather than crashing refresh_one — never raises.
    """
    try:
        return classify(extract_features(metrics, regime))
    except Exception as e:  # noqa: BLE001
        return {"state": UNKNOWN, "direction": "NEUTRAL", "reason": str(e)}
