"""Bot Monitor — Streamlit UI for active Pionex grid bot monitoring."""
from __future__ import annotations

import html as _html

import streamlit as st

from bot_advisor import assess_bot_health
from pionex_client import PionexClient


# ─────────────────────────────────────────────────────────────────────
#  Colour helpers
# ─────────────────────────────────────────────────────────────────────
_ACTION_STYLE = {
    "CLOSE_NOW":    ("#ef4444", "#2a0f0f", "#7f1d1d"),
    "TAKE_PROFIT":  ("#22c55e", "#052e16", "#166534"),
    "WARNING":      ("#fbbf24", "#3b2a0b", "#78350f"),
    "WATCH":        ("#f97316", "#431407", "#9a3412"),
    "REVIEW":       ("#a78bfa", "#1e1b4b", "#3730a3"),
    "HOLD":         ("#94a3b8", "#1e293b", "#334155"),
}

_CSS = """
<style>
.bot-card {
  padding: 1rem 1.25rem; border-radius: 14px; border: 2px solid #2a2f3a;
  background: linear-gradient(160deg,#12151c 0%,#0b0d12 100%);
  margin-bottom: .75rem;
  font-family: 'JetBrains Mono', monospace;
}
.bot-header { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:.5rem; margin-bottom:.4rem; }
.bot-title { font-size:1.05rem; font-weight:700; color:#f1f5f9; }
.bot-meta { font-size:.78rem; color:#94a3b8; }
.bot-gauge { margin:.5rem 0; }
.bot-gauge-bar { height:8px; background:#1e293b; border-radius:4px; position:relative; }
.bot-gauge-fill { height:8px; border-radius:4px; position:absolute; top:0; left:0; }
.bot-gauge-marker { width:3px; height:14px; background:#f1f5f9; border-radius:1px; position:absolute; top:-3px; }
.bot-pnl { display:flex; gap:1rem; flex-wrap:wrap; margin:.4rem 0; font-size:.84rem; }
.bot-pnl-item { }
.bot-pnl-label { font-size:.7rem; color:#94a3b8; text-transform:uppercase; letter-spacing:.5px; }
.bot-pnl-val { font-weight:600; font-size:.9rem; }
.bot-alert {
  margin:.5rem 0; padding:.5rem .8rem; border-radius:10px;
  font-size:.82rem;
}
.bot-alert-action { font-weight:700; font-size:.88rem; }
.bot-alert-reason { margin-top:.1rem; }
.bot-indicators { display:flex; gap:.5rem; flex-wrap:wrap; margin:.3rem 0; }
.bot-pill {
  display:inline-block; padding:.15rem .45rem; border-radius:12px;
  font-size:.74rem; font-weight:600;
}
.portfolio-box {
  padding:.8rem 1.2rem; border-radius:12px; border:1px solid #1e2533;
  background:#0f1117; margin-bottom:.8rem;
  font-family: 'JetBrains Mono', monospace;
}
</style>
"""


def _chip(text: str, fg: str, bg: str) -> str:
    return (
        f"<span class='bot-pill' style='background:{bg};color:{fg};"
        f"border:1px solid {fg}33'>{_html.escape(text)}</span>"
    )


def _pnl_color(val: float) -> str:
    return "#22c55e" if val > 0 else "#ef4444" if val < 0 else "#94a3b8"


def _pionex_symbol_to_pair(sym: str) -> str:
    return sym.replace("_", "/") if "_" in sym else sym


