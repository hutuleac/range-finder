"""Streamlit page for the Calibration Signal Health view.

Reads docs/CALIBRATION_SUMMARY.json (written by calibration.run) and renders
metric cards showing signal validity. Includes a Re-run button that executes
the harness on the selected pairs using cached klines (no new network needed).
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

SUMMARY_PATH = Path(__file__).resolve().parent / "docs" / "CALIBRATION_SUMMARY.json"
REPORT_PATH = Path(__file__).resolve().parent / "docs" / "CALIBRATION_REPORT.md"


def _load_summary() -> dict | None:
    try:
        return json.loads(SUMMARY_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return None


def _auc_color(auc: float | None) -> str:
    if auc is None:
        return "gray"
    if auc >= 0.6:
        return "green"
    if auc >= 0.45:
        return "orange"
    return "red"


def _r_color(r: float | None) -> str:
    if r is None:
        return "gray"
    return "green" if r > 0.1 else ("red" if r < -0.1 else "orange")


def _fmt(v: float | None, decimals: int = 3) -> str:
    return f"{v:.{decimals}f}" if v is not None else "n/a"


def render_calibration_page(selected_pairs: list[str]) -> None:
    st.header("Calibration — Signal Health")

    summary = _load_summary()

    if summary is None:
        st.warning(
            "No calibration summary found. Run the harness to generate one.",
            icon="⚠️",
        )
    else:
        st.caption(
            f"Last run: {summary.get('generated', 'unknown')} · "
            f"Pairs: {', '.join(summary.get('pairs', []))} · "
            f"{summary.get('n_steps', 0)} walk steps "
            f"({summary.get('n_live_steps', 0)} with live signals)"
        )

        # ── Regime layer ─────────────────────────────────────────────
        st.subheader("Regime layer (ER × Hurst)")
        c1, c2, c3 = st.columns(3)

        er_r = summary.get("er_vs_trendiness")
        h_r = summary.get("hurst_vs_trendiness")
        rng = summary.get("ranging_mean_trendiness")
        trnd = summary.get("trending_mean_trendiness")

        with c1:
            color = _r_color(er_r)
            st.metric("ER vs fwd trendiness (r)", _fmt(er_r))
            st.caption(
                f":{color}[{'✓ as-expected' if er_r and er_r > 0.1 else '✗ WRONG sign — mean-reversion effect'}]"
            )
        with c2:
            color = _r_color(h_r)
            st.metric("Hurst vs fwd trendiness (r)", _fmt(h_r))
            st.caption(
                f":{color}[{'✓ as-expected' if h_r and h_r > 0.1 else '✗ WRONG sign'}]"
            )
        with c3:
            if rng is not None and trnd is not None:
                separation = rng < trnd
                st.metric("RANGING mean trendiness", _fmt(rng))
                st.caption(
                    f"vs TRENDING {_fmt(trnd)} · "
                    f":{'green' if separation else 'red'}[{'✓ separates' if separation else '✗ inverted'}]"
                )
            else:
                st.metric("RANGING/TRENDING split", "n/a")

        # ── Matrix scores ─────────────────────────────────────────────
        st.subheader("Matrix scores (GRID_NEUTRAL)")
        m1, m2, m3 = st.columns(3)

        gn_all = summary.get("grid_neutral_auc")
        gn_live = summary.get("grid_neutral_auc_live")
        dr = summary.get("directional_auc")

        with m1:
            color = _auc_color(gn_all)
            st.metric("GRID_NEUTRAL AUC (all steps)", _fmt(gn_all))
            verdict = "✓ separates" if (gn_all or 0) > 0.55 else ("≈ coin-flip" if abs((gn_all or 0.5) - 0.5) < 0.1 else "✗ inverted")
            st.caption(f":{color}[{verdict}]")
        with m2:
            color = _auc_color(gn_live)
            n_live = summary.get("n_live_steps", 0)
            st.metric(f"GRID_NEUTRAL AUC (live, n={n_live})", _fmt(gn_live))
            verdict = "✓ separates" if (gn_live or 0) > 0.55 else ("≈ coin-flip" if abs((gn_live or 0.5) - 0.5) < 0.1 else "✗ inverted")
            st.caption(f":{color}[{verdict}]" if gn_live is not None else ":gray[n/a — run harness]")
        with m3:
            color = _auc_color(dr)
            st.metric("DIRECTIONAL AUC", _fmt(dr))
            verdict = "✓ separates" if (dr or 0) > 0.55 else ("≈ coin-flip" if abs((dr or 0.5) - 0.5) < 0.1 else "✗ inverted")
            st.caption(f":{color}[{verdict}]")

    # ── Re-run button ─────────────────────────────────────────────────
    st.divider()
    pairs_for_run = selected_pairs or ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        run_clicked = st.button("Re-run calibration", use_container_width=True)
    with col_info:
        st.caption(
            f"Runs on: {', '.join(pairs_for_run)} · uses cached klines + live "
            "Binance data for funding/OI · ~10–30s"
        )

    if run_clicked:
        with st.spinner("Running calibration harness…"):
            try:
                from calibration.run import run as _cal_run
                _cal_run(pairs_for_run, horizon=5, max_steps=60, use_network=True)
                st.success("Done — report updated.")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"Calibration failed: {e}")

    # ── Full report expander ──────────────────────────────────────────
    if REPORT_PATH.exists():
        with st.expander("Full calibration report", expanded=False):
            st.markdown(REPORT_PATH.read_text())
