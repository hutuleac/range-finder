"""Bot advisor — health assessment and recommendations for active grid bots."""
from __future__ import annotations

import time

from config import BOT_MONITOR_CFG as BC


def _check_price_position(price: float, lower: float, upper: float) -> dict:
    rng = upper - lower
    if rng <= 0:
        return {"zone": "UNKNOWN", "pct": 50.0, "detail": "Invalid range"}
    pct = (price - lower) / rng * 100
    if pct < 0:
        return {"zone": "BELOW_RANGE", "pct": pct, "detail": f"Price {abs(pct):.1f}% below range"}
    if pct > 100:
        return {"zone": "ABOVE_RANGE", "pct": pct, "detail": f"Price {pct - 100:.1f}% above range"}
    if pct < 10:
        return {"zone": "NEAR_BOTTOM", "pct": pct, "detail": f"Price at {pct:.0f}% — near lower edge"}
    if pct > 90:
        return {"zone": "NEAR_TOP", "pct": pct, "detail": f"Price at {pct:.0f}% — near upper edge"}
    return {"zone": "IN_RANGE", "pct": pct, "detail": f"Price at {pct:.0f}% of range"}


def _check_trend(metrics: dict, signal_info: dict | None) -> dict:
    adx = (metrics.get("adx") or {}).get("adx", 0.0)
    sig_type = ((signal_info or {}).get("signal_type") or {}).get("type", "NONE")

    if adx > BC["ADX_EXIT"]:
        return {
            "aligned": False, "severity": "HIGH",
            "detail": f"ADX {adx:.1f} — strong trend, grid underperforms",
        }
    if adx > 25:
        return {
            "aligned": False, "severity": "MEDIUM",
            "detail": f"ADX {adx:.1f} — trend forming, monitor closely",
        }
    if sig_type in ("LONG_SETUP", "SHORT_SETUP"):
        return {
            "aligned": False, "severity": "MEDIUM",
            "detail": f"Signal Scanner: {sig_type.replace('_', ' ')} — regime may shift",
        }
    if sig_type == "GRID_WINDOW":
        return {"aligned": True, "severity": "NONE", "detail": "Grid-friendly conditions confirmed"}
    return {"aligned": True, "severity": "NONE", "detail": f"ADX {adx:.1f} — no strong trend"}


def _check_profit(bot: dict, price: float) -> dict:
    grid_profit = float(bot.get("gridProfit") or 0)
    realized = float(bot.get("realizedProfit") or 0)
    quote_inv = float(bot.get("quoteInvestment") or 0)
    base_inv = float(bot.get("baseInvestment") or 0)
    invested = quote_inv + base_inv * price if base_inv > 0 else quote_inv
    if invested <= 0:
        invested = 1.0

    grid_pct = grid_profit / invested * 100
    realized_pct = realized / invested * 100

    result = {
        "gridProfit": grid_profit,
        "gridProfitPct": grid_pct,
        "realized": realized,
        "realizedPct": realized_pct,
        "invested": invested,
    }

    if grid_pct >= BC["TP_PROFIT_PCT"]:
        result["signal"] = "TP"
        result["detail"] = f"Grid profit {grid_pct:.1f}% — above {BC['TP_PROFIT_PCT']}% target"
    elif realized_pct < BC["LOSS_WARN_PCT"]:
        result["signal"] = "LOSS"
        result["detail"] = f"Realized P&L {realized_pct:+.1f}% — significant loss"
    else:
        result["signal"] = "OK"
        result["detail"] = f"Grid profit {grid_pct:.1f}%"

    return result


def _check_duration(bot: dict) -> dict:
    created = int(bot.get("createTime") or 0)
    if created <= 0:
        return {"days": 0, "flag": False, "detail": "Unknown creation time"}
    days = (time.time() * 1000 - created) / 86400000
    flag = days > BC["MAX_DURATION_DAYS"]
    detail = f"Running {days:.0f} days"
    if flag:
        detail += f" — exceeds {BC['MAX_DURATION_DAYS']}d threshold"
    return {"days": days, "flag": flag, "detail": detail}


def _generate_recommendation(pos: dict, trend: dict, profit: dict, duration: dict) -> dict:
    zone = pos["zone"]

    # Out of range = immediate close
    if zone in ("BELOW_RANGE", "ABOVE_RANGE"):
        return {
            "action": "CLOSE_NOW",
            "reason": f"Bot inactive — price {pos['detail'].lower()}",
            "severity": "CRITICAL",
        }

    # Near edge + bearish trend = close
    if zone == "NEAR_BOTTOM" and not trend["aligned"]:
        return {
            "action": "CLOSE_NOW",
            "reason": f"Price near bottom + {trend['detail']}",
            "severity": "CRITICAL",
        }
    if zone == "NEAR_TOP" and not trend["aligned"]:
        return {
            "action": "TAKE_PROFIT",
            "reason": f"Price near top + {trend['detail']}",
            "severity": "HIGH",
        }

    # In range + trending hard = problem
    if not trend["aligned"] and trend["severity"] == "HIGH":
        if profit["signal"] == "TP":
            return {
                "action": "TAKE_PROFIT",
                "reason": f"{profit['detail']} + {trend['detail']}",
                "severity": "HIGH",
            }
        return {
            "action": "WARNING",
            "reason": trend["detail"],
            "severity": "MEDIUM",
        }

    # Profit target reached
    if profit["signal"] == "TP":
        return {
            "action": "TAKE_PROFIT",
            "reason": profit["detail"],
            "severity": "MEDIUM",
        }

    # Loss warning
    if profit["signal"] == "LOSS":
        return {
            "action": "WARNING",
            "reason": profit["detail"],
            "severity": "HIGH",
        }

    # Duration warning
    if duration["flag"]:
        return {
            "action": "REVIEW",
            "reason": duration["detail"],
            "severity": "LOW",
        }

    # Near edge but no trend = watch
    if zone in ("NEAR_BOTTOM", "NEAR_TOP"):
        return {
            "action": "WATCH",
            "reason": pos["detail"],
            "severity": "LOW",
        }

    return {
        "action": "HOLD",
        "reason": "Price in range, conditions grid-friendly",
        "severity": "NONE",
    }


def assess_bot_health(bot: dict, metrics: dict, signal_info: dict | None = None) -> dict:
    """Main entry point. Returns full health assessment for one bot."""
    price = metrics.get("currClose", 0.0)
    upper = float(bot.get("upperPrice") or 0)
    lower = float(bot.get("lowerPrice") or 0)

    pos = _check_price_position(price, lower, upper)
    trend = _check_trend(metrics, signal_info)
    profit = _check_profit(bot, price)
    duration = _check_duration(bot)
    rec = _generate_recommendation(pos, trend, profit, duration)

    return {
        "position": pos,
        "trend": trend,
        "profit": profit,
        "duration": duration,
        "recommendation": rec,
    }
