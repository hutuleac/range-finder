"""Signal Scanner — Streamlit UI for the predictive signal system."""
from __future__ import annotations

import html as _html

import pandas as pd
import streamlit as st

from telegram_alerts import is_configured as tg_configured, send_signal_alert


# ─────────────────────────────────────────────────────────────────────
#  Colour / badge helpers
# ─────────────────────────────────────────────────────────────────────
_URGENCY_COLORS = {
    "URGENT": ("#ef4444", "#2a0f0f"),
    "SOON": ("#fbbf24", "#3b2a0b"),
    "WATCH": ("#22c55e", "#052e16"),
    "WAIT": ("#94a3b8", "#1e293b"),
}

_SIGNAL_COLORS = {
    "GRID_WINDOW": ("#22d3ee", "#082f49"),
    "LONG_SETUP": ("#22c55e", "#052e16"),
    "SHORT_SETUP": ("#ef4444", "#2a0f0f"),
    "SQUEEZE_PLAY": ("#a78bfa", "#1e1b4b"),
    "NONE": ("#94a3b8", "#1e293b"),
}

_SETUP_SCORE_COLORS = {
    "STRONG SIGNAL": "#22c55e",
    "DEVELOPING": "#fbbf24",
    "EARLY": "#f97316",
    "NO SIGNAL": "#94a3b8",
}


def _chip(text: str, fg: str, bg: str) -> str:
    return (
        f"<span style='display:inline-block;padding:.2rem .55rem;border-radius:6px;"
        f"font-size:.76rem;font-weight:600;background:{bg};color:{fg};"
        f"border:1px solid {fg}33'>{_html.escape(text)}</span>"
    )


def _bar_color(ratio: float) -> str:
    if ratio >= 0.8:
        return "#22c55e"
    if ratio >= 0.5:
        return "#fbbf24"
    if ratio > 0:
        return "#f97316"
    return "#475569"


def _setup_label_color(label: str) -> str:
    return _SETUP_SCORE_COLORS.get(label, "#94a3b8")


# ─────────────────────────────────────────────────────────────────────
#  CSS (injected once)
# ─────────────────────────────────────────────────────────────────────
_CSS = """
<style>
.sig-card {
  padding: 1rem 1.25rem; border-radius: 14px; border: 2px solid #2a2f3a;
  background: linear-gradient(160deg,#12151c 0%,#0b0d12 100%);
  margin-bottom: .75rem;
  font-family: 'JetBrains Mono', monospace;
}
.sig-card-urgent { border-color: #7f1d1d; box-shadow: 0 0 22px rgba(239,68,68,.25); }
.sig-card-soon   { border-color: #78350f; box-shadow: 0 0 22px rgba(251,191,36,.20); }
.sig-card-watch  { border-color: #166534; box-shadow: 0 0 22px rgba(34,197,94,.18); }
.sig-card-wait   { border-color: #1e293b; }
.sig-header { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:.5rem; margin-bottom:.5rem; }
.sig-title { font-size:1.05rem; font-weight:700; color:#f1f5f9; }
.sig-scores { display:flex; gap:.6rem; align-items:baseline; }
.sig-score-big { font-size:1.6rem; font-weight:700; letter-spacing:-.5px; }
.sig-score-sub { font-size:.82rem; color:#94a3b8; }
.sig-meta { font-size:.80rem; color:#94a3b8; margin-bottom:.4rem; }
.sig-bars { margin:.4rem 0; }
.sig-bar-row { display:flex; align-items:center; gap:.4rem; margin:.15rem 0; font-size:.80rem; }
.sig-bar-label { min-width:120px; color:#cbd5e1; }
.sig-bar-bg { flex:1; height:4px; background:#1e293b; border-radius:2px; }
.sig-bar-fill { height:4px; border-radius:2px; }
.sig-bar-val { min-width:50px; text-align:right; color:#94a3b8; font-size:.76rem; }
.sig-bar-detail { color:#6b7280; font-size:.74rem; margin-left:.3rem; }
.sig-action-box {
  margin:.5rem 0; padding:.6rem .8rem; border-radius:10px;
  background:#0f1117; border:1px solid #1e2533; font-size:.82rem;
}
.sig-action-label { color:#94a3b8; font-size:.7rem; text-transform:uppercase; letter-spacing:.5px; }
.sig-action-text { color:#f1f5f9; font-weight:600; margin-top:.1rem; }
.sig-risk-text { color:#ef4444; font-size:.78rem; margin-top:.15rem; }
</style>
"""

