"""Pyonex Streamlit dashboard — Phase 1."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
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


@st.cache_resource
def _start_scheduler():
    from datetime import timezone
    from apscheduler.schedulers.background import BackgroundScheduler
    from refresh_data import main as _main

    def _bg_refresh():
        try:
            _main(DEFAULT_PAIRS)
        except Exception:  # noqa: BLE001
            pass

    sched = BackgroundScheduler(daemon=True)
    sched.add_job(
        _bg_refresh, "interval",
        seconds=CFG["REFRESH_INTERVAL_SEC"],
        id="bg_refresh",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),  # fire immediately on startup
    )
    sched.start()
    return sched


_start_scheduler()


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
#  Sidebar
# ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title(f"Pyonex v{CFG['APP_VERSION']}")
    st.caption("Grid-bot scout for Pionex — OKX/Bybit data")

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

    bb_color   = "#22d3ee" if bb_lb == "squeeze" else "#ef4444" if bb_lb == "expanded" else "#e5e7eb"
    flow_color = "#22c55e" if flow > CFG["FLOW_STRONG"] else "#ef4444" if flow < -CFG["FLOW_STRONG"] else "#fbbf24"
    oi_color   = "#22c55e" if oi_ch > 0 else "#ef4444"
    str_color  = "#22c55e" if str4h == "Bullish" else "#ef4444" if str4h == "Bearish" else "#94a3b8"
    rng_color  = "#22c55e" if direction["type"] == "Long" else "#ef4444" if direction["type"] == "Short" else "#fbbf24"
    fund_color = "#fbbf24" if abs(fund) > 0.05 else "#22c55e"

    cls        = score_cls(score)
    dir_chip_h = direction_chip(direction["type"])
    via_chip_h = chip("VIABLE", "green") if via["viable"] else chip("BLOCKED", "red")
    sq_chip_h  = chip("SQUEEZE", "cyan") if sq else ""

    sl           = calc_grid_stop_loss(rng["rangeLow"], prof_name)
    tp           = calc_grid_take_profit(rng["rangeHigh"], prof_name)
    profit       = calc_grid_profit_per_grid(
        rng["rangeHigh"], rng["rangeLow"], grid_count["recommended"],
        is_geometric=(mode["mode"] == "Geometric"),
    )
    cap_per_grid = calc_grid_capital_per_grid(capital, grid_count["recommended"])

    # ── Header card ────────────────────────────────────────────────
    st.markdown(
        f"<div class='card'>"
        f"<div style='font-size:.7rem;color:#64748b;letter-spacing:.8px;text-transform:uppercase;margin-bottom:.35rem'>{symbol}</div>"
        f"<div style='display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:.5rem'>"
        f"<div>"
        f"<span class='metric-big {cls}'>{score:.1f}</span>"
        f"<span style='font-size:.9rem;color:#8b93a7'> / 10 &nbsp;{score_info['label']}</span>"
        f"<div style='margin:.3rem 0;display:flex;flex-wrap:wrap;gap:.3rem'>"
        f"{dir_chip_h} {via_chip_h} {sq_chip_h}"
        f"</div>"
        f"</div>"
        f"<div style='text-align:right'>"
        f"<div style='font-size:1.05rem;font-weight:600;color:#f8fafc'>{price:,.4f}"
        f"<span style='font-size:.72rem;color:#64748b'> USDT</span></div>"
        f"<div style='font-size:.8rem;color:{str_color};margin-top:.2rem'>Struct: {str4h}</div>"
        f"</div>"
        f"</div>"
        f"<div style='margin-top:.45rem;font-size:.84rem'>"
        f"<span style='color:#8b93a7'>Range </span>"
        f"<span style='color:{rng_color};font-weight:600'>{rng['rangeLow']:,.4f} – {rng['rangeHigh']:,.4f}</span>"
        f"<span style='color:#64748b'> &nbsp;{rng['rangeWidthPct']:.1f}% · {grid_count['recommended']} grids"
        f" · {mode['mode']} · ~{duration['label']}</span>"
        f"</div>"
        f"<div style='font-size:.75rem;color:#64748b;margin-top:.2rem'>{direction['reason']}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Metrics — CSS grid, 3-col on mobile ────────────────────────
    st.markdown(
        "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:.4rem;margin:.5rem 0'>"
        + mblock("RSI 4H",   f"{rsi:.1f}",          rsi_color(rsi))
        + mblock("ATR %",    f"{atr_p:.2f}%",       "#fbbf24" if atr_p > 3 else "#94a3b8")
        + mblock("ADX",      f"{adx_v:.1f}",        adx_color(adx_v))
        + mblock("BB BW",    f"{bb_bw:.2f}%",       bb_color)
        + mblock("Flow 24h", f"{flow:+.1f}%",       flow_color)
        + mblock("OI 7d",    f"{oi_ch:+.1f}%",      oi_color)
        + mblock("Funding",  f"{fund:+.4f}%",       fund_color)
        + mblock("Net/grid", f"{profit['netPct']*100:.3f}%",
                             "#22c55e" if profit["isViable"] else "#ef4444")
        + "</div>",
        unsafe_allow_html=True,
    )

    # ── Score bars + missing hints — single markdown call ──────────
    bars = ""
    for comp in score_info["components"]:
        ratio = comp["score"] / comp["max"] if comp["max"] else 0
        bc    = comp_bar_color(ratio)
        pct   = int(ratio * 100)
        bars += (
            f"<div class='comp-row'>"
            f"<span style='width:110px;color:#94a3b8;font-size:.78rem'>{comp['label']}</span>"
            f"<div class='comp-bar-bg'><div class='comp-bar' style='width:{pct}%;background:{bc}'></div></div>"
            f"<span style='width:28px;text-align:right;color:{bc};font-weight:600;font-size:.78rem'>{comp['score']:.1f}</span>"
            f"<span style='color:#64748b;font-size:.74rem'> /{comp['max']}</span>"
            f"<span style='color:#64748b;font-size:.72rem;margin-left:.3rem'>{comp['detail']}</span>"
            f"</div>"
        )
    for r in score_info.get("recs", []):
        bars += f"<div style='font-size:.75rem;color:#fbbf24;margin:.1rem 0'>▸ {r}</div>"
    if bars:
        st.markdown(bars, unsafe_allow_html=True)

    # ── Viability + CVD ────────────────────────────────────────────
    def cvd_badge(v: float, tf: str) -> str:
        c = "#22c55e" if v > 0 else "#ef4444"
        return f"<span style='color:{c};font-weight:600'>{tf} {'ACC' if v > 0 else 'DIS'}</span>"

    warn_html = (f" &nbsp;<span style='color:#fbbf24'>{via['warning']}</span>"
                 if via.get("warning") else "")
    st.markdown(
        f"<div class='card' style='margin-top:.5rem'>"
        f"<div style='font-size:.82rem;margin-bottom:.3rem'>{via_chip_h} {via['reason']}{warn_html}</div>"
        f"<div style='display:flex;gap:.75rem;flex-wrap:wrap;font-size:.87rem'>"
        f"{cvd_badge(cvd5,'5d')} {cvd_badge(cvd14,'14d')} {cvd_badge(cvd30,'30d')}"
        f"<span style='color:#64748b'>OI <b style='color:{oi_color}'>{oi_ch:+.1f}%</b>"
        f" · Fund <b style='color:{fund_color}'>{fund:+.4f}%</b></span>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    # ── FVG — CSS grid ─────────────────────────────────────────────
    fvg_list = m.get("fvgList", [])
    if fvg_list:
        fvg_html = "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:.4rem;margin:.5rem 0'>"
        for g in fvg_list[:5]:
            c    = "green" if g["type"] == "BULL" else "red"
            dist = abs(price - g["mid"]) / price * 100 if price else 0
            fvg_html += (
                f"<div class='card' style='padding:.45rem .55rem;text-align:center'>"
                f"{chip(g['type']+' FVG', c)}"
                f"<div style='font-size:.72rem;color:#94a3b8;margin-top:.2rem'>"
                f"{g['bottom']:,.4f}–{g['top']:,.4f}</div>"
                f"<div style='font-size:.68rem;color:#64748b'>dist {dist:.1f}%</div>"
                f"</div>"
            )
        st.markdown(fvg_html + "</div>", unsafe_allow_html=True)

    # ── SL / TP / Capital — CSS grid ───────────────────────────────
    st.markdown(
        "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:.4rem;margin:.5rem 0'>"
        + mblock("Capital/grid",      f"{cap_per_grid:,.2f}", "#94a3b8")
        + mblock(f"SL ({prof_name})", f"{sl:,.4f}",           "#ef4444")
        + mblock(f"TP ({prof_name})", f"{tp:,.4f}",           "#22c55e")
        + "</div>",
        unsafe_allow_html=True,
    )

    # ── Drawdown ───────────────────────────────────────────────────
    crash_pct   = st.slider(f"Crash % · {symbol}", 5, 60, 20, 5, key=f"crash-{symbol}")
    crash_price = price * (1 - crash_pct / 100)
    dd          = calc_drawdown_scenario(capital, rng["rangeLow"], price, crash_price)
    dd_pct      = dd["drawdownPct"] * 100
    dd_color    = "#ef4444" if dd_pct > 40 else "#fbbf24" if dd_pct > 20 else "#22c55e"
    st.markdown(
        "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:.4rem;margin:.3rem 0 .5rem'>"
        + mblock("Coins held",  f"{dd['coinsHeld']:,.4f}",                    "#94a3b8")
        + mblock("Value@crash", f"{dd['valueAtCrash']:,.2f}",                 "#fbbf24")
        + mblock("Drawdown",    f"{dd['drawdownUSDT']:,.2f} ({dd_pct:.1f}%)", dd_color)
        + "</div>",
        unsafe_allow_html=True,
    )

    # ── Recommended action ─────────────────────────────────────────
    if via["viable"]:
        act      = direction["type"]
        hdr_c    = "#22c55e" if act == "Long" else "#ef4444" if act == "Short" else "#fbbf24"
        card_cls = ("card-active-long" if act == "Long"
                    else "card-active-short" if act == "Short" else "card-active-neut")
        st.markdown(
            f"<div class='card {card_cls}'>"
            f"<div style='margin-bottom:.3rem'>"
            f"<b style='color:{hdr_c}'>{act} Grid</b> &nbsp;{chip('RECOMMENDED','green')}</div>"
            f"<div style='font-size:.84rem;color:#8b93a7'>"
            f"Range <b style='color:{hdr_c}'>{rng['rangeLow']:,.4f} – {rng['rangeHigh']:,.4f}</b>"
            f" &nbsp;Grids <b style='color:#e5e7eb'>{grid_count['recommended']}</b> · {mode['mode']}<br>"
            f"Capital <b style='color:#e5e7eb'>{capital:,.0f} USDT</b>"
            f" &nbsp;SL <span style='color:#ef4444'>{sl:,.4f}</span>"
            f" &nbsp;TP <span style='color:#22c55e'>{tp:,.4f}</span>"
            f"</div></div>",
            unsafe_allow_html=True,
        )
        st.code(
            f"{symbol} | {act} Grid | {rng['rangeLow']:.4f}-{rng['rangeHigh']:.4f} | "
            f"{grid_count['recommended']} grids | {mode['mode']} | "
            f"{capital:.0f} USDT | SL {sl:.4f} | TP {tp:.4f}",
            language="text",
        )
    else:
        st.markdown(
            f"<div style='font-size:.84rem;color:#64748b;padding:.4rem 0'>"
            f"No grid recommended — {via['reason']}</div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")


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
# ── Per-symbol cards — swipe down ─────────────────────────────────
for sym in payloads:
    render_symbol(payloads[sym], sym)

# ── Summary table — desktop only (collapsed by default) ────────────
with st.expander("Summary table", expanded=False):
    st.dataframe(styled, use_container_width=True, hide_index=True)

with st.expander("Phases 2–4 (not active)"):
    st.markdown(
        "- **Phase 2** — trade logger UI + live P&L monitor\n"
        "- **Phase 3** — Telegram alerts on strong setups\n"
        "- **Phase 4** — Pionex active-trade monitor + re-recommend on trend flip"
    )
