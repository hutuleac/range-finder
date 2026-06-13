"""Pure, network-free helpers for the offline calibration harness.

No I/O, no global state, no live config mutation. Every function here is
deterministic given its inputs, which makes the whole signal-check unit-testable
on synthetic data (see tests/test_calibration.py).

Three groups:

  1. Forward outcomes  — what actually happened in the next N bars (the labels
     a signal is judged against). Computed ONLY from bars strictly after the
     decision index, so there is no lookahead leakage.

  2. Feature reconstruction — replays the regime layer (and the price-derived
     slice of the matrix) "as of" a historical index, feeding build_regime /
     calc_matrix only the data visible at that point.

  3. Separation metrics — simple, honest numpy-only statistics (Pearson r,
     group means, rank-AUC) that answer: does the signal separate the forward
     outcome? No scipy/sklearn.

Honesty note carried in code, not just prose: the matrix consumes live-only
inputs (funding, OI, flow, CVD) that cannot be reconstructed from historical
OHLCV. reconstruct_features holds those at their neutral default so the matrix
columns we report are price+regime driven only. The report labels this loudly.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

# Live-only metric keys that cannot be rebuilt from historical OHLCV. Held at
# neutral so the matrix score we report reflects price+regime structure only.
LIVE_ONLY_NEUTRAL: dict[str, float] = {
    "funding": 0.0,
    "oiChange": 0.0,
    "flow": 0.0,
    "cvd5d": 0.0,
    "cvd14d": 0.0,
    "cvd30d": 0.0,
}


# ─────────────────────────────────────────────────────────────────────
#  1. Forward outcomes (labels) — strictly look-ahead-free
# ─────────────────────────────────────────────────────────────────────
def forward_abs_return(closes: list[float], idx: int, horizon: int) -> float | None:
    """|close[idx+horizon] / close[idx] - 1|, in fraction (0.05 = 5%).

    Uses only bars AFTER idx. Returns None if the horizon runs off the series."""
    closes = list(closes)
    j = idx + horizon
    if idx < 0 or j >= len(closes) or closes[idx] == 0:
        return None
    return abs(closes[j] / closes[idx] - 1.0)


def forward_realized_vol(closes: list[float], idx: int, horizon: int) -> float | None:
    """Std of the next `horizon` log-returns (bars idx+1..idx+horizon).

    A volatility label — high = the next window was choppy/violent. Look-ahead
    free: never touches closes[idx] in a way that peeks past idx for the label
    window (returns are computed on the forward slice only)."""
    closes = list(closes)
    j = idx + horizon
    if idx < 0 or j >= len(closes):
        return None
    window = np.asarray(closes[idx:j + 1], dtype=float)  # idx..idx+h inclusive
    if np.any(window <= 0):
        return None
    rets = np.diff(np.log(window))  # horizon returns, all strictly after idx
    return float(np.std(rets, ddof=0)) if len(rets) else None


def forward_trendiness(closes: list[float], idx: int, horizon: int) -> float | None:
    """Efficiency-Ratio-style trendiness of the NEXT `horizon` bars.

    net displacement / summed path over bars idx..idx+horizon → 0..1.
    1.0 = clean one-way move (bad for grids); 0.0 = pure chop (ideal for grids).
    This is the grid-suitability proxy: low forward trendiness == good grid
    conditions. Look-ahead free (forward slice only)."""
    closes = list(closes)
    j = idx + horizon
    if idx < 0 or j >= len(closes):
        return None
    c = np.asarray(closes[idx:j + 1], dtype=float)
    net = abs(c[-1] - c[0])
    path = float(np.sum(np.abs(np.diff(c))))
    if path <= 0:
        return None
    return float(net / path)


# ─────────────────────────────────────────────────────────────────────
#  2. Feature reconstruction "as of" a historical index
# ─────────────────────────────────────────────────────────────────────
def _slice_4h_for_daily(df_4h: pd.DataFrame, daily_time_ms: int) -> pd.DataFrame:
    """Return the 4H rows at or before a daily bar's timestamp (no future rows).

    df_4h must carry a 'Time' column in epoch-ms (parse_klines shape). When Time
    is absent (synthetic frames in tests) we fall back to the whole frame, which
    is acceptable because tests drive reconstruction with explicit small frames."""
    if "Time" not in df_4h.columns or df_4h.empty:
        return df_4h
    return df_4h[df_4h["Time"] <= daily_time_ms]


def reconstruct_regime(
    daily_closes: list[float],
    df_4h: pd.DataFrame,
    idx: int,
    daily_time_ms: int | None,
    build_regime: Callable,
) -> dict:
    """Replay build_regime as it would have run at daily index `idx`.

    Feeds it ONLY daily_closes[:idx+1] and the 4H rows at/<= the daily bar's
    timestamp. Pulls out the flat, comparable regime features.
    """
    visible_daily = list(daily_closes[: idx + 1])
    if daily_time_ms is not None:
        visible_4h = _slice_4h_for_daily(df_4h, daily_time_ms)
    else:
        visible_4h = df_4h
    regime = build_regime({"dailyCloses": visible_daily}, visible_4h)
    er = regime.get("er") or {}
    hurst = regime.get("hurst") or {}
    conf = regime.get("confirmation") or {}
    adx = regime.get("adxSlope") or {}
    return {
        "er_value": er.get("er_value"),
        "er_regime": er.get("er_regime", "UNKNOWN"),
        "hurst": hurst.get("hurst_daily"),
        "hurst_regime": hurst.get("regime", "UNKNOWN"),
        "trend_daily": regime.get("trendDaily", "Neutral"),
        "combined_regime": conf.get("combined_regime", "UNKNOWN"),
        "conviction": conf.get("conviction", "UNKNOWN"),
        "adx_slope": adx.get("adx_slope", "FLAT"),
        "_regime": regime,  # raw, for matrix reconstruction
    }


def reconstruct_price_metrics(
    df_4h_visible: pd.DataFrame,
    calc_rsi: Callable,
    calc_atr: Callable,
    calc_atr_pct: Callable,
    calc_adx: Callable,
    calc_bb: Callable,
    calc_market_structure: Callable,
    struct_lookback: int = 20,
) -> dict:
    """Rebuild the price-derived slice of the metrics dict from a 4H window.

    Only the OHLCV-derivable metrics the matrix actually reads: adx, bbBw,
    atrPct, rsi, structure4h. Live-only fields (funding/OI/flow/CVD) are added
    by reconstruct_matrix_scores at their neutral default. Callables are injected
    so this stays pure and unit-testable with stubs."""
    if df_4h_visible is None or df_4h_visible.empty:
        return {"adx": {"adx": 0.0}, "bbBw": 0.0, "atrPct": 0.0,
                "rsi": 50.0, "structure4h": "Neutral"}
    last_close = float(df_4h_visible["Close"].iloc[-1])
    atr = calc_atr(df_4h_visible)
    return {
        "adx": calc_adx(df_4h_visible),
        "bbBw": calc_bb(df_4h_visible)["bw"],
        "atrPct": calc_atr_pct(atr, last_close),
        "rsi": calc_rsi(df_4h_visible),
        "structure4h": calc_market_structure(df_4h_visible, struct_lookback),
    }


def reconstruct_matrix_scores(
    metrics_price: dict,
    regime: dict,
    calc_matrix: Callable,
) -> dict[str, float]:
    """Run calc_matrix with live-only inputs held neutral.

    metrics_price carries the price-derived metrics reconstructable from OHLCV
    (adx, bbBw, atrPct, rsi, structure4h). We overlay LIVE_ONLY_NEUTRAL so the
    matrix's funding/OI/flow/CVD terms contribute their neutral 0.5 — the
    reported scores are therefore price+regime driven only (flagged in report).
    """
    metrics = {**LIVE_ONLY_NEUTRAL, **metrics_price}
    out = calc_matrix(metrics, regime)
    return dict(out.get("scores", {}))


# ─────────────────────────────────────────────────────────────────────
#  3. Separation metrics — numpy-only, simple and honest
# ─────────────────────────────────────────────────────────────────────
def _clean_pairs(x: list, y: list) -> tuple[np.ndarray, np.ndarray]:
    xs, ys = [], []
    for a, b in zip(x, y):
        if a is None or b is None:
            continue
        a = float(a)
        b = float(b)
        if np.isnan(a) or np.isnan(b):
            continue
        xs.append(a)
        ys.append(b)
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


def pearson_r(x: list, y: list) -> float | None:
    """Pearson correlation of two aligned series, None-tolerant.

    Returns None when fewer than 3 valid pairs or a series is constant."""
    xs, ys = _clean_pairs(x, y)
    if len(xs) < 3 or np.std(xs) == 0 or np.std(ys) == 0:
        return None
    return float(np.corrcoef(xs, ys)[0, 1])


def group_means(labels: list, values: list) -> dict[str, dict]:
    """Mean/median/count of `values` grouped by categorical `labels`.

    Skips pairs with a None value. Returns {label: {mean, median, n}}."""
    groups: dict[str, list[float]] = {}
    for lab, val in zip(labels, values):
        if val is None:
            continue
        v = float(val)
        if np.isnan(v):
            continue
        groups.setdefault(str(lab), []).append(v)
    return {
        lab: {
            "mean": float(np.mean(vs)),
            "median": float(np.median(vs)),
            "n": len(vs),
        }
        for lab, vs in groups.items()
    }


def rank_auc(scores: list, positive: list) -> float | None:
    """AUC via the Mann-Whitney U statistic — does a higher score predict the
    positive class? AUC = U / (n_pos * n_neg).

    `positive` is a 0/1 (or bool) label aligned with `scores`. 0.5 = no
    separation; >0.5 = higher score → positive; <0.5 = inverted. Ties get the
    standard 0.5 credit (average-rank formulation). None when a class is empty."""
    pairs = [
        (float(s), 1 if bool(p) else 0)
        for s, p in zip(scores, positive)
        if s is not None and not (isinstance(s, float) and np.isnan(s))
    ]
    if not pairs:
        return None
    s_arr = np.asarray([p[0] for p in pairs], dtype=float)
    y_arr = np.asarray([p[1] for p in pairs], dtype=int)
    n_pos = int(np.sum(y_arr == 1))
    n_neg = int(np.sum(y_arr == 0))
    if n_pos == 0 or n_neg == 0:
        return None
    # Average ranks (1-based) handle ties correctly.
    order = np.argsort(s_arr, kind="mergesort")
    ranks = np.empty(len(s_arr), dtype=float)
    sorted_s = s_arr[order]
    i = 0
    while i < len(sorted_s):
        j = i
        while j + 1 < len(sorted_s) and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-based average of the tie block
        ranks[order[i:j + 1]] = avg_rank
        i = j + 1
    sum_ranks_pos = float(np.sum(ranks[y_arr == 1]))
    u_pos = sum_ranks_pos - n_pos * (n_pos + 1) / 2.0
    return float(u_pos / (n_pos * n_neg))


def median_split_label(values: list[float]) -> list[int]:
    """Binary label: 1 if value > median, else 0. Used to turn a continuous
    forward outcome into a positive class for rank_auc. None values map to 0
    and should be filtered upstream by passing only valid rows."""
    vals = np.asarray([v for v in values if v is not None], dtype=float)
    if len(vals) == 0:
        return [0 for _ in values]
    med = float(np.median(vals))
    return [1 if (v is not None and float(v) > med) else 0 for v in values]


def summarize_separation(
    feature_rows: list[dict],
    outcome_rows: list[dict],
) -> dict:
    """Assemble the headline separation table from aligned feature/outcome rows.

    feature_rows[i] and outcome_rows[i] describe the SAME walk step. Returns a
    dict of the comparisons the report cares about:

      - er_vs_trendiness       (Pearson r): high ER should predict high forward
                               trendiness (the whole premise of ER).
      - hurst_vs_trendiness    (Pearson r): high Hurst → more persistence.
      - ranging_grid_quality   (group means of forward trendiness by er_regime):
                               RANGING should show LOWER forward trendiness.
      - grid_neutral_auc       (rank-AUC): does a high GRID_NEUTRAL score predict
                               LOW forward trendiness (good grid window)?
      - directional_auc        (rank-AUC): does a high DIRECTIONAL score predict
                               HIGH forward abs return?
    """
    er = [r.get("er_value") for r in feature_rows]
    hurst = [r.get("hurst") for r in feature_rows]
    er_regime = [r.get("er_regime") for r in feature_rows]
    gn = [r.get("grid_neutral") for r in feature_rows]
    dr = [r.get("directional") for r in feature_rows]

    f_trend = [o.get("fwd_trendiness") for o in outcome_rows]
    f_absret = [o.get("fwd_abs_return") for o in outcome_rows]

    # AUC needs a binary class. Low trendiness = good grid window → positive
    # class is "below median trendiness" (so we invert the label).
    valid_trend = [(g, t) for g, t in zip(gn, f_trend) if g is not None and t is not None]
    if valid_trend:
        g_scores = [g for g, _ in valid_trend]
        t_vals = [t for _, t in valid_trend]
        low_trend_pos = [1 - p for p in median_split_label(t_vals)]
        grid_neutral_auc = rank_auc(g_scores, low_trend_pos)
    else:
        grid_neutral_auc = None

    valid_dir = [(d, a) for d, a in zip(dr, f_absret) if d is not None and a is not None]
    if valid_dir:
        d_scores = [d for d, _ in valid_dir]
        a_vals = [a for _, a in valid_dir]
        high_ret_pos = median_split_label(a_vals)
        directional_auc = rank_auc(d_scores, high_ret_pos)
    else:
        directional_auc = None

    return {
        "n_steps": len(feature_rows),
        "er_vs_trendiness": pearson_r(er, f_trend),
        "hurst_vs_trendiness": pearson_r(hurst, f_trend),
        "ranging_grid_quality": group_means(er_regime, f_trend),
        "grid_neutral_auc": grid_neutral_auc,
        "directional_auc": directional_auc,
    }
