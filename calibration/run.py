"""Offline calibration runner (thin IO shell).

    python3 -m calibration.run [--pairs BTC/USDT,ETH/USDT] [--no-network]
                               [--horizon 5] [--max-steps 60]

Fetches historical daily + 4H klines (cached to calibration/_cache/), walks a
rolling window over the daily index, reconstructs the regime + price-derived
matrix features as of each step with NO lookahead, computes forward N-bar
outcomes, measures separation, and writes docs/CALIBRATION_REPORT.md.

NON-DESTRUCTIVE: imports config/regime/matrix/indicators read-only, never
mutates them, never touches refresh_data. Network is the ONLY side effect, and
it is cached + skippable (--no-network reuses the cache and exits cleanly if a
pair is uncached).

All heavy logic lives in calibration.features (pure, unit-tested). This module
is deliberately thin: fetch, cache, drive, render.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd

from config import CFG, DEFAULT_PAIRS
from indicators import (
    calc_adx,
    calc_atr,
    calc_atr_pct,
    calc_bb,
    calc_market_structure,
    calc_rsi,
    parse_klines,
)
from matrix import calc_matrix
from regime import build_regime

from calibration import features as F

log = logging.getLogger("calibration")

CACHE_DIR = Path(__file__).resolve().parent / "_cache"
REPORT_PATH = Path(__file__).resolve().parents[1] / "docs" / "CALIBRATION_REPORT.md"

# Bounded defaults — keep runtime small and rate-limit friendly.
DEFAULT_PAIR_SAMPLE = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
HORIZON_DAYS = 5            # forward outcome horizon (daily bars)
MAX_STEPS = 60             # cap walk steps per pair
WARMUP = 95                # need >= HURST_WINDOW(90)+ER(10) daily bars before first step
FETCH_SLEEP_S = 0.4        # gentle pacing between network calls


# ─────────────────────────────────────────────────────────────────────
#  Fetch + disk cache (the only side effect)
# ─────────────────────────────────────────────────────────────────────
def _cache_path(symbol: str, timeframe: str) -> Path:
    safe = symbol.replace("/", "_")
    return CACHE_DIR / f"{safe}_{timeframe}.json"


def load_klines(symbol: str, timeframe: str, limit: int, use_network: bool) -> list[list]:
    """Return raw klines, preferring the on-disk cache. Fetches + caches on miss
    when use_network is True. Returns [] when uncached and offline."""
    path = _cache_path(symbol, timeframe)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (ValueError, OSError) as e:  # corrupt cache → refetch if allowed
            log.warning("cache read failed %s: %s", path.name, e)
    if not use_network:
        log.warning("no cache for %s %s and --no-network set", symbol, timeframe)
        return []
    from data_fetcher import fetch_klines  # imported lazily so --no-network never needs ccxt
    try:
        raw = fetch_klines(symbol, timeframe, limit)
    except Exception as e:  # noqa: BLE001 — network is best-effort here
        log.warning("fetch failed %s %s: %s", symbol, timeframe, e)
        raw = []
    if raw:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw))
        time.sleep(FETCH_SLEEP_S)
    return raw


# ─────────────────────────────────────────────────────────────────────
#  Per-pair walk
# ─────────────────────────────────────────────────────────────────────
def walk_pair(symbol: str, horizon: int, max_steps: int, use_network: bool) -> tuple[list, list]:
    """Return (feature_rows, outcome_rows) for one pair, or ([],[]) on no data."""
    raw_daily = load_klines(symbol, "1d", CFG["KLINES_DAILY"], use_network)
    raw_4h = load_klines(symbol, "4h", CFG["KLINES_MAIN"], use_network)
    df_daily = parse_klines(raw_daily)
    df_4h = parse_klines(raw_4h)
    if df_daily.empty or len(df_daily) < WARMUP + horizon + 2:
        log.warning("skip %s — insufficient daily bars (%d)", symbol, len(df_daily))
        return [], []

    daily_closes = df_daily["Close"].tolist()
    daily_times = df_daily["Time"].tolist() if "Time" in df_daily.columns else [None] * len(daily_closes)
    last_idx = len(daily_closes) - horizon - 1
    start_idx = max(WARMUP, last_idx - max_steps + 1)

    feats, outs = [], []
    for idx in range(start_idx, last_idx + 1):
        t_ms = daily_times[idx]
        reg = F.reconstruct_regime(daily_closes, df_4h, idx, t_ms, build_regime)
        visible_4h = F._slice_4h_for_daily(df_4h, t_ms) if t_ms is not None else df_4h
        price_metrics = F.reconstruct_price_metrics(
            visible_4h, calc_rsi, calc_atr, calc_atr_pct,
            calc_adx, calc_bb, calc_market_structure, CFG["STRUCT_LOOKBACK_4H"],
        )
        scores = F.reconstruct_matrix_scores(price_metrics, reg["_regime"], calc_matrix)
        feats.append({
            "symbol": symbol, "idx": idx,
            "er_value": reg["er_value"], "er_regime": reg["er_regime"],
            "hurst": reg["hurst"], "hurst_regime": reg["hurst_regime"],
            "combined_regime": reg["combined_regime"],
            "grid_neutral": scores.get("GRID_NEUTRAL"),
            "directional": scores.get("DIRECTIONAL"),
        })
        outs.append({
            "fwd_trendiness": F.forward_trendiness(daily_closes, idx, horizon),
            "fwd_abs_return": F.forward_abs_return(daily_closes, idx, horizon),
            "fwd_realized_vol": F.forward_realized_vol(daily_closes, idx, horizon),
        })
    return feats, outs


# ─────────────────────────────────────────────────────────────────────
#  Report rendering
# ─────────────────────────────────────────────────────────────────────
def _fmt(x: object, nd: int = 3) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def render_report(sep: dict, per_pair: dict, meta: dict) -> str:
    """Build the markdown report from the aggregated separation stats."""
    rg = sep.get("ranging_grid_quality", {})

    def auc_verdict(a: float | None) -> str:
        if a is None:
            return "no data"
        if abs(a - 0.5) < 0.05:
            return "NO separation (≈coin-flip)"
        return "separates" if a > 0.5 else "INVERTED (signal points the wrong way)"

    def r_verdict(r: float | None, expect_sign: str) -> str:
        if r is None:
            return "no data"
        if abs(r) < 0.1:
            return "NO correlation"
        ok = (r > 0) if expect_sign == "+" else (r < 0)
        return "as-expected" if ok else "WRONG sign vs heuristic"

    lines: list[str] = []
    A = lines.append
    A("# Range Finder — Regime & Matrix Calibration Report")
    A("")
    A("> **Status: suggestions pending review — NOT validated for live use.**  ")
    A("> This is an offline *signal check*, not a trading backtest. All proposed "
      "values below are derived from a small, bounded historical sample and must "
      "be reviewed before any config change.")
    A("")
    A("## Methodology")
    A("")
    A(f"- **Run mode:** {meta['mode']} · generated {meta['generated']}")
    A(f"- **Pairs:** {', '.join(meta['pairs'])}")
    A(f"- **Forward horizon:** {meta['horizon']} daily bars · "
      f"**max steps/pair:** {meta['max_steps']} · **total walk steps:** {sep['n_steps']}")
    A("- For each daily index `t` (after a 95-bar warm-up for Hurst+ER), we "
      "reconstruct `build_regime` and the price-derived slice of `calc_matrix` "
      "using ONLY data ≤ `t` (no lookahead), then measure forward outcomes over "
      "bars `t+1..t+N`.")
    A("- **Forward outcomes:** *trendiness* (ER-style net/path of the next N bars; "
      "low = good grid window), *abs return*, *realized vol*.")
    A("- **Stats are numpy-only:** Pearson r, group means, rank-AUC "
      "(Mann-Whitney U). No scipy/sklearn.")
    A("")
    A("> **Honesty caveat — matrix inputs.** `calc_matrix` consumes live-only "
      "signals (funding, OI change, flow, CVD) that CANNOT be reconstructed from "
      "historical OHLCV. They are held at their neutral default during this "
      "replay, so the reported GRID_NEUTRAL / DIRECTIONAL scores reflect the "
      "**price + regime** structure only. Treat matrix findings as a partial "
      "check; the regime layer (ER × Hurst) is the fully-reconstructable, "
      "primary target.")
    A("")
    A("## Per-signal separation results")
    A("")
    A("### 1. Regime layer (fully reconstructable — primary)")
    A("")
    A("| Signal | Statistic | Value | Expectation | Verdict |")
    A("|---|---|---|---|---|")
    A(f"| ER vs forward trendiness | Pearson r | {_fmt(sep['er_vs_trendiness'])} | "
      f"positive (high ER → trends) | {r_verdict(sep['er_vs_trendiness'], '+')} |")
    A(f"| Hurst vs forward trendiness | Pearson r | {_fmt(sep['hurst_vs_trendiness'])} | "
      f"positive (high H → persistence) | {r_verdict(sep['hurst_vs_trendiness'], '+')} |")
    A("")
    A("**ER regime → forward trendiness (group means).** RANGING should show the "
      "LOWEST forward trendiness if the regime split is real:")
    A("")
    A("| ER regime | mean fwd trendiness | median | n |")
    A("|---|---|---|---|")
    for regime in ("RANGING", "TRANSITIONAL", "TRENDING", "UNKNOWN"):
        if regime in rg:
            g = rg[regime]
            A(f"| {regime} | {_fmt(g['mean'])} | {_fmt(g['median'])} | {g['n']} |")
    A("")
    A("### 2. Matrix scores (price+regime only — partial)")
    A("")
    A("| Signal | Statistic | Value | Expectation | Verdict |")
    A("|---|---|---|---|---|")
    A(f"| GRID_NEUTRAL → low fwd trendiness | rank-AUC | {_fmt(sep['grid_neutral_auc'])} | "
      f">0.5 | {auc_verdict(sep['grid_neutral_auc'])} |")
    A(f"| DIRECTIONAL → high fwd abs return | rank-AUC | {_fmt(sep['directional_auc'])} | "
      f">0.5 | {auc_verdict(sep['directional_auc'])} |")
    A("")
    A("### Per-pair step counts")
    A("")
    A("| Pair | walk steps |")
    A("|---|---|")
    for sym, n in per_pair.items():
        A(f"| {sym} | {n} |")
    A("")
    A("## Which heuristics look mis-set")
    A("")
    A(_findings_block(sep))
    A("")
    A("## Proposed config diff (NOT applied)")
    A("")
    A("```python")
    A("# calibration/run.py output — suggestions pending review, NOT validated "
      "for live use.")
    A("# Apply by hand to config.py ONLY after a larger multi-pair run confirms "
      "the direction holds.")
    A(_proposed_diff(sep))
    A("```")
    A("")
    A("## Caveats")
    A("")
    A("- Small bounded sample (few pairs, capped steps) — directional hint only, "
      "not statistical proof.")
    A(f"- **Overlapping windows → autocorrelated steps.** Consecutive walk steps "
      f"share {meta['horizon'] - 1} of {meta['horizon']} forward bars, so the "
      f"{sep['n_steps']} steps are NOT independent — effective sample size is "
      "much smaller. Read every r/AUC as a flag to investigate on a larger, "
      "non-overlapping run, not as a result.")
    A("- Matrix live-only inputs held neutral (see honesty caveat) — matrix "
      "findings are partial.")
    A("- Forward trendiness is a *proxy* for grid suitability, not realized grid "
      "P&L. A true validation would simulate grid fills.")
    A("- No multiple-testing correction; treat any single r/AUC as a flag to "
      "investigate, not a conclusion.")
    A("")
    return "\n".join(lines)


def _findings_block(sep: dict) -> str:
    out = []
    er_r = sep.get("er_vs_trendiness")
    rg = sep.get("ranging_grid_quality", {})
    gn = sep.get("grid_neutral_auc")
    dr = sep.get("directional_auc")

    # ER: three-way — sound (+), no link (≈0), or STRONG INVERSION (large −).
    if er_r is not None and er_r > 0.1:
        out.append("- **ER threshold looks directionally sound.** ER correlates "
                   "positively with forward trendiness, matching the heuristic "
                   "premise (high ER → trend). The 0.3/0.6 cut points are the "
                   "lever to tune, not the sign.")
    elif er_r is not None and er_r < -0.25:
        out.append(f"- **ER is STRONGLY INVERTED (r={er_r:.2f}) on this sample.** "
                   "High trailing efficiency was followed by *less* directional "
                   "movement, not more — consistent with mean-reversion after a "
                   "completed move. If this holds on a larger run, the ER→grid "
                   "rule may have the sign backwards: high ER could be a grid "
                   "ENTRY cue, not an avoid cue. Lengthening ER_PERIOD will NOT "
                   "fix a sign flip — investigate the rule direction itself.")
    elif er_r is not None:
        out.append("- **ER shows weak/no link to forward trendiness on this "
                   "sample.** The 0.3/0.6 thresholds may be mis-set for these "
                   "pairs, or the daily ER period (10) is too short. Flag for a "
                   "larger run before trusting ER-driven grid gating.")

    ranging = rg.get("RANGING")
    trending = rg.get("TRENDING")
    if ranging and trending:
        if ranging["mean"] < trending["mean"]:
            out.append("- **RANGING vs TRENDING separation present:** RANGING "
                       "steps were followed by lower trendiness than TRENDING "
                       "steps — the regime split carries signal.")
        else:
            out.append("- **RANGING vs TRENDING separation absent/inverted:** "
                       "RANGING did NOT predict calmer forward bars on this "
                       "sample. The ER regime cut points are the prime suspect.")

    # GRID_NEUTRAL AUC: inversion (≪0.5) is as loud as separation (≫0.5).
    if gn is not None and gn < 0.35:
        out.append(f"- **GRID_NEUTRAL score is ANTI-PREDICTIVE (AUC={gn:.2f}).** "
                   "A *higher* price+regime GRID_NEUTRAL score went with *worse* "
                   "forward grid conditions on this sample — the score points the "
                   "wrong way once live inputs (funding/OI/flow/CVD) are removed. "
                   "This says the price+regime weighting is mis-balanced, OR the "
                   "live-only signals carry the real grid edge. A full live-data "
                   "run is needed before re-weighting; do NOT trust the price-only "
                   "GRID_NEUTRAL score as-is.")
    elif gn is not None and abs(gn - 0.5) < 0.05:
        out.append("- **GRID_NEUTRAL score ≈ coin-flip** at predicting good grid "
                   "windows (with live inputs neutralised). Either the "
                   "price+regime weights are mis-balanced, or the live-only "
                   "signals (funding/OI/flow/CVD) carry most of the real grid "
                   "edge — a full live-data run is needed to tell which.")
    if dr is not None and dr < 0.45:
        out.append("- **DIRECTIONAL score is inverted** vs forward move on this "
                   "sample — worth checking the ADX/ER/Hurst directional "
                   "normalisations.")
    if not out:
        out.append("- No strong mis-set signal detected on this bounded sample. "
                   "Re-run across more pairs/history before drawing conclusions.")
    return "\n".join(out)


def _proposed_diff(sep: dict) -> str:
    """Emit commented suggestions keyed off what the sample showed. Conservative
    by design: only nudges, always labelled, never auto-applied."""
    lines = ['CFG["REGIME"] = {']
    er_r = sep.get("er_vs_trendiness")
    if er_r is not None and er_r > 0.1:
        lines.append('    "ER_PERIOD": 10,    # KEEP — ER sign matches forward trendiness')
    elif er_r is not None and er_r < -0.25:
        lines.append('    "ER_PERIOD": 10,    # DO NOT just lengthen — ER was '
                     'STRONGLY INVERTED here.')
        lines.append('    #   The ER->grid RULE DIRECTION is the suspect, not the '
                     'period. High ER')
        lines.append('    #   predicted LESS forward trend on this sample. REVIEW '
                     'regime.py')
        lines.append('    #   calc_efficiency_ratio grid_signal mapping before any '
                     'live use.')
    else:
        lines.append('    "ER_PERIOD": 14,    # SUGGEST ↑ from 10 — ER showed weak '
                     'forward link; longer lookback may de-noise (REVIEW)')
    rg = sep.get("ranging_grid_quality", {})
    ranging, trending = rg.get("RANGING"), rg.get("TRENDING")
    if ranging and trending and ranging["mean"] >= trending["mean"]:
        lines.append('    # ER regime cut points (in regime.py calc_efficiency_ratio):')
        lines.append('    #   RANGING<0.3 / TRENDING>=0.6 did NOT separate — '
                     'SUGGEST testing 0.25 / 0.55 (REVIEW)')
    else:
        lines.append('    # ER regime cut points 0.3 / 0.6 look usable on this sample — KEEP')
    lines.append('    "HURST_WINDOW": 90, # KEEP — insufficient evidence to move')
    lines.append("}")
    lines.append("")
    gn = sep.get("grid_neutral_auc")
    if gn is not None and gn < 0.35:
        lines.append(f'# CFG["MATRIX"]["WEIGHTS"] — GRID_NEUTRAL was ANTI-PREDICTIVE '
                     f'(AUC={gn:.2f}) on')
        lines.append('# price+regime inputs alone: a higher score went with WORSE '
                     'grid windows.')
        lines.append('# This is a flag that the price+regime weighting may be '
                     'backwards/mis-set,')
        lines.append('# OR that the live-only signals carry the edge. Do a FULL '
                     'live-data pass')
        lines.append('# before re-weighting. NO weight change proposed from '
                     'price-only data.')
    elif gn is not None and abs(gn - 0.5) < 0.05:
        lines.append('# CFG["MATRIX"]["WEIGHTS"] — GRID_NEUTRAL price+regime weights')
        lines.append('# did not separate good grid windows on their own. Before '
                     're-weighting,')
        lines.append('# run a FULL live-data pass (funding/OI/flow/CVD present) to '
                     'attribute')
        lines.append('# the edge correctly. NO weight change proposed from price-only data.')
    else:
        lines.append('# CFG["MATRIX"]["WEIGHTS"]: GRID_NEUTRAL price+regime weights '
                     'showed')
        lines.append('# usable separation — no change proposed pending full live run.')
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────
def run(pairs: list[str], horizon: int, max_steps: int, use_network: bool) -> dict:
    """Drive the walk across pairs and write the report. Returns the separation
    summary (handy for tests / programmatic callers)."""
    all_feats: list[dict] = []
    all_outs: list[dict] = []
    per_pair: dict[str, int] = {}
    for sym in pairs:
        feats, outs = walk_pair(sym, horizon, max_steps, use_network)
        per_pair[sym] = len(feats)
        all_feats.extend(feats)
        all_outs.extend(outs)

    sep = F.summarize_separation(all_feats, all_outs)
    meta = {
        "mode": "live+cache" if use_network else "cache-only",
        "generated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "pairs": pairs,
        "horizon": horizon,
        "max_steps": max_steps,
    }
    report = render_report(sep, per_pair, meta)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report)
    log.info("wrote %s (%d walk steps across %d pairs)",
             REPORT_PATH, sep["n_steps"], len(pairs))
    return sep


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Offline regime/matrix calibration signal check.")
    p.add_argument("--pairs", default=",".join(DEFAULT_PAIR_SAMPLE),
                   help="comma-separated pairs (default: small sample)")
    p.add_argument("--all-pairs", action="store_true",
                   help=f"use all DEFAULT_PAIRS ({len(DEFAULT_PAIRS)})")
    p.add_argument("--horizon", type=int, default=HORIZON_DAYS)
    p.add_argument("--max-steps", type=int, default=MAX_STEPS)
    p.add_argument("--no-network", action="store_true",
                   help="use only cached klines; skip pairs that are uncached")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level="INFO", format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)
    pairs = DEFAULT_PAIRS if args.all_pairs else [s.strip() for s in args.pairs.split(",") if s.strip()]
    sep = run(pairs, args.horizon, args.max_steps, use_network=not args.no_network)
    if sep["n_steps"] == 0:
        log.warning("no walk steps produced — report written with empty results "
                    "(check cache / network)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
