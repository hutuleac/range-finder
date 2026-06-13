"""Pyonex cron entry — refresh metrics cache for every watched pair.

Run:
    python -m refresh_data
"""
from __future__ import annotations

import logging
import os
import sys
import time

from config import CFG, DEFAULT_PAIRS
from data_fetcher import fetch_funding, fetch_klines, fetch_oi
from grid_calculator import (
    assess_grid_viability,
    calc_grid_score,
    calc_range_from_atr,
    calc_recommended_grid_count,
    estimate_grid_duration,
    get_ticker_grid_profile,
    grid_headline_label,
    select_grid_direction,
    select_grid_mode,
)
from fsm import build_fsm
from indicators import OIData, get_advanced_metrics, parse_klines
from matrix import calc_matrix
from regime import build_regime
from signal_engine import calc_setup_score
from trade_logger import init_db, upsert_metrics

logging.basicConfig(
    level=os.getenv("PYONEX_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("pyonex.refresh")


def build_mtf(symbol: str) -> dict:
    """Fetch daily/weekly closes for the regime layer (Phase 2 consumer).

    Returns empty lists on fetch failure so downstream regime indicators
    degrade to UNKNOWN rather than crashing the card. Daily/weekly are a
    separate, optional spine — they never block the 4H pipeline.
    """
    df_daily = parse_klines(fetch_klines(symbol, "1d", CFG["KLINES_DAILY"]))
    df_weekly = parse_klines(fetch_klines(symbol, "1w", CFG["KLINES_WEEKLY"]))
    return {
        "dailyCloses": df_daily["Close"].tolist() if not df_daily.empty else [],
        "weeklyCloses": df_weekly["Close"].tolist() if not df_weekly.empty else [],
    }


def refresh_one(symbol: str) -> dict | None:
    t0 = time.time()
    raw_main = fetch_klines(symbol, "4h", CFG["KLINES_MAIN"])
    raw_5d   = raw_main[-CFG["KLINES_5D"]:]
    raw_14d  = raw_main[-CFG["KLINES_14D"]:]
    raw_30d  = raw_main[-CFG["KLINES_30D"]:]
    raw_flow = fetch_klines(symbol, "1h", CFG["FLOW_LIMIT"])
    if not raw_main:
        log.warning("skip %s — no main klines", symbol)
        return None

    df_main = parse_klines(raw_main)
    df_5d = parse_klines(raw_5d)
    df_14d = parse_klines(raw_14d)
    df_30d = parse_klines(raw_30d)
    df_flow = parse_klines(raw_flow)

    oi = fetch_oi(symbol) or OIData()
    funding = fetch_funding(symbol)

    metrics = get_advanced_metrics(df_main, df_5d, df_14d, df_30d, df_flow, oi, funding)
    if not metrics:
        return None

    # Derive range + direction + score
    profile = get_ticker_grid_profile(symbol)
    structure4h = metrics.get("structure4h", "Neutral")
    atr_pct = metrics.get("atrPct", 0.0)
    price = metrics.get("currClose", 0.0)

    # Regime + matrix first — the matrix GRID_NEUTRAL column is the headline
    # grid score and its grid columns drive direction (headline-swap).
    mtf = build_mtf(symbol)
    regime = build_regime(mtf, df_main)
    matrix = calc_matrix(metrics, regime)

    score = matrix["scores"]["GRID_NEUTRAL"]
    headline_label = grid_headline_label(score)
    direction = select_grid_direction(matrix["scores"])

    # Legacy 0–10 grid score kept for the score-breakdown bars / recs only.
    neutral_range = calc_range_from_atr(price, atr_pct, profile["rangeMultiplier"], "Neutral")
    metrics_with_range = {**metrics, "gridRange": neutral_range}
    score_info = calc_grid_score(metrics_with_range)

    directional_range = calc_range_from_atr(price, atr_pct, profile["rangeMultiplier"], direction["type"])
    mode = select_grid_mode(directional_range["rangeWidthPct"])
    recommended = calc_recommended_grid_count(
        directional_range["rangeHigh"], directional_range["rangeLow"],
        target_net_pct=profile["targetNetPct"],
        min_grid_floor_pct=profile["minNetPct"],
        max_grids=profile["maxGrids"],
    )
    duration = estimate_grid_duration(directional_range["rangeWidthPct"], atr_pct)

    viability = assess_grid_viability(
        atr_pct=atr_pct,
        adx=(metrics.get("adx") or {}).get("adx", 0.0),
        rsi=metrics.get("rsi", 50.0),
        bb_bw=metrics.get("bbBw", 0.0),
        structure=structure4h,
    )

    signal_info = calc_setup_score(metrics, df_main)

    fsm = build_fsm(metrics, regime)

    payload = {
        "metrics": metrics,
        "profile": profile,
        "gridHeadline": {"score": score, "label": headline_label},
        "scoreInfo": score_info,
        "direction": direction,
        "range": directional_range,
        "mode": mode,
        "gridCount": recommended,
        "duration": duration,
        "viability": viability,
        "signalInfo": signal_info,
        "mtf": mtf,
        "regime": regime,
        "matrix": matrix,
        "fsm": fsm,
    }
    upsert_metrics(symbol, price, score, direction["type"], payload)
    log.info(
        "%-12s price=%.4f score=%.1f dir=%s via=%s %.2fs",
        symbol, price, score, direction["type"], viability["viable"], time.time() - t0,
    )
    return payload


def main(pairs: list[str] | None = None) -> int:
    init_db()
    pairs = pairs or DEFAULT_PAIRS
    ok = 0
    for sym in pairs:
        try:
            if refresh_one(sym):
                ok += 1
        except Exception:  # noqa: BLE001
            log.exception("refresh %s failed", sym)
    log.info("done: %d/%d pairs", ok, len(pairs))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