# ─────────────────────────────────────────────────────────────────────
#  Recommendation templates
# ─────────────────────────────────────────────────────────────────────
_RECS = {
    "GRID_WINDOW": {
        "action": "Deploy {dir} grid on {sym}",
        "when": "NOW — squeeze conditions confirmed",
        "risk": "Breakout from range — monitor Donchian 20 for break",
    },
    "LONG_SETUP": {
        "action": "Prepare long grid on {sym}",
        "when": "After CVD divergence confirms + RSI stabilises in 35-65",
        "risk": "False divergence — invalidated if price breaks below recent swing low",
    },
    "SHORT_SETUP": {
        "action": "Prepare short grid on {sym}",
        "when": "After CVD divergence confirms + RSI stabilises in 35-65",
        "risk": "False divergence — invalidated if price breaks above recent swing high",
    },
    "SQUEEZE_PLAY": {
        "action": "Wait for liquidation flush on {sym}, then deploy grid",
        "when": "After funding normalises below 0.03%",
        "risk": "Flush may not occur — OI may unwind gradually",
    },
    "NONE": {
        "action": "No action on {sym}",
        "when": "Wait for signal development",
        "risk": "N/A",
    },
}


# ─────────────────────────────────────────────────────────────────────
#  Urgency ranking table
# ─────────────────────────────────────────────────────────────────────
def _render_urgency_table(signal_data: list[dict]) -> None:
    sorted_data = sorted(signal_data, key=lambda d: d["urgency"]["rank_value"], reverse=True)

    rows = []
    for d in sorted_data:
        u = d["urgency"]
        s = d["signal_info"]
        rows.append({
            "Urgency": u["label"],
            "Symbol": d["symbol"],
            "Setup": s["score"],
            "Setup Label": s["label"],
            "Signal": s["signal_type"]["type"].replace("_", " "),
            "Direction": s["signal_type"]["direction"],
            "Grid Score": d.get("grid_score", 0.0),
            "Grid Label": d.get("grid_label", ""),
            "ETA": s["eta"]["label"],
        })

    df = pd.DataFrame(rows)
    if df.empty:
        st.info("No signal data available.")
        return

    def _urg_bg(val: str) -> str:
        for key, (fg, bg) in _URGENCY_COLORS.items():
            if key in val.upper():
                return f"background-color:{bg};color:{fg};font-weight:700"
        return ""

    def _setup_bg(val: float) -> str:
        if val >= 7.5:
            return "background-color:#052e16;color:#22c55e;font-weight:700"
        if val >= 5.0:
            return "background-color:#3b2a0b;color:#fbbf24;font-weight:700"
        if val >= 3.0:
            return "background-color:#431407;color:#f97316;font-weight:700"
        return "background-color:#1e293b;color:#94a3b8"

    def _sig_bg(val: str) -> str:
        val_key = val.upper().replace(" ", "_")
        for key, (fg, bg) in _SIGNAL_COLORS.items():
            if key == val_key:
                return f"background-color:{bg};color:{fg};font-weight:600"
        return ""

    def _dir_bg(val: str) -> str:
        if val == "Long":
            return "background-color:#052e16;color:#22c55e"
        if val == "Short":
            return "background-color:#2a0f16;color:#ef4444"
        return "background-color:#1e293b;color:#94a3b8"

    def _grid_bg(val: float) -> str:
        if val >= 8:
            return "background-color:#052e16;color:#22c55e;font-weight:700"
        if val >= 6:
            return "background-color:#1a2e05;color:#84cc16;font-weight:700"
        if val >= 4:
            return "background-color:#2d2500;color:#eab308;font-weight:700"
        return "background-color:#2a0f0f;color:#ef4444;font-weight:700"

    styled = (
        df.style
        .map(_urg_bg, subset=["Urgency"])
        .map(_setup_bg, subset=["Setup"])
        .map(_sig_bg, subset=["Signal"])
        .map(_dir_bg, subset=["Direction"])
        .map(_grid_bg, subset=["Grid Score"])
        .format({"Setup": "{:.1f}", "Grid Score": "{:.1f}"})
        .set_properties(**{"text-align": "center", "font-size": ".85rem"})
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────
#  Signal detail card
# ─────────────────────────────────────────────────────────────────────
def _render_signal_detail(symbol: str, signal_info: dict, grid_info: dict) -> None:
    si = signal_info
    urgency = si["urgency"]
    card_cls = f"sig-card-{urgency['level'].lower()}"
    setup_color = _setup_label_color(si["label"])
    sig_fg, sig_bg = _SIGNAL_COLORS.get(si["signal_type"]["type"], ("#94a3b8", "#1e293b"))
    urg_fg, urg_bg = _URGENCY_COLORS.get(urgency["level"], ("#94a3b8", "#1e293b"))

    grid_score = grid_info.get("score", 0.0)
    grid_label = grid_info.get("label", "")

    # Header
    html = f"<div class='sig-card {card_cls}'>"
    html += "<div class='sig-header'>"
    html += f"<span class='sig-title'>{_html.escape(symbol)}</span>"
    html += "<div class='sig-scores'>"
    html += f"<span class='sig-score-big' style='color:{setup_color}'>{si['score']:.1f}</span>"
    html += f"<span class='sig-score-sub'>{_html.escape(si['label'])}</span>"
    html += "<span style='color:#475569;font-size:.9rem'>|</span>"
    html += f"<span class='sig-score-sub'>Grid {grid_score:.1f} {_html.escape(grid_label)}</span>"
    html += "</div>"
    html += f"{_chip(urgency['label'], urg_fg, urg_bg)}"
    html += "</div>"

    # Meta line
    html += "<div class='sig-meta'>"
    html += f"Signal: {_chip(si['signal_type']['type'].replace('_', ' '), sig_fg, sig_bg)}"
    html += f"&ensp;Direction: <b style='color:{sig_fg}'>{si['signal_type']['direction']}</b>"
    html += f"&ensp;ETA: <b>{si['eta']['label']}</b>"
    html += "</div>"

    # Component bars
    html += "<div class='sig-bars'>"
    for comp in si["components"]:
        ratio = comp["score"] / comp["max"] if comp["max"] else 0
        pct = int(ratio * 100)
        bc = _bar_color(ratio)
        html += (
            f"<div class='sig-bar-row'>"
            f"<span class='sig-bar-label'>{_html.escape(comp['label'])}</span>"
            f"<div class='sig-bar-bg'><div class='sig-bar-fill' style='width:{pct}%;background:{bc}'></div></div>"
            f"<span class='sig-bar-val'>{comp['score']:.1f}/{comp['max']:.1f}</span>"
            f"<span class='sig-bar-detail'>{_html.escape(comp['detail'])}</span>"
            f"</div>"
        )
    html += "</div>"

    # Recommendation box
    rec = _RECS.get(si["signal_type"]["type"], _RECS["NONE"])
    action = rec["action"].format(sym=symbol, dir=si["signal_type"]["direction"])
    html += (
        f"<div class='sig-action-box'>"
        f"<div class='sig-action-label'>Action</div>"
        f"<div class='sig-action-text'>{_html.escape(action)}</div>"
        f"<div style='margin-top:.2rem'><span class='sig-action-label'>When</span> "
        f"<span style='color:#cbd5e1;font-size:.80rem'>{_html.escape(rec['when'])}</span></div>"
        f"<div class='sig-risk-text'>Risk: {_html.escape(rec['risk'])}</div>"
        f"<div style='color:#6b7280;font-size:.74rem;margin-top:.15rem;font-style:italic'>"
        f"{_html.escape(si['signal_type']['reason'])}</div>"
        f"</div>"
    )

    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────
#  Leading indicators chart
# ─────────────────────────────────────────────────────────────────────
def _render_leading_chart(symbol: str, chart_data: dict) -> None:
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        st.warning("Plotly not available for charts.")
        return

    bw = chart_data.get("bb_bw", [])
    cvd = chart_data.get("cvd", [])
    price = chart_data.get("price", [])

    if not bw and not cvd:
        return

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.5, 0.5], vertical_spacing=0.06,
        subplot_titles=("BB Bandwidth %", "Price + CVD"),
    )

    if bw:
        x = list(range(len(bw)))
        fig.add_trace(go.Scatter(
            x=x, y=bw, mode="lines", name="BB Width %",
            line=dict(color="#fbbf24", width=1.5),
        ), row=1, col=1)
        fig.add_hline(y=5.0, line_dash="dash", line_color="#ef4444", opacity=0.5,
                      annotation_text="Squeeze threshold", row=1, col=1)

    if price:
        x = list(range(len(price)))
        fig.add_trace(go.Scatter(
            x=x, y=price, mode="lines", name="Price",
            line=dict(color="#94a3b8", width=1.5),
        ), row=2, col=1)

    if cvd:
        x = list(range(len(cvd)))
        fig.add_trace(go.Scatter(
            x=x, y=cvd, mode="lines", name="CVD",
            line=dict(color="#22d3ee", width=1.2),
            yaxis="y4",
        ), row=2, col=1)

    fig.update_layout(
        height=360,
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(11,13,18,1)",
        margin=dict(l=50, r=50, t=30, b=20),
        showlegend=True,
        legend=dict(orientation="h", y=1.12, x=0.5, xanchor="center", font=dict(size=10)),
        font=dict(family="JetBrains Mono, monospace", size=11),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor="rgba(30,37,51,0.8)")

    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────
