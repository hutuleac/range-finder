"""Pyonex Streamlit dashboard — Phase 1."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import CFG, DEFAULT_PAIRS, GRID_CONFIG, LEGENDS, SIG_TIPS
from grid_calculator import (
    calc_drawdown_scenario,
    calc_grid_capital_per_grid,
    calc_grid_profit_per_grid,
    calc_grid_stop_loss,
    calc_grid_take_profit,
)
from refresh_data import refresh_one
from trade_logger import all_latest, init_db, latest_metrics

st.set_page_config(
    page_title=f"Pyonex v{CFG['APP_VERSION']}",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* ── Base ─────────────────────────────────────────────────── */
.metric-big  { font-size: 2.0rem; font-weight: 700; letter-spacing: -.5px; }
.metric-sub  { font-size: .85rem; color: #8b93a7; margin-top: .15rem; }

/* ── Score colours ───────────────────────────────────────── */
.score-strong { color: #22c55e; }
.score-good   { color: #84cc16; }
.score-dev    { color: #eab308; }
.score-avoid  { color: #ef4444; }

/* ── Signal text colours ─────────────────────────────────── */
.bull   { color: #22c55e; font-weight: 600; }
.bear   { color: #ef4444; font-weight: 600; }
.warn   { color: #fbbf24; font-weight: 600; }
.neut   { color: #94a3b8; }
.cyan   { color: #22d3ee; font-weight: 600; }
.purple { color: #a78bfa; font-weight: 600; }

/* ── Chips ───────────────────────────────────────────────── */
.chip {
  display:inline-block; padding: 2px 10px; border-radius: 20px;
  font-size: .78rem; font-weight: 600; letter-spacing: .3px;
}
.chip-green  { background:#052e16; color:#22c55e; border:1px solid #166534; }
.chip-red    { background:#2a0f16; color:#ef4444; border:1px solid #7f1d1d; }
.chip-yellow { background:#3b2a0b; color:#fbbf24; border:1px solid #78350f; }
.chip-cyan   { background:#082f49; color:#22d3ee; border:1px solid #164e63; }
.chip-purple { background:#1e1b4b; color:#a78bfa; border:1px solid #3730a3; }
.chip-grey   { background:#1e293b; color:#94a3b8; border:1px solid #334155; }

/* ── Cards ───────────────────────────────────────────────── */
.card {
  padding: 1rem 1.25rem; border-radius: 14px; border: 1px solid #2a2f3a;
  background: linear-gradient(160deg,#12151c 0%,#0b0d12 100%);
  margin-bottom: .75rem;
}
.card-active-long  { border-color: #166534; box-shadow: 0 0 18px rgba(34,197,94,.20); }
.card-active-short { border-color: #7f1d1d; box-shadow: 0 0 18px rgba(239,68,68,.20); }
.card-active-neut  { border-color: #78350f; box-shadow: 0 0 18px rgba(251,191,36,.15); }
.card h3 { margin: 0 0 .35rem 0; font-size: 1.1rem; }
.card small { color: #8b93a7; }

/* ── Metric blocks (top row) ─────────────────────────────── */
.mblock {
  padding:.7rem 1rem; border-radius:10px;
  background:#0f1117; border:1px solid #1e2533;
  text-align:center;
}
.mblock .mlabel { font-size:.72rem; color:#64748b; text-transform:uppercase; letter-spacing:.6px; }
.mblock .mval   { font-size:1.35rem; font-weight:700; margin-top:.1rem; }

/* ── Score component bar ─────────────────────────────────── */
.comp-row { display:flex; align-items:center; gap:.5rem; margin:.2rem 0; font-size:.82rem; }
.comp-bar-bg { flex:1; height:6px; background:#1e293b; border-radius:3px; }
.comp-bar    { height:6px; border-radius:3px; }

/* ── Table colours via Pandas Styler ─────────────────────── */
</style>
""", unsafe_allow_html=True)

init_db()


# ─────────────────────────────────────────────────────────────────────
#  Colour helpers
# ─────────────────────────────────────────────────────────────────────
def chip(text: str, kind: str = "green") -> str:
    return f'<span class="chip chip-{kind}">{text}</span>'


def colored(text: str, cls: str) -> str:
    return f'<span class="{cls}">{text}</span>'


