"""Trade Monitor — Phase 2 Streamlit page.

Tracks simulated grid-bot trades to evaluate Range Finder recommendation quality.
"""
from __future__ import annotations

from datetime import datetime, timezone

import plotly.graph_objects as go
import streamlit as st

from trade_logger import as_utc, get_all_simulated_trades, get_trade_fills
from trade_simulator import (
    build_grid_levels,
    calc_pnl,
    close_trade,
    open_trade,
    update_all_active,
)


# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────

def _age_str(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    delta = datetime.now(timezone.utc) - as_utc(dt)
    h = int(delta.total_seconds() // 3600)
    d = h // 24
    return f"{d}d {h % 24}h" if d else f"{h}h {int((delta.total_seconds() % 3600) // 60)}m"


def _pnl_color(pct: float) -> str:
    return "#22c55e" if pct > 0 else "#ef4444" if pct < 0 else "#94a3b8"


def _status_chip(status: str) -> str:
    cfg = {
        "ACTIVE":  ("#22d3ee", "#082f49"),
        "TP_HIT":  ("#22c55e", "#052e16"),
        "SL_HIT":  ("#ef4444", "#2a0f16"),
        "CLOSED":  ("#94a3b8", "#1e293b"),
    }
    color, bg = cfg.get(status, ("#94a3b8", "#1e293b"))
    return (
        f"<span style='padding:3px 10px;border-radius:12px;font-size:.75rem;"
        f"font-weight:600;color:{color};background:{bg};border:1px solid {color}44'>"
        f"{status}</span>"
    )


def _dir_color(direction: str) -> str:
    return "#22c55e" if direction == "Long" else "#ef4444" if direction == "Short" else "#fbbf24"


def _range_gauge(current: float, low: float, high: float) -> str:
    """Mini HTML range bar showing where current price sits."""
    pct = max(0.0, min(1.0, (current - low) / (high - low))) if high > low else 0.5
    bar_pct = int(pct * 100)
    c = "#22c55e" if pct > 0.3 else "#ef4444" if pct < 0.15 else "#fbbf24"
    return (
        f"<div style='margin:.3rem 0'>"
        f"<div style='display:flex;justify-content:space-between;font-size:.70rem;color:#64748b'>"
        f"<span>{low:,.4f}</span><span>SL–TP range</span><span>{high:,.4f}</span></div>"
        f"<div style='height:6px;border-radius:3px;background:#1e2533;margin:.15rem 0'>"
        f"<div style='width:{bar_pct}%;height:100%;border-radius:3px;background:{c}'></div></div>"
        f"<div style='text-align:center;font-size:.76rem;color:{c};font-weight:600'>"
        f"{current:,.4f} ({pct*100:.0f}%)</div>"
        f"</div>"
    )


# ─────────────────────────────────────────────────────────────────────
#  Render sections
# ─────────────────────────────────────────────────────────────────────

def _render_active(trades: list, payloads: dict) -> None:
    active = [t for t in trades if t.status == "ACTIVE"]
    if not active:
        st.info("No active simulated trades. Open one from the Range Finder or the form below.")
        return

    for trade in active:
        pnl = calc_pnl(trade, trade.last_candle_close or trade.entry_price)
        current = trade.last_candle_close or trade.entry_price
        dc      = _dir_color(trade.direction)
        tc      = _pnl_color(pnl["total_pct"])
        rc      = _pnl_color(pnl["realized_pct"])

        pnl_usd_html = (
            f"<span style='color:{tc};font-size:.85rem'>"
            f"  (${pnl['total_usd']:+.2f})</span>"
            if pnl["total_usd"] is not None else ""
        )

        st.markdown(
            f"<div style='padding:1rem 1.25rem;border-radius:14px;border:2px solid #22d3ee44;"
            f"background:linear-gradient(160deg,#0a1628 0%,#060b12 100%);margin-bottom:.75rem'>"
            f"<div style='display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:.5rem'>"
            f"<span style='font-size:.7rem;color:#94a3b8;letter-spacing:.8px;text-transform:uppercase'>{trade.symbol}</span>"
            f"{_status_chip(trade.status)}</div>"
            f"<div style='display:flex;align-items:baseline;gap:1rem;margin:.3rem 0;flex-wrap:wrap'>"
            f"<span style='color:{dc};font-size:1rem;font-weight:700'>{trade.direction}</span>"
            f"<span style='color:#94a3b8;font-size:.82rem'>Entry {trade.entry_price:,.4f}"
            f" · {trade.num_grids} grids · {trade.grid_mode[:5]} · "
            f"Grid Score <b style='color:#f1f5f9'>{trade.grid_score:.1f}</b>"
            + (f" · Setup Score <b style='color:#f1f5f9'>{trade.setup_score:.1f}</b>" if trade.setup_score else "")
            + f"</span></div>"
            + _range_gauge(current, trade.range_low, trade.range_high)
            + f"<div style='display:flex;gap:2rem;margin:.4rem 0;flex-wrap:wrap'>"
            f"<div><div style='font-size:.68rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px'>Total P&L</div>"
            f"<div style='color:{tc};font-size:1.1rem;font-weight:700'>{pnl['total_pct']:+.2f}%{pnl_usd_html}</div></div>"
            f"<div><div style='font-size:.68rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px'>Realized</div>"
            f"<div style='color:{rc};font-size:.9rem;font-weight:600'>{pnl['realized_pct']:+.2f}%</div></div>"
            f"<div><div style='font-size:.68rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px'>Cycles</div>"
            f"<div style='color:#f1f5f9;font-size:.9rem;font-weight:600'>{pnl['cycle_count']}</div></div>"
            f"<div><div style='font-size:.68rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px'>Open Pos</div>"
            f"<div style='color:#f1f5f9;font-size:.9rem;font-weight:600'>{pnl['open_positions']}</div></div>"
            f"<div><div style='font-size:.68rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px'>Open</div>"
            f"<div style='color:#94a3b8;font-size:.82rem'>{_age_str(trade.opened_at)}</div></div>"
            f"</div>"
            f"<div style='font-size:.76rem;color:#94a3b8'>"
            f"SL <b style='color:#ef4444'>{trade.stop_loss:,.4f}</b> · "
            f"TP <b style='color:#22c55e'>{trade.take_profit:,.4f}</b>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

        col_fill, col_close = st.columns([4, 1])
        with col_fill:
            fills = get_trade_fills(trade.id)
            if fills:
                with st.expander(f"Fill log ({len(fills)} fills)", expanded=False):
                    rows = []
                    for f in reversed(fills[-50:]):
                        ts_dt = datetime.fromtimestamp(f.candle_ts / 1000, tz=timezone.utc)
                        rows.append({
                            "Time":    ts_dt.strftime("%m-%d %H:%M"),
                            "Action":  f.action,
                            "Level":   f"{f.level:,.4f}",
                            "Pair":    f"{f.paired_level:,.4f}" if f.paired_level else "—",
                            "P&L %":   f"{f.pnl_pct*100:+.3f}%" if f.pnl_pct is not None else "—",
                            "P&L $":   f"${f.pnl_usd:+.3f}" if f.pnl_usd is not None else "—",
                        })
                    import pandas as pd
                    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        with col_close:
            if st.button("Close", key=f"close_{trade.id}", type="secondary", use_container_width=True):
                close_trade(trade.id, price=current, reason="Manual close")
                st.success(f"Trade #{trade.id} closed.")
                st.rerun()


def _render_history(trades: list) -> None:
    closed = [t for t in trades if t.status != "ACTIVE"]
    if not closed:
        st.info("No closed trades yet.")
        return

    rows = []
    for t in closed:
        fills  = get_trade_fills(t.id)
        cycles = len([f for f in fills if f.action == "SELL"])
        final_pnl_pct = sum(f.pnl_pct for f in fills if f.action == "SELL" and f.pnl_pct) / t.num_grids * 100
        final_pnl_usd = sum(f.pnl_usd for f in fills if f.action == "SELL" and f.pnl_usd) if t.capital else None

        if t.closed_at and t.opened_at:
            secs = (as_utc(t.closed_at) - as_utc(t.opened_at)).total_seconds()
            h = int(secs // 3600); d = h // 24
            duration = f"{d}d {h%24}h" if d else f"{h}h"
        else:
            duration = _age_str(t.opened_at)

        rows.append({
            "Symbol":    t.symbol,
            "Direction": t.direction,
            "Grid Score": t.grid_score,
            "Setup Score": t.setup_score or "—",
            "Grids":     t.num_grids,
            "Duration":  duration,
            "Cycles":    cycles,
            "P&L %":     round(final_pnl_pct, 3),
            "P&L $":     round(final_pnl_usd, 2) if final_pnl_usd is not None else "—",
            "Close":     t.close_reason or t.status,
        })

    import pandas as pd
    df = pd.DataFrame(rows)

    def _pnl_style(val: int | float | str) -> str:
        if not isinstance(val, (int, float)):
            return ""
        return "color:#22c55e;font-weight:700" if val > 0 else "color:#ef4444;font-weight:700" if val < 0 else ""

    def _dir_style(val: str) -> str:
        return "color:#22c55e" if val == "Long" else "color:#ef4444" if val == "Short" else "color:#fbbf24"

    styled = (
        df.style
        .map(_pnl_style, subset=["P&L %"])
        .map(_dir_style, subset=["Direction"])
        .format({"Grid Score": "{:.1f}", "P&L %": "{:+.3f}%"}, na_rep="—")
    )
    st.dataframe(styled, hide_index=True, use_container_width=True)


def _render_performance(trades: list) -> None:
    closed = [t for t in trades if t.status != "ACTIVE"]
    if len(closed) < 2:
        st.info("Need at least 2 closed trades to show performance stats.")
        return

    scores, pnls, symbols, statuses = [], [], [], []
    for t in closed:
        fills = get_trade_fills(t.id)
        pnl   = sum(f.pnl_pct for f in fills if f.action == "SELL" and f.pnl_pct) / t.num_grids * 100
        scores.append(t.grid_score)
        pnls.append(pnl)
        symbols.append(t.symbol)
        statuses.append(t.status)

    wins   = sum(1 for p in pnls if p > 0)
    avg_pnl = sum(pnls) / len(pnls)
    total_pnl = sum(pnls)
    win_rate  = wins / len(pnls) * 100

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Closed Trades",  len(closed))
    col2.metric("Win Rate",        f"{win_rate:.0f}%")
    col3.metric("Avg P&L",         f"{avg_pnl:+.2f}%")
    col4.metric("Total Realized",  f"{total_pnl:+.2f}%")

    # Score vs P&L scatter
    color_map = {"TP_HIT": "#22c55e", "SL_HIT": "#ef4444", "CLOSED": "#94a3b8"}
    point_colors = [color_map.get(s, "#94a3b8") for s in statuses]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=scores, y=pnls, mode="markers+text",
        text=symbols, textposition="top center",
        marker=dict(color=point_colors, size=12, line=dict(color="#ffffff22", width=1)),
        hovertemplate="<b>%{text}</b><br>Grid Score: %{x:.1f}<br>P&L: %{y:+.2f}%<extra></extra>",
    ))
    # Trend line
    if len(scores) >= 3:
        import numpy as np
        m, b = np.polyfit(scores, pnls, 1)
        x_range = [min(scores), max(scores)]
        fig.add_trace(go.Scatter(
            x=x_range, y=[m * x + b for x in x_range],
            mode="lines", line=dict(color="#94a3b8", dash="dash", width=1),
            showlegend=False,
        ))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0b0d12", plot_bgcolor="#0b0d12",
        title=dict(text="Grid Score vs Realized P&L", font=dict(size=13, color="#94a3b8")),
        xaxis=dict(title="Grid Score at Open", gridcolor="#1e293b"),
        yaxis=dict(title="Realized P&L %", gridcolor="#1e293b"),
        margin=dict(l=40, r=20, t=40, b=40),
        height=380,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_open_form(selected: list[str], payloads: dict) -> None:
    viable = {s: p for s, p in payloads.items() if (p.get("viability") or {}).get("viable")}
    if not viable:
        st.info("No viable setups available in the current cache.")
        return

    with st.form("open_trade_form"):
        cols = st.columns([2, 1, 1, 1])
        sym     = cols[0].selectbox("Pair", list(viable.keys()))
        capital = cols[1].number_input("Capital (USDT, optional)", min_value=0.0, value=300.0, step=50.0)
        profile = cols[2].selectbox("Profile", ["stable", "moderate", "volatile"], index=1)
        submitted = cols[3].form_submit_button("Open Trade", use_container_width=True, type="primary")

        if submitted and sym:
            payload = viable[sym]
            tid = open_trade(payload, sym, capital if capital > 0 else None, profile)
            st.success(f"Trade #{tid} opened for {sym} · {payload['direction']['type']} · "
                       f"Grid Score {payload['scoreInfo']['score']:.1f}")
            st.rerun()


# ─────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────

def render_trade_monitor(selected: list[str], payloads: dict) -> None:
    st.markdown(
        "<div style='font-size:.7rem;color:#94a3b8;letter-spacing:.8px;"
        "text-transform:uppercase;margin-bottom:.5rem'>Trade Monitor</div>"
        "<h2 style='margin:0 0 1rem 0'>Simulated Grid Trades</h2>",
        unsafe_allow_html=True,
    )

    # Refresh active simulations
    with st.spinner("Syncing simulations…"):
        update_all_active(silent=True)

    trades = get_all_simulated_trades()
    active_count = len([t for t in trades if t.status == "ACTIVE"])
    closed_count = len([t for t in trades if t.status != "ACTIVE"])

    # Summary strip
    st.markdown(
        f"<div style='display:flex;gap:1.5rem;flex-wrap:wrap;margin-bottom:1rem'>"
        f"<span style='color:#94a3b8;font-size:.88rem'>Active: <b style='color:#22d3ee'>{active_count}</b></span>"
        f"<span style='color:#94a3b8;font-size:.88rem'>Closed: <b style='color:#f1f5f9'>{closed_count}</b></span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    tab_active, tab_history, tab_perf, tab_open = st.tabs(
        ["Active Trades", "History", "Performance", "Open New Trade"]
    )

    with tab_active:
        _render_active(trades, payloads)

    with tab_history:
        _render_history(trades)

    with tab_perf:
        _render_performance(trades)

    with tab_open:
        st.markdown("Pre-fills all parameters from the current Range Finder output for any viable pair.")
        _render_open_form(selected, payloads)