#  Comparison table
# ─────────────────────────────────────────────────────────────────────
def _render_comparison_table(signal_data: list[dict]) -> None:
    rows = []
    for d in signal_data:
        si = d["signal_info"]
        rows.append({
            "Symbol": d["symbol"],
            "Grid Score": d.get("grid_score", 0.0),
            "Grid": d.get("grid_label", ""),
            "Setup Score": si["score"],
            "Setup": si["label"],
            "Signal": si["signal_type"]["type"].replace("_", " "),
            "ETA": si["eta"]["label"],
            "Outlook": _cross_ref(si["score"], d.get("grid_score", 0.0)),
        })

    df = pd.DataFrame(rows).sort_values("Setup Score", ascending=False)
    if df.empty:
        return

    def _outlook_bg(val: str) -> str:
        if "Deploy" in val:
            return "background-color:#052e16;color:#22c55e;font-weight:700"
        if "Prepare" in val:
            return "background-color:#3b2a0b;color:#fbbf24;font-weight:600"
        if "Monitor" in val:
            return "background-color:#431407;color:#f97316"
        return ""

    styled = (
        df.style
        .map(_outlook_bg, subset=["Outlook"])
        .format({"Grid Score": "{:.1f}", "Setup Score": "{:.1f}"})
        .set_properties(**{"text-align": "center", "font-size": ".84rem"})
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _cross_ref(setup: float, grid: float) -> str:
    if setup >= 7.0 and grid >= 7.0:
        return "Deploy now"
    if setup >= 5.0 and grid < 5.0:
        return "Prepare — wait for grid"
    if setup < 3.0 and grid >= 7.0:
        return "Monitor — may not last"
    return "Skip"


# ─────────────────────────────────────────────────────────────────────
#  Main entry point
# ─────────────────────────────────────────────────────────────────────
def render_signal_scanner(selected: list[str], payloads: dict[str, dict]) -> None:
    st.markdown(_CSS, unsafe_allow_html=True)

    st.markdown(
        "<div style='font-size:.72rem;color:#64748b;letter-spacing:.6px;text-transform:uppercase;"
        "margin-bottom:.5rem'>Signal Scanner — Leading Indicators</div>",
        unsafe_allow_html=True,
    )

    signal_data: list[dict] = []
    for sym in selected:
        p = payloads.get(sym)
        if not p:
            continue
        si = p.get("signalInfo")
        if not si:
            continue
        signal_data.append({
            "symbol": sym,
            "signal_info": si,
            "urgency": si["urgency"],
            "grid_score": p.get("scoreInfo", {}).get("score", 0.0),
            "grid_label": p.get("scoreInfo", {}).get("label", ""),
        })

    if not signal_data:
        st.warning("No signal data — press **Refresh now** in the sidebar to generate signals.")
        return

    # Telegram alerts for URGENT signals
    if tg_configured():
        for d in signal_data:
            send_signal_alert(d["symbol"], d["signal_info"])

    # Section A: Urgency ranking table
    _render_urgency_table(signal_data)

    st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)

    # Section B: Detail cards sorted by urgency
    sorted_data = sorted(signal_data, key=lambda d: d["urgency"]["rank_value"], reverse=True)
    for d in sorted_data:
        si = d["signal_info"]
        _render_signal_detail(d["symbol"], si, {"score": d["grid_score"], "label": d["grid_label"]})

        with st.expander(f"Leading Indicators Chart — {d['symbol']}", expanded=False):
            _render_leading_chart(d["symbol"], si.get("chart_data", {}))

    # Section C: Comparison table
    with st.expander("Grid Score vs Setup Score — Comparison", expanded=False):
        _render_comparison_table(signal_data)
