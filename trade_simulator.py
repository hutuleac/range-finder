"""Grid bot simulation engine — Phase 2.

Replays 4H candles through a grid level array to generate virtual BUY/SELL fills.
Each level index i represents a position "bought at levels[i], sell target at levels[i+1]".
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np

from config import GRID_CONFIG
from data_fetcher import fetch_klines
from grid_calculator import calc_grid_stop_loss, calc_grid_take_profit
from trade_logger import (
    SimulatedTrade,
    as_utc,
    close_simulated_trade,
    create_simulated_trade,
    get_active_trades,
    get_simulated_trade,
    get_trade_fills,
    save_simulation_update,
)

log = logging.getLogger("pyonex.simulator")

_THROTTLE_SEC = 3600   # skip re-simulation if updated less than this many seconds ago
_KLINE_LIMIT  = 500    # ~83 days of 4H candles


# ─────────────────────────────────────────────────────────────────────
#  Grid math
# ─────────────────────────────────────────────────────────────────────

def build_grid_levels(range_low: float, range_high: float, num_grids: int) -> list[float]:
    return [float(v) for v in np.linspace(range_low, range_high, num_grids + 1)]


def initial_inventory(levels: list[float], entry_price: float) -> list[int]:
    """Level indices strictly below entry_price are pre-bought at grid open."""
    return [i for i, lv in enumerate(levels[:-1]) if lv < entry_price]


# ─────────────────────────────────────────────────────────────────────
#  Candle simulation
# ─────────────────────────────────────────────────────────────────────

def process_candle(
    inventory: list[int],
    levels: list[float],
    o: float, h: float, l: float, c: float,
    candle_ts: float,
    fee_pct: float,
    per_grid_capital: float | None,
) -> list[dict]:
    """Process one 4H candle against the grid. Mutates inventory. Returns fill records.

    Model: open is the reference price.
      - Price dropped from o to l  → BUY at any level[i] in [l, o)
      - Price rose   from o to h  → SELL at any level[i+1] in (o, h] where i is in inventory
    For bearish candles (c < o), process SELLs first to avoid pairing same-candle buy+sell.
    """
    fills: list[dict] = []
    is_bull = c >= o

    def do_buys() -> None:
        for i in range(len(levels) - 1):
            lv = levels[i]
            if l <= lv < o and i not in inventory:
                inventory.append(i)
                fills.append({
                    "action": "BUY", "level_idx": i, "level": lv,
                    "paired_level": None, "pnl_pct": None, "pnl_usd": None,
                    "candle_ts": candle_ts,
                })

    def do_sells() -> None:
        # Process from highest level down so the first eligible pair wins
        for i in range(len(levels) - 1, 0, -1):
            lv = levels[i]
            if o < lv <= h and (i - 1) in inventory:
                inventory.remove(i - 1)
                raw_pnl = (lv - levels[i - 1]) / levels[i - 1]
                net_pnl = raw_pnl - 2 * fee_pct
                pnl_usd = net_pnl * per_grid_capital if per_grid_capital is not None else None
                fills.append({
                    "action": "SELL", "level_idx": i, "level": lv,
                    "paired_level": levels[i - 1], "pnl_pct": net_pnl, "pnl_usd": pnl_usd,
                    "candle_ts": candle_ts,
                })

    if is_bull:
        do_buys()
        do_sells()
    else:
        do_sells()
        do_buys()

    return fills


# ─────────────────────────────────────────────────────────────────────
#  P&L calculation
# ─────────────────────────────────────────────────────────────────────

def calc_pnl(trade: SimulatedTrade, current_price: float) -> dict:
    """Compute realized + unrealized P&L from stored fills and current inventory."""
    fills = get_trade_fills(trade.id)
    levels = build_grid_levels(trade.range_low, trade.range_high, trade.num_grids)
    num_grids = trade.num_grids
    per_grid = trade.capital / num_grids if trade.capital else None

    sell_fills = [f for f in fills if f.action == "SELL"]
    realized_pct_raw = sum(f.pnl_pct for f in sell_fills if f.pnl_pct is not None)
    realized_usd = sum(f.pnl_usd for f in sell_fills if f.pnl_usd is not None) if per_grid else 0.0

    inventory = trade.inventory or []
    unrealized_pct_raw = sum(
        (current_price - levels[i]) / levels[i] for i in inventory if i < len(levels)
    )
    unrealized_usd = (
        sum((current_price - levels[i]) / levels[i] * per_grid for i in inventory if i < len(levels))
        if per_grid else 0.0
    )

    # Normalize to total capital (each grid slot = 1/num_grids of capital)
    realized_pct   = realized_pct_raw   / num_grids * 100 if num_grids else 0.0
    unrealized_pct = unrealized_pct_raw / num_grids * 100 if num_grids else 0.0
    total_pct      = realized_pct + unrealized_pct
    total_usd      = realized_usd + unrealized_usd if per_grid else None

    return {
        "realized_pct":   round(realized_pct, 3),
        "unrealized_pct": round(unrealized_pct, 3),
        "total_pct":      round(total_pct, 3),
        "total_usd":      round(total_usd, 2) if total_usd is not None else None,
        "cycle_count":    len(sell_fills),
        "open_positions": len(inventory),
        "buy_fills":      len([f for f in fills if f.action == "BUY"]),
        "total_fills":    len(fills),
    }


# ─────────────────────────────────────────────────────────────────────
#  Open / close
# ─────────────────────────────────────────────────────────────────────

def open_trade(
    payload: dict,
    symbol: str,
    capital: float | None = None,
    profile: str = "moderate",
) -> int:
    """Create a SimulatedTrade from a Range Finder payload. Returns trade ID."""
    m          = payload["metrics"]
    score_info = payload["scoreInfo"]
    direction  = payload["direction"]
    rng        = payload["range"]
    grid_count = payload["gridCount"]
    mode       = payload["mode"]

    entry_price = float(m.get("currClose", 0.0))
    num_grids   = int(grid_count["recommended"])
    range_low   = float(rng["rangeLow"])
    range_high  = float(rng["rangeHigh"])

    sl = calc_grid_stop_loss(range_low, profile)
    tp = calc_grid_take_profit(range_high, profile)

    setup_score_val = None
    sig = payload.get("signalInfo") or {}
    if isinstance(sig, dict):
        setup_score_val = sig.get("setup_score")

    levels    = build_grid_levels(range_low, range_high, num_grids)
    inventory = initial_inventory(levels, entry_price)

    trade = SimulatedTrade(
        symbol            = symbol,
        entry_price       = entry_price,
        range_low         = range_low,
        range_high        = range_high,
        num_grids         = num_grids,
        direction         = direction["type"],
        grid_mode         = mode["mode"],
        grid_score        = float(score_info["score"]),
        setup_score       = float(setup_score_val) if setup_score_val is not None else None,
        stop_loss         = sl,
        take_profit       = tp,
        capital           = capital,
        profile           = profile,
        inventory         = inventory,
        last_candle_close = entry_price,
        snapshot          = payload,
    )
    return create_simulated_trade(trade)


def close_trade(trade_id: int, price: float, reason: str = "Manual close") -> None:
    close_simulated_trade(trade_id, reason=reason, price=price)


# ─────────────────────────────────────────────────────────────────────
#  Simulation update
# ─────────────────────────────────────────────────────────────────────

def update_simulation(trade_id: int) -> dict:
    """Fetch new 4H candles since last update, run grid fills, check SL/TP."""
    trade = get_simulated_trade(trade_id)
    if trade is None:
        return {"error": "trade not found"}
    if trade.status != "ACTIVE":
        return {"status": trade.status, "new_fills": 0}

    # Throttle: don't re-simulate if updated recently
    if trade.last_simulated_at is not None:
        age = (datetime.now(timezone.utc) - as_utc(trade.last_simulated_at)).total_seconds()
        if age < _THROTTLE_SEC:
            return {"status": "throttled", "age_sec": int(age), "new_fills": 0}

    raw = fetch_klines(trade.symbol, "4h", _KLINE_LIMIT)
    if not raw:
        return {"error": f"no klines for {trade.symbol}"}

    # On first run last_candle_ts is None — use opened_at so we don't replay history
    last_ts = (
        trade.last_candle_ts
        if trade.last_candle_ts is not None
        else as_utc(trade.opened_at).timestamp() * 1000
    )
    new_candles = [r for r in raw if float(r[0]) > last_ts]
    if not new_candles:
        return {"status": "up_to_date", "new_fills": 0}

    levels          = build_grid_levels(trade.range_low, trade.range_high, trade.num_grids)
    fee_pct         = float(GRID_CONFIG["FEE_PCT"])
    per_grid        = trade.capital / trade.num_grids if trade.capital else None
    inventory       = list(trade.inventory or [])
    prev_close      = trade.last_candle_close or trade.entry_price
    all_fills: list[dict] = []
    last_processed_ts     = last_ts
    last_processed_close  = prev_close

    for row in new_candles:
        ts   = float(row[0])
        o, h, l, c = float(row[1]), float(row[2]), float(row[3]), float(row[4])

        fills = process_candle(inventory, levels, o, h, l, c, ts, fee_pct, per_grid)
        all_fills.extend(fills)
        last_processed_ts    = ts
        last_processed_close = c

    current_price = last_processed_close

    # Determine new status
    new_status   = "ACTIVE"
    close_reason = None
    close_price  = None
    if current_price <= trade.stop_loss:
        new_status   = "SL_HIT"
        close_reason = f"SL hit · price {current_price:.4f} ≤ SL {trade.stop_loss:.4f}"
        close_price  = current_price
    elif current_price >= trade.take_profit:
        new_status   = "TP_HIT"
        close_reason = f"TP hit · price {current_price:.4f} ≥ TP {trade.take_profit:.4f}"
        close_price  = current_price

    save_simulation_update(
        trade_id          = trade_id,
        inventory         = inventory,
        last_candle_ts    = last_processed_ts,
        last_candle_close = last_processed_close,
        fills             = all_fills,
        new_status        = new_status,
        close_reason      = close_reason,
        close_price       = close_price,
    )

    log.info(
        "%s trade #%d: %d new candles, %d fills, status=%s",
        trade.symbol, trade_id, len(new_candles), len(all_fills), new_status,
    )

    return {
        "status":      new_status,
        "new_fills":   len(all_fills),
        "sell_fills":  len([f for f in all_fills if f["action"] == "SELL"]),
        "candles":     len(new_candles),
        "price":       current_price,
    }


def update_all_active(silent: bool = False) -> list[dict]:
    """Update every ACTIVE simulated trade. Called on Trade Monitor page load."""
    results = []
    for trade in get_active_trades():
        try:
            r = update_simulation(trade.id)
            r["trade_id"] = trade.id
            r["symbol"]   = trade.symbol
            results.append(r)
        except Exception as exc:  # noqa: BLE001
            log.warning("simulation update failed for trade #%d: %s", trade.id, exc)
            if not silent:
                raise
    return results
