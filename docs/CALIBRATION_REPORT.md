# Range Finder — Regime & Matrix Calibration Report

> **Status: suggestions pending review — NOT validated for live use.**  
> This is an offline *signal check*, not a trading backtest. All proposed values below are derived from a small, bounded historical sample and must be reviewed before any config change.

## Methodology

- **Run mode:** cache-only · generated 2026-06-13 21:25:20 UTC
- **Pairs:** BTC/USDT, ETH/USDT, SOL/USDT
- **Forward horizon:** 5 daily bars · **max steps/pair:** 30 · **total walk steps:** 60
- For each daily index `t` (after a 95-bar warm-up for Hurst+ER), we reconstruct `build_regime` and the price-derived slice of `calc_matrix` using ONLY data ≤ `t` (no lookahead), then measure forward outcomes over bars `t+1..t+N`.
- **Forward outcomes:** *trendiness* (ER-style net/path of the next N bars; low = good grid window), *abs return*, *realized vol*.
- **Stats are numpy-only:** Pearson r, group means, rank-AUC (Mann-Whitney U). No scipy/sklearn.

> **Honesty caveat — matrix inputs.** `calc_matrix` consumes live-only signals (funding, OI change, flow, CVD) that CANNOT be reconstructed from historical OHLCV. They are held at their neutral default during this replay, so the reported GRID_NEUTRAL / DIRECTIONAL scores reflect the **price + regime** structure only. Treat matrix findings as a partial check; the regime layer (ER × Hurst) is the fully-reconstructable, primary target.

## Per-signal separation results

### 1. Regime layer (fully reconstructable — primary)

| Signal | Statistic | Value | Expectation | Verdict |
|---|---|---|---|---|
| ER vs forward trendiness | Pearson r | -0.628 | positive (high ER → trends) | WRONG sign vs heuristic |
| Hurst vs forward trendiness | Pearson r | -0.097 | positive (high H → persistence) | NO correlation |

**ER regime → forward trendiness (group means).** RANGING should show the LOWEST forward trendiness if the regime split is real:

| ER regime | mean fwd trendiness | median | n |
|---|---|---|---|
| RANGING | 0.741 | 0.803 | 7 |
| TRANSITIONAL | 0.697 | 0.797 | 32 |
| TRENDING | 0.272 | 0.305 | 21 |

### 2. Matrix scores (price+regime only — partial)

| Signal | Statistic | Value | Expectation | Verdict |
|---|---|---|---|---|
| GRID_NEUTRAL → low fwd trendiness | rank-AUC | 0.158 | >0.5 | INVERTED (signal points the wrong way) |
| DIRECTIONAL → high fwd abs return | rank-AUC | 0.599 | >0.5 | separates |

### Per-pair step counts

| Pair | walk steps |
|---|---|
| BTC/USDT | 20 |
| ETH/USDT | 20 |
| SOL/USDT | 20 |

## Which heuristics look mis-set

- **ER is STRONGLY INVERTED (r=-0.63) on this sample.** High trailing efficiency was followed by *less* directional movement, not more — consistent with mean-reversion after a completed move. If this holds on a larger run, the ER→grid rule may have the sign backwards: high ER could be a grid ENTRY cue, not an avoid cue. Lengthening ER_PERIOD will NOT fix a sign flip — investigate the rule direction itself.
- **RANGING vs TRENDING separation absent/inverted:** RANGING did NOT predict calmer forward bars on this sample. The ER regime cut points are the prime suspect.
- **GRID_NEUTRAL score is ANTI-PREDICTIVE (AUC=0.16).** A *higher* price+regime GRID_NEUTRAL score went with *worse* forward grid conditions on this sample — the score points the wrong way once live inputs (funding/OI/flow/CVD) are removed. This says the price+regime weighting is mis-balanced, OR the live-only signals carry the real grid edge. A full live-data run is needed before re-weighting; do NOT trust the price-only GRID_NEUTRAL score as-is.

## Proposed config diff (NOT applied)

```python
# calibration/run.py output — suggestions pending review, NOT validated for live use.
# Apply by hand to config.py ONLY after a larger multi-pair run confirms the direction holds.
CFG["REGIME"] = {
    "ER_PERIOD": 10,    # DO NOT just lengthen — ER was STRONGLY INVERTED here.
    #   The ER->grid RULE DIRECTION is the suspect, not the period. High ER
    #   predicted LESS forward trend on this sample. REVIEW regime.py
    #   calc_efficiency_ratio grid_signal mapping before any live use.
    # ER regime cut points (in regime.py calc_efficiency_ratio):
    #   RANGING<0.3 / TRENDING>=0.6 did NOT separate — SUGGEST testing 0.25 / 0.55 (REVIEW)
    "HURST_WINDOW": 90, # KEEP — insufficient evidence to move
}

# CFG["MATRIX"]["WEIGHTS"] — GRID_NEUTRAL was ANTI-PREDICTIVE (AUC=0.16) on
# price+regime inputs alone: a higher score went with WORSE grid windows.
# This is a flag that the price+regime weighting may be backwards/mis-set,
# OR that the live-only signals carry the edge. Do a FULL live-data pass
# before re-weighting. NO weight change proposed from price-only data.
```

## Caveats

- Small bounded sample (few pairs, capped steps) — directional hint only, not statistical proof.
- **Overlapping windows → autocorrelated steps.** Consecutive walk steps share 4 of 5 forward bars, so the 60 steps are NOT independent — effective sample size is much smaller. Read every r/AUC as a flag to investigate on a larger, non-overlapping run, not as a result.
- Matrix live-only inputs held neutral (see honesty caveat) — matrix findings are partial.
- Forward trendiness is a *proxy* for grid suitability, not realized grid P&L. A true validation would simulate grid fills.
- No multiple-testing correction; treat any single r/AUC as a flag to investigate, not a conclusion.
