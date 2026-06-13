"""Background polling loop for Bot Monitor — runs every 10 minutes.

Pure module: no Streamlit imports. Called by the APScheduler job in app.py.
"""
from __future__ import annotations

import logging

from bot_advisor import _build_restart, assess_bot_health
from grid_calculator import calc_grid_stop_loss, calc_grid_take_profit, get_ticker_grid_profile
from pionex_client import PionexClient
from trade_logger import (
    BotAssessment,
    BotOpenSnapshot,
    get_open_snapshot,
    save_bot_assessment,
    save_open_snapshot,
)

log = logging.getLogger("pyonex.bot_monitor_loop")


def _resolve_symbol(raw_bot: dict) -> str:
    """Convert Pionex bot dict to ccxt-style pair string (e.g. BTC/USDT)."""
    base  = raw_bot.get("base", "")
    quote = raw_bot.get("quote", "")
    if base and quote:
        return f"{base}/{quote}"
    sym = raw_bot.get("symbol", "")
    for quote_ccy in ("USDT", "USD", "BTC", "ETH"):
        if sym.endswith(quote_ccy):
            return f"{sym[:-len(quote_ccy)]}/{quote_ccy}"
    return sym


def _flatten_bot(raw_bot: dict) -> dict:
    """Merge buOrderData fields into top-level bot dict."""
    bot = {**raw_bot}
    order_data = raw_bot.get("buOrderData") or {}
    for key in ("upperPrice", "lowerPrice", "gridNum", "gridProfit", "realizedProfit",
                "baseAmount", "quoteAmount", "baseInvestment", "quoteInvestment"):
        if key in order_data and key not in bot:
            bot[key] = order_data[key]
    if "upperPrice" not in bot and "top" in order_data:
        bot["upperPrice"] = order_data["top"]
    if "lowerPrice" not in bot and "bottom" in order_data:
        bot["lowerPrice"] = order_data["bottom"]
    if "gridNum" not in bot and "row" in order_data:
        bot["gridNum"] = order_data["row"]
    return bot


def run_bot_monitor_cycle(payloads: dict[str, dict]) -> list[dict]:
    """Fetch live bots, assess each, persist open snapshots + assessments.

    Args:
        payloads: dict mapping symbol -> MetricsCache.payload dict.
    Returns:
        List of result dicts (one per assessed bot).
    """
    client = PionexClient()
    if not client.configured:
        log.debug("Pionex not configured — skipping bot monitor cycle")
        return []

    try:
        bots = client.list_running_bots()
    except Exception:
        log.exception("Failed to fetch bots from Pionex")
        return []

    results: list[dict] = []

    for raw_bot in bots:
        bot_id = raw_bot.get("buOrderId", "")
        if not bot_id:
            continue

        symbol = _resolve_symbol(raw_bot)
        p = payloads.get(symbol)
        if not p:
            log.debug("No cached metrics for %s — skipping", symbol)
            continue

        bot     = _flatten_bot(raw_bot)
        metrics = {**p.get("metrics", {})}
        metrics["_grid_score"]  = p.get("scoreInfo", {}).get("score", 0.0)
        metrics["_setup_score"] = (p.get("signalInfo") or {}).get("score", 0.0)
        metrics["_matrix_scores"] = (p.get("matrix") or {}).get("scores")
        signal_info = p.get("signalInfo")

        if not metrics.get("currClose"):
            log.debug("No currClose for %s — skipping", symbol)
            continue

        # Open snapshot — write once
        if get_open_snapshot(bot_id) is None:
            snap = BotOpenSnapshot(
                bot_id           = bot_id,
                symbol           = symbol,
                open_range_low   = float(bot.get("lowerPrice") or 0) or None,
                open_range_high  = float(bot.get("upperPrice") or 0) or None,
                open_grid_count  = int(bot.get("gridNum") or 0) or None,
                open_created_ms  = float(raw_bot.get("createTime") or 0) or None,
                open_adx         = (metrics.get("adx") or {}).get("adx"),
                open_rsi         = metrics.get("rsi"),
                open_bb_bw       = metrics.get("bbBw"),
                open_grid_score  = metrics["_grid_score"],
                open_setup_score = metrics["_setup_score"],
            )
            save_open_snapshot(snap)

        # Health assessment
        try:
            advice = assess_bot_health(bot, metrics, signal_info, symbol=symbol)
        except Exception:
            log.exception("assess_bot_health failed for %s", symbol)
            continue

        rec = advice["recommendation"]

        # Suggested parameters — always computed. grid_score (0–10) is persisted
        # as the snapshot diagnostic; restart direction comes from the matrix.
        grid_score = metrics["_grid_score"]
        restart    = _build_restart(symbol, metrics, metrics.get("_matrix_scores"))
        if restart:
            profile = get_ticker_grid_profile(symbol)["profile"]
            sl = calc_grid_stop_loss(restart["rangeLow"], profile)
            tp = calc_grid_take_profit(restart["rangeHigh"], profile)
        else:
            sl = tp = None

        assessment = BotAssessment(
            bot_id      = bot_id,
            symbol      = symbol,
            action      = rec["action"],
            severity    = rec["severity"],
            reason      = rec["reason"],
            price       = metrics.get("currClose"),
            price_pct   = advice["position"]["pct"],
            adx         = (metrics.get("adx") or {}).get("adx"),
            rsi         = metrics.get("rsi"),
            bb_bw       = metrics.get("bbBw"),
            grid_score  = grid_score,
            setup_score = metrics["_setup_score"],
            suggested_range_low   = restart["rangeLow"]  if restart else None,
            suggested_range_high  = restart["rangeHigh"] if restart else None,
            suggested_grid_count  = restart["grids"]     if restart else None,
            suggested_stop_loss   = sl,
            suggested_take_profit = tp,
            suggested_grid_mode   = restart["mode"]      if restart else None,
            suggested_duration    = restart["duration"]  if restart else None,
        )
        try:
            save_bot_assessment(assessment)
        except Exception:
            log.exception("Failed to save assessment for %s", symbol)
            continue

        results.append({
            "bot_id": bot_id, "symbol": symbol,
            "action": rec["action"], "restart": restart,
        })

    return results