def score_cls(score: float) -> str:
    return "score-strong" if score >= 8 else "score-good" if score >= 6 else "score-dev" if score >= 4 else "score-avoid"


def score_chip(score: float, label: str) -> str:
    kind = "green" if score >= 8 else "green" if score >= 6 else "yellow" if score >= 4 else "red"
    if score >= 6:
        kind = "green"
    elif score >= 4:
        kind = "yellow"
    else:
        kind = "red"
    return chip(f"{score:.1f} {label}", kind)


def direction_chip(direction: str) -> str:
    m = {"Long": ("green", "LONG GRID"), "Short": ("red", "SHORT GRID"), "Neutral": ("yellow", "NEUTRAL GRID")}
    kind, label = m.get(direction, ("grey", direction))
    return chip(label, kind)


def struct_chip(s: str) -> str:
    return chip(s, "green" if s == "Bullish" else "red" if s == "Bearish" else "grey")


def rsi_color(rsi: float) -> str:
    if rsi >= 70: return "#ef4444"
    if rsi >= 60: return "#fbbf24"
    if rsi <= 30: return "#22d3ee"
    if rsi <= 40: return "#84cc16"
    return "#22c55e"


def adx_color(adx: float) -> str:
    if adx >= 25: return "#ef4444"
    if adx >= 20: return "#fbbf24"
    return "#22c55e"


def cvd_color(val: float) -> str:
    return "#22c55e" if val > 0 else "#ef4444"


def comp_bar_color(ratio: float) -> str:
    if ratio >= 0.75: return "#22c55e"
    if ratio >= 0.4:  return "#eab308"
    return "#ef4444"


def mblock(label: str, value: str, color: str = "#e5e7eb") -> str:
    return (
        f"<div class='mblock'>"
        f"<div class='mlabel'>{label}</div>"
        f"<div class='mval' style='color:{color}'>{value}</div>"
        f"</div>"
    )


# ─────────────────────────────────────────────────────────────────────
#  Chart
# ─────────────────────────────────────────────────────────────────────
def build_chart(symbol: str, metrics: dict, rng: dict) -> go.Figure:
    price = metrics.get("currClose", 0.0)
    bb    = metrics.get("bb") or {}
    dc_s  = metrics.get("donchianShort") or {}
    dc_l  = metrics.get("donchianLong") or {}

    fig = go.Figure()

    def hline(y: float, name: str, color: str, dash: str = "solid", width: float = 1.5):
        fig.add_trace(go.Scatter(x=[0, 1], y=[y, y], mode="lines", name=name,
                                  line=dict(color=color, dash=dash, width=width)))

    # Range band
    if rng.get("rangeLow") and rng.get("rangeHigh"):
        fig.add_shape(type="rect", xref="paper", yref="y",
                      x0=0, x1=1, y0=rng["rangeLow"], y1=rng["rangeHigh"],
                      line=dict(width=0), fillcolor="rgba(251,191,36,0.07)")

    # Price
    hline(price, "Price", "#f8fafc", "solid", 2.5)

    # BB
    if bb.get("upper"):
        hline(bb["upper"], "BB upper", "#60a5fa", "dot")
        hline(bb["lower"], "BB lower", "#60a5fa", "dot")
        if bb.get("mid"):
            hline(bb["mid"], "BB mid", "#3b82f6", "dash", 1.0)

    # Donchian short (purple) / long (pink)
    if dc_s.get("upper"):
        hline(dc_s["upper"], f"DC{dc_s.get('period','20')} hi", "#a78bfa", "dash")
        hline(dc_s["lower"], f"DC{dc_s.get('period','20')} lo", "#a78bfa", "dash")
    if dc_l.get("upper"):
        hline(dc_l["upper"], f"DC{dc_l.get('period','55')} hi", "#f472b6", "longdash")
        hline(dc_l["lower"], f"DC{dc_l.get('period','55')} lo", "#f472b6", "longdash")

    # EMAs
    if metrics.get("emaFast"):
        hline(metrics["emaFast"], "EMA 50",  "#34d399", "dot")
    if metrics.get("emaSlow"):
        hline(metrics["emaSlow"], "EMA 200", "#f87171", "dot")

    # POC lines
    if metrics.get("poc5d"):
        hline(metrics["poc5d"],  "POC 5d",  "#fbbf24", "solid", 2.0)
    if metrics.get("poc14d"):
        hline(metrics["poc14d"], "POC 14d", "#fb923c", "solid", 2.0)
    if metrics.get("poc30d"):
        hline(metrics["poc30d"], "POC 30d", "#f97316", "dash", 1.0)

    # AVWAP lines
    if metrics.get("avwap5d"):
        hline(metrics["avwap5d"],  "AVWAP 5d",  "#a3e635", "dot", 1.0)
    if metrics.get("avwap14d"):
        hline(metrics["avwap14d"], "AVWAP 14d", "#86efac", "dot", 1.0)

    # FVG zones
    for g in metrics.get("fvgList", [])[:5]:
        c = "rgba(34,197,94,0.15)" if g["type"] == "BULL" else "rgba(239,68,68,0.15)"
        border = "rgba(34,197,94,0.5)" if g["type"] == "BULL" else "rgba(239,68,68,0.5)"
        fig.add_shape(type="rect", xref="paper", yref="y",
                      x0=0, x1=1, y0=g["bottom"], y1=g["top"],
                      line=dict(width=1, color=border), fillcolor=c)

    # SL / TP lines
    if rng.get("rangeLow"):
        prof = "moderate"
        sl = calc_grid_stop_loss(rng["rangeLow"], prof)
        tp = calc_grid_take_profit(rng["rangeHigh"], prof)
        hline(sl, "SL", "#ef4444", "dash", 1.2)
        hline(tp, "TP", "#22c55e", "dash", 1.2)

    fig.update_layout(
        title=dict(text=f"{symbol} — reference levels", font=dict(color="#e5e7eb", size=14)),
        xaxis=dict(visible=False),
        yaxis=dict(title="Price (USDT)", gridcolor="#1e2533", color="#8b93a7"),
        height=400, showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(size=11)),
        paper_bgcolor="#0b0d12", plot_bgcolor="#0b0d12",
        font=dict(color="#e5e7eb"),
        margin=dict(l=0, r=0, t=40, b=0),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────