# ─────────────────────────────────────────────────────────────────────
#  Alert summary
# ─────────────────────────────────────────────────────────────────────
def _render_alert_summary(assessments: list[dict]) -> None:
    alerts = [a for a in assessments if a["advice"]["recommendation"]["action"] not in ("HOLD",)]
    if not alerts:
        st.markdown(
            "<div class='portfolio-box' style='border-color:#166534'>"
            "<span style='color:#22c55e;font-weight:600'>All bots healthy</span>"
            "<span style='color:#94a3b8;font-size:.82rem'> — no action needed</span></div>",
            unsafe_allow_html=True,
        )
        return

    alerts.sort(key=lambda a: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NONE": 4}.get(
        a["advice"]["recommendation"]["severity"], 5))

    html = "<div class='portfolio-box' style='border-color:#78350f'>"
    html += f"<div style='font-size:.72rem;color:#94a3b8;letter-spacing:.6px;text-transform:uppercase;margin-bottom:.3rem'>Alerts ({len(alerts)})</div>"
    for a in alerts:
        rec = a["advice"]["recommendation"]
        fg, bg, border = _ACTION_STYLE.get(rec["action"], ("#94a3b8", "#1e293b", "#334155"))
        html += (
            f"<div style='display:flex;align-items:center;gap:.5rem;margin:.2rem 0;font-size:.82rem'>"
            f"{_chip(rec['action'].replace('_', ' '), fg, bg)}"
            f"<b style='color:#f1f5f9'>{a['symbol']}</b>"
            f"<span style='color:#94a3b8'>— {_html.escape(rec['reason'])}</span>"
            f"</div>"
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────
#  Portfolio summary
# ─────────────────────────────────────────────────────────────────────
def _render_portfolio_summary(assessments: list[dict], bot_count: int) -> None:
    total_invested = sum(a["advice"]["profit"]["invested"] for a in assessments)
    total_grid = sum(a["advice"]["profit"]["gridProfit"] for a in assessments)
    total_realized = sum(a["advice"]["profit"]["realized"] for a in assessments)
    pct = total_grid / total_invested * 100 if total_invested > 0 else 0

    gc = _pnl_color(total_grid)
    rc = _pnl_color(total_realized)

    st.markdown(
        f"<div class='portfolio-box'>"
        f"<div style='display:flex;gap:1.5rem;flex-wrap:wrap;align-items:baseline'>"
        f"<div><span style='color:#94a3b8;font-size:.72rem'>BOTS</span> "
        f"<span style='color:#f1f5f9;font-size:1.1rem;font-weight:700'>{bot_count}</span></div>"
        f"<div><span style='color:#94a3b8;font-size:.72rem'>INVESTED</span> "
        f"<span style='color:#f1f5f9;font-size:1.1rem;font-weight:700'>${total_invested:,.0f}</span></div>"
        f"<div><span style='color:#94a3b8;font-size:.72rem'>GRID PROFIT</span> "
        f"<span style='color:{gc};font-size:1.1rem;font-weight:700'>${total_grid:,.2f} ({pct:+.1f}%)</span></div>"
        f"<div><span style='color:#94a3b8;font-size:.72rem'>REALIZED</span> "
        f"<span style='color:{rc};font-size:1.1rem;font-weight:700'>${total_realized:,.2f}</span></div>"
        f"</div></div>",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────
#  Bot card
# ─────────────────────────────────────────────────────────────────────
def _render_bot_card(bot: dict, metrics: dict, advice: dict, symbol: str) -> None:
    rec = advice["recommendation"]
    pos = advice["position"]
    profit = advice["profit"]
    duration = advice["duration"]
    fg, bg, border = _ACTION_STYLE.get(rec["action"], ("#94a3b8", "#1e293b", "#334155"))

    upper = float(bot.get("upperPrice") or 0)
    lower = float(bot.get("lowerPrice") or 0)
    grids = int(bot.get("gridNum") or 0)
    price = metrics.get("currClose", 0.0)

    # Card border color based on severity
    card_border = border

    html = f"<div class='bot-card' style='border-color:{card_border}'>"

    # Header
    html += "<div class='bot-header'>"
    html += f"<span class='bot-title'>{_html.escape(symbol)}</span>"
    html += f"<div>{_chip(rec['action'].replace('_', ' '), fg, bg)}</div>"
    html += "</div>"
    html += f"<div class='bot-meta'>Created {duration['days']:.0f}d ago · {grids} grids · Status: {bot.get('status', 'unknown')}</div>"

    # Range gauge
    gauge_pct = max(0, min(100, pos["pct"]))
    fill_color = "#22c55e" if 10 <= pos["pct"] <= 90 else "#fbbf24" if 0 <= pos["pct"] <= 100 else "#ef4444"
    html += "<div class='bot-gauge'>"
    html += "<div style='display:flex;justify-content:space-between;font-size:.74rem;color:#94a3b8;margin-bottom:.15rem'>"
    html += f"<span>{lower:,.4f}</span><span>Price: <b style='color:#f1f5f9'>{price:,.4f}</b> ({pos['pct']:.0f}%)</span><span>{upper:,.4f}</span>"
    html += "</div>"
    html += "<div class='bot-gauge-bar'>"
    html += f"<div class='bot-gauge-fill' style='width:{gauge_pct}%;background:{fill_color}30'></div>"
    html += f"<div class='bot-gauge-marker' style='left:{gauge_pct}%;background:{fill_color}'></div>"
    html += "</div></div>"

    # P&L
    gpc = _pnl_color(profit["gridProfitPct"])
    rpc = _pnl_color(profit["realizedPct"])
    html += "<div class='bot-pnl'>"
    html += f"<div class='bot-pnl-item'><div class='bot-pnl-label'>Invested</div><div class='bot-pnl-val' style='color:#f1f5f9'>${profit['invested']:,.0f}</div></div>"
    html += f"<div class='bot-pnl-item'><div class='bot-pnl-label'>Grid Profit</div><div class='bot-pnl-val' style='color:{gpc}'>${profit['gridProfit']:,.2f} ({profit['gridProfitPct']:+.1f}%)</div></div>"
    html += f"<div class='bot-pnl-item'><div class='bot-pnl-label'>Realized</div><div class='bot-pnl-val' style='color:{rpc}'>${profit['realized']:,.2f} ({profit['realizedPct']:+.1f}%)</div></div>"
    html += "</div>"

    # Indicator pills
    adx = (metrics.get("adx") or {}).get("adx", 0.0)
    rsi = metrics.get("rsi", 50.0)
    bb_bw = metrics.get("bbBw", 0.0)

    adx_c = "#ef4444" if adx > 28 else "#fbbf24" if adx > 25 else "#22c55e"
    rsi_c = "#ef4444" if rsi > 70 or rsi < 30 else "#fbbf24" if rsi > 62 or rsi < 35 else "#94a3b8"
    bb_c = "#22d3ee" if bb_bw < 5 else "#94a3b8" if bb_bw < 12 else "#fbbf24"

    html += "<div class='bot-indicators'>"
    html += _chip(f"ADX {adx:.1f}", adx_c, f"{adx_c}18")
    html += _chip(f"RSI {rsi:.1f}", rsi_c, f"{rsi_c}18")
    html += _chip(f"BB {bb_bw:.1f}%", bb_c, f"{bb_c}18")
    grid_score = metrics.get("_grid_score", 0.0)
    setup_score = metrics.get("_setup_score", 0.0)
    if grid_score:
        gs_c = "#22c55e" if grid_score >= 8 else "#84cc16" if grid_score >= 6 else "#fbbf24"
        html += _chip(f"Grid {grid_score:.1f}", gs_c, f"{gs_c}18")
    if setup_score:
        ss_c = "#22c55e" if setup_score >= 7.5 else "#fbbf24" if setup_score >= 5 else "#94a3b8"
        html += _chip(f"Setup {setup_score:.1f}", ss_c, f"{ss_c}18")
    html += "</div>"

    # Alert box
    html += (
        f"<div class='bot-alert' style='background:{bg};border:1px solid {border}'>"
        f"<div class='bot-alert-action' style='color:{fg}'>{rec['action'].replace('_', ' ')}</div>"
        f"<div class='bot-alert-reason' style='color:#cbd5e1'>{_html.escape(rec['reason'])}</div>"
        f"</div>"
    )

    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────
#  Main entry point
# ─────────────────────────────────────────────────────────────────────
def render_bot_monitor(selected: list[str], payloads: dict[str, dict]) -> None:
    st.markdown(_CSS, unsafe_allow_html=True)

    st.markdown(
        "<div style='font-size:.72rem;color:#64748b;letter-spacing:.6px;text-transform:uppercase;"
        "margin-bottom:.5rem'>Bot Monitor — Active Pionex Grid Bots</div>",
        unsafe_allow_html=True,
    )

    client = PionexClient()
    if not client.configured:
        st.warning(
            "Pionex API keys not configured. "
            "Set `PIONEX_API_KEY` and `PIONEX_API_SECRET` in .env or Streamlit secrets."
        )
        st.code(
            '# .env\nPIONEX_API_KEY=your_key_here\nPIONEX_API_SECRET=your_secret_here',
            language="bash",
        )
        return

    with st.spinner("Fetching active bots from Pionex..."):
        bots = client.list_running_bots()

    if not bots:
        st.info("No running spot grid bots found on Pionex.")
        return

    # Match bots to our cached metrics
    assessments: list[dict] = []
    for bot in bots:
        raw_sym = bot.get("symbol", "")
        pair = _pionex_symbol_to_pair(raw_sym)
        p = payloads.get(pair, {})
        metrics = p.get("metrics", {})
        signal_info = p.get("signalInfo")

        # Inject scores for display
        metrics["_grid_score"] = p.get("scoreInfo", {}).get("score", 0.0)
        metrics["_setup_score"] = (signal_info or {}).get("score", 0.0)

        if not metrics.get("currClose"):
            continue

        advice = assess_bot_health(bot, metrics, signal_info)
        assessments.append({"bot": bot, "metrics": metrics, "advice": advice, "symbol": pair})

    if not assessments:
        st.warning("Active bots found but no matching cached metrics. Press Refresh to fetch market data.")
        return

    # Portfolio summary
    _render_portfolio_summary(assessments, len(bots))

    # Alert summary
    _render_alert_summary(assessments)

    # Sort: critical first, then by profit
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NONE": 4}
    assessments.sort(key=lambda a: (
        severity_order.get(a["advice"]["recommendation"]["severity"], 5),
        -a["advice"]["profit"]["gridProfitPct"],
    ))

    # Bot cards
    for a in assessments:
        _render_bot_card(a["bot"], a["metrics"], a["advice"], a["symbol"])