#  Sidebar
# ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title(f"Pyonex v{CFG['APP_VERSION']}")
    st.caption("Grid-bot scout for Pionex — Binance/Bybit data")

    selected = st.multiselect(
        "Watched pairs", DEFAULT_PAIRS, default=DEFAULT_PAIRS,
        help="USDT perpetuals. HYPE/SUI fall back to Bybit automatically.",
    )
    capital = st.number_input(
        "Capital per bot (USDT)", min_value=50.0, max_value=100_000.0,
        value=float(GRID_CONFIG["DEFAULT_CAPITAL"]), step=50.0,
    )
    profile_override = st.selectbox(
        "Volatility profile", ["auto", "stable", "moderate", "volatile"], index=0,
        help="Auto = per-ticker default. Overrides SL/TP buffers otherwise.",
    )

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Refresh now", use_container_width=True):
            with st.spinner("Refreshing…"):
                for sym in selected:
                    try:
                        refresh_one(sym)
                    except Exception as e:  # noqa: BLE001
                        st.warning(f"{sym}: {e}")
            st.rerun()
    with col_b:
        st.caption(f"Auto: {CFG['REFRESH_INTERVAL_SEC']}s")

    rows = all_latest()
    last_ts = max((r.updated_at for r in rows), default=None)
    if last_ts:
        delta = (datetime.utcnow() - last_ts.replace(tzinfo=None)).total_seconds()
        age_color = "green" if delta < 400 else "orange" if delta < 1400 else "red"
        st.markdown(
            f"Cache age: <span style='color:{age_color};font-weight:600'>{int(delta)}s</span>"
            f" · rows: {len(rows)}",
            unsafe_allow_html=True,
        )
    else:
        st.warning("Cache empty — press Refresh now.")

    with st.expander("Legend", expanded=False):
        for name, desc in LEGENDS:
            st.markdown(f"**{name}** — {desc}")


# Auto-refresh
st.markdown(
    f'<meta http-equiv="refresh" content="{CFG["REFRESH_INTERVAL_SEC"]}">',
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────────────
#  Per-symbol render
# ─────────────────────────────────────────────────────────────────────
def render_symbol(payload: dict, symbol: str) -> None:
    m          = payload["metrics"]
    score_info = payload["scoreInfo"]
    direction  = payload["direction"]
    rng        = payload["range"]
    mode       = payload["mode"]
    grid_count = payload["gridCount"]
    duration   = payload["duration"]
    via        = payload["viability"]
    profile    = payload["profile"]
    prof_name  = profile_override if profile_override != "auto" else profile["profile"]

    price = m.get("currClose", 0.0)
    score = score_info["score"]
    rsi   = m.get("rsi", 50.0)
    atr_p = m.get("atrPct", 0.0)
    adx_v = (m.get("adx") or {}).get("adx", 0.0)
    bb_bw = m.get("bbBw", 0.0)
    bb_lb = (m.get("bb") or {}).get("label", "normal")
    str4h = m.get("structure4h", "Neutral")
    sq    = (m.get("squeeze") or {}).get("squeeze", False)
    cvd5  = m.get("cvd5d", 0.0)
    cvd14 = m.get("cvd14d", 0.0)
    cvd30 = m.get("cvd30d", 0.0)
    fund  = m.get("funding", 0.0)
    flow  = m.get("flow", 0.0)
    oi_ch = m.get("oiChange", 0.0)

    # ── Top metric row (coloured blocks) ───────────────────────────
    bb_color = "#22d3ee" if bb_lb == "squeeze" else "#ef4444" if bb_lb == "expanded" else "#e5e7eb"
    sq_color = "#22d3ee" if sq else "#64748b"
    flow_color = "#22c55e" if flow > CFG["FLOW_STRONG"] else "#ef4444" if flow < -CFG["FLOW_STRONG"] else "#fbbf24"
    oi_color = "#22c55e" if oi_ch > 0 else "#ef4444"

    cols = st.columns(8)
    cols[0].markdown(mblock("Price",      f"{price:,.4f}",        "#f8fafc"), unsafe_allow_html=True)
    cols[1].markdown(mblock("RSI 4H",     f"{rsi:.1f}",           rsi_color(rsi)), unsafe_allow_html=True)
    cols[2].markdown(mblock("ATR %",      f"{atr_p:.2f}%",        "#fbbf24" if atr_p > 3 else "#94a3b8"), unsafe_allow_html=True)
    cols[3].markdown(mblock("ADX",        f"{adx_v:.1f}",         adx_color(adx_v)), unsafe_allow_html=True)
    cols[4].markdown(mblock("BB BW",      f"{bb_bw:.2f}%",        bb_color), unsafe_allow_html=True)
    cols[5].markdown(mblock("Struct 4H",  str4h,                  "#22c55e" if str4h=="Bullish" else "#ef4444" if str4h=="Bearish" else "#94a3b8"), unsafe_allow_html=True)
    cols[6].markdown(mblock("Squeeze",    "YES" if sq else "no",  sq_color), unsafe_allow_html=True)
    cols[7].markdown(mblock("Flow 24h",   f"{flow:+.1f}%",        flow_color), unsafe_allow_html=True)

    st.write("")

    # ── Score + direction + viability ──────────────────────────────
    left, right = st.columns([1.15, 1])

    with left:
        cls = score_cls(score)
        dir_chip_html = direction_chip(direction["type"])
        via_chip_html = chip("VIABLE", "green") if via["viable"] else chip("BLOCKED", "red")

        st.markdown(
            f"<div class='card'>"
            f"<div class='metric-sub'>Grid Score</div>"
            f"<div class='metric-big {cls}'>{score:.1f} / 10</div>"
            f"<div style='margin:.35rem 0'>{score_chip(score, score_info['label'])} &nbsp; {dir_chip_html} &nbsp; {via_chip_html}</div>"
            f"<div class='metric-sub'>{direction['reason']}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # Component breakdown with mini colour bars
        for comp in score_info["components"]:
            ratio = comp["score"] / comp["max"] if comp["max"] else 0
            bar_color = comp_bar_color(ratio)
            pct = int(ratio * 100)
            st.markdown(
                f"<div class='comp-row'>"
                f"<span style='width:120px;color:#94a3b8'>{comp['label']}</span>"
                f"<div class='comp-bar-bg'><div class='comp-bar' style='width:{pct}%;background:{bar_color}'></div></div>"
                f"<span style='width:32px;text-align:right;color:{bar_color};font-weight:600'>{comp['score']:.1f}</span>"
                f"<span style='color:#64748b;font-size:.78rem'> / {comp['max']}</span>"
                f"<span style='color:#64748b;font-size:.75rem;margin-left:.4rem'>{comp['detail']}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        if score_info["recs"]:
            with st.expander("What's missing?"):
                for r in score_info["recs"]:
                    st.markdown(f"<span class='warn'>▸</span> {r}", unsafe_allow_html=True)

    with right:
        # Viability
        st.markdown(
            f"<div class='card'>"
            f"<div class='metric-sub'>Viability &nbsp; {via_chip_html}</div>"
            f"<div style='margin:.3rem 0;font-size:.88rem'>{via['reason']}</div>"
            + (
                "".join(f"<div style='margin:.15rem 0'>{chip(w, 'yellow')}</div>"
                         for w in via["warning"].split(" | "))
                if via.get("warning") else ""
            )
            + "</div>",
            unsafe_allow_html=True,
        )

        # Range + grid
        mode_chip = chip(mode["mode"], "cyan")
        dir_type  = direction["type"]
        range_color = "#22c55e" if dir_type == "Long" else "#ef4444" if dir_type == "Short" else "#fbbf24"
        st.markdown(
            f"<div class='card'>"
            f"<div class='metric-sub'>Grid Range &nbsp; {mode_chip}</div>"
            f"<div style='font-size:1.05rem;font-weight:600;color:{range_color};margin:.25rem 0'>"
            f"{rng['rangeLow']:,.4f} – {rng['rangeHigh']:,.4f}</div>"
            f"<div style='font-size:.85rem;color:#8b93a7'>"
            f"Width: <b style='color:#e5e7eb'>{rng['rangeWidthPct']:.2f}%</b> &nbsp;·&nbsp; "
            f"Grids: <b style='color:#e5e7eb'>{grid_count['recommended']}</b> "
            f"<span style='color:#475569'>(min {grid_count['min']} max {grid_count['max']})</span> &nbsp;·&nbsp; "
            f"Est: <b style='color:#e5e7eb'>{duration['label']}</b></div>"
            f"<div style='font-size:.75rem;color:#475569;margin-top:.3rem'>{mode['reason']}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # CVD row
        def cvd_badge(v: float, tf: str) -> str:
            c = "#22c55e" if v > 0 else "#ef4444"
            lbl = "ACC" if v > 0 else "DIS"
            return f"<span style='color:{c};font-weight:600'>{tf} {lbl}</span>"

        st.markdown(
            f"<div class='card'>"
            f"<div class='metric-sub'>CVD Alignment</div>"
            f"<div style='display:flex;gap:.75rem;margin:.25rem 0;font-size:.88rem'>"
            f"{cvd_badge(cvd5, '5d')} {cvd_badge(cvd14, '14d')} {cvd_badge(cvd30, '30d')}"
            f"</div>"
            f"<div style='font-size:.78rem;color:#64748b'>"
            f"OI 7d: <b style='color:{'#22c55e' if oi_ch>0 else '#ef4444'}'>{oi_ch:+.1f}%</b> &nbsp; "
            f"Funding: <b style='color:{'#fbbf24' if abs(fund)>0.05 else '#22c55e'}'>{fund:+.4f}%</b>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ── FVG list ───────────────────────────────────────────────────
    fvg_list = m.get("fvgList", [])
    if fvg_list:
        fvg_cols = st.columns(min(len(fvg_list), 5))
        for i, g in enumerate(fvg_list[:5]):
            c = "green" if g["type"] == "BULL" else "red"
            dist = abs(price - g["mid"]) / price * 100 if price else 0
            with fvg_cols[i]:
                st.markdown(
                    f"<div class='card' style='padding:.6rem .8rem;text-align:center'>"
                    f"<div>{chip(g['type'] + ' FVG', c)}</div>"
                    f"<div style='font-size:.8rem;color:#94a3b8;margin-top:.3rem'>"
                    f"{g['bottom']:,.4f}–{g['top']:,.4f}</div>"
                    f"<div style='font-size:.75rem;color:#64748b'>dist {dist:.2f}% · size {g['sizePct']:.2f}%</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        st.write("")

    # ── Profit / risk row ──────────────────────────────────────────
    profit      = calc_grid_profit_per_grid(
        rng["rangeHigh"], rng["rangeLow"], grid_count["recommended"],
        is_geometric=(mode["mode"] == "Geometric"),
    )
    cap_per_grid = calc_grid_capital_per_grid(capital, grid_count["recommended"])
    sl = calc_grid_stop_loss(rng["rangeLow"], prof_name)
    tp = calc_grid_take_profit(rng["rangeHigh"], prof_name)
    net_color = "#22c55e" if profit["isViable"] else "#ef4444"

    p1, p2, p3, p4 = st.columns(4)
    p1.markdown(mblock("Net / grid",        f"{profit['netPct']*100:.3f}%", net_color),    unsafe_allow_html=True)
    p2.markdown(mblock("Capital / grid",    f"{cap_per_grid:,.2f} USDT",   "#94a3b8"),     unsafe_allow_html=True)
    p3.markdown(mblock(f"SL ({prof_name})", f"{sl:,.4f}",                  "#ef4444"),     unsafe_allow_html=True)
    p4.markdown(mblock(f"TP ({prof_name})", f"{tp:,.4f}",                  "#22c55e"),     unsafe_allow_html=True)

    st.write("")

    # ── Drawdown slider ────────────────────────────────────────────
    crash_pct = st.slider(
        f"Crash % · {symbol}", min_value=5, max_value=60, value=20, step=5,
        key=f"crash-{symbol}",
    )
    crash_price = price * (1 - crash_pct / 100)
    dd = calc_drawdown_scenario(capital, rng["rangeLow"], price, crash_price)
    dd_pct = dd["drawdownPct"] * 100
    dd_color = "#ef4444" if dd_pct > 40 else "#fbbf24" if dd_pct > 20 else "#22c55e"

    d1, d2, d3 = st.columns(3)
    d1.markdown(mblock("Coins held",   f"{dd['coinsHeld']:,.4f}",     "#94a3b8"), unsafe_allow_html=True)
    d2.markdown(mblock("Value @ crash",f"{dd['valueAtCrash']:,.2f} USDT", "#fbbf24"), unsafe_allow_html=True)
    d3.markdown(mblock("Drawdown",     f"{dd['drawdownUSDT']:,.2f} USDT ({dd_pct:.1f}%)", dd_color), unsafe_allow_html=True)

    # ── Chart ──────────────────────────────────────────────────────
    st.write("")
    st.plotly_chart(build_chart(symbol, m, rng), use_container_width=True)

    # ── Pionex action cards ────────────────────────────────────────
    st.markdown("### Recommended Pionex Action")
    a1, a2, a3 = st.columns(3)
    for col, label, kind in (
        (a1, "Long Grid",    "Long"),
        (a2, "Neutral Grid", "Neutral"),
        (a3, "Short Grid",   "Short"),
    ):
        active    = direction["type"] == kind and via["viable"]
        card_cls  = ("card-active-long" if kind == "Long"
                     else "card-active-short" if kind == "Short"
                     else "card-active-neut") if active else ""
        badge     = chip("RECOMMENDED", "green") if active else chip("not now", "grey")
        hdr_color = "#22c55e" if kind == "Long" else "#ef4444" if kind == "Short" else "#fbbf24"
        with col:
            st.markdown(
                f"<div class='card {card_cls}'>"
                f"<h3 style='color:{hdr_color}'>{label}</h3>"
                f"<div style='margin:.3rem 0'>{badge}</div>"
                f"<div style='font-size:.85rem;color:#8b93a7'>"
                f"Range: <b style='color:{hdr_color}'>{rng['rangeLow']:,.4f} – {rng['rangeHigh']:,.4f}</b><br>"
                f"Grids: <b style='color:#e5e7eb'>{grid_count['recommended']}</b> · {mode['mode']}<br>"
                f"Capital: <b style='color:#e5e7eb'>{capital:,.0f} USDT</b><br>"
                f"SL <span style='color:#ef4444'>{sl:,.4f}</span> · "
                f"TP <span style='color:#22c55e'>{tp:,.4f}</span>"
                f"</div></div>",
                unsafe_allow_html=True,
            )
            if active:
                copy_text = (
                    f"{symbol} | {label} | {rng['rangeLow']:.4f}-{rng['rangeHigh']:.4f} | "
                    f"{grid_count['recommended']} grids | {mode['mode']} | "
                    f"{capital:.0f} USDT | SL {sl:.4f} | TP {tp:.4f}"
                )
                st.code(copy_text, language="text")


# ─────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────
st.title(f"Pyonex v{CFG['APP_VERSION']} — Pionex grid scout")

if not selected:
    st.info("Pick at least one pair from the sidebar.")
    st.stop()

payloads: dict[str, dict] = {}
for sym in selected:
    row = latest_metrics(sym)
    if row is not None:
        payloads[sym] = row.payload

if not payloads:
    st.warning("No cached metrics yet — press **Refresh now** in the sidebar.")
    st.stop()

# ── Summary table with conditional styling ─────────────────────────
summary = []
for sym, p in payloads.items():
    summary.append({
        "Symbol":    sym,
        "Price":     p["metrics"].get("currClose", 0.0),
        "Score":     p["scoreInfo"]["score"],
        "Label":     p["scoreInfo"]["label"],
        "Direction": p["direction"]["type"],
        "Viable":    "Yes" if p["viability"]["viable"] else "No",
        "Range %":   round(p["range"]["rangeWidthPct"], 2),
        "Mode":      p["mode"]["mode"],
        "Grids":     p["gridCount"]["recommended"],
        "Struct 4H": p["metrics"].get("structure4h", "Neutral"),
        "Squeeze":   "Yes" if (p["metrics"].get("squeeze") or {}).get("squeeze") else "No",
    })

df_summary = pd.DataFrame(summary).sort_values("Score", ascending=False)


def _score_bg(val: float) -> str:
    if val >= 8:  return "background-color:#052e16;color:#22c55e;font-weight:700"
    if val >= 6:  return "background-color:#1a2e05;color:#84cc16;font-weight:700"
    if val >= 4:  return "background-color:#2d2500;color:#eab308;font-weight:700"
    return "background-color:#2a0f0f;color:#ef4444;font-weight:700"


def _dir_bg(val: str) -> str:
    return ("background-color:#052e16;color:#22c55e" if val == "Long"
            else "background-color:#2a0f16;color:#ef4444" if val == "Short"
            else "background-color:#3b2a0b;color:#fbbf24")


def _via_bg(val: str) -> str:
    return "background-color:#052e16;color:#22c55e" if val == "Yes" \
           else "background-color:#2a0f16;color:#ef4444"


def _struct_bg(val: str) -> str:
    return ("background-color:#052e16;color:#22c55e" if val == "Bullish"
            else "background-color:#2a0f16;color:#ef4444" if val == "Bearish"
            else "background-color:#1e293b;color:#94a3b8")


def _sq_bg(val: str) -> str:
    return "background-color:#082f49;color:#22d3ee" if val == "Yes" else ""


styled = (
    df_summary.style
    .map(_score_bg,  subset=["Score"])
    .map(_dir_bg,    subset=["Direction"])
    .map(_via_bg,    subset=["Viable"])
    .map(_struct_bg, subset=["Struct 4H"])
    .map(_sq_bg,     subset=["Squeeze"])
    .format({"Price": "{:,.4f}", "Score": "{:.1f}", "Range %": "{:.2f}%"})
    .set_properties(**{"text-align": "center"})
)
st.dataframe(styled, use_container_width=True, hide_index=True)

# ── Per-symbol tabs ────────────────────────────────────────────────
tabs = st.tabs(list(payloads.keys()))
for tab, sym in zip(tabs, payloads.keys()):
    with tab:
        render_symbol(payloads[sym], sym)

with st.expander("Phases 2–4 (not active)"):
    st.markdown(
        "- **Phase 2** — trade logger UI + live P&L monitor\n"
        "- **Phase 3** — Telegram alerts on strong setups\n"
        "- **Phase 4** — Pionex active-trade monitor + re-recommend on trend flip"
    )
